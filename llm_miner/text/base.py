import regex
from typing import Any, Dict, List, Optional

from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.chains.llm import LLMChain
from langchain.prompts import PromptTemplate
from langchain.callbacks.manager import CallbackManagerForChainRun
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

from llm_miner.text.prompt import PROMPT_TYPE, PROMPT_EXT, FT_TYPE, FT_HUMAN
from llm_miner.schema import Paragraph
from llm_miner.format import Formatter
from llm_miner.error import StructuredFormatError, LangchainError, TokenLimitError
from llm_miner.pricing import TokenChecker, update_token_checker
from llm_miner.parse_utils import parse_structured_output
from llm_miner.llm_compat import run_chain_with_optional_stop


class TextMiningAgent(Chain):
    type_chain: LLMChain
    extract_chain: LLMChain
    input_key: str = "element"
    output_key: str = "output"

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]
    
    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]
    
    def _write_log(self, text: str, run_manager):
        run_manager.on_text(f"\n[Property Mining] ", verbose=self.verbose)
        run_manager.on_text(text, verbose=self.verbose, color="yellow")

    @staticmethod
    def _coerce_output_text(output: Any) -> str:
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            if not output:
                return ""
            first = output[0]
            return first if isinstance(first, str) else str(first)
        return str(output)

    def _parse_output(self, output: Any) -> Dict[str, str]:
        output = self._coerce_output_text(output)
        if regex.search(r"^\s*```json", output, flags=regex.IGNORECASE) and not regex.search(r"```\s*$", output):
            raise TokenLimitError('Output does not finished before token limits', output)

        if regex.search(r"[Ii] do not know", output):
            return [output]
        try:
            return parse_structured_output(output)
        except Exception as e:
            raise StructuredFormatError(e, output)

    def _normalize_props(self, raw: Any) -> List[str]:
        alias = {
            "biochar modification": "biochar_modification",
            "adsorption experiment": "adsorption_experiment",
        }

        def walk(x: Any):
            if x is None:
                return
            if isinstance(x, str):
                s = x.strip()
                if s:
                    yield s
                return
            if isinstance(x, dict):
                for k in x.keys():
                    yield from walk(k)
                for v in x.values():
                    yield from walk(v)
                return
            if isinstance(x, (list, tuple, set)):
                for y in x:
                    yield from walk(y)
                return
            yield str(x).strip()

        out: List[str] = []
        seen = set()
        for item in walk(raw):
            norm = " ".join(item.split()).lower()
            norm = alias.get(norm, norm)
            norm = norm.replace("-", "_").replace(" ", "_")
            if not norm or norm in {"none", "empty", "no_properties", "no_property"}:
                continue
            if norm not in seen:
                seen.add(norm)
                out.append(norm)
        return out

    def _infer_boost_props(self, paragraph: str) -> List[str]:
        s = (paragraph or "").lower()
        has_num = bool(regex.search(r"\d", s))
        if not has_num:
            return []
        props: List[str] = []
        if any(k in s for k in ["biochar", "pyrolysis", "acid", "hcl", "hno3", "h2so4", "h3po4"]):
            props.append("biochar_modification")
        if any(
            k in s
            for k in [
                "adsorption",
                "qe",
                "c0",
                "cd",
                "pb",
                "cr(vi)",
                "ni(ii)",
                "co(ii)",
                "cu(ii)",
            ]
        ):
            props.append("adsorption_experiment")
        return props
    
    def _call(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        callbacks = _run_manager.get_child()

        explanation = self._add_explanation()
        element: Paragraph = inputs[self.input_key]
        token_checker: TokenChecker = inputs.get('token_checker')
        paragraph: str = element.clean_text   # change content -> clean_text

        llm_kwargs = {
            'explanation': explanation,
            'paragraph': paragraph,
        }
        try:
            llm_output = run_chain_with_optional_stop(
                self.type_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=["Paragraph:"],
            )
        except Exception as e:
            element.add_intermediate_step('text-property-type', str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step('text-property-type', llm_output)

        if token_checker:
            update_token_checker(
                name_step='text-property-type',
                chain=self.type_chain,
                token_checker=token_checker, 
                llm_kwargs=llm_kwargs, 
                llm_output=llm_output
            )

        property_type = self._normalize_props(self._parse_output(llm_output))
        if not property_type:
            property_type = self._infer_boost_props(paragraph)
        self._write_log(str(property_type), _run_manager)
        element.set_include_properties(property_type)

        st_data_string = ""
        info_string = ""
        example_string = ""
        prop_string = ""

        for prop in property_type:
            try:
                st_data = Formatter.structured_data[prop]
                info = Formatter.information[prop]
                example = Formatter.example_text[prop]
            except KeyError:
                self._write_log(f"There are no format for {prop}", _run_manager)
                continue

            st_data_string += f"- {st_data}\n"
            info_string += f"- {info}\n"
            example_string += f"- {example}\n"
            prop_string += f"{prop}, "

        if not prop_string.strip():
            element.set_data(["No properties found"])
            return {"output": ["No properties found"]}

        llm_kwargs={
            'prop': prop_string,
            'structured_data': st_data_string,
            'information': info_string,
            'example': example_string,
            'paragraph': paragraph,
        }
        try:
          llm_output = run_chain_with_optional_stop(
              self.extract_chain,
              **llm_kwargs,
              callbacks=callbacks,
              stop=["Paragraph:"],
          )
        except Exception as e:
            element.add_intermediate_step('text-property-extract', str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step('text-property-extract', llm_output)
            
        if token_checker:
            update_token_checker(
                name_step='text-property-extract',
                chain=self.extract_chain,
                token_checker=token_checker, 
                llm_kwargs=llm_kwargs, 
                llm_output=llm_output
            )

        st_output = self._parse_output(llm_output)
        self._write_log(f"{st_output}", _run_manager)

        element.set_data([st_output])
        return {"output": st_output}
    
    def _add_explanation(self,) -> str:
        erase_list = [
            "cell_volume",
            "conversion",
            "reaction_yield",
            "chemical_formula",
        ]
        formatter = Formatter
        target_items = list(formatter.explanation.keys())
        target_items = [item for item in target_items if item not in erase_list]
        explained_props = ""
        for item in target_items:
            explained_props += "\n" + f"- {item}: " + formatter.explanation[item].strip()
        return explained_props.strip()

    @classmethod
    def from_llm(
        cls,
        type_llm: BaseLanguageModel,
        extract_llm: BaseLanguageModel,
        *,
        prompt_type: str = PROMPT_TYPE,
        prompt_extract: str = PROMPT_EXT,
        ft_type: str = FT_TYPE,
        ft_human: str = FT_HUMAN,
        **kwargs,
    ) -> Chain:
        
        if type_llm.model_name.startswith('ft:'): # fine-tuned model
            system_prompt = SystemMessagePromptTemplate.from_template(ft_type)
            human_prompt = HumanMessagePromptTemplate.from_template(ft_human)
            chat_prompt = ChatPromptTemplate.from_messages(
                [system_prompt, human_prompt]
            )
            type_chain = LLMChain(
                llm=type_llm,
                prompt=chat_prompt,
            )
        else:
            template_type = PromptTemplate(
                template=prompt_type,
                input_variables=["explanation", "paragraph"],
            )
            type_chain = LLMChain(llm=type_llm, prompt=template_type)

        if extract_llm.model_name.startswith('ft:'): # fine-tuned model
            raise NotImplementedError('Fine-tuning model for extract is not implemented.')
        else:
            template_extract = PromptTemplate(
                template=prompt_extract,
                input_variables=["prop", "structured_data", "information", "example", "paragraph"],
            )
            extract_chain = LLMChain(llm=extract_llm, prompt=template_extract)

        return cls(
            type_chain=type_chain,
            extract_chain=extract_chain,
            **kwargs
        )
    
