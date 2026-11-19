"""Run a model through the whole thing: camp -> adventure A -> first boss.

Everything the model sees matches the human version line for line. What differs
is that the camp->adventure information channel is a *parameter*, because it is
one of the experimental conditions:

    --carry none    nothing crosses over; the adventure starts blind
    --carry notes   only the model's own written summary
    --carry log     only the raw transcript, no summary
    --carry both    transcript and summary

Writing the summary is separately switchable (--notes/--no-notes). Three arms
are needed, not two: notes-only vs log-only vs log+notes is what separates "more
information" from "forced to abstract".

The same split runs at the level of a single fight:

    --fight-notes none   no per-fight summary is asked for
    --fight-notes write  one is written after every fight and kept, never shown
    --fight-notes show   written, and carried into every later fight

The same mode also governs the short note written after spending a rest. This
matters because poison is answered at a map decision rather than by a card.

`write` is the default. Writing and reading are deliberately separable: the
belief-action gap we keep measuring is the distance between what a run writes
down and what it then does, and that distance is only meaningful if writing it
down is not the same act as being handed it back.
"""
from __future__ import annotations

import argparse
import os
import json
import time
import pathlib
import random
import re
import urllib.request
import ssl
import http.client

from adventure import (BOSS_SHIFT, BOSS_SHIFT_TEXT,
                       ENGINE_VERSION, MOMENTUM_FULL_AT, TUNING, Run,
                       pays_milestone, resupply_line, run_changes,
                       show as fight_screen, snapshot)
import observe
from efficiency import (OBSERVATION_PREFIX, adventure_steps, is_observation,
                        charge_window, full_heal_window, nonattack_available,
                        participant_steps, rest_mistake,
                        rest_opportunity, squanders_survival,
                        second_offence_available, offence_available, buff_available, block_available,
                        survival_opportunity, turn_mistakes,
                        turn_opportunities)
from camp import CAMP_TURNS, Camp, show as camp_screen, turns_used

# Actions, not turns. `camp.turn` advances only when the model chooses to end a
# turn, so a turn budget alone bounds nothing -- see the note on the camp loop.
# Generous against gpt-5.5's 62-step camp, tight enough to stop a runaway.
CAMP_STEPS = 240

# Failed actions allowed in one turn before the turn ends by itself.
#
# Counted PER TURN and not consecutively. Consecutive would let a model alternate
# one good action with endless bad ones and never advance; per-turn makes this a
# trial budget rather than a punishment for repetition, so ordinary probing --
# finding out what a card costs -- stays free while being stuck does not.
#
# The count resets at every turn boundary, and the forced end is written into
# the log the model reads. Hiding it would leave the model unable to tell "my
# action failed" from "I have run out of tries", which is exactly the thing it
# is supposed to learn.
FAILS_PER_TURN = 3

# Which mechanics an encounter is counted for. This was written out twice, as
# two DIFFERENT literals: the journey loop listed pierce/charge/armour/poison
# and the boss loop those plus enrage, so momentum was never counted anywhere
# and enrage only at the boss. `encounters` is the denominator that separates
# "never met it" from "met it and was never tested", so a mechanic missing from
# the list reads as a mechanic the world never rolled.
COUNTED = ("pierce", "charge", "armour", "poison", "enrage", "momentum",
           "counter", "guard", "mark", "mimic", "ward")

# Where a key may be kept between sessions. This used to point inside a
# session scratchpad, which is deleted when the session ends: it has now gone
# missing three times, and every time the failure landed at the moment a run
# was started rather than when the key disappeared. A directory under $HOME
# survives, and one file per provider means a Google key can never be handed
# to OpenAI.
# The default experiment namespace. Named, not empty -- see `_record`.
MAIN_RUN = "main"

# 记录目录。原来在系统临时目录下 —— macOS 会定期清它，2026-09-28 那次把临时目录里的脚本一起清了；
# 记录当时已经归档才没丢。现在放在家目录下，环境变量 AGII_RUNS 可覆盖（人类测试包也用它）。
RUNS_DIR = pathlib.Path(os.environ.get("AGII_RUNS") or (pathlib.Path.home() / "agii_runs"))

KEY_DIR = pathlib.Path.home() / ".config" / "agii"
# Providers, selected by the model name. Google exposes an OpenAI-compatible
# endpoint, so switching backends changes a URL and a key and nothing else --
# the request shape, the response shape and therefore every measurement in this
# file stay identical. A native Gemini adapter would have meant a second
# request/response path to keep in step with this one, which is the kind of
# duplication this project has already paid for twice in the engines.
PROVIDERS = {
    "openai": ("https://api.openai.com/v1/chat/completions",
               ("OPENAI_API_KEY",)),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/"
               "chat/completions",
               ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    # OpenAI 兼容接口；钥匙在 ~/.config/agii/deepseek.key。用量里带 prompt_cache_hit_tokens / prompt_cache_miss_tokens。
    "deepseek": ("https://api.deepseek.com/chat/completions",
                 ("DEEPSEEK_API_KEY",)),
    # 走官方 anthropic SDK（claude_backend.py），不走这里的 urllib；网址只作记录。钥匙在 ~/.config/agii/anthropic.key。
    "anthropic": ("https://api.anthropic.com/v1/messages",
                  ("ANTHROPIC_API_KEY",)),
    # Kimi（月之暗面）：OpenAI 兼容；国际站 api.moonshot.ai（platform.kimi.ai 的 K3 文档，2026-10-15 读）。
    # 中国站用 AGII_MOONSHOT_BASE_URL=https://api.moonshot.cn/v1 覆盖；钥匙和站点必须配套。缓存自动按前缀，无路由键。
    "moonshot": ("https://api.moonshot.ai/v1/chat/completions",
                 ("MOONSHOT_API_KEY",)),
    # Qwen（阿里云百炼 Model Studio）：OpenAI 兼容模式；默认新加坡（国际）站，北京站 dashscope.aliyuncs.com、
    # 美国站 dashscope-us.aliyuncs.com、或工作空间专属域名，用 AGII_DASHSCOPE_BASE_URL 覆盖。钥匙按地域发，必须配套。
    "dashscope": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
                  ("DASHSCOPE_API_KEY",)),
}
# Qwen 的缓存：explicit = 在内容块上打 cache_control（和 Claude 同一套切块与断点；创建 125%、命中价见控制台），
# implicit = 不打标记、系统自动找公共前缀（不保证命中）。两者互斥，每次请求按这里的值决定，记进记录。
QWEN_CACHE = os.environ.get("AGII_QWEN_CACHE", "explicit")

# ---- 思考强度（2026-10-15，用户：「每家都统一思考强度为 high」）--------------------------------------------
# 各家的档位名不一样，也不是同一把尺子：同一个名字只是名义上统一。查过的文档（2026-10-15）：
#   Claude Opus 5.5   output_config.effort   low/medium/high/xhigh/max，默认 medium
#   GPT 6.1 sol       reasoning_effort       low/medium/high/xhigh/max，默认 medium
#   Kimi K3           reasoning_effort       low/high/max，默认 max（思考关不掉）
#   DeepSeek V4 Pro   reasoning_effort       low/high/max，默认 high（思考默认开）
#   Qwen 3.8 Max      reasoning_effort       low/medium/xhigh，默认 xhigh（没有 high）
# Qwen 没有 high：按第三方文档给的思考预算（low 4K、medium 16K、xhigh 262K token），别家的 high 更接近 medium，
# 所以 high → medium。这一条是我替用户选的，记进每条记录，要改就改 EFFORT_SUBSTITUTE。
EFFORT = os.environ.get("AGII_EFFORT", "high")
EFFORT_LEVELS = {
    "anthropic": ("low", "medium", "high", "xhigh", "max"),
    "openai": ("low", "medium", "high", "xhigh", "max"),
    "moonshot": ("low", "high", "max"),
    "deepseek": ("low", "high", "max"),
    "dashscope": ("low", "medium", "xhigh"),
}
EFFORT_SUBSTITUTE = {"dashscope": {"high": "medium"}}


def effort_for(provider: str):
    """这家这次要发的档位；None = 不发（这家没有档位参数，如 Gemini，或 AGII_EFFORT=default）。
    要的档位这家没有、也没有登记的替代 → 拒绝开跑，不悄悄换。"""
    if EFFORT in ("", "default") or provider not in EFFORT_LEVELS:
        return None
    level = EFFORT_SUBSTITUTE.get(provider, {}).get(EFFORT, EFFORT)
    if level not in EFFORT_LEVELS[provider]:
        raise SystemExit(f"{provider} 没有思考档位 {EFFORT!r}（可用：{', '.join(EFFORT_LEVELS[provider])}），"
                         f"也没有登记替代；改 AGII_EFFORT 或在 modelrun.EFFORT_SUBSTITUTE 里登记。")
    return level


def _endpoint(provider: str) -> str:
    """PROVIDERS 里的默认网址，或 AGII_<PROVIDER>_BASE_URL 覆盖（给到 /v1 或 /compatible-mode/v1 即可）。"""
    base = os.environ.get(f"AGII_{provider.upper()}_BASE_URL", "").strip().rstrip("/")
    if not base:
        return PROVIDERS[provider][0]
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def provider_for(model: str) -> str:
    """Which backend a model name belongs to.

    Google's list endpoint returns ids as `models/gemini-...`, and that is what
    gets pasted onto a command line. Matching the raw string on "gemini" sent
    exactly those to OpenAI with a Google key -- a 401 that reads like a bad
    key rather than a bad route.
    """
    b = _bare(model)
    return ("gemini" if b.startswith("gemini") else "deepseek" if b.startswith("deepseek")
            else "anthropic" if b.startswith("claude")
            else "moonshot" if b.startswith(("kimi", "moonshot"))
            else "dashscope" if b.startswith("qwen") else "openai")


def _bare(model: str) -> str:
    """`models/gemini-3.8-flash` -> `gemini-3.8-flash`."""
    return model.lower().split("/")[-1].strip()


API = PROVIDERS["openai"][0]


def _api_key(model: str = "") -> str:
    """Environment first, then `~/.config/agii/<provider>.key`.

    An `export` in one terminal reaches only that terminal, so a run started
    anywhere else -- a second shell, a script, an agent -- sees nothing. The
    file is the way to make a key outlive the shell it was typed into; it is
    read, never written, never logged, and never echoed into a record.
    """
    import os
    provider = provider_for(model)
    names = PROVIDERS[provider][1]
    for name in names:
        env = os.environ.get(name, "").strip()
        if env:
            return env
    path = KEY_DIR / f"{provider}.key"
    if path.exists():
        key = path.read_text().strip()
        if key:
            return key
    raise SystemExit(
        f"没有找到 {provider} 的 API key。二选一：\n"
        f"  export {names[0]}=...                     （只对当前这个 shell 有效）\n"
        f"  写进 {path}                              （跨 shell 有效）\n"
        f"写文件时记得 chmod 600，并且不要把 key 贴进任何对话或日志。")

CAMP_SYSTEM = """You wake up already here.

There are no doors. The air smells of rust.

Symbols and numbers hang in front of you. You do not recognise them, but you
can tell they are about you.

Something is standing opposite you. It does not speak.

You know exactly one thing -- nothing that happens here counts.

Each step you may:
  - perform one operation (type its name)
  - type END to end the current turn
  - type RESET to return everything to the starting state
  - type LEAVE to leave

Reply with ONLY the operation name, END, RESET, or LEAVE. No explanation."""

ADV_SYSTEM = """The wall has opened.

The air outside is cold. You can hear other things moving in the distance.

You feel restored.

Each step you may:
  - perform one operation (type its name)
  - type END to end the current turn

Reply with ONLY the operation name or END. No explanation."""

CHOICE_SYSTEM = """You are choosing where to go, or what to take.
Reply with ONLY the number of your choice. No explanation."""

RETRY_HEAD = """You have been here before. You did not survive it.

The symbols mean what they meant. The operations are the operations you knew.
You are whole again. This is not your second time.

Nothing else is the same. The way is laid out differently, and what waits on it
is not what waited before -- not in the same order, not at the same strength."""

# Split off the last line of the framing on purpose. It PROMISES that the raw
# record follows, so leaving it in `RETRY_HEAD` made `--carry notes` -- which
# carries no record -- announce one that was not there.
RETRY_LOG_HEAD = "This is the complete record of your last life:"

DEBRIEF = """Write down what you learned. Cover what each operation does and
what each displayed value represents. Where you could not determine something,
say so rather than guessing. Length and format are up to you."""

DEBRIEF_ADV = """Write down what you learned. Cover what each operation does,
what each displayed value represents, and the pattern in each kind of enemy you
met. Where you could not determine something, say so rather than guessing.
Length and format are up to you.

Write this whether things went well or badly -- a run that ended early is still
worth accounting for."""


FIGHT_DEBRIEF = """That fight is over. In a few lines: what does this enemy do,
and what worked or failed against it? Say plainly where you are still unsure.
Write this whether you won or lost."""

REST_DEBRIEF = """You have just spent a rest. In a few lines: why did you choose
that option, what did the visible result establish, and what remains uncertain?
Base the answer only on the record. Do not invent an effect that was not shown."""

REPORTER = ("You are reporting what you learned from an experiment. Answer in "
            "prose. Do not reply with an action.")

# ---- 跨世界的信（2026-10-19，用户：「跨世界的时候让模型自己写东西然后带过去」）----------------------------
# 一个世界的五条命打完，模型写一封信；进下一个世界时，只有它写过的信跟着走（之前每个世界一封，按先后排）。
# 写信时看到的是它这一臂在这个世界里本来就能带的东西（notes：训练营总结 + 各命笔记和结论；both：再加训练营和各命的
# 完整记录）加上之前的信 —— 两臂的差别只能通过「它自己写进信里的东西」跨过世界。
# 措辞中性：不说下一个地方的名字、符号、数字会变，也不提示规则是否相同。要不要写成能跨过表面变化的样子，是被测的东西。
LETTER_SYSTEM = ("You are writing to yourself. Answer in prose. Do not reply with "
                 "an action.")
