"""Record -> per-turn facts shown to the player (SCORING R.2-R.4, TRACE §4).

Pure text parsing: no engine, no referee fields. Line indexes are 1-based positions in `adv_log`
(the convention of TRACE.md). Both the Chinese and the English harness forms are accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

OBS = "[observation]"
FORCED_LINES = ("(三次无效，回合自动结束)", "(three invalid actions: the turn ends)")
LOCKED_HEADS = ("(锁定的攻击结算)", "(locked attack resolves)")
BOSS_SHIFT_TEXT = "The enemy's form has changed."
# The cue of a boss-world boss life (scripts/antagonist_boss.CUE_TEXT; docs/antagonist_boss/40_boss_entry.md, 2026-11-07): the same
# event, the participant text of the prototype entry. Accepted as a boss-shift line too (no record that parsed before contains it:
# such a line was an unknown line).
BOSS_WORLD_CUE = "The enemy has changed."
WITHHELD = "<consequence withheld>"          # an END whose change list was cut off for the judge (F2)
TURN_HEADS = ("回合 ", "Turn ")
ME_HEADS = ("我:", "You:")
THEM_HEADS = ("对方:", "Them:")

RE_FIGHT_BEGIN = re.compile(r"^\[layer (\d+)\] fight begins$")
RE_BOSS_BEGIN = re.compile(r"^\[boss (\d+)\] begins$")
RE_FIGHT_END = re.compile(r"^\[(layer|boss) (\d+)\] fight ended$")
RE_DODGE_LOSS = re.compile(r"^\((\d+) consecutive dodge turns: fight lost\)$")
RE_REPEAT_CARD_LOSS = re.compile(r"^\((\d+) consecutive turns playing (\S+): fight lost\)$")
ROUND_LIMIT_LOSS = "(exceed round limit: fight lost)"
WARD_LIMIT_LOSS = "(fight lost)"   # PROTO_WARDLIMIT (2026-11-12, v8): the seal time limit; no reason is given
RE_REST = re.compile(r"^\[layer (\d+)\] rested -> (.*)$")
# Registration 12 (TUNING["auto_rest"]): the environment's automatic resupply at a rest layer. Not the player's action,
# so it is never a rest item (Life.rests); it is kept in Life.resupplies and its change list feeds the running values.
RE_RESUPPLY = re.compile(r"^\[layer (\d+)\] automatic resupply -> (.*)$")
RE_TOOK = re.compile(r"^\[layer (\d+)\] won, took (.+)$")
RE_CHOSE = re.compile(r"^\[layer (\d+)\] won, chose (\S+) \+\?(?: -> (.*))?$")
RE_ACTION = re.compile(r"^(\S+)  ->  (.*)$")
RE_CHANGE = re.compile(r"^([A-Za-z]\d+): (-?\d+)->(-?\d+)$")
RE_HAND = re.compile(r"^(\S+)\((\d+|\?)\)$")


class ParseError(Exception):
    pass


def parse_changes(text: str):
    """'a1: 2->1, b1: 42->35' -> [(label, old, new), ...]; '(nothing changed)' -> []; withheld -> None."""
    if text == WITHHELD:
        return None
    if text == "(nothing changed)":
        return []
    out = []
    for part in text.split(", "):
        m = RE_CHANGE.match(part.strip())
        if not m:
            raise ParseError(f"cannot parse change {part!r}")
        out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return out


@dataclass
class Screen:
    turn: int
    me: dict                 # label -> int or None ('?')
    me_flags: dict           # transient: label -> int or True (bare flag)
    them: dict
    them_flags: dict
    hand: list               # [(name, cost or None)]


def parse_screen(text: str) -> Screen:
    lines = text.split("\n")
    if lines[0] != OBS:
        raise ParseError("observation does not start with [observation]")
    head = lines[1]
    turn = None
    for h in TURN_HEADS:
        if head.startswith(h):
            turn = int(head[len(h):].split()[0])
    if turn is None:
        raise ParseError(f"no turn header in {head!r}")
    me, me_flags, them, them_flags, hand = {}, {}, {}, {}, None
    side = None
    for line in lines[2:]:
        if line.startswith("In hand:"):
            hand = []
            for tok in line[len("In hand:"):].split():
                m = RE_HAND.match(tok)
                if not m:
                    raise ParseError(f"cannot parse hand token {tok!r}")
                hand.append((m.group(1), None if m.group(2) == "?" else int(m.group(2))))
            continue
        head_me = next((h for h in ME_HEADS if line.startswith(h)), None)
        head_them = next((h for h in THEM_HEADS if line.startswith(h)), None)
        if head_me or head_them:
            side = "me" if head_me else "them"
            body = line[len(head_me or head_them):]
            target = me if side == "me" else them
            for tok in body.split():
                lab, _, val = tok.partition("=")
                target[lab] = None if val == "?" else int(val)
            continue
        if line.startswith(" ") and side:
            target = me_flags if side == "me" else them_flags
            for tok in line.split():
                if ":" in tok:
                    lab, _, val = tok.partition(":")
                    target[lab] = None if val == "?" else int(val)
                else:
                    target[tok] = True
            continue
        raise ParseError(f"unexpected screen line {line!r}")
    if hand is None:
        raise ParseError("observation without a hand line")
    return Screen(turn, me, me_flags, them, them_flags, hand)


@dataclass
class Entry:
    idx: int                 # 1-based line number in adv_log
    raw: str
    kind: str                # obs, card, refused, unparseable, end, forced, locked, boss_shift, fight_begin,
    #                          fight_end, rest, resupply, took, chose
    name: str = ""           # card name (card / refused)
    changes: list = None     # [(label, old, new)] or None (withheld)
    where: tuple = None      # ('layer', i) or ('boss', k) for fight markers, rests, rewards
    screen: Screen = None
    extra: dict = field(default_factory=dict)

    def delta(self, label):
        """(old, new) for a label in this entry's change list, else None."""
        for lab, old, new in self.changes or ():
            if lab == label:
                return old, new
        return None


