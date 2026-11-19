"""The calculation engine.

Every number about "how likely is this to be cleared" goes through here.

What it replaces: `tune.py` answered *"clear rate under the route heuristic I
wrote"*. The route search below covers a named, executable policy family. Its
reported result is an estimate for the route found by coordinate ascent, not a
proof of optimality and not the benchmark score: the benchmark score is the
learning curve over lives, interaction steps and corrected mistakes.

Three layers, in the order the user asked for them:

  1. `run_once`      one complete run on the REAL engine -- draws, energy, card
                     exhaustion, rage, armour breaking, rewards, rest, all of it
  2. `best_route`    coordinate ascent over the declared route family
  3. `probability`   evaluates the selected route on a disjoint random stream,
                     averages over seeds, and puts uncertainty over seeds

Knowledge is first class: `Know` is the set of mechanics the player has worked
out, and the in-fight policy is derived from it. A run's clear probability is
therefore a function of what is understood, which is the thing the benchmark is
actually measuring.

RULES THIS FILE MUST NOT QUIETLY BREAK. Each has already cost real time:

  * Every piece of state the solver touches is restored, EVERY TRIAL, not once
    at the end: `deck_list`, `Card.cost_known`, `hp`, `base_atk`, `max_hp`,
    `poison`, `shuffles`. Seven separate bugs so far have been the screen or the bench
    leaving a mark on the thing it was measuring -- twice the fix itself left a
    new one, because "restore after the loop" is not "restore each trial".
  * No number comes from a hand-written damage model. Simplified models have
    twice produced the exact opposite of the truth (both times by assuming an
    unlimited hand). Everything runs `Fight`.
  * Enemy numbers that depend on the player's attack are read from the CURRENT
    attack, never from the value the run started with. Pinning armour to the
    starting attack made one elite reward delete the mechanic outright, and that
    was the second time the same mistake was made.
  * Policies being compared use common random streams for each layer's shuffle
    and blind node draw. Rolling fresh randomness per policy makes differences
    mostly noise; sharing one mutable RNG across decisions makes later layers
    drift when two policies take different branches.
  * A result is reproducible as (ENGINE_VERSION, seed, life) only under the
    canonical screen configuration. Changing any knob changes what the screen
    selects; the selected salt and configuration are stored with every run.
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import math
import multiprocessing
import os
import errno
import time
if os.name == "nt":
    import msvcrt
else:
    import fcntl
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import itertools
from itertools import combinations
import pathlib
import random
import statistics
import tempfile
from dataclasses import dataclass, field, replace

import adventure
from adventure import (BOSS_SHIFT, ENGINE_VERSION, MOMENTUM_FULL_AT, Run, TUNING,
                       scaled)

# What a player can have worked out, on TWO axes.
#
# `MECHANICS` is enemy knowledge: what this monster does and what answers it.
# `CARD_SKILLS` is knowledge of the player's own deck: what a card does,
# independent of who is standing in front of you.
#
# They were one list until c21, and that is what made the armour measurement a
# strawman. Both `buff_mark` branches below were gated on `"armour" in know`,
# so ablating armour ablated TWO things at once -- "does not recognise this
# monster" and "will not use the doubler at all" -- and no player is the second
# one. Ablating an enemy mechanic must leave the player's card knowledge
# untouched, or the gap measured against it is the cost of playing badly rather
# than the cost of not knowing.
#
# "armour" stays spellable so its implementation can still be exercised (pass
# `ALL | {"armour"}`), but it is no longer in `ALL`: the monster left the
# rotation in c21. See the note in adventure.py.
# Derived, not repeated. A hand-kept copy of the rotation is a copy that
# disagrees with it: the audited family is `len(MECHANICS)` partial policies
# wide, so a mechanic added to the rotation and not here would be a mechanic the
# certificate silently does not cover.
MECHANICS = tuple(adventure.BEHAVIOURS)
CARD_SKILLS = ("double", "tempo")

# Bumped whenever the SCREEN changes, separately from the engine. The blind
# family was added to `screen_precise` and the cache key did not move, so
# `c17:7731:1` kept hitting a world chosen before shortcuts were priced -- a
# tightened screen that silently reuses its own pre-tightening answers has done
# nothing at all. The engine version is for changes to the game; this one is for
# changes to how worlds are selected, and the two move independently.
# s3: `heal_at` 0 joins the route grid, so the blind family can express a
# line that never plays a non-attack card at all. That widens what the
# shortcut ceiling can find, which is exactly a change to world selection.
SCREEN_VERSION = "s7-neverhold"
ALL = frozenset(MECHANICS) | frozenset(CARD_SKILLS)
NONE = frozenset()


# --------------------------------------------------------------- in-fight play

@dataclass
class FightBelief:
    """Mechanisms identified from observations made in this fight.

    This is deliberately smaller than ``Enemy.parts``.  In particular a fresh
    piercer has no identifying slot, so even a player who knows the rule has to
    see it interact with a shield before conditioning later actions on it.
    """
    pierce: bool = False
    enrage: bool = False
    momentum: bool = False
    counter: bool = False
    mimic: bool = False
    worst: int = 0               # heaviest hit taken so far THIS fight
    # Whether the end-of-turn detector runs for a policy that does NOT already
    # know the rule. False here, and that is right for a REFERENCE policy: its
    # premise is "knows what a piercer is, must still identify this one".
    #
    # It is wrong for anything that has to LEARN the rule, and the gate below
    # made that structurally impossible -- the detector that would teach you
    # about pierce only ran once you already knew about pierce. A learner sets
    # this True; every policy measured so far leaves it alone, so no number
    # that has been reported moves.
    #
    # Deliberately WITHOUT a type annotation. `FightBelief` is a dataclass, so
    # an annotated attribute becomes a FIELD, and the generated `__init__`
    # writes the default onto every instance -- which silently overrides a
    # subclass that sets it as a class attribute. That is how the first version
    # of this flag read False on the very class that set it to True.
    always_observe = False

    def observe_play(self, f, atk_before: int, kind: str) -> None:
        """Evidence that arrives inside your own turn, not at the end of it.

        The piercer answers at end of turn; the enrager answers immediately,
        and the causal link is unusually clean -- the public attack slot moved
        between two of your own cards, so nothing else can be blamed for it.
        That is a bit the player BOUGHT with an action, which is why a line
        that uses it belongs in `AdaptiveProbe` and not in `StaticBlind`.
        """
        if kind != "attack" and f.state[("them", "atk")] > atk_before:
            self.enrage = True
        # 模仿：你出增伤的当下它身上的槽位亮起 —— 公开、即时、只有它会这样。
        if kind == "buff_mark" and f.state.get(("them", "mimic"), 0) >= 1:
            self.mimic = True

    def observe_end_turn(self, f, hp_before: int, block_before: int,
                         poison_before: int, charge_before: int = 0,
                         atk_before: int = None, played_non_attack: bool = False
                         ) -> None:
        if charge_before >= max(1, f.enemy.charge_max):
            return               # a wind-up firing is not evidence about shields
        # Everything here was on the public screen: current-health loss and the
        # poison counter. Poison bites and can lower the ceiling before the
        # enemy hits, so rebuild the publicly inferable post-poison baseline
        # first -- otherwise the tick is mistaken for a shield reaction.
        post_poison = min(hp_before - poison_before, f.max_hp)
        attack_loss = post_poison - f.state[("me", "hp")]
        # 反击：一个进攻了两次的回合，挨了远超印在屏幕上的攻击的一下。蓄力大招
        # 在上面已经排除（charge_before 满格直接 return），所以剩下的「大的」只有它。
        # 阈值 2 倍：探针那一下就是 2 倍，检测器必须在探针上就认出来，不然懂的
        # 人要挨到全价那一下才知道 —— 那就不是探针了。
        if (getattr(f, "last_offences", 0) >= 2
                and attack_loss >= 2 * max(1, f.state[("them", "atk")])):
            self.counter = True
        # The comparison is against the heaviest hit ALREADY TAKEN, not against
        # the shield. Thresholding on the shield coupled two unrelated numbers:
        # a piercer's probe is twice the ENEMY's attack, while `block * 2` grows
        # with the PLAYER's card, so a bigger shield made the piercer harder to
        # identify and a large enough one made it invisible. Measured on a
        # screened world: at block 4 the reference cleared 92%, at block 9 it
        # cleared 30% and at block 99 it cleared 6% -- not because the shield was
        # worse, but because the detector had been blinded by its own threshold.
        #
        # Health loss per turn is visible every turn and needs no knowledge of
        # the enemy's attack (which shows as `?` until rage moves it, so reading
        # it would be privileged). Rage adds 1 a turn; the probe doubles. The
        # two do not overlap.
        # The scale is the player's OWN attack, not the shield. Enemy attack is
        # generated as `my_atk + 0..3`, so twice my attack is above anything an
        # ordinary enemy can land through a shield of any size, and at or below
        # the probe's doubling of its own attack. `worst` keeps the threshold
        # honest once rage has pushed the real attack past that floor.
        floor = max(f.state[("me", "atk")], self.worst)
        if block_before > 0 and attack_loss >= floor * 2:
            self.pierce = True
        self.worst = max(self.worst, attack_loss)
        # Momentum and enrage put the SAME thing on screen -- the public attack
        # number rising -- and that is deliberate: one experiment separates
        # them, because a shield sends an enrager's attack up and a momentum
        # enemy's down. So the two detectors have to differ in exactly the way
        # the two mechanics do:
        #
        #   enrage    the number moved BETWEEN two of your cards, inside a turn
        #             (`observe_play`), and a non-attack card had just resolved
        #   momentum  the number moved at the END of a turn in which you held no
        #             shield, with no non-attack card to blame it on
        #
        # `played_non_attack` is what keeps the second from claiming the first:
        # without it, every enrage trigger would also read as momentum.
        if (atk_before is not None and not played_non_attack
                and block_before <= 0
                and f.state[("them", "atk")] > atk_before):
            self.momentum = True


@dataclass
class RevisableBelief(FightBelief):
    """A belief that can be WITHDRAWN when the world stops obeying it.

    `FightBelief` is monotonic: once a mechanic is identified it stays
    identified for the rest of the fight. That is correct for an enemy whose
    rule never changes, and it is exactly wrong for one whose rule does --
    measured on a boss that changes rule at half health, a line using the
    monotonic belief scored 26% against a fixed habit's 29%. Learning a rule
    and being unable to drop it was worth nothing at all.

    What is withdrawn is deliberately NOT the knowledge. The player still knows
    what an enrager is and what a momentum enemy is; what they give up is the
    claim about which of them they are fighting RIGHT NOW. Three time scales,
    and only the middle one moves here:

        across lives      the mechanics themselves          (`know`, untouched)
        across enemies    which mechanic this monster is    (a fresh belief)
        inside one fight  whether that is still true        (this class)

    Retraction is driven by a falsified PREDICTION, not by a count of bad
    turns. Each asserted mechanic says something that the very next turn can
    contradict:

        enrage     "play no non-attack card and the attack will not rise"
        momentum   "end the turn holding a shield and the attack will not rise"

    and the two are contradictories, not merely different: a shield IS a
    non-attack card, so the one experiment that tests either of them
    distinguishes both. A turn that provides no such test is not counted as
    evidence either way.
    """
    chain: dict = field(default_factory=lambda: dict(
        tests=0,                 # turns that could have contradicted a belief
        violations=0,            # turns that did
        suspected_turn=None,     # first contradiction
        retracted=(),            # what was withdrawn, in order
        reidentified_turn=None,  # first turn a new mechanic was asserted after
        relapses=0,              # a withdrawn belief asserted again
    ))

    def _retract(self, name: str, f) -> None:
        if not getattr(self, name):
            return
        setattr(self, name, False)
        c = self.chain
        c["violations"] += 1
        if c["suspected_turn"] is None:
            c["suspected_turn"] = f.turn
        c["retracted"] = c["retracted"] + (name,)

    def _reidentify(self, f) -> None:
        c = self.chain
        if not c["retracted"]:
            return
        if c["reidentified_turn"] is None and (self.enrage or self.momentum
                                               or self.pierce):
            c["reidentified_turn"] = f.turn
        for name in set(c["retracted"]):
            if getattr(self, name):
                c["relapses"] += 1

    def observe_play(self, f, atk_before: int, kind: str) -> None:
        # A non-attack that RAISED the attack is the enrager's signature and
        # momentum's contradiction in the same event: under momentum a shield
        # sends the number the other way.
        if (self.momentum and kind != "attack"
                and f.state[("them", "atk")] > atk_before):
            self.chain["tests"] += 1
            self._retract("momentum", f)
        super().observe_play(f, atk_before, kind)
        self._reidentify(f)

    def observe_end_turn(self, f, hp_before: int, block_before: int,
                         poison_before: int, charge_before: int = 0,
                         atk_before: int = None,
                         played_non_attack: bool = False) -> None:
        if atk_before is not None and charge_before < max(1, f.enemy.charge_max):
            rose = f.state[("them", "atk")] > atk_before
            if self.enrage and not played_non_attack:
                self.chain["tests"] += 1
                if rose:
                    self._retract("enrage", f)
            if self.momentum and block_before > 0:
                self.chain["tests"] += 1
                if rose:
                    self._retract("momentum", f)
        super().observe_end_turn(f, hp_before, block_before, poison_before,
                                 charge_before, atk_before, played_non_attack)
        self._reidentify(f)


@dataclass
class CueAwareBelief(FightBelief):
    """Told that something changed; not told what.

    The announced arm's reference policy. It needs no per-mechanic
    falsification rule, and that is the point: with the silent arm, ten of the
    twelve ordered pairs never retracted anything, because only enrage and
    momentum had a prediction a turn could contradict. A cue is one signal that
    works for every pair.

    What the cue does is exactly three things:

        keeps       the knowledge of what each mechanic IS   (`know`, untouched)
        clears      the claim about which one is in front of you
        restarts    evidence collection from the next turn

    `worst` -- the heaviest hit taken so far -- is deliberately NOT cleared. It
    is a fact about damage that was really taken, not a judgement, and the
    piercer's detector uses it as a FLOOR: lowering it makes a false positive
    easier, not identification fairer.
    """
    _seen_events: int = 0
    cues: int = 0
    cleared: tuple = ()
    reidentified_turn: int = None

    def observe_events(self, f) -> None:
        events = getattr(f, "events", ())
        if len(events) <= self._seen_events:
            return
        for _turn, name in events[self._seen_events:]:
            if name != BOSS_SHIFT:
                continue
            self.cues += 1
            self.cleared = self.cleared + tuple(
                m for m in ("pierce", "enrage", "momentum") if getattr(self, m))
            self.pierce = self.enrage = self.momentum = False
            self.reidentified_turn = None
        self._seen_events = len(events)

    def _note_reid(self, f) -> None:
        if (self.cues and self.reidentified_turn is None
                and (self.pierce or self.enrage or self.momentum)):
            self.reidentified_turn = f.turn

    def observe_play(self, f, atk_before: int, kind: str) -> None:
        super().observe_play(f, atk_before, kind)
        self._note_reid(f)

    def observe_end_turn(self, f, hp_before: int, block_before: int,
                         poison_before: int, charge_before: int = 0,
                         atk_before: int = None,
                         played_non_attack: bool = False) -> None:
        super().observe_end_turn(f, hp_before, block_before, poison_before,
                                 charge_before, atk_before, played_non_attack)
        self._note_reid(f)


def act(f, know, kinds, information="oracle", belief=None,
        enrage_budget=0, offence_cap=None, avoid=()):
    """What to play next, given what the player has worked out.

    Every branch is gated on knowledge. This is the reference policy after a
    mechanic and its encounter signature have been learned; map routing still
    cannot inspect the behaviour hidden behind a node."""
    if information not in {"oracle", "observable"}:
        raise ValueError(f"unknown information mode: {information}")
    # 标记：知道规则的人这回合不出被标记的那种牌。槽位公开，不分模式。
    marked = f.marked_kind() if ("mark" in know and hasattr(f, "marked_kind")) else None
    # `avoid`：调用方另外认定这回合不该出的牌种（core/cautious.py 用它代替直接读标记映射：代号对应哪种牌
    # 每张图重抽，只看画面的玩家得自己推）。默认空，行为不变。
    def can(kind):
        return f.can_play(kinds[kind]) and kind != marked and kind not in avoid
    parts = f.parts
    # The charge counter is public from turn 0 -- every enemy carries that
    # slot, so reading it is not privileged. The armour slot is NOT public
    # until the armour has acted: it is carried by one kind of enemy only,
    # so showing it up front handed over the answer, and it is now withheld
    # (see `_row`). The policy has to be held to the same screen, or the
    # informed ceiling is quoted from information no player can have --
    # which inflates every gap measured against it. Reading `Enemy.parts`
    # for an unmarked piercer is privileged in the same way.
    charged = ("charge" in know
               and f.state[("them", "charge")] >= f.enemy.charge_max)
    armoured = ("armour" in know and f.armour_seen
                and f.state[("them", "armour")] > 0 and not f.broke)
    piercer = ("pierce" in know and
               ((information == "oracle" and "pierce" in parts)
                or (information == "observable" and belief is not None
                    and belief.pierce)))
    # How much of the enrager's gain this policy is WILLING TO SPEND, and the
    # reason it is a parameter rather than a rule.
    #
    #   0  refuse every avoidable non-attack until the gain is capped
    #   1  spend the cheap first tier deliberately, then refuse
    #   2  spend both, then play normally -- the increment is capped, so after
    #      that the shield and the doubler are free again
    #
    # The first of these used to be hard-coded and was quoted as the "oracle"
    # ceiling. It is not one: it is `strict_avoid`, a policy that throws away a
    # shield on every turn of every enrage fight to dodge a cost it may never
    # have paid. Measured, it LOST to the observation-legal line below full
    # 250%, which is not an anomaly -- it is the hard-coded policy being worse.
    #
    # Which budget wins is the structural verdict on the mechanic:
    #   1 wins  -> what is learned is "the first tier is tradeable, the second
    #              is not", which is the shape this is trying to teach
    #   0 wins  -> a pure restraint mechanic; still a mechanic
    #   2 wins  -> the CAP is broken: the best thing to know becomes "enrage it
    #              to the ceiling as fast as possible, then play as you like"
    #
    # Above `enrage_cap` nothing grows, so refusing there is pure self-harm.
    enrager = ("enrage" in know
               and enrage_budget <= f.enraged < TUNING["enrage_cap"]
               and ((information == "oracle" and "enrage" in parts)
                    or (information == "observable" and belief is not None
                        and belief.enrage)))

    # A shield RESETS the ramp, so the answer is to spend one before the full
    # tier lands -- which means playing it FIRST, ahead of the attack, rather
    # than with whatever energy is left over. That priority is the whole
    # difference between knowing this mechanic and not: the default line already
    # blocks with spare energy about a third of the time, so a player who never
    # heard of momentum keeps it down by accident some of the time and the
    # separation has to come from the turns where the ramp is about to fire.
    ramping = ("momentum" in know
               and f.momentum >= MOMENTUM_FULL_AT - 1
               and ((information == "oracle" and "momentum" in parts)
                    or (information == "observable" and belief is not None
                        and belief.momentum)))

    # The second-offence arm's answer is a different SHAPE of answer, so it
    # gets its own name rather than being folded into `enrager`. The old rule
    # says "play no non-attack card"; this one says "do not take a SECOND
    # offensive action this turn" -- defending, healing and dodging are free,
    # and the budget now counts offensive actions you are willing to pay for
    # rather than tiers you are willing to spend.
    # A MEASUREMENT INSTRUMENT, not a rule of the game. It caps how many
    # offensive actions the informed line will take in a turn, against every
    # monster, so the second one's contribution can be priced -- which is the
    # number that decides whether any anti-aggression mechanic is worth
    # designing at all. It gates here because `overcommitting` already gates
    # exactly the right set of branches: the attack and both doubler branches,
    # and nothing defensive.
    # 反击的答案就是 `offence_cap=1`：识别出来之后，这一场一回合只进攻一次。
    # 复用测量用的那条盖子，而不是再写一条会自己漂移的规则。
    counterer = ("counter" in know
                 and ((information == "oracle" and "counter" in parts)
                      or (information == "observable" and belief is not None
                          and belief.counter)))
    # 守势：相位槽是公开的（只有守势怪会让它非零），所以不分 oracle/observable；
    # 守相时一次进攻都不做 —— 同样并进 `capped`。
    guarder = "guard" in know and f.state.get(("them", "guard"), 0) >= 1
    capped = ((offence_cap is not None and f.offences >= offence_cap)
              or (counterer and f.offences >= 1) or guarder)
    # 模仿：懂的人对它不增伤 —— 除非翻倍的攻击这回合就能打死它（怪死了那一击不落下）。
    # 不是「只有能击杀才增伤」这么死板的唯一答案：账本只把「增伤了、它没死、那一击落下」
    # 记成错；这里的参考策略取最稳的那条。
    mimicker = ("mimic" in know
                and ((information == "oracle" and "mimic" in parts)
                     or (information == "observable" and belief is not None
                         and belief.mimic)))
    lethal_double = (f.state[("them", "hp")] <= 2 * f.state[("me", "atk")]
                     and f.can_play(kinds["attack"])
                     and f.state[("me", "energy")] >= f.deck[kinds["buff_mark"]].cost + f.deck[kinds["attack"]].cost)
    buff_ok = (not mimicker) or lethal_double
    # 破势：封印槽位公开（非零起始就印出来），懂的人封着时举盾、不攻击。
    warded = "ward" in know and f.state.get(("them", "ward"), 0) > 0
    overcommitting = capped or (
        TUNING["enrage_on_second_offence"]
        and "enrage" in know
        and f.enraged < TUNING["enrage_cap"]
        and f.offences >= 1 + enrage_budget
        and ((information == "oracle" and "enrage" in parts)
             or (information == "observable" and belief is not None
                 and belief.enrage)))

    if charged and can("dodge"):
        return kinds["dodge"]

    if ramping and can("block"):
        return kinds["block"]

    # 流血：身份是公开计数器（和蓄力槽、毒层一样），所以不分 oracle/observable，
    # 也不需要 belief。答案是一张牌 —— 这正是它存在的理由。
    if ("wound" in know
            and f.state[("me", "wound")] >= TUNING["wound_heal_stacks"]
            and can("heal")):
        return kinds["heal"]

    if armoured and not overcommitting:
        # Plain hits land for nothing until the armour is broken, so the double
        # has to go up first and an attack has to follow it.
        if not f.state[("me", "double")] and can("buff_mark") and buff_ok:
            return kinds["buff_mark"]
    # 势：攒到 2 以上、手里有增伤 —— 先翻倍再放。懂势的人唯一多做的事；不主动等待，
    # 只利用怪的规则逼出来的等待回合（守相、被标的攻击、闪大招的回合）。
    if (TUNING["tempo"] and "tempo" in know and f.state.get(("me", "tempo"), 0) >= 2
            and not f.state[("me", "double")] and not overcommitting
            and can("buff_mark") and buff_ok):
        return kinds["buff_mark"]

    if warded and can("block") and not piercer:
        return kinds["block"]
    # 封着又没盾：不能干等 —— 手牌只有出了牌才会换，干等就永远抽不到盾（实测标量侧死锁在
    # 一手没有盾的牌上 26 回合）。出非攻击牌换牌；连非攻击牌都没有才攻击（加固一格，但换了牌）。
    # 只在这回合**还什么都没出**时才算卡住：举了盾之后余下能量绝不能去攻击（那会把刚减的封印加回去）。
    stuck = (warded and not getattr(f, "played_kinds", {})
             and not any(can(k) for k in ("block", "dodge", "heal", "buff_mark")))
    # 斜坡·安静盾：这回合已经为压斜坡举了盾，就别再攻击，不然盾白举。
    quiet_hold = (TUNING["momentum_quiet_reset"] and ramping
                  and getattr(f, "played_kinds", {}).get("block", 0) >= 1)
    if can("attack") and not overcommitting and (not warded or stuck) and not quiet_hold:
        return kinds["attack"]

    # Spare energy goes on block by default. Knowledge of the encounter
    # signature is what gates the exception for a learned piercer.
    #
    # The enrager stops here for a different reason, and the difference is the
    # whole point of splitting avoidable from necessary. Everything BELOW this
    # line is an optimisation -- a shield, the doubler, a dodge held for a
    # wind-up that is not due -- and against an enrager each of them hands it a
    # permanent attack increase for a marginal gain. Everything ABOVE it
    # already ran: the charged dodge, which is the difference between living
    # and dying, and the attack, which does not feed it at all. The heal is
    # decided in `play_fight` before this function is reached, deliberately: a
    # player low enough to need it may rationally pay the increase for it, and
    # scoring every non-attack as an error would price a move nobody should
    # avoid.
    # The enrager refuses EVERY optimisation below this line, for the reason
    # above. A piercer refuses exactly one thing, because it punishes exactly
    # one thing: `block > 0` at settlement. It used to share the enrager's
    # branch and therefore gave up the doubler and a held dodge as well, which
    # nothing in its rule asks for -- measured on the four confirmed worlds,
    # that cost the informed line 3.7 points of clear rate and understated
    # pierce's own marginal value by the same amount, in every world, every
    # time. An informed line that throws away free damage is not the ceiling
    # the whole method quotes its gaps against.
    if enrager:
        return None
    if can("block") and not piercer:
        return kinds["block"]
    # Only cycle passive cards after the defensive decision. Putting the mark
    # before block made the generic attack+mark combo accidentally solve the
    # piercer without recognising it, erasing the mechanism's knowledge gap.
    # Card knowledge, not enemy lore: whether you know what the doubler does
    # has nothing to do with what you are fighting. Gating this on "armour"
    # is what made the armour ablation a strawman.
    if ("double" in know and not f.state[("me", "double")]
            and not overcommitting
            and can("buff_mark") and buff_ok):
        return kinds["buff_mark"]
    if "charge" in know and can("dodge"):
        return kinds["dodge"]
    return None


# --------------------------------------------------- mechanism-blind play

@dataclass(frozen=True)
class StaticBlind:
    """A line that plays the same way whatever it is fighting, and never
    changes its rule in response to anything that happens.

    This family exists because the screen was measuring the wrong opponent. Its
    partial policies are "informed, except one mechanic, and therefore doing the
    move that mechanic punishes" -- a player who blocks the piercer, stands in
    the wind-up. A model does not have to be any of those. It can be ignorant of
    every mechanic and simply never make the punished move, and that line was
    never priced: measured on c17/7731, it cleared 20.5% while every
    single-mechanic partial was under 6%.

    So the family is deliberately ignorant, and not only of `Enemy.parts`: it
    may not read the armour value or the wind-up counter either. Those are on
    the public screen, but conditioning on them -- "hold the dodge until the
    counter reads 2" -- IS the charge mechanic, and a policy that can express it
    is not blind.

    It may not change its own rule mid-fight either. A line that stops blocking
    after being punished for blocking has LEARNED something, at the cost of one
    punished turn; it belongs in `AdaptiveProbe`, and scoring it here would
    require an accepted world to defeat learning itself.

    `mark` was a boolean called `combo` until c21, which meant BOTH settings
    played the doubler and only the timing changed -- so "never touch the
    doubler", the line an enrage-style monster would force, could not be
    expressed and was silently priced at zero.
    """
    mark: str            # "first" | "late" | "never"
    block: bool          # leftover energy goes on a shield
    dodge_open: bool     # spend the dodge on the first turn of every fight
    attack_limit: int | None   # most attacks in one turn, or None for no cap
    # "Play the dodge whenever you are holding one." It reads the HAND, never
    # the wind-up counter, so it stays inside this family's rule -- and it only
    # became worth pricing with `charge_returns_dodge`, which puts the card in
    # hand at exactly the moment the counter is at the top. The environment
    # would then be handing out the answer, and a line that never understood
    # anything would take it. Default False, so the declared family and its
    # Bonferroni accounting are unchanged until the grid is deliberately
    # widened.
    dodge_hand: bool = False

    def __post_init__(self):
        if self.mark not in {"first", "late", "never"}:
            raise ValueError(f"unknown mark policy: {self.mark!r}")


STATIC_GRID = tuple(
    StaticBlind(m, b, d, a)
    for m in ("first", "late", "never")
    for b in (True, False)
    for d in (True, False)
    for a in (1, None))


@dataclass(frozen=True)
class AdaptiveProbe:
    """A static line plus corrections it is allowed to make AFTER paying.

    Separate from `StaticBlind` on purpose, and not because the distinction is
    tidy. "Never block" from turn one is a habit that costs nothing to hold;
    "block once, take an anomalous hit, stop blocking" spent a turn and a chunk
    of health to buy the same behaviour. The second is skill acquisition -- the
    thing this benchmark exists to measure -- and folding it into the blind
    ceiling would require an accepted world to be one in which LEARNING also
    fails. That is not a harder benchmark, it is a broken one.

    What it may read is exactly what the player can see happen: its own health
    and slots, the public enemy row, and the fact that one of those changed
    immediately after a card it played. It still may not read `Enemy.parts`.
    """
    base: StaticBlind
    # Stop blocking for the rest of a fight after one end of turn that cost
    # >= this many multiples of the player's own attack while a shield was up.
    stop_blocking_at: float | None = 2.0

    @property
    def dodge_open(self):           # `play_fight` reads this off either family
        return self.base.dodge_open


ADAPTIVE_GRID = tuple(AdaptiveProbe(b, 2.0) for b in STATIC_GRID if b.block)


@dataclass(frozen=True)
class FixedOrder:
    """Never hold a card back.

    "Play everything" needs saying carefully, because two energy a turn means a
    hand is never emptied. What this line actually is:

        while there is energy and a playable card, do not end the turn
        never keep a heal, a dodge, a shield or the doubler for later
        choose by a fixed priority that does not look at the enemy

    It is not expressible as a `StaticBlind`: that family decides WHETHER to
    shield and WHEN to double, but it still declines to spend -- it stops on a
    learned piercer, and it holds the dodge unless `dodge_open` is set. The
    habit being priced here is the opposite one, "never save anything", and a
    world that is only tested against families which save cards has not been
    tested against it at all.

    Two orders are carried rather than one, because a single permutation being
    weak says nothing about the habit -- only about that permutation.
    """
    order: tuple[str, ...]
    name: str = ""
    # At most this many offensive actions (attack or doubler) per turn. Still a
    # habit: it reads the line's own turn, never the enemy.
    offence_cap: int | None = None
    # 针对性盲线。三条都不读怪，只读自己的回合数或自己上回合出了什么：
    #   attack_on   只在奇/偶回合进攻 —— 守势若固定从「开」开始就被它解掉
    #   alternate   不出上回合出得最多的那种 —— 标记若标「你出得最多的」就被它解掉
    #   digit_memo  读标记槽位的数字、按**固定**映射避牌 —— 代号不每局重掷就被它解掉
    # 它们在盲线族里，是为了让门自己抓到这三条捷径，而不是靠我记得。
    attack_on: str | None = None
    alternate: bool = False
    digit_memo: bool = False
    # 势的固定节奏（事先指定的对照）：等待回合按 wait_order 出牌；attack_at_tempo 表示
    # 只在自己势 >= k 的回合进攻（读的是自己的公开槽位，不读怪）。
    wait_order: tuple | None = None
    attack_at_tempo: int | None = None
    # 破势的固定节奏对照：开场第一回合只举盾；每 block_every 回合有一回合只举盾。
    block_open: bool = False
    block_every: int | None = None

    @property
    def dodge_open(self):      # `play_fight` reads this off any blind family
        return False

    @property
    def dodge_hand(self):
        return False


ATTACK_FIRST = FixedOrder(("attack", "buff_mark", "block", "heal", "dodge"),
                          "不留牌·攻击优先")
UTILITY_FIRST = FixedOrder(("heal", "dodge", "block", "buff_mark", "attack"),
                           "不留牌·功能牌优先")
# One offensive action a turn, then a fixed fallback. This is the habit the
# second-offence arm of enrage hands out: its answer -- "do not swing twice in
# one turn" -- is expressible as a rule that needs no reading of the enemy at
# all, so it has to be IN the fixed-habit family or the acceptance instrument
# cannot see it as a shortcut. The same omission is what let "never block"
# clear the piercer for free until momentum was built.
ONE_SWING = tuple(
    FixedOrder(("attack", kind, "dodge", "heal", "block", "buff_mark"),
               f"一击后{label}", offence_cap=1)
    for kind, label in (("block", "举盾"), ("heal", "治疗"), ("dodge", "闪避")))
NEVER_HOLD = (ATTACK_FIRST, UTILITY_FIRST)
RHYTHM = (
    FixedOrder(ATTACK_FIRST.order, "奇数回合才攻击", attack_on="odd"),
    FixedOrder(ATTACK_FIRST.order, "偶数回合才攻击", attack_on="even"),
    FixedOrder(ATTACK_FIRST.order, "不出上回合出得最多的", alternate=True),
    FixedOrder(ATTACK_FIRST.order, "背数字避标记", digit_memo=True),
)
# 势经济下事先指定的固定节奏对照。只在 TUNING["tempo"] 开时进族：它们读自己的势槽位或回合
# 数，不读怪；若有一条跨怪都能赢，势就只是把无脑猛攻换成了无脑蓄势。
TEMPO_LINES = (
    FixedOrder(("attack", "attack", "heal", "dodge", "block", "buff_mark"), "势·增伤+防御→双攻",
               attack_on="even", wait_order=("buff_mark", "block", "heal", "dodge")),
    FixedOrder(("attack", "attack", "heal", "block", "buff_mark", "dodge"), "势·闪避→双攻",
               attack_on="even", wait_order=("dodge", "block", "heal", "buff_mark")),
    FixedOrder(("attack", "attack", "buff_mark", "heal", "block", "dodge"), "势·挡挡打",
               attack_at_tempo=2, wait_order=("block", "heal", "dodge", "buff_mark")),
    FixedOrder(("attack", "attack", "heal", "block", "dodge"), "势·增伤等等放",
               attack_at_tempo=2, wait_order=("buff_mark", "block", "heal", "dodge")),
    FixedOrder(("attack", "attack", "heal", "block", "dodge", "buff_mark"), "势·攒满再放",
               attack_at_tempo=3, wait_order=("block", "dodge", "heal", "buff_mark")),
)


# 破势的事先指定对照：只在池里有 ward 时进族。都不读怪，只读自己的回合数。
WARD_LINES = (
    FixedOrder(ATTACK_FIRST.order, "破势·开场先举盾", block_open=True,
               wait_order=("block", "heal", "dodge", "buff_mark")),
    FixedOrder(ATTACK_FIRST.order, "破势·每三回合举盾", block_every=3,
               wait_order=("block", "heal", "dodge", "buff_mark")),
    FixedOrder(ATTACK_FIRST.order, "破势·每两回合举盾", block_every=2,
               wait_order=("block", "heal", "dodge", "buff_mark")),
)


def fixed_order_act(f, kinds, v: FixedOrder):
    """First playable kind in the declared order. Returns None only when the
    energy or the hand is genuinely spent -- this line never stops early.

    `offence_cap` is the one exception and it is not a reading of the enemy: it
    caps how many offensive actions the line takes in a turn, whatever it is
    fighting. That is what makes it a HABIT rather than an answer.
    """
    cap = getattr(v, "offence_cap", None)
    odd = (getattr(f, "turn", 1) % 2 == 1)
    wait = getattr(v, "wait_order", None)
    if wait is not None:
        # 势节奏：这回合是不是等待回合 —— 按回合奇偶（attack_on）或按自己的势（attack_at_tempo）
        at = getattr(v, "attack_at_tempo", None)
        turn = getattr(f, "turn", 1)
        every = getattr(v, "block_every", None)
        waiting = ((v.attack_on is not None and odd != (v.attack_on == "odd"))
                   or (at is not None and f.state.get(("me", "tempo"), 0) < at)
                   or (getattr(v, "block_open", False) and turn == 1)
                   or (every is not None and (turn - 1) % every == 0))
        if waiting:
            for kind in wait:
                name = kinds.get(kind)
                if name is not None and f.can_play(name):
                    return name
            return None
        order = v.order
    avoid = set()
    if getattr(v, "alternate", False) and getattr(f, "last_kinds", None):
        avoid.add(max(f.last_kinds, key=f.last_kinds.get))
    if getattr(v, "digit_memo", False):
        code = f.state.get(("them", "mark"), 0)
        if code:
            avoid.add(("attack", "block", "dodge", "heal", "buff_mark")[code - 1])
    for kind in v.order:
        if (cap is not None and kind in ("attack", "buff_mark")
                and f.offences >= cap):
            continue
        if (v.attack_on is not None and kind in ("attack", "buff_mark")
                and odd != (v.attack_on == "odd")):
            continue
        if kind in avoid:
            continue
        name = kinds.get(kind)
        if name is not None and f.can_play(name):
            return name
    return None


@dataclass(frozen=True)
class NumericFingerprint:
    """Reads the health number on screen and answers by band, not by mechanic.

    This is the shortcut the generator's own arithmetic hands out for free.
    Enemy health is `base_atk * randint(*TUNING["hp_<behaviour>"])`, so the
    multiplier IS the behaviour's label: a line that divides the number it can
    see by its own attack and looks the answer up in a table gets the right
    move without any idea what the move is for. It is not expressible in
    `StaticBlind`, which may not read the screen at all -- that restriction is
    what makes `StaticBlind` a clean measure of "ignorant", and it is also what
    left this family unpriced.

    Measured working once already: on charge+pierce+enrage at full=450 a
    threshold classifier gained 10.8 to 21.5 points.

    Not a learner. It never updates the table, never pays for evidence, and
    conditions only on a number printed before the first action -- so it does
    not belong in `AdaptiveProbe`, which is deliberately exempt from the
    shortcut family for having paid.
    """
    cuts: tuple[int, ...]                  # enemy hp / base_atk thresholds
    answers: tuple[StaticBlind, ...]       # one per band, len == len(cuts) + 1

    def __post_init__(self):
        if len(self.answers) != len(self.cuts) + 1:
            raise ValueError("one answer per band, and one more than cuts")
        if list(self.cuts) != sorted(set(self.cuts)):
            raise ValueError(f"cuts must be increasing and distinct: {self.cuts}")

    def resolve(self, enemy_hp: int, base_atk: int) -> StaticBlind:
        mult = enemy_hp / max(base_atk, 1)
        return self.answers[sum(1 for c in self.cuts if mult >= c)]


# The answers a health-band table can give. They are the `StaticBlind` axes a
# mechanic actually punishes: hold a shield (wrong against the piercer), never
# hold one (right against it), spend the dodge on the opening turn (aimed at
# the wind-up), and -- the one this family was missing -- never touch the
# doubler at all.
#
# That fourth answer is not cosmetic. The enrager punishes non-attack actions,
# so the move its health band would sell is "stop marking", and with every
# answer fixed at mark="first" the table could read the band perfectly and
# still be unable to act on it. An audit run that way would have reported
# "the numeric shortcut fails on four mechanics" about an instrument that
# could not express the shortcut.
FINGERPRINT_ANSWERS = (
    StaticBlind("first", True, False, None),
    StaticBlind("first", False, False, None),
    StaticBlind("first", False, True, None),
    StaticBlind("never", False, False, None),
)

# Three bands, so four answers make 64 tables. The cap is a budget, not a
# claim: the full set of signature changes gives six bands on four mechanics
# and 4**6 tables, which at 3,000 trials each is beyond what an audit can
# spend. What is not enumerated is declared in `AUDIT_EXCLUDES`, and the
# witnesses the search itself finds are audited on top.
FINGERPRINT_MAX_CUTS = 2


def fingerprint_cuts(behaviours=None) -> tuple[int, ...]:
    """Where a classifier would put its thresholds, given the rotation in play.

    Derived, not chosen. Enemy health is `base_atk * randint(*hp_<behaviour>)`,
    so at each multiplier there is a SET of behaviours it could be, and the
    useful thresholds are exactly where that set changes. Band starts alone are
    not enough: they find where a behaviour enters and never where one leaves,
    so on the current rotation they produce (4, 6) and lump the pure-charger
    multipliers 10 and 11 in with the mixed band at 6.

    Capped at `FINGERPRINT_MAX_CUTS`, keeping the LOWEST -- and that is a
    measurement, not a preference. Keeping the first and the last instead looks
    obviously better on paper: the high end is where the long-band behaviour is
    alone, an unambiguous signal the low cuts cannot see. Measured over twenty
    worlds it was worse, and not marginally -- (4, 10) gained 0.0 points on
    average against (4, 6)'s 3.0, and 8.0 at most against 15.0.

    The reason is that the unambiguous band is small. On this rotation the
    pure-charger multipliers are 10 and 11 out of a band running 6 to 11, so
    isolating them costs the cut at 6 -- which splits the common case -- to buy
    a signal that fires on a sixth of chargers. With two cuts the common case
    wins. That is an argument about band WIDTHS, and nothing about it was
    visible from the list of where the signatures change.
    """
    names = list(behaviours if behaviours is not None else adventure.BEHAVIOURS)
    bands = {n: TUNING[f"hp_{n}"] for n in names + ["normal"]
             if f"hp_{n}" in TUNING}
    if not bands:
        return ()
    top = max(hi for _lo, hi in bands.values())
    changes, prev = [], None
    for m in range(1, top + 2):
        sig = frozenset(n for n, (lo, hi) in bands.items() if lo <= m <= hi)
        # Both sides must be non-empty: the multiplier below every band is not
        # a threshold between two answers, it is the floor.
        if prev and sig and sig != prev:
            changes.append(m)
        prev = sig
    return tuple(changes[:FINGERPRINT_MAX_CUTS])


def fingerprint_grid(behaviours=None) -> tuple[NumericFingerprint, ...]:
    """Every answer table over the rotation's own cuts."""
    cuts = fingerprint_cuts(behaviours)
    bands = len(cuts) + 1
    return tuple(NumericFingerprint(cuts, combo) for combo in
                 itertools.product(FINGERPRINT_ANSWERS, repeat=bands))


