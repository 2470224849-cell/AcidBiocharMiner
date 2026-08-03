from typing import Any, Dict, List, Optional
import random

from langchain.base_language import BaseLanguageModel
from langchain.callbacks.manager import CallbackManagerForChainRun
from langchain.chains.base import Chain
from langchain.chains.llm import LLMChain
from langchain.prompts import PromptTemplate
from langchain.prompts.chat import (
      ChatPromptTemplate,
      SystemMessagePromptTemplate,
      HumanMessagePromptTemplate,
)

from llm_miner.schema import Paragraph
from llm_miner.error import StructuredFormatError, LangchainError
from llm_miner.format import Formatter
from llm_miner.table.property.prompt import PROPERTY_CATEGORIZE, PROPERTY_EXTRACT, FT_TYPE, FT_HUMAN
from llm_miner.pricing import TokenChecker, update_token_checker
from llm_miner.parse_utils import parse_structured_output
from llm_miner.llm_compat import run_chain_with_optional_stop


class PropertyTableAgent(Chain):
    categorize_chain: LLMChain
    extract_chain: LLMChain
    input_key: str = "element"
    output_key: str = "output"
    included_props: list = []

    @classmethod
    def from_llm(
        cls,
        type_llm: BaseLanguageModel,
        extract_llm: BaseLanguageModel,
        *,
        prompt_categorize: str = PROPERTY_CATEGORIZE,
        prompt_extract: str = PROPERTY_EXTRACT,
        ft_type: str = FT_TYPE,
        ft_human: str = FT_HUMAN,
        **kwargs,
    ) -> Chain:
        if type_llm.model_name.startswith('ft:'):
            system_prompt = SystemMessagePromptTemplate.from_template(ft_type)
            human_prompt = HumanMessagePromptTemplate.from_template(ft_human)
            chat_prompt = ChatPromptTemplate.from_messages(
                [system_prompt, human_prompt]
            )
            categorize_chain = LLMChain(llm=type_llm, prompt=chat_prompt)
        else:
            template_categorize = PromptTemplate(
                template=prompt_categorize,
                template_format='jinja2',
                input_variables=['explanation', 'paragraph'],
            )
            categorize_chain = LLMChain(llm=type_llm, prompt=template_categorize)

        template_extract = PromptTemplate(
            template=prompt_extract,
            template_format="jinja2",
            input_variables=['prop', 'format', 'examples', 'paragraph'],
        )
        extract_chain = LLMChain(llm=extract_llm, prompt=template_extract)

        return cls(
            categorize_chain=categorize_chain,
            extract_chain=extract_chain,
            **kwargs
        )

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    def _write_log(self, text, run_manager):
        run_manager.on_text('\n[Included props] ', verbose=self.verbose)
        run_manager.on_text(text, verbose=self.verbose, color='yellow')

    def _call(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        callbacks = _run_manager.get_child()

        explanation = self._add_explanation()
        element: Paragraph = inputs[self.input_key]
        paragraph: str = element.clean_text
        token_checker: TokenChecker = inputs['token_checker']

        llm_kwargs={
            'explanation':explanation,
            'paragraph': paragraph,
        }
        try:
            included_props = run_chain_with_optional_stop(
                self.categorize_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=["Input:"],
            )
        except Exception as e:
            element.add_intermediate_step('table-property-type', str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step('table-property-type', included_props)

        if token_checker:
            update_token_checker(
                name_step='table-property-type',
                chain=self.categorize_chain,
                token_checker=token_checker,
                llm_kwargs=llm_kwargs,
                llm_output=included_props,
            )

        self.included_props = self._normalize_props(self._parse_output_props(included_props))
        if not self.included_props:
            self.included_props = self._infer_props_from_table_text(paragraph)
        self._write_log(str(self.included_props), _run_manager)

        props = self.included_props[:]

        if not props:
            self._write_log('There are no properties', _run_manager)
            return {"output": ["No properties found"]}

        format = self._make_format(props)
        examples = self._make_examples(props)

        llm_kwargs = {
            'prop': props,
            'format': format,
            'examples': examples,
            'paragraph': paragraph,
        }
        try:
            output = run_chain_with_optional_stop(
                self.extract_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=["Input:"],
            )
            # prompt = self.extract_chain.prompt.format_prompt(**llm_kwargs).to_string()
            # print(prompt)

        except Exception as e:
            element.add_intermediate_step('table-property-extract', str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step('table-property-extract', output)

        if token_checker:
            update_token_checker(
                name_step='table-property-extract',
                chain=self.extract_chain,
                token_checker=token_checker,
                llm_kwargs=llm_kwargs,
                llm_output=output,
            )

        output = self._parse_output_json(output)
        return {"output": output}

    def _add_explanation(self):
        erase_list = [
            "chemical_formula",
            "chemical_formula_weight",
            "refractive_index",
            "cell_volume",
            "lattice_parameters",
            "catalytic_activity",
            "crystal_system",
            "etc"

        ]
        formatter = Formatter
        target_items = list(formatter.explanation.keys())
        target_items = [item for item in target_items if item not in erase_list] + ["etc"]
        explained_props = ""
        for item in target_items:
            explained_props += "\n" + f"- {item}: " + formatter.explanation[item].strip()
        return explained_props.strip()

    def _parse_output_props(self, output: str) -> Dict[str, str]:
        try:
            list_ = parse_structured_output(output, strip_labels=("List",))
        except Exception as e:
            raise StructuredFormatError(e)
        else:
            return list_

    def _normalize_props(self, raw: Any) -> List[str]:
        """Normalize model output into a flat string list of property keys."""
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
            norm = "_".join(item.split()).lower()
            if not norm or norm in {"none", "empty", "no_properties", "no_property"}:
                continue
            if norm not in seen:
                seen.add(norm)
                out.append(norm)
        return out

    def _infer_props_from_table_text(self, paragraph: str) -> List[str]:
        s = (paragraph or "").lower()
        props: List[str] = []
        if any(
            k in s
            for k in ["biochar", "pyrolysis", "acid", "hcl", "hno3", "h2so4", "h3po4"]
        ):
            props.append("biochar_modification")
        if any(
            k in s
            for k in [
                "pollutant",
                "c0",
                "qe",
                "adsorption",
                "mg/l",
                "mg/g",
                "te_min",
                "slr",
                "cd",
                "pb",
                "cr(vi)",
            ]
        ):
            props.append("adsorption_experiment")
        return props

    def _parse_output_json(self, output: str) -> Dict[str, str]:
        if "llipsis" in output:
            return ["Ellipsis Error"]

        try:
            list_ = parse_structured_output(output, strip_labels=("Output",))
        except Exception as e:
            raise StructuredFormatError(e)
        else:
            return list_

    def _make_format(self, props):
        formatter = Formatter
        items = ["meta"]+props
        items = ["_".join(str(item).split(" ")) for item in items]

        formatted_props = ""
        for item in items:
            if item not in formatter.structured_data:
                continue
            item = '\n'.join(['    ' + line for line in formatter.structured_data[item].split('\n')])
            formatted_props += "\n"+item

        example = f"""Format: ```JSON
{{{formatted_props}
}}
```"""
        return example

    def _make_examples(self, props):
        formatter = Formatter
        included_in_examples = []
        choosen_examples = []

        for item in props:
            item = "_".join(str(item).split(" "))
            candidate_examples = []
            
            if item.replace("_", " ") in included_in_examples:
                continue
            
            for key, value in formatter.example_table.items():
                if key in choosen_examples:
                    continue
                
                if item.replace("_", " ") in value['contain']:
                    candidate_examples.append(key)
                    
            if candidate_examples:
                choosen = random.choice(candidate_examples)
                choosen_examples.append(choosen)
                included_in_examples += formatter.example_table[choosen]['contain']
                

        if len(choosen_examples) < 2:
            tmp = list(formatter.example_table.keys())[:]
            for exam in choosen_examples:
                tmp.remove(exam)
            extra = random.choice(tmp)
            choosen_examples.append(extra)
            included_in_examples += formatter.example_table[extra]['contain']

        included_in_examples = list(set(included_in_examples))           
        result = [formatter.example_table[item]['content'].strip() for item in choosen_examples]
        result = "\n\n".join(result)
        return result
