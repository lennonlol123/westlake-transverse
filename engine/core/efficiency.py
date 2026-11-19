"""Skill-acquisition efficiency: how much it cost to learn, not how strong it got.

The clear rate answers "did it end up knowing enough". It cannot answer the
question the benchmark is actually about, which is how expensively that
knowledge was bought. Three things together do:

    lives      how many attempts before it stopped dying
    steps      how much interaction those attempts cost -- a 13-step death that
               produced the decisive correction is cheap; a 75-step death that
               produced nothing is not, and counting lives alone rates them the
               same
    mistakes   whether the wrong move stopped being played
    experiments how quickly the training cards were successfully activated
    resources  zero-effect use of exhaustible cards
    planning   only immediately dominated lethal choices, not ordinary tempo

The third is the one that makes the other two mean anything. A run can clear by
luck and a run can die having learned everything; only the mistake trace says
which. Every mistake is paired with an OPPORTUNITY count. Zero mistakes in zero
opportunities means "not tested", not "understood". Both are recorded from the
ENGINE's side at the moment the move is made rather than reconstructed from the
log afterwards -- what counts depends on the enemy's hidden behaviour.

A mistake here is never "played a suboptimal card". It is specifically: took the
action this environment was built to punish after the relevant evidence was
available, against the enemy that punishes it. Necessary experiments and turns
where the response was not executable are recorded separately.

    pierce   repeated a shield after its first diagnostic hit
    charge   had a playable dodge on a full wind-up but ended undodged
    armour   repeated a zero hit after armour evidence existed
    poison   spent a rest on health while carrying stacks
"""
from __future__ import annotations

import json
import pathlib
import statistics

from adventure import ENGINE_VERSION, TUNING

MECHANICS = ("pierce", "charge", "armour", "poison")
OBSERVATION_PREFIX = "[observation]"


def is_observation(entry) -> bool:
    """Neutral public state saved for later recall, never a paid action."""
    return str(entry).startswith(OBSERVATION_PREFIX)


def participant_steps(log) -> int:
    return sum(not is_observation(x) for x in log)


def charge_window(f) -> bool:
    return ("charge" in f.parts
            and f.state[("them", "charge")] >= f.enemy.charge_max)


def dodge_available(f) -> bool:
    """The response is already active or can still be executed right now."""
    if f.state[("me", "dodge")]:
        return True
    return any(card.kind == "dodge" and f.can_play(name)
               for name, card in f.deck.items())


def momentum_window(f) -> bool:
    """The ramp is at the step where a shield is the answer.

    `MOMENTUM_FULL_AT - 1` and not a threshold of its own: it is the line
    `solver.act` blocks on, so the reference policy and the scorer cannot
    disagree about when a shield was called for.
    """
    from adventure import MOMENTUM_FULL_AT
    return ("momentum" in f.parts
            and getattr(f, "momentum", 0) >= MOMENTUM_FULL_AT - 1)


def block_available(f) -> bool:
    by_kind = {c.kind: n for n, c in f.deck.items()}
    return (f.state[("me", "block")] > 0
            or ("block" in by_kind and f.can_play(by_kind["block"])))


def heal_available(f) -> bool:
    return any(card.kind == "heal" and f.can_play(name)
               for name, card in f.deck.items())


def buff_available(f) -> bool:
    return any(card.kind == "buff_mark" and f.can_play(name)
               for name, card in f.deck.items())


def offence_available(f) -> bool:
    return any(card.kind in ("attack", "buff_mark") and f.can_play(name)
               for name, card in f.deck.items())


def second_offence_available(f) -> bool:
    """已经进攻过一次，手里还有一张打得出的进攻牌 —— 反击的题就在这一刻。"""
    return getattr(f, "offences", 0) >= 1 and any(
        card.kind in ("attack", "buff_mark") and f.can_play(name)
        for name, card in f.deck.items())