def fingerprint_all_cuts(behaviours=None) -> tuple[int, ...]:
    """Every signature change, uncapped -- the space the SEARCH gets to use."""
    saved = globals()["FINGERPRINT_MAX_CUTS"]
    try:
        globals()["FINGERPRINT_MAX_CUTS"] = 99
        return fingerprint_cuts(behaviours)
    finally:
        globals()["FINGERPRINT_MAX_CUTS"] = saved


def best_fingerprint(run, seed, trials, route, *, information="observable",
                     passes=2):
    """Coordinate ascent over a health-band table, one band at a time.

    Enumeration and search answer different halves of the same question, and
    the split is forced by arithmetic. Measured over twenty worlds, widening
    the enumerated table from three bands to six raised the median gain from
    0.7 points to 4.7 and found one more world in twenty that crosses the 10%
    ceiling -- worth having. It also took the audited line count from 832 to
    53,248, which at 3,000 trials each is about forty hours a seed.

    So the family enumerates what it can afford and this searches the rest. The
    champion it returns is audited as a witness, at the same trial count and on
    the same independent stream as everything else, which is what keeps the
    claim honest: the certificate covers the enumerated tables outright and the
    found table specifically, and says so.
    """
    cuts = fingerprint_all_cuts()
    if not cuts:
        return None, 0.0
    # Four starts, one per uniform table, not one. Coordinate ascent from
    # all-shields alone is a single basin, and the answer a band wants is
    # sometimes the opposite of its neighbour's -- a table that has to change
    # two bands together to pay off is invisible from one start. Four starts
    # cost four times the search and the search is 1.5 minutes a seed.
    best, val, answers = None, -1.0, None
    for opening in FINGERPRINT_ANSWERS:
        start = [opening] * (len(cuts) + 1)
        cand = NumericFingerprint(cuts, tuple(start))
        v = evaluate(run, NONE, route, trials, seed,
                     stream="fingerprint-search", information=information,
                     blind=cand)
        if v > val:
            best, val, answers = cand, v, start
    for _ in range(passes):
        improved = False
        for band in range(len(answers)):
            for answer in FINGERPRINT_ANSWERS:
                if answers[band] == answer:
                    continue
                trial = list(answers)
                trial[band] = answer
                cand = NumericFingerprint(cuts, tuple(trial))
                v = evaluate(run, NONE, route, trials, seed,
                             stream="fingerprint-search",
                             information=information, blind=cand)
                if v > val:
                    answers, best, val, improved = trial, cand, v, True
        if not improved:
            break
    return best, val


