"""参与者文字开关 PROTO_TEXT（2026-11-05；docs/antagonist_boss/23_minimal_participant_text_draft.md，用户 11-05 定稿）。
PROTO_TEXT=minimal：proto_play 的参与者入口（模型、命令行人类、图形界面 worker）用 23 号文档 A1–A4、B1–B10、B12 的最简英文文字；
不设（= registered，默认）：本模块什么也不做，proto_play 的每一个输出逐字不变（默认路径一律不经过这里的任何函数）。
只在 scripts/ 里做运行时替换，core/ 一字不改：
  · 行动系统提示 B1：proto_play.adv_system 在这条命里把 modelrun.ADV_SYSTEM 换成 ADV_SYSTEM（同 v1.2 的换法），modelrun._call_kind 按文字
    认种类，新文字照样是 "adv-act"。
  · 笔记 / 信的系统提示 B6（NOTE_SYSTEM）：战后笔记、命末笔记、跨世界的信三处共用。modelrun._call_kind 只认 REPORTER 这一种笔记文字，
    所以 session() 里把 modelrun._call_kind 换成 call_kind：NOTE_SYSTEM 按调用处给种类（战后笔记 "note"，命末笔记和信 "debrief"，
    与默认文字下 REPORTER / "You are reporting what you learned. …" / LETTER_SYSTEM 各自得到的种类相同），其余交还原函数。
    call() 与 _trace_call 在调用时读模块全局 _call_kind，USAGE_BY_KIND / 记录的 usage.by_kind / TRACE 的 kind 都因此不变。
  · A1：session() 里 modelrun.LOCKED_ATTACK = ""，run_fight 写出 "  ->  a3: 111->90"；proto_play 在 run_fight 返回后、任何人读到这一行之前
    用 fix_locked() 去掉前面两个空格 → "->  a3: 111->90"。
  · B11（v2，11-05 晚）：休息行去掉 "automatic resupply"，写成 "[layer 3] -> a3: 52->123"（proto_play 在写进日志之前换，resupply_line）。
  · 解析（v2）：A1、B11 的新行在登记写法的解析器（audit/parse_log、audit/cards、audit/replay、recount_kills、c10v2、behaviour_report …）
    里认不出，所以每个读参与者日志的工具都经 audit/participant_text.registered_record() 读记录（按记录自己写的 participant_text.text /
    text_version 换回登记写法；默认记录原样返回、同一个对象）。这里的 registered_log / registered_record 就是它（审计包只许用标准库，
    所以实现放在 audit/ 里，这里转出）。读数与默认文字的同一条命相同（v3b_rule_check v3 的 Q 检查）。
  · 提示里剩下的结构语（v2，lead 11-05）：命末笔记 "Here is the full record:" → "Record:"、"What you wrote during this life:" → "Notes:"；
    show 臂 "What you wrote after earlier fights and rests:" → "Notes:"（carried）；行动提示 "What has happened so far:" → "This life:"
    （session() 里换 modelrun.build_act_blocks）；B3 一条命的记录 "Record of the previous life:"、几条 "Records of previous lives:"；
    缩写调用 "Your previous note:" → "Draft:"；人的笔记提示去掉 "[Write your notes]" 和 "One point per line"，印完整的 NOTE_SYSTEM
    （模型的系统提示）和 "(Empty line to finish.)"（只有人要：输入怎么结束）。"Your move:" 保留（提示的最后一行，告诉它在哪里答）。
  · 人的交接（11-05 夜，用户批准）：human_notes() 里同时换 humanrun._show_once —— 人不再看到只有人有的 "[Carried over]" 标签，交接逐字
    照模型收到的那一段印；只是光抬头（"World w, Camp" / "World w, Life k"，什么也没带）就不印。模型的文字不变，所以 VERSION 不改；
    人类 v3b 入口的记录按 proto_play.HUMAN_V3B_VERSION（entry v2）区分。
记录：minimal 下 participant_text 多 text / text_version / world_index / life_header 四个键，命末笔记多 adv_notes_cap；默认下一个键也不加。"""
import builtins, contextlib, os, pathlib, re, sys

import modelrun
import humanrun

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.append(_ROOT)                          # audit 包（registered_record 的实现，只用标准库）
from audit.participant_text import LOCKED_REGISTERED, NORM_ID, registered_log, registered_record, text_of   # noqa: E402,F401

VERSION = "proto-text-v2-2026-11-05"                # v2：B11、提示结构语压短、B3 单复数、人的笔记提示（v1 = proto-text-v1-2026-11-05）
MODES = ("registered", "minimal")
MODE = os.environ.get("PROTO_TEXT", "").strip() or "registered"
if MODE not in MODES:
    raise SystemExit(f"PROTO_TEXT={MODE!r}: only {MODES} (unset = registered)")


def minimal() -> bool:
    return MODE == "minimal"


