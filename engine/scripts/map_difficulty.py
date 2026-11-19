"""地图难度量尺（docs/antagonist_boss/18_candidate_v3_spec.md §6 + §7 用户 11-04 晚的决定；定义写在 docs/antagonist_boss/19_c10_v3_and_difficulty.md §4）。
不改 core/，不花 API，不读钥匙，单进程（不开进程池）。只读本进程的开关（候选 v3 由环境变量给，同 antagonist_proto），按开关建图、打命、记数。

用户的话：「我们需要一个东西来计算和量化每个地图每个长度的难度，并且保持这个东西在一个范围」；「这个东西应该根据一个公式算出某个值」；
「不控制长度，但控制 d，0.3–0.6 可以，并且全知者只是相当于事先知道所有规则的谨慎玩家」；选 A：D = R1v2 掉的血 ÷ 血量预算 B；
「oracle - r1v2 就等于理论上最优的学习成本」→ 另报 I（lead 的叫法：规则已知时认模式的代价（R1v2 版），是上界，不是最优本身）。

每张图、每一段（图里每一场教学战 / 考试战，和 boss）报：
  R1v2-c（事先知道所有规则、只读公开信息、谨慎；r1v2.VERSION 按开关是 c 或 d）：胜率、掉的血、学费（被阶梯罚掉的血）、回合数、动作数；
  oracle-c（读真值的全知，诊断，不进 D）：同上；
  简单打法面板（fixed_tune 的面板定义：冻结清单 habit 211 类、固定手牌条件习惯 fhc、固定节奏 rhythm、盲线 blind）：最好的过线率（筛图门槛，不进 D）；
  D  = R1v2 平均掉的血 ÷ B（受控的值；用户定的范围 [0.3, 0.6]，只标在整张图 / 整个 boss 上，各段照报不判）；
  I  = (R1v2 平均掉的血 − oracle 平均掉的血) ÷ B（诊断）；
  Λ  = R1v2 平均动作数（出牌 + 结束回合；只报告，不设范围）；oracle 的动作数另报。
  B（整张图）= 进图时的上限血 + 这张图每个休息层的自动补给（上限血 × rest_pct%，按名义量，不看当时缺不缺血）+ 起始牌组里治疗牌的回血量之和；
  B（一段）= R1v2 进这一场时的平均血（同一批命；只算进了这一场的命）；boss 的 B = 进场血（play_boss 满血进场）。
  掉的血 = 每次出牌 / 结束回合让自己的血下降的量之和（死的那一下只算到 0；治疗不抵消，另记 heal）。学费 = 阶梯事件（penalty_ladder.events）
  那一下实际掉的血（打之前的血 − 打之后的血，到 0 为止）；阶梯没装 → None。动作 = 成功的出牌（含路线自动出的治疗）+ END。
随机流：确定性，stream = map-difficulty-v1（参照 / 面板同一个流名、同一组 t：R1v2 与 oracle 的第 t 条命用同一副牌，I 是配对的）。
用法：
  python3 -B scripts/map_difficulty.py OUT.json [--salts=2000007,2000011 | --first=N] [--boss=SALT:p1/p2,...] [--n-ref=20] [--n-oracle=20]
         [--panel=cheap|full|none] [--n-panel=4] [--stream=map-difficulty-v1]
  --first=N：proto_world.two_round_salts(N)（本进程的池子）。--panel=cheap：每组按固定步长取至多 CHEAP 条（habit 25、fhc 25、rhythm 40、blind 20），
  每条 --n-panel 命；full：fixed_tune._panel() 全部、每组 fixed_tune.SAMPLE 命（一张图约 2.6 万条命，只有 lead 跑）。
  OUT 已存在就拒绝（不覆盖）。默认不写任何结果文件名：OUT 必须给。
v2（2026-11-05，v3 build 的独立审查之后）：
  · 世界模式 --world=BOSS_SALT:p1/p2[,…]（要 PROTO_MARKMAP=world）：proto_world.select_world 从 two_round_salts(WORLD_POOL) 选 4 张图 + 这个 boss，
    按世界顺序打；R1v2 的标记证据跨图、跨到 boss 带着走（一个世界一张代号表，spec 18 §2 —— 懂规则的玩家知道，第 2–4 张图不该从零认表）。
    每张图 / boss 报带着证据的 D（主值）和单独打的 D（fresh）。单图模式（--salts / --first / --boss）照旧每张图从零认（替身表），
    所以它给的是「世界第一张图」的 D；对世界里后面的图，单图模式的 D 偏高（审查：标记几乎是 D 的全部）。
  · D_by_mech：D 按机制拆开（这一下掉血时怪的机制；加起来 = D）。现在的候选下盾吸收整个普通一击，蓄力 / 动量 / 破势对 R1v2 几乎是 0，
    D 主要是标记 + 守势的一次试探 —— 量尺把这一点直接印出来，范围要不要靠改标记的倍数 / 敌人血量来够，是用户的事（19 §7）。
  · screen 子命令：python3 -B scripts/map_difficulty.py screen OUT.json IN.json [IN2.json …] --B=nominal|max_hp [--band=0.3,0.6]
    [--ref-win=0.9] [--shortcut=0.4]：按 D 的范围、R1v2 胜率、捷径过线率给每张图 / boss keep / reject / undetermined，另报 D 的分布和
    各机制的份额。--B 必须给（用户还没定 B）。这就是「保持在一个范围」的那一步：量一批 → 用户定范围 → 按范围留图。
  · 面板加 vh（value_habits v2 的 100 套读数值的习惯）；最好的捷径过线率在命数 < SHORTCUT_MIN_N（20）时记 underpowered，
    每段的最好只取进了这一段的命 >= 20 的玩家（少的只计数）。screen 不把 underpowered 当通过。
v3（2026-11-05，候选 v3b：18 §8.1–§8.4；只做地图，用户「boss 先不急」）：
  · 识别：antagonist_proto.POOL == "v3b" 且 GUARDSTART == "map"（_v3b()）。这时地图上没有对局内的随机：固定手牌（FixedPile 不洗牌、
    draw / discard 永远空，补闪抽不到东西）、池里没有标记（标记是唯一按 Fight.rng 每回合抽的机制）、守势开场攻守建图时按图 salt 预抽
    （guard_slot.StartRng 把第一次 randrange(2) 换成预抽值）。每条命还在变的只有 solver._trial_rng 分的种子：洗牌种子（只喂 Fight.rng，
    见上，不再被读到）和每层的 node_seeds（run.choose 在每层唯一的固定节点里 rng.choice —— 一个元素的表，结果不变）。
  · 所以 R1v2、oracle 和面板里每个玩家每张图只打一条命（n_ref = n_oracle = n_panel = 1，强制；显式给别的数就拒绝），
    并**核对**确定性：每个玩家再打 DET_CHECKS 条核对命（另一个流 STREAM + DET_SUFFIX；第 p 个玩家用 t = 1 + DET_CHECKS·p … DET_CHECKS·(p+1)，
    各玩家的种子互不相同），逐场记录（_Seg.fights + 自动补给）必须与第一条命完全相同，不同就 raise（那就是有藏着的随机）。
    核对覆盖参照和面板的每一个玩家（不只前几个；面板命很便宜）。只打一条核对命不够：故意改错（守势开场换回引擎随机）时，同一组种子下
    三张冒烟图漏了一张（各场二选一碰巧相同、且所有玩家共用那组种子）。
    输出每张图带 determinism（核对了多少玩家、用的流和 t）。一条确定的命就是精确值：捷径的 underpowered 门槛（SHORTCUT_MIN_N）在这里不适用
    （min_n = 1）。
  · 没有标记 → 世界模式没有东西可带：v3b 池下 --world 拒绝；boss 不在这一轮：v3b 池下 --boss 拒绝（都给清楚的话）。
  · 开关不是 v3b 时，输出与 v2 逐字相同（除了版本串 / 代码散列 / 日期 / 用时）：v3 环境下在旧树、新树各跑一次小冒烟比对过。"""
