"""工作便签（PROTO_WORKNOTE=on；2026-11-11 用户：「你来做」）。默认 off：什么也不装，所有输出逐字不变。

规则（人和模型逐字相同，英文）：
  · 每次选动作的回复：第一行是动作；可加一行以 NOTE: 开头的工作便签（至多 LIMIT token），整张替换旧便签；
    没有 NOTE: 行 = 保留旧便签；NOTE: (empty) = 清空。超长按 o200k 截到 LIMIT token（事先写在规则里）。
  · 每一步都看到最新一版（模型：提示里 "Your move:" 之前一行 "Working note: …"；人：输入框之前印同一行）。
  · 一场战斗（同一个 Fight 对象；boss 换阶段不换对象，不清空）结束即清空；营地整段算一段（RESET 不清空）。
  · 历次版本存档（记录的 work_note.versions）；写战斗笔记、营后笔记、boss 命笔记时，只把这一段的最后一版附在记录之后
    （11-11 用户：不给修改历史；空的不附）。
  · 动作只从 NOTE: 之前的文字里找：便签里写到牌名不会被当成动作。

实现（运行时替换，session() 里装、退出还原）：
  modelrun.act          → act：换系统提示（ADV_SYSTEM / CAMP_SYSTEM → 带便签规则的版本），调用期间临时换
                          modelrun.build_act_blocks（在 "Your move:" 前插便签行）、modelrun.call（拆出便签，只把动作部分交回原 act 解析）、
                          humanrun.input（人：先印便签行，读入一行后拆出便签，只把动作部分交回 human_act）。
  modelrun._call_kind   → 同样只在一次出牌调用期间换：带便签规则的系统提示按原系统提示认种类（act / camp-act 不变）；
                          不在整条命期间换，proto_text.session() 开头要它是原函数。
记录里多一个键 work_note（只在 on 时）；adv_log、画面、审计重放的一切不变（便签不进 adv_log）。
"""
from __future__ import annotations

import builtins
import contextlib
import os
import re

import modelrun
import humanrun
import antagonist_proto as ap
import proto_text as pt

VERSION = "work-note-v2-2026-11-11"     # v2：上限 100 → 200 token（用户 11-11「给200吧」）
LIMIT = 200
EMPTY = "(empty)"
LINE = "Working note: {note}"
_RULE = (f"You may add a second line starting with NOTE: to rewrite your working note (at most {LIMIT} tokens; "
         "a longer note is cut). It replaces your previous working note. Without a NOTE: line the previous one is kept; "
         f"NOTE: {EMPTY} clears it. Your working note is shown to you at every step")
ADV_SYSTEM = ("Each step: on the first line, type one operation name, or END to end the turn.\n"
              + _RULE + " of this fight and is cleared when the fight ends.")
CAMP_SYSTEM = ("You can practice here for a while.\n"
               "Each step: on the first line, type one operation name, END to end the turn, RESET to start over, or LEAVE to leave.\n"
               + _RULE + " here and is cleared when you leave.")
FINAL_HEAD = "Your working note at the end of this fight:"          # 写笔记时只附最后一版（11-11 用户：不给修改历史）
FINAL_HEAD_CAMP = "Your working note at the end of the camp:"
if os.environ.get("AGII_SIMPLE_NOTES") == "1":
    VERSION = "work-note-v3-simple-2026-11-11"
    _SIMPLE_RULE = (f"Optional second line:\nNOTE: a short note, up to {LIMIT} tokens.\n\n"
                    "The note replaces the old one. Omit NOTE to keep it.\n"
                    "NOTE: (empty) clears it.\n")
    ADV_SYSTEM = ("First line: an action, or END.\n\n" + _SIMPLE_RULE +
                  "You can see your note throughout this fight.\nIt is cleared when the fight ends.")
    CAMP_SYSTEM = ("First line: an action, END, RESET, or LEAVE.\n\n" + _SIMPLE_RULE +
                   "You can see your note throughout this camp.\nIt is cleared when you leave.")
    FINAL_HEAD = FINAL_HEAD_CAMP = "Your note:"
NOTE_RE = re.compile(r"(?:^|\s)NOTE\s*:", re.I)
for _t in (ADV_SYSTEM, CAMP_SYSTEM, FINAL_HEAD, FINAL_HEAD_CAMP, LINE):
    modelrun._assert_english("work_note", _t)

_CAMP = object()                                    # 营地整段的段标记
_S = dict(seg=None, seq=0, kind=None, enemy=None, note="", versions=[], step=0)


def on() -> bool:
    return getattr(ap, "WORKNOTE", "off") == "on"


def _enc():
    import tiktoken
    return tiktoken.get_encoding("o200k_base")


def split(raw):
    """(动作部分, 便签或 None)。便签 = 第一个 NOTE: 之后的全部文字（可多行）；"(empty)" → ""。"""
    if not isinstance(raw, str):
        return raw, None
    m = NOTE_RE.search(raw)
    if not m:
        return raw, None
    note = raw[m.end():].strip()
    return raw[:m.start()], ("" if note.lower() == EMPTY else note)


