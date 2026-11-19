"""Prototype OpenRouter routes: DeepSeek/Cohere (fp8; Alibaba until 2026-11-12) and GPT Sol/OpenAI Flex.

The direct DeepSeek model IDs keep their original backend. Importing this file
does not access credentials or make requests; install() registers these IDs.
"""
import copy
import hashlib
import math
import os

MODEL = "deepseek/deepseek-v4.1-flash-1017"
GPT_MODEL = "openai/gpt-6.1-sol"
GPT_PROVIDER = "openai/flex"
GPT_TIMEOUT = 1800
OPUS_MODEL = "anthropic/claude-opus-5.5"
OPUS5_MODEL = "anthropic/claude-opus-5"
OPUS48_MODEL = "anthropic/claude-opus-4.8"
OPUS_MODELS = (OPUS_MODEL, OPUS5_MODEL, OPUS48_MODEL)
SONNET_MODEL = "anthropic/claude-sonnet-5.5"
HAIKU_MODEL = "anthropic/claude-haiku-5.5"
HAIKU_PROVIDER = "google-vertex/global"
HAIKU_PRICE = dict(input=0.10, cache_read=0.01, cache_write=0.125, output=0.50,
                   uncached_as_write=False,
                   long_context=dict(threshold=99999, input_mult=5.0, output_mult=5.0),
                   source="OpenRouter Google Vertex global explicit-cache rates, checked 2026-11-17: "
                          "https://openrouter.ai/api/v1/models/anthropic/claude-haiku-5.5/endpoints")
CLAUDE_MODELS = (*OPUS_MODELS, SONNET_MODEL, HAIKU_MODEL)
OPUS_PROVIDER = "anthropic"
OPUS5_PRICE = dict(input=5.0, cache_read=0.5, cache_write=6.25, output=25.0,
                   uncached_as_write=False, long_context=None,
                   source="OpenRouter Anthropic standard endpoint, checked 2026-11-12: "
                          "https://openrouter.ai/api/v1/models/anthropic/claude-opus-5/endpoints")
OPUS48_PRICE = dict(OPUS5_PRICE, source="OpenRouter Claude Platform on AWS standard endpoint, checked 2026-11-12: "
                                      "https://openrouter.ai/api/v1/models/anthropic/claude-opus-4.8/endpoints")
SONNET_PRICE = dict(input=2.0, cache_read=0.1, cache_write=2.5, output=10.0,
                    uncached_as_write=False, long_context=None,
                    source="OpenRouter Claude Platform on AWS endpoint, checked 2026-11-13: "
                           "https://openrouter.ai/api/v1/models/anthropic/claude-sonnet-5.5/endpoints")
GEMINI_MODEL = "google/gemini-3.8-flash"
QWEN_MODEL = "qwen/qwen3.8-flash"
GLM_MODEL = "z-ai/glm-5.3-flash"
GLM_PROVIDER = "kt"
NEMOTRON_MODEL = "nvidia/nemotron-3.5-lightning"
NEMOTRON_PROVIDER = "fireworks"
NEMOTRON_PRICE = dict(input=0.05, cache_read=0.01, cache_write=0.05, output=0.20,
                      uncached_as_write=False, long_context=None,
                      source="OpenRouter Fireworks implicit-cache rates, checked 2026-11-17: "
                             "https://openrouter.ai/api/v1/models/nvidia/nemotron-3.5-lightning/endpoints")
MINIMAX_MODEL = "minimax/minimax-m3.1-flash"
MINIMAX_PROVIDER = "digitalocean"
MINIMAX_PRICE = dict(input=0.15, cache_read=0.015, cache_write=0.15, output=0.60,
                     uncached_as_write=False, long_context=None,
                     source="OpenRouter DigitalOcean implicit-cache rates, checked 2026-11-17: "
                            "https://openrouter.ai/api/v1/models/minimax/minimax-m3.1-flash/endpoints")
