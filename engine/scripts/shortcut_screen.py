"""条件打法的筛查与独立复测（2026-10-20）：不懂规则、只按画面上看得见的符号做固定反应的打法，能不能通过精选包。
只测量，不改规则，不做认证，不换图。显示规范 TUNING["state_slots"] = "seen"（core/adventure.py；画面只整理日志已给的信息）。
背景：scripts/public_info_check.py（study public-info-v3）发现「认证的固定打法 + 怪身上有数字亮着就防守」能打过不少精选图；
用户（GPT 审过）定的方向：把这类打法正式算作盲打（不随经验更新的固定策略），扩充清单、重新测量，再决定正式认证与换图。

0. 机制覆盖的基线（筛查之前，写进声明）：主实验 125 张图上，每个世界每种机制的教学战、复考战场数，以及谨慎参考策略
   （core/cautious.py 的 counter_after_probe/likely/defend，即 public-info-v3 在开发图上选中的那个，marks = 0）实际能打到
   这些战斗的期望场数。由此定下以后重新选包必须满足的下限（BALANCE_RULE）。
1. 筛查：打法 = 底子 × 判法 × 反应 × 路线，每一项都是固定的，五条命用同一套：
     底子    认证族里的 12 条固定节奏线（NEVER_HOLD、ONE_SWING、RHYTHM、WARD_LINES）和 24 条 StaticBlind，各用自己的认证经济
             （blind=该线：休息 blind_rest_choice、拿牌照路线；StaticBlind 照认证在 heal_at 自动治疗，固定节奏线不自动治疗）
     判法    只读画面上 Them 下面那一行印出来的符号和值（不读引擎里符号的含义）：any（任何一格值 > 0）、present（印出了任何一格）、
             only:Bk（Bk 那一格值 > 0，k = 1..5）、except:Bk（除 Bk 之外任何一格值 > 0）—— 共 12 种
     反应    hold（盾 > 闪 > 疗，都出不了就结束回合）、dodge（闪 > 盾 > 疗，同上）、calm（底子本来要出的牌是攻击或增伤就改出
             盾 > 闪 > 疗，否则照出）
     路线    blind_gate(full=True) 的全部 17 条（认证用的那些）
   每套打法在每张精选图上先打 5 条命（LIB_SCREEN_STREAM + "/family"）；有通关的再加 15 条（共 20）。判法在这张图上永远不会
   触发（图上的机制都没有对应的状态槽）的格子不跑：那套打法在这张图上就是底子本身，底子已经认证过（记为 None）。
2. 选复测：每个（打法，包）用同一套打法在五张图上的估计通关率 p̂_i = k_i / n_i 算「五条命里 ≥ 2 条通关」的概率（各命独立，
   盲打不跨命学习）；≥ FLAG（0.005，BLIND_MAX 的一半）的进复测，每包最多 TOPK 套（按这个概率排，没进的记下来）。
3. 独立复测：每个入选的（打法，包）在新流 LIB_SCREEN_STREAM + "/packrun" 上打 200 轮，每轮按站序连打五张图、每张一条命、
   同一套打法；X = 五条命里 ≥ 2 条通关的轮数。
4. 判定（事先写定，见 DECISION）：
     确实被打穿      某个复测（打法，包）的单侧 Clopper-Pearson 下界（α = 0.05 / 复测对数，Bonferroni）> BLIND_MAX
     需要补测        没有被打穿，但有复测对 X ≥ 1 —— 要按正式认证的样本量在新流上再测
     本轮未发现明显捷径  没有入选复测，或入选的全部 X = 0 —— 这不是认证：0/200 的单侧 95% 上界约 1.49%，仍高于 1%
   单张图另报：复测里这张图的单命通关数，下界（α = 0.05 / 复测里的（打法，图）对数）> MAP_BLIND_MAX 的算这张图被打穿。
声明（DECLARATION + 用到的全部模块和数据文件的哈希 + 第 0 段的基线）只追加写进 results/sweeps/shortcut_screen_declarations.jsonl；
同一 STUDY 下有任何变化就拒绝开跑。工作进程回报自己读到的哈希。SHORTCUT_OUT=<目录> 是试跑：只取几个包、几套打法。
用法：python3 scripts/shortcut_screen.py  →  results/sweeps/shortcut_screen.json

第 2 版（STUDY shortcut-screen-v2，2026-10-20）：用户指出「怪身上一直没冒数字」本身就是线索 —— 反击、穿透（和毒）身上从来没有
状态槽，只是「动作 → 结果」，不给记号是它们本来的样子；但这样一来，「没冒数字就小心」这种不懂规则的打法也得测。实测
（scratchpad，主实验 25 包、每套 40 轮）：大多数包里更差，E-3 从 8/40 升到 36/40、A-5 从 2/40 升到 12/40。所以每套打法多一维
「暗」（DARKS）：这一场还没印出过任何状态槽（except:Bk 的判法不算 Bk 那一格）时怎么出牌：
    one       一回合最多出一张进攻牌（攻击或增伤，攻击优先），不出盾，其余能量出闪 > 疗
    noblock   照底子出，但不出盾（底子要出盾就改出闪 > 疗，都出不了就结束回合）
    oneatk    照底子出，但一回合最多出一张进攻牌（第二张起改出盾 > 闪 > 疗）
只跑 dark ≠ none 的打法（none 就是第 1 版测过的那批），用新流 /family2、/packrun2；判定时把两版复测过的（打法，包）合在一起，
Bonferroni 的对数取两版之和。"""
import collections
import datetime
import hashlib
import itertools
import json
import math
import os
import pathlib
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
STUDY = "shortcut-screen-v2"
V1 = ROOT / "results" / "sweeps" / "shortcut_screen.json"       # 第 1 版的结果（dark = none），判定时合并
SEED = 9065
WORKERS = 5
TRIAL = bool(os.environ.get("SHORTCUT_OUT"))
OUT = pathlib.Path(os.environ.get("SHORTCUT_OUT", ROOT / "results" / "sweeps"))
N1, N2 = 5, 20                    # 筛查：先 5 条命；有通关的格子补到 20
FLAG, TOPK = 0.005, 30            # 进复测的门槛（包级概率的估计值）和每包上限
PACKRUNS = 200                    # 复测：每个（打法，包）连打五张图的轮数
REACH_LIVES = 200                 # 第 0 段：谨慎参考策略每张图的命数
REFERENCE = "counter_after_probe/likely/defend"
LABELS = ("B1", "B2", "B3", "B4", "B5")
TRIGGERS = ("any", "present") + tuple(f"only:{l}" for l in LABELS) + tuple(f"except:{l}" for l in LABELS)
RESPONSES = ("hold", "dodge", "calm")
DARKS = ("one", "noblock", "oneatk")
STATE_MECHANICS = ("charge", "guard", "mark", "ward")       # 池里有状态槽的机制（mimic 不在登记的池里）
HASHED = ("core/solver.py", "core/adventure.py", "core/devworld.py", "core/gates.py", "core/camp.py", "core/library.py",
          "core/namegen.py", "core/cautious.py", "scripts/shortcut_screen.py", "results/release_packs.json",
          "results/worlds/five_pack_plan.json") + tuple(f"results/worlds/{w}/library_certification.json" for w in "BCDE")
