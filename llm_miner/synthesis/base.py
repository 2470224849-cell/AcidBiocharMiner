import json
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

from llm_miner.synthesis.prompt import PROMPT_TYPE, PROMPT_STRUCT, FT_TYPE, FT_HUMAN
from llm_miner.schema import Paragraph
from llm_miner.error import StructuredFormatError, LangchainError, TokenLimitError
from llm_miner.format import Formatter
from llm_miner.pricing import TokenChecker, update_token_checker
from llm_miner.utils import num_tokens_from_string
from llm_miner.config import config
from llm_miner.parse_utils import parse_structured_output
from llm_miner.llm_compat import run_chain_with_optional_stop


class SynthesisMiningAgent(Chain):
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
        run_manager.on_text(f"\n[Synthesis Mining] ", verbose=self.verbose)
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
        if isinstance(output, dict):
            try:
                return json.dumps(output, ensure_ascii=False)
            except Exception:
                return str(output)
        return str(output)

    def _parse_output(self, output: Any) -> List[Any]:
        output = self._coerce_output_text(output)
        if regex.search(r"^\s*(```)?json", output, flags=regex.IGNORECASE) and not regex.search(
            r"```\s*$", output
        ):
            raise TokenLimitError(
                "Output does not finished before token limits", output
            )

        output = output.replace("```JSON", "")
        output = output.replace("```", "")
        output = output.strip()

        if regex.search(r"[Ii] do not know", output):
            return [output]
        try:
            data = parse_structured_output(output)
            if isinstance(data, list):
                return data
            else:
                return [data]
        except Exception as e:
            raise StructuredFormatError(e, output)

    def _normalize_synthesis_types(self, raw: Any) -> List[str]:
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
            norm = item.strip().lower().replace("-", "_").replace(" ", "_")
            if not norm or norm in {"none", "empty"}:
                continue
            if norm not in seen:
                seen.add(norm)
                out.append(norm)
        return out

    def reconstruct_paragraph(
        self, content: str, max_token: int, sep: str = "\n"
    ) -> List[str]:
        ls_para = []
        ls_content = content.split(sep)
        tmp_para = ls_content[0]
        tmp_token = 0

        for para in ls_content[1:]:
            if not para.strip():
                continue
            n_token = num_tokens_from_string(para, self.type_chain.llm.model_name)
            tmp_token += n_token
            if tmp_token > max_token:
                ls_para.append(tmp_para)
                tmp_para = para
                tmp_token = n_token
            else:
                tmp_para += sep + para
        ls_para.append(tmp_para)

        return ls_para

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        callbacks = _run_manager.get_child()

        element: Paragraph = inputs[self.input_key]
        token_checker: TokenChecker = inputs.get("token_checker")
        element.clear()

        max_token_type: int = config["input_max_token_synthesis_type"]
        synthesis_type: list = []

        for paragraph in self.reconstruct_paragraph(element.clean_text, max_token_type):
            llm_kwargs = {
                "paragraph": paragraph,
            }
            try:
                llm_output = run_chain_with_optional_stop(
                    self.type_chain,
                    **llm_kwargs,
                    callbacks=callbacks,
                    stop=["Paragraph:"],
                )
            except Exception as e:
                element.add_intermediate_step("text-synthesis-type", str(e))
                raise LangchainError(e)
            else:
                element.add_intermediate_step("text-synthesis-type", llm_output)

            if token_checker:
                update_token_checker(
                    name_step="text-synthesis-type",
                    chain=self.type_chain,
                    token_checker=token_checker,
                    llm_kwargs=llm_kwargs,
                    llm_output=llm_output,
                )
            synthesis_type.extend(self._normalize_synthesis_types(self._parse_output(llm_output)))
        synthesis_type = list(dict.fromkeys(synthesis_type))
        self._write_log(str(synthesis_type), _run_manager)
        element.set_include_properties(synthesis_type)

        if not synthesis_type:
            self._write_log(f"There are no synthesis type", _run_manager)
            return {"output": ["No synthesis type found"]}

        prop_string = ""
        for prop in synthesis_type:
            try:
                structure = Formatter.operation[prop]
            except KeyError:
                self._write_log(
                    f"There are no operation information for {prop}", _run_manager
                )
                continue
            prop_string += f"- {structure}\n"

        llm_kwargs = {
            "paragraph": element.clean_text,
            "synthesis_type": synthesis_type,
            "format": prop_string,
        }
        try:
            llm_output = run_chain_with_optional_stop(
                self.extract_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=["Paragraph:"],
            )
        except Exception as e:
            element.add_intermediate_step("text-synthesis-struct", str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step("text-synthesis-struct", llm_output)

        if token_checker:
            update_token_checker(
                name_step="text-synthesis-struct",
                chain=self.extract_chain,
                token_checker=token_checker,
                llm_kwargs=llm_kwargs,
                llm_output=llm_output,
            )

        output = self._parse_output(llm_output)
        self._write_log(json.dumps(output), _run_manager)
        element.set_data(output)

        return {"output": output}

    @classmethod
    def from_llm(
        cls,
        type_llm: BaseLanguageModel,
        extract_llm: BaseLanguageModel,
        *,
        prompt_type: str = PROMPT_TYPE,
        prompt_extract: str = PROMPT_STRUCT,
        ft_type: str = FT_TYPE,
        ft_human: str = FT_HUMAN,
        **kwargs,
    ) -> Chain:
        if type_llm.model_name.startswith("ft:"):  # fine-tuned model
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
                input_variables=["paragraph"],
                partial_variables={
                    "list_operation": str(Formatter.operation.list_keys())
                },
            )
            type_chain = LLMChain(llm=type_llm, prompt=template_type)

        if extract_llm.model_name.startswith("ft:"):  # fine-tuned model
            raise NotImplementedError(
                "Fine-tuning model for extract is not implemented."
            )
        else:
            template_extract = PromptTemplate(
                template=prompt_extract,
                input_variables=["synthesis_type", "paragraph", "format"],
            )
            extract_chain = LLMChain(llm=extract_llm, prompt=template_extract)

        return cls(type_chain=type_chain, extract_chain=extract_chain, **kwargs)