# ---------------------------------------------------------------- 文字（23 号文档，逐字）
LIMIT = modelrun.LETTER_LIMIT                       # 命的笔记与世界的信同一个上限（B12；tiktoken o200k_base）
LIMIT_WORDS = LIMIT * 3 // 4                        # 与 modelrun.LETTER_QUESTION 的 "roughly … words" 同一算法
ADV_SYSTEM = "Each step: type one operation name, or END to end the turn.\nReply with only that word."          # B1
NOTE_SYSTEM = "Write prose. Do not reply with an operation."                                                    # B6
if __import__("os").environ.get("AGII_SIMPLE_NOTES") == "1":
    NOTE_SYSTEM = "Write a short note."
RECORD_HEAD = "Record of the previous life:"                                                                    # B3（一条命）
RECORDS_HEAD = "Records of previous lives:"                                                                     # B3（几条命，v2）
RECORD = "Record:"                      # v2：命末笔记里这条命的记录（原 "Here is the full record:"）
NOTES = "Notes:"                        # v2：命末笔记里这条命的笔记、show 臂行动提示里的笔记（原两句长的）
HISTORY = "This life:"                  # v2：行动提示里这条命到现在的记录（原 "What has happened so far:"）
HUMAN_END = "(Empty line to finish.)"   # v2：人写笔记时输入怎么结束（只有人要；原 "(One point per line. Submit an empty note to skip.)"）
LIMIT_SENTENCE = f"At most {LIMIT} tokens (about {LIMIT_WORDS} words)."
LIFE_QUESTION = "Write notes for your next life. " + LIMIT_SENTENCE                                             # B4 + B12
FIGHT_HEAD = "Opponent: {name}. Record of the fight:"                                                           # B5
FIGHT_QUESTION = "Write notes on this fight."                                                                   # B5
LETTER_QUESTION = "Write a note for the next place. Only this note carries over. " + LIMIT_SENTENCE             # B7
LETTERS_HEAD = "Notes you wrote before, oldest first:"                                                          # B8
SHORTEN = "{n} tokens; limit {limit}. Shorten it."                                                              # B9
PREVIOUS_NOTE = "Draft:"                            # v2：缩写调用里上一版（原 "Your previous note:"，modelrun.write_letter 的原文）
LIFE_HEADER = "World {w}, Life {k}"                                                                             # B2
LIFE_LABEL = "World {w}, Life {k}:"                                                                             # B10
if __import__("os").environ.get("AGII_SIMPLE_NOTES") == "1":
    LIFE_QUESTION = "Write a note for your next life. " + LIMIT_SENTENCE
    FIGHT_QUESTION = "Write a note about this fight."
    LETTER_QUESTION = "Write a note for the next world. Only this note carries over. " + LIMIT_SENTENCE
RESULT_CLEARED = "Result: cleared"                                                                              # A2
RESULT_NOT_CLEARED = "Result: not cleared ({where})"                                                            # A2
HEADER_RE = re.compile(r"World (\d+), Life (\d+)")
# 训练营（PROTO_CAMP=1，候选 v3b，18 §8.6；用户 11-05 晚定的系统提示；实现在 scripts/proto_camp.py）。不开营地时这些一个也不被读到。
CAMP_SYSTEM = ("You can practice here for a while.\n"
               "Each step: type one operation name, END to end the turn, RESET to start over, or LEAVE to leave.\n"
               "Reply with only that word.")
CAMP_HEADER = "World {w}, Camp"                     # 营地的抬头（模型每一步的提示开头、人的横幅）
CAMP_LABEL = "World {w}, Camp:"                     # 之后每条命带着的营后笔记的标签（同 B10 的 "World w, Life n:"）
CAMP_HISTORY = "This camp:"                         # 营地提示里记录的抬头（地图上是 HISTORY "This life:"）
CAMP_RECORD_HEAD = "Record of the camp:"            # log / both 臂带着的营地记录的抬头（同 B3）
for _t in (ADV_SYSTEM, NOTE_SYSTEM, RECORD_HEAD, RECORDS_HEAD, RECORD, NOTES, HISTORY, HUMAN_END, PREVIOUS_NOTE, LIFE_QUESTION, FIGHT_HEAD,
           FIGHT_QUESTION, LETTER_QUESTION, LETTERS_HEAD, SHORTEN, CAMP_SYSTEM, CAMP_HEADER, CAMP_LABEL, CAMP_HISTORY, CAMP_RECORD_HEAD):
    modelrun._assert_english("proto_text", _t)


def life_header(w, k):
    return LIFE_HEADER.format(w=w, k=k)


def life_label(w, k):
    return LIFE_LABEL.format(w=w, k=k)


def result_line(result):
    """A2：人类命令行 / 图形界面每条命末的那一行，不带血量。"""
    if result == "cleared":
        return RESULT_CLEARED
    m = re.fullmatch(r"died at (.+)", str(result))
    if not m:
        raise ValueError(f"unknown result {result!r}")
    return RESULT_NOT_CLEARED.format(where=m.group(1))