def static_act(f, kinds, v: StaticBlind, swung: int = 0, block: bool = None):
    """`swung` is how many attacks this policy has already played THIS turn.

    Counting lives in `play_fight`, not on the Fight: the cap is a property of
    the policy, and putting it in engine state would let a policy that does not
    declare one inherit it."""
    block = v.block if block is None else block
    double_up = f.state[("me", "double")]
    if v.mark == "first" and not double_up and f.can_play(kinds["buff_mark"]):
        return kinds["buff_mark"]
    if ((v.attack_limit is None or swung < v.attack_limit)
            and f.can_play(kinds["attack"])):
        return kinds["attack"]
    if v.mark == "late" and not double_up and f.can_play(kinds["buff_mark"]):
        return kinds["buff_mark"]
    if block and f.can_play(kinds["block"]):
        return kinds["block"]
    return None


def grabs_dodge(f, kinds) -> bool:
    """"Play the dodge whenever you are holding one" -- the ONE definition.

    Two very different opponents want it and neither of them reads the wind-up
    counter, so neither stops being ignorant by taking it:

      the blind family          `StaticBlind.dodge_hand`, a line that knows no
                                mechanic at all;
      the informed-minus-one    `ALL - {charge}`, which understands poison,
                                pierce and enrage and is missing only the
                                counter. This is the dangerous one. A fully
                                blind line can clear the wind-up and still die
                                to an enrager, so its total clear rate says
                                almost nothing about whether charge leaked.

    It matters because `charge_returns_dodge` puts the card in hand at exactly
    the moment the counter is at the top; a policy that spends dodges on sight
    would then answer every wind-up without ever having looked at it.

    Written once, because a second copy would be free to drift -- and the first
    version of this WAS two copies, one in `static_act` and one here.
    """
    return not f.state[("me", "dodge")] and f.can_play(kinds["dodge"])