def classify(idx: int, line: str) -> Entry:
    if line.startswith(OBS):
        return Entry(idx, line, "obs", screen=parse_screen(line))
    if line == "[unparseable]":
        return Entry(idx, line, "unparseable")
    if RE_DODGE_LOSS.fullmatch(line) or RE_REPEAT_CARD_LOSS.fullmatch(line) or line in (ROUND_LIMIT_LOSS, WARD_LIMIT_LOSS):
        return Entry(idx, line, "fight_feedback")
    if line in FORCED_LINES:
        return Entry(idx, line, "forced")
    for head in FORCED_LINES:                       # 2026-11-10：自动结算也写出变化 "(three invalid …)  ->  …"
        if line.startswith(head + "  ->  "):
            return Entry(idx, line, "forced", changes=parse_changes(line[len(head) + 6:]))
    if line == BOSS_SHIFT_TEXT or line == BOSS_WORLD_CUE:
        return Entry(idx, line, "boss_shift")
    m = RE_FIGHT_BEGIN.match(line)
    if m:
        return Entry(idx, line, "fight_begin", where=("layer", int(m.group(1))))
    m = RE_BOSS_BEGIN.match(line)
    if m:
        return Entry(idx, line, "fight_begin", where=("boss", int(m.group(1))))
    m = RE_FIGHT_END.match(line)
    if m:
        return Entry(idx, line, "fight_end", where=(m.group(1), int(m.group(2))))
    m = RE_REST.match(line)
    if m:
        return Entry(idx, line, "rest", where=("layer", int(m.group(1))), changes=parse_changes(m.group(2)))
    m = RE_RESUPPLY.match(line)
    if m:
        return Entry(idx, line, "resupply", where=("layer", int(m.group(1))), changes=parse_changes(m.group(2)))
    m = RE_TOOK.match(line)
    if m:
        return Entry(idx, line, "took", where=("layer", int(m.group(1))), name=m.group(2))
    m = RE_CHOSE.match(line)
    if m:
        return Entry(idx, line, "chose", where=("layer", int(m.group(1))), name=m.group(2),
                     changes=parse_changes(m.group(3)) if m.group(3) else [])
    for head in LOCKED_HEADS:
        if line.startswith(head + "  ->  "):
            return Entry(idx, line, "locked", changes=parse_changes(line[len(head) + 6:]))
    if line.startswith("end turn  ->  "):
        return Entry(idx, line, "end", changes=parse_changes(line[len("end turn  ->  "):]))
    m = RE_ACTION.match(line)
    if m:
        name, tail = m.group(1), m.group(2)
        if tail in ("(no effect)", "(not in hand)"):
            return Entry(idx, line, "refused", name=name, extra={"why": tail})
        return Entry(idx, line, "card", name=name, changes=parse_changes(tail))
    raise ParseError(f"line {idx}: unknown line {line[:80]!r}")


@dataclass
class Turn:
    number: int
    dps: list = field(default_factory=list)          # observation entries, in order
    actions: list = field(default_factory=list)      # (dp position in this turn, entry)
    end: Entry = None                                 # 'end turn' line
    forced: Entry = None
    locked: Entry = None
    closing: str = "open"   # end / forced / kill / death / open

    @property
    def first_dp(self) -> Entry:
        return self.dps[0]

    @property
    def end_resolved(self) -> bool:
        """SCORING R.9: closed with an END line or a forced END."""
        return self.closing in ("end", "forced")

    def plays(self):
        """Played cards (non-empty change list, R.6), as (dp position, entry)."""
        return [(p, e) for p, e in self.actions if e.kind == "card" and e.changes]

    def last_line(self) -> int:
        idx = [e.idx for _, e in self.actions]
        for e in (self.end, self.forced, self.locked):
            if e is not None:
                idx.append(e.idx)
        idx += [d.idx for d in self.dps]
        return max(idx)

    def decision_end_line(self) -> int:
        """Last line of the player's decision in this turn (the closing action; locked attack excluded)."""
        idx = [e.idx for _, e in self.actions] + [d.idx for d in self.dps]
        for e in (self.end, self.forced):
            if e is not None:
                idx.append(e.idx)
        return max(idx)