DECISION = dict(
    broken="some re-tested (strategy, pack): one-sided Clopper-Pearson lower bound of X/200 at alpha = 0.05 / (number of re-tested pairs) > gates.BLIND_MAX",
    needs_recheck="not broken, but some re-tested pair has X >= 1: re-test at certification N on a fresh stream",
    no_obvious_shortcut="no pair reached the re-test, or all re-tested pairs have X = 0; NOT a certification (0/200 gives a one-sided 95% upper bound of about 1.49%)",
    map_broken="a map in the re-test whose single-life clears for one strategy have a lower bound at alpha = 0.05 / (number of re-tested (strategy, map) pairs) > gates.MAP_BLIND_MAX",
)
BALANCE_RULE = dict(
    structural="every re-selected pack keeps the registered composition rules (library.check_pack: all seven mechanics, each on >= 2 maps, "
               "schedule 4/2/1/0/0, ...); hence, per world over the five main-study packs, every mechanic has >= 10 teach and >= 10 test fights",
    reached="per world and mechanic, the cautious reference's expected number of reached TEST fights over the five main-study packs must be "
            ">= max(2, 0.8 x the stage-0 baseline below)",
    classes="per world, the same quantity summed over enemy-state mechanics (charge, guard) and over own-action mechanics (counter, pierce) "
            "must each be >= 0.8 x its stage-0 baseline; ward and mark are reported separately (classification pending: trigger type x cue salience)",
    report="for any re-selection, report the teach/test counts and the reached counts per mechanic next to the baseline",
)


