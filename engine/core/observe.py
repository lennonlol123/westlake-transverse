"""行为指标的被动观察器 —— 接给模型，也接给参考学习者。

===================== 两个指标，主次分明 =====================

主指标 B（纯行为，一个字都不引用证据时刻）
          第 k 次可执行机会的错误率
          新生命第一次可执行机会的答对率
          第一次做对之后，后续又做错的比例

辅助指标 A（依赖客观证据 E）
          E 之后的错误率
          E -> 第一次正确行动的机会距离
          E 之后没等到可执行机会的截尾率
          E 之后做对又复发的比例

          A 的名字是「客观判别性证据已经出现在模型可见信息中」。它**不是**
          「模型认出了机制」，观察器无从知道那件事。它只说：从这一刻起，推断
          这条规则所需的信息已经展示过了。

「做对之后又做错」在两边都有，但定义不同、不可混用：B 的锚点是**第一次做对**
（纯行为，看得见），A 的锚点是**证据出现**（要知道 E）。之前把依赖 E 的那个
放进 B 是分类矛盾 —— 主指标一旦引用证据，就不再是「不猜模型心里想什么」。

不作为评分：模型口头声称「我理解了」。它可能说懂了继续做错，也可能还没说
          清楚但行为已经改变。语言总结用于解释个案，不决定是否学会。

===================== 两条纪律 =====================

1. 只读参与者当时已经在屏幕或日志里看到的东西。**不许读 `Enemy.parts` 等
   隐藏真相。** 这里的做法是包住 `solver.FightBelief` 而不是重写它的阈值 ——
   它的判别规则本来就是按「只用公开信息」设计的（源码里反复写着 reading the
   enemy's real attack "would be privileged"），而复制一条规则然后让它漂移是
   这个代码库最贵的反复缺陷。

2. 证据必须在**真正展示给参与者之后**才记为 E，不能在引擎内部刚算出来时提前
   记。结算发生在回合末，参与者要到下一个屏幕才看得见，所以「E 之后的机会」
   一律要求 (场, 回合) **严格大于** E 的 (场, 回合)。

3. 结算之后立刻死亡、证据从没进入下一次模型输入的那一次，记为「产生了后果但
   没有新的行动机会」—— `after_evidence` 会返回空列表，报表里单列成**截尾**，
   不能记成 0。把它当 0 等于假装参与者在死前已经看见并且来得及反应。

4. 观察器只旁观：不改信念、不改行动、不改 RNG、不改日志、不改提示词。有一条
   配对回归跑同一条随机流、观察器开和关两遍，要求行动、伤害、结局和参与者看得
   见的每一个字节完全一致，只有测量记录不同。

===================== 逐机制的 E =====================

    charge    两件事分开记：
                cue          槽位可见地满了 —— 这是可行动线索
                consequence  大招释放**而且玩家真的因此掉了血**。这个判断在
                             观察器内部做，不接受调用方的说法 —— 「满格且没闪
                             避」并不等于结算：把普通蓄力怪抢杀掉，敌方行动就
                             被取消了，而调用方那个条件照样为真。判据改成结算
                             之后实际掉了血（已扣掉毒），闪避和抢杀两种情况都
                             自然落在 0 上。
    pierce    两级，因为单看一次举盾挨重击**不足以排除狂暴**：
                suspect   举盾之后出现异常伤害 —— 合理怀疑，但有歧义
                confirm   **连续两个举盾回合，伤害明显升级，而 b3 没有变过**。
                          这才排除势头：势头的加成挂在「不格挡」上，格挡会把它
                          压住，所以**相邻**两个举盾回合不会逐级变重。穿透会 ——
                          2x -> 8x -> 24x（实测掉血 18 / 72 / 216）。

                          「相邻」是必要条件，不是修饰：只要求「上一次举盾」而
                          不要求回合相邻，两次之间就可能夹着不举盾的回合，势头
                          正是在那里爬上去的。实测那个版本让 confirm 变成 5 次
                          全误报、0 个真阳性。
                          狂暴和势头把加成算进 `b3` 本身，所以它们打得再重，
                          伤害和 b3 对得上；穿透不抬 `b3`、只在结算时翻倍 ——
                          实测 b3 恒为 9 而伤害 18/72/216。所以「伤害对不上
                          b3」才是公开信息里真正的判别性证据。

                          走过三版弯路，都记在这里：
                          一版「本回合 b3 没上升」—— 势头是在你**不格挡**的上
                          一回合抬 b3，你这回合格挡时它不再动，于是每次怀疑都
                          被判成确认（误报 4.9%/4.9%，全在势头怪身上）。
                          二版「掉血 >= 2 x 真实攻击力」—— 数对了，但读的是
                          `state[("them","atk")]` 的**内部真值**，而屏幕要看
                          `("them","atk") in fight.seen` 才显示。那个 0% 误报
                          是拿模型看不见的信息换来的。所以调用方必须传
                          `atk_shown=None` 来表示「屏幕上是 `?`」。
                          三版「b3 是 `?` 也算确认」—— 势头怪同样可能整场没显示
                          过 b3，所以这条路径把它的误配全放了进来：实测 confirm
                          和 suspect 的误报率又变成一模一样的 4.9%/4.9%。一个和
                          怀疑同误报率的「确认」不是确认。
    enrage    打出非攻击牌之后，公开攻击数上升
    momentum  没有格挡之后，公开攻击数上升
    poison    毒造成扣血或扣上限。**不绑定当前怪的身份** —— 毒跨战斗存在，带毒
              走进一场普通怪的战斗、毒在这一回合发作，那仍然是关于毒这条规则的
              真实证据。A 问的是「规则证据出现了没有」，不是「眼前这只是不是
              毒怪」。

正式的 E -> A 延迟**只从 confirm 起算**。suspect 只用来解释模型为什么可能尝试
改变行为，不进延迟统计。

没有产生任何证据的样本记为**缺失/截尾**，不能当成 0 延迟，也不能读成「反应快」。
"""
import solver
from adventure import TUNING