def _set(note):
    """记一版便签（None = 保留，不记）。截到 LIMIT token。"""
    if note is None:
        return
    enc = _enc()
    ids = enc.encode(note)
    cut = len(ids) > LIMIT
    # 截到 LIMIT token 时按字节解码、丢掉被切开的半个字符（中文等多字节字符不会变成乱码）
    text = enc.decode_bytes(ids[:LIMIT]).decode("utf-8", errors="ignore").strip() if cut else note
    _S["note"] = text
    _S["versions"].append(dict(seg=_S["seq"], kind=_S["kind"], enemy=_S["enemy"], step=_S["step"], text=text,
                               tokens=len(enc.encode(text)) if cut else len(ids), truncated=cut, written_tokens=len(ids)))


def line():
    return LINE.format(note=_S["note"] or EMPTY)


def _enter(obj, system):
    camp = system in (pt.CAMP_SYSTEM, CAMP_SYSTEM)
    key = _CAMP if camp else obj                    # 存对象本身（按身份比）：id() 在上一场对象回收后可能被新的一场重用
    if key is not _S["seg"]:
        _S.update(seg=key, seq=_S["seq"] + 1, kind="camp" if camp else "fight", note="",
                  enemy=None if camp else getattr(getattr(obj, "enemy", None), "name", None))
    _S["step"] += 1


def versions_of(obj=None, camp=False):
    """这一段（这一场 / 营地）的全部版本，按先后。"""
    if camp:
        segs = {v["seg"] for v in _S["versions"] if v["kind"] == "camp"}
    else:
        segs = {_S["seq"]} if _S["seg"] is obj else set()
    return [v for v in _S["versions"] if v["seg"] in segs]


def block(versions):
    """写笔记时附在记录之后的那一段：只给这一段的最后一版（参与者自己决定便签里留什么，系统不把改掉的中间稿捡回来）；
    没写过或最后一版是空的 → 不附。单换行接问题之前的段落，人看到的提示里也有。历次版本照旧全部存进记录。"""
    if not versions or not versions[-1]["text"]:
        return ""
    head = FINAL_HEAD_CAMP if versions[-1]["kind"] == "camp" else FINAL_HEAD
    return head + "\n" + versions[-1]["text"]


def export():
    return dict(version=VERSION, limit=LIMIT, adv_system_sha=modelrun._sha(ADV_SYSTEM), camp_system_sha=modelrun._sha(CAMP_SYSTEM),
                versions=list(_S["versions"]), steps=_S["step"])


@contextlib.contextmanager
def session():
    """一条命（营地 + 各场）期间装上；off 时什么也不做。"""
    if not on():
        yield
        return
    _S.update(seg=None, seq=0, kind=None, enemy=None, note="", versions=[], step=0)
    saved_act = modelrun.act
    back = {ADV_SYSTEM: pt.ADV_SYSTEM, CAMP_SYSTEM: pt.CAMP_SYSTEM}

    def act(model, key, system, obj, screen, log, allow, carry=""):
        _enter(obj, system)
        system = {pt.ADV_SYSTEM: ADV_SYSTEM, pt.CAMP_SYSTEM: CAMP_SYSTEM}.get(system, system)
        prev_blocks, prev_call, prev_kind = modelrun.build_act_blocks, modelrun.call, modelrun._call_kind
        missing = object()
        prev_input = humanrun.__dict__.get("input", missing)
        read = prev_input if prev_input is not missing else builtins.input

        def blocks(*a, **k):
            out = prev_blocks(*a, **k)
            t, c = out[-1]
            assert t.endswith("Your move:"), t[-40:]
            out[-1] = (t[:-len("Your move:")] + line() + "\n\nYour move:", c)
            return out

        def call(m, s, u, k, blocks=None):
            raw = prev_call(m, s, u, k, blocks=blocks)
            action, note = split(raw)
            _set(note)
            return action

        def inp(prompt="> "):
            print(line(), flush=True)
            raw = read(prompt)
            action, note = split(raw)
            _set(note)
            return action.strip()

        def call_kind(s):                           # 带便签规则的系统提示按原系统提示认种类（act / camp-act）
            return prev_kind(back.get(s, s))

        modelrun.build_act_blocks, modelrun.call, modelrun._call_kind, humanrun.input = blocks, call, call_kind, inp
        try:
            return saved_act(model, key, system, obj, screen, log, allow, carry)
        finally:
            modelrun.build_act_blocks, modelrun.call, modelrun._call_kind = prev_blocks, prev_call, prev_kind
            if prev_input is missing:
                del humanrun.input
            else:
                humanrun.input = prev_input

    modelrun.act = act
    try:
        yield
    finally:
        modelrun.act = saved_act
