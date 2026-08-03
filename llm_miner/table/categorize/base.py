from typing import Any, Dict, List, Optional

from langchain.base_language import BaseLanguageModel
from langchain.chains.base import Chain
from langchain.chains.llm import LLMChain
from langchain.prompts import PromptTemplate
from langchain.prompts.chat import (
      ChatPromptTemplate,
      SystemMessagePromptTemplate,
      HumanMessagePromptTemplate,
)
from langchain.callbacks.manager import CallbackManagerForChainRun

from llm_miner.schema import Paragraph
from llm_miner.table.categorize.prompt import PROMPT_CATEGORIZE, FT_CATEGORIZE, FT_HUMAN
from llm_miner.error import ContextError, LangchainError
from llm_miner.pricing import TokenChecker, update_token_checker
from llm_miner.parse_utils import parse_structured_output
from llm_miner.llm_compat import run_chain_with_optional_stop


class CategorizeAgent(Chain):
    categorize_chain: LLMChain
    labels: List[str] = ["Crystal", "Bond & Angle", "Coordinate", "Property", "Elemental Composition"]
    input_key: str = "element"
    output_key: str = "output"

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    def _write_log(self, text: str, run_manager):
        run_manager.on_text('\n[Categorize] ', verbose=self.verbose)
        run_manager.on_text(text, verbose=self.verbose, color='yellow')

    def _coerce_output_text(self, output: Any) -> str:
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
        output = output.replace("Output:", "").strip()
        try:
            parsed = parse_structured_output(output)
        except Exception:
            if output.startswith("'") and output.endswith("'"):
                return output[1:-1].strip()
            if output.startswith('"') and output.endswith('"'):
                return output[1:-1].strip()
            return output

        if isinstance(parsed, list):
            return str(parsed[0]).strip() if parsed else ""
        return str(parsed).strip()

    def _call(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None,
            token_checker: Optional[TokenChecker] = None
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        callbacks = _run_manager.get_child()

        element: Paragraph = inputs[self.input_key]
        para: str = element.clean_text
        token_checker: TokenChecker = inputs['token_checker']

        llm_kwargs = {
            'paragraph': para,
        }
        try:
            llm_output = run_chain_with_optional_stop(
                self.categorize_chain,
                **llm_kwargs,
                callbacks=callbacks,
                stop=['Input:'],
            )
        except Exception as e:
            element.add_intermediate_step('table-categorize', str(e))
            raise LangchainError(e)
        else:
            element.add_intermediate_step('table-categorize', llm_output)

        if token_checker:
            update_token_checker(
                name_step='table-categorize',
                chain=self.categorize_chain,
                token_checker=token_checker,
                llm_kwargs=llm_kwargs,
                llm_output=llm_output,
            )

        output = self._parse_output(llm_output)
        if output == "Empty Content":
            output = "['Empty Content']"

        if not output:
            raise ContextError('There are no categories in table')

        if output == "Empty content":
            raise ContextError(f'Table seems to be empty')

        elif output not in self.labels:
            raise ContextError(f'Class of table must be one of {self.labels}, not {output}')

        self._write_log(str(output), _run_manager)
        return {self.output_key: output}

    @classmethod
    def from_llm(
        cls,
        llm: BaseLanguageModel,
        prompt: str = PROMPT_CATEGORIZE,

        ft_categorize: str = FT_CATEGORIZE,
        ft_human: str = FT_HUMAN,

        **kwargs,
    ) -> Chain:
        if llm.model_name.startswith('ft:'):
            system_prompt = SystemMessagePromptTemplate.from_template(ft_categorize)
            human_prompt = HumanMessagePromptTemplate.from_template(ft_human)
            chat_prompt = ChatPromptTemplate.from_messages(
                [system_prompt, human_prompt]
            )
            categorize_chain = LLMChain(llm=llm, prompt=chat_prompt)

        else:
            template = PromptTemplate(
                template=prompt,
                template_format="jinja2",
                input_variables=['paragraph'],
            )
            categorize_chain = LLMChain(llm=llm, prompt=template)
        return cls(categorize_chain=categorize_chain, **kwargs)