import collections, json, pathlib, sys, time, weakref

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
import antagonist_proto as ap
import antagonist_boss as ab

VERSION = "map-difficulty-v3-2026-11-05"           # v3（11-05 晚，候选 v3b）：v3b 下地图确定性 —— 每个玩家一条命 + 核对命逐场相同；v3b 池下拒绝 --world / --boss；
                                                   # 开关不是 v3b 时与 v2 逐字相同。v2 = 世界模式、D_by_mech、screen、vh、underpowered（存档 scratchpad v3b/archive）；v1 = 2026-11-04
STREAM = "map-difficulty-v1"                       # 流名不变：v1 的参照命与 v2 / v3 的单图参照命逐张相同
DET_SUFFIX = "/determinism-check"                  # v3b：核对命的流 = STREAM + DET_SUFFIX
DET_CHECKS = 3                                     # v3b：每个玩家的核对命条数（第一条命是 t = 0；核对命的 t 按玩家错开，见 _det_check）
DET_INFO = ("candidate v3b (PROTO_POOL=v3b, PROTO_GUARDSTART=map): no in-fight randomness on maps -- fixed hand (FixedPile never shuffles; "
            "draw / discard always empty, so the dodge top-up draws nothing), no mark in the pool (the only mechanism that draws from "
            "Fight.rng every turn), guard opening stance pre-drawn per map fight from the map salt (guard_slot.StartRng). What still varies "
            "per trial is only solver._trial_rng's seeds: the shuffle seeds (feed Fight.rng, which nothing reads any more) and the per-layer "
            "node seeds (run.choose picks among the one fixed node per layer). So every player plays ONE life per map (n_ref = n_oracle = "
            "n_panel = 1) and three check lives on another stream (trial indices staggered per player) must give identical per-fight records, else the run raises; "
            "one deterministic life is the exact value, so the shortcut underpowered threshold does not apply (min_n = 1)")
BAND = (0.3, 0.6)                                  # 用户 11-04 晚：「控制 d，0.3–0.6 可以」
CHEAP = dict(habit=25, fhc=25, rhythm=40, blind=20, vh=25)
GROUPS = ("habit", "fhc", "rhythm", "blind", "vh")
SHORTCUT_MIN_N = 20                                # 捷径的最好过线率要至少这么多命才算数（= fixed_tune.N_PANEL，fixed_tune 筛选时每套的命数）；不够 → underpowered
WORLD_POOL = 40                                    # 世界模式：proto_world.select_world 从 two_round_salts(WORLD_POOL) 里选图（同 c10v2 一个窗口 40 张）
B_RULES = ("nominal", "max_hp")                    # screen 的 B：nominal = 上限血 + 名义补给 + 治疗牌（lead 初稿）；max_hp = 只取上限血（对照列）
LEAD_DEFAULTS = dict(ref_win=0.9, shortcut=0.4)    # screen 的另两条门槛：fixed_tune 的 REF_LINE / PASS_LINE（19 §7 第 4 条，待用户定）
ZH_ROLE = dict(teach="教学", test="考试", boss="boss")
ZH_MECH = dict(charge="蓄力", pierce="穿透", momentum="动量", guard="守势", mark="标记", ward="破势", counter="反击")   # 反击：v3b（只在 v3b 池里出现）


def _v3b():
    """候选 v3b 的地图确定性模式（18 §8.1–§8.4）：池 = 蓄力 / 动量 / 反击 / 守势 / 破势（没有标记）且守势开场按图预抽。"""
    return ap.POOL == "v3b" and ap.GUARDSTART == "map"


# ---------------------------------------------------------------- 逐场账本：出牌 / END 前后的血（运行时包一层，退出还原同一个对象）
_LED = {}                                          # id(Fight) → (weakref, 账本 dict)；没登记的（深拷贝的副本等）直接穿过


def _ledger(f):
    hit = _LED.get(id(f))
    return hit[1] if hit is not None and hit[0]() is f else None


def _mk(f):
    """掉血记到哪种机制（研究者侧，读引擎的当前机制；只给 D 的按机制拆分用）。"""
    return "+".join(f.parts) or "none"


class _Tap:
    """包住**当前的** Fight.play / Fight.end_turn（阶梯、固定手牌、boss 层都在下面），退出时还原并核对没被别人换掉（同 c10v2._Tap 的做法）。"""

    def __enter__(self):
        import adventure
        F = adventure.Fight
        self.F, self.saved = F, (F.__dict__["play"], F.__dict__["end_turn"])
        orig_play, orig_end = self.saved

        def play(f, name):
            led = _ledger(f)
            if led is None:
                return orig_play(f, name)
            hp0 = f.state[("me", "hp")]
            r = orig_play(f, name)
            if r is True:
                d = f.state[("me", "hp")] - hp0
                led["plays"] += 1
                if d < 0:
                    led["dmg_play"] += hp0 - max(0, f.state[("me", "hp")])
                    led["by_mech"][_mk(f)] += hp0 - max(0, f.state[("me", "hp")])
                elif d > 0:
                    led["heal"] += d
            return r

        def end_turn(f):
            led = _ledger(f)
            if led is None:
                return orig_end(f)
            hp0 = f.state[("me", "hp")]
            mk = _mk(f)                                # 这一 END 结算时怪的机制（boss 换阶段那一 END 算旧阶段）
            r = orig_end(f)
            led["ends"] += 1
            led["dmg_end"] += max(0, hp0 - max(0, f.state[("me", "hp")]))
            if hp0 > max(0, f.state[("me", "hp")]):
                led["by_mech"][mk] += hp0 - max(0, f.state[("me", "hp")])
            return r
        F.play, F.end_turn = play, end_turn
        self.mine = (play, end_turn)
        return self

    def __exit__(self, *exc):
        F = self.F
        assert (F.__dict__["play"], F.__dict__["end_turn"]) == self.mine, "map_difficulty tap: Fight.play / end_turn replaced underneath"
        F.play, F.end_turn = self.saved
        _LED.clear()
        return False


def _layer_of(run, f):
    for i, L in enumerate(run.layers):
        for n in L.nodes:
            if getattr(n, "enemy", None) is f.enemy:
                return i, n
    return None, None