def play_fight(run, f, know, kinds, heal_at, cap=40, count=False,
               information="oracle", blind=None, enrage_budget=0,
               record=None, dodge_hand=False, belief_cls=None,
               offence_cap=None, act_policy=None, heal_veto=None):
    """One fight to the end. Returns True if it was won.

    `cap` exists because a player who has not worked out the armour literally
    cannot damage it -- the fight does not end, and that is the correct outcome
    to record as a loss."""
    turns = 0
    f.track_seen = False
    belief = (belief_cls or FightBelief)()
    if TUNING["marks"] and information == "observable":
        # 可见签名。规则已经学会的机制，身份直接从屏幕读出来，不必再为
        # 「眼前这只是不是它」付一次探针。
        #
        # 只碰 pierce / enrage / momentum：蓄力槽和毒层本来就是公开计数器，
        # 这三种才是现在唯一要靠挨打才认得出的。
        #
        # 它**不**送规则：`m in know` 是前提，所以第一次遇到某条机制照样要
        # 付探测代价才学得会。省掉的是第二只、第三只怪的重复识别税。
        # counter 也在：它的身份也只能靠挨一下才认出来。漏了它，记号对反击无效，
        # 懂的人每遇到一只新的反击怪都要重付一次探针 —— 而探针按局只便宜一次，
        # 第二只起就是 8 倍 × 考试轮价，直接死。实测漏掉时懂的人 36%，盲线 6%。
        for m in ("pierce", "enrage", "momentum", "counter", "mimic"):
            if m in f.parts and m in know:
                setattr(belief, m, True)
        # 守势的身份本来就在公开槽位上，不需要记号
    # Published immediately, not at `leave`. A recorder that wants to ask "had
    # the policy re-identified the rule YET when this turn went wrong" needs it
    # while the fight is running; handing it over at the end answers a
    # different question.
    if record is not None:
        record.belief = belief
    # An explicit hook rather than a monkeypatch, because what it watches is a
    # measurement this benchmark is ABOUT -- whether the mechanic showed itself,
    # whether a different action was available at that moment, and whether the
    # next chance to act on it was taken. A recorder attached from outside
    # would have to guess the turn boundaries this loop owns.
    if record is not None:
        record.enter(run, f, kinds)
    # One object, two families: an `AdaptiveProbe` is a static line plus rules
    # that fire once it has paid for the evidence. Its correctable state lives
    # here rather than on the policy, which is frozen and shared across trials.
    # A fingerprint resolves to a static line the moment the enemy is on
    # screen, so everything below it is unchanged: it is a table lookup, not a
    # new kind of player.
    if isinstance(blind, NumericFingerprint):
        blind = blind.resolve(f.enemy.hp, run.base_atk)
    order = blind if isinstance(blind, FixedOrder) else None
    probe = blind if isinstance(blind, AdaptiveProbe) else None
    base = None if order is not None else (
        probe.base if probe is not None else blind)
    # The argument covers the informed-minus-one family, the field covers the
    # blind one. Joined here so the behaviour below has a single source.
    grab = dodge_hand or bool(base is not None and base.dodge_hand)
    blocking = base.block if base is not None else None
    if blind is not None and blind.dodge_open and f.can_play(kinds["dodge"]):
        f.play(kinds["dodge"])
    while not f.over() and turns < cap:
        # At the TOP of the turn: the cue was produced at the end of the last
        # one, so this is the first decision after it, and the policy sees it
        # before it acts. A belief that has no use for events ignores this.
        getattr(belief, "observe_events", lambda _f: None)(f)
        swung = 0
        # Both read by the end-of-turn observation. `atk_at_turn_start` is
        # taken before ANY card is played, because momentum's evidence is the
        # attack moving across the whole turn while nothing the player did can
        # be blamed for it -- a per-card `atk_before` would miss a rise that
        # happened at settlement.
        atk_at_turn_start = f.state[("them", "atk")]
        non_attack = 0
        if record is not None:
            # BEFORE any card is played. Asking "was the answer available"
            # after the turn is over asks it of an emptied hand and a spent
            # energy bar, so a player who used the answer correctly and a
            # player who wasted the energy both read as never having had the
            # chance -- the instrument was checking whether the question was
            # answerable only after it had been answered.
            record.before_decision(f)
        while not f.over():
            if (order is None
                    and f.state[("me", "hp")] * 100 < f.max_hp * heal_at
                    and f.can_play(kinds["heal"])
                    and not (heal_veto is not None and heal_veto(f))
                    and not ("mark" in know and hasattr(f, "marked_kind")
                             and f.marked_kind() == "heal")):
                # The heal is decided here rather than in `act`, and the
                # evidence it produces has to be recorded here too. It was not,
                # and the vector engine -- which keys on the stack count rather
                # than on a separate belief -- spotted enragers this line never
                # did: measured, 3.6 points of clear rate on pierce+enrage with
                # healing on, and exactly 0.00 with healing off.
                atk_before = f.state[("them", "atk")]
                f.play(kinds["heal"])
                non_attack += 1
                if information == "observable":
                    belief.observe_play(f, atk_before, "heal")
                continue
            if grab and grabs_dodge(f, kinds):
                c = kinds["dodge"]
            elif act_policy is not None:
                # A policy that decides for itself instead of being handed the
                # reference answer. `rest_policy` is the precedent: a decision
                # the caller owns, threaded through rather than monkeypatched.
                #
                # It exists for the reference LEARNER. `act` applies the correct
                # response the moment a mechanic is in `know`, so a learner
                # built on it goes from "this is a piercer" straight to "so
                # never block" without paying for the experiment that connects
                # them -- and then measures its own answer key.
                c = act_policy(f, know, kinds, belief=belief,
                               information=information)
            elif order is not None:
                c = fixed_order_act(f, kinds, order)
            else:
                c = (static_act(f, kinds, base, swung, blocking)
                     if base is not None
                     else act(f, know, kinds, information=information,
                              offence_cap=offence_cap,
                              belief=belief, enrage_budget=enrage_budget))
            if c is None:
                break
            atk_before = f.state[("them", "atk")]
            if record is not None:
                record.before_play(f, c)
            if f.play(c) is not True:
                break
            if record is not None:
                # Per CARD, not per turn. A mechanic whose effect lands the
                # moment a card is played -- the enrager's attack rising -- is
                # invisible to a turn-level hook: two non-attack cards in one
                # turn are one event to it, and the second one is the first
                # repeat AFTER the first has already shown the rule.
                record.after_play(f, c, atk_before)
            if information == "observable":
                belief.observe_play(f, atk_before, f.deck[c].kind)
            swung += f.deck[c].kind == "attack"
            non_attack += f.deck[c].kind != "attack"
        hp_before = f.state[("me", "hp")]
        block_before = f.state[("me", "block")]
        poison_before = f.state[("me", "poison")]
        charge_before = f.state[("them", "charge")]
        if record is not None:
            record.before_end_turn(f)
        f.end_turn()
        if record is not None:
            record.after_end_turn(f, hp_before, block_before, charge_before)
        if information == "observable" and (
                getattr(belief, "always_observe", False)
                or ({"pierce", "momentum"} & set(know))):
            belief.observe_end_turn(f, hp_before, block_before, poison_before,
                                    charge_before,
                                    atk_before=atk_at_turn_start,
                                    played_non_attack=bool(non_attack))
        # The probe's price is this turn: it held the shield, and it is only
        # allowed to stop because the shield visibly cost it something. Nothing
        # here reads the enemy -- only the player's own health and attack.
        if (probe is not None and probe.stop_blocking_at is not None
                and blocking and block_before > 0
                and hp_before - f.state[("me", "hp")]
                >= probe.stop_blocking_at * f.state[("me", "atk")]):
            blocking = False
        turns += 1
    if count:
        global _TURNS, _FIGHTS
        _TURNS += turns
        _FIGHTS += 1
    if record is not None:
        # An attribute rather than a hook. `kernel.Recorder` fans every
        # ATTRIBUTE LOOKUP out to its children, so `getattr(record, "hook",
        # default)` never takes the default -- it returns a fan-out callable
        # that then fails inside every child that does not define it. Writing
        # the belief where a recorder can read it in `leave` asks nothing of
        # the recorders that do not care.
        record.leave(f, f.won())
    return f.won()


# ------------------------------------------------------------------ route family

@dataclass(frozen=True)
class Route:
    """The decisions that are NOT about which card to play this turn.

    These used to be hard-coded. The family is deliberately explicit so its
    estimate cannot be mistaken for unrestricted optimal play."""
    # Node kinds are visible. Above the threshold the policy deliberately takes
    # a visible elite; below it the policy takes a visible ordinary fight when
    # one exists. Hidden monster behaviour is random only within that kind.
    elite_at: float = 0.60
    heal_at: int = 40            # play a heal below this percent of max
    rest_mode: str = "auto"      # "hp" | "cap" | "auto"
    cleanse_at: int = 6          # poison stacks at which a rest is spent on it
    cap_safe_at: float = 0.45    # only forgo healing above this health fraction
    reward: str = "atk"          # elite reward: "atk" | "hp" | "hurt"
    take: str | None = None      # card taken after an ordinary fight
    # What `take` becomes once a glutton has been met AND worked out. A field
    # rather than a hard-coded None, because "stop taking attack cards" and
    # "take a shield instead" are different claims and only one of them is
    # free. The blind family can express both -- its `take` is a free
    # coordinate -- so the informed family has to be able to as well, or the
    # knowledge gets measured against a handicapped version of itself. That is
    # the same instrument hole the habit gate had, and it is not worth having
    # twice.
    take_glut: str | None = None
    # Deliberately NOT in `GRID`: each budget is a different claim about
    # what the mechanic teaches, so they are optimised and reported apart
    # rather than averaged into one search.
    enrage_budget: int = 0       # enrage stacks this line will spend

    def rest_choice(self, run, know) -> str:
        """Which way to spend a rest.

        Someone who has not worked out the poisoner takes health every time --
        it is the obvious call, and it is the wrong one, which is exactly what
        the knowledge is worth.

        Someone who HAS worked it out decides on the stacks. Keying this on how
        much ceiling had already been lost, which is what it used to do, made
        the informed player blind in precisely the case where the ceiling loss
        was small: at `poison_cap` 0 nothing is ever lost, so the rule never
        fired, stacks ran to 18, and the measured ceiling FELL as the mechanic
        was made gentler. That impossible reading was this rule, not the screen
        -- three separate attempts to fix the screen were chasing the wrong
        thing, and the giveaway had been sitting in plain sight the whole time:
        the anomaly only ever appeared along the poison knob."""
        if "poison" not in know:
            return "hp"
        if self.rest_mode != "auto":
            return self.rest_mode
        lost = run.recoverable_max_hp - run.max_hp
        wants_cap = (run.poison >= self.cleanse_at
                     or lost >= scaled("rest_cap_pct", run.base_max_hp))
        safe = run.hp >= run.max_hp * self.cap_safe_at
        return "cap" if wants_cap and safe else "hp"

    def blind_rest_choice(self, poison, max_hp, recoverable_max_hp,
                          base_max_hp, hp) -> str:
        """The rest decision for a line that knows nothing about the enemy.

        Separate from `rest_choice` on purpose. The blind family was reading the
        normal one with `know=ALL` so that it could react to the anonymous
        counter -- which is legitimate, the counter is the player's own visible
        slot and both menu options are printed -- but it handed the whole
        knowledge set to a function that branches on it. Any knowledge branch
        added to `rest_choice` later would have been inherited in silence.

        So this one takes numbers, not a run and not a knowledge set, and the
        numbers are exactly what is on the player's own screen.
        """
        if self.rest_mode != "auto":
            return self.rest_mode
        wants_cap = (poison >= self.cleanse_at
                     or recoverable_max_hp - max_hp
                     >= scaled("rest_cap_pct", base_max_hp))
        return "cap" if wants_cap and hp >= max_hp * self.cap_safe_at else "hp"

    def take_choice(self, know, met) -> str | None:
        """Which card to take after an ordinary fight.

        The knowledge branch lives here for the same reason poison's lives in
        `rest_choice`: this is the only decision a glutton HAS an answer at.
        Every other mechanic is answered with a card this turn; this one was
        answered three fights ago, and by the time its attack slot is on screen
        there is nothing left to do about it.

        Gated on `met`, not on the world's behaviour list. A policy that has
        not fought one yet is not entitled to act on it, and reading the layers
        ahead would be clairvoyance rather than knowledge -- the difference
        this whole instrument exists to measure.
        """
        if "glutton" in know and "glutton" in met:
            return self.take_glut
        return self.take

    def elite_choice(self, hp, max_hp) -> str:
        if self.reward != "hurt":
            return self.reward
        return "atk" if hp > max_hp * 0.5 else "hp"


GRID = {
    "elite_at": (2.0, 0.50, 0.60, 0.70),          # 2.0 = never SEEK an elite
    # 0 is here so a line that never spends a card on anything but an
    # attack can be EXPRESSED. `play_fight` plays the heal before it asks
    # the policy at all, so without this the "pure attack" blind line
    # still healed and what got priced was "ignores every mechanic but
    # heals anyway" -- the same shape as `combo` being unable to say
    # "never touch the doubler". It costs the informed search nothing:
    # an option a searcher does not want is an option it does not take.
    "heal_at":  (0, 25, 40, 55),
    "rest_mode": ("auto", "hp", "cap"),
    "cleanse_at": (2, 4, 6, 10),
    "cap_safe_at": (0.30, 0.40, 0.50, 0.60),
    "reward":   ("atk", "hp", "hurt"),
    # Only what the game actually offers after an ordinary fight. `buff_mark`
    # was in this list and is not on the reward menu, so the search could settle
    # on a route no player can play -- and an illegal option can only ever
    # inflate the number it produces.
    "take":     (None, "attack", "block", "dodge"),
    # "attack" is in here deliberately. Leaving it out would hard-code the
    # answer into the option set -- "knowing about the glutton means stopping"
    # -- when whether it is worth stopping is the thing being priced. An option
    # a searcher does not want is an option it does not take.
    "take_glut": (None, "attack", "block", "dodge"),
}


# ---------------------------------------------------------------------- one run

def run_once(run, know, route, rng, count=False, information="oracle",
             blind=None, record=None, boss_entry=None, fight_boss=True,
             dodge_hand=False, rest_policy=None, belief_cls=None,
             enrage_budget=None, offence_cap=None, act_policy=None,
             take_policy=None, boss_know=None, heal_veto=None) -> bool:
    """A complete run on the real engine, inside a trial transaction.

    `boss_know`: knowledge set used for the boss phases ONLY; the ordinary
    fights are still played under `know`. This is the counterfactual the
    `boss_entry` comment below asks for -- same arrival state, different
    knowledge at the boss -- priced forward on the engine instead of through
    `mapdp`'s state enumeration. None means the boss is played under `know`.

    Every piece of per-life state is reset on the way in and the caller's state
    is put back on the way out -- see `Run.trial`. This used to be a hand-written
    save list here, and it was missing the poison stacks, so consecutive trials
    inherited each other's and the answer depended on the order candidate routes
    were tried in."""
    # Allocate every layer's randomness before the policy makes a decision.
    # Otherwise taking a deterministic branch in layer i shifts the shared RNG
    # and silently gives every later layer a different blind draw.
    shuffles = [rng.randrange(1 << 30) for _ in run.shuffles]
    node_seeds = [rng.randrange(1 << 30) for _ in run.layers]
    with run.trial(shuffles=shuffles):
        kinds = run.by_kind
        # What this life has actually FOUGHT, accumulated as it goes. Local to
        # the run rather than a field on `Run`, because it is the policy's
        # memory and not the world's state -- putting it on the run would have
        # made it one more thing `TRIAL_STATE` has to remember to restore, and
        # that list has been the wrong length twice.
        met: set[str] = set()
        for i, layer in enumerate(run.layers):
            node_rng = random.Random(node_seeds[i])
            j, kind = run.choose(i, node_rng, False,
                                 run.hp > run.max_hp * route.elite_at)
            if kind == "rest" and adventure.TUNING["auto_rest"]:
                # Registration 12: no rest choice. Every player kind -- informed, blind,
                # cautious, planner, habit -- gets the same automatic resupply; no rest
                # policy is consulted and nothing is scored. A record that wants to see
                # the event implements `auto_rest(run, layer, hp_before, hp_after)`.
                hp0, hp1 = run.auto_resupply()
                hook = getattr(record, "auto_rest", None) if record is not None else None
                if hook is not None:
                    hook(run, i + 1, hp0, hp1)
                continue
            if kind == "rest":
                # A blind line is blind about ENEMIES, not about its own screen.
                # Both rest options are printed, and the stack counter is the
                # player's own visible slot, so "take the other one when that
                # number is high" needs no idea what poison is. Gating it on
                # knowledge made the family strictly weaker than what a model
                # actually plays: measured, forcing health every time gives 0%
                # while letting the route decide gives 20.5% -- and gpt-5.5's
                # clearing life did exactly the latter.
                # A rest can now end the run: an untreated stack settles here,
                # and ignoring that would walk a dead run into the next fight
                # and record its death against the wrong thing.
                # `rest_policy` overrides both. Poison is the one mechanic
                # whose answer is not a card, so pricing it means varying the
                # REST rule while the fight rule is held fixed -- otherwise a
                # rest habit is measured together with whatever play style the
                # route it came attached to happened to have.
                mode = (rest_policy(run) if rest_policy is not None
                        else route.blind_rest_choice(
                            run.poison, run.max_hp, run.recoverable_max_hp,
                            run.base_max_hp, run.hp) if blind is not None
                        else route.rest_choice(run, know))
                if record is not None:
                    record.rest(run, mode)
                run.rest(mode)
                continue
            f = run.fight_at(i, j)
            if not play_fight(run, f, know, kinds, route.heal_at, count=count,
                              belief_cls=belief_cls, offence_cap=offence_cap,
                              act_policy=act_policy, heal_veto=heal_veto,
                              information=information, blind=blind,
                              enrage_budget=(route.enrage_budget if enrage_budget is None
                                             else enrage_budget),
                              record=record, dodge_hand=dodge_hand):
                return False
            run.absorb(f)
            met.update(f.parts)
            # `node.reward`, not `kind == "elite"`. Under the curriculum the
            # test fight is elite-STRENGTH and unavoidable, while loot is
            # assigned separately and its count does not grow with the number
            # of mechanics -- so tying the two together would make every
            # curriculum measurement a measurement of a bigger economy too.
            if adventure.pays_milestone(run.layers[i].nodes[j]):
                run.apply_reward(route.elite_choice(run.hp, run.max_hp))
            else:
                # `blind` takes what its route says, every time, and that is
                # the whole point: the glutton's answer is prospective, so a
                # line that never worked it out has nothing to react WITH. The
                # informed line branches, which is what the knowledge is worth.
                # `take_policy` is the build hook, same shape as `rest_policy`
                # and `act_policy`: a decision the caller owns. It sees the run,
                # what is known and what has been MET -- never the layers ahead.
                pick = (take_policy(run, know, met) if take_policy is not None
                        else route.take if blind is not None
                        else route.take_choice(know, met))
                if pick:
                    run.deck_list.append(kinds[pick])
        if count:
            global _REACHED_BOSS
            _REACHED_BOSS += 1
        # `boss_entry` is called INSIDE the trial, on the state a player
        # actually arrives in. It exists so the boss can be examined as a
        # counterfactual: the same entry state replayed under two knowledge
        # sets. Comparing `ALL` runs to `ALL-m` runs end to end does not do
        # that -- the two never reach the boss in the same condition, so the
        # difference measured at the boss is partly a difference in who got
        # there. Measured: the mechanic the boss examines scored HIGHER than
        # one it does not, which is backwards and is that selection.
        if boss_entry is not None:
            boss_entry(run)
        if not fight_boss:
            return True
        # Two phases, and nothing between them: no rest, no reward. The run's
        # health, ceiling, poison and spent cards carry; the hand, energy,
        # block, dodge and the wind-up and rage counters do not.
        bknow = know if boss_know is None else boss_know
        for bf in run.boss_fights():
            # `act_policy` / `offence_cap` threaded exactly as for ordinary fights:
            # without them the boss was played by the built-in `act`, so a
            # caller-supplied policy (the probing learner, the calibration
            # planner) never actually met the boss it was being scored on.
            if not play_fight(run, bf, bknow, kinds, route.heal_at, count=count,
                              belief_cls=belief_cls, offence_cap=offence_cap,
                              act_policy=act_policy, heal_veto=heal_veto,
                              information=information, blind=blind,
                              enrage_budget=(route.enrage_budget if enrage_budget is None
                                             else enrage_budget), record=record,
                              dodge_hand=dodge_hand):
                return False
            run.absorb(bf)
        return True


