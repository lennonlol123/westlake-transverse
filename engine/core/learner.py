"""参考学习者 —— 证明这套地图可学，不是给 Gemini 定及格线。

它要回答的唯一问题：这四张地图给出的证据，够不够让一个会更新规则的策略在第
二轮和后续生命里变好。如果连它都不改善，那是测量或地图有问题，不该花钱跑模型。

================== 两层记忆，分开的 ==================

    长期规则记忆    「穿透会惩罚护盾」—— 跨怪、跨命保留
    当前敌人身份    「眼前这只是不是穿透」—— 每遇到新怪重新判断

这两层在引擎里本来就是分开的：`solver.act(f, know, ...)` 里的 `know` 是前者，
`FightBelief` 是后者，而且行动必须两者同时成立：

    piercer = ("pierce" in know and ... belief.pierce)

所以「学会穿透 = 以后永远不举盾」是偷看答案：知道规则之后，面对一只新怪仍然
要付出探测的代价。这里只把 `know` 做成会生长的，身份那一层原样不动。

逐机制，规则怎么学、身份怎么认：

自己牌的知识（`solver.CARD_SKILLS`，现在只有「加倍牌真的会翻倍」）不在学习
范围内：那是训练营教的，参与者进冒险前已经解出来了。学习者要学的是怪。

    charge    规则：看见蓄力槽满格那一下重击，才知道满格意味着什么
              身份：蓄力槽是公开的，而且只有蓄力怪有 —— 认身份不要钱
    pierce    规则：举盾之后挨了异常伤害，才知道盾会被惩罚
              身份：新怪仍需一次合理探测，看到异常伤害后停止举盾
    enrage    规则 & 身份：出非攻击牌之后攻击力当场上涨
    momentum  规则 & 身份：不格挡之后攻击力上涨
    poison    规则：毒层扣血且啃上限；身份：毒层计数是公开的
              不能预知后面还会叠多少层

================== 两种学习速度 ==================

    OneShotIdeal   一次证据就确认（need=1）。**天花板和管线检查**，不是真实
                   基线：它从不误判、从不遗忘，一条命之内就学完五条规则。
    TwoStage       第一次证据 -> 怀疑；第二次**独立**证据（另一场战斗里再次
                   认出同一条机制）-> 确认（need=2）。慢学习者。

两条都保留。one-shot 测得出「证据够不够」，two-stage 才测得出「记忆值多少」——
因为 one-shot 在命 1 就学完了，跨命根本没有剩余空间可测。

「独立」的定义：同一场里反复挨打不算第二次证据，必须是另一场战斗。同一场里
反复挨打只证明这只怪是这样，不证明这是一条通则。

================== 三个对照臂 ==================

    none      从不学 —— 地板。`know` 永远是空的
    within    一条命之内学，换命清空
    cross     一条命之内学，并把规则记忆带进下一条命
    oracle    开局全知 —— 天花板（引擎里本来就有）

（你给的 "Fresh" 和 "Within-life" 两条定义读起来是同一件事，所以这里把地板
明确成「从不学」。要的是别的意思就说，改起来是一行。）

三臂用同一批地图、同一条路线、同一组随机流，差别只有记忆。

要看的：
    获得速度    第几次证据之后行为首次改正
    命内保持    改正之后还会不会再犯
    跨命保持    新命的第一次相关机会，是否仍按旧规则行动
    探测代价 vs 真正错误，分开报：
        首次合理探测        —— 知道规则也必须付的，不算错
        证据之后的重复错误  —— 真正的错
        重新识别付的血       —— 代价的大小
    五种机制是否都拿到足够机会                  （地图有没有出全题）
    整局通关率只作最终结果，不作学习指标
"""
import solver
from solver import FightBelief


class LearnedRules:
    """长期那一层。`act` 只对它做 `in` 测试，所以一个集合就够。"""

    def __init__(self, known=(), need=1):
        self.known = set(known)
        self.need = need              # 1 = one-shot ideal, 2 = two-stage
        self.seen = {}                # 机制 -> 见过它的 (命, 场) 集合
        self.learned_at = {}          # 机制 -> 第一次确认的 (命, 场)
        self.events = []              # (命, 场, 机制, "evidence"|"confirm")

    def __contains__(self, m):
        return m in self.known

    def __iter__(self):
        return iter(self.known)

    def evidence(self, m, where):
        """在 `where` 这一场认出了 m。够次数（`need`）才转成规则。

        按**场**去重：同一场里反复挨打只算一次证据。"""
        if m in self.known:
            return
        new = where not in self.seen.setdefault(m, set())
        self.seen[m].add(where)
        if new:
            self.events.append((*where, m, "evidence"))
        if len(self.seen[m]) >= self.need:
            self.known.add(m)
            self.learned_at[m] = where
            self.events.append((*where, m, "confirm"))

    learn = evidence          # 旧名字，保留给已有调用

    def suspected(self, m):
        return m in self.seen and m not in self.known

    def copy(self):
        c = LearnedRules(self.known, self.need)
        c.seen = {k: set(v) for k, v in self.seen.items()}
        c.learned_at = dict(self.learned_at)
        c.events = list(self.events)
        return c