class _Seg:
    """一条命的逐场记录（solver 的记录钩子）。每一场：层、角色、机制、进场血、出牌 / END / 掉的血 / 治疗（_Tap 记）、结局、阶梯事件。"""
    belief = None

    def __init__(self, run):
        self.run, self.fights, self.rests, self.cur = run, [], [], None

    def enter(self, run, f, kinds):
        i, node = _layer_of(run, f)
        role = "boss" if f.is_boss else (node.role if node is not None else ("teach" if f.enemy.punish < 100 else "test"))
        mech = list(f.parts)
        if f.is_boss and hasattr(f.enemy, "parts_for"):  # boss：两个阶段的机制（进场时 f.parts 只有第一阶段）
            mech = list(dict.fromkeys(tuple(f.enemy.parts_for(False)) + tuple(f.enemy.parts_for(True))))
        self.cur = dict(layer=i, role=role, mech=mech, hp0=f.state[("me", "hp")], max_hp=f.max_hp, plays=0, ends=0, dmg_play=0,
                        dmg_end=0, heal=0, by_mech=collections.Counter())
        _LED[id(f)] = (weakref.ref(f), self.cur)

    def leave(self, f, won):
        c = self.cur
        pl = sys.modules.get("penalty_ladder")
        ev = pl.events(f) if pl is not None and pl.installed() else None
        tuition = None if ev is None else sum(max(0, e["hp_before"] - max(0, e["hp_after_hit"])) for e in ev
                                              if e.get("hp_after_hit") is not None and e.get("hp_before") is not None)
        c.update(won=bool(won), end=ap.ended_by(f) or ("won" if won else "died"), hp1=max(0, f.state[("me", "hp")]), turns=f.turn - 1,
                 lost=c["dmg_play"] + c["dmg_end"], actions=c["plays"] + c["ends"], tuition=tuition,
                 punished=None if ev is None else collections.Counter(f"{e['mech']}/k{e['k']}" for e in ev))
        self.fights.append(c)
        _LED.pop(id(f), None)
        self.cur = None

    def auto_rest(self, run, layer, hp0, hp1):
        self.rests.append(dict(layer=layer, hp0=hp0, hp1=hp1))

    def before_decision(self, f): pass
    def before_play(self, f, c): pass
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, hp_before, block_before, charge_before): pass
    def rest(self, run, mode): pass


# ---------------------------------------------------------------- 命
def _bind(run, salt, kind):
    """PROTO_MARKMAP=world：单张图 / 独立 boss 不属于任何世界 → 绑替身表 salt_mark_table(salt)（同 c10v2._bind_standalone）；salt 下什么也不做。"""
    if ap.MARKMAP == "world":
        ap.set_mark_table(run, ap.salt_mark_table(salt), f"map-difficulty-standalone-{kind}-salt:{int(salt)}")


