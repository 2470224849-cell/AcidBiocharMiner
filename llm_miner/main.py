import os
from pydantic import BaseModel

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # backward compatibility for older environments
    from langchain_community.chat_models import ChatOpenAI
from llm_miner.agent import LLMMiner
from llm_miner.reader import JournalReader
from llm_miner.config import config


def set_agent(config, openai_api_key=None):
    model_name = config["model_name"]
    simple_model_name = config["simple_model_name"]
    temp = config['temperature']
    api_base = config.get("api_base") or os.getenv("OPENAI_API_BASE")
    api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
    resolved_api_key = openai_api_key or os.getenv(api_key_env)

    llm_kwargs = {
        "temperature": temp,
        "openai_api_key": resolved_api_key,
    }
    if api_base:
        llm_kwargs["openai_api_base"] = api_base

    llm = ChatOpenAI(model_name=model_name, **llm_kwargs)
    simple_llm = ChatOpenAI(model_name=simple_model_name, **llm_kwargs)
    return llm, simple_llm


llm, simple_llm = set_agent(config)


def main(file_path: str, journal=None):
    global llm, simple_llm

    jr = JournalReader.from_file(file_path, journal)
    if not jr.elements:
        return False

    agent = LLMMiner.from_llm(llm, simple_llm, verbose=config['verbose'])

    for element in jr.elements:
        data = agent.run(element)
        element.set_data(data)

    return jr