def nonattack_available(f) -> bool:
    """A non-attack card is payable right now.

    What makes "do not play one" a decision rather than a description of the
    hand. Like `dodge_available`, this is the DEGRADED fallback: asked at the
    end of a turn it is asked of a spent energy bar. A caller that recorded the
    answer at decision time must pass it in.
    """
    return any(card.kind != "attack" and f.can_play(name)
               for name, card in f.deck.items())


def _mimic_probe_spent(f) -> bool:
    return _probe_spent(f, 6)


def _probe_spent(f, idx) -> bool:
    p = getattr(f, "punished", ())
    return len(p) > idx and p[idx] >= 1


def turn_mistakes(f, charge_executable: bool | None = None,
                  momentum_executable: bool | None = None,
                  enrage_played: bool | None = None,
                  heal_executable: bool | None = None,
                  heal_played: bool | None = None,
                  ward_block_executable: bool | None = None) -> list[str]:
    """What this turn got wrong, judged the instant before the turn resolves.

    `ward_block_executable`: 决策时刻盾可不可出。破势的错是「没有不攻击且举盾」，判它要用决策时刻的
    可执行性：出了两刀之后能量是 0，回合末再看 block_available 永远是假，把「封着还猛攻」记成对
    （v1-1 命 2 的考试轮破势：10 次机会只记了 1 次错）。分母那边 turn_opportunities 早就用了它。"""
    out, s, parts = [], f.state, f.parts
    down = s.get(("them", "hp"), 1) <= 0      # 同 `turn_opportunities`：怪死了，回合末的罚不落下
    # 流血的题不挂在怪身上，挂在**你身上的层数**上：层数跨战斗保留，所以打完
    # 那只怪题还在。分母同样只算「手里真有治疗可打」的回合。
    h_exec = heal_available(f) if heal_executable is None else heal_executable
    if (s.get(("me", "wound"), 0) >= TUNING["wound_heal_stacks"] and h_exec
            and not heal_played):
        out.append("wound")
    # 反击：第一下是探针（和 pierce 的 fed==0 一样），之后再在一回合里进攻两次
    # 才是错。分母见 `turn_opportunities`。
    if ("counter" in parts and getattr(f, "countered", 0) >= 1
            and getattr(f, "offences", 0) >= 2 and not down):
        out.append("counter")
    # 守势：守相时进攻了（本局已被反弹过一次之后）。`punished[4]` 含这一回合的
    # 反弹，所以「之前已经有过」要减掉这回合的。
    if "guard" in parts and s.get(("them", "guard"), 0) >= 1:
        p = getattr(f, "punished", [0] * 6)
        before = p[4] - (1 if getattr(f, "offences", 0) >= 1 and p[4] else 0)
        if before >= 1 and getattr(f, "offences", 0) >= 1:
            out.append("guard")
    # 标记：探针之后，又出了被标记的那种牌
    mk = f.marked_kind() if hasattr(f, "marked_kind") else None
    if "mark" in parts and mk:
        p = getattr(f, "punished", [0] * 6)
        before = p[5] - getattr(f, "mark_hits_turn", 0)
        if before >= 1 and getattr(f, "played_kinds", {}).get(mk, 0) >= 1:
            out.append("mark")
    # fed==0 is the first causal probe against an otherwise unmarked enemy.
    # Only doing it again after that evidence is a correction failure.
    if "pierce" in parts and f.fed > 0 and s[("me", "block")] > 0 and not down:
        out.append("pierce")
    # 破势：封着、探针（打空一次）之后、盾可出 —— 这回合没有「不攻击且举盾」就是错。
    if "ward" in parts and s.get(("them", "ward"), 0) > 0 and _probe_spent(f, 7):
        be = block_available(f) if ward_block_executable is None else ward_block_executable
        if ((be or getattr(f, "played_kinds", {}).get("block", 0) >= 1)
                and (getattr(f, "played_kinds", {}).get("attack", 0) >= 1
                     or getattr(f, "played_kinds", {}).get("block", 0) == 0)):
            out.append("ward")
    # 模仿：探针之后又增伤了、它还活着、你没在闪 —— 那一击会落下。增伤后打死了它不算错。
    if ("mimic" in parts and _mimic_probe_spent(f)
            and getattr(f, "played_kinds", {}).get("buff_mark", 0) >= 1
            and s[("them", "hp")] > 0 and not s[("me", "dodge")]):
        out.append("mimic")
    executable = dodge_available(f) if charge_executable is None else charge_executable
    if (charge_window(f) and executable and not s[("me", "dodge")]):
        out.append("charge")
    # momentum lived only in `modelrun`'s own counters, so the shared
    # opportunity/mistake tables read zero for a life that was asked three
    # times and answered none -- the same mechanic-missing-from-one-path defect
    # that left the vector engine fighting a plain monster.
    m_exec = (block_available(f) if momentum_executable is None
              else momentum_executable)
    if momentum_window(f) and m_exec and s[("me", "block")] <= 0 and not down:
        out.append("momentum")
    # enrage sits on pierce's rungs with the sign flipped: `enraged` counts the
    # non-attacks the enemy has already been shown, so `enraged > 0` is the
    # evidence and playing another one is the repeat. Whether one was played
    # THIS turn is not readable from the end-of-turn state, so the caller says.
    # The CAP belongs in both counters. `act` stops refusing at `enrage_cap`
    # on purpose -- above it nothing grows, so restraint is pure self-harm --
    # but this counter had no cap, so it scored the reference policy's correct
    # play as a mistake. Measured on a pure enrager, the informed line read an
    # 82% "error" rate against an ignorant line's 89%: the instrument could not
    # tell knowing from not knowing, which is the one thing it exists to do.
    if ("enrage" in parts and 0 < f.enraged < TUNING["enrage_cap"]
            and enrage_played):
        out.append("enrage")
    return out