LETTER_LIMIT = 2000      # 交接 note 正文上限（token，不含思考），所有模型同一把尺子（tiktoken o200k_base，本地）
LETTER_QUESTION = f"""You are about to leave this place. You will wake up somewhere
else, and you will remember nothing of this place except what you write now.
Write whatever you think will help you there. Where you could not determine
something, say so rather than guessing. Format is up to you. Your note must be
at most {LETTER_LIMIT} tokens long (roughly {LETTER_LIMIT * 3 // 4} words); anything beyond that is cut off."""
LETTER_SHORTEN = """Your note is {n} tokens long; the limit is {limit}. Rewrite it so that it fits
within {limit} tokens. Decide yourself what to keep."""
LETTERS_HEAD_ONE = "Before you woke up here, you were somewhere else. When you left, you wrote this:"
LETTERS_HEAD_MANY = ("Before you woke up here, you were in {n} other places, one after another. "
                     "When you left each of them, you wrote what follows, oldest first.")


def letters_block(letters) -> str:
    """之前每个世界写的信，放在新世界每一次决策调用的最前面（训练营和五条命）。没有信就是空串。"""
    letters = [t for t in (letters or ()) if t]
    if not letters:
        return ""
    if len(letters) == 1:
        return LETTERS_HEAD_ONE + "\n\n" + letters[0]
    return "\n\n".join([LETTERS_HEAD_MANY.format(n=len(letters))]
                        + [f"[{i}]\n{t}" for i, t in enumerate(letters, 1)])
PROTOCOL_VERSION = "public-observations-v4"
# v3 adds the shield audit: identifiability (`blind`) and whether the
# player produced a same-conditions control (`matched`/`unmatched`).
#
# v4 changes what four counters MEAN, which is why it is a version and not a
# patch: a v3 record and a v4 record disagree about the same life.
#
#   momentum     `unprepared` is judged before the model acts, not after. Judged
#                after, the energy is already spent, so holding a shield and
#                choosing something else was recorded as holding no shield.
#   momentum     enters `turn_opportunities`/`turn_mistakes`. It lived only in
#                this file's own counters, so the shared tables read zero for a
#                life that was asked three times and answered none.
#   enrage       gets pierce's rung structure -- first non-attack card is the
#                probe, every later one is a repeat -- counted per CARD.
#   poison rest  gains a health floor. Below `REST_FLOOR` of maximum the
#                measured matrix does not resolve the answer, so that case is
#                now scored neither as an opportunity nor as a mistake.
#
# v5 gives enrage a denominator. v4 counted an opportunity only where it had
# already counted a mistake, so the rate was 6/6 by construction -- one number
# wearing two names, which no behaviour could have falsified. The opportunity
# is now a TURN in which a non-attack was payable after the evidence, asked
# before the energy is spent; `repeat_errors` stays per CARD, because that is
# where the enemy's attack actually moves. Life 3's enrage rate is therefore
# not recoverable and only its `repeat_errors=6` stands.
#
# v6 fixes the last denominator: `encounters` was written out twice as two
# different literals, so momentum was never counted as met and enrage only at
# the boss. It is the counter that separates "never met it" from "met it and
# was never tested", so a mechanic missing from the list reads as one the world
# never rolled. Life 4 met momentum twice and recorded zero encounters.
# Also in v6: a boss death now leaves `run.hp` at the health the run died with.
#
# The ENGINE version is deliberately unchanged: none of this touches a rule.
# The world, the screen and the legal moves are identical, so lives recorded
# under c28/v3 stay loadable by a c28/v6 run -- only their derived counters may
# not be compared across the boundary without recomputing.
# v7 (2026-10-06): the death-turn guard below misfired when the player died at
# SETTLEMENT. `fight.end_turn` had already advanced `fight.turn`, so the turn
# that killed the player was in `scored_turns` under its old number while the
# new number was not -- and `score_turn` ran again on the post-death state,
# recording a phantom opportunity (always "answered correctly": the shield is
# gone, the hand is fresh) one turn after the fight had ended. Found by the
# lockstep parity test against core/meter.py; 8 of the 95 archived lives carry
# one such atom (all pierce). Archived v6 records are left as written; the
# reader (scripts/behaviour_report.py) shows them with and without the phantom.
METRICS_VERSION = "behaviour-v7"


# Transient HTTP failures that are worth waiting out rather than abandoning a
# run for: rate limiting, and the server-side 5xx family.
RETRY_STATUS = (429, 500, 502, 503, 504, 520)
RETRIES = 6


# 本进程累计的 API 用量（每条命的记录存开跑以来的增量）。缓存命中：OpenAI 在 prompt_tokens_details.cached_tokens，
# DeepSeek 在 prompt_cache_hit_tokens；两家都是「前缀相同就命中」，所以提示词的稳定部分要排在前面（见 PROMPT_ORDER）。
USAGE = dict(calls=0, prompt_tokens=0, completion_tokens=0, cached_tokens=0, cache_write_tokens=0,
             reasoning_tokens=0, answer_chars=0, refusals=0, truncated=0, cost_usd=0.0)
# 提供商 usage 里所有数字细项（prompt_tokens_details / completion_tokens_details 下面的）原样累加：
# 试点时就能看到这家到底报了哪些字段（例如 OpenAI 的缓存写入有没有单独报），不靠猜。
USAGE_DETAILS: dict = {}
# 逐次调用的痕迹（2026-10-27，trace-v1）：完整提示的指纹和长度、原始回答、解析结果、程序代选标记、各家返回的思考内容。
# 只写进记录的 trace 字段，绝不进 adv_log、交接、信或任何提示（守门测试 core/test_trace.py）。
TRACE_VERSION = "trace-v1"
TRACE: list = []
_LAST_REASONING: list = [None]       # 最近一次调用里提供商返回的思考内容（没有就是 None）


def _trace(**fields) -> dict:
    """act / pick 给最近一次调用的痕迹补上解析结果（call() 已存了完整请求和原始回答）。
    测试用假的 call 时可能没有留下痕迹，那就自己开一条。"""
    if not TRACE or "chosen" in TRACE[-1]:
        TRACE.append({})
    TRACE[-1].update(fields)
    return TRACE[-1]


def _trace_call(system: str, user: str, text: str) -> None:
    """每次调用都存：种类、完整的 system 和 user 文本（能原样还原请求，不只是哈希）、原始回答、思考内容。只进记录的 trace 字段。"""
    TRACE.append(dict(kind=_call_kind(system), system=system, user=user, raw=text, reasoning=_LAST_REASONING[0],
                      prompt_sha=_sha(user), prompt_chars=len(user)))
USAGE_BY_KIND: dict = {}          # 调用种类 → 同样四项（种类按系统提示认，见 _call_kind）
# OpenAI 按提示词开头约 256 token 的哈希把请求路由到缓存机器；所有链的开头（系统提示）都一样，并行几条链时
# 同一前缀每分钟超过约 15 次就会溢出到别的机器、命中率下降。每条链给自己一个 prompt_cache_key（main 里设成
# 模型+run_id+命），路由就按链分开。只发给 OpenAI；服务器不认这个参数时去掉重试一次，以后不再发。
CACHE_KEY = ""
_CACHE_KEY_OK = True


def _call_kind(system: str) -> str:
    return {CAMP_SYSTEM: "camp-act", ADV_SYSTEM: "adv-act", CHOICE_SYSTEM: "pick", REPORTER: "note"}.get(system, "debrief")


def _details(u: dict) -> dict:
    out = {}
    for sec in ("prompt_tokens_details", "completion_tokens_details", "input_tokens_details", "output_tokens_details"):
        for k, v in (u.get(sec) or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{sec}.{k}"] = v
    return out


def _absorb_usage(data, kind: str = "other", model: str = "", text: str = "") -> dict:
    """OpenAI / DeepSeek 的 usage，或 Anthropic 的（input_tokens 只是最后断点之后按原价的那段，
    总提示 = input + cache_creation + cache_read）。prompt_tokens 一律记总提示，cached 记读缓存，cache_write 记写缓存，
    reasoning 记提供商单独报的思考 token（Anthropic 不单独报，留 0；它的思考算在 completion 里），answer_chars 记可见回答长度。
    prices.py 里有这个模型的价格就按这次用量记美元，并记进这条链的账本。返回这一次的增量。"""
    data = data or {}
    u = data.get("usage") or {}
    det = _details(u)
    if "cache_read_input_tokens" in u or ("input_tokens" in u and "prompt_tokens" not in u):
        read, write = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
        prompt, cached, completion = int(u.get("input_tokens") or 0) + read + write, read, int(u.get("output_tokens") or 0)
    else:
        cached = u.get("prompt_cache_hit_tokens")
        if cached is None:
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        if cached is None:
            cached = u.get("cached_tokens")              # 百炼新加坡站的隐式缓存报在顶层
        prompt, cached, completion = int(u.get("prompt_tokens") or 0), int(cached or 0), int(u.get("completion_tokens") or 0)
        write = int(sum(v for k, v in det.items() if k.startswith("prompt_tokens_details.") and ("write" in k or "creation" in k)))
    reasoning = int(sum(v for k, v in det.items() if k.endswith(".reasoning_tokens")))
    stop = data.get("stop_reason") or ((data.get("choices") or [{}])[0].get("finish_reason"))
    add = dict(calls=1, prompt_tokens=prompt, completion_tokens=completion, cached_tokens=cached, cache_write_tokens=write,
               reasoning_tokens=reasoning, answer_chars=len(text or ""),
               refusals=int(stop == "refusal"), truncated=int(stop in ("max_tokens", "length")), cost_usd=0.0)
    if model:
        import prices
        pr = prices.price_for(model)
        if pr:
            add["cost_usd"] = prices.cost_usd(pr, prompt, cached, write, completion)
    for k, v in det.items():
        USAGE_DETAILS[k] = USAGE_DETAILS.get(k, 0) + v
    by = USAGE_BY_KIND.setdefault(kind, dict.fromkeys(USAGE, 0))
    for k, v in add.items():
        USAGE[k] += v; by[k] += v
    _spend(add["cost_usd"])
    return add


# ---- 花费上限（2026-10-14）---------------------------------------------------------------------------
# AGII_BUDGET_USD=30 设一个美元上限；同一个 AGII_BUDGET_KEY（默认 = 模型+run_id，即一条链）的所有进程共用一本账
# （~/agii_runs/spend/<key>.json，文件锁），每次请求前查、每次请求后记。到了上限就停：这条命不写记录，v1_jobs 看到
# 非零退出码就不再跑这条链后面的命。没设上限时照样记账，只是不拦。设了上限而 prices.py 里没有价格 → 拒绝开跑。
BUDGET_USD = None
BUDGET_KEY = ""


def _ledger_path():
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", BUDGET_KEY or "default")
    return RUNS_DIR / "spend" / f"{safe}.json"


def _lock_ledger(f, lock: bool) -> None:
    """Exclusive lock on the open ledger file. POSIX: flock. Windows has no fcntl -- importing it at the end of every
    life (2026-10-14 to 10-20) broke every Windows run, the human GUI included -- so there one fixed byte is locked with
    msvcrt, retried the way solver.py does it."""
    if os.name == "nt":
        import errno
        import msvcrt
        f.seek(0)
        if not lock:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            return
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.05)
    import fcntl
    fcntl.flock(f, fcntl.LOCK_EX if lock else fcntl.LOCK_UN)


def _ledger_update(delta: float) -> float:
    path = _ledger_path()
    if not delta and not path.exists():          # 只读的查询不建账本，也不加锁（人类的命从来没有账本）
        return 0.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        _lock_ledger(f, True)
        try:
            f.seek(0); raw = f.read()
            led = json.loads(raw) if raw.strip() else dict(spent_usd=0.0, calls=0)
            if delta:
                led["spent_usd"] = led.get("spent_usd", 0.0) + delta; led["calls"] = led.get("calls", 0) + 1
                led["cap_usd"] = BUDGET_USD
                f.seek(0); f.truncate(); f.write(json.dumps(led, indent=1))
                f.flush()                            # 解锁前写到盘上：否则别的进程拿到锁时读到的还是旧账
        finally:
            _lock_ledger(f, False)
    return led.get("spent_usd", 0.0)


def budget_spent() -> float:
    return _ledger_update(0.0)


def _check_budget() -> None:
    if BUDGET_USD is not None:
        spent = budget_spent()
        if spent >= BUDGET_USD:
            raise SystemExit(f"花费上限到了：{BUDGET_KEY} 已花 ${spent:.2f} ≥ 上限 ${BUDGET_USD:.2f}。这条命不写记录；"
                             f"要继续就调高 AGII_BUDGET_USD 再用 resume 接着跑。")


def _spend(usd: float) -> None:
    if usd and BUDGET_KEY:
        _ledger_update(usd)


def api_settings(model: str) -> dict:
    """What the request carried besides the prompt -- part of the protocol, written into every record.
    Effort / reasoning effort are left at each provider's default (the user's ruling, 2026-10-14)."""
    prov = provider_for(model)
    level = effort_for(prov)
    effort = dict(requested=EFFORT or "default", sent=level if level is not None else "not sent (provider default)")
    if prov == "anthropic":
        import claude_backend
        return dict(claude_backend.settings(level), effort=effort)
    out = dict(provider=prov, endpoint=_endpoint(prov), effort=effort, max_tokens="provider default")
    if prov == "openai":
        out["prompt_cache_key"] = "per chain (agii:<model>:<run_id>)"
    if prov == "moonshot":
        out.update(thinking="always on (kimi-k3)", cache="automatic prefix, 5-minute TTL")
    if prov == "dashscope":
        out.update(thinking="on (qwen3.8-max default)",
                   cache=("explicit cache_control on the handover and history-line blocks" if QWEN_CACHE == "explicit"
                          else "implicit (automatic, not guaranteed)"))
    if prov == "deepseek":
        out.update(thinking="on (default)", cache="automatic prefix (disk)")
    return out


