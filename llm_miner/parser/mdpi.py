from typing import List
from bs4 import BeautifulSoup

from llm_miner.schema import Paragraph
from llm_miner.parser.base import BaseParser, Metadata
from llm_miner.parser.utils import clean_text as f_clean


class MDPIParser(BaseParser):
    suffix: str = ".xml"
    parser: str = "xml"
    para_tags: List[str] = ["p", "title"]
    table_tags: List[str] = ["table-wrap"]
    figure_tags: List[str] = ["fig"]

    @classmethod
    def open_file(cls, filepath: str):
        with open(filepath, "r", encoding="UTF-8") as f:
            data = f.read()
        return BeautifulSoup(data, cls.parser)

    @classmethod
    def parsing(cls, file_bs) -> List[Paragraph]:
        elements = []

        for element in file_bs.find_all(cls.all_tags()):
            if element.name in cls.table_tags:
                type_ = "table"
                clean_text = ""
            elif element.name in cls.figure_tags:
                type_ = "figure"
                clean_text = f_clean(element.text)
            elif element.name in cls.para_tags and cls._is_para(element):
                type_ = "text"
                for tags in element(["xref", "named-content", "fig", "table-wrap"]):
                    tags.extract()
                clean_text = f_clean(element.text)
                if not clean_text.strip():
                    continue
            else:
                continue

            data = Paragraph(
                idx=len(elements) + 1,
                type=type_,
                content=str(element),
                clean_text=clean_text,
            )
            elements.append(data)

        return elements

    @classmethod
    def _is_para(cls, element):
        try:
            parent_name = element.parent.name
        except AttributeError:
            return False
        if parent_name in ["caption", "table-wrap-foot", "ack", "fn", "ref-list", "kwd-group"]:
            return False
        return True

    @classmethod
    def get_metadata(cls, file_bs) -> Metadata:
        try:
            doi = file_bs.find("article-id", attrs={"pub-id-type": "doi"}).text
        except AttributeError:
            doi = None
        try:
            title = file_bs.find("article-title").text
        except AttributeError:
            title = None
        try:
            journal = file_bs.find("journal-title").text
        except AttributeError:
            journal = None
        try:
            pub_date = file_bs.find("pub-date", attrs={"pub-type": "epub"}) or file_bs.find("pub-date")
            year = pub_date.find("year").text
            month_tag = pub_date.find("month")
            month = month_tag.text.zfill(2) if month_tag else "01"
            date = f"{year}.{month}"
        except AttributeError:
            date = None
        try:
            author_list = [
                contrib.find("name").text.strip()
                for contrib in file_bs.find_all("contrib", attrs={"contrib-type": "author"})
                if contrib.find("name")
            ]
        except AttributeError:
            author_list = None

        return Metadata(
            doi=doi,
            title=title,
            journal=journal,
            date=date,
            author_list=author_list,
        )