_STREAM_SALT: dict[str, int] = {}


def _trial_rng(seed, stream, trial) -> random.Random:
    """Stable, namespaced randomness with no overlapping integer bit fields.

    Seeded from an int, not a string: `Random(str)` hashes its argument, and at
    68k constructions per screen that was 10% of the total. The string's job was
    to keep streams from colliding, which a per-stream salt does just as well --
    and the salt is derived from the name, so the mapping stays stable across
    processes (`hash()` of a str is not)."""
    salt = _STREAM_SALT.get(stream)
    if salt is None:
        salt = _STREAM_SALT[stream] = int.from_bytes(
            hashlib.blake2b(f"{ENGINE_VERSION}:{stream}".encode(),
                            digest_size=8).digest(), "big")
    return random.Random((salt ^ (seed * 0x9E3779B97F4A7C15)) + trial * 0x100000001B3)


def evaluate(run, know, route, trials, seed, stream="route-search",
             *, information, blind=None, dodge_hand=False) -> float:
    """Clear rate for one (run, knowledge, route).

    Common random numbers: the RNG is keyed on the trial index, so two routes
    being compared draw from the same stream. That is what makes the comparison
    paired -- it does not guarantee identical card sequences, because the two
    routes consume randomness at different points, but it removes most of the
    variance from the difference.

    `stream` separates the samples the search CHOOSES on from the samples the
    result is REPORTED on. Picking the best of forty candidates on one set of
    trials and then quoting that same number is a winner's curse: the winner is
    partly whichever candidate got lucky, so the quoted rate is biased upward.
    The reported figure is re-measured on a disjoint stream.
    `information` is REQUIRED here and on `batch.run_trials`, because the
    two used to default to "oracle" and "observable" respectively and
    comparing them silently read as an engine disagreement: measured, that
    mistake produced a 3.5-8.2 point 'divergence' that was chased into the
    armour branch twice before the modes were checked. Only these two
    public entry points are locked; `best_route`, `run_once` and
    `play_fight` below still carry defaults, so a caller that reaches past
    these two can still pick a mode by accident.
    """
    wins = 0
    for t in range(trials):
        wins += run_once(run, know, route, _trial_rng(seed, stream, t),
                         information=information, blind=blind,
                         dodge_hand=dodge_hand)
    return wins / trials


# ------------------------------------------------------------- route optimisation

def best_route(run, know, seed, trials=60, passes=2, start=None,
               information="oracle", blind=None) -> tuple[Route, float]:
    """Coordinate ascent over `GRID`, started from the best of `SCREEN_ROUTES`.

    Not a proof of optimality: it searches a named family and can stop at a
    local optimum. The returned value is measured on a stream that was not used
    to choose the route.

    The start point used to be `Route()` alone, which put a second
    local-optimum problem on top of the one the route bank already had: the
    bank decided which worlds looked good, and a single fixed start decided
    whether the expensive pass could recover from that. Pricing the bank first
    makes the two the same instrument, and makes this search a strict superset
    of the old one -- `Route()` is in the bank, so the old start is still
    considered. Pass `start` explicitly to pin it.
    """
    if start is None:
        start = max(((evaluate(run, know, r, trials, seed,
                               information=information, blind=blind), i, r)
                     for i, r in enumerate(SCREEN_ROUTES)))[2]
    route, val = start, evaluate(run, know, start, trials, seed,
                                 information=information, blind=blind)
    for _ in range(passes):
        improved = False
        for field, options in GRID.items():
            for opt in options:
                if getattr(route, field) == opt:
                    continue
                cand = replace(route, **{field: opt})
                v = evaluate(run, know, cand, trials, seed,
                             information=information, blind=blind)
                if v > val:
                    route, val, improved = cand, v, True
        if not improved:
            break
    # Re-measured on a fresh stream -- see `evaluate`. The search's own best
    # score is not a usable estimate of the winner's rate.
    return route, evaluate(run, know, route, trials, seed,
                           stream="route-report", information=information,
                           blind=blind)


# ------------------------------------------------------------------- aggregation

def _z_one_sided(alpha: float) -> float:
    """Normal critical value for a ONE-sided tail of `alpha`.

    Every claim the audit makes points one way -- an ignorant line is under a
    ceiling, an informed line is over a floor -- so a two-sided critical value
    spends half the alpha guarding a direction nobody asked about, and the
    conservatism shows up as worlds refused for a reason that is not about the
    world."""
    return _z_for(2 * alpha)