# ---------------------------------------------------------------- 共用
def file_hashes():
    return {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in HASHED}


_WH = None


def worker_hashes():
    global _WH
    if _WH is None:
        _WH = file_hashes()
    return _WH


def _binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def cp_upper(k, n, alpha=0.05):
    if k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _binom_cdf(k, n, mid) > alpha else (lo, mid)
    return hi


def cp_lower(k, n, alpha=0.05):
    """单侧下界：P(X >= k | p) = alpha 的 p。"""
    if k <= 0:
        return 0.0
    lo, hi = 0.0, k / n
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if 1 - _binom_cdf(k - 1, n, mid) < alpha else (lo, mid)
    return lo


def p_two_or_more(ps):
    """独立的五条命，各自通关概率 ps：至少两条通关的概率。"""
    none = math.prod(1 - p for p in ps)
    one = sum(p * math.prod(1 - q for j, q in enumerate(ps) if j != i) for i, p in enumerate(ps))
    return max(0.0, 1 - none - one)


class TrackSeen:
    """读画面的打法要看到人看到的画面：play_fight 为省时间关掉了 `?` 规则的追踪，这里打开。"""
    belief = None
    def enter(self, run, f, kinds): f.track_seen = True
    def before_decision(self, f): pass
    def before_play(self, f, c): pass
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, *a): pass
    def leave(self, f, won): pass
    def rest(self, run, mode): pass


def bases():
    import solver
    return tuple(solver.NEVER_HOLD) + tuple(solver.ONE_SWING) + tuple(solver.RHYTHM) + tuple(solver.WARD_LINES) + tuple(solver.STATIC_GRID)


def routes():
    """认证用的 17 条路线：和 solver.blind_gate(full=True) 同一个定义（4 条朴素经济 + 13 条筛选路线）。"""
    import solver
    return tuple(solver.Route(take=t) for t in solver.BLIND_ECONOMIES) + tuple(solver.SCREEN_ROUTES)


def strategies():
    """第 1 版的打法：（底子序号, 判法, 反应, 路线序号）。路线序号指向 routes()。顺序不能动：第 1 版的结果按这个序号存。"""
    nb, nr = len(bases()), len(routes())
    return [(b, t, r, ri) for b in range(nb) for t in TRIGGERS for r in RESPONSES for ri in range(nr)]


def strategies2():
    """第 2 版的打法：（第 1 版序号, 暗）。"""
    return [(sid, d) for sid in range(len(strategies())) for d in DARKS]


def fires_on(trigger, layout_labels, mechanics):
    """这张图上这条判法会不会触发：图上（含 boss）有没有对应的状态槽。只用来省掉一定和底子相同的格子，不进打法。"""
    present = {layout_labels[m] for m in mechanics if m in STATE_MECHANICS}
    if trigger in ("any", "present"):
        return bool(present)
    kind, lab = trigger.split(":")
    return (lab in present) if kind == "only" else bool(present - {lab})