def counted_beliefs(rules, life, base=FightBelief):
    """给 run_once 的 `belief_cls`：一条命里每开一场（引擎每场新建一个信念，boss 每段也是一场）就把场号加一，
    证据记在 (命, 场) 下，`need=2` 才真的是「两场不同的战斗」。

    2026-10-21 修：原来的调用方（scripts/search4.py 的 learn、scripts/learner_rest_variants.py）写了
    `fight_no = [0]` 却从不加一，同一命里的证据全记成 (命, 0)，只算一次，于是「两场」实际变成「两条命」，
    第一命永远学不会（learner_rest_variants.json 第 1 命已学会条数均值 0.0）。旧结果按旧行为留档。"""
    n = [0]
    cls = belief_for(rules, lambda: (life, n[0]), base=base)

    def make():
        n[0] += 1
        return cls()
    return make


def belief_for(rules, where, base=FightBelief, poison_this_fight=True):
    """身份那一层，外加「确认身份的同时也学会了规则」这一条线。

    规则是从身份推出来的，不是反过来：第一次认出一只穿透怪，就同时知道了
    「盾会被惩罚」这条规则。之后再遇到新怪，规则还在，身份要重认。

    `where()` 给出这条证据记在哪一场；按场计数用 `counted_beliefs`。`base` 是认怪的信念：
    默认 FightBelief（读怪攻击真值），只看公开信息的学习者用 cautious.PublicBelief。
    `poison_this_fight=False` 是 2026-10-21 之前的毒规则（只要毒层扣血就算证据，余毒也算），只为逐位复现旧曲线。
    """

    import solver as _solver

    def learn(m, at):
        # 只学池子里有的规则。六池世界上 `FightBelief.momentum` 会被守势怪的怒气
        # 顶起来（守相不进攻算停顿，攻击数字回合末上涨，和 momentum 的公开信号一样），
        # 于是学习者「学会」了一条不存在的规则，已学会条数虚高约 1。仪器误报，
        # 不进 `known`；检测器本身不动，参考策略的身份层不受影响。
        if m in _solver.MECHANICS:
            rules.learn(m, at)

    class Learning(base):
        # 没有这一条，规则永远学不会：`play_fight` 里的回合末探测器被
        # `{"pierce","momentum"} & know` 门住，也就是「先知道才会看见」。
        # 对参考策略那是对的（它的设定是懂规则、认不出这只怪），对学习者是死锁。
        always_observe = True

        def observe_play(self, f, atk_before, kind):
            was = self.enrage
            super().observe_play(f, atk_before, kind)
            if self.enrage and not was:
                learn("enrage", where())

        def observe_end_turn(self, f, hp_before, block_before, poison_before,
                             charge_before=0, atk_before=None,
                             played_non_attack=False):
            was = (self.pierce, self.momentum, self.counter)
            super().observe_end_turn(f, hp_before, block_before, poison_before,
                                     charge_before, atk_before,
                                     played_non_attack)
            if self.pierce and not was[0]:
                learn("pierce", where())
            if self.momentum and not was[1]:
                learn("momentum", where())
            # 反击：同 pierce，第一次挨那一下就是证据（进攻了两次、挨了远超印在
            # 屏幕上的攻击的一记）。规则和身份一起学。
            if self.counter and not was[2]:
                learn("counter", where())
            # 守势：身份在公开槽位，规则挂在后果上 —— 第一次被反弹
            if getattr(f, "reflected", 0) >= 1:
                learn("guard", where())
            if getattr(f, "mark_hits", 0) >= 1:
                learn("mark", where())
            if getattr(f, "mimic_hits", 0) >= 1:
                learn("mimic", where())
            # 破势：和别的机制一样，线索挂在**被罚的那一步**的后果上 —— 攻击打在封印上落空
            # （`ward_wasted`，也是它的探针）。原先挂在 `ward_opened`（解开过一次）上，那是
            # 答案的后果：不懂的人永远打不开（图库 28 张破势图上 ALL−ward 全是 0），于是
            # 学习者永远认不出它、每条带破势的命都死在第一只破势怪上（登记 9 第一次读数：
            # P′ 0/0/0/96%，results/library/library_packs_learner_cue_ward_opened.json）。
            if getattr(f, "ward_wasted", 0) >= 1:
                learn("ward", where())
            # 蓄力和毒的身份都是公开计数器，所以「学会规则」挂在看见后果上：
            # 蓄力槽满格那一下重击、毒层真的扣了血。
            if charge_before >= max(1, f.enemy.charge_max):
                learn("charge", where())
            # 毒还要求**这一场**叠过毒（毒层比开场时高；开场毒层 poison0 和现在的毒层都在画面上）：毒层跨场带着走，
            # 上一场毒怪留下的余毒在下一场照样扣血。按场计数之后（counted_beliefs，2026-10-21），余毒那一场会被记成
            # 「第二场证据」，一只毒怪就学会了毒，和上面「同一只怪反复伤你不算第二次」相反（审查复现：R2 学会毒的
            # 2,486 次里 98% 靠余毒；E-3 第 3 命 0.405 → 修后 0）。旧计数下一命只算一次，不受影响。
            if poison_before > 0 and (not poison_this_fight or f.state[("me", "poison")] > getattr(f, "poison0", 0)):
                learn("poison", where())

    return Learning