def _z_for(alpha: float) -> float:
    """Two-sided normal critical value. Bisection because the inverse normal is
    not in the standard library and one number at import time does not justify
    a dependency."""
    lo, hi = 0.0, 8.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson(k, n, z=1.96) -> tuple[float, float]:
    """Wilson score interval -- the normal approximation is wrong at the ends,
    and the ends are exactly where these numbers live (0% and 90%+)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


# ---------------------------------------------------------------- the screen

@dataclass(frozen=True)
class Targets:
    """What a generated run has to be, stated as probabilities.

    This is the inversion. The old screen pinned ONE number -- the informed
    clear rate -- and re-rolled until it landed in a band. Everything else was
    free, and "free" meant the screen quietly compensated every attempt to make
    a mechanic matter: raise the punishment and it hands you a softer run, so
    the half-informed line ends up back where it was. Pinning the partials too
    removes the compensation, because a run that lets a partial through is
    simply not accepted.

    The enemy mix, the health numbers, the layer structure and the node layout
    are therefore OUTPUTS of the search, not inputs. Which is the point: what a
    run must contain is decided by what it has to discriminate."""
    informed: float = 0.70       # floor: a player who worked everything out
    partial: float = 0.10        # any player missing exactly one mechanic
    turns: float = 8.0           # mean turns per fight -- fights stay short

    # These are deliberately one-sided constraints. Once informed play clears
    # reliably, making it still easier is good; once a partial player is below
    # the ceiling, making that knowledge gap still sharper is also good.
    # `reach_boss` is measured below, but it is not a target: dying cheaply in
    # the adventure is a legitimate learning outcome, not a generation defect.


def _measure(run, know, trials, seed, route, stream="screen-report",
             information="oracle", blind=None):
    wins = turns = fights = reached = 0
    for t in range(trials):
        rng = _trial_rng(seed, stream, t)
        w, tt, ff, rr = _one(run, know, route, rng, information=information,
                             blind=blind)
        wins += w; turns += tt; fights += ff; reached += rr
    return (wins / trials, (turns / fights if fights else 0.0),
            reached / trials)


def _one(run, know, route, rng, information="oracle", blind=None):
    """`run_once` plus the turn counter the screen needs."""
    global _TURNS, _FIGHTS, _REACHED_BOSS
    _TURNS = _FIGHTS = _REACHED_BOSS = 0
    w = run_once(run, know, route, rng, count=True,
                 information=information, blind=blind)
    return w, _TURNS, _FIGHTS, _REACHED_BOSS


_TURNS = _FIGHTS = _REACHED_BOSS = 0

# The screen has to judge every knowledge state at ITS best, not at one shared
# guess. Judging the informed player by a route that is not their best rejects
# runs that are fine, and judging a partial player the same way accepts runs
# that they would in fact clear. A full coordinate ascent per candidate is far
# too slow for a screen, so this is a small spread of sensible routes. Route
# selection and reporting use separate streams so the screen does not price a
# world using the lucky sample that selected its route.
# Built, not hand-written. `_best_of` takes the MAX over this bank, so its
# answer is a lower bound on what the policy family can reach: a bank that
# misses a world's shape does not report "this world is hard", it reports
# "these routes are wrong" -- and stage 1 was spending that confusion as if it
# were evidence, both to rank candidates and to prune 89% of them.
#
# Measured on the four routes this replaced: they underestimated the
# full-knowledge rate by 28.8 points and the worst single-mechanic partial by
# 22.0 on held-out worlds. The direction matters and it is not the same on the
# two sides. A low reading on the full-knowledge side cannot reject a world --
# it is a lower bound, so it only ever says the bank failed. A HIGH reading on
# the shortcut side is a concrete counterexample and can reject immediately.
#
# Construction: coordinate ascent on 48 worlds x 4 knowledge states, the 69
# distinct champions pooled, then a bank chosen greedily to minimise the
# shortfall against that pool -- selected on half the worlds, scored on the
# other half. Held-out shortfall by bank size:
#
#     bank     inf    worst
#        4   28.8%    22.0%    <- what this replaced
#        1    9.9%     6.7%    <- one well-chosen route beats all four
#        8    4.3%     1.8%
#       12    3.1%     0.9%    <- here
#       16    1.5%     0.5%
#
# Twelve is where the residue drops under the sampling noise of the estimate it
# feeds (a 30-trial rate has a 9.1 point standard deviation), so a larger bank
# buys precision the trials cannot deliver. `Route()` is kept as a thirteenth
# so that ascent started from this bank is a strict superset of ascent started
# from the old default, and no caller can regress.
#
# It is FITTED to what the current mechanics reward. Rebuild it when the
# rotation or the tuning changes -- nothing checks that for you.
SCREEN_ROUTES = (
    Route(),
    Route(elite_at=0.5, heal_at=55, cleanse_at=6, cap_safe_at=0.3,
          reward="hurt", take="attack"),
    Route(elite_at=2.0, heal_at=55, cleanse_at=4, cap_safe_at=0.3,
          reward="atk", take="attack"),
    Route(elite_at=0.5, heal_at=55, cleanse_at=6, cap_safe_at=0.3,
          reward="atk", take="attack"),
    Route(elite_at=0.5, heal_at=55, cleanse_at=6, reward="hp", take="attack"),
    Route(elite_at=0.6, heal_at=55, cleanse_at=2, cap_safe_at=0.3,
          reward="hurt", take="dodge"),
    Route(elite_at=0.6, heal_at=55, cleanse_at=2, cap_safe_at=0.3,
          reward="atk", take="attack"),
    Route(elite_at=0.5, heal_at=55, rest_mode="hp", cleanse_at=6,
          reward="atk", take="attack"),
    Route(elite_at=2.0, heal_at=55, cleanse_at=2, cap_safe_at=0.3,
          reward="hp"),
    Route(elite_at=0.6, heal_at=55, cleanse_at=2, cap_safe_at=0.3,
          reward="hp", take="attack"),
    Route(elite_at=0.6, heal_at=55, cleanse_at=6, cap_safe_at=0.3,
          reward="hurt"),
    Route(elite_at=0.6, heal_at=40, cleanse_at=6, reward="atk",
          take="attack"),
    Route(elite_at=0.5, heal_at=40, cleanse_at=6, reward="atk"),
)


# Two routes, not the whole bank: stage 1 ranks candidates, it does not price
# them. The shapes that matter for a blind line are "decline every elite and
# race" and "take the default", and the eight in-fight variants cover the rest.
BLIND_STAGE1_ROUTES = (Route(), Route(elite_at=2.0, heal_at=55, cleanse_at=2),
                       Route(heal_at=0))   # the pure-attack line


def _blind_best_of(run, trials, seed, stream="screen-blind1"):
    """Cheap blind ceiling for stage 1.

    Without this the shortlist is chosen knowing nothing about shortcuts, so a
    world that genuinely resists them can be eliminated before the precise
    screen ever sees it -- the expensive check would then only ever be applied
    to candidates that were selected for the wrong thing.
    """
    priced = [(_measure(run, NONE, trials, seed, r,
                        stream=f"{stream}:select", information="observable",
                        blind=v)[0], (v, r))
              for v in STATIC_GRID for r in BLIND_STAGE1_ROUTES]
    v, r = max(priced, key=lambda x: x[0])[1]
    return _measure(run, NONE, trials, seed, r, stream=f"{stream}:report",
                    information="observable", blind=v)[0]


# The lines a model can run without understanding anything: always play the
# doubler, always attack, never block, never dodge. Named by the user as the
# thing that must not clear, and measured here rather than assumed.
#
# Stage 1 is allowed to reject on THIS side and not on the other, and the
# asymmetry is not a policy choice -- it is what a max over a finite bank can
# support. `_best_of` returns a lower bound on what the family can reach, so:
#
#   full knowledge   a low reading says the bank failed, not that the world is
#                    hard. It cannot reject. It may only rank.
#   shortcut         a HIGH reading is a concrete counterexample. Some line
#                    already clears more than the target allows, and no further
#                    search makes that line worse. It rejects, exactly.
#
# The cascade this replaced had the veto on the wrong side: it pruned 89% of
# candidates on the full-knowledge reading, measured 22.7 points low.
#
# Four, chosen greedily against the full 72-combination blind family (24 static
# variants x 3 routes) on half of 48 worlds and scored on the other half:
#
#     lines   shortfall   of the worlds whose true blind line clears >10%,
#                         this many are caught
#         1       3.5%    72%
#         2       2.6%    89%
#         3       1.6%    94%
#         4       1.5%    94%      <- here, at 4 evaluations instead of 72
#
# The first line alone is the one named above, and it is the strongest.
GENERIC_LINES = (
    (StaticBlind("first", False, False, None), Route()),
    (StaticBlind("first", True, False, None), Route()),
    (StaticBlind("first", False, False, None),
     Route(elite_at=2.0, heal_at=55, cleanse_at=2)),
    (StaticBlind("first", False, True, None), Route()),
)


# Trials multiplier for the confirmation pass. A point estimate is not a
# counterexample: 3 clears in 24 reads 12.5% and its 95% Wilson interval runs
# from 4.3% to 31.0%, so a bare `> 0.10` rejects worlds whose true rate is 5%
# about as happily as worlds whose true rate is 30%. At 8x, 16/192 reads 8.3%
# and 26/192 reads 13.5% with a lower bound of 9.4% -- the line has to be
# genuinely over before the interval clears the target.
CONFIRM_MULT = 8

OVER, UNDECIDED, CLEAR = "over", "undecided", "clear"


def _confirmed_over(run, target, trials, seed, *, know, lines, stream):
    """Three-valued: does some line in `lines` clear more than `target`?

    `lines` is a sequence of (blind_variant_or_None, route) pairs.

    Returns (verdict, rate, witness):

      OVER       the confirmation pass on an independent stream puts the Wilson
                 lower bound above `target`. A reliable counterexample; the
                 caller may reject on it.
      UNDECIDED  a cheap line read above `target` and the interval straddles it.
                 Not a rejection. The fine screen decides.
      CLEAR      nothing in `lines` read above `target`. This is NOT a proof of
                 safety -- `lines` is a finite bank and its max is a LOWER bound
                 on what the family can reach. It only means this bank found
                 nothing, which is the whole reason `inf` may not reject.

    The confirmation prices the specific line that tripped the cheap pass, on a
    stream disjoint from the one that selected it. Selecting the max of a bank
    and then quoting that same number is the winner's curse the route search
    already separates streams to avoid, and here it lands directly on the
    figure a rejection is made from.
    """
    best, witness = -1.0, None
    for blind, route in lines:
        v = evaluate(run, know, route, trials, seed, stream=f"{stream}:select",
                     information="observable", blind=blind)
        if v > best:
            best, witness = v, (blind, route)
    if best <= target:
        return CLEAR, best, None
    n = trials * CONFIRM_MULT
    blind, route = witness
    rate = evaluate(run, know, route, n, seed, stream=f"{stream}:confirm",
                    information="observable", blind=blind)
    lo, _hi = wilson(round(rate * n), n)
    # `best`, not `rate`, goes back for ranking: every candidate is ranked on
    # the same cheap scale, and only the ones that trip the target pay for a
    # confirmation. Mixing the two would rank confirmed candidates on a
    # different instrument from unconfirmed ones.
    return (OVER if lo > target else UNDECIDED), best, witness


def _generic_ceiling(run, trials, seed, stream="screen-generic"):
    """Best of the named generic lines. A lower bound on the blind ceiling."""
    return max(evaluate(run, NONE, r, trials, seed, stream=stream,
                        information="observable", blind=v)
               for v, r in GENERIC_LINES)


def _best_of(run, know, trials, seed, stream="screen", information="oracle"):
    priced = [(_measure(run, know, trials, seed, r,
                        stream=f"{stream}:select", information=information), r)
              for r in SCREEN_ROUTES]
    route = max(priced, key=lambda x: x[0][0])[1]
    return _measure(run, know, trials, seed, route,
                    stream=f"{stream}:report", information=information)


SHORTLIST = 8


def _screen_score(inf, worst, turns, reach, targets):
    gap = inf - worst
    # The benchmark wants a cliff, not a prescribed death location. Informed
    # clear rate is a floor and partial clear rate an upper bound; `reach` is
    # intentionally absent, and remains in the returned diagnostics only.
    misses = (max(0.0, targets.informed - inf)
              + max(0.0, worst - targets.partial)
              + max(0.0, turns - targets.turns) / targets.turns)
    return gap - 2.0 * misses


# How many standard deviations of slack the stage-1 bound carries.
#
# Measured, not chosen: three seeds x 150 candidates at 2.0, 1.0, 0.5 and 0.0
# standard deviations all produced a shortlist and a champion identical to the
# exhaustive pass. One is kept rather than zero because the bound consumes a
# NOISY estimate of `inf` -- the arithmetic is exact, the input is not, and
# twelve agreeing cases do not establish that an unlucky estimate can never
# drop a candidate that deserved the expensive pass. At one sd the cascade
# skips 57-66% of candidates against 55% at two.
_SLACK_MULT = 1.0


def screen_bound(inf, turns, targets=Targets(), slack=0.0):
    """The best score this candidate could still reach, before the rest is measured.

    NO LONGER IN THE SEARCH PATH, and the reason is worth keeping.

    The arithmetic below is right: `_screen_score` is strictly decreasing in
    `worst`, so substituting zero bounds the score from above. What was wrong is
    the input. `inf` arrives from `_best_of`, a max over a finite route bank,
    which is a LOWER bound on what the policy family can reach -- so a low
    reading never meant "this world is hard", only "these routes are wrong".
    Measured against coordinate ascent, the four-route bank this used read 22.7
    points low, and the candidates it read lowest were the ones that needed an
    unusual route -- exactly the worlds worth keeping. The bound was exact with
    respect to the unmeasured terms and meaningless with respect to the measured
    one, and the "EXACT" this docstring used to claim covered only the first.

    `make_run` now rejects on the shortcut side, where a high reading from the
    same kind of lower bound IS a counterexample. See `GENERIC_LINES`.

    Deliberately not a bar on `inf`. Two different fixed bars have broken this
    search by short-circuiting the partial constraints, and both times the
    giveaway was an impossible reading. A bound is not a bar: it prunes only
    against candidates already priced in full.

    `slack` widens the bound to absorb the sampling error in `inf` itself.
    Stage 1 measures it on few trials, so an unlucky estimate could otherwise
    eliminate a candidate that deserved the expensive pass.
    """
    return ((inf + slack)
            - 2.0 * (max(0.0, targets.informed - inf - slack)
                     + max(0.0, turns - targets.turns) / targets.turns))


# The route bank and the generic lines are FITTED objects: they were chosen by
# running coordinate ascent on worlds built from a particular rotation under a
# particular tuning, and they are only as good as that fit. Change the rotation
# or the punishment shapes and the bank is a set of answers to a different
# question -- which reads, from the outside, exactly like a world that got
# harder.
#
# So the fit is declared, and two things enforce it. The rotation is checked
# against what the bank was built on, loudly, because nothing else would notice.
# And the bank's own contents are hashed into the world-cache key, because a
# rebuilt bank selects different worlds and the old entries are answers to the
# old instrument. Bumping `SCREEN_VERSION` by hand does the same job only as
# long as somebody remembers to.
ROUTE_BANK_FITTED_TO = ("poison", "charge", "pierce")

def check_route_bank(behaviours=None):
    """Raise if the bank was fitted to a different rotation than is in play."""
    current = tuple(behaviours if behaviours is not None
                    else adventure.BEHAVIOURS)
    if current != ROUTE_BANK_FITTED_TO:
        raise RuntimeError(
            f"route bank was fitted to {ROUTE_BANK_FITTED_TO} and the rotation "
            f"is {current}. Rebuild it (coordinate ascent on a sample of "
            f"worlds, greedy selection against the pooled champions), set "
            f"ROUTE_BANK_FITTED_TO, and let the fingerprint invalidate the "
            f"world cache. Screening on a stale bank underestimates both sides "
            f"and the full-knowledge side by far more.")


class NoQualifyingWorld(RuntimeError):
    """No candidate met the hard conditions, so this seed has no world.

    Raised rather than returning the best near-miss. The near-miss exists and is
    useful, but only as a diagnostic: a `make_run` that quietly returns one turns
    the hard conditions back into a ranking, which is the failure this screen was
    rebuilt to stop. `diagnostic_search` returns it, flagged.
    """


# Three budgets, three jobs, and conflating any two of them is how a statistical
# margin gets mistaken for a design result.
#
#   triage   `trials`        rank, and reject on a confirmed counterexample
#   refine   x REFINE_MULT   optimise routes, rank the shortlist. NOT a verdict.
#   audit    AUDIT_TRIALS    the only measurement that certifies anything, taken
#                            on a stream that chose nothing
#
# AUDIT_TRIALS is large on purpose. Certifying "no ignorant line clears more
# than 10%" from n samples means the OBSERVED rate has to sit well under 10%,
# and how far under is a function of n alone:
#
#     n= 300   observed must be <= 4.3%
#     n= 900   observed must be <= 6.7%
#     n=1200   observed must be <= 7.2%
#     n=2000   observed must be <= 7.8%
#
# Auditing at 300 does not enforce a 10% line; it enforces a 4.3% line while
# still calling it 10%, and every world refused by the difference gets read as
# a mechanic that does not work. That is the same misdiagnosis as a route bank
# that reads 22.7 points low, arriving through statistics instead of search.
REFINE_MULT = 10
AUDIT_TRIALS = 3000

# The claim is a CONJUNCTION and the alpha has to cover all of it. Per audited
# world: one informed lower bound and `IGNORANT_LINES` upper bounds. Across the
# shortlist: `SHORTLIST` worlds, any of which may be the one accepted. Testing
# eight worlds at 95% each and keeping whichever passes is a 34% chance of
# keeping one that should not have passed -- the same winner's curse the route
# search separates streams for, one level up.
#
# Simultaneous INTERVALS, not hypothesis rejection: Holm is uniformly more
# powerful for the rejection side and does not produce simultaneous confidence
# bounds, which is what a conjunction of "this rate is under the target" needs.
# Bonferroni is the right tool for this side; Holm belongs on triage's veto if
# that ever tests more than one line per decision.
# The DECLARED family. Auditing the champion the search picked proves something
# about that champion and nothing about the family it was picked from: if the
# blind ceiling is a max over 312 lines and one is re-priced, the other 311 are
# uncertified, and the search can have picked the wrong one. So the audit
# enumerates the family instead, and the claim it supports is exactly
#
#   "within this declared family, no line clears more than the target"
#
# and never "this world has no shortcut". The gap between those two sentences
# is the edge of what the benchmark can say.
#
# The routes are the fitted bank, so the family moves when the bank moves --
# which is correct, and the fingerprint carries it.
def blind_family():
    """Every line that plays without understanding, in ONE place.

    The four world gates measured "strongest fixed habit" as a max over
    `STATIC_GRID` alone -- 24 of the 93 lines that exist. The missing ones are
    not decoration: the strongest habit on both confirmed worlds is a
    FINGERPRINT table, which reads the printed health and looks the answer up,
    and it beat the best static line by 2.1 and 0.9 points. A shortcut the
    instrument cannot express is a shortcut the instrument will certify.

    `AUDIT_FAMILY` already enumerated these for `screen_precise`; the search
    pipeline was reading a different, smaller list. Same defect as the habit
    groups that once missed the strongest static line, one layer up.
    """
    return (tuple(STATIC_GRID) + tuple(fingerprint_grid())
            + tuple(NEVER_HOLD) + tuple(ONE_SWING) + tuple(RHYTHM)
            + (tuple(TEMPO_LINES) if TUNING["tempo"] else ())
            + (tuple(WARD_LINES) if "ward" in adventure.BEHAVIOURS else ()))


# The economies a blind line is allowed to play under. The gate used to run
# every one of them on a bare `Route()`, whose `take` is None -- so a fixed
# habit finished the run on 18 cards while the informed line it was compared
# against finished on 28, and the model itself is offered a card after every
# ordinary fight. Measured on the two worlds confirmed under the old gate, the
# strongest habit went from 7.8% to 24.1% and from 2.4% to 15.2% once it was
# allowed to take a card too: both would have failed the 10% bar.
#
# `take` is the dimension that carries it, so the cheap version crosses only
# that; the confirmation stage crosses the whole route family, exactly as
# `AUDIT_FAMILY` already did for `screen_precise`.
BLIND_ECONOMIES = (None, "attack", "dodge", "block")


def blind_gate(full: bool = False):
    """(line, route) pairs the "strongest fixed habit" gate must maximise over."""
    # The plain routes are NOT optional in the full version. Handing a fixed
    # habit the informed line's tuned routes is not the same as giving it a
    # fair economy: those carry a `heal_at` and a `cleanse_at` chosen for
    # someone who reads the enemy. Measured, the best habit under bank4's
    # routes was 3.8% and under a bare route with `take="attack"` it was 24.1%
    # -- on the same world. The family has to contain both.
    plain = tuple(Route(take=t) for t in BLIND_ECONOMIES)
    routes = (plain + tuple(SCREEN_ROUTES)) if full else plain
    return tuple((v, r) for v in blind_family() for r in routes)


def _audit_family():
    """Every declared ignorant line, enumerated from what is in play.

    Nothing here is a literal count. The rotation decides how many partial
    policies there are and the fitted bank decides how many routes each gets,
    so adding enrage to the rotation widens the family and the alpha with it,
    without anyone editing a number.
    """
    return tuple(
        [(NONE, variant, route)
         for variant in STATIC_GRID for route in SCREEN_ROUTES]
        + [(NONE, table, route)
           for table in fingerprint_grid() for route in SCREEN_ROUTES]
        + [(ALL - {m}, None, route)
           for m in MECHANICS for route in SCREEN_ROUTES])


AUDIT_FAMILY = _audit_family()

# What the certificate does NOT cover. Written down because an unlisted omission
# reads exactly like coverage, and the difference between "no line in this
# family clears" and "this world has no shortcut" is the whole credibility of
# the benchmark.
AUDIT_EXCLUDES = {
    "adaptive-probe":
        "DELIBERATE. `AdaptiveProbe` blocks once, takes an anomalous hit, and "
        "stops blocking -- it paid a turn and a chunk of health to learn "
        "something. That is the skill acquisition this benchmark exists to "
        "measure, and requiring an accepted world to defeat it would require an "
        "accepted world to be one in which learning also fails.",
    "fingerprint tables the search did not find":
        "GAP, and a measured one. The enumerated family is the 64 tables over "
        "the two lowest cuts; the full signature-change set gives six bands and "
        "4,096 tables, which is 53,248 audited lines and about forty hours a "
        "seed. What the cap gives up was measured over twenty worlds: the "
        "median gain falls from 4.7 points to 0.7 and one world in twenty "
        "stops crossing the 10% ceiling. `best_fingerprint` searches the full "
        "space and its champion is audited as a witness, so the residue is not "
        "'tables nobody enumerated' but 'tables coordinate ascent missed from "
        "the all-shields start'. The maximum gain was 22.0 points at every cut "
        "set containing 6, so the worst case is reached by the enumerated part.",
    "out-of-family routes":
        "GAP, narrowed. `blind_ceiling` and the partial searches optimise over "
        "the whole of `GRID` while the family enumerates the 13-route fitted "
        "bank, so either can find a line the family does not contain. Those "
        "lines are now carried to the audit as witnesses -- up to "
        "`MAX_WITNESSES`, with the alpha reserved whether they turn up or not "
        "-- so what remains uncovered is routes that NOTHING found: not in the "
        "bank, not a search champion, not a triage reading over the target."
}

# One informed claim, not thirteen: the fine screen has already picked the route
# and the audit re-prices THAT one on a fresh stream, which is unbiased for the
# route it was handed. Taking a max over thirteen and bounding it from below
# would put the selection back inside the bound, in the direction that helps the
# world pass.
# Bonferroni needs the error rates to SUM to alpha; it does not need them equal.
# Splitting 0.05 evenly over 352 claims makes the single informed claim carry a
# penalty as if it were 352 claims, and the world then fails on a threshold that
# has nothing to do with the world. So the informed side gets a fifth of the
# budget for its one claim and the ignorant family shares the rest:
#
#                            z      informed floor    ignorant ceiling
#     two-sided, uniform   3.805         73.2%              7.9%
#     one-sided, uniform   3.629         73.1%              8.0%
#     one-sided, split     2.326/3.686   72.0%              8.0%
#
# All of these are valid. The last one is the least conservative that still
# sums to 0.05, which matters because every point of over-conservatism here
# reads downstream as a mechanic that does not discriminate.
_ALPHA = 0.05
_ALPHA_INFORMED = 0.01
_ALPHA_IGNORANT = _ALPHA - _ALPHA_INFORMED
# Room in the alpha budget for lines the SEARCH finds that the declared family
# does not contain. `blind_ceiling` optimises over the whole of `GRID` while the
# family enumerates the fitted bank, and triage can read a line over the target
# without confirming it -- so without this there is a live path where the fine
# screen sees a dangerous route, triage declines to reject on it for want of
# samples, the audit skips it for not being in the family, and the world passes
# carrying the exact line that was found and then dropped.
#
# Reserved rather than counted: the number of witnesses is data, and an alpha
# that moves with the data is not an alpha. The budget is paid whether or not
# the witnesses turn up.
MAX_WITNESSES = 16
_AUDIT_CLAIMS = len(AUDIT_FAMILY) + MAX_WITNESSES + 1
_Z_INFORMED = _z_one_sided(_ALPHA_INFORMED)
_Z_IGNORANT = _z_one_sided(
    _ALPHA_IGNORANT / (len(AUDIT_FAMILY) + MAX_WITNESSES))
_BONFERRONI_Z = _Z_IGNORANT        # the one that guards the dangerous side

# Only the top-ranked candidate is audited. Auditing all eight and keeping
# whichever passes needs alpha spread over eight times as many claims, which
# costs more threshold than the extra chances are worth: measured at n=3000,
# rank-1-only certifies an observed 7.9% and all-eight only 7.2%, for an eighth
# of the simulations. Testing candidates until one passes, without paying for
# it in alpha, is the same error one level up from a bank that reads low.
AUDITED_CANDIDATES = 1


def _merge_witnesses(existing, found):
    """Dedupe against the declared family and against each other, then cap.

    Capped at `MAX_WITNESSES` because the alpha was reserved for that many. A
    silent truncation would be the wrong failure, so it is not silent: going
    over raises rather than dropping the seventeenth line, which is the one most
    likely to be the interesting one.
    """
    known = set(AUDIT_FAMILY)
    out = list(existing)
    seen = set(out)
    for line in found:
        if line in known or line in seen:
            continue
        seen.add(line)
        out.append(line)
    if len(out) > MAX_WITNESSES:
        raise RuntimeError(
            f"{len(out)} out-of-family witnesses but alpha was reserved for "
            f"{MAX_WITNESSES}. Raise MAX_WITNESSES (and pay for it in the "
            f"threshold) rather than dropping one.")
    return tuple(out)


def audit(run, seed, inf, worst, trials, audit_trials=None):
    """Price the declared family AND the search's own witnesses, once.

    Returns (informed_rate, worst_ignorant_rate, n).

    ONE pass, fixed n, no retry. Drawing more samples when the interval
    straddles the target, until it lands on the wanted side, is not a longer
    measurement -- it is a different and much weaker test, and the code that
    does it looks identical to the code that does not. Undecided is a verdict.

    Falls back to the caller's estimates when no witness was recorded, so a
    stubbed `screen_precise` still behaves.
    """
    w = getattr(run, "screen_witness", None)
    if w is None:
        return inf, worst, trials
    n = AUDIT_TRIALS if audit_trials is None else audit_trials
    know, variant, route = w["informed"]
    informed = evaluate(run, know, route, n, seed, stream="audit:informed",
                        information="observable", blind=variant)
    lines = AUDIT_FAMILY + tuple(getattr(run, "audit_witnesses", ()))
    ignorant = max(
        evaluate(run, k, r, n, seed, stream=f"audit:ignorant-{i}",
                 information="observable", blind=v)
        for i, (k, v, r) in enumerate(lines))
    return informed, ignorant, n


def certified(inf, worst, trials, targets=Targets()):
    """Do the measured rates CERTIFY the world, or merely suggest it?

    The two sides need opposite ends of the interval, and having that backwards
    is how a screen ships a world whose shortcut it never ruled out:

      inf    a reliable solution must exist  ->  Wilson LOWER bound >= target
      worst  no ignorant line may clear      ->  Wilson UPPER bound <= target

    Both are demanding, and the second is the expensive one. Certifying a 10%
    ceiling needs the observed rate well under it -- at 72 trials no more than
    2 clears, at 200 no more than 11. That is the real price of the claim "a
    player who did not understand this does not get through"; a point estimate
    of 9% on 72 trials does not support it.
    """
    # Both sides carry the corrected z. The informed bound is one claim among
    # `_AUDIT_CLAIMS`, not a separate question asked at full confidence: the
    # world is kept only if the whole conjunction holds, so the alpha has to
    # cover the whole conjunction. Leaving this one at 1.96 was worth 1.2 points
    # of threshold, in the direction that lets a world through.
    inf_lo, _ = wilson(round(inf * trials), trials, _Z_INFORMED)
    _, worst_hi = wilson(round(worst * trials), trials, _Z_IGNORANT)
    return inf_lo >= targets.informed and worst_hi <= targets.partial


# Everything the screen's verdict depends on, hashed into the world-cache key.
#
# This started as a list of constants, and it was wrong within the hour: stage 1
# was rewritten, the listed constants did not move, and the next test run read a
# cached world produced by the code that had just been replaced -- in 4 seconds
# instead of 796, which is the only reason anybody noticed. The second version
# listed the deciding FUNCTIONS, which fixes that case and leaves the next one:
# a helper those functions call is still outside the list.
#
# So it hashes the module FILES. Every dependency closure kept by hand is a
# closure somebody forgets to extend, and the cost of being wrong is asymmetric:
# an extra cache miss costs a screening run, while a missed one silently
# certifies a world under a rule that no longer exists. Reformatting a comment
# invalidates the cache. That is the cheap direction.
_SCREEN_MODULES = ("solver.py", "adventure.py", "camp.py", "namegen.py",
                   "tune.py")


def _instrument_fingerprint() -> str:
    h = hashlib.blake2b(digest_size=5)
    here = pathlib.Path(__file__).parent
    for name in _SCREEN_MODULES:
        path = here / name
        h.update(name.encode())
        h.update(path.read_bytes() if path.exists() else b"<absent>")
    return h.hexdigest()


def screen_informed(run, seed, trials=24, stream="screen-stage-1"):
    """The cheap half: the informed rate and fight length, nothing else.

    One route search instead of seven. The other six -- the oracle reference,
    the four single-mechanic partials and the blind family -- are what the
    cascade defers, and together they are about five sixths of `screen`'s cost.
    """
    inf, turns, reach = _best_of(run, ALL, trials, seed, stream,
                                 information="observable")
    return inf, turns, reach


def screen(run, seed, targets=Targets(), trials=24, stream="screen-stage-1"):
    """Return screening score and both information-regime diagnostics.

    ``observable`` is the full-knowledge policy that can condition only on what
    appeared on screen. It is the rate used to select worlds. ``oracle`` gets
    the hidden enemy behaviour before acting and is reported only as a
    privileged-information reference. Keeping the two separate prevents the
    generator from buying worlds that are easy only for its own internals.

    Scored, not judged. Two different fixed bars have now quietly broken this
    search in the same way: `screen` short-circuits when the informed check
    fails, so a bar set above what the run can reach means the partial
    constraints are never evaluated and the multi-objective screen collapses
    into the single-objective one it replaced. The giveaway both times was a
    number that cannot happen -- making a mechanic LESS punishing lowered the
    measured ceiling -- and both times it took a while to recognise.

    There is no short-circuiting bar. Target misses are continuous penalties, so
    an unreachable target still guides the search toward the nearest world.
    The objective is the knowledge cliff itself: full knowledge should make a
    run easy and missing any one mechanic should make it hard. Boss reach is
    returned to diagnose where failures happen, but it is not optimized; an
    adventure death can be both valid and cheaper evidence than a late failure.

    """
    inf, turns, reach = _best_of(run, ALL, trials, seed, stream,
                                 information="observable")
    oracle_only = _best_of(run, ALL, trials, seed, stream,
                           information="oracle")[0]
    # The privileged policy family includes the option to ignore its extra
    # information and follow the observable policy exactly. Taking the union is
    # what makes this a reference ceiling rather than a second, occasionally
    # worse, hard-coded heuristic.
    oracle = max(inf, oracle_only)
    worst = max(max(_best_of(run, ALL - {m}, trials, seed, stream,
                             information="observable")[0]
                    for m in MECHANICS),
                _blind_best_of(run, trials, seed, f"{stream}:blind"))
    score_ = _screen_score(inf, worst, turns, reach, targets)
    return score_, inf, oracle, worst, turns, reach


def blind_ceiling(run, seed, trials=24, passes=1, stream="screen-blind"):
    """The best a mechanism-ignorant line can do, over the whole blind family.

    Measured separately from the single-mechanic partials because it is a
    different kind of opponent: those know everything but one and walk into the
    punishment, this one knows nothing and simply never offers the punished
    move. A world that stops the first and not the second can be cleared by a
    player who learned nothing, which is what happened on c17/7731.
    """
    # Winner picked on one stream, priced on another. Choosing the best of
    # eight variants BY the number you then quote is the same winner's curse the
    # route search already separates streams to avoid -- the max of eight noisy
    # estimates is biased upward, and the bias lands exactly on the figure the
    # screen tests against its ceiling.
    best, best_v = None, -1.0
    for v in STATIC_GRID:
        route, _ = best_route(run, NONE, seed, trials, passes,
                              information="observable", blind=v)
        val = _measure(run, NONE, trials, seed, route,
                       stream=f"{stream}:select", information="observable",
                       blind=v)[0]
        if val > best_v:
            best, best_v = (v, route), val
    v, route = best
    reported = _measure(run, NONE, trials * 2, seed, route,
                        stream=f"{stream}:report", information="observable",
                        blind=v)[0]
    return reported, best


def screen_precise(run, seed, targets=Targets(), trials=24, passes=2,
                   stream="screen-stage-2"):
    """Final screening with route search for every knowledge state.

    The cheap route bank above is suitable only for shortlisting. It can miss a
    strong partial route and accept a world whose apparent knowledge cliff is a
    policy-library artifact. The small final shortlist can afford coordinate
    ascent; its winners cannot.
    """
    route, _ = best_route(run, ALL, seed, trials, passes,
                          information="observable")
    inf, turns, reach = _measure(run, ALL, trials, seed, route,
                                 stream=f"{stream}:observable-report",
                                 information="observable")
    oroute, _ = best_route(run, ALL, seed, trials, passes,
                           information="oracle")
    oracle_only = _measure(run, ALL, trials, seed, oroute,
                           stream=f"{stream}:oracle-report",
                           information="oracle")[0]
    oracle = max(inf, oracle_only)
    partials = []
    for mechanic in MECHANICS:
        know = ALL - {mechanic}
        proute, _ = best_route(run, know, seed, trials, passes,
                               information="observable")
        partials.append((_measure(
            run, know, trials, seed, proute,
            stream=f"{stream}:partial-report", information="observable")[0],
            know, proute))
    # The blind ceiling joins the partials in the same max: a world only passes
    # if NO ignorant line clears, whichever kind of ignorance it is.
    blind_v, blind_best = blind_ceiling(run, seed, trials, passes=1)
    worst = max(max(partials)[0], blind_v)
    # Every line the audit has to re-price, not just whichever is strongest
    # here. At this trial count the ranking among the ignorant lines is itself
    # noisy, and the audit's whole job is to be the measurement that chose
    # nothing -- handing it a pre-selected winner would put the selection back
    # inside the number it certifies.
    #
    # Left on the run rather than returned so that every existing caller and
    # stub keeps its arity; `audit` falls back to the point estimates when it is
    # absent, and a stub that returns no blind witness simply contributes no
    # blind line rather than crashing the screen.
    ignorant = [(k, None, r) for _v, k, r in partials]
    if blind_best is not None:
        variant, broute = blind_best
        ignorant.append((NONE, variant, broute))
    # The partial routes and the blind champion come from coordinate ascent over
    # the whole of `GRID`, so any of them can be a line the declared family does
    # not contain. They join the audit as witnesses rather than being trusted at
    # the trial count that found them.
    run.screen_witness = {"informed": (ALL, None, route), "ignorant": ignorant}
    found = list(ignorant)
    for froute in BLIND_STAGE1_ROUTES:
        table, _v = best_fingerprint(run, seed, trials, froute)
        if table is not None:
            found.append((NONE, table, froute))
    run.audit_witnesses = _merge_witnesses(
        getattr(run, "audit_witnesses", ()), found)
    return (_screen_score(inf, worst, turns, reach, targets),
            inf, oracle, worst, turns, reach)


CACHE = pathlib.Path("/tmp/agii_runs/screen_cache.json")


def _cache_read_unlocked():
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


@contextlib.contextmanager
def _cache_lock(exclusive=False):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = CACHE.with_name(CACHE.name + ".lock")
    with lock_path.open("a+b") as lock:
        if os.name == "nt":
            # Windows：读者也拿独占锁；锁一个固定字节，非阻塞重试模拟 flock 的等待。
            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _cache_load():
    with _cache_lock():
        return _cache_read_unlocked()


def _cache_put(key, value):
    """Merge one result without losing another worker's concurrent result."""
    with _cache_lock(exclusive=True):
        data = _cache_read_unlocked()
        data[key] = value
        fd, name = tempfile.mkstemp(prefix=":screen-cache-", suffix=".json",
                                    dir=CACHE.parent)
        os.close(fd)
        tmp = pathlib.Path(name)
        try:
            tmp.write_text(json.dumps(data, indent=1))
            os.replace(tmp, CACHE)
        finally:
            if tmp.exists():
                tmp.unlink()


