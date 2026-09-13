"""Optional explicit API/prose helpers; importing never changes app providers."""
from __future__ import annotations

_owned_cache = None
_REQUEST_OPTIONS = frozenset({"temperature", "top_p", "max_tokens", "max_completion_tokens",
                             "stop", "seed", "response_format", "tools", "tool_choice",
                             "parallel_tool_calls", "presence_penalty", "frequency_penalty",
                             "timeout", "api_base", "api_key", "api_version", "custom_llm_provider"})


def api_completion(*, model: str, messages: list[dict], **kwargs):
    """Reuse an explicit configured model with five-minute exact-request caching."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("An explicit, authorized provider/model is required")
    if kwargs.pop("caching", True) is not True or kwargs.pop("num_retries", 0) != 0:
        raise ValueError("Caching is required and retries must remain zero")
    if set(kwargs) - _REQUEST_OPTIONS:
        raise ValueError("Unsupported request options; routing and cache overrides are not allowed")
    import litellm
    from litellm.caching.caching import Cache
    global _owned_cache
    if any(getattr(litellm, name, None) for name in
           ("fallbacks", "longer_context_model_fallback_dict", "model_alias_map")):
        raise ValueError("Existing LiteLLM routing preserved; use an isolated process")
    # Never inherit a cache another application configured: it may persist data.
    if litellm.cache is not None and litellm.cache is not _owned_cache:
        raise ValueError("Existing LiteLLM cache preserved; use the application's authorized cache directly")
    if _owned_cache is None:
        _owned_cache = Cache(type="local", ttl=300)
    litellm.cache = _owned_cache
    litellm.telemetry = False
    return litellm.completion(model=model, messages=messages, num_retries=0, caching=True, **kwargs)


def compress_notes(text: str, *, low_risk_prose: bool, rate: float = 0.7) -> dict:
    """Return a candidate only. Caller retains original and evaluates quality."""
    if not low_risk_prose:
        raise ValueError("Only explicitly identified low-risk prose is eligible")
    if not 0 < rate <= 1:
        raise ValueError("Compression rate must be above zero and at most one")
    from llmlingua import PromptCompressor
    compressor = PromptCompressor(
        model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        device_map="cpu", use_llmlingua2=True,
        model_config={"trust_remote_code": False})
    return compressor.compress_prompt(text, rate=rate)