# ===================== 冻结的 schema =====================
#
# 定义在看到任何模型结果**之前**冻结。跑完 Gemini 不得据其结果修改 —— 判据
# 跟着结果动一次，就再也洗不干净了。要改就升版本号，并说明改的理由和时间。
OBSERVER_SCHEMA_VERSION = "observe-v2"
#
# v1 -> v2（2026-09-18，管线 bug，不是为了迎合结果）：
#   毒的可执行机会发生在**休息点**，而观察器只挂在战斗循环上，所以毒整条机制
#   从没进过 B 表 —— smoke 验收读到 `poison 0/0 机会`，而同一条命的 A 里有 23
#   个毒证据事件。B 少一整条机制不能发版。
#   修法：`note_rest` 把休息处的决定按 (场号, REST_TURN) 记进同一张表。
#   按规矩升版本并重跑整条 smoke chain，不在 v1 名下静默改含义。

# 指标定义与事件类型
SCHEMA = {
    "B": {
        "什么": "纯行为主指标，一个字不引用证据时刻",
        "量": ("第 k 次可执行机会的错误率",
               "新生命第一次可执行机会的答对率",
               "第一次做对之后后续又做错的比例"),
        "分母": "efficiency.turn_opportunities —— 只数答案真的可执行的回合",
    },
    "A": {
        "什么": ("客观判别性证据已经出现在模型可见信息中。"
                 "**不是**「模型认出了机制」—— 观察器无从知道那件事。"),
        "确认性事件": Ellipsis,      # 下面用 Evidence.CONFIRMING 填
        "歧义事件": ("pierce:suspect", "charge:cue"),
        "量": ("E(confirm) 之后的错误率",
               "E(confirm) -> 第一次正确行动的机会距离",
               "E 之后没等到可执行机会的截尾率",
               "E 之后做对又复发的比例"),
        "缺失": "没有确认性证据的样本记为缺失/截尾，不是 0 延迟",
    },
    "C": {
        "什么": "事后因果归因。**本版未实现**，不阻塞本轮。",
        "做法": ("配对反事实：存回合结算前状态，按真实规则结算一次，再关掉目标"
                 "机制、其余状态完全不变结算一次，比较两次结果。"),
        "允许读隐藏真相": True,
        "禁止": ("不得进入模型提示或行动决策；"
                 "不得用于计算「模型看到证据后多久改正」—— 模型当时不知道 C。"),
    },
}

