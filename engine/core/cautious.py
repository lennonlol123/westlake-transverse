"""谨慎的懂规则参考策略，第 2 版（2026-10-20）。知道七条规则、每个符号和每张牌是什么、每只怪只有一种机制，
也知道标记是按这一场各种牌的累计出牌数加权抽的（没出过牌时均匀）。**不知道**眼前这只怪是哪一种，也不知道这张图上
标记代号对应哪种牌。量的是「公开信息完整、没有身份标签时，会谨慎行动的玩家能打多少」（用户 2026-10-20：不加身份记号，
认怪是被测能力的一部分，代价是更多的辨别成本）。第 1 版的问题见 2026-10-20 的审查（漏用「出了没挨打」、全避开会死锁、
治疗偷看映射、穿透检测在怪攻击低于自己时失灵、反击检测读了画面上是 ? 的怪攻击）。

它读的：画面（`TUNING["state_slots"]` 下印出的怪方状态槽；主实验用 "seen"，即变过一次才印），自己的血、盾、毒、出过的牌，
以及三种它亲眼看到的事件 —— 引擎替它们记的计数器只当作那个事件本身用：
    f.reflected      出了攻击，自己当场掉血（守相反弹）
    f.ward_wasted    出了攻击，怪没掉血，自己也没掉血（打在封印上）
    f.mark_hits      出了某张牌，当场掉一大截血（被标记击中；这一场的累计）
它不读：Enemy.parts、怪的攻击数值（画面上是 ?）、mark_perm（代号映射）、任何未来的东西。

认怪（每场重新认；认出了就不再设防）：
    怪方印出了任何状态槽且值非零（seen：槽一出现就是它变过了）→ 是带状态的怪（蓄力 / 守 / 标记 / 破势），不是反击或穿透
    出攻击被反弹 → 守；攻击打空 → 破势；这一场自己的毒层涨了 → 毒
    回合末（`PublicBelief`）：一回合进攻 ≥ 2 次、没举盾、掉血 ≥ 1.5 × 一记普通伤害 → 反击
                              举着盾、进攻 < 2 次、仍掉了 ≥ 一记普通伤害 → 穿透（正常的一记被盾挡掉一部分，掉的一定比一记少）
    「一记普通伤害」= 怪的攻击值，如果它这一场变过（怒气）、因而已经印出来；否则这一场最近一次干净挨打（没举盾、没闪、
    进攻 < 2 次、不是满格大招）掉的血；都没有就用自己的攻击力。
    两种惩罚的第一下都是怪攻击的 2 倍（TUNING counter_probe_mult / pierce_probe_mult）。
标记映射：每条命（= 一张图，映射在图内不变）记下全部证据 —— 每次代号亮出时这一场的累计出牌数（似然 = 那种牌的次数 / 总次数，
    没出过牌时 1/5）、每次在亮着的代号下出牌有没有挨打（挨打 ⇔ 代号就是那种牌）—— 对 5! = 120 种一一对应逐一核对，
    得到「这个代号是哪种牌」的后验。

没有做排除法（例如「一个回合过去什么槽都没印、毒层没涨 → 不是蓄力 / 守 / 标记 / 毒」）：第 2 轮审查测过，加上它最好的变体
不变（0.615 对 0.613），「不设防」的那几种是下界；「开局先防 + 防反击」等于用排除法认出反击。

事先写好的变体（`VARIANTS`，三条轴交叉；在开发图上选，见 scripts/public_info_check.py）：
    设防    none                 不设防：没认出也照常打
            counter              没认出之前一回合最多进攻一次（反击的答案）
            counter_after_probe  只在这条命已经挨过一次反击之后才这样防（反击的便宜第一下每条命只有一次）
            pierce               没认出之前不留盾到回合末（穿透的答案）
            both                 两样都防
    防标记  likely               避开后验最大的那一种（并列时按 AVOID_TIES 先避开不值钱的）
            safe                 后验 > 0 的全避开；但要是这样就什么都出不了（而不避开时本来会出牌），改出后验最小的那张，不干等
    开局    attack               照常先攻
            defend               还没认出的怪，这一场第一回合不出进攻牌（攻击、增伤），只出防守牌 —— 安全出牌：封印会降一层、
                                 守相会翻、蓄力会涨、标记会抽，回合末多半就认出来了，代价是一回合不打
`solver.act` 会直接读守相、封印的真值；这两个在认出这只怪之前没上过画面，所以认出它是守 / 破势之前，知识里不给这两条
（审查第 2 轮之前的试跑发现：防穿透的变体碰上没认出的破势怪，act 偷看到封着、不攻击，又不许举盾，干等到死）。
它调用的仍是 `solver.act`（同一套懂规则的出牌顺序）：知识里去掉 mark，`avoid` 给出要避开的牌种，设防时把信念里的
pierce / counter 当成已认出来交给 act（act 对认出的穿透不留盾、对认出的反击一回合只进攻一次）；治疗由 `heal_veto` 管。
用法：p = Cautious("counter/likely"); TUNING["marks"] = 0; TUNING["state_slots"] = "seen"
      solver.run_once(run, solver.ALL - {"mark"}, route, rng, information="observable",
                      act_policy=p.act, heal_veto=p.heal_veto, belief_cls=PublicBelief)"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import adventure
import solver
from adventure import TUNING

HEDGES = ("none", "counter", "counter_after_probe", "pierce", "both")
MARKS = ("likely", "safe")
OPENINGS = ("attack", "defend")
VARIANTS = tuple(f"{h}/{m}/{o}" for h in HEDGES for m in MARKS for o in OPENINGS)
KINDS = ("attack", "block", "dodge", "heal", "buff_mark")
AVOID_TIES = ("buff_mark", "heal", "dodge", "block", "attack")     # 后验并列时，先避开最不值钱的
PERMS = tuple(itertools.permutations(KINDS))                         # 一种映射：代号 i+1 → perm[i]


def them_slots(f) -> dict:
    """画面上怪方状态那一行（Them: 下面缩进的那行）印出来的 {符号: 值}。只读画面文字。"""
    lines = adventure.show(f).split("\n")
    out = {}
    for i, line in enumerate(lines):
        if line.startswith("Them:") and i + 1 < len(lines) and lines[i + 1].startswith(" " * 8):
            for tok in lines[i + 1].split():
                lab, _, val = tok.partition(":")
                if val and val.lstrip("-").isdigit():
                    out[lab] = int(val)
    return out


@dataclass
class PublicBelief(solver.FightBelief):
    """回合末的认怪，只用公开的量（见模块说明）。替换 FightBelief 里读怪攻击、以自己攻击为尺的那两条。"""
    clean_hit: int = 0           # 这一场最近一次干净挨打掉的血
    atk0: int | None = None      # 这一场开局时怪的攻击（Cautious 在第一次决策时记）：之后它一变，日志和画面就给出了真值
    always_observe = True

    def observe_play(self, f, atk_before, kind):
        return                   # 不在池里的机制（激怒、模仿）才在这里认；它们读的是画面上是 ? 的怪攻击

    def observe_end_turn(self, f, hp_before, block_before, poison_before, charge_before=0,
                         atk_before=None, played_non_attack=False):
        if charge_before >= max(1, f.enemy.charge_max):
            return               # 满格的大招落下：不是关于盾或进攻次数的证据
        loss = min(hp_before - poison_before, f.max_hp) - f.state[("me", "hp")]
        offences = getattr(f, "last_offences", 0)
        dodged = getattr(f, "last_kinds", {}).get("dodge", 0) >= 1
        atk = f.state[("them", "atk")]
        visible = atk if (self.atk0 is not None and atk != self.atk0) else None    # 怒气动过它：真值已经公开
        est = visible or self.clean_hit or f.state[("me", "atk")]
        shielded = block_before > 0
        if offences >= 2 and not shielded and not dodged and loss > 1.5 * est:      # 严格大于：普通怪攻击最高正好是自己的 1.5 倍（D、E）
            self.counter = True
        elif shielded and offences < 2 and not dodged and loss >= est:
            self.pierce = True
        if not shielded and offences < 2 and not dodged and loss > 0:
            self.clean_hit = loss
        self.worst = max(self.worst, loss)


class _Hedged:
    """交给 act 的信念：设防时把 pierce / counter 当成已认出。其余字段原样转给真信念。"""

    def __init__(self, base, pierce, counter):
        self._base, self.pierce, self.counter = base, pierce, counter

    def __getattr__(self, name):
        return getattr(self._base, name)


class _Fight:
    def __init__(self, f):
        self.f = f
        self.types = set()                              # 认出来的机制（每只怪只有一种，所以一般只有一个）
        self.first_turn = f.turn                        # 这一场的第一回合
        self.identified_turn = None                     # 第一次认出的回合（只给报告用）
        self.poison0 = f.state[("me", "poison")]
        self.turn = None
        self.code = 0                                   # 上次看时亮着的代号
        self.kinds_seen = dict(getattr(f, "fight_kinds", {}))
        self.hits_seen = getattr(f, "mark_hits", 0)     # 这一场累计的标记击中（回合末不清零，回合最后一张牌也算得上）
        self.reflected = getattr(f, "reflected", 0)
        self.wasted = getattr(f, "ward_wasted", 0)


class Cautious:
    """一条命的谨慎玩家；每条命新建一个（标记映射的证据、「这条命挨过反击没有」只在一条命里有效）。"""

    def __init__(self, variant: str):
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}; one of {VARIANTS}")
        self.hedge_rule, self.mark_rule, self.opening = variant.split("/")
        self.counter_seen = False
        self.draws = []          # (代号, 这一场的累计出牌数)
        self.plays = []          # (代号, 牌种, 挨打没有)
        self._post = None        # 缓存的后验（证据变了就作废）
        self._fights = {}

    # -- 标记映射的后验 -----------------------------------------------------------------
    def posterior(self) -> dict:
        """{代号: {牌种: 概率}}，对 120 种一一对应逐一核对证据。"""
        if self._post is not None:
            return self._post
        weights = []
        for perm in PERMS:
            w = 1.0
            for code, counts in self.draws:
                kind = perm[code - 1]
                total = sum(counts.values())
                w *= (counts.get(kind, 0) / total) if total else 1 / len(KINDS)
                if not w:
                    break
            if w:
                for code, kind, hit in self.plays:
                    if (perm[code - 1] == kind) != hit:
                        w = 0.0
                        break
            weights.append(w)
        z = sum(weights)
        if not z:                # 证据互相矛盾（不该发生）：退回均匀，宁可多防
            weights, z = [1.0] * len(PERMS), float(len(PERMS))
        post = {c: dict.fromkeys(KINDS, 0.0) for c in range(1, len(KINDS) + 1)}
        for perm, w in zip(PERMS, weights):
            if w:
                for i, kind in enumerate(perm):
                    post[i + 1][kind] += w / z
        self._post = post
        return post

    def _avoid(self, code) -> frozenset:
        if not code:
            return frozenset()
        p = self.posterior()[code]
        if self.mark_rule == "safe":
            return frozenset(k for k in KINDS if p[k] > 0)
        top = max(p.values())
        return frozenset({next(k for k in AVOID_TIES if p[k] == top)})

    # -- 每次决策前看一眼 ------------------------------------------------------------------
    def _st(self, f) -> _Fight:
        st = self._fights.get(id(f))
        if st is None or st.f is not f:
            st = self._fights[id(f)] = _Fight(f)
        return st

    def _observe(self, f, belief):
        st = self._st(f)
        mode = TUNING.get("state_slots", "hidden")
        code = f.state.get(("them", "mark"), 0) if mode != "hidden" else 0
        shown = them_slots(f)
        # 槽的符号是什么意思，懂规则的人知道。seen / carrier：槽一出现就说明这只怪带它（seen 下它变过，不带的怪的槽从来不变）；
        # all：每只怪都印，要等值非零
        meaning = {f.layout.L("them", m): m for m in adventure.ENEMY_STATE_SLOTS}
        st.types |= {meaning[lab] for lab, v in shown.items() if lab in meaning and (v or mode != "all")}
        if f.state[("me", "poison")] > st.poison0:
            st.types.add("poison")
        if f.reflected > st.reflected:
            st.types.add("guard")                    # 出了攻击，自己当场掉血
        if f.ward_wasted > st.wasted:
            st.types.add("ward")                     # 出了攻击，怪没掉血，自己也没掉血
        st.reflected, st.wasted = f.reflected, f.ward_wasted
        if belief is not None:
            st.types |= {m for m in ("pierce", "counter") if getattr(belief, m, False)}
            self.counter_seen |= bool(belief.counter)
        if st.types and st.identified_turn is None:
            st.identified_turn = f.turn
        now = dict(getattr(f, "fight_kinds", {}))
        played_now = [k for k in KINDS if now.get(k, 0) > st.kinds_seen.get(k, 0)]
        hits = getattr(f, "mark_hits", 0)
        if st.code and len(played_now) == 1:         # 上次看完之后出了一张（可能是上回合最后一张）：在当时亮着的代号下，挨没挨打
            self.plays.append((st.code, played_now[0], hits > st.hits_seen)); self._post = None
        if f.turn != st.turn:                        # 新回合：上回合末抽的代号刚亮出来，当时的累计出牌数就是现在的
            st.turn = f.turn
            if code:
                self.draws.append((code, now)); self._post = None
        st.code, st.kinds_seen, st.hits_seen = code, now, hits
        return st, code

    # -- 给 solver 的两个钩子 ------------------------------------------------------------------
    def heal_veto(self, f) -> bool:
        st, code = self._observe(f, None)
        return "heal" in self._avoid(code)

    def _guards(self):
        """（防反击, 防穿透）：这一刻、对还没认出的怪设不设这两种防。"""
        return (self.hedge_rule in ("counter", "both") or (self.hedge_rule == "counter_after_probe" and self.counter_seen),
                self.hedge_rule in ("pierce", "both"))

    def _defend_opening(self):
        return self.opening == "defend"

    def _extra_avoid(self, f) -> frozenset:
        """子类追加要避开的牌种（默认没有）。"""
        return frozenset()

    def act(self, f, know, kinds, belief=None, information="observable"):
        st, code = self._observe(f, belief)
        if belief is not None and getattr(belief, "atk0", 0) is None:
            belief.atk0 = f.state[("them", "atk")]
        guard_counter, guard_pierce = self._guards()
        b = belief
        if not st.types and belief is not None and (guard_counter or guard_pierce):
            b = _Hedged(belief, belief.pierce or guard_pierce, belief.counter or guard_counter)
        # act 直接读守相、封印的真值；它们在认出这只怪之前没上过画面（seen：变过才印），所以认出之前不把这两条规则交给它
        know = frozenset(know) - {"mark"} - ({"guard", "ward"} - st.types)
        mark_avoid = self._avoid(code)
        open_avoid = (frozenset({"attack", "buff_mark"})
                      if self._defend_opening() and not st.types and f.turn == st.first_turn else frozenset())
        extra = self._extra_avoid(f)
        c = solver.act(f, know, kinds, information=information, belief=b, avoid=mark_avoid | open_avoid | extra)
        if (c is None and code and mark_avoid and self.mark_rule == "safe"
                and solver.act(f, know, kinds, information=information, belief=b, avoid=open_avoid | extra) is not None):
            # 全避开会干等：改出后验最小的那张（并列按 KINDS 的反序，先出不值钱的）
            p = self.posterior()[code]
            playable = [k for k in reversed(KINDS) if k in kinds and k not in open_avoid | extra and f.can_play(kinds[k])]
            if playable:
                c = kinds[min(playable, key=lambda k: p[k])]
        return c


class LearningCautious(Cautious):
    """从零学规则的谨慎玩家（2026-10-21，主实验正式参照之一）。出牌、认怪、推标记和 Cautious 同一套，只看公开信息、
    没有身份标签；区别是规则要自己学：`rules` 是跨命保留的 learner.LearnedRules（两场不同战斗里各见一次证据才算学会，
    证据由 learner.counted_beliefs(rules, 命, base=PublicBelief) 记），而它只对已经学会的规则做 Cautious 的那些事 ——
        防反击 / 防穿透    要先学会反击 / 穿透
        避标记（含治疗）   要先学会标记
        开局先防           要先学会至少一条靠认怪才用得上的规则（反击、穿透、守、破势）；什么都不懂时没有理由先防
        交给 act 的知识    就是 rules（守、破势照旧要等认出这只怪才给）
    每条命新建一个（标记映射的证据只在一张图里有效）；rules 跨命共用。"""
    IDENTIFY_FOR = frozenset({"counter", "pierce", "guard", "ward"})

    def __init__(self, variant: str, rules):
        super().__init__(variant)
        self.rules = rules

    def _guards(self):
        c, p = super()._guards()
        return c and "counter" in self.rules, p and "pierce" in self.rules

    def _defend_opening(self):
        return super()._defend_opening() and any(m in self.rules for m in self.IDENTIFY_FOR)

    def _avoid(self, code) -> frozenset:
        return super()._avoid(code) if "mark" in self.rules else frozenset()

    def know(self):
        """交给 run_once 的知识：rules 去掉 mark，随 rules 实时更新。solver.play_fight 治疗前有一道
        `"mark" in know and f.marked_kind() == "heal"` 的否决，读的是本图隐藏的代号映射（mark_perm）；把 rules 本身交过去，
        学会标记之后就偷看了（审查 2026-10-21）。避标记（含治疗）只走这里的后验和 heal_veto。"""
        return _WithoutMark(self.rules)


class _WithoutMark:
    def __init__(self, rules):
        self.rules = rules

    def __contains__(self, m):
        return m != "mark" and m in self.rules

    def __iter__(self):
        return (m for m in self.rules if m != "mark")


class Remedial(LearningCautious):
    """「缺一条规则」的补救版（2026-10-21，规则必要性验收：缺一条的玩家要允许合理的保守和补救，不能靠故意打得差的脚本证明必要）。
    不懂那条规则，但按公开看到的后果做通用的补救 —— 只在这一场里有效：
        刚出一张牌就当场掉血（标记、守相反弹那一类）     这一回合不再出这种牌
        攻击打下去怪没掉血（封印那一类）                 这一回合不再出攻击
        回合末挨了一记远大于平常的重击                   这一场里把上回合做过的可疑动作都停掉：出过两张进攻牌 → 一回合最多一张；
                                                         留着盾 → 不留盾；出过加倍 → 不出加倍
    「平常的一记」= 这一场最近一次干净挨打掉的血（PublicBelief.clean_hit），没有就用自己的攻击力。"""

    def __init__(self, variant: str, rules):
        super().__init__(variant, rules)
        self._rem = {}

    def _r(self, f):
        r = self._rem.get(id(f))
        if r is None or r["f"] is not f:
            r = self._rem[id(f)] = dict(f=f, turn=f.turn, hp=f.state[("me", "hp")], ehp=f.state[("them", "hp")],
                                        kinds=dict(getattr(f, "fight_kinds", {})), turn_kinds={}, block=f.state[("me", "block")],
                                        ban_turn=set(), cap1=False, noblock=False, nodouble=False, clean=0)
        return r

    def _extra_avoid(self, f) -> frozenset:
        r = self._r(f)
        hp, ehp = f.state[("me", "hp")], f.state[("them", "hp")]
        now = dict(getattr(f, "fight_kinds", {}))
        played = [k for k in KINDS if now.get(k, 0) > r["kinds"].get(k, 0)]
        if f.turn == r["turn"]:
            if played and hp < r["hp"]:
                r["ban_turn"] |= set(played)                 # 出牌当场挨打
            if "attack" in played and ehp >= r["ehp"]:
                r["ban_turn"].add("attack")                  # 攻击没打出伤害
            for k in played:
                r["turn_kinds"][k] = r["turn_kinds"].get(k, 0) + now[k] - r["kinds"].get(k, 0)
        else:                                                # 新回合：上回合末的那一下
            tk = r["turn_kinds"]
            for k in played:                                 # 上回合最后一张（出完就没再问过它）
                tk[k] = tk.get(k, 0) + now[k] - r["kinds"].get(k, 0)
            held = r["block"] > 0 or "block" in played
            loss = r["hp"] - hp - f.state[("me", "poison")]
            est = r["clean"] or f.state[("me", "atk")]
            offences = tk.get("attack", 0) + tk.get("buff_mark", 0)
            if loss > 1.5 * est:
                r["cap1"] |= offences >= 2
                r["noblock"] |= held
                r["nodouble"] |= tk.get("buff_mark", 0) > 0
            elif loss > 0 and offences < 2 and not held:
                r["clean"] = loss
            r.update(turn=f.turn, turn_kinds={}, ban_turn=set())
        r.update(hp=hp, ehp=ehp, kinds=now, block=f.state[("me", "block")])
        avoid = set(r["ban_turn"])
        if r["cap1"] and r["turn_kinds"].get("attack", 0) + r["turn_kinds"].get("buff_mark", 0) >= 1:
            avoid |= {"attack", "buff_mark"}
        if r["noblock"]:
            avoid.add("block")
        if r["nodouble"]:
            avoid.add("buff_mark")
        return frozenset(avoid)
