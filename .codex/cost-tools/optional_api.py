"""Optional explicit API/prose helpers; importing never changes app providers."""
from __future__ import annotations

_owned_cache = None


def api_completion(*, model: str, messages: list[dict], **kwargs):
    """Reuse an explicit configured model with five-minute exact-request caching."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("An explicit, authorized provider/model is required")
    import litellm
    from litellm.caching.caching import Cache
    global _owned_cache
    # Never inherit a cache another application configured: it may persist data.
    if litellm.cache is not None and litellm.cache is not _owned_cache:
        raise ValueError("Existing LiteLLM cache preserved; use the application's authorized cache directly")
    if _owned_cache is None:
        _owned_cache = Cache(type="local", ttl=300)
    litellm.cache = _owned_cache
    litellm.telemetry = False
    kwargs.setdefault("num_retries", 0)
    kwargs.setdefault("caching", True)
    return litellm.completion(model=model, messages=messages, **kwargs)


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
