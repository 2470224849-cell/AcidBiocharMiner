from typing import Dict, List, Any, Optional
from pydantic import BaseModel

from llm_miner.schema import Elements
from llm_miner.config import config

# from llm_miner.reader import JournalReader
from llm_miner.meta_collector.base import MinedData, Results
from llm_miner.meta_collector.utils import flatten_list_of_dicts


def _normalize_formula_source(value: Any, fallback: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (list, tuple, set)):
        for item in value:
            norm = _normalize_formula_source(item, fallback="")
            if norm:
                return norm
        return fallback
    if value is None:
        return fallback
    return str(value)


class MetaCollector(BaseModel):
    list_data: List[MinedData]
    doi: Optional[str]

    def run(
        self,
    ) -> Results:  # before : categorize_by_equality
        results = Results.empty(doi=self.doi)
        for idx, data in enumerate(self.list_data):
            results.append(data, idx)
        return results

    @classmethod
    def from_elements(cls, elements: Elements, doi: Optional[str] = None):
        list_data = []
        for element in elements:
            if not element.has_data():
                continue
            elif element.type == "text":
                formula_source = _normalize_formula_source(
                    element.classification, fallback="text"
                )
            else:
                formula_source = _normalize_formula_source(
                    element.type, fallback=element.type
                )

            for data in flatten_list_of_dicts(element.data):
                if isinstance(data, str):
                    continue
                elif "meta" not in data:
                    continue
                mined_data = MinedData.from_data(
                    data,
                    formula_source=formula_source,
                    element_idx=element.idx,
                    doi=doi,
                )
                list_data.append(mined_data)

        return cls(list_data=list_data, doi=doi)

    @classmethod
    def from_journal_reader(cls, jr: object):
        if jr.cln_elements:
            if config.get("collect_from_both_elements", True):
                merged = Elements(
                    elements=[*jr.cln_elements.elements, *jr.elements.elements]
                )
                return cls.from_elements(elements=merged, doi=jr.doi)
            return cls.from_elements(elements=jr.cln_elements, doi=jr.doi)
        return cls.from_elements(elements=jr.elements, doi=jr.doi)