GLM_PRICE = dict(input=0.15, cache_read=0.03, cache_write=0.15, output=0.50,
                 uncached_as_write=False, long_context=None,
                 source="OpenRouter KT implicit-cache endpoint rates, checked 2026-11-16: "
                        "https://openrouter.ai/api/v1/models/z-ai/glm-5.3-flash/endpoints")
QWEN_PROVIDER = "alibaba"
QWEN_PRICE = dict(input=0.15, cache_read=0.016, cache_write=0.20, output=0.47,
                  uncached_as_write=False, long_context=None,
                  source="OpenRouter Alibaba explicit-cache endpoint rates, checked 2026-11-14: "
                         "https://openrouter.ai/api/v1/models/qwen/qwen3.8-flash/endpoints")
GEMINI_PROVIDER = "google-ai-studio/flex"
GEMINI_PRICE = dict(input=0.375, cache_read=0.0375, cache_write=0.3958333333333333, output=1.875,
                    uncached_as_write=False, long_context=None,
                    source="OpenRouter Google AI Studio Flex endpoint, checked 2026-11-12; "
                           "cache write estimate includes input plus five-minute storage: "
                           "https://openrouter.ai/api/v1/models/google/gemini-3.8-flash/endpoints")
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
# 2026-11-12（用户「ok 换 cohere」）：DeepSeek 主试验走 Cohere（fp8，标价无折扣，随时可跑）。此前 pilot 走 Alibaba（夜间 UTC 14–24 促销价；
# 白天 $0.21 / $0.84），记录里的 api.routing 照旧是 alibaba。DeepSeek 自家线路在 OpenRouter 上 "Not routable"。
PROVIDER = "cohere"
PROVIDER_NAMES = ("Cohere", "cohere", "cohere/fp8")
PRICE = dict(input=0.15, cache_read=0.003, cache_write=0.15, output=0.50,
             uncached_as_write=False, long_context=None,
             source="OpenRouter Cohere endpoint rates (fp8, no discount), checked 2026-11-12: "
                    "https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints")
_ORIGINAL = {}
GPT_PRICE = dict(input=1.00, cache_read=0.05, cache_write=1.25, output=5.00,
                 uncached_as_write=True,
                 long_context=dict(threshold=272_000, input_mult=2.0, output_mult=1.5),
                 source="OpenRouter OpenAI Flex endpoint rates, checked 2026-11-11: "
                        "https://openrouter.ai/api/v1/models/openai/gpt-6.1-sol/endpoints")


def is_model(model):
    return model in (MODEL, GPT_MODEL, *CLAUDE_MODELS, GEMINI_MODEL, QWEN_MODEL, GLM_MODEL, MINIMAX_MODEL, NEMOTRON_MODEL)


def uses_responses(model):
    return model == GPT_MODEL


def opus_provider(model):
    if model == HAIKU_MODEL:
        return HAIKU_PROVIDER
    if model in (OPUS48_MODEL, SONNET_MODEL):
        return "claude-on-aws"
    provider = os.environ.get("AGII_OPUS5_PROVIDER", "anthropic") if model == OPUS5_MODEL else OPUS_PROVIDER
    if provider not in ("anthropic", "claude-on-aws"):
        raise ValueError(f"Unsupported Opus endpoint: {provider}")
    return provider


def preferences(model=MODEL):
    return dict(only=[NEMOTRON_PROVIDER if model == NEMOTRON_MODEL else MINIMAX_PROVIDER if model == MINIMAX_MODEL else GLM_PROVIDER if model == GLM_MODEL else QWEN_PROVIDER if model == QWEN_MODEL else GEMINI_PROVIDER if model == GEMINI_MODEL else opus_provider(model) if model in CLAUDE_MODELS else GPT_PROVIDER if uses_responses(model) else PROVIDER],
                allow_fallbacks=False, require_parameters=True)