# ---------------------------------------------------------------- 调用种类（modelrun._call_kind 的运行时替换）
_ORIG_CALL_KIND = modelrun._call_kind
_KIND = ["note"]


def call_kind(system):
    if system == NOTE_SYSTEM:
        return _KIND[0]
    return _ORIG_CALL_KIND(system)


@contextlib.contextmanager
def kind(k):
    """NOTE_SYSTEM 的这次调用记成哪一种（默认 "note" = 战后笔记）。"""
    saved = _KIND[0]
    _KIND[0] = k
    try:
        yield
    finally:
        _KIND[0] = saved


# ---------------------------------------------------------------- 行动提示（modelrun.build_act_blocks 的运行时替换，v2）
_ORIG_ACT_BLOCKS = modelrun.build_act_blocks
HISTORY_REGISTERED = "What has happened so far:"
_HEAD = [HISTORY]                       # 营地期间换成 CAMP_HISTORY（history_head；默认就是 HISTORY，act_blocks 的输出不变）


@contextlib.contextmanager
def history_head(text):
    saved = _HEAD[0]
    _HEAD[0] = text
    try:
        yield
    finally:
        _HEAD[0] = saved


def act_blocks(carry, screen_text, hand_text, history, order=None):
    """modelrun.build_act_blocks 原样（同样的块、同样的缓存断点），只把这条命记录的抬头换成 HISTORY。只做 history-first（默认）。
    分层记忆（11-09）：carry 是 LayeredCarry 时，把记忆块拆成「旧记忆 + 每条战斗笔记各一块」，断点只打在最后一块上（断点总数不变，
    仍 ≤ 4）；拼起来逐字节同原来的那一块，只改缓存位置。下一场开头的请求就能读回上一场写下的「旧记忆 + 此前笔记」前缀。"""
    order = order or modelrun.PROMPT_ORDER
    if order != "history-first":
        raise RuntimeError(f"PROTO_TEXT=minimal only has the history-first prompt order, not {order!r}")
    out = []
    for t, c in _ORIG_ACT_BLOCKS(carry, screen_text, hand_text, history, order):
        if t in (HISTORY_REGISTERED, "\n\n" + HISTORY_REGISTERED):
            t = t[:-len(HISTORY_REGISTERED)] + _HEAD[0]
        out.append((t, c))
    if isinstance(carry, LayeredCarry) and out and out[0] == (str(carry), True):
        out[0:1] = carry.blocks
    return out


@contextlib.contextmanager
def session():
    """一条 minimal 的命 / 一封 minimal 的信：modelrun._call_kind → call_kind，modelrun.LOCKED_ATTACK → ""（A1），
    modelrun.build_act_blocks → act_blocks（v2）；退出时还原。"""
    if (modelrun._call_kind is not _ORIG_CALL_KIND or modelrun.LOCKED_ATTACK != "(locked attack resolves)"
            or modelrun.build_act_blocks is not _ORIG_ACT_BLOCKS):
        raise RuntimeError("modelrun._call_kind / LOCKED_ATTACK / build_act_blocks were already replaced (a nested life?); not replacing again")
    modelrun._call_kind, modelrun.LOCKED_ATTACK, modelrun.build_act_blocks = call_kind, "", act_blocks
    try:
        yield
    finally:
        modelrun._call_kind, modelrun.LOCKED_ATTACK, modelrun.build_act_blocks = _ORIG_CALL_KIND, "(locked attack resolves)", _ORIG_ACT_BLOCKS


def fix_locked(log, start=0):
    """A1：run_fight 在 LOCKED_ATTACK = "" 下写的 "  ->  …" → "->  …"（只有这一种行以两个空格加箭头开头）。返回改了几行。"""
    n = 0
    for i in range(start, len(log)):
        line = list.__getitem__(log, i)
        if isinstance(line, str) and line.startswith("  ->  "):
            list.__setitem__(log, i, line[2:])
            n += 1
    return n


RESUPPLY_REGISTERED = "] automatic resupply -> "


def resupply_line(line):
    """B11（v2）：modelrun.resupply_line 写的 "[layer 3] automatic resupply -> a3: 52->123" → "[layer 3] -> a3: 52->123"。"""
    if not re.match(r"^\[layer \d+\] automatic resupply -> ", line):
        raise ValueError(f"not a resupply line: {line!r}")
    return line.replace(RESUPPLY_REGISTERED, "] -> ", 1)


# registered_log / registered_record：见上面的 import（audit/participant_text.py）。按记录的 participant_text 换回登记写法；
# 默认记录原样返回。A1（"->  …" → "(locked attack resolves)  ->  …"）、B11（"[layer N] -> …" → "[layer N] automatic resupply -> …"）。