def turn_opportunities(f, charge_executable: bool | None = None,
                       momentum_executable: bool | None = None,
                       enrage_offer: bool | None = None,
                       heal_executable: bool | None = None,
                       second_offence_executable: bool | None = None,
                       offence_executable: bool | None = None,
                       marked_executable: bool | None = None,
                       buff_executable: bool | None = None,
                       ward_block_executable: bool | None = None) -> list[str]:
    """Mechanisms on which ending this turn constitutes a scored decision."""
    out, s, parts = [], f.state, f.parts
    # 怪已经死在这回合：回合末的结算不会发生 —— 反击那一下、穿透那一下、斜坡、流血的 tick 都不落下。
    # 这些机制这回合没有题（第二刀打死了它不是「双进攻」的错，举着盾打死了它也不是「举盾」的错）。
    # 蓄力例外：满格时的挥击是锁定的（charge_commits），怪死了那一下照落，题照算。
    down = s.get(("them", "hp"), 1) <= 0
    h_exec = heal_available(f) if heal_executable is None else heal_executable
    if s.get(("me", "wound"), 0) >= TUNING["wound_heal_stacks"] and h_exec:
        out.append("wound")
    # 分母：已经挨过一次反击，而且这回合曾有机会进攻第二次。调用方最好在决策
    # 时刻传 `second_offence_executable`；回合末的默认值读的是花光了的能量条。
    # 只在真的是反击怪时才去算「第二次进攻可执行」：测试里的假战斗对象没有这些
    # 字段，无条件地算会在别的机制的测试里炸。
    if "counter" in parts and getattr(f, "countered", 0) >= 1 and not down:
        so = (second_offence_available(f) if second_offence_executable is None
              else second_offence_executable)
        if so or getattr(f, "offences", 0) >= 2:
            out.append("counter")
    if "guard" in parts and s.get(("them", "guard"), 0) >= 1:
        p = getattr(f, "punished", [0] * 6)
        offended = getattr(f, "offences", 0) >= 1
        before = p[4] - (1 if offended and p[4] else 0)
        oe = (offence_available(f) if offence_executable is None else offence_executable)
        if before >= 1 and (oe or offended):
            out.append("guard")
    mk = f.marked_kind() if hasattr(f, "marked_kind") else None
    if "mark" in parts and mk:
        p = getattr(f, "punished", [0] * 6)
        before = p[5] - getattr(f, "mark_hits_turn", 0)
        me = (marked_executable if marked_executable is not None
              else any(c.kind == mk and f.can_play(n) for n, c in f.deck.items()))
        if before >= 1 and (me or getattr(f, "played_kinds", {}).get(mk, 0) >= 1):
            out.append("mark")
    if "pierce" in parts and f.fed > 0 and not down:
        out.append("pierce")
    # 破势的分母：封着、探针之后、决策时刻盾可出（或真的出了）。
    if "ward" in parts and s.get(("them", "ward"), 0) > 0 and _probe_spent(f, 7):
        be = block_available(f) if ward_block_executable is None else ward_block_executable
        if be or getattr(f, "played_kinds", {}).get("block", 0) >= 1:
            out.append("ward")
    # 模仿的分母：探针之后、决策时刻增伤可出（或真的出了）、回合末它还活着。
    # 打死了它的回合没有题 —— 增伤后抢杀正是答案之一。
    if "mimic" in parts and _mimic_probe_spent(f) and s[("them", "hp")] > 0:
        be = buff_available(f) if buff_executable is None else buff_executable
        if be or getattr(f, "played_kinds", {}).get("buff_mark", 0) >= 1:
            out.append("mimic")
    executable = dodge_available(f) if charge_executable is None else charge_executable
    if charge_window(f) and executable:
        out.append("charge")
    m_exec = (block_available(f) if momentum_executable is None
              else momentum_executable)
    if momentum_window(f) and m_exec and not down:
        out.append("momentum")
    # The denominator enrage did not have. Counting an opportunity only where a
    # repeat had already been counted made the rate 6/6 by construction: the
    # same numerator wearing two names, which no behaviour could have falsified.
    e_offer = (nonattack_available(f) if enrage_offer is None else enrage_offer)
    # Same cap as `turn_mistakes`, for the same reason it is stated there: a
    # turn on which restraint is not the right answer is not an opportunity to
    # get enrage right, and counting it in the denominator only would have
    # moved the rate the other way while hiding the same defect.
    if "enrage" in parts and 0 < f.enraged < TUNING["enrage_cap"] and e_offer:
        out.append("enrage")
    return out