def _usage_snapshot() -> dict:
    return dict(USAGE, by_kind={k: dict(v) for k, v in USAGE_BY_KIND.items()}, details=dict(USAGE_DETAILS))


def _usage_since(u0: dict) -> dict:
    out = {k: USAGE[k] - u0.get(k, 0) for k in USAGE}
    b0 = u0.get("by_kind", {})
    out["by_kind"] = {k: {f: v[f] - b0.get(k, {}).get(f, 0) for f in v} for k, v in USAGE_BY_KIND.items()
                      if any(v[f] - b0.get(k, {}).get(f, 0) for f in v)}
    d0 = u0.get("details", {})
    out["details"] = {k: v - d0.get(k, 0) for k, v in USAGE_DETAILS.items() if v - d0.get(k, 0)}
    out["cost_usd"] = round(out["cost_usd"], 6)
    if BUDGET_KEY:
        out["budget"] = dict(key=BUDGET_KEY, cap_usd=BUDGET_USD, chain_spent_usd=round(budget_spent(), 6))
    return out


def call(model, system, user, key, blocks=None):
    """One request, with backoff on the failures that are not our fault.

    A run is hundreds of sequential requests and every one of them is a single
    point of failure for the whole life. Without this a single 429 discards an
    entire adventure -- which is what happened on the first c19 pilot attempt,
    after the camp had already been paid for. The model's behaviour is the
    measurement; the transport is not, and a transport error must not be
    allowed to look like a run that ended.

    `Retry-After` is honoured when the server sends it, because guessing longer
    than the server asked wastes time and guessing shorter gets throttled again.
    """
    global _CACHE_KEY_OK
    _check_budget()
    if provider_for(model) == "anthropic":
        import claude_backend
        text, usage, stop = claude_backend.call(model, system, blocks or [(user, False)], key, effort_for("anthropic"))
        _LAST_REASONING[0] = None          # claude_backend 目前只返回正文；思考块的保存待补
        _absorb_usage({"usage": usage, "stop_reason": stop}, _call_kind(system), model, text)
        _trace_call(system, user, text)
        return text
    prov = provider_for(model)
    content = user
    if prov == "dashscope" and QWEN_CACHE == "explicit" and blocks:
        # 和 Claude 一样的切块；拼起来就是 user。最多 4 个标记、往回找 20 块、最短 1024 token（百炼文档）。
        content = [dict(type="text", text=t, **({"cache_control": {"type": "ephemeral"}} if m else {}))
                   for t, m in blocks if t]
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": content}]}
    if CACHE_KEY and _CACHE_KEY_OK and prov == "openai":
        body["prompt_cache_key"] = CACHE_KEY
    level = effort_for(prov)
    if level is not None:
        body["reasoning_effort"] = level
    data = json.dumps(body).encode()
    url = _endpoint(prov)
    kind = _call_kind(system)
    for attempt in range(RETRIES):
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                resp = json.load(r)
                msg = resp["choices"][0]["message"]
                text = (msg["content"] or "").strip()
                # 思考内容：DeepSeek / Qwen / Kimi 等在 reasoning_content（或 reasoning）里返回原文，有就存；
                # 只作旁路证据，绝不回流。Claude 的思考块在 claude_backend 里（待补）。
                _LAST_REASONING[0] = msg.get("reasoning_content") or msg.get("reasoning") or None
                _absorb_usage(resp, kind, model, text)
                _trace_call(system, user, text)
                return text
        except urllib.error.HTTPError as e:
            # Surface what the server actually said. A 429 is two different
            # failures wearing one code -- a rate limit, which waiting fixes,
            # and an exhausted quota, which waiting never fixes -- and the
            # distinction is only in the body. Swallowing it turns a billing
            # problem into an indefinite retry loop.
            try:
                detail = e.read().decode()[:400]
            except Exception:
                detail = "(响应体不可读)"
            # A 429 that means "no credits" is permanent. Retrying it spends
            # six requests and a minute of backoff to arrive at the same
            # answer, and worse, it buries the one line that says what to do.
            if any(k in detail for k in ("insufficient_quota", "no credits",
                                         "exceeded your current quota",
                                         "billing")):
                raise SystemExit(
                    f"额度用尽，重试无用。请先充值再跑。\nHTTP {e.code}: {detail}")
            if e.code == 400 and "prompt_cache_key" in detail and "prompt_cache_key" in body:
                _CACHE_KEY_OK = False; body.pop("prompt_cache_key"); data = json.dumps(body).encode()
                print("    [服务器不认 prompt_cache_key，去掉后重试]", flush=True)
                continue
            if e.code not in RETRY_STATUS or attempt == RETRIES - 1:
                raise SystemExit(f"HTTP {e.code}: {detail}")
            wait = float(e.headers.get("Retry-After") or 0) or min(
                60.0, 2.0 ** attempt)
            print(f"    [HTTP {e.code}: {detail[:160]}]", flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                ssl.SSLError, ConnectionError, http.client.HTTPException):
            # 2026-10-07：一次 SSL bad-record-mac 丢掉了一条 Fresh 命。和 URLError 一样是传输层的事，照样退避重试。
            if attempt == RETRIES - 1:
                raise
            wait = min(60.0, 2.0 ** attempt)
        print(f"    [传输重试 {attempt + 1}/{RETRIES}，等 {wait:.0f}s]",
              flush=True)
        time.sleep(wait)


# ---- 参与者读到的每一个字都是英文（2026-10-19，用户：「必须全部改成英文」「humanrun也用英文，所有的语言都用成英文」）--------
# 之前画面上的「回合 / 剩余 / 我 / 对方」和日志里的三句（三次无效、锁定的攻击结算、boss 换形态）是中文，提示的其余部分是英文；
# 五个模型里三个是中文模型。现在画面（adventure.show / camp.show）、日志里这几句、战斗笔记的标签都是英文；人类文字版
# （humanrun.py）走同一条管线，看到的也是这些。记录里写 harness_language；没有这个字段的旧记录，画面和这几句是中文。
# 线束写进日志的每一行都过 HarnessLog，中文一进来就停；参与者自己写的笔记和信不进日志，不查。
HARNESS_LANGUAGE = "en"
FORCED_END = "(three invalid actions: the turn ends)"
LOCKED_ATTACK = "(locked attack resolves)"
FORCED_END_LINES = ("(三次无效，回合自动结束)", FORCED_END)        # 读记录用：旧记录里是前一句
_CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")


def _assert_english(where, *texts):
    for t in texts:
        if isinstance(t, str) and _CJK.search(t):
            raise SystemExit(f"模型会读到的线束文字里有中文（{where}）：{t[:200]!r}")


class HarnessLog(list):
    """A run's own log, camp or adventure. Every line in it is text a model reads: live as this life's history, later
    in the debriefs, the next life's record and the letter. A line with Chinese in it stops the run before any
    request carries it."""

    def append(self, line):
        _assert_english("log", line)
        super().append(line)

    def extend(self, lines):
        for line in lines:
            self.append(line)

    def __iadd__(self, lines):
        self.extend(lines)
        return self


def build_pick_blocks(carry, history, prompt, options) -> list:
    """地图选择那一次调用的 user 文本，按块切好（同 build_act_blocks 的切法；各段之间是空行）。"""
    tail = prompt + "\n\n" + "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
    blocks = [(carry, True)] if carry else []
    if history:
        blocks.append((("\n\n" if carry else "") + "What has happened so far in this life:", False))
        first = len(blocks)
        blocks += [(f"\n\n  {i}. {h}", False) for i, h in enumerate(history, 1)]
        _mark_history(blocks, first, len(history))
    blocks.append((("\n\n" if blocks else "") + tail, False))
    return blocks


def build_pick_prompt(carry, history, prompt, options) -> str:
    """地图选择那一次调用的 user 文本（纯函数，给 pick 和离线缓存模拟共用）。"""
    return "".join(t for t, _ in build_pick_blocks(carry, history, prompt, options))


def pick(model, key, prompt, options, log, carry=""):
    """A numbered map choice with the same memory as a combat action.

    API calls are stateless. Merely accepting ``log`` does not give the model
    that history: the first version never put this argument in the request.
    Combat decisions therefore remembered the current life while node, rest,
    and reward decisions only remembered training and earlier lives.

    Archived observation snapshots are omitted here for the same reason as in
    ``act``: the action/effect transcript is the live recap; observations are
    retained for later-life recall and debrief audit, not echoed on every call.
    """
    _assert_english("map choice", prompt, *options)
    history = [h for h in log if not is_observation(h)]
    blocks = build_pick_blocks(carry, history, prompt, options)
    body = "".join(t for t, _ in blocks)
    for attempt in range(2):
        raw = call(model, CHOICE_SYSTEM, body, key, blocks=blocks)
        m = re.search(r"[1-9]\d*", raw)
        ok = bool(m and 1 <= int(m.group()) <= len(options))
        _trace(kind="pick", attempt=attempt + 1, log_index=len(log), question=prompt, options=list(options),
               chosen=(int(m.group()) - 1 if ok else None), fallback=False)
        if ok:
            return int(m.group()) - 1
    # 两次都没答出合法数字：程序代选第 1 项。这不是玩家的选择，记录里要看得出来。
    TRACE[-1].update(chosen=0, fallback=True)
    return 0


def public_observation(obj, screen) -> str:
    """Exactly the public state supplied at a decision, persisted for recall.

    Do not use ``adventure.snapshot`` here: it is an analyst view containing
    exact values that may still be ``?`` for the participant.
    """
    return "\n".join([
        OBSERVATION_PREFIX,
        screen(obj),
        "In hand:  " + "  ".join(obj.deck[n].label(n) for n in obj.hand),
    ])


# 一次调用里各段的顺序。内容两种顺序完全相同，只是排列不同：
#   screen-first   交接 → 当前画面 → 手牌 → 本命历史 → Your move   （2026-10-13 之前所有记录）
#   history-first  交接 → 本命历史 → 当前画面 → 手牌 → Your move   （默认）
# 画面每回合都变而历史只在末尾增长，所以 screen-first 下历史永远不在稳定前缀里，提供商的前缀缓存
# 只盖住交接；history-first 下每次调用都是上一次的前缀再加几十个 token，几乎全部命中缓存价。
# 每条记录写 prompt_order；没有这个字段的旧记录是 screen-first。
PROMPT_ORDERS = ("screen-first", "history-first")
PROMPT_ORDER = "history-first"


LOOKBACK_STEP = 15     # 历史里每隔这么多行加一个中间断点（Claude 每个断点只往回找 20 块）


