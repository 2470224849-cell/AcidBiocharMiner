__version__ = '0.1.0'

import warnings

try:
    from langchain_core._api.deprecation import LangChainDeprecationWarning
except Exception:
    LangChainDeprecationWarning = None

if LangChainDeprecationWarning is not None:
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
warnings.filterwarnings("ignore", message=r".*urllib3 v2 only supports OpenSSL 1\.1\.1\+.*")
warnings.filterwarnings("ignore", message=r".*To install langchain-community.*")
warnings.filterwarnings("ignore", message=r".*The class `ChatOpenAI` was deprecated.*")
warnings.filterwarnings("ignore", message=r".*The class `LLMChain` was deprecated.*")
warnings.filterwarnings("ignore", message=r".*The method `Chain.run` was deprecated.*")

from llm_miner.agent import LLMMiner
from llm_miner.reader import JournalReader
from llm_miner.schema import Paragraph, Elements