# ---------------------------------------------------------------- 交接、笔记、信的材料
def letters_block(letters):
    """B8（一封或几封都用同一个抬头）。"""
    letters = [t for t in (letters or ()) if t]
    if not letters:
        return ""
    if len(letters) == 1:
        return LETTERS_HEAD + "\n\n" + letters[0]
    return LETTERS_HEAD + "\n\n" + "\n\n".join(f"[{i}]\n{t}" for i, t in enumerate(letters, 1))


def prior_life_notes(earlier, w):
    """B10：每条前面的命一个抬头 "World w, Life n:"，下面是那条命的战后笔记（modelrun._render_notes 的原样）和命末笔记。"""
    parts = []
    for life, data in earlier:
        body = []
        if data.get("fight_notes"):
            body.append(modelrun._render_notes(data["fight_notes"]))
        if data.get("adv_notes"):
            body.append(data["adv_notes"])
        if body:
            parts.append(life_label(w, life) + "\n" + "\n\n".join(body))
    return "\n\n".join(parts)


def handover_evidence(carry, prev_adv, earlier, w, camp=None):
    """modelrun.handover_evidence（没有营地）的 minimal 版：B3 记录抬头、B10 每条命的标签（不带结果）。
    camp（PROTO_CAMP=1，proto_camp.evidence 的 {log, notes}；None = 没有营地，输出与之前逐字相同）：log / both 臂在各条命的记录前面放
    "Record of the camp:" + 营地记录；notes / both 臂在各条命的笔记前面放 "World w, Camp:" + 营后笔记（照命的笔记带法）。"""
    carried = []
    if carry in ("log", "both"):
        if camp and camp.get("log"):
            carried.append(CAMP_RECORD_HEAD + "\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(camp["log"], 1)))
        lives = [life_label(w, n) + "\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(log, 1)) for n, log, _res in prev_adv if log]
        if lives:
            carried += [RECORD_HEAD if len(lives) == 1 else RECORDS_HEAD] + lives
    if carry in ("notes", "both"):
        if camp and camp.get("notes"):
            carried.append(CAMP_LABEL.format(w=w) + "\n" + camp["notes"])
        written = prior_life_notes(earlier, w)
        if written:
            carried.append(written)
    return carried


def build_handover(life, carry, prev_adv, earlier, letters, w, camp=None):
    """第 1 条命：只有信（B8）；第 k>1 条命：B2 抬头 "World w, Life k"，后面接信、记录、笔记。不说上一条命的结果，不说符号。
    camp（PROTO_CAMP=1）：第 1 条命也有抬头 "World w, Life 1"（和营地分开），后面接信和营地（handover_evidence）；第 k>1 条命的证据里带营地。"""
    if life == 1 and camp is not None:
        return "\n\n".join([life_header(w, 1)] + ([letters_block(letters)] if letters else []) + handover_evidence(carry, (), (), w, camp))
    if life == 1:
        return letters_block(letters) if letters else ""
    carried = [life_header(w, life)]
    if letters:
        carried.append(letters_block(letters))
    carried += handover_evidence(carry, prev_adv, earlier, w, camp)
    return "\n\n".join(carried)


def life_debrief(adv_log, fnotes=(), work_notes=""):
    """modelrun.build_life_debrief（record+notes）的同一段材料，问题换成 B4。"""
    mode = modelrun.LIFE_DEBRIEF
    assert mode in modelrun.LIFE_DEBRIEFS, mode
    parts = [RECORD + "\n\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(adv_log, 1))]
    if mode == "record+notes" and fnotes:
        parts.append(NOTES + "\n" + modelrun._render_notes(fnotes))
    return "\n\n".join(parts + [(work_notes + "\n" if work_notes else "") + LIFE_QUESTION])   # 工作便签（营后笔记，on 时）


def carried(mode, notes, handover=""):
    """modelrun._carried 的 minimal 版（v2）：show 臂的笔记抬头 "Notes:"，笔记本身同 modelrun._render_notes（与 _carried 的写法逐字相同）。"""
    parts = [handover] if handover else []
    if mode == "show" and notes:
        parts.append(NOTES + "\n" + modelrun._render_notes(notes))
    return "\n\n".join(parts)


def note_fight(model, key, mode, notes, tag, name, slice_, verbose):
    """modelrun._note_fight 的 minimal 版（B5、B6；不另限字数）。"""
    if mode == "none":
        return
    body = (FIGHT_HEAD.format(name=name) + "\n\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(slice_, 1))
            + "\n\n" + FIGHT_QUESTION)
    with kind("note"):
        text = modelrun.call(model, NOTE_SYSTEM, body, key)
    notes.append(dict(tag=tag, enemy=name, kind="fight", text=text))
    if verbose:
        print(f"\n  --- {tag} fight note ---\n{text}\n", flush=True)


def capped_call(model, key, body):
    """命笔记、营地笔记和信先缩写三次，仍超 2000 则保留前缀；完整草稿留档。"""
    return capped_call_limit(model, key, body, LIMIT)


def life_notes(model, key, adv_log, fnotes, work_notes=""):
    """命末笔记（B4 + B6 + B12）；种类记 "debrief"（同默认文字下的命末结论）。"""
    with kind("debrief"):
        return capped_call(model, key, life_debrief(adv_log, fnotes, work_notes))


# ---------------------------------------------------------------- 世界序号（B2 的 w）
def world_index_from_letters(model, seed, letters_from):
    """这个参与者的第几个世界：没有信 = 1；有信 = 那封信记下的世界序号 + 1（信必须是 minimal 下写的）。"""
    if not letters_from:
        return 1
    if len(letters_from) > 1:
        raise SystemExit("Only the latest letter is carried to the next world (one run id in letters_from).")
    import json
    f = modelrun._letter_path(model, seed, letters_from[-1])
    if not f.exists():
        raise SystemExit(f"No letter for {letters_from[-1]} ({f.name}).")
    pt = json.loads(f.read_text()).get("participant_text") or {}
    if pt.get("text") != "minimal" or not isinstance(pt.get("world_index"), int):
        raise SystemExit(f"The letter of {letters_from[-1]} was not written under PROTO_TEXT=minimal; the world sequence is unknown.")
    return pt["world_index"] + 1


# ---------------------------------------------------------------- 世界末的信（4 条或 5 条命）
def write_letter(model, seed, run_id, carry, *, lives, key, letters_from=(), verbose=True, human=False):
    """modelrun.write_letter 的 minimal 版：同样的材料范围（这一世界每条命的完整记录和笔记、之前的信，不随 carry 变）、
    同样的上限与缩写 / 截断、同样的记录字段，外加 participant_text。lives = 这个世界的命数（v3b 下 4：boss 先不做）。"""
    import json, os as _os
    if carry == "layered" and modelrun._letter_path(model, seed, run_id).exists():   # 11-08 审查：原文固定留档——信已存在就拒绝覆盖（在任何调用之前）
        raise SystemExit(f"{modelrun._letter_path(model, seed, run_id).name} already exists; a letter is never overwritten.")
    if not human:                                   # 11-10：人类的信不经调用日志 / 回放（那一层会把人当模型记、还可能回放旧回复）
        import reasoning_capture
        reasoning_capture.install()
        reasoning_capture.bind(model, modelrun._letter_path(model, seed, run_id))
    u0 = modelrun._usage_snapshot()
    modelrun.CACHE_KEY = f"agii:{modelrun._slug(model)}:{run_id or modelrun.MAIN_RUN}"
    modelrun.BUDGET_KEY = _os.environ.get("AGII_BUDGET_KEY") or f"{modelrun._slug(model)}_{run_id or modelrun.MAIN_RUN}"
    cap = _os.environ.get("AGII_BUDGET_USD", "").strip()
    modelrun.BUDGET_USD = float(cap) if cap else None
    if not human:
        modelrun.effort_for(modelrun.provider_for(model))
    earlier = [(n, modelrun._load(model, seed, n, run_id=run_id)) for n in range(1, lives + 1)]
    missing = [n for n, d in earlier if not d or "adv_log" not in d]
    if missing:
        raise SystemExit(f"{run_id}: lives {missing} have no record yet.")
    pts = [(d.get("participant_text") or {}) for _n, d in earlier]
    if any(p.get("text") != "minimal" for p in pts) or len({p.get("world_index") for p in pts}) != 1:
        raise SystemExit(f"{run_id}: every life of the world must have been played under PROTO_TEXT=minimal with one world index.")
    w = pts[0]["world_index"]
    first = earlier[0][1]
    prev_adv = [(n, d.get("adv_log", []), d.get("result", "?")) for n, d in earlier]
    if carry == "layered":                          # 11-08 审查：写信沿用首条命锁定的入境信（省略 letters_from 也不丢）；给了不同来源就拒绝；再核内容指纹
        locked = list(first.get("letters_from") or [])
        if letters_from and list(letters_from) != locked:
            raise SystemExit(f"letters_from {list(letters_from)} differs from the letter this world was played with ({locked}).")
        letters_from = locked
    letters = modelrun.load_letters(model, seed, letters_from)
    if carry == "layered" and (modelrun._sha(letters_block(letters)) if letters else None) != first.get("letters_sha"):
        raise SystemExit("The letter carried into this world has changed since life 1 (content fingerprint differs).")
    import proto_camp                               # 营地（PROTO_CAMP=1）：信的材料里也有（同 modelrun.write_letter 的材料带营地）；没有营地 → None
    if carry == "layered":                          # 46 U5：信 + 营地笔记（第 1 个世界）+ 本世界全部命笔记；不展开战斗笔记、不读记录
        body = layered_letter_body(letters, w, first.get("notes", "") if w == 1 else "", [(n, d.get("adv_notes", "")) for n, d in earlier],
                                   (first.get("layered") or {}).get("mapping"))
    else:
        body = "\n\n".join(([letters_block(letters)] if letters else []) + handover_evidence("both", prev_adv, earlier, w, proto_camp.evidence(first))
                           + [LETTER_QUESTION])
    modelrun.TRACE.clear()
    with session(), kind("debrief"):
        text, c = capped_call(model, key, body)
    f = modelrun._letter_path(model, seed, run_id)
    payload = dict(engine=modelrun.ENGINE_VERSION, run_id=run_id, carry=carry, lives=lives, letter=text,
                   letter_tokens=c["tokens"], letter_limit=c["limit"], letter_versions=c["versions"], shortened=c["shortened"],
                   truncated=c["truncated"], trace_version=modelrun.TRACE_VERSION, trace=list(modelrun.TRACE),
                   world=first.get("world"), pack=first.get("pack"), letters_from=list(letters_from or ()),
                   material_sha=modelrun._sha(body), material_chars=len(body), usage=modelrun._usage_since(u0),
                   prompt_order=modelrun.PROMPT_ORDER, api=modelrun.api_settings(model), protocol=modelrun.PROTOCOL_VERSION,
                   harness_language=modelrun.HARNESS_LANGUAGE,
                   participant_text=dict(text="minimal", text_version=VERSION, world_index=w, letter_question=LETTER_QUESTION))
    if carry == "layered":                          # 下一个世界的对应表要知道这个世界的外衣
        payload["layered"] = dict(version=LAYERED_VERSION, surface=(first.get("proto") or {}).get("world") or "A", world_index=w)
    import durable_resume
    durable_resume.atomic_json(f, payload)
    if verbose:
        print(f"\n{'=' * 58}\nletter ({len(text)} chars):\n{text}\n{'=' * 58}", flush=True)
    return payload


# ---------------------------------------------------------------- 人类：笔记提示（humanrun.human_call 的 minimal 版）
HUMAN_FULL = [False]                                # proto_play._human_letter 写信时打开：human_call 印模型收到的整段
LETTER_HEADER = "World {w}, Letter"                 # 人类界面横幅（同 "World w, Life k" 的作用：图形界面在这里清空 Record 栏）


def human_call(model, system, user, key, blocks=None):
    """humanrun.human_call 的 minimal 版：战后笔记那一句对手（模型收到 "Opponent: X. Record of the fight:"，人在这里看到
    "Opponent: X."；原函数只认旧的 "You have just finished a fight against X."）。v2：不印 "[Write your notes]" 横幅（模型那边没有对应的
    文字），印模型收到的完整系统提示（NOTE_SYSTEM）；"One point per line" 去掉（模型没有这句），只留输入怎么结束（HUMAN_END）。
    输入照 humanrun 的绑定读（命令行脚本键盘、图形界面的桥）。"""
    question = user if HUMAN_FULL[0] else user.rsplit("\n\n", 1)[-1] if "\n\n" in user else user   # 信：整段材料（人没有别的地方看笔记）
    about = user.split(". ", 1)[0] + "." if user.startswith("Opponent: ") else ""
    print("\n" + "=" * 52 + "\n" + system + ("\n" + about if about else "") + "\n" + question)
    print(HUMAN_END)
    if humanrun.AUTO["on"]:
        print("> (auto) nothing"); return "auto: nothing learned"
    read = humanrun.__dict__.get("input", builtins.input)
    lines = []
    while True:
        try:
            s = read("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not s.strip():
            break
        lines.append(s)
    return "\n".join(lines)


# 人类：交接（11-05 夜，用户批准，18 §8.6 末行）。core/humanrun.human_act / human_pick 把交接印成 "[Carried over]\n" + carry（只有人看到这个
# 标签，模型的提示里没有）。minimal 下换 humanrun._show_once（human_act / human_pick 调用时按模块全局查它，图形界面的桥调的也是它）：
# 交接照原样印、不带标签；交接只是一个光抬头（"World w, Camp" / "World w, Life k"，后面什么也没带）就整块不印 —— 横幅已经印过这一行。
# 人看到的交接仍然逐字是模型收到的那一段（只少了标签），没有多出来的东西。
CARRY_LABEL = "[Carried over]\n"                    # core/humanrun.py 的原文（human_act / human_pick）
BARE_HEADER_RE = re.compile(r"World \d+, (Camp|Life \d+)")


def human_carry_shown(carry):
    """minimal 下人看到的交接（不带标签）；光抬头 → ""（不印）。核对脚本用它算期望。"""
    return "" if BARE_HEADER_RE.fullmatch(carry.strip()) else carry


def _show_once_factory(orig):
    def show_once(key, text):
        if isinstance(key, tuple) and key and key[0] == "carry" and text.startswith(CARRY_LABEL):
            if key in humanrun._shown:
                return
            body = human_carry_shown(text[len(CARRY_LABEL):])
            if not body:
                humanrun._shown.add(key)                # 光抬头：记为已印（同原函数的一次性），什么也不印
                return
            return orig(key, body)
        return orig(key, text)
    show_once.orig = orig
    return show_once


_HUMAN = [0]


@contextlib.contextmanager
def human_notes():
    """minimal 下把 humanrun.human_call 换成 human_call（最外一层换，嵌套的什么也不做：图形界面 worker 先换，桥再把它包起来）。
    11-05 夜（用户）：同时把 humanrun._show_once 换成不带 "[Carried over]" 标签的版本（_show_once_factory；光抬头不印）。默认文字下什么也不换。"""
    if not minimal() or _HUMAN[0]:
        _HUMAN[0] += 1
        try:
            yield
        finally:
            _HUMAN[0] -= 1
        return
    saved, saved_show = humanrun.human_call, humanrun._show_once
    humanrun.human_call, humanrun._show_once = human_call, _show_once_factory(saved_show)
    _HUMAN[0] += 1
    try:
        yield
    finally:
        _HUMAN[0] -= 1
        humanrun.human_call, humanrun._show_once = saved, saved_show


# ---------------------------------------------------------------- 分层记忆（carry="layered"；46 号文档；用户 11-08 定稿）
# 只追加、不修改的四层：营地笔记（只有参与者的第 1 个世界）→ 战斗笔记 → 命笔记 → 信。只在 PROTO_TEXT=minimal 的 boss 世界里用；
# 别的 carry、别的环境下这一段一个也不被读到。新的参与者文字只有一处：行动提示里本场记录的抬头 "This fight:"（两个词，不进 3 词清单）。
# 对应表（世界 2 起）：上个世界与这个世界的牌名、自身符号并排的 JSON，按固定的用途次序对齐（次序只用来对齐，不说作用）。
LAYERED_VERSION = "layered-memory-v2-note600-2026-11-10"
FIGHT_HISTORY = "This fight:"                       # 行动提示里本场到目前为止的记录的抬头（地图上原是 HISTORY "This life:"）
FIGHT_NOTE_LIMIT = 600                              # 用户 11-10：扩大预算，先告知；超长由模型重写，不切尾
MAX_NOTE_SHORTENINGS = 3                           # 2000 上限仍超长则切尾；600 上限仍超长照旧暂停
MAP_CARD_ORDER = ("attack", "block", "dodge", "heal", "buff_mark")
MAP_YOU_ORDER = ("me.hp", "me.cap", "me.atk", "me.energy", "me.block", "me.dodge", "me.offence", "me.double")   # 原型屏幕上出现的自身符号
modelrun._assert_english("proto_text", FIGHT_HISTORY)


def correspondence(prev_surface, surface, w):
    """世界 w（>= 2）的对应表：{"World w-1": {"cards": [...], "you": [...]}, "World w": {...}}，按 MAP_*_ORDER 对齐。"""
    import json as _json, proto_worlds as _pws, antagonist_proto as _ap
    order = tuple(k for k in MAP_CARD_ORDER if k != "heal") if _ap.HEAL == "off" else MAP_CARD_ORDER   # 修订 6（43 §19）：没有治疗就不列它
    def side(name):
        f = _pws.surface(name)["facts"]
        kinds = {k: n for n, k in f["cards"].items()}
        hidden = {f"{side_}.{prop}" for side_, prop in _ap.HIDES[_ap.HIDE]}           # 画面减项（PROTO_HIDE）：不上画面的格子不列
        return dict(cards=[kinds[k] for k in order], you=[f["labels"][k] for k in MAP_YOU_ORDER if k not in hidden])
    return _json.dumps({f"World {w - 1}": side(prev_surface), f"World {w}": side(surface)}, ensure_ascii=True)


def layered_memory(w, life, letters, camp_notes, life_notes, mapping):
    """行动和写战斗笔记共用的旧记忆（不含当前命的战斗笔记）：抬头 "World w, Life k"、信（B8）、营地笔记（只有第 1 个世界）、
    本世界此前每条命的命笔记（B10 标签）、对应表（世界 2 起）。"""
    parts = [life_header(w, life)]
    if letters:
        parts.append(letters_block(letters))
    if camp_notes:
        parts.append(CAMP_LABEL.format(w=w) + "\n" + camp_notes)
    for n, text in life_notes:
        if text:
            parts.append(life_label(w, n) + "\n" + text)
    if mapping:
        parts.append(mapping)
    return "\n\n".join(parts)


class LayeredCarry(str):
    """分层记忆的记忆块（文字同普通 str）；.blocks = [(旧记忆, 断点?), ("\n\n" + 第 i 条战斗笔记, 断点?) …]，只有最后一块打断点。
    拼起来 == 本身（缓存切块，11-09）。"""
    blocks = ()


def layered_carry(memory, fnotes):
    """行动提示的记忆块：旧记忆 + 当前命此前各场的战斗笔记（modelrun._render_notes 的样子；没有就不加）。"""
    parts = [memory] + ["\n\n" + modelrun._render_notes([n]) for n in fnotes]   # _render_notes 用 "\n\n" 连各条，逐条渲染再拼回同一段文字
    text = "".join(parts)
    assert text == memory + ("\n\n" + modelrun._render_notes(fnotes) if fnotes else ""), "layered carry blocks do not rebuild the text"
    c = LayeredCarry(text)
    c.blocks = [(t, i == len(parts) - 1) for i, t in enumerate(parts)]
    return c


def capped_call_limit(model, key, body, limit, blocks=None):
    """有界缩写；三次后仍超限，按对应上限保留前缀。"""
    text = modelrun.call(model, NOTE_SYSTEM, body, key, blocks=blocks)
    versions = [text]
    n = modelrun.letter_tokens(text)
    for _ in range(MAX_NOTE_SHORTENINGS):
        if n <= limit:
            break
        extra = "\n\n" + PREVIOUS_NOTE + "\n" + text + "\n\n" + SHORTEN.format(n=n, limit=limit)
        text = modelrun.call(model, NOTE_SYSTEM, body + extra, key, blocks=(list(blocks) + [(extra, False)]) if blocks else None)
        versions.append(text)
        n = modelrun.letter_tokens(text)
    truncated = n > limit
    before_cut = n
    if truncated:
        original = text
        text = modelrun.letter_truncate(original, limit)
        n = modelrun.letter_tokens(text)
        # A token boundary can split a Unicode character. Keep a valid prefix
        # of the original text, never a replacement character or >limit tokens.
        while text and (not original.startswith(text) or n > limit):
            text = text[:-1]
            n = modelrun.letter_tokens(text)
    cap = dict(tokens=n, limit=limit, versions=versions, shortened=len(versions) > 1, truncated=truncated)
    if truncated:
        cap.update(tokens_before_truncation=before_cut, truncation_policy="prefix_after_three_shortenings")
    return text, cap


def _numbered(lines):
    return "\n".join(f"  {i}. {h}" for i, h in enumerate(lines, 1))


def layered_fight_note(model, key, memory, fnotes, tag, name, fight_log, verbose, work_notes=""):
    """战斗笔记：旧记忆、本命此前笔记、本场完整记录；写前告知 600 token 上限。"""
    carry = layered_carry(memory, fnotes)
    rest = ("\n\n" + FIGHT_HEAD.format(name=name) + "\n\n" + _numbered(fight_log)
            + "\n\n" + (work_notes + "\n" if work_notes else "") + f"At most {FIGHT_NOTE_LIMIT} tokens. " + FIGHT_QUESTION)   # 工作便签（on 时）单换行接问题，人看到的那一段里也有
    body = carry + rest
    with kind("note"):                                  # 11-09：同记忆块切法（上一场的战斗笔记请求写下的前缀，这一场读回）
        text, cap = capped_call_limit(model, key, body, FIGHT_NOTE_LIMIT, blocks=list(carry.blocks) + [(rest, False)])
    fnotes.append(dict(tag=tag, enemy=name, kind="fight", text=text, cap=cap))
    if verbose:
        print(f"\n  --- {tag} fight note ---\n{text}\n", flush=True)
    return body


def layered_life_note(model, key, fnotes, mapping=None):
    """地图命的命笔记（U4）：只读这条命的全部战斗笔记 + 对应表（世界 2 起；46 §4「每次写笔记都带」，11-08 审查）+ B4。"""
    body = (mapping + "\n\n" if mapping else "") + NOTES + "\n" + modelrun._render_notes(fnotes) + "\n\n" + LIFE_QUESTION
    with kind("debrief"):
        text, cap = capped_call(model, key, body)
    return text, cap, body


def layered_boss_note(model, key, memory, name, fight_log, work_notes=""):
    """boss 那条命只写命笔记（用户 11-08）：读战斗笔记的那一套（旧记忆 + boss 的完整记录）+ B4。"""
    body = memory + "\n\n" + FIGHT_HEAD.format(name=name) + "\n\n" + _numbered(fight_log) + "\n\n" + (work_notes + "\n" if work_notes else "") + LIFE_QUESTION
    with kind("debrief"):
        text, cap = capped_call(model, key, body)
    return text, cap, body


def layered_letter_body(letters, w, camp_notes, life_notes, mapping=None):
    """世界末的信（U5）：带进来的信 + 本世界营地笔记（只有第 1 个世界）+ 本世界全部命笔记 + 对应表（世界 2 起；11-08 审查）+ B7。
    不展开战斗笔记、不读记录。"""
    parts = []
    if letters:
        parts.append(letters_block(letters))
    if camp_notes:
        parts.append(CAMP_LABEL.format(w=w) + "\n" + camp_notes)
    for n, text in life_notes:
        if text:
            parts.append(life_label(w, n) + "\n" + text)
    if mapping:
        parts.append(mapping)
    return "\n\n".join(parts + [LETTER_QUESTION])