def wasted_attack(f, before_hp: int) -> bool:
    """An attack that landed for nothing -- the armour was up and unbroken."""
    return ("armour" in f.parts and not f.broke
            and s_eq(f, before_hp))


def s_eq(f, before_hp: int) -> bool:
    return f.state[("them", "hp")] == before_hp


# Below this share of the ceiling the rest is not scored at all. The measured
# buckets pooled "low health" as everything under half, which hides the case a
# player has no next fight left to spend a ceiling on -- and the project's rule
# is that healing at low health must not be marked wrong by default. Where the
# measurement does not resolve it, neither counter fires.
REST_FLOOR = 0.25


def rest_mistake(run, mode: str, at: int = 4, floor: float = REST_FLOOR) -> bool:
    """Spending a rest on health while carrying a stack -- scored only where the
    measured counterfactual says it is wrong.

    Forcing the choice at one rest on the confirmed worlds and playing the
    remainder conditionally (6 worlds, 600 lives each):

        low stack,  low health     health 88.6%   ceiling 51.2%
        low stack,  safe health    health 82.3%   ceiling 73.6%
        high stack, low health     health 37.5%   ceiling 74.9%
        high stack, safe health    health 57.4%   ceiling 87.5%

    So the STACK decides it and the health level does not -- which is why the
    threshold is on `poison` -- but the pooled bottom bucket does not resolve
    the case where health is nearly gone, so that case is left unscored rather
    than scored either way.
    """
    if TUNING["auto_rest"]:          # registration 12: the automatic resupply is an environment event, never an item
        return False
    return (mode == "hp" and run.poison >= at
            and run.hp >= run.max_hp * floor)