@dataclass
class Fight:
    ordinal: int
    where: tuple
    begin: int
    end: int = None
    turns: dict = field(default_factory=dict)       # turn number -> Turn (insertion order = play order)
    entries: list = field(default_factory=list)


@dataclass
class Rest:
    where: tuple
    entry: Entry
    fights_before: int


@dataclass
class Life:
    entries: list
    fights: list
    rests: list
    rewards: list
    lang: str
    truncated: bool
    errors: list
    resupplies: list = field(default_factory=list)     # registration 12: automatic resupply entries (never items)


def parse_life(adv_log: list, labels: dict) -> Life:
    """Group the log into fights, turns and decision points (R.4)."""
    entries = [classify(i, line) for i, line in enumerate(adv_log, 1)]
    lang = "en" if any(e.raw.startswith(FORCED_LINES[1]) or (e.kind == "obs" and "\nTurn " in e.raw)
                       for e in entries) else "zh"
    fights, rests, rewards, errors = [], [], [], []
    resupplies = []
    cur = None
    turn = None
    lab_b1, lab_a3 = labels["them_hp"], labels["me_hp"]
    for e in entries:
        if e.kind == "fight_begin":
            if cur is not None and cur.end is None:
                errors.append(f"line {e.idx}: fight begins inside an open fight")
            cur = Fight(len(fights) + 1, e.where, e.idx)
            fights.append(cur)
            turn = None
            continue
        if e.kind == "fight_end":
            if cur is None or (cur.where[0], cur.where[1]) != e.where:
                errors.append(f"line {e.idx}: fight end does not match the open fight")
            if cur is not None:
                cur.end = e.idx
            cur = None
            turn = None
            continue
        if e.kind == "rest":
            rests.append(Rest(e.where, e, len(fights)))
            continue
        if e.kind == "resupply":
            resupplies.append(Rest(e.where, e, len(fights)))
            continue
        if e.kind in ("took", "chose"):
            rewards.append(e)
            continue
        if cur is None:
            errors.append(f"line {e.idx}: {e.kind} outside a fight")
            continue
        cur.entries.append(e)
        if e.kind == "obs":
            t = e.screen.turn
            if turn is None or turn.number != t:
                if t in cur.turns:
                    errors.append(f"line {e.idx}: turn {t} reopened")
                turn = cur.turns.setdefault(t, Turn(t))
            turn.dps.append(e)
            continue
        if turn is None:
            if e.kind == "locked":
                errors.append(f"line {e.idx}: locked attack before any turn")
            continue
        pos = len(turn.dps) - 1
        if e.kind in ("card", "refused", "unparseable"):
            turn.actions.append((pos, e))
            if e.kind == "card" and e.changes:
                b1 = e.delta(lab_b1)
                a3 = e.delta(lab_a3)
                if b1 and b1[1] <= 0:
                    turn.closing = "kill"
                elif a3 and a3[1] <= 0:
                    turn.closing = "death"
        elif e.kind == "end":
            turn.actions.append((pos, e))
            turn.end = e
            turn.closing = "end"
        elif e.kind == "forced":
            turn.forced = e
            turn.closing = "forced"
        elif e.kind == "locked":
            turn.locked = e
        elif e.kind == "boss_shift":
            pass
    truncated = cur is not None
    return Life(entries, fights, rests, rewards, lang, truncated, errors, resupplies)


# ---------------------------------------------------------------- running values (R.8)

def running_values(life: Life, labels: dict, c0: int):
    """Running H, C, P before every entry, with the forced-END exception of SCORING R.8.

    Returns (before: dict idx -> (H, C, P), mismatches: list of (idx, label, expected, logged)).
    """
    lab = {"H": labels["me_hp"], "C": labels["me_cap"], "P": labels["me_poison"]}
    val = {"H": c0, "C": c0, "P": 0}
    pending = set()          # labels whose next `old` is taken as the new running value (after a forced END)
    before, mism = {}, []
    for e in life.entries:
        before[e.idx] = (val["H"], val["C"], val["P"])
        if e.kind == "forced":
            pending = {"H", "C", "P"}
            continue
        if e.kind == "fight_begin":
            continue
        for key, label in lab.items():
            d = e.delta(label) if e.changes else None
            if d is None:
                continue
            old, new = d
            if key in pending:
                pending.discard(key)
            elif old != val[key]:
                mism.append((e.idx, label, val[key], old))
            val[key] = new
        if e.kind == "fight_end":
            continue
    return before, mism
