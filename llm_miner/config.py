config = {
    # API connection (OpenAI-compatible providers)
    "api_base": None,
    "api_key_env": "OPENAI_API_KEY",
    # default llms
    "model_name": "gpt-4",
    "simple_model_name": "gpt-3.5-turbo-16k",
    # fine-tuned llms (optional)
    "fine_tuning_models": {
        "ft_text_categorize": None,
        "ft_text_property_type": None,
        "ft_text_property_extract": None,
        "ft_text_synthesis_type": None,
        "ft_text_synthesis_extract": None,
        "ft_table_convert": None,
        "ft_table_categorize": None,
        "ft_table_crystal_type": None,
        "ft_table_property_type": None,
    },
    # llm options
    "temperature": 0.0,
    "verbose": False,
    # config - agent
    "reconstruct": True,  # merge paragraph for reducing tokens
    # recall boosters
    "process_original_elements_after_reconstruct": True,
    "process_else_with_topic_signals": True,
    "max_else_boost_elements": 20,
    "collect_from_both_elements": True,
    "input_max_tokens_synthesis": None,  # max tokens for reconstruct
    "input_max_token_synthesis_type": 3500,  # max tokens for synthesis-type
    "input_max_tokens_property": 3500,  # max tokens for reconstruct
}