def _panel_list(mode):
    if mode == "none":
        return {}
    import fixed_tune as ft, value_habits as vh
    p = dict(ft._panel(), vh=vh.habits())            # v2：加读数值的习惯（value_habits v2，候选 v3 的守势格映射下的「看数字」捷径）
    out = {}
    for g in GROUPS:
        keys = list(p[g])
        if mode == "cheap":
            step = max(1, len(keys) // CHEAP[g])
            keys = keys[::step][:CHEAP[g]]
        out[g] = keys
    return out


def _panel_n(mode, g, n_panel):
    import fixed_tune as ft
    if _v3b():
        return 1                                   # v3：v3b 下确定性，一条命就是精确值（full 也一样）；核对命另打（_det_check）
    return ft.SAMPLE.get(g, ft.N_PANEL) if mode == "full" else n_panel     # vh 不在 fixed_tune 的面板里：同 fhc 的命数


_PANEL_CACHE = {}


def _panel_items():
    if not _PANEL_CACHE:
        import solver
        _PANEL_CACHE.update(items=json.loads(ap.LIST.read_text())["items"], blind=solver.blind_gate(full=True))
    return _PANEL_CACHE


def _scripted(who, key):
    """fhc / rhythm / vh 的 (act_policy, route)：fixed_habits.make / fixed_rhythms / value_habits.make（每条命新建）。"""
    import fixed_rhythms as fr, fixed_habits as fh, value_habits as vh
    if who == "rhythm":
        return fr.make_act(fr.parse(key)), fr.route()
    return (vh if who == "vh" else fh).make(key)


def _map_life(run, salt, who, key, t, stream):
    """一条地图命 → (_Seg, won)。参照经 antagonist_boss.play_map（R1v2-c = 默认 c / d 版；oracle-c = oracle_veto=True，同 fixed_tune）；
    habit / blind 同 play_map；fhc / rhythm 同 fixed_tune._life（solver.run_once，habit 的画面）。"""
    import solver
    rec = _Seg(run)
    if who == "R1v2":
        won = ab.play_map(run, salt, "R1v2", t, stream, record=rec)["won"]
    elif who == "oracle":
        won = ab.play_map(run, salt, "oracle", t, stream, record=rec, oracle_veto=True)["won"]
    elif who == "habit":
        won = ab.play_map(run, salt, "habit", t, stream, item=_panel_items()["items"][key], record=rec)["won"]
    elif who == "blind":
        won = ab.play_map(run, salt, "blind", t, stream, item=_panel_items()["blind"][key], record=rec)["won"]
    else:
        act, route = _scripted(who, key)
        rng = solver._trial_rng(ap.SEED ^ salt, stream, t)
        with ap.using_display("habit"):
            won = solver.run_once(run, solver.NONE, route, rng, information="observable", act_policy=act, record=ap.screen("habit", rec),
                                  fight_boss=False)
    return rec, bool(won)


def _boss_life(ctx, who, key, t, stream):
    """一条 boss 命 → (_Seg, won)。参照 / habit / blind 经 antagonist_boss.play_boss；fhc / rhythm 在 boss 这一场上直接 solver.play_fight
    （同 play_boss 的入场：run.trial + 同一套洗牌种子、habit 的画面）。"""
    import solver
    from adventure import TUNING
    run = ctx["run"]
    rec = _Seg(run)
    if who in ("R1v2", "oracle", "habit", "blind"):
        item = None if who in ("R1v2", "oracle") else _panel_items()["items" if who == "habit" else "blind"][key]
        out = ab.play_boss(ctx, who, t, stream, item=item, record=rec, oracle_veto=True if who == "oracle" else None)
        return rec, bool(out["won"])
    act, route = _scripted(who, key)
    rng = solver._trial_rng(ap.SEED ^ ctx["salt"], stream, t)
    shuffles = [rng.randrange(1 << 30) for _ in run.shuffles]
    disp = ap.display_settings("habit")
    saved = {k: TUNING[k] for k in disp}
    try:
        TUNING.update(disp)
        with run.trial(shuffles=shuffles):
            f = next(run.boss_fights())
            won = solver.play_fight(run, f, solver.NONE, run.by_kind, route.heal_at, record=ap.screen("habit", rec), act_policy=act,
                                    information="observable")
    finally:
        TUNING.update(saved)
    return rec, bool(won)


# ---------------------------------------------------------------- 汇总
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _budget(run):
    """整张图的血量预算 B：进图时的上限血 + 每个休息层的名义补给（上限血 × rest_pct%）+ 起始牌组里治疗牌的回血量之和（按牌组，不看用没用）。"""
    from adventure import TUNING
    rests = sum(1 for L in run.layers if L.nodes and L.nodes[0].kind == "rest")
    heal = sum(run.deck[n].amount for n in run.deck_list if run.deck[n].kind == "heal")
    rest_each = run.max_hp * TUNING["rest_pct"] // 100 if TUNING.get("auto_rest") else 0
    return dict(B=run.max_hp + rests * rest_each + heal, max_hp=run.max_hp, rest_layers=rests, rest_each=rest_each, heal_cards=heal,
                auto_rest=bool(TUNING.get("auto_rest")))


def _by_mech(groups):
    """每条命（groups 的一项 = 这条命的若干场）按机制掉的血之和 → 各机制的平均（每条命都算，没掉就是 0）。"""
    keys = sorted({k for g in groups for c in g for k in c["by_mech"]})
    n = len(groups)
    return {k: round(sum(sum(c["by_mech"].get(k, 0) for c in g) for g in groups) / n, 3) for k in keys} if n else {}


def _player_stats(lives):
    """一个玩家在一张图 / 一个 boss 上的命 → 整体 + 每一段（按层）的数。lives = [(rec, won)]。"""
    n = len(lives)
    segs = collections.OrderedDict()
    for rec, _w in lives:
        for c in rec.fights:
            segs.setdefault((c["layer"], c["role"], tuple(c["mech"])), []).append(c)
    whole = dict(n=n, win_rate=round(sum(w for _r, w in lives) / n, 4) if n else None,
                 hp_lost=_mean([sum(c["lost"] for c in r.fights) for r, _w in lives]),
                 heal=_mean([sum(c["heal"] for c in r.fights) for r, _w in lives]),
                 tuition=_mean([None if any(c["tuition"] is None for c in r.fights) else sum(c["tuition"] for c in r.fights) for r, _w in lives]),
                 turns=_mean([sum(c["turns"] for c in r.fights) for r, _w in lives]),
                 actions=_mean([sum(c["actions"] for c in r.fights) for r, _w in lives]),
                 hp_lost_by_mech=_by_mech([r.fights for r, _w in lives]),
                 ends=dict(collections.Counter(next((c["end"] for c in r.fights if not c["won"]), "won") for r, _w in lives)))
    per = []
    for (layer, role, mech), cs in segs.items():
        pun = collections.Counter()
        for c in cs:
            pun.update(c["punished"] or {})
        per.append(dict(layer=layer, role=role, mech=list(mech), entered=len(cs), survived=sum(c["won"] for c in cs),
                        survive_rate=round(sum(c["won"] for c in cs) / len(cs), 4), hp_entry=_mean([c["hp0"] for c in cs]),
                        hp_lost=_mean([c["lost"] for c in cs]), heal=_mean([c["heal"] for c in cs]), tuition=_mean([c["tuition"] for c in cs]),
                        turns=_mean([c["turns"] for c in cs]), actions=_mean([c["actions"] for c in cs]), punished=dict(sorted(pun.items())),
                        hp_lost_by_mech=_by_mech([[c] for c in cs])))
    return dict(whole=whole, segments=per)


def _ratio(a, b):
    return None if a is None or not b else round(a / b, 4)


def _compose(B, refs, panel, max_hp=None):
    """D / I / Λ 与各段的同样数；panel = {组: {键: [(rec, won)]}} → 最好的过线率（整体、每段）。
    v3：v3b 下一条确定的命就是精确值，min_n = 1（underpowered 只对抽样的命有意义）；不是 v3b 时 min_n = SHORTCUT_MIN_N（同 v2）。"""
    min_n = 1 if _v3b() else SHORTCUT_MIN_N
    r, o = refs["R1v2"], refs.get("oracle")
    D = _ratio(r["whole"]["hp_lost"], B)
    D_by_mech = {k: _ratio(v, B) for k, v in r["whole"]["hp_lost_by_mech"].items()}   # v2：D 按机制拆开（加起来 = D；哪种机制在驱动 D）
    I = None if o is None or r["whole"]["hp_lost"] is None or o["whole"]["hp_lost"] is None else _ratio(r["whole"]["hp_lost"] - o["whole"]["hp_lost"], B)
    oseg = {(s["layer"], s["role"]): s for s in (o["segments"] if o else [])}
    segs = []
    for s in r["segments"]:
        so = oseg.get((s["layer"], s["role"]))
        Bs = s["hp_entry"]
        segs.append(dict(layer=s["layer"], role=s["role"], mech=s["mech"], B=Bs, D=_ratio(s["hp_lost"], Bs),
                         I=None if so is None or so["hp_lost"] is None or s["hp_lost"] is None else _ratio(s["hp_lost"] - so["hp_lost"], Bs),
                         Lambda=s["actions"], R1v2=s, oracle=so))
    best = dict(overall=None, by_group={}, by_segment={}, by_segment_underpowered={}, min_n=min_n)
    for g, players in panel.items():
        rates = {k: sum(w for _r, w in lv) / len(lv) for k, lv in players.items() if lv}
        if rates:
            k = max(rates, key=lambda x: (rates[x], -list(players).index(x)))
            best["by_group"][g] = dict(key=str(k), pass_rate=round(rates[k], 4), n=len(players[k]), players=len(rates),
                                       underpowered=len(players[k]) < min_n)
            if best["overall"] is None or rates[k] > best["overall"]["pass_rate"]:
                best["overall"] = dict(group=g, key=str(k), pass_rate=round(rates[k], 4), n=len(players[k]),
                                       underpowered=len(players[k]) < min_n)
        for k, lv in players.items():
            st = _player_stats(lv)
            for s in st["segments"]:
                sk = f"{s['layer']}|{s['role']}"
                cur = best["by_segment"].get(sk)
                if s["entered"] < min_n:                   # v2：进了这一段的命太少的不当捷径的证据（只计数）；v3b 下 min_n = 1
                    best["by_segment_underpowered"][sk] = best["by_segment_underpowered"].get(sk, 0) + 1
                    continue
                if cur is None or s["survive_rate"] > cur["survive_rate"]:
                    best["by_segment"][sk] = dict(group=g, key=str(k), survive_rate=s["survive_rate"], entered=s["entered"])
    band = None if D is None else BAND[0] <= D <= BAND[1]
    # 对照列（不受控、只报告）：B 只取进图时的上限血（不算休息层的名义补给和治疗牌）—— 名义补给在 R1v2 满血时用不上，B 的取法要用户定（19 §4.4）
    alt = None if max_hp is None else dict(D_max_hp=_ratio(r["whole"]["hp_lost"], max_hp), B_max_hp=max_hp)
    return dict(B=B, D=D, D_in_band=band, band=list(BAND), D_by_mech=D_by_mech, I=I, Lambda=r["whole"]["actions"], **({"alt": alt} if alt else {}),
                Lambda_oracle=None if o is None else o["whole"]["actions"], segments=segs, panel_best=best)


def measure_map(salt, args, panel_keys):
    run = ap.build(salt)
    _bind(run, salt, "map")
    layers = [dict(layer=i, kind=L.nodes[0].kind, role=getattr(L.nodes[0], "role", None), mech=getattr(L.nodes[0], "behaviour", None))
              for i, L in enumerate(run.layers)]
    bud = _budget(run)
    det = _v3b()
    chk = dict(stream=args["stream"] + DET_SUFFIX, checks_per_player=DET_CHECKS, refs=0, panel_players=0) if det else None
    refs = {}
    for who, n in (("R1v2", args["n_ref"]), ("oracle", args["n_oracle"])):
        lives = [_map_life(run, salt, who, None, t, args["stream"]) for t in range(n)]
        if det:
            _det_check(run, salt, who, None, lives, chk, "refs")
        refs[who] = _player_stats(lives)
    panel = {}
    for g, keys in panel_keys.items():
        panel[g] = {}
        for k in keys:
            lives = [_map_life(run, salt, g, k, t, args["stream"]) for t in range(_panel_n(args["panel"], g, args["n_panel"]))]
            if det:
                _det_check(run, salt, g, k, lives, chk, "panel_players")
            panel[g][k] = lives
    out = dict(salt=salt, layers=layers, budget=bud, refs=refs, **_compose(bud["B"], refs, panel, max_hp=bud["max_hp"]))
    if det:
        out["determinism"] = dict(chk, identical=True, rule=f"every player: one life (t = 0) + {DET_CHECKS} check lives on another stream (t staggered per player); "
                                                             "per-fight records and auto rests identical (else raise)")
    return out


def _det_check(run, salt, who, key, lives, chk, slot):
    """v3b：一条命（t = 0）之外再打 DET_CHECKS 条核对命（另一个流；t 按玩家错开），逐场记录（含自动补给）必须相同；不同 → 有藏着的随机 → raise。"""
    assert len(lives) == 1, ("v3b: one life per player expected", who, key, len(lives))
    p = chk["refs"] + chk["panel_players"]          # 第 p 个玩家：核对命的 t 互不重叠（各玩家的洗牌 / 节点种子都不同）
    a = _plain(lives[0]) + (lives[0][0].rests,)
    for t in range(1 + DET_CHECKS * p, 1 + DET_CHECKS * (p + 1)):
        again = _map_life(run, salt, who, key, t, chk["stream"])
        b = _plain(again) + (again[0].rests,)
        if a != b:
            break
    if a != b:
        diff = next((i for i, (x, y) in enumerate(zip(a[1], b[1])) if x != y), min(len(a[1]), len(b[1])))
        raise RuntimeError(f"map_difficulty v3b determinism check FAILED on map {salt}: player {who} {key!r} -- the life at "
                           f"(stream {chk['stream'][:-len(DET_SUFFIX)]!r}, t=0) and the check life (stream {chk['stream']!r}, t={t}) "
                           f"differ (won {a[0]} vs {b[0]}; fights {len(a[1])} vs {len(b[1])}; first differing fight #{diff}: "
                           f"{a[1][diff] if diff < len(a[1]) else None} vs {b[1][diff] if diff < len(b[1]) else None}; rests {a[2]} vs {b[2]}). "
                           "That is hidden in-fight randomness under PROTO_POOL=v3b / PROTO_GUARDSTART=map: one life per player is not valid.")
    chk[slot] += 1


def measure_boss(salt, pair, args, panel_keys):
    ctx = ab.build_boss(salt, pair, 0)
    _bind(ctx["run"], salt, "boss")
    refs = {}
    for who, n in (("R1v2", args["n_ref"]), ("oracle", args["n_oracle"])):
        refs[who] = _player_stats([_boss_life(ctx, who, None, t, args["stream"]) for t in range(n)])
    panel = {g: {k: [_boss_life(ctx, g, k, t, args["stream"]) for t in range(_panel_n(args["panel"], g, args["n_panel"]))] for k in keys}
             for g, keys in panel_keys.items()}
    B = refs["R1v2"]["segments"][0]["hp_entry"] if refs["R1v2"]["segments"] else None
    return dict(salt=salt, pair=list(pair), budget=dict(B=B, rule="boss entry hp (play_boss enters at full hp)"), refs=refs,
                **_compose(B, refs, panel))


# ---------------------------------------------------------------- 世界模式（v2）：标记表跨图带着走
def _new_r1v2():
    import inspect, devworld, r1v2
    P = r1v2.R1v2Policy
    return P(devworld.R1_VARIANT) if len(inspect.signature(P).parameters) else P()      # 同 antagonist_boss._policy


def _inherit(p, prev):
    """世界模式：把同一个世界里上一张图 / 上一场的标记证据（Cautious.draws / plays：每次代号亮出时的累计出牌、每次在亮着的代号下出牌挨没挨打）
    交给新建的策略。PROTO_MARKMAP=world 下一个世界一张代号表（spec 18 §2），懂规则的玩家知道这一点，所以证据跨图有效；按图的东西
    （守势格的映射 gcode、视图、每场的状态、自己的攻击）不带。prev = None → 原样（新建的策略，没有证据）。"""
    if prev is not None:
        p.draws, p.plays, p._post = list(prev.draws), list(prev.plays), None
    return p


def _r1v2_map_with(run, salt, t, stream, rec, p):
    """= antagonist_boss.play_map(run, salt, "R1v2", t, stream, record=rec) 的出牌那一半（同一个随机流、知识、路线、画面、信念），只是策略由调用方给。
    p 是新建的、没带证据的策略时与 play_map 逐张相同：measure_world 在每个世界的第 1 张图上核对（identity_map0）。"""
    import solver, r1v2
    ap.require_mark_table(run)
    rng = solver._trial_rng(ap.SEED ^ salt, stream, t)
    with ap.using_display("R1v2"):
        won = solver.run_once(run, getattr(r1v2, "KNOW", solver.ALL - {"mark"}), solver.SCREEN_ROUTES[9], rng, record=ap.screen("R1v2", rec),
                              boss_entry=None, fight_boss=False, information="observable", act_policy=p.act, heal_veto=p.heal_veto,
                              belief_cls=r1v2.R1v2Belief)
    return bool(won)


def _r1v2_boss_with(ctx, t, stream, rec, p):
    """= antagonist_boss.play_boss(ctx, "R1v2", t, stream, record=rec) 的出牌那一半（同一副洗牌、画面、Trace 包装、满血入场），策略由调用方给。"""
    import solver, r1v2
    from adventure import TUNING
    run = ctx["run"]
    ap.require_mark_table(run)
    rng = solver._trial_rng(ap.SEED ^ ctx["salt"], stream, t)
    shuffles = [rng.randrange(1 << 30) for _ in run.shuffles]
    disp = ap.display_settings("R1v2")
    tr = ab.Trace(rec, track_seen=ap.tracks_screen("R1v2"))
    route = solver.SCREEN_ROUTES[9]
    saved = {k: TUNING[k] for k in disp}
    try:
        TUNING.update(disp)
        with run.trial(shuffles=shuffles):
            f = next(run.boss_fights())
            won = solver.play_fight(run, f, getattr(r1v2, "KNOW", solver.ALL - {"mark"}), run.by_kind, route.heal_at, record=tr,
                                    enrage_budget=route.enrage_budget, information="observable", act_policy=p.act, heal_veto=p.heal_veto,
                                    belief_cls=r1v2.R1v2Belief)
    finally:
        TUNING.update(saved)
    return bool(won)


def _plain(rec_won):
    """比较用：一条命的逐场记录（Counter → dict）。"""
    rec, won = rec_won
    return won, [{k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in c.items()} for c in rec.fights]


def measure_world(bsalt, pair, args, panel_keys):
    """一个世界（proto_world.select_world：从 two_round_salts(WORLD_POOL) 里按规则选 4 张图 + 这个 boss）。每条命 t：
    R1v2_carry = 同一个 t 依次打图 1–4、再打 boss，标记证据带着走（_inherit；每张图 / boss 新建策略）——这是世界里第 i 张图的 D（主值）；
    R1v2 = 每张图单独打（同一张世界表、新策略，= 单图模式的 R1v2，只是表是这个世界的）—— D_fresh（对照：不带证据时的 D）；
    全知、面板 = 每张图单独打（它们不学标记表）。同一个流、同一组 t，所以各列配对。图 1 的 R1v2_carry 与 R1v2 必须逐张相同（identity_map0）。"""
    import proto_world as pw
    if ap.MARKMAP != "world":
        raise SystemExit("--world needs PROTO_MARKMAP=world: only then is there one mark table per world, so the evidence carries "
                         "from map to map (under salt every map has its own table and nothing carries)")
    spec = pw.select_world(pw.two_round_salts(WORLD_POOL), tuple(pair), bsalt)
    runs = pw.world_runs(spec)
    salts = [m["salt"] for m in spec["maps"]]
    n = args["n_ref"]
    carry = [[] for _ in salts]
    boss_carry = []
    for t in range(n):
        prev = None
        for i, (run, s) in enumerate(zip(runs["maps"], salts)):
            rec, p = _Seg(run), _inherit(_new_r1v2(), prev)
            carry[i].append((rec, _r1v2_map_with(run, s, t, args["stream"], rec, p)))
            prev = p
        rec, p = _Seg(runs["boss"]["run"]), _inherit(_new_r1v2(), prev)
        boss_carry.append((rec, _r1v2_boss_with(runs["boss"], t, args["stream"], rec, p)))
    maps, ident = [], None
    for i, (run, s) in enumerate(zip(runs["maps"], salts)):
        layers = [dict(layer=j, kind=L.nodes[0].kind, role=getattr(L.nodes[0], "role", None), mech=getattr(L.nodes[0], "behaviour", None))
                  for j, L in enumerate(run.layers)]
        bud = _budget(run)
        fresh = [_map_life(run, s, "R1v2", None, t, args["stream"]) for t in range(n)]
        if i == 0:
            ident = [_plain(x) for x in fresh] == [_plain(x) for x in carry[0]]
        refs = dict(R1v2=_player_stats(carry[i]), oracle=_player_stats([_map_life(run, s, "oracle", None, t, args["stream"])
                                                                        for t in range(args["n_oracle"])]),
                    R1v2_fresh=_player_stats(fresh))
        panel = {g: {k: [_map_life(run, s, g, k, t, args["stream"]) for t in range(_panel_n(args["panel"], g, args["n_panel"]))] for k in keys}
                 for g, keys in panel_keys.items()}
        m = dict(salt=s, world_index=i, layers=layers, budget=bud, refs=refs, **_compose(bud["B"], refs, panel, max_hp=bud["max_hp"]))
        m["fresh"] = dict(D=_ratio(refs["R1v2_fresh"]["whole"]["hp_lost"], bud["B"]),
                          D_max_hp=_ratio(refs["R1v2_fresh"]["whole"]["hp_lost"], bud["max_hp"]),
                          D_by_mech={k: _ratio(v, bud["B"]) for k, v in refs["R1v2_fresh"]["whole"]["hp_lost_by_mech"].items()},
                          win_rate=refs["R1v2_fresh"]["whole"]["win_rate"])
        maps.append(m)
    ctx = runs["boss"]
    brefs = dict(R1v2=_player_stats(boss_carry),
                 oracle=_player_stats([_boss_life(ctx, "oracle", None, t, args["stream"]) for t in range(args["n_oracle"])]),
                 R1v2_fresh=_player_stats([_boss_life(ctx, "R1v2", None, t, args["stream"]) for t in range(n)]))
    bpanel = {g: {k: [_boss_life(ctx, g, k, t, args["stream"]) for t in range(_panel_n(args["panel"], g, args["n_panel"]))] for k in keys}
              for g, keys in panel_keys.items()}
    B = brefs["R1v2"]["segments"][0]["hp_entry"] if brefs["R1v2"]["segments"] else None
    boss = dict(salt=bsalt, pair=list(pair), world_index=len(salts), budget=dict(B=B, rule="boss entry hp (play_boss enters at full hp)"),
                refs=brefs, **_compose(B, brefs, bpanel))
    boss["fresh"] = dict(D=_ratio(brefs["R1v2_fresh"]["whole"]["hp_lost"], B), win_rate=brefs["R1v2_fresh"]["whole"]["win_rate"])
    return dict(id=spec["id"], spec=spec, maps=maps, boss=boss, identity_map0=ident,
                rule="R1v2 carries its mark evidence across the world's maps and boss (one table per world); D = carried; fresh = each map alone")


def _fmt(x, pct=False):
    if x is None:
        return "—"
    return f"{x:.0%}" if pct else (f"{x:.2f}" if isinstance(x, float) else str(x))


def _pb_note(pb):
    if not pb:
        return ""
    return "（" + pb["group"] + ("，n=%d 命不够" % pb["n"] if pb.get("underpowered") else "") + "）"


def table_zh(rep):
    """简短的中文表：每张图 / boss 一段，每一段一行。"""
    out = []
    entries = [(None, m) for m in rep["maps"] + rep["bosses"]]
    for w in rep.get("worlds", ()):
        entries += [(w["id"], m) for m in w["maps"] + [w["boss"]]]
    for wid, m in entries:
        name = f"图 {m['salt']}" if "pair" not in m else f"boss {m['salt']} {ZH_MECH.get(m['pair'][0])}→{ZH_MECH.get(m['pair'][1])}"
        if wid is not None:
            name = f"世界 {wid} 第 {m['world_index'] + 1} 个（{name}，标记证据带着走；单独打 D={_fmt(m['fresh']['D'])}）"
        r, o = m["refs"]["R1v2"]["whole"], m["refs"]["oracle"]["whole"]
        pb = m["panel_best"]["overall"]
        alt = f"（只按上限血 {_fmt(m['alt']['D_max_hp'])}）" if m.get("alt") else ""
        out.append(f"{name}：B={m['B']}  D={_fmt(m['D'])}{alt}（{'在' if m['D_in_band'] else '不在' if m['D_in_band'] is not None else '—'}"
                   f" [{BAND[0]}, {BAND[1]}] 里）  I={_fmt(m['I'])}  Λ={_fmt(m['Lambda'])}（全知 {_fmt(m['Lambda_oracle'])}）  "
                   f"R1v2 胜率 {_fmt(r['win_rate'], True)}、掉血 {_fmt(r['hp_lost'])}、学费 {_fmt(r['tuition'])}；"
                   f"全知 胜率 {_fmt(o['win_rate'], True)}、掉血 {_fmt(o['hp_lost'])}；"
                   f"捷径最好 {_fmt(pb and pb['pass_rate'], True)}{_pb_note(pb)}")
        out.append("  D 按机制：" + "  ".join(f"{'+'.join(ZH_MECH.get(x, x) for x in k.split('+'))} {_fmt(v)}" for k, v in m["D_by_mech"].items()))
        if m.get("determinism"):                       # v3：v3b 下才有
            d = m["determinism"]
            out.append(f"  确定性（v3b）：每个玩家一条命；{d['checks_per_player']} 条核对命（流 {d['stream']}）逐场相同 —— 参照 {d['refs']} 个、面板 {d['panel_players']} 个")
        out.append("  段            D      I      Λ     R1v2 过 / 掉血 / 学费 / 回合      全知 过 / 掉血 / 动作     捷径最好（这一段）")
        for s in m["segments"]:
            rs, os_ = s["R1v2"], s["oracle"] or {}
            bs = m["panel_best"]["by_segment"].get(f"{s['layer']}|{s['role']}")
            label = f"{ZH_ROLE.get(s['role'], s['role'])} {'/'.join(ZH_MECH.get(x, x) for x in s['mech'])}"
            out.append(f"  {label:12} {_fmt(s['D']):>6} {_fmt(s['I']):>6} {_fmt(s['Lambda']):>6}   "
                       f"{_fmt(rs['survive_rate'], True):>5} / {_fmt(rs['hp_lost']):>6} / {_fmt(rs['tuition']):>5} / {_fmt(rs['turns']):>5}   "
                       f"{_fmt(os_.get('survive_rate'), True):>5} / {_fmt(os_.get('hp_lost')):>6} / {_fmt(os_.get('actions')):>5}   "
                       f"{_fmt(bs and bs['survive_rate'], True)}")
    return out


def _parse(argv):
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) != 1:
        raise SystemExit(__doc__)
    args = dict(out=pos[0], salts=None, first=None, boss=[], world=[], n_ref=20, n_oracle=20, panel="cheap", n_panel=4, stream=STREAM)
    for a in argv:
        if not a.startswith("--"):
            continue
        k, _, v = a[2:].partition("=")
        if k == "salts":
            args["salts"] = [int(x) for x in v.split(",") if x]
        elif k == "first":
            args["first"] = int(v)
        elif k in ("boss", "world"):
            for item in v.split(","):
                s, _, pr = item.partition(":")
                p1, _, p2 = pr.replace(">", "/").partition("/")        # SALT:p1/p2（命令行里 > 是重定向，用 /；> 也认）
                args[k].append((int(s), (p1, p2)))
        elif k in ("n-ref", "n-oracle", "n-panel"):
            args[k.replace("-", "_")] = int(v)
            args.setdefault("_explicit", set()).add(k.replace("-", "_"))   # v3：v3b 下显式给的命数要是 1（main 核对；不进输出）
        elif k == "panel":
            if v not in ("cheap", "full", "none"):
                raise SystemExit("--panel=cheap|full|none")
            args["panel"] = v
        elif k == "stream":
            args["stream"] = v
        else:
            raise SystemExit(f"unknown flag {a}")
    return args


