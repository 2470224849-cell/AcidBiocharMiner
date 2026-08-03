import re
from setuptools import setup, find_packages


with open("requirements.txt", "r") as f:
    install_requires = f.readlines()

with open("README.md", "r") as f:
    long_description = f.read()

extras_require = {"docs": ["sphinx", "livereload", "myst-parser"]}

with open("llm_miner/__init__.py") as f:
    version = re.search(r"__version__ = [\'\"](?P<version>.+)[\.\"]", f.read()).group("version")


setup(
    name="acid-biochar-miner",
    version=version,
    description="Traceable LLM-assisted extraction pipeline for acid-modified biochar literature",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Wonseok Lee, Yeonghun Kang, Taeun Bae",
    author_email="dudgns1675@kaist.ac.kr",
    packages=find_packages(),
    install_requires=install_requires,
    #extras_require=extras_require,
    scripts=[],
    python_requires=">=3.9",
)
