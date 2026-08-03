from typing import Any, Dict, List, Optional

from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.chains.llm import LLMChain
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.prompts import PromptTemplate
from langchain.callbacks.manager import CallbackManagerForChainRun

from llm_miner.categorize.prompt import PROMPT_CATEGORIZE, FT_CATEGORIZE, FT_HUMAN
from llm_miner.error import StructuredFormatError, ContextError, LangchainError
from llm_miner.schema import Paragraph
from llm_miner.pricing import TokenChecker, update_token_checker
from llm_miner.parse_utils import parse_structured_output
from llm_miner.llm_compat import run_chain_with_optional_stop


class CategorizeAgent(Chain):
    categorize_chain: LLMChain
    labels: List[str] = ["table", "figure", "property", "synthesis condition", "else"]
    input_key: str = "paragraph"
    output_key: str = "output"

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]
    
    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]
    
    def _write_log(self, text: str, run_manager):
        run_manager.on_text(f"\n[Categorize] ", verbose=self.verbose)
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
        try:
            parsed = parse_structured_output(output, strip_labels=("List",))
            if isinstance(parsed, str):
                return [parsed]
            return parsed
        except Exception:
            # Be tolerant to non-JSON outputs from non-OpenAI providers.
            return [output]

    def _normalize_labels(self, raw: Any) -> List[str]:
        def walk(x):
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
            parts = [p.strip().lower() for p in item.replace("\n", ",").split(",") if p.strip()]
            for p in parts:
                label = ""
                if "table" in p:
                    label = "table"
                elif "figure" in p or p.startswith("fig") or "graph" in p:
                    label = "figure"
                elif "synthesis" in p or "preparation" in p or "condition" in p:
                    label = "synthesis condition"
                elif "property" in p or "adsorption" in p or "character" in p:
                    label = "property"
                elif "else" in p or "other" in p or "background" in p or "intro" in p:
                    label = "else"
                if label and label not in seen:
                    seen.add(label)
                    out.append(label)
        return out
    
    def _call(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        callbacks = _run_manager.get_child()
        
        para: Paragraph = inputs[self.input_key]
        token_checker: TokenChecker = inputs.get('token_checker')

        if para.type in self.labels:
            self._write_log([para.type], _run_manager)
            return {self.output_key: [para.type]}
        
        llm_kwargs={
            'paragraph': str(para.content),
        }
        try:
            llm_output = run_chain_with_optional_stop(
                self.categorize_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=["List:"],
            )
        except Exception as e:
            para.add_intermediate_step('categorize', str(e))
            raise LangchainError(e)
        else:
            para.add_intermediate_step('categorize', llm_output)

        if token_checker:
            update_token_checker(
                name_step='categorize',
                chain=self.categorize_chain,
                token_checker=token_checker,
                llm_kwargs=llm_kwargs,
                llm_output=llm_output
            )
        output = self._normalize_labels(self._parse_output(llm_output))
        if not output:
            output = ["else"]
        para.set_classification(output)

        if any([v not in self.labels for v in output]):
            output = [v for v in output if v in self.labels] or ["else"]
            para.set_classification(output)

        self._write_log(str(output), _run_manager)

        return {self.output_key: output}
    
    @classmethod
    def from_llm(
        cls,
        llm: BaseLanguageModel,
        prompt: str = PROMPT_CATEGORIZE,
        ft_prompt: str = FT_CATEGORIZE,
        ft_human: str = FT_HUMAN,
        **kwargs,
    ) -> Chain:
        
        if llm.model_name.startswith('ft:'): # fine-tuned model
            system_prompt = SystemMessagePromptTemplate.from_template(ft_prompt)
            human_prompt = HumanMessagePromptTemplate.from_template(ft_human)
            chat_prompt = ChatPromptTemplate.from_messages(
                [system_prompt, human_prompt]
            )
            categorize_chain = LLMChain(
                llm=llm,
                prompt=chat_prompt,
            )
        else:  # gpt base model
            template = PromptTemplate(
                template=prompt,
                input_variables=["paragraph"],
            )
            categorize_chain = LLMChain(llm=llm, prompt=template)

        return cls(categorize_chain=categorize_chain, **kwargs)