def calibrate(targets=Targets(), seeds=range(9000, 9012), tries=400, trials=24):
    """Find where the informed ceiling actually is, and put the bar just under.

    A fixed bar has now failed twice in the same way. `screen` returns early
    when the informed check fails, so a bar above the reachable ceiling means
    the partial constraints are never evaluated -- and the multi-objective
    search silently becomes the single-objective one it was built to replace.
    Both times the symptom was the same and misleading: making a mechanic LESS
    punishing lowered the measured ceiling, which cannot happen for a real
    difficulty change and only happens when the screen has stopped screening.

    So the bar is measured, not chosen. Sample what unconstrained runs achieve
    under full knowledge, take a high quantile of that, and screen against it."""
    from adventure import Run as _R
    vals = []
    for sd in seeds:
        run = _R(sd, validate=False)
        best = 0.0
        for a in range(24):
            run._roll(sd * 1009 + a)
            v, t, _reach = _best_of(run, ALL, trials, sd, stream="calibrate",
                                    information="observable")
            if t <= targets.turns:
                best = max(best, v)
        vals.append(best)
    vals.sort()
    return vals[int(len(vals) * 0.4)]          # reachable by most seeds


DEFAULT_SCREEN_TRIES = 2000
DEFAULT_SCREEN_TRIALS = 30