# 验证轨迹上的覆盖率。**这是参考策略轨迹上的读数，不是 A 的固定能力。**
# Gemini 的行动不同，可能主动制造 enrage / momentum / pierce 的对照证据，
# 实际覆盖率会不同 —— 正式结果必须重新报告该模型自己轨迹上的覆盖率。
VALIDATION = {
    "轨迹": "参考学习者 need=1，四张同身份两轮制地图，200 条四命链",
    "样本": {"命": 800, "证据事件": 6001},
    "覆盖": {"charge": 1.00, "poison": 1.00,
             "pierce": 0.00, "enrage": 0.00, "momentum": 0.00},
    "误报": {"charge:cue": 0.0, "charge:consequence": 0.0, "poison:bite": 0.0,
             "pierce:suspect": 0.049, "pierce:confirm": None},
    "注": ("pierce:confirm 在验证轨迹上一次都没产生：参考策略认出穿透之后就不再"
           "举盾，而它的判据要求**相邻**两个举盾回合。这是如实的缺失，不是 0。"),
}


class Evidence:
    """客观判别性证据出现的时刻。只从公开状态读。"""

    KINDS = ("charge:cue", "charge:consequence",
             "pierce:suspect", "pierce:confirm", "enrage",
             "momentum", "poison:bite", "poison:choice")
    # 哪些种类算「确认性」—— 只有这些进正式的 E -> A 延迟。
    CONFIRMING = ("charge:consequence", "pierce:confirm", "enrage",
                  "momentum", "poison:bite")

    def __init__(self):
        self.seen = []                 # (场, 回合, 种类)
        self._first = {}

    def _note(self, kind, where):
        self.seen.append((*where, kind))
        self._first.setdefault(kind, where)

    def first(self, kind):
        return self._first.get(kind)

    def mechanic_first(self, m):
        """一条机制第一次有**任何**信号，含歧义的 suspect。只用于解释。"""
        cands = [self._first[k] for k in self._first if k.split(":")[0] == m]
        return min(cands) if cands else None

    def confirm_first(self, m):
        """一条机制第一次有**确认性**证据 —— 正式延迟只从这里起算。

        返回 None 表示这条轨迹里从没出现过能排除其它解释的公开证据。那是
        **缺失**，不是 0。
        """
        cands = [self._first[k] for k in self.CONFIRMING
                 if k in self._first and k.split(":")[0] == m]
        return min(cands) if cands else None

    def coverage(self, mechanics):
        """A 的证据覆盖率：每条机制有没有拿到确认性证据。"""
        return {m: self.confirm_first(m) is not None for m in mechanics}


class Watcher:
    """挂在一场战斗上：记 E，记第 k 次可执行机会答对没有。

    `belief` 是一只 `solver.FightBelief`，由调用方喂同样的公开观察 —— 阈值
    只有它那一份。
    """

    def __init__(self, evidence, opps, fight_index):
        self.ev, self.opps, self.fi = evidence, opps, fight_index
        self.belief = solver.FightBelief()
        self.belief.always_observe = True
        self._was = (False, False, False)
        self._blocked_losses = []   # (掉血, 屏幕上的 b3) —— 只记举盾的回合
        self._escalated = False

    def _flips(self, turn):
        now = (self.belief.pierce, self.belief.enrage, self.belief.momentum)
        for flag, name in zip(range(3), ("pierce", "enrage", "momentum")):
            if now[flag] and not self._was[flag]:
                # 穿透分两级：异常伤害本身只够怀疑，要公开攻击数没动才叫确认。
                if name == "pierce":
                    self.ev._note("pierce:suspect", (self.fi, turn))
                else:
                    self.ev._note(name, (self.fi, turn))
        self._was = now

    def after_play(self, f, turn, atk_before, kind):
        """出牌之后 —— 攻击数当场上涨是 enrage 的判别证据。"""
        self.belief.observe_play(f, atk_before, kind)
        self._flips(turn)

    def after_end_turn(self, f, turn, hp_before, block_before, poison_before,
                       charge_before, big_fired=None, atk_shown=None):
        # 掉的血对不对得上屏幕上的 b3 —— 把穿透和「单纯打得重」分开的那一格。
        # `atk_shown` 是玩家做决定时屏幕上的那个数，由调用方在 end_turn 之前存。
        lost = max(0, hp_before - poison_before - f.state[("me", "hp")])
        # 举盾的回合才进对照序列。连续举盾伤害逐级升级而 b3 不变 = 穿透；
        # 势头的加成挂在「不格挡」上，被格挡压住，一串举盾回合不会越来越重。
        if block_before > 0:
            self._blocked_losses.append((turn, lost, atk_shown))
            if len(self._blocked_losses) >= 2:
                (t0, l0, a0), (t1, l1, a1) = self._blocked_losses[-2:]
                # 必须是**相邻回合**。只按「列表里相邻」判，两次举盾之间可能
                # 隔着不举盾的回合 —— 势头正好在那里爬上去，于是升级是势头造
                # 的。实测这个缺陷让 confirm 变成 5 次全是误报、0 个真阳性。
                if t1 == t0 + 1 and l0 > 0 and l1 >= l0 * 2 and a0 == a1:
                    self._escalated = True
                    self.ev._note("pierce:confirm", (self.fi, turn))
        # 蓄力：线索和后果分开。线索是槽位可见地满了，后果是大招真的落下。
        if charge_before >= max(1, f.enemy.charge_max):
            self.ev._note("charge:cue", (self.fi, turn))
            # `big_fired` 参数**不再被采信**：观察器自己看结算之后有没有掉血。
            # 闪掉 -> 掉血 0；抢杀取消 -> 掉血 0。两种都不算经历了后果。
            if lost > 0:
                self.ev._note("charge:consequence", (self.fi, turn))
        # 毒：不看这只怪是什么。毒跨战斗存在，带毒进任何一场战斗、毒在这一
        # 回合发作，都是关于毒这条规则的真实证据。
        if poison_before > 0 and f.state[("me", "hp")] < hp_before:
            self.ev._note("poison:bite", (self.fi, turn))
        self.belief.observe_end_turn(f, hp_before, block_before, poison_before,
                                     charge_before)
        self._flips(turn)

    def opportunity(self, turn, mechanic, wrong):
        """第 k 次可执行机会 —— 主指标 B 的原子记录。"""
        self.opps.append((self.fi, turn, mechanic, bool(wrong)))