# ---------------------------------------------------------------- 筛图（v2）：把量好的图按 D 的范围筛（用户：「保持这个东西在一个范围」）
def _quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    q = lambda f: xs[min(len(xs) - 1, int(f * (len(xs) - 1) + 0.5))]
    return dict(n=len(xs), min=xs[0], q25=q(0.25), median=q(0.5), q75=q(0.75), max=xs[-1])


def screen(argv):
    """screen OUT.json IN.json [IN2.json …] --B=nominal|max_hp [--band=lo,hi] [--ref-win=0.9] [--shortcut=0.4]
    读 measure 的输出（单图、boss、世界模式的图和 boss），每一项给 keep / reject / undetermined：
      D（按 --B 取：nominal = 上限血 + 名义补给 + 治疗牌；max_hp = 只取上限血；boss 两种都是进场血；世界模式取带着证据的 D）在 band 里；
      R1v2 胜率 >= --ref-win；最好的捷径过线率 < --shortcut。捷径命数不够（underpowered）或没跑面板 → 这一条记 undetermined，不当作通过。
    --B 必须给：B 的取法用户还没定（19 §7 第 1 条），筛图不替用户选。--band 默认用户定的 [0.3, 0.6]；--ref-win / --shortcut 默认 fixed_tune 的
    REF_LINE / PASS_LINE（lead 的默认，19 §7 第 4 条待用户定）。另报 D 的分布（两种 B 都报）和各机制在 D 里的平均份额（哪种机制在驱动 D）。"""
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) < 2:
        raise SystemExit(screen.__doc__)
    opt = dict(B=None, band=BAND, ref_win=LEAD_DEFAULTS["ref_win"], shortcut=LEAD_DEFAULTS["shortcut"])
    for a in argv:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            if k == "B":
                if v not in B_RULES:
                    raise SystemExit(f"--B={v!r}: one of {B_RULES}")
                opt["B"] = v
            elif k == "band":
                lo, hi = (float(x) for x in v.split(","))
                opt["band"] = (lo, hi)
            elif k in ("ref-win", "shortcut"):
                opt[k.replace("-", "_")] = float(v)
            else:
                raise SystemExit(f"unknown flag {a}")
    if opt["B"] is None:
        raise SystemExit("screen needs --B=nominal or --B=max_hp: the user has not fixed how B is counted (doc 19 section 7, item 1)")
    out = pathlib.Path(pos[0]).resolve()
    ap.refuse_overwrite(out)
    reps = [json.loads(pathlib.Path(x).read_text()) for x in pos[1:]]
    keys = {json.dumps([r.get("version"), r.get("proto"), r.get("switches"), r.get("r1v2_version")], sort_keys=True, default=str) for r in reps}
    if len(keys) != 1:
        raise SystemExit("the input reports were measured under different versions / switches; screen them separately")
    lo, hi = opt["band"]
    rows = []
    for src, r in zip(pos[1:], reps):
        items = [(None, m) for m in r.get("maps", []) + r.get("bosses", [])]
        for w in r.get("worlds", []):
            items += [(w["id"], m) for m in w["maps"] + [w["boss"]]]
        for wid, m in items:
            boss = "pair" in m
            D_nom = m["D"]
            D_max = m["D"] if boss else (m.get("alt") or {}).get("D_max_hp")
            D = D_nom if opt["B"] == "nominal" else D_max
            win = m["refs"]["R1v2"]["whole"]["win_rate"]
            pb = m["panel_best"]["overall"]
            reasons, undet = [], []
            if D is None or not lo <= D <= hi:
                reasons.append(f"D={D} outside [{lo}, {hi}]")
            if win is None or win < opt["ref_win"]:
                reasons.append(f"R1v2 win {win} < {opt['ref_win']}")
            if pb is None:
                undet.append("no panel run")
            elif pb["pass_rate"] >= opt["shortcut"] and not pb.get("underpowered"):
                reasons.append(f"shortcut {pb['group']} {pb['key']} {pb['pass_rate']} >= {opt['shortcut']}")
            elif pb.get("underpowered"):
                undet.append(f"shortcut best from n={pb['n']} < {SHORTCUT_MIN_N} lives")
            rows.append(dict(source=src, world=wid, kind="boss" if boss else "map", salt=m["salt"], pair=m.get("pair"),
                             world_index=m.get("world_index"), D=D, D_nominal=D_nom, D_max_hp=D_max, D_fresh=(m.get("fresh") or {}).get("D"),
                             D_by_mech=m.get("D_by_mech"), R1v2_win=win, shortcut=pb,
                             verdict="reject" if reasons else "undetermined" if undet else "keep", reasons=reasons, undetermined=undet))
    shares = collections.defaultdict(list)
    mrows = [x for x in rows if x["kind"] == "map" and sum((x["D_by_mech"] or {}).values())]
    mkeys = sorted({k for x in mrows for k in x["D_by_mech"]})
    for x in mrows:                                    # 每张图里各机制占 D 的份额（这张图没有的机制记 0），再对图取平均：份额加起来 = 1
        tot = sum(x["D_by_mech"].values())
        for k in mkeys:
            shares[k].append(x["D_by_mech"].get(k, 0) / tot)
    rep = dict(version=VERSION, run_date=time.strftime("%Y-%m-%d %H:%M"), inputs=pos[1:], options=dict(opt, band=list(opt["band"])),
               defaults_pending_user=dict(B="not fixed (doc 19 section 7, item 1)", ref_win=LEAD_DEFAULTS["ref_win"], shortcut=LEAD_DEFAULTS["shortcut"]),
               counts=dict(collections.Counter(x["verdict"] for x in rows)), keep=[x["salt"] for x in rows if x["verdict"] == "keep"],
               distribution=dict(D=_quantiles([x["D"] for x in rows if x["kind"] == "map"]),
                                 D_nominal=_quantiles([x["D_nominal"] for x in rows if x["kind"] == "map"]),
                                 D_max_hp=_quantiles([x["D_max_hp"] for x in rows if x["kind"] == "map"]),
                                 boss_D=_quantiles([x["D"] for x in rows if x["kind"] == "boss"])),
               mean_share_of_D_by_mech={k: round(sum(v) / len(v), 3) for k, v in sorted(shares.items())}, rows=rows)
    zh = [f"筛图：B = {opt['B']}，范围 [{lo}, {hi}]，R1v2 胜率 >= {opt['ref_win']}，捷径 < {opt['shortcut']}（命数 < {SHORTCUT_MIN_N} 的捷径记「待定」）",
          f"  结果 {rep['counts']}；留下 {rep['keep']}",
          f"  图的 D 分布 {rep['distribution']['D']}；只按上限血 {rep['distribution']['D_max_hp']}",
          "  各机制在图的 D 里平均占多少：" + "  ".join(f"{ZH_MECH.get(k, k)} {v:.0%}" for k, v in rep["mean_share_of_D_by_mech"].items())]
    rep["table_zh"] = zh
    print("\n".join(zh), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    ap.refuse_overwrite(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    print(f"-> {out}", flush=True)
    return rep


def main(argv=None):
    t0 = time.time()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["screen"]:
        return screen(argv[1:])
    args = _parse(argv)
    explicit = args.pop("_explicit", set())
    out = pathlib.Path(args["out"]).resolve()
    ap.refuse_overwrite(out)
    if ap.POOL == "v3b":                               # v3：候选 v3b 只做地图（用户 11-05「boss 先不急」）
        if args["boss"]:
            raise SystemExit("--boss under PROTO_POOL=v3b is out of scope for map_difficulty v3: the v3b boss (ordered pairs, the x3 non-lethal "
                             "first hit at the phase switch, 18 section 8.4) is not built yet (user 11-05: boss later, maps first). Measure maps only.")
        if args["world"]:
            raise SystemExit("--world under PROTO_POOL=v3b is refused: world mode exists to carry the mark evidence from map to map, and the "
                             "v3b pool has no mark (18 section 8.1), so nothing carries. Measure each map alone with --salts / --first.")
        if not _v3b():
            print(f"  note: PROTO_POOL=v3b with PROTO_GUARDSTART={ap.GUARDSTART}: the guard opening stance is still drawn in the fight, so the "
                  "maps are NOT deterministic; measuring with sampled lives as in v2", flush=True)
    if _v3b():
        bad = {k: args[k] for k in sorted(explicit) if args[k] != 1}
        if bad:
            raise SystemExit(f"{bad} under v3b (PROTO_POOL=v3b, PROTO_GUARDSTART=map): the maps are deterministic, one life per player is the "
                             "exact value (and check lives assert it); drop these flags or pass 1")
        args.update(n_ref=1, n_oracle=1, n_panel=1)
    ab.setup_boss()
    if args["salts"] is None:
        import proto_world as pw
        args["salts"] = [] if (args["world"] and args["first"] is None) else pw.two_round_salts(args["first"] or 2)
    panel_keys = _panel_list(args["panel"])
    rep = dict(version=VERSION, run_date=time.strftime("%Y-%m-%d %H:%M"), proto=ap.settings(), switches=ap._now(),
               r1v2_version=__import__("r1v2").VERSION, args={k: v for k, v in args.items() if k != "out"},
               panel_sizes={g: len(v) for g, v in panel_keys.items()},
               definitions=dict(D="R1v2 mean hp lost / B (controlled; user band [0.3, 0.6] at the map / boss level)",
                                I="(R1v2 mean hp lost - oracle mean hp lost) / B (diagnostic: the cost of identifying the patterns with the "
                                  "rules known, R1v2's version; an upper bound, not the optimum)",
                                Lambda="R1v2 mean actions (cards played incl. auto heals + ENDs); report only",
                                B_map="max hp at map entry + nominal auto resupply per rest layer (max hp x rest_pct%) + heal card amounts in "
                                      "the starting deck", B_segment="R1v2 mean hp at entry to that fight (lives that entered it)",
                                hp_lost="sum of hp drops over card plays and ENDs (a death counts to 0; heals do not offset)",
                                tuition="hp actually lost to penalty-ladder events (penalty_ladder.events: hp before - hp after the hit, to 0)",
                                panel="best pass rate over the simple panel (fixed_tune._panel groups habit / fhc / rhythm / blind, plus vh = "
                                      "value_habits v2); a screening threshold, not part of D; with few lives per player the max is biased upward, "
                                      f"so a best with n < {SHORTCUT_MIN_N} lives is marked underpowered (and segments entered by fewer are skipped)",
                                D_by_mech="hp lost per mechanism (the engine's current mechanism at the play / END that cost the hp) / B; sums to D",
                                world="--world: maps measured in world order with R1v2 carrying its mark evidence (one table per world under "
                                      "PROTO_MARKMAP=world); D = carried, fresh = the same map alone"),
               maps=[], bosses=[], worlds=[])
    if _v3b():                                         # v3：只在 v3b 下加键（不是 v3b 时输出与 v2 逐字相同）
        rep["definitions"]["deterministic"] = DET_INFO
        rep["deterministic"] = dict(mode="v3b", check_stream=args["stream"] + DET_SUFFIX, checks_per_player=DET_CHECKS, lives_per_player=1)
    with _Tap():
        for s in args["salts"]:
            rep["maps"].append(measure_map(s, args, panel_keys))
            print(f"  map {s}: D={rep['maps'][-1]['D']} ({time.time() - t0:.0f}s)", flush=True)
        for s, pair in args["boss"]:
            rep["bosses"].append(measure_boss(s, pair, args, panel_keys))
            print(f"  boss {s} {pair}: D={rep['bosses'][-1]['D']} ({time.time() - t0:.0f}s)", flush=True)
        for s, pair in args["world"]:
            w = measure_world(s, pair, args, panel_keys)
            rep["worlds"].append(w)
            print(f"  world {w['id']}: D carried {[m['D'] for m in w['maps']]} boss {w['boss']['D']}; fresh {[m['fresh']['D'] for m in w['maps']]} "
                  f"boss {w['boss']['fresh']['D']}; identity_map0 {w['identity_map0']} ({time.time() - t0:.0f}s)", flush=True)
    rep["table_zh"] = table_zh(rep)
    rep["seconds"] = round(time.time() - t0, 1)
    print("\n".join(rep["table_zh"]), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    ap.refuse_overwrite(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=lambda x: dict(x) if isinstance(x, collections.Counter) else str(x)))
    print(f"-> {out}", flush=True)
    return rep


if __name__ == "__main__":
    main()