def rest_opportunity(run, at: int = 4, floor: float = REST_FLOOR) -> bool:
    """A poison decision is testable only once enough stacks make it nontrivial.

    The SAME guard as `rest_mistake`, deliberately. A mistake counted on a rest
    that the opportunity counter refuses to count is a rate whose numerator and
    denominator are different questions -- the defect that made a charge
    mistake rate read over 100%.
    """
    if TUNING["auto_rest"]:          # registration 12: no rest choice, so no poison opportunity at a rest
        return False
    return run.poison >= at and run.hp >= run.max_hp * floor


# ---------------------------------------------------- resource / survival signals

def full_heal_window(f, heal_name: str) -> bool:
    """A turn in which an exhaustible heal is payable but health is already full."""
    return (f.state[("me", "hp")] >= f.max_hp and f.can_play(heal_name))


def attack_would_kill(f, attack_name: str) -> bool:
    """Exact immediate result of the basic attack from the current public state."""
    if not f.can_play(attack_name):
        return False
    s, card = f.state, f.deck[attack_name]
    damage = (s[("me", "atk")] + card.amount) * (
        2 if s[("me", "double")] else 1)
    armour = s[("them", "armour")]
    if "armour" in f.parts and not f.broke:
        damage = damage - armour if damage > armour else 0
    return s[("them", "hp")] - damage <= 0


