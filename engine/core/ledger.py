"""干净通关：通关，而且每种遇到过的机制，在有可执行答案的机会上没有一直答错。

通关率算的是「活到最后」，而懂规则的人 83% 的死与答题无关 —— 反过来，一条猛攻
线也可能靶着活到 boss。所以「不懂的一定不通关」在测量层就要收紧：一次通关只有
在账本干净时才算。这条独立于任何游戏改动，今天就能加。

    Ledger      record 协议的实现：每种机制的机会数 / 错误数，
                可执行性在**决策时刻**取（回合末的能量条已经花光了）
    clean()     通关 且 每个机会数 >= min_opp 的机制错误率 < threshold

反击的「第二次进攻可执行」要在第一次进攻打出之后才能判断，所以它在 `after_play`
里取，不在 `before_decision`。
"""
from __future__ import annotations

import collections

import efficiency

MECHANICS = ("charge", "pierce", "enrage", "momentum", "poison", "wound",
             "counter", "guard", "mark", "mimic", "ward")
OFFENSIVE = ("attack", "buff_mark")


class Ledger:
    def __init__(self):
        self.opp = collections.Counter()
        self.mis = collections.Counter()
        self.belief = None
        self.run = None

    # -- record 协议 -----------------------------------------------------
    def enter(self, run, f, kinds):
        self.run = run

    def before_decision(self, f):
        self.dodge = efficiency.dodge_available(f)
        self.block = efficiency.block_available(f)
        self.offer = efficiency.nonattack_available(f)
        self.heal = efficiency.heal_available(f)
        self.buff = efficiency.buff_available(f)
        self.nonattack = False
        self.heal_played = False
        self.second = False

    def before_play(self, f, c):
        kind = f.deck[c].kind
        self.nonattack |= kind != "attack"
        self.heal_played |= kind == "heal"

    def after_play(self, f, c, atk_before):
        if f.deck[c].kind in OFFENSIVE and f.offences == 1:
            self.second = efficiency.second_offence_available(f)

    def before_end_turn(self, f):
        kw = dict(charge_executable=self.dodge, momentum_executable=self.block,
                  heal_executable=self.heal)
        for m in efficiency.turn_opportunities(
                f, enrage_offer=self.offer, second_offence_executable=self.second,
                buff_executable=self.buff, ward_block_executable=self.block, **kw):
            self.opp[m] += 1
        for m in efficiency.turn_mistakes(
                f, enrage_played=self.nonattack, heal_played=self.heal_played,
                ward_block_executable=self.block, **kw):
            self.mis[m] += 1

    def after_end_turn(self, f, hp_before, block_before, charge_before): pass
    def leave(self, f, won): pass

    def auto_rest(self, run, layer, hp_before, hp_after):
        """Registration 12 (TUNING["auto_rest"]): the automatic resupply is an environment event -- not scored."""

    def rest(self, run, mode):
        if efficiency.rest_opportunity(run):
            self.opp["poison"] += 1
            if efficiency.rest_mistake(run, mode):
                self.mis["poison"] += 1

    # -- 判定 --------------------------------------------------------------
    def rate(self, m):
        return self.mis[m] / self.opp[m] if self.opp[m] else None

    def dirty(self, threshold=.2, min_opp=1):
        """错误率过线的机制。空 = 干净。"""
        return [m for m in MECHANICS
                if self.opp[m] >= min_opp and self.mis[m] / self.opp[m] >= threshold]


def clean(won, ledger, threshold=.2, min_opp=1) -> bool:
    return bool(won) and not ledger.dirty(threshold, min_opp)