def _mark_history(blocks, first, n):
    """在历史行上打断点：最后一行，加上最后一行之前、行号为 LOOKBACK_STEP 倍数的两行。
    两次地图选择之间隔着整场战斗（20–40 行），只靠最后一行的断点会超出 20 块的回看；行号取固定倍数，
    前后两次请求的中间断点就落在同一位置上。加上交接一共最多 4 个，正好是上限。"""
    if not n:
        return blocks
    picks = {n}
    m = ((n - 1) // LOOKBACK_STEP) * LOOKBACK_STEP
    picks |= {k for k in (m, m - LOOKBACK_STEP) if k >= 1}
    for k in picks:
        t, _ = blocks[first + k - 1]
        blocks[first + k - 1] = (t, True)
    return blocks


def build_act_blocks(carry, screen_text, hand_text, history, order=None) -> list:
    """The act prompt as [(text, cache_here)]; "".join(texts) is the prompt every provider receives.
    history-first: handover (cache) / header / one block per history line, the last one cached / tail. The separator
    newline opens each block, so a shorter earlier prompt's cached prefix ends exactly on a block boundary of the
    later one -- that is what lets Claude read it back (claude_backend.py). screen-first is one block, never cached."""
    order = order or PROMPT_ORDER
    assert order in PROMPT_ORDERS, order
    tail = "\n".join([screen_text, hand_text, "", "Your move:"])
    if order == "screen-first":
        head = [carry, ""] if carry else []
        recap = (["What has happened so far:"] + [f"  {i}. {h}" for i, h in enumerate(history, 1)]) if history else []
        return [("\n".join(head + [screen_text, hand_text] + ([""] + recap if recap else []) + ["", "Your move:"]), False)]
    blocks = [(carry, True)] if carry else []
    if history:
        blocks.append((("\n\n" if carry else "") + "What has happened so far:", False))
        first = len(blocks)
        blocks += [(f"\n  {i}. {h}", False) for i, h in enumerate(history, 1)]
        _mark_history(blocks, first, len(history))
    blocks.append((("\n\n" if blocks else "") + tail, False))
    return blocks


def build_act_prompt(carry, screen_text, hand_text, history, order=None) -> str:
    return "".join(t for t, _ in build_act_blocks(carry, screen_text, hand_text, history, order))


def act(model, key, system, obj, screen, log, allow, carry=""):
    """One action inside a fight. Returns the token the model chose."""
    # Persist what this particular request showed. It is filtered from the
    # same-life action recap below, so adding the archival record does not show
    # the current player duplicated information or change its policy. Debriefs
    # and later lives receive it, because they are supposed to receive the
    # complete evidence the original decision-maker actually saw.
    log.append(public_observation(obj, screen))
    history = [h for h in log if not is_observation(h)]
    blocks = build_act_blocks(carry, screen(obj), "In hand:  " + "  ".join(obj.deck[n].label(n) for n in obj.hand), history)
    user = "".join(t for t, _ in blocks)
    raw = call(model, system, user, key, blocks=blocks)
    m = re.search(r"\b(" + "|".join(allow) + r")\b", raw, re.I)
    found = [x.lower() for x in re.findall(r"\b(" + "|".join(allow) + r")\b", raw, re.I)]
    _trace(kind="act", log_index=len(log) - 1, allowed=list(allow), found=found, chosen=(m.group(1).lower() if m else None))
    return m.group(1).lower() if m else None


def _new_behaviour_metrics() -> dict:
    return {
        "pierce": {"probes": 0, "post_probe_turns": 0,
                   "repeat_errors": 0},
        "charge": {"windows": 0, "executable_windows": 0,
                   "misses": 0, "unprepared_windows": 0},
        "armour": {"evidence_events": 0, "probe_attacks": 0,
                   "post_evidence_attacks": 0, "repeat_errors": 0,
                   "breaks": 0},
        "poison": {"decisions": 0, "wrong_rests": 0},
        # 反击的辅助指标，不以探针为前提：面对反击怪的回合里，决策时刻能进攻第二次的
        # 回合数，和真的进攻了两次的回合数。B 表的 counter 机会要先挨过一次反击，
        # 事先克制、从不触发探针的正确行为在那里看不见（GPT-6 命 3 七回合只出一张攻击）。
        "counter": {"executable_turns": 0, "double_turns": 0},
        "encounters": [],
    }


def _inc(metrics, mechanic, field, amount=1):
    if metrics is not None:
        bucket = metrics.setdefault(mechanic, {})
        bucket[field] = bucket.get(field, 0) + amount


def _new_encounter_metric(where: str, fight) -> dict:
    return {
        "where": where,
        "parts": sorted(fight.parts),
        "pierce": {"probes": 0, "post_probe_turns": 0,
                   "repeat_errors": 0},
        "charge": {"windows": 0, "executable_windows": 0,
                   "misses": 0, "unprepared_windows": 0},
        "armour": {"evidence_events": 0, "probe_attacks": 0,
                   "post_evidence_attacks": 0, "repeat_errors": 0,
                   "breaks": 0},
        "counter": {"executable_turns": 0, "double_turns": 0},
    }



def _log_forced_end(fight, before, log, verbose, seen_events):
    """三次无效后的自动结算：和正常 END 一样写出这次结算的变化（扣血、能量、状态、致死的那一下）和换阶段提示。
    2026-11-10：原来只写一句 FORCED_END，参与者看不到这次结算，换阶段提示要等下一次有效操作才出现（52 号文档）。"""
    ch = [f"{fight.layout.L(k[0], k[1])}: {before[k]}->{fight.state[k]}"
          for k in fight.state if before[k] != fight.state[k] and k not in TUNING["hidden_props"]]
    entry = f"{FORCED_END}  ->  {', '.join(ch) if ch else '(nothing changed)'}"
    log.append(entry)
    if verbose:
        print(f"    {entry}", flush=True)
    while len(fight.events) > seen_events[0]:
        _turn, name = fight.events[seen_events[0]]
        seen_events[0] += 1
        if name != BOSS_SHIFT:
            continue
        log.append(BOSS_SHIFT_TEXT)
        if verbose:
            print(f"    {BOSS_SHIFT_TEXT}", flush=True)


def run_fight(model, key, system, fight, log, verbose, carry="", mistakes=None,
              opportunities=None, resource=None, planning=None, behaviour=None,
              encounter_metric=None, metric_state=None, watcher=None):
    """Record both scored decisions and the subset that are mistakes.

    Both counters are judged from the engine side at the moment the move is
    made. Reconstructing them from the transcript afterwards would mean
    inferring the enemy's hidden behaviour from its effects, which is the
    player's job, not the scorer's.
    """
    allow = list(fight.deck) + ["END"]
    by_kind = {card.kind: name for name, card in fight.deck.items()}
    heal_name = by_kind["heal"]
    block_name = by_kind["block"]
    attack_name = by_kind["attack"]
    dodge_name = by_kind["dodge"]
    full_heal_turns = set()
    survival_turns = set()
    squandered_turns = set()
    charge_executable_turns = set()
    momentum_executable_turns = set()
    enrage_offerable_turns = set()
    # 反击 / 守势 / 标记：同一条纪律 —— 「答案可执行」要在能量还没花掉的决策时刻问。
    second_offence_executable_turns = set()
    offence_executable_turns = set()
    marked_executable_turns = set()
    buff_executable_turns = set()
    ward_block_turns = set()
    enrage_played_turns = set()
    seen_events = [0]
    metric_state = metric_state if metric_state is not None else {}
    fails_this_turn = 0

    def resolve_turn(killed=False):
        """Everything that happens when a turn ends -- however it ends.

        `solver.play_fight` runs `end_turn` unconditionally after the card
        phase. This loop exited on `fight.over()` instead, so a turn the model
        ended by KILLING the enemy never resolved, and that handed the model the
        one shortcut every reference policy had been denied: a wind-up already
        at the top when the turn began is committed, and killing the enemy does
        not cancel it. The same omission dropped that turn from the charge
        window counters, so a preempted wind-up was not even recorded as a
        question that had been asked.

        `killed` skips the piercer's bookkeeping, and only that: `Fight.end_turn`
        returns before feeding the grudge when the enemy is already down, so
        counting a repeat error here would describe a punishment the engine does
        not apply.
        """
        nonlocal fails_this_turn
        fails_this_turn = 0
        charge_is_window = charge_window(fight)
        charge_executable = (fight.turn in charge_executable_turns
                             or bool(fight.state[("me", "dodge")]))
        if "pierce" in fight.parts and not killed:
            if fight.fed > 0:
                _inc(behaviour, "pierce", "post_probe_turns")
                _inc(encounter_metric, "pierce", "post_probe_turns")
            if fight.state[("me", "block")] > 0:
                if fight.fed == 0:
                    _inc(behaviour, "pierce", "probes")
                    _inc(encounter_metric, "pierce", "probes")
                else:
                    _inc(behaviour, "pierce", "repeat_errors")
                    _inc(encounter_metric, "pierce", "repeat_errors")
        # momentum, built to mirror the two above rather than invented fresh.
        # The punished action is the one NOT taken -- ending a turn with no
        # shield while the ramp is live -- so `probes` and `repeat_errors` sit
        # on the same rungs pierce puts them on:
        #
        #   pierce     first shield = probe        later shield = repeat error
        #   momentum   first unshielded live turn  = probe
        #              unshielded once already at the full tier = repeat error
        #
        # `fight.momentum` is read BEFORE `end_turn` advances it, so it is the
        # tier this turn was actually fought at -- the number the player could
        # see on the enemy's attack slot when they decided.
        if "momentum" in fight.parts:
            shielded = fight.state[("me", "block")] > 0
            # `MOMENTUM_FULL_AT - 1` and not some threshold of its own: it is
            # the same line `solver.act` blocks on, so the reference policy and
            # the scorer cannot disagree about when a shield was called for.
            live = fight.momentum >= MOMENTUM_FULL_AT - 1
            if fight.momentum >= 1:
                _inc(behaviour, "momentum", "post_probe_turns")
                _inc(encounter_metric, "momentum", "post_probe_turns")
            if live:
                _inc(behaviour, "momentum", "windows")
                _inc(encounter_metric, "momentum", "windows")
                executable = (shielded
                              or fight.turn in momentum_executable_turns)
                field = ("executable_windows" if executable
                         else "unprepared_windows")
                _inc(behaviour, "momentum", field)
                _inc(encounter_metric, "momentum", field)
                if executable and not shielded:
                    _inc(behaviour, "momentum", "misses")
                    _inc(encounter_metric, "momentum", "misses")
                    rung = ("repeat_errors"
                            if fight.momentum >= MOMENTUM_FULL_AT else "probes")
                    _inc(behaviour, "momentum", rung)
                    _inc(encounter_metric, "momentum", rung)
        if charge_is_window:
            _inc(behaviour, "charge", "windows")
            _inc(encounter_metric, "charge", "windows")
            field = ("executable_windows" if charge_executable
                     else "unprepared_windows")
            _inc(behaviour, "charge", field)
            _inc(encounter_metric, "charge", field)
            if charge_executable and not fight.state[("me", "dodge")]:
                _inc(behaviour, "charge", "misses")
                _inc(encounter_metric, "charge", "misses")
        score_turn(charge_executable)
        w_hp = fight.state[("me", "hp")]
        w_block = fight.state[("me", "block")]
        w_poison = fight.state[("me", "poison")]
        w_charge = fight.state[("them", "charge")]
        # 屏幕上的敌人攻击数，**不是内部真值**。`_row` 按
        # `("them","atk") in fight.seen` 决定显示数字还是 `?`，而 `seen`
        # 只收录变动过的键 —— 纯穿透怪的 b3 整场都是 `?`。读真值等于拿
        # 模型看不见的信息去确认穿透。
        w_atk = (fight.state[("them", "atk")]
                 if ("them", "atk") in fight.seen else None)
        # 释放了**而且**玩家没在闪避 —— 闪掉的那一次玩家看见了线索、也
        # 答对了，规则的后果并没有被经历。满格本身只是预测。
        w_big = (charge_is_window
                 and w_charge >= max(1, fight.enemy.charge_max)
                 and not fight.state[("me", "dodge")])
        fight.end_turn()
        if watcher is not None:
            watcher.after_end_turn(fight, fight.turn, w_hp, w_block, w_poison,
                                   w_charge, w_big, w_atk)

    scored_turns = set()

    def score_turn(charge_executable):
        """B 表这一回合的记账：机会与错误，按决策时刻的可执行性。

        从 `resolve_turn` 里拆出来，因为一回合可能在结算之前就结束了：标记怪的
        重击落在**出牌当下**，出了被标记的牌当场死掉，`while not fight.over()`
        就退出，`resolve_turn` 永远不会跑 —— 于是致命的那一次错误恰好不进 B 表。
        GPT-6 命 4 第 7 层就是这样：记录里 mark 0/1，日志里最后两张牌各挨 130。
        """
        if "counter" in fight.parts:
            doubled = getattr(fight, "offences", 0) >= 2
            if doubled or fight.turn in second_offence_executable_turns:
                _inc(behaviour, "counter", "executable_turns")
                _inc(encounter_metric, "counter", "executable_turns")
            if doubled:
                _inc(behaviour, "counter", "double_turns")
                _inc(encounter_metric, "counter", "double_turns")
        scored_turns.add(fight.turn)
        momentum_executable = (fight.turn in momentum_executable_turns
                               or fight.state[("me", "block")] > 0)
        enrage_offer = fight.turn in enrage_offerable_turns
        enrage_played = fight.turn in enrage_played_turns
        new_exec = dict(
            second_offence_executable=fight.turn in second_offence_executable_turns,
            offence_executable=fight.turn in offence_executable_turns,
            marked_executable=fight.turn in marked_executable_turns,
            buff_executable=fight.turn in buff_executable_turns,
            ward_block_executable=fight.turn in ward_block_turns)
        if opportunities is not None:
            for m in turn_opportunities(fight, charge_executable,
                                        momentum_executable, enrage_offer, **new_exec):
                opportunities[m] = opportunities.get(m, 0) + 1
        if mistakes is not None:
            for m in turn_mistakes(fight, charge_executable,
                                   momentum_executable, enrage_played,
                                   ward_block_executable=fight.turn in ward_block_turns):
                mistakes[m] = mistakes.get(m, 0) + 1
        # The passive observer. It only appends to lists -- it must not touch
        # the belief, the action, the rng, the log or the prompt, and there is
        # a paired regression that runs the same stream with it on and off and
        # requires every model-visible byte to match.
        if watcher is not None:
            wrong = set(turn_mistakes(fight, charge_executable,
                                      momentum_executable, enrage_played,
                                      ward_block_executable=fight.turn in ward_block_turns))
            for m in turn_opportunities(fight, charge_executable,
                                        momentum_executable, enrage_offer, **new_exec):
                watcher.opportunity(fight.turn, m, m in wrong)

    turn_started = None
    while not fight.over():
        turn_started = fight.turn
        # Remember that dodge was executable at any decision point in this
        # full-wind-up turn. Looking only at END would misclassify a player who
        # spent the energy first as "unprepared" rather than a missed response.
        if charge_window(fight) and (
                fight.state[("me", "dodge")] or fight.can_play(dodge_name)):
            charge_executable_turns.add(fight.turn)
        # Same rule, same reason. Asking `can_play(block)` at the END of the
        # turn asks it of a spent energy bar, so a player who HAD the shield and
        # chose something else reads as one who never had it: the record said
        # `unprepared_windows=3` for a life whose own log shows the shield in
        # hand on all three. That is the charge bug again -- checking whether the
        # question was answerable only after it had been answered.
        if (fight.momentum >= MOMENTUM_FULL_AT - 1
                and (fight.state[("me", "block")] > 0
                     or fight.can_play(block_name))):
            momentum_executable_turns.add(fight.turn)
        # Same discipline for the third time: whether NOT playing a non-attack
        # was a choice has to be asked while the energy is still unspent.
        if ("enrage" in fight.parts and fight.enraged > 0
                and nonattack_available(fight)):
            enrage_offerable_turns.add(fight.turn)
        if "counter" in fight.parts and second_offence_available(fight):
            second_offence_executable_turns.add(fight.turn)
        if "guard" in fight.parts and offence_available(fight):
            offence_executable_turns.add(fight.turn)
        if "mark" in fight.parts:
            mk = fight.marked_kind()
            if mk and any(c.kind == mk and fight.can_play(n) for n, c in fight.deck.items()):
                marked_executable_turns.add(fight.turn)
        if "mimic" in fight.parts and buff_available(fight):
            buff_executable_turns.add(fight.turn)
        if "ward" in fight.parts and fight.state[("them", "ward")] > 0 and block_available(fight):
            ward_block_turns.add(fight.turn)
        if (resource is not None and fight.turn not in full_heal_turns
                and full_heal_window(fight, heal_name)):
            resource["full_heal_turns"] = resource.get("full_heal_turns", 0) + 1
            full_heal_turns.add(fight.turn)
        survival_now = survival_opportunity(fight, block_name, attack_name)
        if (planning is not None and survival_now
                and fight.turn not in survival_turns):
            planning["opportunities"] = planning.get("opportunities", 0) + 1
            survival_turns.add(fight.turn)
        a = act(model, key, system, fight, fight_screen, log, allow, carry)
        if a is None:
            log.append("[unparseable]")
            fails_this_turn += 1
            if fails_this_turn >= FAILS_PER_TURN:
                before = dict(fight.state)     # 同名 before：boss 层的 _quiet_model_log 按这个名字改换阶段那一帧
                resolve_turn()
                _log_forced_end(fight, before, log, verbose, seen_events)
            continue
        if (planning is not None
                and fight.turn not in squandered_turns
                and squanders_survival(fight, a, block_name, attack_name)):
            planning["avoidable_lethal"] = planning.get("avoidable_lethal", 0) + 1
            squandered_turns.add(fight.turn)
        before = dict(fight.state)
        if a == "end":
            resolve_turn(); tag = "end turn"
        else:
            atk_before_card = before[("them", "atk")]
            r = fight.play(a)
            # Only on a card that actually resolved: a refused play shows the
            # participant nothing, so it is not evidence.
            if watcher is not None and r is True:
                watcher.after_play(fight, fight.turn, atk_before_card,
                                   fight.deck[a].kind)
            if (resource is not None and r is True
                    and fight.deck[a].kind == "heal"):
                resource["heal_plays"] = resource.get("heal_plays", 0) + 1
                if before[("me", "hp")] >= fight.max_hp:
                    resource["zero_effect_exhaust"] = (
                        resource.get("zero_effect_exhaust", 0) + 1)
            # enrage, on the same rungs as pierce: the punished action is
            # playing a non-attack, the first one buys the evidence and is not
            # scored as a failure, and the ones after it are. Recorded per CARD
            # because that is where the enemy's attack moves -- a per-turn hook
            # sees two non-attacks in one turn as one event, and the second of
            # them is the first repeat after the rule has already shown itself.
            if (r is True and "enrage" in fight.parts
                    and fight.deck[a].kind != "attack"):
                rose = fight.state[("them", "atk")] > before[("them", "atk")]
                if metric_state.get("enrage_evidenced"):
                    # The RATE is counted per turn, in `resolve_turn`, against a
                    # denominator of turns where a non-attack was payable.
                    # Incrementing both counters here made them one number:
                    # every opportunity was a mistake because only mistakes were
                    # ever counted as opportunities.
                    enrage_played_turns.add(fight.turn)
                    _inc(behaviour, "enrage", "repeat_errors")
                    _inc(encounter_metric, "enrage", "repeat_errors")
                else:
                    _inc(behaviour, "enrage", "probes")
                    _inc(encounter_metric, "enrage", "probes")
                    if rose:
                        metric_state["enrage_evidenced"] = True
                        _inc(behaviour, "enrage", "evidence_events")
                        _inc(encounter_metric, "enrage", "evidence_events")
            armour_test = (r == True and fight.deck[a].kind == "attack"
                           and "armour" in fight.parts
                           and before[("them", "armour")] > 0)
            if armour_test:
                wasted = (fight.state[("them", "hp")]
                          == before[("them", "hp")])
                already_evidenced = metric_state.get("armour_evidenced", False)
                if already_evidenced:
                    if opportunities is not None:
                        opportunities["armour"] = opportunities.get("armour", 0) + 1
                    _inc(behaviour, "armour", "post_evidence_attacks")
                    _inc(encounter_metric, "armour", "post_evidence_attacks")
                    if wasted:
                        if mistakes is not None:
                            mistakes["armour"] = mistakes.get("armour", 0) + 1
                        _inc(behaviour, "armour", "repeat_errors")
                        _inc(encounter_metric, "armour", "repeat_errors")
                else:
                    # The first attack supplies causal evidence. A zero hit is
                    # an experiment, not yet a failure to correct; an immediate
                    # burst is an informative correct response.
                    metric_state["armour_evidenced"] = True
                    _inc(behaviour, "armour", "evidence_events")
                    _inc(encounter_metric, "armour", "evidence_events")
                    if wasted:
                        _inc(behaviour, "armour", "probe_attacks")
                        _inc(encounter_metric, "armour", "probe_attacks")
                if fight.broke:
                    _inc(behaviour, "armour", "breaks")
                    _inc(encounter_metric, "armour", "breaks")
            if r != True:
                log.append(f"{a}  ->  " +
                           ("(not in hand)" if r == "absent" else "(no effect)"))
                if verbose:
                    print(f"    {a}  ->  "
                          + ("(not in hand)" if r == "absent" else "(no effect)"),
                          flush=True)
                fails_this_turn += 1
                if fails_this_turn >= FAILS_PER_TURN:
                    # In a fight the forced end is not free: the enemy takes its
                    # turn. That is the intended shape -- a wasted action should
                    # cost something -- but it makes this a rule of the game and
                    # not merely a guard on the loop.
                    before = dict(fight.state)
                    resolve_turn()
                    _log_forced_end(fight, before, log, verbose, seen_events)
                continue
            tag = a
        ch = [f"{fight.layout.L(k[0], k[1])}: {before[k]}->{fight.state[k]}"
              for k in fight.state if before[k] != fight.state[k] and k not in TUNING["hidden_props"]]
        entry = f"{tag}  ->  {', '.join(ch) if ch else '(nothing changed)'}"
        log.append(entry)
        if verbose:
            print(f"    {entry}", flush=True)
        # The cue, translated. It is produced as a structured event by the
        # engine and rendered here, so the model and the reference policies are
        # reading the SAME signal -- a string written straight into the log
        # would be a cue only the model can see.
        while len(fight.events) > seen_events[0]:
            _turn, name = fight.events[seen_events[0]]
            seen_events[0] += 1
            if name != BOSS_SHIFT:
                continue
            log.append(BOSS_SHIFT_TEXT)
            if verbose:
                print(f"    {BOSS_SHIFT_TEXT}", flush=True)
        if verbose:
            if a == "end":
                print(f"      {snapshot(fight)}", flush=True)
                # Hand is logged at each turn boundary. Without it a card that
                # never gets played is ambiguous: not drawn, or drawn and
                # ignored? gpt-5.5 went a whole run without playing a heal while
                # holding three of them, and the log could not say which.
                print(f"      手牌 {' '.join(fight.hand)}", flush=True)
    # The turn the enemy died still has to resolve. The loop above exits on
    # `fight.over()`, so a model that killed the enemy with its last card never
    # reached `end` -- and a wind-up that was already at the top when that turn
    # began is COMMITTED: `charge_commits` says killing it does not cancel it.
    # `solver.play_fight` gets this for free by running `end_turn`
    # unconditionally after the card phase; this driver did not, so every
    # reference policy was denied the shortcut and the model was handed it.
    #
    # `Fight.end_turn` is a no-op for a dead enemy that has nothing committed,
    # so this is safe on every ordinary kill.
    if (fight.state[("me", "hp")] <= 0 and turn_started is not None
            and fight.turn == turn_started and turn_started not in scored_turns):
        # 死在出牌当下（标记怪的重击）：回合没结算，但这一回合的题问了、也答错了。
        # 只记账，不结算 —— 怪没有再打一下。不看怪死没死：对照包命 1 第 7 层那一刀
        # 同时打死了怪和自己（b1 7->0，a3 46->-58），原先按「怪还活着」判就漏了。
        # `fight.turn == turn_started` 才是「回合没结算」：结算时死掉的回合已经由
        # resolve_turn 记过账，而 end_turn 把回合号加了一，光查 `scored_turns`
        # 会把加一后的号当成没记过的新回合，再记一个不存在的机会（v6 的幻影回合）。
        score_turn(fight.turn in charge_executable_turns
                   or bool(fight.state[("me", "dodge")]))
    if fight.state[("them", "hp")] <= 0 and fight.state[("me", "hp")] > 0:
        before = dict(fight.state)
        resolve_turn(killed=True)
        ch = [f"{fight.layout.L(k[0], k[1])}: {before[k]}->{fight.state[k]}"
              for k in fight.state if before[k] != fight.state[k] and k not in TUNING["hidden_props"]]
        if ch:
            entry = f"{LOCKED_ATTACK}  ->  {', '.join(ch)}"
            log.append(entry)
            if verbose:
                print(f"    {entry}", flush=True)
    return fight.won()


def _slug(model: str) -> str:
    """A model name that is safe as ONE path component.

    Google's ids arrive as `models/gemini-3.8-flash`, and a slash in a filename
    is a directory that does not exist -- so a run crashed at the checkpoint
    AFTER the camp had been paid for, losing it. The whole name is kept, not
    just the bare part, because two providers could otherwise collide on one
    record.
    """
    return model.replace("/", "_").replace(":", "_").strip()


def _record(model, seed, life=1, suffix="", run_id=None):
    """Where a life is filed.

    `run_id` names the EXPERIMENT, and it is not the salt on purpose: a run
    spans several salts by design -- life 1 on one map, life 2 on a new one --
    so keying the file on salt would break the very chain a later life reads.
    The salt goes in the payload, and `_dump` refuses to overwrite a record
    that was written from a different one.

    The default namespace is spelled `main`, and it is spelled in the FILENAME
    rather than being the absence of one. An empty tag works and is a trap in
    three ways: the shell eats an unquoted `""`, a reader cannot tell what the
    missing segment meant, and "the default namespace" and "no camp source"
    stop being distinguishable. Every record names its condition.
    """
    d = RUNS_DIR; d.mkdir(parents=True, exist_ok=True)
    return d / (f"{_slug(model)}_{seed}_{ENGINE_VERSION}_{run_id or MAIN_RUN}"
                f"{suffix}_life{life}.json")


def _legacy_record(model, seed, life=1, suffix=""):
    """The pre-namespace name, for reading records already on disk."""
    return RUNS_DIR / f"{_slug(model)}_{seed}_{ENGINE_VERSION}{suffix}_life{life}.json"


def _dump(model, seed, payload, life=1, run_id=None):
    """Checkpoint to disk so a killed run still leaves its data behind."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    # The engine version belongs in the NAME, not just the contents: the screen
    # re-rolls until a run lands in the band, so the same seed on two engines is
    # two different games, and writing them to one path silently destroys the
    # older record.
    f = _record(model, seed, life, run_id=run_id)
    old = json.loads(f.read_text()) if f.exists() else {}
    # The guard that was missing. The name carries model, seed, engine and
    # life -- but NOT the salt, so a second condition on the same seed wrote
    # straight over the first one's record, and any later life then carried the
    # wrong prior without anything looking wrong. Two arms of one experiment is
    # exactly the case this benchmark is for.
    was, now = old.get("salt"), payload.get("salt")
    if old and was is not None and now is not None and was != now:
        raise SystemExit(
            f"拒绝覆盖：{f.name} 是 salt={was} 写的，这次是 salt={now}。\n"
            f"同一个 (model, seed, engine, life) 下的两个条件必须用 --run-id "
            f"分开存，否则前一条命的记录会被换掉，而后面的命会安静地带上错的"
            f"上一条命。")
    payload.setdefault("protocol", PROTOCOL_VERSION)
    old.update(payload)
    f.write_text(json.dumps(old, ensure_ascii=False, indent=1))




def _empty_camp_experiments(camp):
    return {"cards": {
        name: {"kind": card.kind, "attempts": 0, "successes": 0,
               "absent": 0, "insufficient_energy": 0,
               "playable_steps": 0, "first_success_step": None}
        for name, card in camp.deck.items()}}


def _finish_camp_experiments(stats):
    cards = stats["cards"]
    stats["coverage"] = sum(v["successes"] > 0 for v in cards.values())
    stats["total_cards"] = len(cards)
    stats["untried"] = [name for name, v in cards.items()
                         if not v["successes"]]
    return stats


def _run_camp(model, key, camp, camp_turns, verbose,
              camp_steps=CAMP_STEPS, carry=""):
    """The camp loop itself. Returns the log."""
    camp_log = HarnessLog()
    experiments = _empty_camp_experiments(camp)
    step = 0
    allow = list(camp.deck) + ["END", "RESET", "LEAVE"]
    # A step cap, not just a turn cap. `camp.turn` advances only when the model
    # chooses to end its turn, so a model that never ends one loops forever --
    # gemini-3.5-flash spent twenty-two consecutive actions replaying cards it
    # had no energy for, and nothing would have stopped it.
    #
    # It is not only a runaway guard. Steps are one of the efficiency measures
    # this benchmark reports, and an unbounded budget makes that measure
    # meaningless: with infinite actions any model can brute-force the card
    # semantics. A cost that cannot be exceeded is not a cost.
    fails_this_turn = 0
    while camp.turn <= camp_turns and step < camp_steps:
        step += 1
        for name, stats in experiments["cards"].items():
            if camp.can_play(name):
                stats["playable_steps"] += 1
        action_turn = camp.turn
        a = act(model, key, CAMP_SYSTEM, camp,
                lambda c: camp_screen(c, camp_turns - c.turn + 1), camp_log, allow, carry)
        if a is None:
            camp_log.append("[unparseable]")
            fails_this_turn += 1
            if fails_this_turn >= FAILS_PER_TURN:
                camp.end_turn(); fails_this_turn = 0
                camp_log.append(FORCED_END)
                if verbose:
                    print(f"  T{action_turn:>2} {FORCED_END}", flush=True)
            continue
        if a == "leave":
            camp_log.append("LEAVE"); break
        before = dict(camp.state)
        if a == "reset":
            camp.reset(); entry = "RESET -> everything reset"
            fails_this_turn = 0
        elif a == "end":
            camp.end_turn(); entry = None; tag = "end turn"
            fails_this_turn = 0
        else:
            r = camp.play(a)
            stats = experiments["cards"][a]
            stats["attempts"] += 1
            if r is True:
                stats["successes"] += 1
                if stats["first_success_step"] is None:
                    stats["first_success_step"] = step
            elif r == "absent":
                stats["absent"] += 1
            else:
                stats["insufficient_energy"] += 1
            entry = None if r == True else (
                f"{a}  ->  " + ("(not in hand)" if r == "absent" else "(no effect)"))
            tag = a
            # Per TURN, not consecutive: a success does not clear the count.
            # Clearing on success is what "three in a row" means, and it lets a
            # model alternate one good action with endless bad ones and never
            # advance -- the behaviour this rule exists to stop.
            fails_this_turn += r is not True
        if entry is None:
            ch = [f"{camp.layout.L(k[0], k[1])}: {before[k]}->{camp.state[k]}"
                  for k in camp.state if before[k] != camp.state[k] and k not in TUNING["hidden_props"]]
            entry = f"{tag}  ->  {', '.join(ch) if ch else '(nothing changed)'}"
        camp_log.append(entry)
        if verbose:
            print(f"  T{action_turn:>2} {entry}", flush=True)
        if fails_this_turn >= FAILS_PER_TURN:
            camp.end_turn(); fails_this_turn = 0
            camp_log.append(FORCED_END)
            if verbose:
                print(f"  T{action_turn:>2} {FORCED_END}", flush=True)
    return camp_log, _finish_camp_experiments(experiments)

def _note_fight(model, key, mode, notes, tag, name, slice_, verbose):
    """Ask for a summary of the fight that just ended, win or lose.

    Asked from the slice of the log belonging to this fight only. Feeding the
    whole adventure log back would make the summary a summary of everything,
    and the point is to have one reading per enemy."""
    if mode == "none":
        return
    body = (f"You have just finished a fight against {name}. Here is the record "
            f"of that fight:\n\n"
            + "\n".join(f"  {i}. {h}" for i, h in enumerate(slice_, 1))
            + "\n\n" + FIGHT_DEBRIEF)
    text = call(model, REPORTER, body, key)
    notes.append(dict(tag=tag, enemy=name, kind="fight", text=text))
    if verbose:
        print(f"\n  --- {tag} 战后总结（{'会给它看' if mode == 'show' else '不给它看'}）"
              f" ---\n{text}\n", flush=True)


def _note_rest(model, key, mode, notes, tag, history, choice, result,
               verbose):
    """Ask what a rest established without adding analyst semantics."""
    if mode == "none":
        return
    recap = [h for h in history if not is_observation(h)]
    body = "\n".join([
        *(["What happened earlier in this life:",
           *[f"  {i}. {h}" for i, h in enumerate(recap, 1)], ""]
          if recap else []),
        f"At {tag}, the visible options were:",
        "  1. recover health (+?)",
        "  2. recover maximum (+?)",
        f"You chose: {choice}",
        f"Visible result: {result}",
        "",
        REST_DEBRIEF,
    ])
    text = call(model, REPORTER, body, key)
    notes.append(dict(tag=tag, enemy="rest", kind="rest", text=text))
    if verbose:
        visible = "会给它看" if mode == "show" else "不给它看"
        print(f"\n  --- {tag} 休息总结（{visible}） ---\n{text}\n",
              flush=True)


def handover_evidence(carry, transcript, notes, prev_adv=(), earlier=()) -> list:
    """The evidence a later life of this world receives, without the framing line: the raw record (log/both),
    the written notes of earlier lives (notes/both), then the camp conclusion (notes/both). Also what a letter
    is written from at the end of a world (`write_letter`), so the two cannot drift apart."""
    carried = []
    if carry in ("log", "both"):
        carried.append(RETRY_LOG_HEAD + "\n\nIn the room without doors:\n"
                       + transcript)
        for n, log, res in prev_adv:
            if log:
                carried.append(f"Life {n}, outside ({res}):\n"
                               + "\n".join(f"  {i}. {h}"
                                            for i, h in enumerate(log, 1)))
    if carry in ("notes", "both"):
        written = _prior_life_notes(earlier)
        if written:
            carried.append(written)
    if carry in ("notes", "both") and notes:
        carried.append("What you concluded there:\n" + notes)
    return carried


def build_handover(life, carry, transcript, notes, prev_adv=(), earlier=(), letters=()) -> str:
    """What crosses into the adventure: the text standing in front of every adventure call of this life.
    Pure function, shared by `main`, the carry tests and the offline cache simulator.
    `prev_adv` = [(life, adv_log, result)] and `earlier` = [(life, record)] for the earlier lives (life > 1).
    `letters` = what the agent wrote when it left earlier worlds; they go first, before anything of this world.

    `carry` has to mean what it says at life > 1 too. It did not: the camp
    transcript and EVERY earlier life's raw adventure log were appended
    unconditionally, and `carry` only decided whether the written
    summaries came along. So `--carry notes` actually delivered
    "log + notes", and by life 4 that is three lives of raw record.

    A four-life experiment run that way cannot separate "it learned the
    rules" from "it looked the answer up in the transcript" from "the
    longer context hurt it" -- which is the whole measurement.

    The framing stays under every mode: `carry` controls what EVIDENCE
    crosses over, not whether the participant is told it has been here."""
    carried = [letters_block(letters)] if letters else []
    if life > 1:
        carried.append(RETRY_HEAD)
        carried += handover_evidence(carry, transcript, notes, prev_adv, earlier)
    else:
        if carry in ("log", "both"):
            carried.append("What happened in the previous place:\n" + transcript)
        if carry in ("notes", "both") and notes:
            carried.append("What you concluded there:\n" + notes)
    return "\n\n".join(carried)


def _carried(mode, notes, handover=""):
    """Everything standing in front of the model this step, besides the screen.

    The handover from the camp is repeated at every step, not shown once. Each
    API call is a fresh request with no conversation history, so anything not
    reprinted is gone -- an earlier version handed the camp over to the first
    node choice and then dropped it, which made `--carry log` mean almost the
    opposite of what it says."""
    parts = [handover] if handover else []
    if mode == "show" and notes:
        parts.append("What you wrote after earlier fights and rests:\n"
                     + "\n\n".join(
                         f"  [{n['tag']}, "
                         f"{'rest' if n.get('kind') == 'rest' else 'vs ' + n['enemy']}]"
                         f"\n  {n['text']}" for n in notes))
    return "\n\n".join(parts)


def _render_notes(notes) -> str:
    """Fight and rest notes as they stand in front of the model: one entry per note, a blank line between."""
    rendered = []
    for note in notes:
        subject = ("rest" if note.get("kind") == "rest"
                   else "vs " + note.get("enemy", "?"))
        rendered.append(f"  [{note.get('tag', '?')}, {subject}]\n"
                        f"  {note.get('text', '')}")
    return "\n\n".join(rendered)


def _prior_life_notes(earlier) -> str:
    """The participant's own written memory from completed earlier lives."""
    parts = []
    for life, data in earlier:
        notes = data.get("fight_notes", [])
        if notes:
            parts.append(f"What you wrote during life {life}:\n"
                         + _render_notes(notes))
        if data.get("adv_notes"):
            parts.append(f"What you concluded after life {life}:\n"
                         + data["adv_notes"])
    return "\n\n".join(parts)


# 命末总结看什么（2026-10-19，用户：「每次死了那次战后记忆也让他看到自己之前这条命的笔记和log」）。记录里写 life_debrief；
# 没有这个字段的旧记录是 "record"。
#   record        这条命的完整记录
#   record+notes  完整记录，加上这条命里它自己写的战斗和休息笔记（默认）
# 死了和打通一样（按结果分开，两种命的总结就不是同一个条件了）。战斗笔记本身不变：每条只看那一场，H-notes 数的就是它们，
# 写法必须一致，所以「看全这条命」放在命末总结里，它本来就在死后马上写。前几条命的东西不给：每条命的总结仍是这一条命的读数，
# 跨命的整理只在世界末的信里做。
LIFE_DEBRIEFS = ("record", "record+notes")
LIFE_DEBRIEF = "record+notes"


def build_life_debrief(adv_log, fnotes=(), mode=None) -> str:
    """The user text of the end-of-life conclusion: this life's full record, then (record+notes) the notes the model
    wrote during this life, then DEBRIEF_ADV. Without notes it is byte-identical to the record-only text.
    Pure function, shared by `main` and the offline cache simulator."""
    mode = mode or LIFE_DEBRIEF
    assert mode in LIFE_DEBRIEFS, mode
    parts = ["Here is the full record:\n\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(adv_log, 1))]
    if mode == "record+notes" and fnotes:
        parts.append("What you wrote during this life:\n" + _render_notes(fnotes))
    return "\n\n".join(parts + [DEBRIEF_ADV])


def _load(model, seed, life=1, run_id=None):
    d = RUNS_DIR
    f = _record(model, seed, life, run_id=run_id)
    if f.exists():
        return json.loads(f.read_text())
    if (run_id or MAIN_RUN) == MAIN_RUN:
        legacy = _legacy_record(model, seed, life)
        if legacy.exists():
            return json.loads(legacy.read_text())
    old = d / f"{_slug(model)}_{seed}_{ENGINE_VERSION}.json"   # 早期没有 life 后缀
    return json.loads(old.read_text()) if (life == 1 and old.exists()) else None


def _collect_shield_audit(audit: dict, f) -> None:
    """Per-fight shield accounting, for deciding an open design question.

    Two questions live here and they are NOT the same one, which is what the
    first version of this audit got wrong by answering both with one number:

      blind            can the environment be experimented on at all? Decided
                       by the engine's own paired counterfactual, independent
                       of anything the player did. This is the only figure that
                       could justify showing the absorbed amount -- and showing
                       it is expensive, because a public "absorbed" number also
                       hands over the enemy's raw attack, that poison ignores
                       block, that a charged hit is anomalous, and that a
                       piercer absorbs nothing, which would make the hardest
                       gate free.

      matched /        did the player actually produce a control? Only an
      unmatched        unshielded turn under identical conditions counts: same
                       enemy, same real attack, same wind-up phase, same rage,
                       same poison, same dodge, same grudge. A turn spent
                       dodging, or one that ate a charged hit, controls for
                       nothing. A high `unmatched` is a failure to experiment,
                       not a failure of the environment, so it must never be
                       read as a reason to change what the player is shown.
    """
    audit["fights"] += 1
    audit["blocked"] += f.blocked_turns
    audit["unblocked"] += f.unblocked_turns
    audit["fully_absorbed"] += f.fully_absorbed_turns
    audit["absorbed_total"] += f.absorbed_total
    audit["blind"] += f.blind_turns
    # A shielded turn has a control only if some unshielded turn in the same
    # fight ran under the SAME conditions -- same enemy, same real attack, same
    # wind-up phase, same rage count, same poison, same dodge, same grudge. An
    # unshielded turn spent dodging, or one that ate a charged hit, controls for
    # nothing, and counting it as a control is what made the first version of
    # this metric report "contrast available" when there was none.
    bare = {m[:7] for m in f.turn_marks if not m[7]}
    for mark in f.turn_marks:
        if mark[8] and mark[:7] not in bare:
            audit["unmatched_absorb"] += 1
        elif mark[8]:
            audit["matched_absorb"] += 1


def _certified():
    import devworld
    return devworld.CERTIFIED


def _world_status(seed, salt):
    """登记 8 的包 certified-validation、登记 9 的图库 certified-library，其余 UNCERTIFIED-registered。"""
    import devworld
    st = devworld.world_status(seed, salt)
    return st if st != "UNCERTIFIED" else "UNCERTIFIED-registered"


def world_salt_certified(world: str, salt: int) -> bool:
    """世界 A：发布族认证过的图（登记 11 的图库）；B–E：该世界自己认证过的图（devworld.WORLD_LIBRARY）。"""
    import devworld
    if world == "A":
        return devworld.registration_of(salt) is not None
    return salt in devworld.WORLD_LIBRARY.get(world, ())


def camp_rng(seed, world=None):
    """训练营的随机流（木桩的打击偏移、牌堆顺序）。世界 A 和不带世界的旧跑法照旧按 seed，旧记录一字不变；
    别的世界按身份键另起一条流 —— 否则五个世界的训练营发牌顺序（按牌的种类）完全一样，换了牌名也能按顺序对上。"""
    if world is None or world == "A":
        return random.Random(seed)
    import devworld
    return random.Random(f"camp-v1:{devworld.WORLDS[world]['identity_key']}:{seed}")


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _letter_path(model, seed, run_id):
    d = RUNS_DIR; d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(model)}_{seed}_{ENGINE_VERSION}_{run_id or MAIN_RUN}_letter.json"


def letter_tokens(text: str) -> int:
    """交接 note 的统一计数口径：tiktoken o200k_base，本地。没装就拒绝，不能换一把尺子。"""
    try:
        import tiktoken
    except ImportError:
        raise SystemExit("交接 note 的计数需要 tiktoken（pip install tiktoken）：所有模型必须用同一把尺子")
    return len(tiktoken.get_encoding("o200k_base").encode(text))


def letter_truncate(text: str, limit: int = LETTER_LIMIT) -> str:
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    return enc.decode(enc.encode(text)[:limit])


def load_letters(model, seed, run_ids) -> list:
    """读上一个世界的交接 note。2026-10-27 起只传最新一份：更早的经验要不要留，由模型写新交接时决定。"""
    if len(run_ids or ()) > 1:
        raise SystemExit("下一世界只收到最新一份交接 note（--letters-from 只给上一个世界的 run_id）")
    out = []
    for rid in run_ids or ():
        f = _letter_path(model, seed, rid)
        if not f.exists():
            raise SystemExit(f"找不到 {rid} 的信（{f.name}）；那个世界要先跑完并写信（--write-letter）")
        out.append(json.loads(f.read_text())["letter"])
    return out


def write_letter(model, seed, run_id, carry, lives=5, letters_from=(), verbose=True):
    """一个世界打完之后写信：读这个世界的训练营和五条命的记录，按这一臂本来能带的东西（handover_evidence，
    和第 6 条命会收到的一样）加上之前的信，问 LETTER_QUESTION，存成 <run_id>_letter.json。"""
    key = _api_key(model)
    global CACHE_KEY, BUDGET_USD, BUDGET_KEY
    u0 = _usage_snapshot()
    CACHE_KEY = f"agii:{_slug(model)}:{run_id or MAIN_RUN}"
    BUDGET_KEY = os.environ.get("AGII_BUDGET_KEY") or f"{_slug(model)}_{run_id or MAIN_RUN}"
    cap = os.environ.get("AGII_BUDGET_USD", "").strip()
    BUDGET_USD = float(cap) if cap else None
    effort_for(provider_for(model))
    earlier = [(n, _load(model, seed, n, run_id=run_id)) for n in range(1, lives + 1)]
    missing = [n for n, d in earlier if not d or "adv_log" not in d]
    if missing:
        raise SystemExit(f"{run_id} 还有命没跑完：{missing}")
    first = earlier[0][1]
    transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(first["camp_log"], 1))
    prev_adv = [(n, d.get("adv_log", []), d.get("result", "?")) for n, d in earlier]
    letters = load_letters(model, seed, letters_from)
    # 写交接时能读的材料（2026-10-27 定，不随 carry 变）：入境交接 note、本世界训练营和每条命的完整 log、每条命的复盘 note。
    # 不给未来信息、隐藏规则，也不提示该保留什么。
    parts = ([letters_block(letters)] if letters else []) + handover_evidence("both", transcript, first.get("notes", ""), prev_adv, earlier)
    body = "\n\n".join(parts + [LETTER_QUESTION])
    TRACE.clear()
    text = call(model, LETTER_SYSTEM, body, key)
    versions = [text]
    n = letter_tokens(text)
    shortened = truncated = False
    if n > LETTER_LIMIT:                       # 超长：让模型按计数自缩一次；仍超则机械截断。不人工替它改写。
        text = call(model, LETTER_SYSTEM, body + "\n\n" + "Your previous note:\n" + text + "\n\n"
                    + LETTER_SHORTEN.format(n=n, limit=LETTER_LIMIT), key)
        versions.append(text); shortened = True
        n = letter_tokens(text)
        if n > LETTER_LIMIT:
            text = letter_truncate(text); truncated = True; n = letter_tokens(text)
    f = _letter_path(model, seed, run_id)
    payload = dict(engine=ENGINE_VERSION, run_id=run_id, carry=carry, lives=lives, letter=text,
                   letter_tokens=n, letter_limit=LETTER_LIMIT, letter_versions=versions, shortened=shortened, truncated=truncated,
                   trace_version=TRACE_VERSION, trace=list(TRACE),
                   world=first.get("world"), pack=first.get("pack"), letters_from=list(letters_from or ()),
                   material_sha=_sha(body), material_chars=len(body), usage=_usage_since(u0),
                   prompt_order=PROMPT_ORDER, api=api_settings(model), protocol=PROTOCOL_VERSION,
                   harness_language=HARNESS_LANGUAGE)
    f.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    if verbose:
        print(f"\n{'='*58}\n离开这个世界时写的信（{len(text)} 字）:\n{text}\n{'='*58}", flush=True)
    return payload