def make_run(seed, targets=Targets(), tries=DEFAULT_SCREEN_TRIES,
             trials=DEFAULT_SCREEN_TRIALS, use_cache=True,
             life=1, require_valid=True, audit_trials=None):
    """Roll this seed's run until it discriminates, keeping the best near-miss.

    Near-misses are scored by how far outside the targets they are, so a seed
    that never lands still gets its least-bad configuration rather than
    whatever try 300 happened to produce -- keeping the LAST roll instead of the
    best one is what once turned a threshold change into a 16-point drop that
    had nothing to do with the threshold."""
    run = Run(seed, validate=False)
    # The search is the expensive part now, and its answer is a single number:
    # which salt to roll. Caching it by (engine, seed, life) is what finally
    # makes the generated world reproducible in practice; the engine changing
    # invalidates the entry by construction.
    # Keyed by life as well: a later life is the SAME identity in a freshly
    # rolled world, so it needs its own screened configuration -- and it must
    # not be allowed to reuse the first life's, or the transfer test degenerates
    # back into a replay.
    check_route_bank()
    key = f"{ENGINE_VERSION}:{SCREEN_VERSION}:{_BANK_FINGERPRINT}:{seed}:{life}"
    config = dict(tries=tries, trials=trials, precise_trials=trials * REFINE_MULT,
                  precise_passes=2, shortlist=SHORTLIST,
                  targets=dict(informed=targets.informed,
                               partial=targets.partial,
                               turns=targets.turns))
    # A diagnostic call with `tries=1` used to be able to populate the same
    # cache key as the formal 2,000-candidate screen. That makes (version, seed,
    # life) non-reproducible. Only the declared canonical screen may read or
    # write that compact key; non-default experiments still run, but never
    # masquerade as a benchmark world.
    canonical = (tries == DEFAULT_SCREEN_TRIES
                 and trials == DEFAULT_SCREEN_TRIALS
                 and targets == Targets()
                 and audit_trials in (None, AUDIT_TRIALS))
    cache = _cache_load() if use_cache and canonical else {}
    if key in cache:
        salt, sc = cache[key]["salt"], cache[key]["screen"]
        run._roll(salt)
        run.rate, run.screen = sc[0], tuple(sc)
        run.selected_salt = salt
        run.screen_config = cache[key].get("config", config)
        run.valid = True          # only certified worlds are ever stored
        return run
    # Two stages, and the second one is not optional.
    #
    # A single pass that keeps the running best is what a screen wants to be,
    # but with a noisy estimate it locks up: an early candidate that got lucky
    # sets a floor no later candidate can clear, and since the floor is also
    # what prunes, everything after it is rejected without being priced. The
    # search then reports whatever it stumbled into first. That is what produced
    # the impossible reading where making a mechanic LESS punishing lowered the
    # measured ceiling.
    #
    # So: price everything cheaply, keep a shortlist, and re-price the shortlist
    # properly. The cheap pass may misrank; it only has to keep the good ones in
    # the top few, and the expensive pass decides among those.
    # Stage 1 used to be a cascade that pruned on the full-knowledge reading and
    # called that pruning exact. The arithmetic was exact; the input was a max
    # over four hand-written routes, which is a lower bound, so a low reading
    # only ever meant the routes were wrong. It read 22.7 points low and it cut
    # 89% of candidates -- preferentially the ones that needed a route the bank
    # did not contain. What replaced it is below.
    # Stage 1 is triage, not a screen. It may reject and it may rank, and those
    # are different entitlements resting on the same fact: every number it
    # produces is a max over a finite bank, hence a LOWER bound on what the
    # policy family can reach.
    #
    #   ignorant line clears more than allowed   -> counterexample, reject
    #   full-knowledge line clears little        -> the bank failed. Rank only.
    #
    # Rejections run first and cheapest, and short-circuit: a candidate that
    # dies to the generic lines never pays for its partials, and one that dies
    # on the first mechanic never pays for the other two. `inf` is measured
    # last and only for survivors, because it is the one reading that cannot
    # end a candidate.
    shortlist = []
    rejects = []          # (worst, salt) -- the least-bad, if nothing survives
    rejected = 0
    for attempt in range(tries):
        salt = (seed * 1009 + attempt) * 31 + life * 104729
        run._roll(salt)
        # A line that read over the target and was not confirmed is the most
        # dangerous thing triage produces: too weak to reject on, and -- until
        # it is carried forward -- invisible to everything downstream. It rides
        # to the audit as a witness.
        seen = []

        def _note(know, witness):
            if witness is not None:
                seen.append((know, witness[0], witness[1]))

        verdict, worst, w = _confirmed_over(
            run, targets.partial, trials, seed, know=NONE,
            lines=GENERIC_LINES, stream="screen-stage-1:generic")
        _note(NONE, w)
        if verdict is not OVER:
            partial_lines = [(None, r) for r in SCREEN_ROUTES]
            for mechanic in MECHANICS:
                know = ALL - {mechanic}
                v, rate, w = _confirmed_over(
                    run, targets.partial, trials, seed, know=know,
                    lines=partial_lines, stream=f"screen-stage-1:-{mechanic}")
                _note(know, w)
                worst = max(worst, rate)
                if v is OVER:
                    verdict = OVER
                    break
        if verdict is OVER:
            # Confirmed on an independent stream, Wilson lower bound above the
            # target. UNDECIDED does NOT land here: a cheap line reading over
            # the target with an interval that straddles it is a reason to look
            # harder, not a reason to reject, and it rides into the shortlist
            # carrying the raised `worst` that the score already penalises.
            rejected += 1
            rejects.append((worst, salt))
            continue
        inf, turns, reach = screen_informed(run, seed, trials,
                                            stream="screen-stage-1")
        # `None` where the oracle rate goes: stage 1 does not measure it and
        # stage 2 does. Left as None rather than filled with `inf` so that a
        # future reader of this slot gets a TypeError instead of a number that
        # looks like a privileged-information reference and is not one.
        shortlist.append((_screen_score(inf, worst, turns, reach, targets),
                          salt, (inf, None, worst, turns, reach, attempt),
                          tuple(seen)))
    if not shortlist:
        # Keeping the least-bad near-miss is what stops a seed that never lands
        # from returning whatever try 2000 happened to produce. The rejected
        # candidates were never priced on the informed side -- they short-
        # circuited -- so the few closest are priced now.
        rejects.sort()
        for worst, salt in rejects[:SHORTLIST]:
            run._roll(salt)
            inf, turns, reach = screen_informed(run, seed, trials,
                                                stream="screen-stage-1")
            shortlist.append((_screen_score(inf, worst, turns, reach, targets),
                              salt, (inf, None, worst, turns, reach, -1), ()))
    shortlist.sort(key=lambda x: -x[0])
    # Named `skipped` while the cascade pruned on a bound. These are rejections,
    # not skips: each one carries a concrete ignorant line that cleared.
    run.stage1_skipped = rejected
    run.stage1_shortlist = [salt for _s, salt, _d, _w in shortlist[:SHORTLIST]]
    best = (float("-inf"), None, None)
    for _, salt, _sc, triaged in shortlist[:SHORTLIST]:
        run._roll(salt)
        # Reset per candidate: a witness found on a rejected roll says nothing
        # about this one, and carrying it would spend the reserved alpha on a
        # line that cannot appear in the world being audited.
        run.audit_witnesses = _merge_witnesses((), triaged)
        # passes=2, not 1. One sweep of coordinate ascent cannot find a route
        # whose two changes only pay off together, and the strongest partial
        # route on the world this screen last accepted was exactly that shape
        # (`take=attack` AND `reward=hurt`). Measured on that world: one pass
        # reported the best pierce-blind line at 4.8%, two passes at 15.8%, and
        # three and four passes agreed with two. The screen had therefore
        # accepted a world whose true worst partial was over the 10% target it
        # was screening against -- it understated the opposition it was built to
        # measure, which is the same failure as a weak reference policy, on the
        # other side of the subtraction. Cost is +0.3s per knowledge state,
        # about 3% of a full screen.
        score_, inf, oracle, worst, turns, reach = screen_precise(
            run, seed, targets, trials * REFINE_MULT, passes=2,
            stream="screen-stage-2")
        if score_ > best[0]:
            best = (score_, salt,
                    (inf, oracle, worst, turns, reach, _sc[5]))
    run._roll(best[1])
    run.rate, run.screen = best[2][0], best[2]
    run.selected_salt = best[1]
    run.screen_config = config
    inf, _oracle, worst = best[2][0], best[2][1], best[2][2]
    cert_inf, cert_worst, cert_n = audit(run, seed, inf, worst,
                                         trials * REFINE_MULT, audit_trials)
    run.certified_at = (cert_inf, cert_worst, cert_n)
    run.valid = certified(cert_inf, cert_worst, cert_n, targets)
    if not run.valid:
        # Neither cached nor returned to a caller that asked for a benchmark
        # world. The best near-miss is real and worth looking at, and that is
        # exactly why it must not come back through this door: a `make_run`
        # that silently downgrades to "closest available" turns every hard
        # condition into a tiebreak, and the condition being downgraded here is
        # the one that says an ignorant line does not clear.
        if require_valid:
            raise NoQualifyingWorld(
                f"seed {seed} life {life}: {tries} candidates, none certified "
                f"(best: informed {inf:.1%} need >={targets.informed:.0%}, "
                f"worst {worst:.1%} need <={targets.partial:.0%}, "
                f"at {trials * 3} trials). Use `diagnostic_search` to inspect it.")
        return run
    if use_cache and canonical:
        _cache_put(key, {"salt": best[1], "screen": list(run.screen),
                         "config": config})
    return run


def diagnostic_search(seed, targets=Targets(), tries=DEFAULT_SCREEN_TRIES,
                      trials=DEFAULT_SCREEN_TRIALS, life=1, audit_trials=None):
    """The same search, returning its best near-miss with `run.valid` set.

    Never reads or writes the world cache, and never claims the result is a
    benchmark world. For asking "how close did this seed get, and on which
    condition did it fail" -- not for running anything against.
    """
    return make_run(seed, targets, tries, trials, use_cache=False, life=life,
                    require_valid=False, audit_trials=audit_trials)


_BANK_FINGERPRINT = _instrument_fingerprint()

_RUNS: dict[int, Run] = {}


def cached_run(seed: int) -> Run:
    """Generating a run means running the screen, which is the expensive part.
    Eight knowledge states over the same seeds would otherwise pay for it eight
    times -- and, worse, the screen leaves the run in its post-screen state, so
    re-generating is not even a way of getting a clean one."""
    if seed not in _RUNS:
        _RUNS[seed] = make_run(seed)
    return _RUNS[seed]


def _seed_job(args):
    """One seed's search, run in its own process. Runs are rebuilt from the
    disk-cached screen result, so a worker pays for generation at most once."""
    seed, know, trials, passes, information = args
    run = cached_run(seed)
    route, v = best_route(run, know, seed, trials, passes,
                          information=information)
    return seed, v, route


_T95 = (
    0.0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365,
    2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
    2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069,
    2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def _t95(df: int) -> float:
    """Two-sided 95% Student-t critical value without a scipy dependency."""
    if df < 1:
        raise ValueError("degrees of freedom must be positive")
    if df < len(_T95):
        return _T95[df]
    # Cornish-Fisher expansion around the normal 97.5% quantile. Accurate well
    # beyond the table, whose last and hardest case is df=30.
    z = 1.959963984540054
    return (z + (z**3 + z) / (4 * df)
            + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)
            + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z)
            / (384 * df**3))


def _summarize_seed_rates(vals, trials):
    """Mean and uncertainty over independently generated seed-level worlds."""
    if not vals:
        raise ValueError("probability requires at least one seed")
    m = statistics.mean(vals)
    if len(vals) == 1:
        lo, hi = wilson(round(m * trials), trials)
    else:
        se = statistics.stdev(vals) / math.sqrt(len(vals))
        half = _t95(len(vals) - 1) * se
        lo, hi = max(0.0, m - half), min(1.0, m + half)
    return m, lo, hi


def probability(know, seeds, trials=60, passes=2, verbose=False, workers=None,
                information="observable"):
    """Diagnostic clear-rate estimate for a knowledge state, over seeds.

    Each seed gets its own coordinate-ascent route, so this is not the benchmark
    score or a deployable universal policy. ``observable`` is the default and
    obeys the player's information boundary; ``oracle`` additionally knows the
    current hidden enemy behaviour and exists only as a diagnostic reference.
    The benchmark score is the empirical learning curve over lives, steps and
    corrected mistakes.

    Parallel across seeds because that is where the precision has to come from.
    Nothing clever is needed to make this accurate -- one simulated run costs
    about 0.2 ms, so the sampling error is bought down simply by taking more
    samples, and ten cores make that affordable. A smarter estimator (caching
    per-fight damage distributions and doing exact backward induction over the
    layers) would remove the sampling noise entirely, but it has to bucket
    health, key on deck composition and carry the poison stacks -- three new
    places to be subtly wrong, in a file whose history is mostly subtle wrongness
    in exactly such places. More samples cannot be wrong."""
    if workers is None:
        # Leave the machine usable. This runs on someone's laptop while they are
        # working on it, and saturating every core makes the editor stutter --
        # the speed is not worth that. Ask for more explicitly if the machine is
        # idle.
        workers = max(1, (os.cpu_count() or 2) - 2)
    seeds = list(seeds)
    if information not in {"oracle", "observable"}:
        raise ValueError(f"unknown information mode: {information}")
    jobs = [(sd, know, trials, passes, information) for sd in seeds]
    got = None
    if workers > 1 and len(seeds) > 1:
        # fork, not spawn. A spawned worker re-imports the entry module, and the
        # driver here is usually a throwaway script (or stdin), so the import
        # fails and the pool dies with BrokenProcessPool. Forking inherits the
        # parent's sys.path and everything already loaded, which is exactly what
        # is wanted; this code is single-threaded, so the usual objection to
        # fork does not apply.
        try:
            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                got = list(pool.map(_seed_job, jobs))
        except (ValueError, OSError, BrokenProcessPool):
            got = None                       # no fork here: fall back, do not fail
    if got is None:
        got = [_seed_job(j) for j in jobs]
    per = {sd: (v, route) for sd, v, route in got}
    vals = [v for _, v, _ in got]
    if verbose:
        for sd, v, route in got:
            print(f"  seed {sd:<6} {v:5.0%}  {route}", flush=True)
    # The interval is over SEEDS, not over pooled trials. Pooling treats every
    # trial as an independent draw from one population, which understates the
    # uncertainty badly: what varies most is which run you were handed, and all
    # the trials within a seed share that. Use the spread of seed-level rates
    # and the actual small-sample Student-t critical value.
    m, lo, hi = _summarize_seed_rates(vals, trials)
    return m, lo, hi, per


def _probability_serial(know, seeds, trials=60, passes=2, verbose=False,
                        information="observable"):
    """The public calculation with one worker; never a second implementation."""
    return probability(know, seeds, trials, passes, verbose, workers=1,
                       information=information)


def probability_pair(know, seeds, trials=60, passes=2, verbose=False,
                     workers=None):
    """Observable estimate plus a privileged-information reference.

    They are evaluated with the same trial streams. The privileged number is
    not called a mathematical upper bound: coordinate ascent and Monte Carlo
    noise can still mis-rank routes even though its information set is larger.
    """
    seeds = list(seeds)
    observable = probability(know, seeds, trials, passes, verbose, workers,
                             information="observable")
    oracle_only = probability(know, seeds, trials, passes, verbose, workers,
                              information="oracle")
    per = {}
    vals = []
    for seed in seeds:
        ov, oroute = observable[3][seed]
        pv, proute = oracle_only[3][seed]
        if ov >= pv:
            per[seed] = (ov, oroute, "observable")
            vals.append(ov)
        else:
            per[seed] = (pv, proute, "oracle")
            vals.append(pv)
    m, lo, hi = _summarize_seed_rates(vals, trials)
    privileged = (m, lo, hi, per)
    return {"observable": observable, "privileged": privileged}


def curve(seeds, trials=60, passes=1, verbose=True):
    """Clear probability against how much you have worked out.

    This is the measurement, not the single-life number. What a benchmark built
    on skill-acquisition efficiency wants to know is how fast a player climbs,
    so the object of interest is the whole curve -- and a model's score is where
    it sits on this curve after N lives, i.e. how many lives it needed.

    Two things it also checks, which a single number cannot:

      * MONOTONICITY. Knowing one more thing has to help, at every step. Twice
        now a mechanic has been built whose "correct" response actually lost --
        the piercer, then the regenerator -- and in both cases the giveaway was
        a knowledge state that scored HIGHER without it. A dip in this curve is
        that bug, and nothing else looks like it.
      * The floor. Knowing nothing has to be near zero, or the run can be
        cleared without learning and the climb is not being measured at all.
    """
    out = {}
    for k in range(len(MECHANICS) + 1):
        subs = [frozenset(c) for c in combinations(MECHANICS, k)]
        vals = [probability(s, seeds, trials, passes)[0] for s in subs]
        best = max(zip(vals, subs))
        out[k] = (sum(vals) / len(vals), min(vals), best[0], best[1])
        if verbose:
            m, lo, hi, who = out[k]
            print(f"  懂 {k} 样   平均 {m:>5.0%}   最差 {lo:>5.0%}   最好 {hi:>5.0%}"
                  f"   ({'+'.join(sorted(who)) or '什么都不懂'})", flush=True)
    return out


STATES = {
    "全懂": ALL,
    "只差护甲": ALL - {"armour"},
    "只差穿透": ALL - {"pierce"},
    "只差蓄力": ALL - {"charge"},
    "只差中毒": ALL - {"poison"},
    "只懂蓄力": frozenset({"charge"}),
    "只懂穿透": frozenset({"pierce"}),
    "什么都不懂": NONE,
}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--state", default=None, help="只算某一个知识状态")
    a = ap.parse_args()
    seeds = list(range(1, a.seeds + 1))
    print(f"engine={ENGINE_VERSION}  seeds={len(seeds)}  trials={a.trials}"
          f"  passes={a.passes}\n")
    print(f"{'知识状态':<12}{'通关概率':>10}{'95% 区间':>18}   最常选中的路线")
    print("-" * 78)
    for name, know in STATES.items():
        if a.state and name != a.state:
            continue
        m, lo, hi, per = probability(know, seeds, a.trials, a.passes)
        routes = [r for _, r in per.values()]
        elite = statistics.median(r.elite_at for r in routes)
        takes = max(set(r.take for r in routes), key=lambda t: sum(
            1 for r in routes if r.take == t))
        print(f"{name:<12}{m:>9.0%}{f'[{lo:.0%}, {hi:.0%}]':>18}"
              f"   主动精英线 "
              f"{'从不' if elite > 1 else f'{elite:.0%}'}  "
              f"拿牌 {takes or '不拿'}", flush=True)