def make_act(base, trigger, response, dark=None):
    import cautious
    import solver
    offence = ("attack", "buff_mark")
    ever = {}                                       # 这一场印出过（判法不忽略的）状态槽没有

    def first(f, kinds, order):
        for k in order:
            if k in kinds and f.can_play(kinds[k]):
                return kinds[k]
        return None

    def base_choice(f, kinds):
        if isinstance(base, solver.FixedOrder):
            return solver.fixed_order_act(f, kinds, base)
        return solver.static_act(f, kinds, base, getattr(f, "played_kinds", {}).get("attack", 0), base.block)

    def lit(f):
        shown = cautious.them_slots(f)
        if trigger == "any":
            return any(v > 0 for v in shown.values())
        if trigger == "present":
            return bool(shown)
        kind, lab = trigger.split(":")
        if kind == "only":
            return shown.get(lab, 0) > 0
        return any(v > 0 for k, v in shown.items() if k != lab)

    def dark_choice(f, kinds):
        c = base_choice(f, kinds)
        kind = f.deck[c].kind if c is not None else None
        if dark == "one":
            if f.offences < 1:
                return first(f, kinds, ("attack", "buff_mark", "dodge", "heal"))
            return first(f, kinds, ("dodge", "heal"))
        if dark == "noblock":
            return first(f, kinds, ("dodge", "heal")) if kind == "block" else c
        if dark == "oneatk":
            return first(f, kinds, ("block", "dodge", "heal")) if (kind in offence and f.offences >= 1) else c
        return c

    def act(f, know, kinds, belief=None, information="observable"):
        if dark is not None:
            shown = cautious.them_slots(f)
            if trigger.startswith("except:"):
                shown.pop(trigger.split(":")[1], None)
            st = ever.get(id(f))
            if st is None or st[0] is not f:
                st = ever[id(f)] = [f, False]
            st[1] = st[1] or bool(shown)
            if not st[1]:
                return dark_choice(f, kinds)
        if not lit(f):
            return base_choice(f, kinds)
        if response == "hold":
            return first(f, kinds, ("block", "dodge", "heal"))
        if response == "dodge":
            return first(f, kinds, ("dodge", "block", "heal"))
        c = base_choice(f, kinds)
        return first(f, kinds, ("block", "dodge", "heal")) if (c is not None and f.deck[c].kind in offence) else c
    return act


def _build(world, salt, pack):
    import devworld
    run = devworld.build_world(world, SEED, salt, pack)
    import solver
    return run, solver


# ---------------------------------------------------------------- 0. 机制覆盖的基线
class _Reach(TrackSeen):
    def __init__(self, counts):
        self.counts, self.n = counts, 0
    def enter(self, run, f, kinds):
        f.track_seen = True
        self.counts[self.n] += 1
        self.n += 1


def reach_job(job):
    world, pack, salt = job
    import gates
    import cautious
    from adventure import TUNING
    run, solver = _build(world, salt, pack)
    seq = []
    for layer in run.layers:
        if layer.kinds() == ["rest"]:
            continue
        node = layer.nodes[0]
        seq.append((node.behaviour, node.role or "?"))
    seq += [(m, "boss") for m in run.boss_stages]
    counts = collections.Counter()
    TUNING["marks"], TUNING["state_slots"] = 0, "seen"
    for t in range(REACH_LIVES):
        p = cautious.Cautious(REFERENCE)
        solver.run_once(run, solver.ALL - {"mark"}, solver.SCREEN_ROUTES[9], solver._trial_rng(SEED ^ salt, gates.INFORMED_STREAM, t),
                        information="observable", act_policy=p.act, heal_veto=p.heal_veto, belief_cls=cautious.PublicBelief,
                        record=_Reach(counts))
    TUNING["marks"], TUNING["state_slots"] = 1, "hidden"
    reach = [counts[i] / REACH_LIVES for i in range(len(seq))]
    return dict(world=world, pack=pack, salt=salt, fights=[dict(mechanic=m, role=r, reach=round(x, 4)) for (m, r), x in zip(seq, reach)],
                hashes=worker_hashes())


def balance_table(rows):
    out = {}
    for w in "ABCDE":
        d = collections.defaultdict(lambda: dict(teach=0, test=0, boss=0, reached_teach=0.0, reached_test=0.0, reached_boss=0.0))
        for r in rows:
            if r["world"] != w:
                continue
            for x in r["fights"]:
                m = x["mechanic"]
                for part in (m.split("+") if "+" in m else [m]):
                    role = x["role"] if x["role"] in ("teach", "test", "boss") else None
                    if role:
                        d[part][role] += 1
                        d[part]["reached_" + role] += x["reach"]
        out[w] = {m: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in vals.items()} for m, vals in sorted(d.items())}
    return out


# ---------------------------------------------------------------- 1. 筛查
def screen_job(job):
    world, pack, station, salt, strat_ids, n_first, n_more = job
    import gates
    from adventure import TUNING
    run, solver = _build(world, salt, pack)
    TUNING["state_slots"] = "seen"
    labels = {m: run.layout.L("them", m) for m in STATE_MECHANICS}
    mechanics = set(run.drawn) | set(run.boss_stages)
    all_s, all_2 = strategies(), strategies2()
    stream = gates.LIB_SCREEN_STREAM + "/family2"
    out = {}
    for sid in strat_ids:
        sid1, dark = all_2[sid]
        b, trig, resp, ri = all_s[sid1]
        base = bases()[b]
        act = make_act(base, trig, resp, dark)
        def life(t):
            return bool(solver.run_once(run, solver.NONE, routes()[ri], solver._trial_rng(SEED ^ salt, stream, t),
                                        information="observable", blind=base, act_policy=act, record=TrackSeen()))
        k = sum(life(t) for t in range(n_first))
        n = n_first
        if k:
            k += sum(life(t) for t in range(n_first, n_more)); n = n_more
        out[sid] = (k, n)
    TUNING["state_slots"] = "hidden"
    return dict(world=world, pack=pack, station=station, salt=salt, cells=out, hashes=worker_hashes())