def cache_parts(blocks):
    """Request blocks [(text, breakpoint?)] -> Responses input_text parts with OpenAI explicit breakpoints.

    The blocks are the ones built for Claude (layered memory; the fight log up to the previous step). Besides the
    marked blocks, the block just before the last mark is marked too: that is where the previous step wrote, so this
    step can read it. Concatenated text is identical to the plain user message."""
    marks = {i for i, (_t, m) in enumerate(blocks) if m}
    if marks:
        last = max(marks)
        if last - 1 >= 0 and last - 1 not in marks and all(m < last - 1 for m in marks - {last}):
            marks.add(last - 1)
    parts = []
    for i, (text, _m) in enumerate(blocks):
        if not text:
            continue
        part = dict(type="input_text", text=text)
        if i in marks:
            part["prompt_cache_breakpoint"] = dict(mode="explicit")
        parts.append(part)
    return parts


def responses_body(chat, cache_key=None, blocks=None):
    """Request official GPT summaries through OpenRouter's Responses API.

    cache_key (2026-11-11): modelrun.CACHE_KEY ("agii:<model>:<run_id>", one per world run). Sent as prompt_cache_key,
    which OpenAI uses to route shared prefixes to the same cache machine and OpenRouter uses as its sticky-routing key.
    Without it the GPT chain had 0 cache reads in 219 calls (every prompt billed as a cache write at $1.25/M).
    It changes routing only; the participant's text is untouched."""
    body = dict(model=chat["model"], input=copy.deepcopy(chat["messages"]),
                reasoning=dict(effort=chat.get("reasoning_effort", "high"), summary="auto"),
                provider=preferences(chat["model"]), service_tier="flex", store=False, stream=False)
    if cache_key:
        # OpenAI accepts at most 64 characters. Hard run IDs can exceed that;
        # hash the whole identifier so each run retains a stable, distinct key.
        body["prompt_cache_key"] = (cache_key if len(cache_key) <= 64
                                    else hashlib.sha256(cache_key.encode()).hexdigest())
    user = body["input"][-1] if body["input"] else None
    if blocks and user and user.get("role") == "user" and isinstance(user.get("content"), str) \
            and "".join(t for t, _m in blocks) == user["content"]:
        user["content"] = cache_parts(blocks)          # same text, split at the cache boundaries
    return body


def request_body(chat, blocks=None, cache_key=None):
    body = copy.deepcopy(chat)
    body["reasoning"] = dict(effort=body.pop("reasoning_effort", "high"), exclude=False)
    body["provider"] = preferences(body["model"])
    body["stream"] = False
    if body["model"] == NEMOTRON_MODEL:
        # Fireworks exposes a reasoning toggle, but no effort levels for this model.
        body["reasoning"] = dict(enabled=True, exclude=False)
    if body["model"] in (GLM_MODEL, MINIMAX_MODEL, NEMOTRON_MODEL) and cache_key:
        # These endpoints advertise implicit prefix caching, not cache_control.
        # A stable session routes this run consistently without changing its text.
        body["session_id"] = hashlib.sha256(cache_key.encode()).hexdigest()
    if body["model"] == GEMINI_MODEL:
        body["service_tier"] = "flex"
        if cache_key:
            body["session_id"] = hashlib.sha256(cache_key.encode()).hexdigest()
        user = body["messages"][-1]
        if blocks:
            if "".join(t for t, _m in blocks) != user["content"]:
                raise ValueError("Gemini cache blocks differ from participant text")
            # Gemini uses only the final marked prefix. Keep the changing tail outside it.
            user["content"] = [dict(type="text", text=t, **({"cache_control": {"type": "ephemeral"}} if mark else {}))
                               for t, mark in blocks if t]
    if body["model"] == QWEN_MODEL:
        if cache_key:
            body["session_id"] = hashlib.sha256(cache_key.encode()).hexdigest()
        if blocks:
            user = body["messages"][-1]
            if "".join(t for t, _m in blocks) != user["content"]:
                raise ValueError("Qwen cache blocks differ from participant text")
            if sum(bool(t and mark) for t, mark in blocks) > 4:
                raise ValueError("Qwen supports at most four cache breakpoints")
            user["content"] = [dict(type="text", text=t, **({"cache_control": {"type": "ephemeral"}} if mark else {}))
                               for t, mark in blocks if t]
    return body