def _hp_after_immediate_turn(f, extra_block: int) -> int:
    """End-turn health without mutating the fight, for a strict dominance test."""
    s = f.state
    hp, cap, poison = s[("me", "hp")], f.max_hp, s[("me", "poison")]
    if poison > 0:
        hp -= poison
        cap = max(f.hp_floor,
                  cap - poison * TUNING["poison_cap"] // 100)
        hp = min(hp, cap)
    if hp <= 0 or s[("me", "dodge")]:
        return hp

    block = s[("me", "block")] + extra_block
    hit, ignores = f.enemy.hit_now(
        f.stalls, s[("them", "charge")], block, fed=f.fed, parts=f.parts)
    big = ("charge" in f.parts
           and s[("them", "charge")] >= f.enemy.charge_max)
    if f.is_boss and TUNING["big_frac"] and big:
        hit = max(hit, f.max_hp * TUNING["big_frac"] // 100)
    if f.is_boss and TUNING["big_lethal"] and big:
        return 0
    return hp - (hit if ignores else max(0, hit - block))


def survival_opportunity(f, block_name: str, attack_name: str) -> bool:
    """A narrowly objective attack-vs-defence decision.

    It fires only when the payable attack cannot end the fight, the payable
    block changes this turn from dead to alive, and the enemy is not a piercer.
    Ordinary tempo choices are intentionally outside this metric.
    """
    if ("pierce" in f.parts or not f.can_play(block_name)
            or not f.can_play(attack_name) or attack_would_kill(f, attack_name)):
        return False
    amount = f.deck[block_name].amount
    return (_hp_after_immediate_turn(f, 0) <= 0
            and _hp_after_immediate_turn(f, amount) > 0)


def squanders_survival(f, action: str, block_name: str,
                       attack_name: str) -> bool:
    """The chosen move consumes the last chance to take the saving block."""
    if not survival_opportunity(f, block_name, attack_name):
        return False
    if action == "end":
        return True
    if action not in f.deck or not f.can_play(action):
        return False
    card = f.deck[action]
    if card.kind in ("block", "dodge", "heal"):
        return False
    energy_left = f.state[("me", "energy")] - card.cost
    return energy_left < f.deck[block_name].cost


# ------------------------------------------------------------------ reporting

def load(model: str, seed: int, engine: str, lives: int = 9):
    d = pathlib.Path("/tmp/agii_runs")
    out = []
    for n in range(1, lives + 1):
        f = d / f"{model}_{seed}_{engine}_life{n}.json"
        if f.exists():
            out.append((n, json.loads(f.read_text())))
    return out


def adventure_steps(log) -> int:
    """Paid participant interactions, excluding neutral environment markers."""
    return sum(not is_observation(x) and not str(x).endswith("fight ended")
               for x in log)


def interaction_costs(rows):
    """Per-life camp/adventure cost, charging the shared camp exactly once."""
    out, total, camp_charged = [], 0, False
    for life, data in rows:
        camp = 0
        if not camp_charged and data.get("camp_log"):
            camp = participant_steps(data["camp_log"])
            camp_charged = True
        # A neutral terminal marker is evidence carried into the next life, not
        # another action paid for by the participant.
        adventure = adventure_steps(data.get("adv_log", []))
        total += camp + adventure
        out.append((life, camp, adventure, camp + adventure, total))
    return out


def report(model: str, seed: int, engine: str) -> None:
    rows = load(model, seed, engine)
    if not rows:
        print("没有记录"); return
    print(f"{model}  seed {seed}  engine {engine}")
    print(f"\n{'命':>3}{'结局':>16}{'训练营':>8}{'冒险':>8}{'本命成本':>10}{'累计':>8}"
          + "".join(f"{m:>9}" for m in MECHANICS))
    fair_metrics = all(d.get("metrics") == "behaviour-v2" for _, d in rows)
    print(" " * 54 + "（各机制分母不同；— 表示尚未遇到）")
    if fair_metrics:
        print(" " * 54 + "pierce=重复持盾/首次探针后的回合，")
        print(" " * 54 + "charge=未闪/当时可执行的槽满窗口，")
        print(" " * 54 + "armour=重复无效攻击/已有证据后的攻击，")
        print(" " * 54 + "poison=错休息/清毒机会；探针和不可执行窗口另列")
    else:
        print(" " * 54 + "旧口径：pierce=持盾回合/穿透怪回合，charge=未闪/槽满，")
        print(" " * 54 + "armour=无效攻击/攻击试验，poison=错休息/清毒机会")
    costs = {life: row for life, *row in interaction_costs(rows)}
    first_clear = None
    trace = {m: [] for m in MECHANICS}
    for n, d in rows:
        camp, adventure, life_cost, total = costs[n]
        mis = d.get("mistakes", {})
        opp = d.get("opportunities")
        enc = d.get("encounters", {})
        for m in MECHANICS:
            trace[m].append((mis.get(m, 0),
                             None if opp is None else opp.get(m, 0),
                             enc.get(m, 0)))
        if d.get("result") == "cleared" and first_clear is None:
            first_clear = n
        def cell(m):
            if opp is None:
                return f"{mis.get(m, 0)}/?"
            if not enc.get(m, 0) and not opp.get(m, 0):
                return "—"
            return f"{mis.get(m, 0)}/{opp.get(m, 0)}"
        print(f"{n:>3}{d.get('result','?'):>16}{camp:>8}{adventure:>8}"
              f"{life_cost:>10}{total:>8}"
              + "".join(f"{cell(m):>9}" for m in MECHANICS))
    print(f"\n通关于第 {first_clear} 条命" if first_clear else "\n尚未通关")
    print(f"总交互步数 {costs[rows[-1][0]][-1]}")
    print("\n错误行为是否被纠正：")
    for m in MECHANICS:
        v = trace[m]
        errors = [e for e, _, _ in v]
        chances = [o for _, o, _ in v if o is not None]
        seen = sum(e for _, _, e in v)
        if not any(errors):
            if sum(chances):
                tag = f"共 {sum(chances)} 次机会，尚未犯错"
            elif seen:
                tag = "已经遇到，但尚无可判定机会"
            elif any(o is None for _, o, _ in v):
                tag = "旧记录未统计机会，无法判断是否受测"
            else:
                tag = "尚未遇到"
            print(f"  {m:<8} {tag}")
            continue
        first = next(i for i, x in enumerate(errors) if x)
        later = [(e, o) for e, o, _ in v[first + 1:]
                 if o is not None and o > 0]
        if any(e for e, _ in later):
            tag = "⚠️ 后续机会仍在犯"
        elif later:
            tag = f"✅ 后续 {sum(o for _, o in later)} 次机会未再犯"
        else:
            tag = "— 后续尚无再测机会"
        pairs = [(f"{e}/?" if o is None else
                  "—" if not encountered and not o else f"{e}/{o}")
                 for e, o, encountered in v]
        print(f"  {m:<8} 每条命 {pairs}   首次在第 {first+1} 条命   {tag}")

    if any(d.get("behaviour") for _, d in rows):
        print("\n通关 ≠ 掌握：")
    for n, d in rows:
        b = d.get("behaviour") or {}
        enc = d.get("encounters", {})
        verdicts, shortcuts = {}, []
        pi = b.get("pierce", {})
        if not enc.get("pierce"):
            verdicts["穿透"] = "未遭遇"
        elif not pi.get("probes"):
            verdicts["穿透"] = "未受测"
            shortcuts.append("穿透 0 探针（从未举盾，机制没显形）")
        elif pi.get("repeat_errors"):
            verdicts["穿透"] = "受测未过"
        else:
            verdicts["穿透"] = "受测通过"
        ch = b.get("charge", {})
        if not enc.get("charge"):
            verdicts["蓄力"] = "未遭遇"
        elif not ch.get("executable_windows"):
            verdicts["蓄力"] = "未受测"
            shortcuts.append(f"蓄力 {ch.get('windows', 0)} 次槽满，"
                             f"0 次手里有闪避")
        elif ch.get("misses"):
            verdicts["蓄力"] = "受测未过"
        else:
            verdicts["蓄力"] = "受测通过"
        ar = b.get("armour", {})
        if not enc.get("armour"):
            verdicts["护甲"] = "未遭遇"
        elif not ar.get("evidence_events"):
            verdicts["护甲"] = "未受测"
            shortcuts.append("护甲 0 次诊断事件（习惯性破甲，没见过 0 伤害）")
        elif ar.get("repeat_errors"):
            verdicts["护甲"] = "受测未过"
            shortcuts.append(f"护甲见证据后仍错 {ar['repeat_errors']} 次")
        else:
            verdicts["护甲"] = "受测通过"
        po = b.get("poison", {})
        if not po.get("decisions"):
            verdicts["腐蚀"] = "未受测"
        elif po.get("wrong_rests"):
            verdicts["腐蚀"] = "受测未过"
        else:
            verdicts["腐蚀"] = "受测通过"
        passed = sum(v == "受测通过" for v in verdicts.values())
        print(f"  命 {n}: 结局 {d.get('result', '?')}")
        print(f"         迁移掌握 {passed}/4 受测通过   "
              + "  ".join(f"{k}={v}" for k, v in verdicts.items()))
        if shortcuts:
            print("         捷径信号：" + "；".join(shortcuts))
    print("  一次通关不结束 benchmark：受测通过数才是掌握，继续进入新世界看曲线。")

    if any(d.get("behaviour") for _, d in rows):
        print("\n探针、可执行性与遭遇内纠错：")
        for life, data in rows:
            b = data.get("behaviour")
            if not b:
                continue
            p, c, a = b["pierce"], b["charge"], b["armour"]
            print(
                f"  命 {life}: 穿透首次探针 {p['probes']}，证据后重复 "
                f"{p['repeat_errors']}/{p['post_probe_turns']}；"
                f"蓄力槽满 {c['windows']}，其中可执行 {c['executable_windows']}、"
                f"未准备 {c['unprepared_windows']}、可执行却未闪 {c['misses']}；"
                f"护甲探针 {a['probe_attacks']}，证据后重复 "
                f"{a['repeat_errors']}/{a['post_evidence_attacks']}")
            for encounter in b.get("encounters", []):
                pieces = []
                ep = encounter.get("pierce", {})
                ec = encounter.get("charge", {})
                ea = encounter.get("armour", {})
                if "pierce" in encounter.get("parts", []):
                    pieces.append(
                        f"穿透 探针{ep.get('probes', 0)} "
                        f"重复{ep.get('repeat_errors', 0)}/"
                        f"{ep.get('post_probe_turns', 0)}")
                if "charge" in encounter.get("parts", []):
                    pieces.append(
                        f"蓄力 槽满{ec.get('windows', 0)} "
                        f"可执行{ec.get('executable_windows', 0)} "
                        f"漏闪{ec.get('misses', 0)}")
                if "armour" in encounter.get("parts", []):
                    pieces.append(
                        f"护甲 探针{ea.get('probe_attacks', 0)} "
                        f"重复{ea.get('repeat_errors', 0)}/"
                        f"{ea.get('post_evidence_attacks', 0)} "
                        f"破除{ea.get('breaks', 0)}")
                if pieces:
                    print(f"      {encounter['where']}: " + "；".join(pieces))

    experiment = next((d.get("camp_experiments") for _, d in rows
                       if d.get("camp_experiments")), None)
    if experiment:
        print("\n训练营实验覆盖：")
        print(f"  成功激活 {experiment['coverage']}/{experiment['total_cards']} 张牌")
        for name, stats in experiment["cards"].items():
            first = stats.get("first_success_step")
            status = (f"首次成功第 {first} 步，成功 {stats['successes']} 次"
                      if first is not None else
                      f"从未成功（可操作 {stats['playable_steps']} 步）")
            failures = stats.get("absent", 0) + stats.get("insufficient_energy", 0)
            print(f"  {name:<8} {status}；尝试 {stats['attempts']} 次，失败 {failures} 次")

    print("\n格挡审计（不给模型看，用于判断是否需要公开吸收量）：")
    for n, d in rows:
        a = d.get("shield_audit")
        if not a:
            print(f"  命 {n}: 旧记录无审计")
            continue
        print(f"  命 {n}: 举盾 {a['blocked']} / 不举盾 {a['unblocked']} 回合；"
              f"完全吸收 {a['fully_absorbed']} 次，累计吸收 {a['absorbed_total']}")
        print(f"         引擎侧不可辨认回合 {a.get('blind', '?')}"
              f"   模型做出同条件对照 {a.get('matched_absorb', '?')}"
              f" / 未做 {a.get('unmatched_absorb', '?')}")
    print("  引擎侧不可辨认 = 同一回合前状态下，带盾与不带盾的可见结果完全相同。")
    print("  只有这一项能支持公开吸收量；它与模型策略无关。")
    print("  同条件对照 = 模型自己在同场跑出了条件完全相同的无盾回合，")
    print("  这是主动实验效率的指标，不能用来决定要不要改界面。")

    if any(d.get("resource") or d.get("planning") for _, d in rows):
        print("\n资源效率与生存规划：")
        for life, data in rows:
            resource = data.get("resource", {})
            planning = data.get("planning", {})
            print(f"  命 {life}: 满血耗治疗 {resource.get('zero_effect_exhaust', 0)} 次；"
                  f"满血且治疗可用 {resource.get('full_heal_turns', 0)} 回合；"
                  f"可避免的立即死亡 {planning.get('avoidable_lethal', 0)}/"
                  f"{planning.get('opportunities', 0)}")


if __name__ == "__main__":
    import sys
    report(sys.argv[1], int(sys.argv[2]),
           sys.argv[3] if len(sys.argv) > 3 else ENGINE_VERSION)
