"""Provider-returned reasoning, kept outside participant memory (prototype only).

GPT uses stateless Responses with reasoning summaries; Claude requests summarized
thinking. Compatible providers retain their returned reasoning fields unchanged.
Every completed response is flushed to a per-life/per-letter JSONL journal before
the caller parses an action. This module never reads those journals into prompts.
"""
from contextvars import ContextVar
import copy
import io
import json
import os
from pathlib import Path
import time
import uuid

import modelrun as mr
import conversation_mode as cm
import durable_resume
import openrouter_backend as router
from study_models import GEMINI_THINKING_LEVEL

VERSION = "reasoning-capture-v1-2026-11-09"
_CURRENT = ContextVar("transverse_reasoning_request", default=None)
_TARGET = ContextVar("transverse_reasoning_target", default=None)
_ORIGINAL = {}


def _plain(value):
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return _plain(vars(value))


def bind(model, record_path):
    """Choose the journal for subsequent real calls; no file is created yet."""
    _TARGET.set((model, Path(record_path).with_suffix(".calls.jsonl")))


def _texts(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    if isinstance(value, dict):
        return _texts(value.get("text") or value.get("thinking"))
    return []


def _reasoning(ctx):
    response, provider = ctx.get("response") or {}, ctx["provider"]
    blocks, texts = [], []
    if provider == "anthropic" or ctx["model"] in router.CLAUDE_MODELS:
        blocks = [b for b in response.get("content", []) if b.get("type") in ("thinking", "redacted_thinking")]
        texts = [b["thinking"] for b in blocks if b.get("type") == "thinking" and b.get("thinking")]
        format_ = "provider_summary"
    elif provider == "openai" or router.uses_responses(ctx["model"]):
        blocks = [b for b in response.get("output", []) if b.get("type") == "reasoning"]
        texts = [part["text"] for b in blocks for part in b.get("summary", []) if part.get("text")]
        format_ = "provider_summary"
    elif provider == "gemini":
        candidate = (response.get("candidates") or [{}])[0]
        blocks = [b for b in (candidate.get("content") or {}).get("parts", []) if b.get("thought") is True]
        texts = [b["text"] for b in blocks if b.get("text")]
        format_ = "provider_summary"
    else:
        msg = ((response.get("choices") or [{}])[0].get("message") or {})
        blocks = [{"field": k, "value": msg[k]} for k in ("reasoning_content", "reasoning", "reasoning_details") if k in msg]
        # Preserve both source fields; use the primary one for the convenience text.
        texts = _texts(msg.get("reasoning_content")) or _texts(msg.get("reasoning"))
        if not texts:
            texts = [b.get("text") or b.get("summary") for b in (msg.get("reasoning_details") or [])
                     if b.get("type") in ("reasoning.text", "reasoning.summary") and (b.get("text") or b.get("summary"))]
        format_ = "provider_summary" if ctx["model"] == router.GEMINI_MODEL else "provider_reasoning"
    text = "\n\n".join(texts) or None
    redacted = any(b.get("type") == "redacted_thinking" for b in blocks)
    if provider == "openai" or router.uses_responses(ctx["model"]):
        redacted = redacted or any(b.get("encrypted_content") for b in blocks)
    if provider == "openrouter" and not router.uses_responses(ctx["model"]) and ctx["model"] not in router.CLAUDE_MODELS:
        redacted = redacted or any(b.get("type") == "reasoning.encrypted" for b in msg.get("reasoning_details") or [])
    status = "returned" if text else "redacted" if redacted else "empty" if blocks else "not_returned"
    u = response.get("usageMetadata") or response.get("usage") or {}
    count = None
    for section in ("output_tokens_details", "completion_tokens_details"):
        if (u.get(section) or {}).get("reasoning_tokens") is not None:
            count = u[section]["reasoning_tokens"]
            break
        if (u.get(section) or {}).get("thinking_tokens") is not None:      # Anthropic Messages（11-12）
            count = u[section]["thinking_tokens"]
            break
    if count is None:
        count = u.get("thoughtsTokenCount", u.get("reasoning_tokens"))
    return dict(version=VERSION, format=format_, status=status, text=text,
                blocks=copy.deepcopy(blocks), redacted=redacted, reasoning_tokens=count,
                raw_internal_chain_available=False if format_ == "provider_summary" else None)


def _journal(ctx, *, error=None):
    target = _TARGET.get()
    if not target or target[0] != ctx["model"] or ctx.get("journal_written"):
        return
    path = target[1]
    event = dict(version=VERSION, call_id=ctx["call_id"], model=ctx["model"], provider=ctx["provider"],
                 kind=ctx["kind"], system=ctx["system"], user=ctx["user"],
                 raw=ctx.get("text"), reasoning_capture=_reasoning(ctx),
                 api=mr.api_settings(ctx["model"]), request_blocks=ctx.get("request_blocks"),
                 provider_response=ctx.get("response"), usage=ctx.get("usage"),
                 usage_details=ctx.get("usage_details", {}),
                 routing=ctx.get("routing"), elapsed_seconds=time.monotonic() - ctx["started"],
                 outcome="error" if error else "response", error=error,
                 **({"conversation": ctx["conversation"]["info"]} if ctx.get("conversation") else {}),
                 aborted_attempts=ctx.get("aborted_attempts") or [])   # 上游中断、已重试的尝试（11-12）
    path.parent.mkdir(parents=True, exist_ok=True)
    # Append, never replace completed calls from an earlier interrupted process.
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    ctx["journal_written"] = True


def _trace_call(system, user, text):
    _ORIGINAL["trace"](system, user, text)
    ctx = _CURRENT.get()
    if ctx is None:
        return
    ctx["text"] = text
    captured = _reasoning(ctx)
    mr._LAST_REASONING[0] = captured["text"]
    mr.TRACE[-1].update(reasoning=captured["text"], reasoning_capture=captured,
                        provider_usage=copy.deepcopy((ctx.get("response") or {}).get("usageMetadata")
                                                     or (ctx.get("response") or {}).get("usage")),
                        usage=copy.deepcopy(ctx.get("usage")), call_id=ctx["call_id"])
    if ctx.get("routing"):
        mr.TRACE[-1]["routing"] = copy.deepcopy(ctx["routing"])
    target = _TARGET.get()
    if target and target[0] == ctx["model"]:
        mr.TRACE[-1]["call_journal"] = str(target[1])
    _journal(ctx)


def _absorb_usage(data, kind="other", model="", text=""):
    ctx = _CURRENT.get()
    before_details = dict(mr.USAGE_DETAILS)
    if ctx is not None and ctx.get("response") is None:
        ctx["response"] = copy.deepcopy(data)
    if router.is_model(model):
        # Reuse token normalization, then account once using the routed charge,
        # not the price of DeepSeek's direct API.
        usage = _ORIGINAL["usage"](data, kind, "", text)
        charge, source = router.cost(data, model, usage)
        usage["cost_usd"] = charge
        mr.USAGE["cost_usd"] += charge
        mr.USAGE_BY_KIND[kind]["cost_usd"] += charge
        mr._spend(charge)
        if ctx is not None:
            ctx["routing"] = dict(router.route_metadata(data, model), cost_source=source)
            ctx["usage"] = copy.deepcopy(usage)
        if not data.get("error"):       # Billed error envelopes may omit model/provider; they never become actions.
            router.validate_response(data, model)
    else:
        usage = _ORIGINAL["usage"](data, kind, model, text)
    if ctx is not None:
        ctx["usage"] = copy.deepcopy(usage)
        ctx["usage_details"] = {k: v - before_details.get(k, 0) for k, v in mr.USAGE_DETAILS.items()
                                if v != before_details.get(k, 0)}
    return usage


def _openrouter_open(transport, req, **kwargs):
    chat = json.loads(req.data)
    if chat["model"] in router.CLAUDE_MODELS:
        return _opus_router_open(transport, req, chat, **kwargs)
    if router.uses_responses(chat["model"]):
        return _responses_open(transport, req, **kwargs)
    body = router.request_body(chat, blocks=_CURRENT.get().get("request_blocks"), cache_key=mr.CACHE_KEY)
    if _CURRENT.get().get("conversation"):           # AGII_HARNESS=continuous: earlier answers + reasoning_details
        body["messages"] = cm.chat_messages(cm.active(), _CURRENT.get()["conversation"], chat["messages"][0]["content"])
    request = mr.urllib.request.Request(req.full_url, data=json.dumps(body).encode(), headers=dict(req.header_items()))
    with transport(request, **kwargs) as r:
        response = json.load(r)
    _CURRENT.get()["response"] = response
    if response.get("error"):
        error = response["error"]
        code = error.get("code", "unknown")
        retry_code = int(code) if str(code).isdigit() else None
        if retry_code in mr.RETRY_STATUS:
            # Chat Completions may return HTTP 200 with an upstream 504 envelope.
            # Hand it to the existing bounded backoff, preserving any billed attempt.
            ctx = _CURRENT.get()
            ctx.setdefault("aborted_attempts", []).append(dict(response=response, seconds=time.monotonic() - ctx["started"]))
            if ((response.get("usage") or {}).get("cost") or 0) > 0:
                mr._absorb_usage(response, ctx["kind"], ctx["model"], "")
            ctx["response"] = None
            raise mr.urllib.error.HTTPError(req.full_url, retry_code, "Transient OpenRouter API error", {},
                                             io.BytesIO(json.dumps(error).encode()))
        raise RuntimeError(f"OpenRouter API error: {code}")
    choice = (response.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "error":
        # 2026-11-12：上游在生成途中中断（DS / Cohere：思考 13,065 token 后 finish_reason=error、content=None、不收费）。
        # 这不是参与者的回答：不能当空回复交给对局（否则日志里多一行 [unparseable]、算一次无效操作）。
        # 记下这次中断，交给 modelrun.call 的退避重试（502 在 RETRY_STATUS 里），同一请求重发。
        ctx = _CURRENT.get()
        ctx.setdefault("aborted_attempts", []).append(dict(response=response, seconds=time.monotonic() - ctx["started"]))
        if ((response.get("usage") or {}).get("cost") or 0) > 0:      # 若上游对中断也收费：照记进花费（预算上限不能漏）
            mr._absorb_usage(response, ctx["kind"], ctx["model"], "")
        ctx["response"] = None
        raise mr.urllib.error.HTTPError(req.full_url, 502, "Upstream generation aborted (finish_reason=error)", {},
                                         io.BytesIO(json.dumps(dict(error=dict(code=502, message="finish_reason=error"))).encode()))
    return io.BytesIO(json.dumps(response).encode())


def _opus_router_open(transport, req, chat, **kwargs):
    """Native Messages through OpenRouter; retain Claude cache blocks and summaries."""
    import claude_backend as cb
    ctx = _CURRENT.get()
    messages = chat["messages"]
    user = messages[-1]["content"]
    blocks = ctx.get("request_blocks") or [(user, False)]
    if "".join(t for t, _m in blocks) != user:
        raise ValueError("Opus cache blocks differ from participant text")
    body = cb.build_request(chat["model"], ctx["system"], blocks,
                            chat.get("reasoning_effort", "high"))
    if ctx.get("conversation"):                      # AGII_HARNESS=continuous: the whole fight so far, thinking replayed
        body["messages"] = cm.messages_body(cm.active(), ctx["conversation"])
    body.update(thinking=dict(type="adaptive", display="summarized"),
                provider=router.preferences(chat["model"]), stream=False)
    url = req.full_url.removesuffix("/chat/completions") + "/messages"
    headers = dict(req.header_items())
    headers["Anthropic-Version"] = "2023-06-01"
    request = mr.urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with transport(request, **kwargs) as response_stream:
        response = json.load(response_stream)
    ctx["response"] = response
    if response.get("error"):
        raise RuntimeError(f"OpenRouter Messages error: {response['error'].get('type', 'unknown')}")
    if response.get("type") != "message" or not isinstance(response.get("content"), list):
        raise RuntimeError("OpenRouter Messages returned no message")
    text = "".join(b.get("text", "") for b in response["content"] if b.get("type") == "text")
    stop = response.get("stop_reason")
    usage = copy.deepcopy(response.get("usage") or {})
    thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens")
    if thinking is not None:                         # 11-12：Anthropic 报 thinking_tokens；记账统一读 reasoning_tokens（花费照旧用 usage.cost）
        usage["output_tokens_details"] = dict(usage["output_tokens_details"], reasoning_tokens=thinking)
        # modelrun sums reasoning_tokens across detail sections. Keep one alias,
        # otherwise native thinking tokens are counted twice (not billed twice).
        if "completion_tokens_details" in usage:
            usage["completion_tokens_details"] = {k: v for k, v in usage["completion_tokens_details"].items()
                                                   if k != "reasoning_tokens"}
    normalized = dict(usage=usage, stop_reason=stop, stop_details=copy.deepcopy(response.get("stop_details")),
                      choices=[dict(message=dict(content=text),
                                    finish_reason="length" if stop == "max_tokens" else stop)])
    normalized.update({k: response.get(k) for k in ("provider", "model", "id")})
    return io.BytesIO(json.dumps(normalized).encode())


def _responses_open(transport, req, **kwargs):
    chat = json.loads(req.data)
    routed = router.uses_responses(chat["model"])
    reasoning = {"summary": "auto"}
    if "reasoning_effort" in chat:
        reasoning["effort"] = chat["reasoning_effort"]
    body = dict(model=chat["model"], input=chat["messages"], reasoning=reasoning, store=False)
    if "prompt_cache_key" in chat:
        body["prompt_cache_key"] = chat["prompt_cache_key"]
    if routed:
        # prompt_cache_key (11-11): routing only. Not added to api settings: those are part of the resume manifest.
        body = router.responses_body(chat, cache_key=mr.CACHE_KEY or None,
                                     blocks=(_CURRENT.get() or {}).get("request_blocks"))
        if (_CURRENT.get() or {}).get("conversation"):   # AGII_HARNESS=continuous: earlier output items replayed
            body["input"] = cm.responses_input(cm.active(), _CURRENT.get()["conversation"], chat["messages"][0]["content"])
        kwargs["timeout"] = router.GPT_TIMEOUT
    suffix = "/chat/completions"
    if not req.full_url.endswith(suffix):
        raise ValueError("Expected a Chat Completions endpoint before the Responses bridge")
    url = req.full_url[:-len(suffix)] + "/responses"
    request = mr.urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(req.header_items()))
    if routed:                                     # account-wide 20 rpm for GPT on OpenRouter (scripts/gpt_rate_gate.py)
        import gpt_rate_gate
        gpt_rate_gate.acquire()
    with transport(request, **kwargs) as r:
        response = json.load(r)
    _CURRENT.get()["response"] = response
    if response.get("error"):
        error = response["error"]
        code = error.get("code")
        if routed and isinstance(code, int) and code in mr.RETRY_STATUS:
            raise mr.urllib.error.HTTPError(url, code, "OpenRouter API error", {},
                                             io.BytesIO(json.dumps(error).encode()))
        if routed and code == "rate_limit_exceeded":
            # 2026-11-11: OpenRouter's upstream pool for gpt-6.1-sol ("temporarily rate-limited upstream") answers with
            # an error body, not HTTP 429, and the throttle lasts minutes. Hand it to modelrun's backoff as a 429 with
            # Retry-After 120 s: six tries cover about ten minutes before the worker pauses.
            raise mr.urllib.error.HTTPError(url, 429, "OpenRouter upstream rate limit", {"Retry-After": "120"},
                                             io.BytesIO(json.dumps(error).encode()))
        if routed and code in ("server_error", "internal_server_error", "provider_error",
                               "temporarily_unavailable", "overloaded_error", "timeout"):
            # A Responses HTTP-200 envelope can still be a failed upstream generation.
            # Retry the identical request; never turn it into a participant action.
            ctx = _CURRENT.get()
            ctx.setdefault("aborted_attempts", []).append(dict(response=response, seconds=time.monotonic() - ctx["started"]))
            if ((response.get("usage") or {}).get("cost") or 0) > 0:
                u = response["usage"]
                normalized = dict(usage=dict(prompt_tokens=u.get("input_tokens", 0),
                                            completion_tokens=u.get("output_tokens", 0),
                                            prompt_tokens_details=u.get("input_tokens_details") or {},
                                            completion_tokens_details=u.get("output_tokens_details") or {},
                                            cost=u["cost"]),
                                  **{k: response.get(k) for k in ("provider", "model", "id", "service_tier")})
                mr._absorb_usage(normalized, ctx["kind"], ctx["model"], "")
            ctx["response"] = None
            raise mr.urllib.error.HTTPError(url, 504 if code == "timeout" else 502,
                                             "Transient upstream Responses failure", {},
                                             io.BytesIO(json.dumps(error).encode()))
        raise RuntimeError(f"Responses API error: {code or 'unknown'}")
    if response.get("status") not in ("completed", "incomplete"):
        raise RuntimeError(f"Responses request did not complete: {response.get('status')!r}")
    messages = [b for b in response.get("output", []) if b.get("type") == "message"]
    finals = [b for b in messages if b.get("phase") == "final_answer"]
    parts = [p for b in (finals or messages) for p in b.get("content", [])]
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "output_text")
    refused = any(p.get("type") == "refusal" for p in parts)
    stop = "refusal" if refused else "length" if response.get("status") == "incomplete" else "stop"
    u = response.get("usage") or {}
    usage = dict(prompt_tokens=u.get("input_tokens", 0), completion_tokens=u.get("output_tokens", 0),
                 prompt_tokens_details=u.get("input_tokens_details") or {},
                 completion_tokens_details=u.get("output_tokens_details") or {})
    if "cost" in u:
        usage["cost"] = u["cost"]
    normalized = dict(usage=usage, choices=[dict(message=dict(content=text), finish_reason=stop)])
    if routed:
        normalized.update({k: response.get(k) for k in ("provider", "model", "id", "service_tier")})
    # Let the existing parser, price accounting, cache-key retry, and HTTP retry
    # machinery consume its usual response shape. Native output is journalled above.
    return io.BytesIO(json.dumps(normalized).encode())


