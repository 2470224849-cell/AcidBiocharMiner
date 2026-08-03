from typing import Any, Optional, Sequence


def _is_unsupported_stop_error(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    if "stop" not in msg:
        return False
    markers = [
        "unsupported parameter",
        "unsupported_parameter",
        "not supported",
        "invalid_request_error",
        "param': 'stop'",
        'param": "stop"',
    ]
    return any(m in msg for m in markers)


def run_chain_with_optional_stop(
    chain: Any,
    *,
    callbacks: Any = None,
    stop: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> Any:
    """
    Run LLMChain.run with graceful fallback when backend does not support `stop`.
    """
    if stop:
        try:
            return chain.run(**kwargs, callbacks=callbacks, stop=list(stop))
        except Exception as exc:
            if not _is_unsupported_stop_error(exc):
                raise
    return chain.run(**kwargs, callbacks=callbacks)

