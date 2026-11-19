"""Per-model API prices (USD per million tokens), for the spending cap and the per-record cost (2026-10-14).

Every row names where it was read and when. A model without a row has no price: modelrun then refuses to start
when a budget cap is set (a cap that cannot be computed is not a cap). Set AGII_PRICE="in,read,write,out" to run
such a model under a cap with prices you have checked yourself.

`uncached_as_write`: the provider bills cache writes but its usage does not say how many tokens were written.
The cap then charges every uncached input token at the write price -- an upper bound, never an underestimate.
"""
from __future__ import annotations

import os

PRICES = {
    # prefix of the bare model name -> prices
    "claude-opus-5-5": dict(input=4.00, cache_read=0.20, cache_write=5.00, output=20.00, uncached_as_write=False,
                            long_context=None,
                            source="claude-api skill model table (cached 2026-10-06): $4 / $20, cache reads $0.20, "
                                   "5-minute cache writes 1.25x input"),
    "kimi-k3": dict(input=3.00, cache_read=0.30, cache_write=3.00, output=15.00, uncached_as_write=False,
                    long_context=None,
                    source="https://platform.kimi.ai/docs/pricing/chat (read 2026-10-15): cache-miss input $3, "
                           "cached input $0.30, cache write $3 (5-minute TTL; $6 for 1 hour), output $15; usage reports "
                           "prompt_tokens_details.cached_tokens and .cache_write_tokens"),
    # 峰谷计价：峰时（UTC 01–04、06–10，周一到周五，中国法定假日除外）是谷时的两倍。上限按峰时价算 = 上界。
    "deepseek-v4-pro": dict(input=1.32, cache_read=0.044, cache_write=1.32, output=3.96, uncached_as_write=False,
                            long_context=None,
                            source="https://api-docs.deepseek.com/quick_start/pricing (read 2026-10-15): deepseek-v4-pro "
                                   "(DeepSeek-V4-Pro-0813) peak $0.044 hit / $1.32 miss / $3.96 out; off-peak half "
                                   "($0.022 / $0.66 / $1.98); thinking mode on by default"),
    # qwen3.8-max：官方价目页这次没打开（404），第三方给的新加坡价（输入 $2、输出 $6、显式缓存创建 $2.50、命中 $0.17）
    # 没核实，所以不进表。核实后加一行，或者跑之前设 AGII_PRICE。
    "gpt-6.1-sol": dict(input=2.00, cache_read=0.10, cache_write=2.50, output=10.00, uncached_as_write=True,
                        long_context=dict(threshold=272_000, input_mult=2.0, output_mult=1.5),
                        source="https://developers.openai.com/api/docs/models/gpt-6.1-sol (read 2026-10-14): "
                               "input $2, cached input $0.10 (5%), cache writes $2.50 (1.25x), output $10; "
                               "prompts over 272K input tokens: 2x input and cache rates, 1.5x output"),
}


def price_for(model: str):
    env = os.environ.get("AGII_PRICE", "").strip()
    if env:
        i, r, w, o = (float(x) for x in env.split(","))
        return dict(input=i, cache_read=r, cache_write=w, output=o, uncached_as_write=False, long_context=None,
                    source="AGII_PRICE")
    bare = model.lower().split("/")[-1].strip()
    for prefix in sorted(PRICES, key=len, reverse=True):
        if bare.startswith(prefix):
            return PRICES[prefix]
    return None


def cost_usd(price: dict, prompt: int, cached: int, written: int, completion: int) -> float:
    """One request. `prompt` is the whole prompt; `cached` read from cache; `written` reported cache writes."""
    uncached = max(0, prompt - cached - written)
    in_mult = out_mult = 1.0
    lc = price.get("long_context")
    if lc and prompt > lc["threshold"]:
        in_mult, out_mult = lc["input_mult"], lc["output_mult"]
    write_tokens = written + (uncached if price.get("uncached_as_write") else 0)
    plain_tokens = 0 if price.get("uncached_as_write") else uncached
    usd = (plain_tokens * price["input"] + cached * price["cache_read"] + write_tokens * price["cache_write"]) * in_mult \
        + completion * price["output"] * out_mult
    return usd / 1e6