# ---------------------------------------------------------------- 3. 复测
def packrun_job(job):
    world, pack, maps, sid = job
    import gates
    import devworld
    from adventure import TUNING
    sid1, dark = strategies2()[sid]
    b, trig, resp, ri = strategies()[sid1]
    base = bases()[b]
    stream = gates.LIB_SCREEN_STREAM + "/packrun2"
    runs = [devworld.build_world(world, SEED, s, pack) for s in maps]
    import solver
    TUNING["state_slots"] = "seen"
    per_map = [0] * len(maps)
    X = 0
    for t in range(PACKRUNS):
        cleared = 0
        for i, (run, s) in enumerate(zip(runs, maps)):
            w = bool(solver.run_once(run, solver.NONE, routes()[ri], solver._trial_rng(SEED ^ s, stream, t), information="observable",
                                     blind=base, act_policy=make_act(base, trig, resp, dark), record=TrackSeen()))
            per_map[i] += w; cleared += w
        X += cleared >= 2
    TUNING["state_slots"] = "hidden"
    return dict(world=world, pack=pack, sid=sid, X=X, n=PACKRUNS, per_map=per_map, hashes=worker_hashes())


# ---------------------------------------------------------------- 主程序
def declare(baseline):
    decl = dict(study=STUDY, display="state_slots='seen'", n_first=N1, n_more=N2, flag=FLAG, topk=TOPK, packruns=PACKRUNS,
                triggers=list(TRIGGERS), responses=list(RESPONSES), darks=list(DARKS), bases=[getattr(b, "name", repr(b)) for b in bases()],
                n_routes=len(routes()), n_strategies=len(strategies2()), streams=dict(screen="LIB_SCREEN_STREAM/family2", retest="LIB_SCREEN_STREAM/packrun2"),
                combine="verdict combines the re-tested pairs of shortcut-screen-v1 (dark = none, results/sweeps/shortcut_screen.json) and of this run; "
                        "Bonferroni over the sum of both",
                v1_sha256_16=hashlib.sha256(V1.read_bytes()).hexdigest()[:16],
                decision=DECISION, balance_rule=BALANCE_RULE, balance_baseline=baseline, reference_for_reach=REFERENCE,
                files=file_hashes())
    log = OUT / "shortcut_screen_declarations.jsonl"
    old = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    same = [d for d in old if d.get("study") == STUDY]
    body = lambda d: {k: v for k, v in d.items() if k != "written"}
    if same and body(same[-1]) != body(decl):
        raise SystemExit(f"{STUDY} 已经声明过，而代码、数据、参数或基线变了：换 STUDY 名再跑（声明只追加）。")
    if same:
        return same[-1]
    decl["written"] = datetime.datetime.now().isoformat(timespec="seconds")
    with log.open("a") as fh:
        fh.write(json.dumps(decl, ensure_ascii=False) + "\n")
    return decl


def check(rows, files):
    bad = [r for r in rows if r.get("hashes") != files]
    if bad:
        raise SystemExit(f"工作进程读到的文件和声明对不上（{len(bad)} 个作业）：结果不写。")
    for r in rows:
        r.pop("hashes", None)