SCHEMA["A"]["确认性事件"] = Evidence.CONFIRMING


# 休息发生在两场战斗之间。给它一个排在「那一场所有回合之后」的回合坐标，
# 这样 (场, 回合) 的全序仍然是真实时间顺序。
REST_TURN = 10 ** 6


def note_rest(opps, fight_index, wrong):
    """休息处的毒决定 —— B 表的原子记录。

    它不在战斗循环里，所以 `Watcher` 挂不到。v1 因此让毒整条机制缺席 B 表。
    """
    opps.append((fight_index, REST_TURN, "poison", bool(wrong)))


def kth_opportunity_table(opps, mechanics, upto=8):
    """主指标 B：某机制第 k 次可执行机会的错误率。

    纯行为，不引用任何证据时刻。
    """
    out = {}
    for m in mechanics:
        seq = [w for (_, _, mm, w) in opps if mm == m]
        out[m] = [(k + 1, seq[k]) for k in range(min(len(seq), upto))]
    return out


def relapse_after_first_correct(opps, m):
    """主指标 B 的第三项：第一次做对之后，后续又做错的比例。

    锚点是**第一次做对**，不是证据出现 —— 所以它纯粹是行为的函数，不需要知道
    参与者什么时候被展示了什么。和 `after_evidence` 那一版不可混用。
    """
    seq = [(fi, t, w) for (fi, t, mm, w) in opps if mm == m]
    first = next((i for i, x in enumerate(seq) if not x[2]), None)
    if first is None:
        return None
    rest = seq[first + 1:]
    return (sum(1 for x in rest if x[2]), len(rest))


def first_opportunity_of_life(opps, m, life_of):
    """主指标 B 的第二项：每条命里该机制**第一次**可执行机会，答对没有。

    `life_of` 把 (场) 映射到命 —— 观察器本身不知道命的边界。
    """
    out = {}
    for (fi, t, mm, w) in opps:
        if mm != m:
            continue
        L = life_of(fi)
        if L not in out:
            out[L] = not w
    return out


def after_confirm(opps, evidence, m):
    """辅助 A 的正式版本：**确认性**证据之后的可执行机会序列。

    返回 None = 这条轨迹从没拿到确认性证据（**缺失**，不是 0 延迟）。
    返回 []   = 拿到了，但之后再没有可执行机会（**截尾**）。
    """
    e = evidence.confirm_first(m)
    if e is None:
        return None
    return [(fi, t, w) for (fi, t, mm, w) in opps
            if mm == m and (fi, t) > e]


def after_evidence(opps, evidence, m):
    """辅助 A：E 之后的可执行机会序列，(场,回合) **严格大于** E。

    严格大于，因为结算在回合末、参与者要到下一个屏幕才看得见 —— 把 E 当回合
    本身算进去，等于把还没展示的信息算作已知。
    """
    e = evidence.mechanic_first(m)
    if e is None:
        return None
    return [(fi, t, w) for (fi, t, mm, w) in opps
            if mm == m and (fi, t) > e]
