"""Continuous conversation inside one fight (ARC-AGI-3 "provider adapter" style; 2026-11-13, user: 「我能不能做一个arc那样的provider-adapte的调用方式」→「可以」).

Default OFF. AGII_HARNESS=stateless (default) keeps today's calls: every step is one system + one user message, and only
the visible fight log and the 200-token working note carry anything from one step to the next.
AGII_HARNESS=continuous: inside one modelrun.run_fight call, the steps form one native multi-turn conversation and the
provider's own reasoning state is replayed with every earlier answer (same idea as ARC's Provider Adapter harness,
https://github.com/arcprize/arc-agi-3-benchmarking, docs/runtime-state.md):
  * Claude through OpenRouter Messages: every earlier assistant content block is replayed as returned, thinking blocks
    with their signatures included.
  * GPT (Responses through OpenRouter, store=false): every earlier output item is replayed, reasoning items with their
    encrypted_content included; message items lose only their transient id.
  * DeepSeek / other Chat Completions routes on OpenRouter: the earlier answer plus its reasoning_details.
  * Anything else (direct provider routes, Gemini): refused, not silently run stateless.
What the participant is shown does not change. The first step of a fight sends the same user text as stateless mode;
each later step sends only what is new since the previous step (the new fight-log lines and the new screen, i.e. the
request blocks after the part the conversation already holds). If the earlier part of the prompt ever differs from what
the conversation holds, the full text is sent again and the step is marked resync (never expected in a fight; counted).
The system prompt, the game, the note rule, the action parser, limits and scoring are untouched. The conversation ends
with the fight (the working note is cleared at the same boundary); camp, letters and later fights stay as they are.
Results from the two harnesses are reported separately, as ARC does.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import functools
import os

VERSION = "continuous-conversation-v1-2026-11-13"
MODES = ("stateless", "continuous")
_SCOPE = ContextVar("transverse_conversation_scope", default=None)


def mode():
    m = os.environ.get("AGII_HARNESS", "stateless").strip() or "stateless"
    if m not in MODES:
        raise SystemExit(f"AGII_HARNESS must be one of {MODES}, not {m!r}")
    return m


def enabled():
    return mode() == "continuous"


def route(model):
    """Which replay a model gets in continuous mode, or None when it is not supported."""
    import modelrun as mr
    import openrouter_backend as router
    if mr.provider_for(model) != "openrouter":
        return None
    if model in router.CLAUDE_MODELS:
        return "messages"
    if router.uses_responses(model):
        return "responses"
    if model == router.GEMINI_MODEL:
        return None
    return "chat"


def settings(model):
    r = route(model)
    replay = dict(messages="all assistant content blocks incl. thinking + signature",
                  responses="all output items incl. reasoning encrypted_content; store=false",
                  chat="assistant content + reasoning_details")[r]
    return dict(harness=VERSION, conversation_state=f"continuous within one fight; {replay}; later steps send only new text")


@contextmanager
def scope(label="fight"):
    state = dict(label=label, turns=[], held=None, steps=0, resyncs=0)
    token = _SCOPE.set(state)
    try:
        yield state
    finally:
        _SCOPE.reset(token)


def active():
    return _SCOPE.get()


def wrap_run_fight(mr):
    """One conversation per modelrun.run_fight call. functools.wraps keeps __wrapped__ (antagonist_boss._quiet_model_log)."""
    if getattr(mr.run_fight, "_conversation_scope", False):
        return
    inner = mr.run_fight

    @functools.wraps(inner)
    def run_fight(*a, **k):
        with scope("fight"):
            return inner(*a, **k)
    run_fight._conversation_scope = True
    mr.run_fight = run_fight


def _texts(blocks, user):
    return [t for t, _m in blocks if t] if blocks else [user]


def delta(state, user, blocks):
    """What this step adds to the conversation: (new blocks [(text, mark)], resync?). `held` = the texts of every block the
    conversation already holds, in order (the previous request's blocks)."""
    texts = _texts(blocks, user)
    if "".join(texts) != user:
        raise ValueError("request blocks differ from participant text")
    held = state["held"]
    if held is None:
        return [(t, False) for t in texts], False
    # Everything the previous request showed except its last block (the screen, which always changes) must be a prefix.
    keep = held[:-1]
    if texts[:len(keep)] == keep and len(texts) > len(keep):
        new = texts[len(keep):]
        new[0] = new[0].lstrip("\n")
        new = [(t, False) for t in new if t]
        if new:
            return new, False
    return [(t, False) for t in texts], True


def begin_step(user, blocks):
    """Called before a request inside a scope. Returns the info journalled with the call."""
    state = _SCOPE.get()
    new, resync = delta(state, user, blocks)
    info = dict(version=VERSION, scope=state["label"], step=state["steps"] + 1, prior_turns=len(state["turns"]),
                resync=resync, sent_text="".join(t for t, _m in new))
    return dict(info=info, new=new)


def end_step(step, user, blocks, response, route_name):
    """After a successful (or replayed) response: the conversation now holds this user message and the answer."""
    state = _SCOPE.get()
    state["turns"].append(dict(user=[t for t, _m in step["new"]], answer=_answer(response, route_name)))
    state["held"] = _texts(blocks, user)
    state["steps"] += 1
    state["resyncs"] += step["info"]["resync"]


def _answer(response, route_name):
    response = response or {}
    if route_name == "messages":
        keep = []
        for b in response.get("content") or []:
            t = b.get("type")
            if t == "thinking":
                keep.append(dict(type="thinking", thinking=b.get("thinking", ""), signature=b.get("signature", "")))
            elif t == "redacted_thinking":
                keep.append(dict(type="redacted_thinking", data=b.get("data", "")))
            elif t == "text" and b.get("text"):
                keep.append(dict(type="text", text=b["text"]))
        return keep
    if route_name == "responses":
        items = []
        for it in response.get("output") or []:
            it = copy.deepcopy(it)
            if it.get("type") == "message":
                it.pop("id", None)
                it.pop("status", None)
            items.append(it)
        return items
    msg = ((response.get("choices") or [{}])[0].get("message") or {})
    out = dict(role="assistant", content=msg.get("content") or "")
    if msg.get("reasoning_details"):
        out["reasoning_details"] = copy.deepcopy(msg["reasoning_details"])
    return out


def _marked_last(parts, mark_key):
    if parts:
        parts[-1] = dict(parts[-1], **mark_key)
    return parts


def messages_body(state, step):
    """Anthropic Messages list. Cache marks: end of the previous user message and end of this one (≤ 4 with system)."""
    cc = {"cache_control": {"type": "ephemeral"}}
    msgs = []
    for i, turn in enumerate(state["turns"]):
        content = [dict(type="text", text=t) for t in turn["user"]]
        if i == len(state["turns"]) - 1:
            _marked_last(content, cc)
        msgs.append(dict(role="user", content=content))
        msgs.append(dict(role="assistant", content=copy.deepcopy(turn["answer"]) or [dict(type="text", text="(no answer)")]))
    msgs.append(dict(role="user", content=_marked_last([dict(type="text", text=t) for t, _m in step["new"]], cc)))
    return msgs


def responses_input(state, step, system):
    mark = {"prompt_cache_breakpoint": {"mode": "explicit"}}
    items = [dict(role="system", content=system)]
    for i, turn in enumerate(state["turns"]):
        parts = [dict(type="input_text", text=t) for t in turn["user"]]
        if i == len(state["turns"]) - 1:
            _marked_last(parts, mark)
        items.append(dict(role="user", content=parts))
        items += copy.deepcopy(turn["answer"])
    items.append(dict(role="user", content=_marked_last([dict(type="input_text", text=t) for t, _m in step["new"]], mark)))
    return items


def chat_messages(state, step, system):
    msgs = [dict(role="system", content=system)]
    for turn in state["turns"]:
        msgs.append(dict(role="user", content="".join(turn["user"])))
        msgs.append(copy.deepcopy(turn["answer"]))
    msgs.append(dict(role="user", content="".join(t for t, _m in step["new"])))
    return msgs