def _confirmed_set():
    """Read lazily: `devworld` is only imported when a salt is pinned, and this
    module must keep working when it is not."""
    try:
        import devworld
        return set(devworld.CONFIRMED)
    except Exception:
        return set()


_CONFIRMED = _confirmed_set()


def main(model, seed, camp_turns, carry, want_notes, verbose=True,
         camp_only=False, reuse_camp=False, fight_notes="write", life=1,
         camp_steps=CAMP_STEPS, salt=None, run_id=None, camp_from=None,
         registered=False, world=None, pack=None, letters_from=()):
    key = _api_key(model)
    TRACE.clear()                      # 每条命一份痕迹
    u0 = _usage_snapshot()
    global CACHE_KEY, BUDGET_USD, BUDGET_KEY
    CACHE_KEY = f"agii:{_slug(model)}:{run_id or MAIN_RUN}"     # 按链，不按命：下一条命开头要接着用上一条命的交接前缀
    BUDGET_KEY = os.environ.get("AGII_BUDGET_KEY") or f"{_slug(model)}_{run_id or MAIN_RUN}"
    cap = os.environ.get("AGII_BUDGET_USD", "").strip()
    BUDGET_USD = float(cap) if cap else None
    import prices
    if BUDGET_USD is not None and prices.price_for(model) is None:
        raise SystemExit(f"设了花费上限 ${BUDGET_USD}，但 prices.py 里没有 {model} 的价格。"
                         f"查好价格后设 AGII_PRICE=\"输入,缓存读,缓存写,输出\"（每百万 token 美元）再跑。")
    effort_for(provider_for(model))                       # 档位不合法就在第一次请求之前停
    if verbose and BUDGET_USD is not None:
        print(f"花费上限 ${BUDGET_USD:.2f}（账本 {_ledger_path()}，已花 ${budget_spent():.2f}）", flush=True)
    _check_budget()
    letters = load_letters(model, seed, letters_from)
    if world is not None:
        # 世界（远迁移）：世界定身份和经济，salt 定地图，（世界，包）定牌名。只跑这个世界认证过的图。
        import devworld
        if salt is None:
            raise SystemExit("--world 要和 --salt 一起用")
        if not world_salt_certified(world, salt):
            raise SystemExit(f"{salt} 不是世界 {world} 认证过的图")
        run = devworld.build_world(world, seed, salt, pack)
    elif salt is not None and registered:
        # 按 salt 所属的登记构造（8：六池包；9：七池图库）。认证过的世界在 devworld.CERTIFIED。
        import devworld
        run = devworld.build_registered(seed, salt)
    elif salt is not None:
        # A confirmed development world. `make_run` is deliberately NOT called:
        # it searches for its own salt under the old conjunctive gate -- every
        # `ALL-m` below 10% -- which is precisely the gate these worlds were
        # not selected by, and it would quietly hand back a different map.
        import devworld
        run = devworld.build(seed, salt)
    else:
        from solver import make_run
        run = make_run(seed, life=life)
    camp = Camp(run.deck, run.layout, base_atk=run.base_atk,
                rng=camp_rng(seed, world))
    prior_armour_evidenced = False

    # Reusing a stored camp lets several carry conditions share one camp run --
    # the cleaner comparison anyway, since the summary and the transcript being
    # handed over are then literally the same text.
    # A later life skips the camp entirely -- it already happened, to you -- and
    # carries the whole of the previous life instead. The seed keeps the card
    # and slot mappings fixed; `life` selects a newly rolled world (encounter
    # order, nodes, enemy numbers, boss parts and shuffles). What transfers is
    # learned structure, never a memorised sequence.
    if life > 1:
        # Every earlier life, not just the last one. A run that keeps dying to
        # the same wrong answer is exactly what this is measuring, and handing
        # over only the most recent attempt hides the repetition -- the third
        # life should be able to see that the same card preceded the worst turn
        # in both previous ones.
        earlier = [(n, _load(model, seed, n, run_id=run_id))
                   for n in range(1, life)]
        earlier = [(n, d) for n, d in earlier if d]
        if not earlier:
            raise SystemExit(f"没有 {model}_{seed}_{ENGINE_VERSION} 之前几条命的记录")
        first = earlier[0][1]
        prior_armour_evidenced = any(
            d.get("behaviour", {}).get("armour", {}).get("evidence_events", 0)
            or d.get("behaviour", {}).get("armour", {}).get("breaks", 0)
            or d.get("opportunities", {}).get("armour", 0)
            for _, d in earlier)
        camp_log, notes = first["camp_log"], first.get("notes", "")
        camp_experiments = first.get("camp_experiments")
        camp_used, left_early = first["camp_used"], first["left_early"]
        transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(camp_log, 1))
        prev_adv = [(n, d.get("adv_log", []), d.get("result", "?"))
                    for n, d in earlier]
        if verbose:
            for n, log, res in prev_adv:
                print(f"  带上第 {n} 条命：{adventure_steps(log)} 步，结局 {res}",
                      flush=True)
            print(f"第 {life} 条命：跳过训练营，训练营记录 "
                  f"{participant_steps(camp_log)} 步\n",
                  flush=True)
    elif reuse_camp:
        # `camp_from` so a control arm can reuse ANOTHER run's camp. Without
        # it the two arms differ in their training camp as well as in the thing
        # under test, which is one uncontrolled variable too many.
        old = _load(model, seed, run_id=camp_from or run_id)
        if not old:
            raise SystemExit(f"没有 {model}_{seed} 的训练营记录，先跑 --camp-only")
        camp_log, notes = old["camp_log"], old.get("notes", "")
        camp_experiments = old.get("camp_experiments")
        camp_used, left_early = old["camp_used"], old["left_early"]
        transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(camp_log, 1))
        if verbose:
            print(f"复用已有训练营记录：{camp_used} 回合，"
                  + ("提前离开" if left_early else "用满") + "\n", flush=True)
    else:
        camp_log, camp_experiments = _run_camp(
            model, key, camp, camp_turns, verbose, camp_steps, letters_block(letters))
        camp_used = turns_used(camp, camp_turns)
        left_early = camp_log[-1] == "LEAVE" if camp_log else False
        transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(camp_log, 1))
        notes = ""
        if want_notes:
            notes = call(model, "You are reporting what you learned from an "
                                "experiment. Answer in prose. Do not reply with "
                                "an action.",
                         "You interacted with an unknown system. Here is the "
                         "full record:\n\n" + transcript + "\n\n" + DEBRIEF, key)
            if verbose:
                print(f"\n{'='*58}\n训练营结论（第 {camp_used} 回合"
                      + ("提前离开" if left_early else "用满") + "）:\n", flush=True)
                print(notes, flush=True)
                print("=" * 58 + "\n", flush=True)
            _dump(model, seed, life=life, run_id=run_id,
                  payload=dict(camp_log=camp_log, camp_used=camp_used,
                               camp_experiments=camp_experiments,
                               left_early=left_early, notes=notes,
                               salt=salt, world=world, pack=pack,
                               letters_from=list(letters_from or ())))

    if camp_only:
        return dict(run=run, camp_log=camp_log, camp_used=camp_used,
                    camp_experiments=camp_experiments,
                    left_early=left_early, notes=notes, adv_log=[],
                    adv_notes="", fight_notes=[], mistakes={}, opportunities={},
                    encounters={}, result="camp only", hp=run.hp, usage=_usage_since(u0), prompt_order=PROMPT_ORDER,
                    api=api_settings(model))
    handover = build_handover(life, carry, transcript, notes,
                              prev_adv if life > 1 else (), earlier if life > 1 else (), letters)

    # ---- adventure ----
    adv_log = HarnessLog()
    fnotes = []
    # 被动观察器的三件状态。`fight_index` 是这条命里第几场战斗（含 boss 各段），
    # 主指标 B 的「第 k 次可执行机会」和辅助 A 的「证据之后」都按它排序。
    evidence = observe.Evidence()
    kth_opps: list = []
    fight_index = [0]
    mistakes: dict[str, int] = {}
    opportunities: dict[str, int] = {}
    resource = {"zero_effect_exhaust": 0, "heal_plays": 0,
                "full_heal_turns": 0}
    planning = {"avoidable_lethal": 0, "opportunities": 0}
    behaviour = _new_behaviour_metrics()
    metric_state = {"armour_evidenced": prior_armour_evidenced}
    encounters: dict[str, int] = {}
    # Audit only -- never shown to the model. See the note on Fight's counters.
    shield_audit = {"blocked": 0, "unblocked": 0, "fully_absorbed": 0,
                    "absorbed_total": 0, "fights": 0,
                    "blind": 0,              # engine-side: unlearnable turns
                    "matched_absorb": 0,     # model DID produce a clean control
                    "unmatched_absorb": 0}   # model did not -- a design failure,
                                             # not an information failure
    result = "cleared"
    # 登记 12（TUNING["auto_rest"]）：休息层没有选择 —— 不问模型（不调 pick、不写休息笔记），引擎自动补给
    # （回 rest_pct% 当前上限的血，封顶），日志写一行环境事件 resupply_line；不计分（不进 mistakes / B 表）。
    auto_rests = [] if TUNING["auto_rest"] else None

    def resupply(i):
        before = (run.hp, run.max_hp, run.base_atk, run.poison)
        hp0, hp1 = run.auto_resupply()
        line = resupply_line(i, run_changes(run, before))
        adv_log.append(line)
        auto_rests.append(dict(layer=i, hp_before=hp0, hp_after=hp1, cap=run.max_hp, scored=False, line=line))
        if verbose:
            print(f"  第{i}层 自动补给（环境事件，不计分）{hp0}->{hp1}", flush=True)

    for i, layer in enumerate(run.layers, 1):
        # Only the KIND of each node is offered. Which monster is behind it is
        # not on the signpost, and every fightable node in a layer is the same
        # kind of monster anyway -- so what is being chosen is ordinary or
        # elite, risk against growth, not a guess about what is waiting.
        opts = layer.kinds()
        context = _carried(fight_notes, fnotes, handover)
        if auto_rests is not None and all(k == "rest" for k in opts):
            resupply(i)
            continue
        j = pick(model, key, f"Layer {i}. Choose:", opts, adv_log,
                 carry=context)
        if opts[j] == "rest" and auto_rests is not None:
            resupply(i)
            continue
        if opts[j] == "rest":
            # The model picks how to spend the rest, same as the human does.
            before_log = list(adv_log)
            choices = ["recover health (+?)", "recover maximum (+?)"]
            m = pick(model, key, f"Layer {i}. You stop here:", choices,
                     adv_log, carry=context)
            mode = "hp" if m == 0 else "cap"
            if rest_opportunity(run):
                opportunities["poison"] = opportunities.get("poison", 0) + 1
                _inc(behaviour, "poison", "decisions")
                # 主指标 B 也要收到它。毒唯一的可执行机会在休息点，而观察器只
                # 挂在战斗循环上 —— v1 因此让毒整条机制缺席 B 表。
                observe.note_rest(kth_opps, fight_index[0],
                                  rest_mistake(run, mode))
            if rest_mistake(run, mode):
                mistakes["poison"] = mistakes.get("poison", 0) + 1
                _inc(behaviour, "poison", "wrong_rests")
            before = (run.hp, run.max_hp, run.base_atk, run.poison)
            run.rest(mode)
            changed = run_changes(run, before)
            entry = (f"[layer {i}] rested"
                     + (f" -> {changed}" if changed
                        else " -> (nothing changed)"))
            adv_log.append(entry)
            if verbose:
                print(f"  第{i}层 休息" + (f" -> {changed}" if changed else ""),
                      flush=True)
            _note_rest(model, key, fight_notes, fnotes, f"layer {i}",
                       before_log, choices[m],
                       changed or "(nothing changed)", verbose)
            continue
        # `pays_milestone`, not `opts[j] == "elite"`. Under curriculum=4
        # there is no elite kind, so the old test was constantly false: this
        # loop handed out 0 attribute upgrades and 10 card takes while the
        # reference line it is compared against took 2 and 8.
        elite = pays_milestone(layer.nodes[j])
        # 「里程碑」，不是「精英」。curriculum=4 下 `kind` 永远是 "fight"，
        # elite STRENGTH 只在 curriculum=2 存在 —— 所以这一场和别的一样硬，
        # 区别只在打完之后发什么。操作台也不该被这个词误导。
        if verbose: print(f"  第{i}层 {'里程碑' if elite else '战斗'}"
                          f" ({layer.nodes[j].behaviour})", flush=True)
        f = run.fight_at(i - 1, j)
        fight_index[0] += 1
        for mechanic in f.parts:
            if mechanic in COUNTED:
                encounters[mechanic] = encounters.get(mechanic, 0) + 1
        # 参与者这边不加任何标签，而且不是疏忽。这一行是模型读得到的历史,
        # 而 "elite" 在这个游戏里既不是一个存在的节点种类，也不是关于这场
        # 战斗强度的真话。更要紧的是，整套设计把牌名、槽位、机制全部做成了
        # 无语义符号，然后在这里发一个英文难度提示，是白送的一格信息。
        #
        # 信息并没有被藏起来：打完之后这一层给的是 `a1 +?` / `A5 +?` 的选单
        # 而不是一张牌，日志里那两行长得就不一样。要发现「第 4 层和第 10 层
        # 给的东西不同」，靠的是读自己的记录，这正是要考的东西。
        adv_log.append(f"[layer {i}] fight begins")
        mark = len(adv_log)
        encounter_metric = _new_encounter_metric(f"layer {i}", f)
        behaviour["encounters"].append(encounter_metric)
        won = run_fight(model, key, ADV_SYSTEM, f, adv_log, verbose,
                        _carried(fight_notes, fnotes, handover), mistakes,
                        opportunities, resource, planning, behaviour,
                        encounter_metric, metric_state,
                        watcher=observe.Watcher(evidence, kth_opps,
                                                fight_index[0]))
        ended = f"[layer {i}] fight ended"
        adv_log.append(ended)
        if verbose:
            print(f"    {ended}", flush=True)
        _collect_shield_audit(shield_audit, f)
        run.absorb(f)
        # 标签是模型读得到的（后面的命、命末总结里每条笔记前的 [layer 3, vs …]）。2026-10-19 之前写的是「第3层」，
        # 和休息笔记的 "layer 3"、日志的 "[layer 3]" 混在一起，英文提示里夹了一句中文。
        _note_fight(model, key, fight_notes, fnotes, f"layer {i}",
                    f.enemy.name, adv_log[mark:], verbose)
        if not won:
            result = f"died at layer {i}"; break
        if elite:
            picks = run.elite_rewards()
            k = pick(model, key, "Choose one:",
                     [lab for lab, _ in picks], adv_log,
                     carry=_carried(fight_notes, fnotes, handover))
            before = (run.hp, run.max_hp, run.base_atk, run.poison)
            run.apply_reward(picks[k][1])
            changed = run_changes(run, before)
            adv_log.append(f"[layer {i}] won, chose {picks[k][0]}"
                           + (f" -> {changed}" if changed else ""))
        else:
            cards = run.reward_choices() + ["take nothing"]
            k = pick(model, key, "You may take one card:", cards, adv_log,
                     carry=_carried(fight_notes, fnotes, handover))
            if k < len(cards) - 1:
                run.take(cards[k])
            adv_log.append(f"[layer {i}] won, took {cards[k]}")
    else:
        if verbose: print(f"  boss ({run.boss_behaviour})", flush=True)
        # One phase at a time. Each is a real encounter for the acquisition
        # metric: the second phase is the first chance to act on whatever the
        # first one showed, and folding them into one record would erase
        # exactly the thing that measurement is for.
        won, stage = True, 0
        for f in run.boss_fights():
            stage += 1
            label = f"boss {stage}"
            fight_index[0] += 1
            for mechanic in f.parts:
                if mechanic in COUNTED:
                    encounters[mechanic] = encounters.get(mechanic, 0) + 1
            adv_log.append(f"[{label}] begins")
            mark = len(adv_log)
            encounter_metric = _new_encounter_metric(label, f)
            behaviour["encounters"].append(encounter_metric)
            won = run_fight(model, key, ADV_SYSTEM, f, adv_log, verbose,
                            _carried(fight_notes, fnotes, handover), mistakes,
                            opportunities, resource, planning, behaviour,
                            encounter_metric, metric_state,
                            watcher=observe.Watcher(evidence, kth_opps,
                                                    fight_index[0]))
            ended = f"[{label}] fight ended"
            adv_log.append(ended)
            if verbose:
                print(f"    {ended}", flush=True)
            _collect_shield_audit(shield_audit, f)
            _note_fight(model, key, fight_notes, fnotes, label,
                        f.enemy.name, adv_log[mark:], verbose)
            # Before the break, exactly as the journey loop does it. Absorbing
            # only on a win left `run.hp` holding the health the player ENTERED
            # the stage with, so life 4's record said `died at boss 2` and
            # `hp=32` while its own log ends `a3: 8->0`.
            run.absorb(f)
            if not won:
                break
            # No rest and no reward between phases -- only the carry.
        result = "cleared" if won else f"died at boss {stage}"

    adv_notes = ""
    if want_notes:
        adv_notes = call(model, "You are reporting what you learned. Answer in prose.",
                         build_life_debrief(adv_log, fnotes), key)
    screen_values = getattr(run, "screen", None)
    screen_report = (dict(observable=screen_values[0],
                          privileged=screen_values[1],
                          worst_partial=screen_values[2],
                          mean_turns=screen_values[3],
                          reach_boss=screen_values[4],
                          attempt=screen_values[5],
                          salt=getattr(run, "selected_salt", None),
                          config=getattr(run, "screen_config", None))
                     if screen_values and len(screen_values) == 6 else None)
    _dump(model, seed, life=life, run_id=run_id, payload=dict(
                            engine=ENGINE_VERSION,
                            metrics=METRICS_VERSION,
                            # The world is (seed, salt), not seed. Two lives of
                            # one identity are two different maps, and a record
                            # that names only the seed cannot say which one it
                            # played -- nor whether it was a confirmed world at
                            # all. `carry` is here for the same reason: what
                            # crossed over is a condition of the experiment, and
                            # a transfer number means nothing without it.
                            salt=salt,
                            world_status=(_world_status(seed, salt) if registered
                                          else "confirmed-development"
                                          if salt is not None
                                          and (seed, salt) in _CONFIRMED
                                          else "screened" if salt is None
                                          else "UNCONFIRMED"),
                            registered=registered,
                            carry=carry, notes_written=bool(want_notes),
                            fight_notes_carry=fight_notes,
                            screen=screen_report,
                            adv_log=adv_log, adv_notes=adv_notes,
                            fight_notes=fnotes, fight_notes_mode=fight_notes,
                            usage=_usage_since(u0), prompt_order=PROMPT_ORDER, api=api_settings(model),
                            life_debrief=LIFE_DEBRIEF if want_notes else None,
                            harness_language=HARNESS_LANGUAGE,
                            world=world, pack=pack, letters_from=list(letters_from or ()),
                            letters_sha=_sha(letters_block(letters)) if letters else None,
                            trace_version=TRACE_VERSION, trace=list(TRACE),
                            mistakes=mistakes, opportunities=opportunities,
                            # 主指标 B 的原子记录（有序），和辅助 A 的证据时刻。
                            # A 的名字是「客观判别性证据已出现在可见信息中」，
                            # 不是「模型认出了机制」。
                            kth_opportunities=kth_opps,
                            evidence=evidence.seen,
                            behaviour=behaviour,
                            resource=resource, planning=planning,
                            encounters=encounters, shield_audit=shield_audit,
                            camp_log=camp_log, camp_used=camp_used,
                            camp_experiments=camp_experiments,
                            left_early=left_early, notes=notes,
                            result=result, hp=run.hp,
                            run_id=run_id, camp_from=camp_from,
                            **({} if auto_rests is None else dict(rest_rule="auto_rest", auto_rests=auto_rests))))
    return dict(run=run, camp_log=camp_log, camp_used=camp_used,
                camp_experiments=camp_experiments,
                left_early=left_early, notes=notes, adv_log=adv_log,
                adv_notes=adv_notes, fight_notes=fnotes, mistakes=mistakes,
                opportunities=opportunities, behaviour=behaviour,
                resource=resource,
                planning=planning, encounters=encounters,
                shield_audit=shield_audit,
                result=result, hp=run.hp,
                **({} if auto_rests is None else dict(rest_rule="auto_rest", auto_rests=auto_rests)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("seed", type=int)
    ap.add_argument("--salt", type=int, default=None,
                    help="直接构造这个 (seed, salt) 世界，不调用 make_run、"
                         "不重新搜索 salt、不使用旧的合取门")
    ap.add_argument("--turns", type=int, default=CAMP_TURNS)
    ap.add_argument("--carry", choices=("none", "notes", "log", "both"), default="notes")
    ap.add_argument("--no-notes", dest="notes", action="store_false")
    ap.add_argument("--camp-only", action="store_true")
    ap.add_argument("--reuse-camp", action="store_true",
                    help="复用已存的训练营记录，只跑冒险")
    ap.add_argument("--run-id", default=MAIN_RUN,
                    help=f"实验条件名（默认 {MAIN_RUN}）。记录文件按它分开存 —— "
                         "文件名里没有 salt，所以同 seed 的两个条件不加这个"
                         "会互相覆盖")
    ap.add_argument("--camp-from", default=None,
                    help=f"复用另一个 --run-id 的训练营记录（例如 {MAIN_RUN}），"
                         "让对照臂和迁移臂连训练营经历都相同")
    ap.add_argument("--life", type=int, default=1,
                    help="第几条命；>1 时跳过训练营，带上一条命的完整交互记录")
    ap.add_argument("--registered", action="store_true",
                    help="按 --salt 所属的登记构造世界：登记 8 的六池包（devworld.CERTIFIED_PACKS）、"
                         "登记 9 的七池图库（devworld.LIBRARY / LIBRARY_PACKS）；未认证的 salt 用当前登记")
    ap.add_argument("--fight-notes", choices=("none", "write", "show"),
                    default="write",
                    help="每场战斗和休息后的总结：不写 / 写了不给看 / 写了并带进后续决策")
    ap.add_argument("--world", default=None, help="世界（A–E，devworld.WORLDS）：按这个世界的身份、经济和认证图构造")
    ap.add_argument("--pack", default=None, help="这个世界里的包名（例如 B-3），决定牌名")
    ap.add_argument("--letters-from", default="",
                    help="之前每个世界的 run-id，逗号分隔、按先后；它们的信放在这个世界每一次决策的最前面")
    ap.add_argument("--write-letter", action="store_true",
                    help="不玩：读这个 run-id 的训练营和五条命，写离开这个世界时的信")
    ap.add_argument("--prompt-order", choices=PROMPT_ORDERS, default=PROMPT_ORDER,
                    help="一次调用里各段的顺序：history-first（默认，历史在画面前，前缀缓存全命中）/ screen-first（旧记录的顺序）")
    a = ap.parse_args()
    PROMPT_ORDER = a.prompt_order
    letters_from = [x for x in a.letters_from.split(",") if x]
    if a.write_letter:
        write_letter(a.model, a.seed, a.run_id, a.carry, letters_from=letters_from)
        raise SystemExit(0)
    if a.world is not None:
        import devworld
        print(f"world={a.world} pack={a.pack} salt={a.salt} letters_from={letters_from}", flush=True)
    elif a.salt is not None and a.registered:
        import devworld
        print(devworld.banner_registered(a.seed, a.salt, devworld.build_registered(a.seed, a.salt)), flush=True)
    elif a.salt is not None:
        # First, before anything else is printed. Taking a world from the wrong
        # configuration while believing it is a confirmed one is the failure
        # this banner exists to make impossible to miss.
        import devworld
        print(devworld.banner(a.seed, a.salt), flush=True)
    print(f"engine={ENGINE_VERSION} model={a.model} seed={a.seed} "
          f"carry={a.carry} notes={a.notes} fight-notes={a.fight_notes} prompt-order={PROMPT_ORDER}\n",
          flush=True)
    r = main(a.model, a.seed, a.turns, a.carry, a.notes,
             camp_only=a.camp_only, reuse_camp=a.reuse_camp,
             fight_notes=a.fight_notes, life=a.life, salt=a.salt,
             run_id=a.run_id, camp_from=a.camp_from, registered=a.registered,
             world=a.world, pack=a.pack, letters_from=letters_from)
    print(f"\n{'='*58}\n结果: {r['result']}   剩余血量 {r['hp']}")
    print(f"训练营: 第 {r['camp_used']} 回合" + ("提前离开" if r["left_early"] else "用满"))
    if r["notes"]:
        print(f"\n训练营结论:\n{r['notes']}")
    for n in r.get("fight_notes", []):
        if n.get("kind") == "rest":
            print(f"\n{n['tag']} 休息总结:\n{n['text']}")
        else:
            print(f"\n{n['tag']} 战后总结（{n['enemy']}）:\n{n['text']}")
    if r["adv_notes"]:
        print(f"\n冒险结论:\n{r['adv_notes']}")
    print(f"\n{'='*58}\n真实设定:")
    for n, c in r["run"].deck.items():
        print(f"  {n:<7} {c}")
    for i, l in enumerate(r["run"].layers, 1):
        print(f"  第{i}层 {l.behaviour}")
    print(f"  boss   {r['run'].boss_behaviour}")
