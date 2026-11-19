"""Claude (Anthropic Messages API) backend for modelrun, through the official `anthropic` SDK (2026-10-14).

modelrun talks to OpenAI, Gemini and DeepSeek over plain urllib with an OpenAI-shaped body. Claude is different in
the one way that matters for cost: prompt caching is NOT automatic. A request is cached only up to blocks that carry
`cache_control`, and a later request reads that entry only if the cached prefix ends on one of ITS block boundaries.

So modelrun hands this backend the user text already cut into blocks (`modelrun.build_act_blocks` /
`build_pick_blocks`), with the separator newline at the START of each block and the stable/volatile boundary marked:
    handover            marked      -- stable for the whole life
    history header      -
    one block per line  marked: the last line, and the two lines before it whose number is a multiple of 15
                        (modelrun.LOOKBACK_STEP). Each breakpoint looks back at most 20 blocks for an earlier entry;
                        consecutive actions are a few lines apart, but two map choices have a whole fight (20-40
                        lines) between them, and the fixed multiples give both requests markers at the same places.
    tail                -           -- current screen, hand, "Your move:" (or the choice prompt) -- never cached
At most four markers per request, which is the API limit.
Joined, the blocks are byte-for-byte the text every other provider receives. Measured offline on the recorded
chains (scripts/cache_sim.py): reads 95-97%, writes 2-3%, the rest at base price -> about 9-10% of the base input
price on Claude Opus 5.5 (reads $0.20 vs $4.00 per MTok, 5-minute writes 1.25x, minimum cacheable prefix 512 tokens).
A top-level automatic `cache_control` would put the breakpoint after the unique tail and never read anything back.

Thinking: no `thinking` parameter (adaptive; it cannot be disabled on Opus 5.5). Effort: `output_config.effort`
from modelrun.effort_for -- "high" for every provider since the user's ruling of 2026-10-15 (it replaced the
2026-10-14 "each provider's default"). One value per chain; changing it mid-run would invalidate the cache.

Deliberately OFF: server-side refusal `fallbacks`. A fallback answers with a different model, which would put another
model's decisions into this model's record. A refusal comes back as an empty answer with stop_reason "refusal",
modelrun treats it as an unparseable action, and the count lands in the record's usage.
"""
from __future__ import annotations

import anthropic

MAX_TOKENS = 16000        # non-streaming ceiling the SDK guidance gives; adaptive thinking counts toward it
MAX_RETRIES = 6           # same budget as modelrun's own transport retries (429, 5xx, connection errors)
CACHE_TTL = None          # None = the default 5-minute TTL; calls in a chain are seconds apart
MAX_BREAKPOINTS = 4       # API limit per request

_CLIENTS: dict = {}


def _client(key: str):
    c = _CLIENTS.get(key)
    if c is None:
        c = _CLIENTS[key] = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    return c


def build_request(model: str, system: str, blocks, effort: str | None = None) -> dict:
    """The keyword arguments for `messages.create`. `blocks` = [(text, cache_here)]; empty texts are dropped
    (the API rejects empty text blocks); at most the last MAX_BREAKPOINTS marks are kept."""
    blocks = [(t, m) for t, m in blocks if t]
    marked = {i for i, (_, m) in enumerate(blocks) if m}
    keep = set(sorted(marked)[-MAX_BREAKPOINTS:])
    cc = {"type": "ephemeral"} if CACHE_TTL is None else {"type": "ephemeral", "ttl": CACHE_TTL}
    content = []
    for i, (text, _) in enumerate(blocks):
        b = {"type": "text", "text": text}
        if i in keep:
            b["cache_control"] = dict(cc)
        content.append(b)
    req = dict(model=model, max_tokens=MAX_TOKENS,
               system=[{"type": "text", "text": system}],
               messages=[{"role": "user", "content": content}])
    if effort:
        req["output_config"] = {"effort": effort}       # 整条链固定一个值；中途改会让缓存全部失效
    return req


def fatal_message(status: int, message: str) -> str:
    """What to tell the operator when a request cannot succeed by waiting."""
    low = (message or "").lower()
    if status == 402 or "credit balance" in low or "billing" in low:
        return f"额度用尽或计费问题，重试无用。请先充值再跑。\nHTTP {status}: {message}"
    if status == 401:
        return f"Anthropic 钥匙无效（~/.config/agii/anthropic.key 或 ANTHROPIC_API_KEY）。\nHTTP {status}: {message}"
    if status == 404:
        return f"模型名不对或这个账号用不了这个模型。\nHTTP {status}: {message}"
    return f"HTTP {status}: {message}"


def call(model: str, system: str, blocks, key: str, effort: str | None = None):
    """One request. Returns (text, usage, stop_reason); usage keeps Anthropic's own field names."""
    try:
        msg = _client(key).messages.create(**build_request(model, system, blocks, effort))
    except anthropic.APIStatusError as e:              # every non-2xx after the SDK's own retries
        raise SystemExit(fatal_message(e.status_code, getattr(e, "message", str(e))))
    except anthropic.APIConnectionError as e:          # network, after retries
        raise SystemExit(f"连不上 Anthropic（已重试 {MAX_RETRIES} 次）：{e}")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    u = msg.usage
    usage = dict(input_tokens=getattr(u, "input_tokens", 0) or 0,
                 cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                 cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                 output_tokens=getattr(u, "output_tokens", 0) or 0)
    return text, usage, msg.stop_reason


def settings(effort: str | None = None) -> dict:
    """Written into every record, so a later reader knows what this backend sent."""
    return dict(provider="anthropic", sdk=f"anthropic {anthropic.__version__}", max_tokens=MAX_TOKENS,
                thinking="provider default (adaptive; cannot be disabled on Opus 5.5)",
                output_config_effort=effort or "not sent (provider default medium)", fallbacks="off",
                cache="explicit breakpoints on the handover and the last history line, 5-minute TTL")