def _claude_call(model, system, blocks, key, effort=None):
    import claude_backend as cb
    req = cb.build_request(model, system, blocks, effort)
    req["thinking"] = dict(type="adaptive", display="summarized")
    try:
        msg = cb._client(key).messages.create(**req)
    except cb.anthropic.APIStatusError as e:
        raise SystemExit(cb.fatal_message(e.status_code, getattr(e, "message", str(e))))
    except cb.anthropic.APIConnectionError as e:
        raise SystemExit(f"Cannot connect to Anthropic after {cb.MAX_RETRIES} retries: {e}")
    response = dict(content=_plain(msg.content), usage=_plain(msg.usage), stop_reason=msg.stop_reason,
                    id=getattr(msg, "id", None), model=getattr(msg, "model", model))
    ctx = _CURRENT.get()
    if ctx is not None:
        ctx["response"] = response
    text = "".join(b.get("text", "") for b in response["content"] if b.get("type") == "text").strip()
    return text, response["usage"], msg.stop_reason


def _gemini_endpoint(model):
    bare = model.split("/")[-1]
    base = os.environ.get("AGII_GEMINI_NATIVE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    return f"{base}/models/{bare}:generateContent"


def _gemini_open(transport, req, **kwargs):
    chat = json.loads(req.data)
    messages = chat["messages"]
    if [m["role"] for m in messages] != ["system", "user"]:
        raise ValueError("Gemini prototype requests must contain only the current system and user prompt")
    body = dict(systemInstruction=dict(parts=[dict(text=messages[0]["content"])]),
                contents=[dict(role="user", parts=[dict(text=messages[1]["content"])])],
                generationConfig=dict(thinkingConfig=dict(thinkingLevel=GEMINI_THINKING_LEVEL, includeThoughts=True)))
    auth = req.get_header("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ValueError("The Gemini bridge requires the existing API-key credential")
    request = mr.urllib.request.Request(_gemini_endpoint(chat["model"]), data=json.dumps(body).encode(),
                                        headers={"x-goog-api-key": auth[len("Bearer "):], "Content-Type": "application/json"})
    with transport(request, **kwargs) as r:
        response = json.load(r)
    _CURRENT.get()["response"] = response
    if response.get("error"):
        raise RuntimeError("Gemini returned an API error response")
    candidate = (response.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts", [])
    # Summary text can contain action names. Only the answer reaches the parser.
    text = "".join(p.get("text", "") for p in parts if p.get("thought") is not True)
    finish = candidate.get("finishReason")
    blocked = finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY")
    blocked = blocked or bool((response.get("promptFeedback") or {}).get("blockReason"))
    stop = "refusal" if blocked else "length" if finish == "MAX_TOKENS" else "stop"
    u = response.get("usageMetadata") or {}
    prompt, thoughts = int(u.get("promptTokenCount") or 0), int(u.get("thoughtsTokenCount") or 0)
    if "candidatesTokenCount" in u:
        completion = int(u.get("candidatesTokenCount") or 0) + thoughts
    else:
        completion = max(thoughts, int(u.get("totalTokenCount") or 0) - prompt)
    details = dict(reasoning_tokens=thoughts) if "thoughtsTokenCount" in u else {}
    usage = dict(prompt_tokens=prompt, completion_tokens=completion,
                 prompt_tokens_details=dict(cached_tokens=int(u.get("cachedContentTokenCount") or 0)),
                 completion_tokens_details=details)
    normalized = dict(usage=usage, choices=[dict(message=dict(content=text), finish_reason=stop)])
    return io.BytesIO(json.dumps(normalized).encode())


def _call(model, system, user, key, blocks=None):
    provider = mr.provider_for(model)
    ctx = dict(model=model, provider=provider, call_id=uuid.uuid4().hex,
               kind=mr._call_kind(system), system=system, user=user, response=None, started=time.monotonic(), request_blocks=blocks)
    token = _CURRENT.set(ctx)
    transport = mr.urllib.request.urlopen
    route = None
    if cm.enabled() and cm.active() is not None and ctx["kind"] == "adv-act":
        route = cm.route(model)
        if route is None:
            _CURRENT.reset(token)
            raise SystemExit(f"AGII_HARNESS=continuous is not supported for {model} (route {provider}); refusing to run stateless")
        ctx["conversation"] = cm.begin_step(user, blocks)
    try:
        event = durable_resume.replay(model, system, user, blocks)
        if event is not None:
            if route is not None:
                if (event.get("conversation") or {}).get("sent_text") != ctx["conversation"]["info"]["sent_text"]:
                    raise RuntimeError("Resume diverged (conversation text); no new request sent")
                cm.end_step(ctx["conversation"], user, blocks, event.get("provider_response"), route)
            ctx.update(response=event.get("provider_response"), usage=event.get("usage"), routing=event.get("routing"),
                       usage_details=event.get("usage_details", {}),
                       call_id=event["call_id"], journal_written=True)
            _trace_call(system, user, event["raw"])
            mr.TRACE[-1]["resumed_from_journal"] = True
            return event["raw"]
        if provider == "openrouter":
            mr.urllib.request.urlopen = lambda req, **kw: _openrouter_open(transport, req, **kw)
        elif provider == "openai":
            mr.urllib.request.urlopen = lambda req, **kw: _responses_open(transport, req, **kw)
        elif provider == "gemini":
            mr.urllib.request.urlopen = lambda req, **kw: _gemini_open(transport, req, **kw)
        elif provider == "anthropic":
            import claude_backend as cb
            cb.call = _claude_call
        text = _ORIGINAL["call"](model, system, user, key, blocks=blocks)
        if route is not None:
            cm.end_step(ctx["conversation"], user, blocks, ctx.get("response"), route)
        limit = int(os.environ.get("AGII_EMPTY_RESPONSE_LIMIT", "0"))
        if limit and not (text or "").strip() and _TARGET.get():
            empty_count = 0
            for journal in _TARGET.get()[1].parent.glob("*.calls.jsonl"):
                for line in journal.read_text().splitlines():
                    event = json.loads(line)
                    empty_count += (event.get("model") == model and event.get("outcome") == "response"
                                    and not (event.get("raw") or "").strip())
            if empty_count >= limit:
                raise SystemExit(f"Paused: {empty_count} empty responses total (limit {limit}); response saved")
        return text
    except BaseException as e:
        _journal(ctx, error=type(e).__name__)
        raise
    finally:
        if provider in ("openai", "gemini", "openrouter"):
            mr.urllib.request.urlopen = transport
        _CURRENT.reset(token)


def _settings(model):
    result = _ORIGINAL["settings"](model)
    result["reasoning_capture"] = VERSION
    provider = mr.provider_for(model)
    if provider == "openrouter":
        import prices
        level = mr.effort_for(provider) or "high"
        result.update(routing=router.preferences(model), reasoning=dict(effort=mr.effort_for(provider) or "high", exclude=False),
                      effort=dict(requested=mr.EFFORT or "default", sent=level),
                      conversation_state="stateless; no thought replay", quantization="unknown",
                      cache="provider automatic prefix; cache reads recorded from usage",
                      price=prices.price_for(model), cost_accounting="usage.cost; endpoint-rate estimate when absent")
        if router.uses_responses(model):
            result.update(endpoint=mr._endpoint(provider).removesuffix("/chat/completions") + "/responses",
                          service_tier="flex", reasoning=dict(effort=level, summary="auto"),
                          reasoning_summary="auto", conversation_state="stateless; store=false; no thought replay",
                          request_timeout_seconds=router.GPT_TIMEOUT)
        elif model in router.CLAUDE_MODELS:
            result.update(endpoint=mr._endpoint(provider).removesuffix("/chat/completions") + "/messages",
                          thinking="adaptive", thinking_display="summarized",
                          reasoning=dict(effort=level), max_tokens=16000,
                          cache="explicit Claude cache_control breakpoints; at most four; volatile tail excluded")
        elif model == router.GEMINI_MODEL:
            result.update(service_tier="flex", reasoning_summary="provider returned summary when available",
                          cache="explicit cache_control prefix; Gemini uses final breakpoint; volatile tail excluded")
        elif model == router.QWEN_MODEL:
            result.update(cache="explicit Alibaba cache_control breakpoints; at most four; volatile tail excluded; reads/writes recorded from usage")
        elif model == router.MINIMAX_MODEL:
            result.update(quantization="unknown")
        elif model == router.NEMOTRON_MODEL:
            result.update(reasoning=dict(enabled=True, exclude=False), reasoning_effort_supported=False,
                          effort=dict(requested=mr.EFFORT or "default", sent=None))
    elif provider == "openai":
        result.update(endpoint=mr._endpoint(provider).removesuffix("/chat/completions") + "/responses",
                      reasoning_summary="auto", conversation_state="stateless; store=false")
    if cm.enabled() and cm.route(model):
        result.update(cm.settings(model))
    elif provider == "anthropic":
        result.update(thinking="adaptive", thinking_display="summarized")
    elif provider == "gemini":
        result.update(endpoint=_gemini_endpoint(model), thinking_level=GEMINI_THINKING_LEVEL,
                      include_thoughts=True, effort=dict(requested="medium", sent="medium"),
                      cache="automatic prefix (native Gemini)", conversation_state="stateless; no thought replay")
    return result


def install():
    """Install once in the prototype; the archived core runner stays unchanged."""
    if _ORIGINAL:
        return
    router.install()
    _ORIGINAL.update(call=mr.call, trace=mr._trace_call, usage=mr._absorb_usage, settings=mr.api_settings)
    mr.call, mr._trace_call, mr._absorb_usage, mr.api_settings = _call, _trace_call, _absorb_usage, _settings
    if cm.enabled():                                  # AGII_HARNESS=continuous: one conversation per fight (default off)
        cm.wrap_run_fight(mr)