def main():
    import devworld
    import gates
    OUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / "results" / "worlds" / "five_pack_plan.json").read_text())
    curated = {(w, f"{w}-{i + 1}"): tuple(p) for w in "ABCDE" for i, p in enumerate(devworld.WORLD_PACKS[w])}
    plan_maps = [(w, p, s) for (w, p), maps in curated.items() if p in plan["packs_per_world"][w] for s in maps]
    sids = list(range(len(strategies2())))
    if TRIAL:
        curated = dict(list(curated.items())[::25]); plan_maps = plan_maps[:3]; sids = sids[::400]
    result = dict()
    save = lambda: (OUT / "shortcut_screen_v2.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    v1 = json.loads(V1.read_text())
    t0 = datetime.datetime.now()
    try:
        with ProcessPoolExecutor(WORKERS) as ex:
            reach_rows = list(ex.map(reach_job, plan_maps))
            files = file_hashes()
            check(reach_rows, files)
            baseline = balance_table(reach_rows)
            decl = declare(baseline)
            result.update(declaration=decl, reach_rows=reach_rows)
            save(); print("declared; balance baseline written", flush=True)
            jobs = [(w, p, k + 1, s, sids, N1, N2) for (w, p), maps in curated.items() for k, s in enumerate(maps)]
            screen = list(ex.map(screen_job, jobs))
            check(screen, decl["files"])
            result["screen"] = screen
            save(); print("screen done:", len(screen), "maps", flush=True)
            cells = {(r["world"], r["salt"]): r["cells"] for r in screen}
            ranked = {}
            for (w, p), maps in curated.items():
                rows = []
                for sid in sids:
                    ps = []
                    for s in maps:
                        c = cells[(w, s)].get(sid)
                        ps.append(0.0 if c is None else c[0] / c[1])
                    rows.append((p_two_or_more(ps), sid))
                rows.sort(reverse=True)
                flagged = [(q, sid) for q, sid in rows if q >= FLAG]
                ranked[(w, p)] = dict(flagged=len(flagged), kept=[sid for _, sid in flagged[:TOPK]], dropped=len(flagged[TOPK:]),
                                      top=[(round(q, 4), sid) for q, sid in rows[:5]])
            result["flags"] = {f"{w}/{p}": v for (w, p), v in ranked.items()}
            save()
            jobs = [(w, p, curated[(w, p)], sid) for (w, p), v in ranked.items() for sid in v["kept"]]
            retest = list(ex.map(packrun_job, jobs))
            check(retest, decl["files"])
            result["retest"] = retest
            save(); print("retest done:", len(retest), "pairs", flush=True)
        # 判定：两版的复测合在一起
        both = [dict(r, version=1, strategy=strategies()[r["sid"]] + ("none",)) for r in v1["retest"]] + \
               [dict(r, version=2, strategy=strategies()[strategies2()[r["sid"]][0]] + (strategies2()[r["sid"]][1],)) for r in retest]
        M = max(1, len(both)); Mmap = max(1, len(both) * 5)
        verdict = {}
        for (w, p) in curated:
            rs = [r for r in both if r["world"] == w and r["pack"] == p]
            broken = [r for r in rs if cp_lower(r["X"], r["n"], 0.05 / M) > gates.BLIND_MAX]
            cat = ("broken" if broken else "needs_recheck" if any(r["X"] >= 1 for r in rs) else "no_obvious_shortcut")
            maps_broken = sorted({curated[(w, p)][i] for r in rs for i, k in enumerate(r["per_map"])
                                  if cp_lower(k, r["n"], 0.05 / Mmap) > gates.MAP_BLIND_MAX})
            best = max(rs, key=lambda r: r["X"], default=None)
            verdict[f"{w}/{p}"] = dict(category=cat, plan=p in plan["packs_per_world"][w], retested=len(rs),
                                       worst=(dict(X=best["X"], n=best["n"], strategy=best["strategy"], version=best["version"],
                                                   lower=round(cp_lower(best["X"], best["n"], 0.05 / M), 4),
                                                   upper=round(cp_upper(best["X"], best["n"]), 4)) if best else None),
                                       maps_broken=maps_broken)
        result["verdict"] = verdict
        result["summary"] = dict(retested_pairs=M, retested_v1=len(v1["retest"]), retested_v2=len(retest), categories=collections.Counter(v["category"] for v in verdict.values()),
                                 plan_categories=collections.Counter(v["category"] for v in verdict.values() if v["plan"]),
                                 broken_maps=sorted({(k.split("/")[0], s) for k, v in verdict.items() for s in v["maps_broken"]}))
    finally:
        result["minutes"] = round((datetime.datetime.now() - t0).total_seconds() / 60, 1)
        save()
    print(json.dumps(result.get("summary", {}), ensure_ascii=False, default=list, indent=1))


if __name__ == "__main__":
    main()