def route_metadata(response, model=MODEL):
    result = dict(requested_provider=preferences(model)["only"][0],
                  reported_provider=response.get("provider"),
                  reported_model=response.get("model"), generation_id=response.get("id"))
    if uses_responses(model) or model == GEMINI_MODEL:
        result.update(requested_service_tier="flex", reported_service_tier=response.get("service_tier"))
    return result


def validate_response(response, model=MODEL):
    reported = response.get("provider")
    if model == NEMOTRON_MODEL:
        if reported is not None and reported not in ("Fireworks", NEMOTRON_PROVIDER):
            raise RuntimeError(f"Expected OpenRouter Fireworks, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("nvidia/")
        if name != "nemotron-3.5-lightning" and not name.startswith("nemotron-3.5-lightning-20"):
            raise RuntimeError(f"Expected Nemotron 3.5 Lightning, received model {name!r}")
        return
    if model == MINIMAX_MODEL:
        if reported is not None and reported not in ("DigitalOcean", MINIMAX_PROVIDER):
            raise RuntimeError(f"Expected OpenRouter DigitalOcean, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("minimax/")
        if name != "minimax-m3.1-flash" and not name.startswith("minimax-m3.1-flash-20"):
            raise RuntimeError(f"Expected MiniMax M3.1 Flash, received model {name!r}")
        return
    if model == GLM_MODEL:
        if reported is not None and reported not in ("KT", GLM_PROVIDER):
            raise RuntimeError(f"Expected OpenRouter KT, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("z-ai/")
        if name != "glm-5.3-flash" and not name.startswith("glm-5.3-flash-20"):
            raise RuntimeError(f"Expected GLM 5.3 Flash, received model {name!r}")
        return
    if model == QWEN_MODEL:
        if reported is not None and reported not in ("Alibaba", "Alibaba Cloud Int.", "alibaba", "alibaba/us-east-1"):
            raise RuntimeError(f"Expected OpenRouter Alibaba, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("qwen/")
        if name != "qwen3.8-flash" and not name.startswith("qwen3.8-flash-20"):
            raise RuntimeError(f"Expected Qwen3.8 Flash, received model {name!r}")
        return
    if model == GEMINI_MODEL:
        if reported is not None and reported not in ("Google AI Studio", "google-ai-studio", GEMINI_PROVIDER):
            raise RuntimeError(f"Expected Google AI Studio Flex, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("google/")
        if name != "gemini-3.8-flash" and not name.startswith("gemini-3.8-flash-20"):
            raise RuntimeError(f"Expected Gemini 3.8 Flash, received model {name!r}")
        # Some chat responses omit the tier. Pinning the endpoint is mandatory;
        # retain unknown metadata rather than inventing a reported tier.
        if response.get("service_tier") not in (None, "flex"):
            raise RuntimeError(f"Expected Flex service tier, received {response.get('service_tier')!r}")
        return
    if model in CLAUDE_MODELS:
        expected = opus_provider(model)
        names = (("Google", "Google Vertex", "google-vertex", HAIKU_PROVIDER) if model == HAIKU_MODEL
                 else ("Anthropic", "anthropic") if expected == "anthropic"
                 else ("Claude Platform on AWS", "claude-on-aws"))
        if reported is not None and reported not in names:
            raise RuntimeError(f"Expected OpenRouter {expected}, received provider {reported!r}")
        name = (response.get("model") or "").removeprefix("anthropic/")
        if model == HAIKU_MODEL:
            valid = (name in ("claude-haiku-5.5", "claude-haiku-5-5")
                     or name.startswith(("claude-haiku-5.5-20", "claude-haiku-5-5-20")))
        elif model == SONNET_MODEL:
            valid = (name in ("claude-sonnet-5.5", "claude-sonnet-5-5")
                     or name.startswith(("claude-sonnet-5.5-20", "claude-sonnet-5-5-20")))
        elif model == OPUS_MODEL:
            valid = name in ("claude-opus-5.5", "claude-opus-5-5") or name.startswith("claude-opus-5-5-20")
        elif model == OPUS48_MODEL:
            valid = (name in ("claude-opus-4.8", "claude-opus-4-8")
                     or name.startswith(("claude-4.8-opus-20", "claude-opus-4-8-20")))
        else:
            valid = name == "claude-opus-5" or name.startswith("claude-opus-5-20")
        if not valid:
            raise RuntimeError(f"Expected {model}, received model {name!r}")
        return
    if uses_responses(model):
        if reported is not None and reported not in ("OpenAI", "openai", GPT_PROVIDER):
            raise RuntimeError(f"Expected OpenRouter OpenAI Flex, received provider {reported!r}")
        if response.get("service_tier") != "flex":
            raise RuntimeError(f"Expected Flex service tier, received {response.get('service_tier')!r}")
        reported_model = (response.get("model") or "").removeprefix("openai/")
        if reported_model != "gpt-6.1-sol" and not reported_model.startswith("gpt-6.1-sol-20"):
            raise RuntimeError(f"Expected GPT 6.1 Sol, received {reported_model!r}")
        return
    # Some response shapes omit provider; preserve that absence in the journal.
    if reported is not None and reported not in PROVIDER_NAMES:
        raise RuntimeError(f"Expected OpenRouter Cohere, received provider {reported!r}")


def cost(response, model, usage):
    """Prefer OpenRouter's actual inference charge; otherwise label an estimate."""
    import prices
    reported = (response.get("usage") or {}).get("cost")
    if reported is not None:
        if isinstance(reported, bool) or not isinstance(reported, (int, float)) or not math.isfinite(reported) or reported < 0:
            raise ValueError("Invalid OpenRouter usage.cost")
        return float(reported), "openrouter_usage.cost"
    price = prices.price_for(model)
    return prices.cost_usd(price, usage["prompt_tokens"], usage["cached_tokens"],
                           usage["cache_write_tokens"], usage["completion_tokens"]), "endpoint_rate_estimate"


def install():
    import modelrun as mr
    import prices
    if _ORIGINAL:
        return
    _ORIGINAL.update(provider_for=mr.provider_for, price_for=prices.price_for)
    mr.PROVIDERS["openrouter"] = (ENDPOINT, ("OPENROUTER_API_KEY",))
    mr.EFFORT_LEVELS["openrouter"] = ("low", "medium", "high")
    mr.provider_for = lambda model: "openrouter" if is_model(model) else _ORIGINAL["provider_for"](model)

    def price_for(model):
        if is_model(model) and not os.environ.get("AGII_PRICE", "").strip():
            if model == HAIKU_MODEL:
                return copy.deepcopy(HAIKU_PRICE)
            if model == SONNET_MODEL:
                return copy.deepcopy(SONNET_PRICE)
            if model == OPUS48_MODEL:
                return copy.deepcopy(OPUS48_PRICE)
            if model == OPUS5_MODEL:
                return copy.deepcopy(OPUS5_PRICE)
            if model == GEMINI_MODEL:
                return copy.deepcopy(GEMINI_PRICE)
            if model == QWEN_MODEL:
                return copy.deepcopy(QWEN_PRICE)
            if model == GLM_MODEL:
                return copy.deepcopy(GLM_PRICE)
            if model == MINIMAX_MODEL:
                return copy.deepcopy(MINIMAX_PRICE)
            if model == NEMOTRON_MODEL:
                return copy.deepcopy(NEMOTRON_PRICE)
            if model == OPUS_MODEL:
                return _ORIGINAL["price_for"]("claude-opus-5-5")
            return copy.deepcopy(GPT_PRICE if uses_responses(model) else PRICE)
        return _ORIGINAL["price_for"](model)

    prices.price_for = price_for
