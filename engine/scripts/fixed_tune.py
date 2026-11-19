"""固定手牌下的机制调参筛选（2026-11-03 晚；小原型，不改现行版本，不改 core/）。
用户（经 GPT，11-03 晚）：「继续以固定操作为开发方向，不回退抽牌；但先暂停大规模搜图……让已有机制真正约束这套组合。先针对『动量来不及起作用』
『破势被开场盾顺便解决』做小原型调整。懂规则的玩家仍要可靠通过，已找到的组合及其变体则不能轻易通吃。不要只增加伤害，也不要单靠提高标记的出场量
来挡住所有习惯。」背景：docs/antagonist_boss/09_fixed_hand_validation_results.md。

候选（CONFIGS，跑之前定下；只动时间和条件，不动伤害倍数、不动标记出场量）：TUNING 覆盖，建图之前、打的时候都生效。
  base       不改（= 09 的固定手牌臂）
  M59 / M610 动量怪血量 hp_momentum (3,7) → (5,9) / (6,10)：让动量有时间攒起来（同守势 5–9 / 蓄力 6–11 的量级）
  W3 / W2    破势打开的窗口 ward_window 4 → 3 / 2：开场一块盾打开的窗口不够把它打死，要再挡一次
  WH         破势怪血量 hp_ward (4,7) → (6,9)：同上，靠血量
  WS2        考试战的破势起始封印 2（ward_test_start=2；教学战不变）：一块盾打不开
  组合        M59+W3、M59+W2、M59+WH、M59+WS2、M610+W2
玩家（只在 PROTO_HAND=fixed）：
  参照   R1v2-c（N_REF）、全知-c、R1 v1（各 N_REF2）
  简单   冻结清单 211 类代表（N_PANEL）、固定手牌条件习惯 scripts/fixed_habits.py 105 套（N_PANEL）、固定节奏 4,336 条（N_RHYTHM）、盲线 200 类代表（N_BLIND）
  复核   每图每组前 TOP 个不同签名用新流再打 N_CONFIRM 条；每组「≥ PASS_LINE 的图数」最多的前 TOP 个不同向量，在全部图上用新流打 N_UNI 条
图：
  tune   与 09 相同的 40 张（proto_world.two_round_salts(40)）
  fresh  接下来的 40 张两轮图（two_round_salts(80)[40:]）—— 防止只调合了那 40 张
  血量区间、封印只改敌人的数，不改抽到哪几种机制和顺序：工作进程里逐图核对 drawn / 顺序与 base 相同。
报告（每个候选 × 每组图）：
  可用图   R1v2-c ≥ 0.90 且最好的简单打法（复核后、各组合起来）< PASS_LINE 的图数 —— 以后搜图能用的图（主指标）
  参照     R1v2-c / 全知-c / R1 ≥ 0.90 的图数、平均
  简单     最好的简单打法 ≥ PASS_LINE 的图数（各组、合起来）；单个打法过线的最多图数（复核 2）
  组合     已发现的组合 oB.XA|slot>D 与「亮了改举盾」oB.XA|slot>B 的过线图数
跑之前写定的挑法（建议，取舍由用户定）：只看 fresh 那组图；先要求 R1v2-c ≥ 0.90 的图 ≥ 36/40；在满足的候选里取「可用图」最多的，
  同分取「单个打法过线的最多图数」少的。tune 那组照报，用来看是不是调合了。
用法：
  python3 -B scripts/fixed_tune.py plan
  WORKERS=6 python3 -B scripts/fixed_tune.py run      → results/proto13/fixed_tune/fixed_tune_v1.json（已存在就拒绝）
  python3 -B scripts/fixed_tune.py summary [文件]"""
import collections, datetime, hashlib, json, os, pathlib, statistics, sys, time
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))

VERSION = "fixed-tune-v1.3-2026-11-04"   # v1.3：加候选 M59+WS2+T25
# v1.2   # v1.2：加两个候选 M59+WS2+T50 / T100（考试战敌人血 +50% / +100%）
# v1.1   # v1.1（11-03 夜）：复核 1 按所有图组循环（v1 写死了 tune / fresh，确认用的新图组会出 KeyError）；跑完从文件汇总
OUT = ROOT / "results" / "proto13" / "fixed_tune" / os.environ.get("OUTNAME", "fixed_tune_v1.json")
STREAM, CONFIRM_STREAM, UNI_STREAM = "fixed-tune", "fixed-tune-confirm", "fixed-tune-universal"
CONFIGS = {
    "base": {},
    "M59": dict(hp_momentum=(5, 9)),
    "M610": dict(hp_momentum=(6, 10)),
    "W3": dict(ward_window=3),
    "W2": dict(ward_window=2),
    "WH": dict(hp_ward=(6, 9)),
    "WS2": dict(ward_test_start=2),
    "M59+W3": dict(hp_momentum=(5, 9), ward_window=3),
    "M59+W2": dict(hp_momentum=(5, 9), ward_window=2),
    "M59+WH": dict(hp_momentum=(5, 9), hp_ward=(6, 9)),
    "M59+WS2": dict(hp_momentum=(5, 9), ward_test_start=2),
    "M610+W2": dict(hp_momentum=(6, 10), ward_window=2),
    # v1.2（11-04）：阶梯下考试战太短（标记 / 动量 / 穿透平均 3–4 回合，同一种错一场多半只犯 1–3 次，阶梯的高格用不上）→ 加长考试战（时间杠杆，
    # 不加惩罚）：引擎的 test_hp_pct（只加考试战敌人的血，教学战不动，第一次遭遇照样活得下来）
    "M59+WS2+T50": dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=50),
    "M59+WS2+T100": dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=100),
    # v1.3（11-04 上午，用户「加百分之百的血量太多了，能不能少加然后配合倍数解决」）：+25%
    "M59+WS2+T25": dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=25),
}
KNOBS = sorted({k for c in CONFIGS.values() for k in c})
N_REF, N_REF2, N_PANEL, N_RHYTHM, N_BLIND = 100, 50, 20, 4, 10
TOP, N_CONFIRM, N_UNI = 5, 100, 50
PASS_LINE, REF_LINE = 0.4, 0.9
REFS = {"R1v2-c": N_REF, "oracle-c": N_REF2, "R1": N_REF2}
GROUPS = ("habit", "fhc", "rhythm", "blind")
SAMPLE = dict(habit=N_PANEL, fhc=N_PANEL, rhythm=N_RHYTHM, blind=N_BLIND)
CHUNK = dict(habit=40, fhc=40, rhythm=400, blind=100)
WORKERS = min(6, int(os.environ.get("WORKERS", 6)))
WATCH = ("oB.XA|slot>D", "oB.XA|slot>B")
FILES = ("scripts/fixed_tune.py", "scripts/fixed_habits.py", "scripts/fixed_rhythms.py", "scripts/antagonist_proto.py", "scripts/antagonist_boss.py",
         "scripts/r1v2.py", "scripts/shortcut_screen.py", "scripts/fixed_panel.py", "scripts/proto_world.py", "core/adventure.py", "core/solver.py")


def _hashes():
    return {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in FILES}


# ---------------------------------------------------------------- 工作进程
_W = dict(ready=False)


def _init():
    os.environ["PROTO_HAND"] = "fixed"


def _ready():
    if _W["ready"]:
        return
    import antagonist_proto as ap, antagonist_boss as ab, solver
    from adventure import TUNING
    assert ap.HAND == "fixed" and ap._now() == dict(ap.DEFAULTS, hand="fixed") and ap.SALT0 == 2000000, ap._now()
    ab.setup_boss()
    _W.update(ready=True, ap=ap, ab=ab, items=json.loads(ap.LIST.read_text())["items"], blind=solver.blind_gate(full=True),
              base={k: TUNING[k] for k in KNOBS if k in TUNING}, cfg=None, cells={}, sig={})


def _apply(cfg):
    """把 TUNING 里的调参键放回 base，再写这个候选的值（建图和打的时候都要是这一套）。"""
    from adventure import TUNING
    if _W["cfg"] == cfg:
        return
    for k in KNOBS:
        if k in _W["base"]:
            TUNING[k] = _W["base"][k]
        else:
            TUNING.pop(k, None)
    TUNING.update(CONFIGS[cfg])
    _W["cfg"] = cfg


def _run(cfg, salt):
    key = (cfg, salt)
    if key not in _W["cells"]:
        _apply(cfg)
        run = _W["ap"].build(salt)
        sig = (tuple(run.drawn), tuple(L.behaviour for L in run.layers))
        _W["sig"].setdefault(salt, sig)
        assert _W["sig"][salt] == sig, ("调参改了抽到的机制或顺序", cfg, salt)   # 每个工作进程第一次见到这张图时记下签名
        _W["cells"][key] = run
    _apply(cfg)
    return _W["cells"][key]


class End:
    belief = None
    last = None
    def enter(self, run, f, kinds): pass
    def before_decision(self, f): pass
    def before_play(self, f, c): pass
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, *a): pass
    def leave(self, f, won): self.last = "won" if won else (_W["ap"].ended_by(f) or "died")
    def rest(self, run, mode): pass


def _life(run, salt, group, key, t, stream):
    import solver, fixed_rhythms as fr, fixed_habits as fh, r1v2
    ap, ab = _W["ap"], _W["ab"]
    rec = End()
    if group == "ref":
        if key == "R1v2-c":
            old = r1v2.ENERGY_VETO; r1v2.ENERGY_VETO = True
            try:
                won = ab.play_map(run, salt, "R1v2", t, stream, record=rec)["won"]
            finally:
                r1v2.ENERGY_VETO = old
        elif key == "oracle-c":
            won = ab.play_map(run, salt, "oracle", t, stream, record=rec, oracle_veto=True)["won"]
        else:
            won = ab.play_map(run, salt, "R1", t, stream, record=rec)["won"]
    elif group == "habit":
        won = ab.play_map(run, salt, "habit", t, stream, item=_W["items"][key], record=rec)["won"]
    elif group == "blind":
        won = ab.play_map(run, salt, "blind", t, stream, item=_W["blind"][key], record=rec)["won"]
    else:
        if group == "rhythm":
            act, route = fr.make_act(fr.parse(key)), fr.route()
        else:
            act, route = fh.make(key)
        rng = solver._trial_rng(ap.SEED ^ salt, stream, t)
        with ap.using_display("habit"):
            won = solver.run_once(run, solver.NONE, route, rng, information="observable", act_policy=act,
                                  record=ap.screen("habit", rec), fight_boss=False)
    return bool(won), rec.last


def job(spec):
    _ready()
    cfg, salt, group, keys, n, stream = spec
    run = _run(cfg, salt)
    out = {}
    for key in keys:
        sig, ends = 0, collections.Counter()
        for t in range(n):
            won, end = _life(run, salt, group, key, t, stream)
            sig |= int(won) << t
            ends[end or ("won" if won else "died")] += 1
        out[key] = dict(w=bin(sig).count("1"), sig=sig, end=dict(ends))
    return (cfg, salt, group), out, dict(hashes=_hashes(), pid=os.getpid(), base=_W["base"])


# ---------------------------------------------------------------- 编排
def _sets():
    import proto_world as pw
    s = pw.two_round_salts(80)
    return dict(tune=s[:40], fresh=s[40:80])


def _panel():
    import antagonist_proto as ap, fixed_rhythms as fr, fixed_habits as fh
    pc = ap.panel_classes()
    return dict(habit=[c[0] for c in pc["habits"]["classes"]], blind=[c[0] for c in pc["blind"]["classes"]],
                rhythm=[fr.rid(r) for r in fr.rhythms(3)], fhc=fh.habits(), ref=list(REFS))


def _chunks(xs, k):
    return [xs[i:i + k] for i in range(0, len(xs), k)]


def _pool(jobs, label, stamps):
    t0 = time.time(); res = []
    with ProcessPoolExecutor(WORKERS, initializer=_init) as ex:
        for i, (head, out, stamp) in enumerate(ex.map(job, jobs, chunksize=1)):
            res.append((head, out)); stamps.setdefault(stamp["pid"], stamp)
            if i % 500 == 0:
                print(f"{label} {i + 1}/{len(jobs)}（{time.time() - t0:.0f} 秒）", flush=True)
    print(f"{label} 完成 {len(jobs)} 个作业（{time.time() - t0:.0f} 秒）", flush=True)
    return res


def _top_distinct(rows, order, k):
    pos = {key: i for i, key in enumerate(order)}
    seen, out = set(), []
    for key, (score, sig) in sorted(rows.items(), key=lambda kv: (-kv[1][0], pos[kv[0]])):
        if sig in seen:
            continue
        seen.add(sig); out.append(key)
        if len(out) == k:
            break
    return out


def run():
    import antagonist_proto as ap
    t_start = time.time()
    ap.refuse_overwrite(OUT)
    h0 = _hashes()
    sets, panel = _sets(), _panel()
    stamps = {}
    jobs = []
    for cfg in CONFIGS:
        for sname, salts in sets.items():
            for s in salts:
                for ref, n in REFS.items():
                    jobs.append((cfg, s, "ref", [ref], n, STREAM))
                for g in GROUPS:
                    for ch in _chunks(panel[g], CHUNK[g]):
                        jobs.append((cfg, s, g, ch, SAMPLE[g], STREAM))
    scr = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (cfg, s, g), out in _pool(jobs, "筛选", stamps):
        scr[(cfg, s)][g].update(out)
    conf_jobs = []
    for cfg in CONFIGS:
        for s in [x for v in sets.values() for x in v]:
            for g in GROUPS:
                top = _top_distinct({k: (v["w"], v["sig"]) for k, v in scr[(cfg, s)][g].items()}, panel[g], TOP)
                conf_jobs.append((cfg, s, g, top, N_CONFIRM, CONFIRM_STREAM))
    conf = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (cfg, s, g), out in _pool(conf_jobs, "复核 1", stamps):
        conf[(cfg, s)][g].update(out)
    uni_jobs, uni_pick = [], {}
    for cfg in CONFIGS:
        for sname, salts in sets.items():
            for g in GROUPS:
                rows = {k: (sum(scr[(cfg, s)][g][k]["w"] / SAMPLE[g] >= PASS_LINE for s in salts), tuple(scr[(cfg, s)][g][k]["w"] for s in salts))
                        for k in panel[g]}
                pick = _top_distinct(rows, panel[g], TOP)
                for w in WATCH:
                    if g == "fhc" and w not in pick:
                        pick.append(w)
                uni_pick[(cfg, sname, g)] = pick
                uni_jobs += [(cfg, s, g, pick, N_UNI, UNI_STREAM) for s in salts]
    uni = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (cfg, s, g), out in _pool(uni_jobs, "复核 2", stamps):
        for k, v in out.items():
            uni[(cfg, g)][k][s] = v
    h1 = _hashes()
    if h0 != h1 or any(st["hashes"] != h0 for st in stamps.values()):
        raise SystemExit("跑的过程中代码变了：结果不写")
    out = dict(study="fixed-tune", version=VERSION, date=datetime.date.today().isoformat(), hashes=h0, configs={k: {kk: list(vv) if isinstance(vv, tuple) else vv for kk, vv in v.items()} for k, v in CONFIGS.items()},
               sets=sets, design=dict(refs=REFS, sample=SAMPLE, top=TOP, n_confirm=N_CONFIRM, n_uni=N_UNI, pass_line=PASS_LINE, ref_line=REF_LINE,
                                      panel_sizes={g: len(panel[g]) for g in GROUPS}, watch=list(WATCH), workers=WORKERS),
               screen={f"{c}|{s}": {g: v for g, v in d.items()} for (c, s), d in scr.items()},
               confirm={f"{c}|{s}": {g: v for g, v in d.items()} for (c, s), d in conf.items()},
               universal_pick={f"{c}|{sn}|{g}": v for (c, sn, g), v in uni_pick.items()},
               universal={f"{c}|{g}": {k: v for k, v in d.items()} for (c, g), d in uni.items()},
               base_tuning={k: (list(v) if isinstance(v, tuple) else v) for k, v in next(iter(stamps.values()))["base"].items()},
               minutes=round((time.time() - t_start) / 60, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    print(f"→ {OUT}（{out['minutes']} 分钟）", flush=True)
    summary(json.loads(OUT.read_text()))               # 从文件读：内存里的整数键在 JSON 里是字符串


def summary(out=None):
    if out is None:
        out = json.loads((pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else OUT).read_text())
    d = out["design"]; rows = []
    for cfg in out["configs"]:
        for sname, salts in out["sets"].items():
            refs = {r: [out["screen"][f"{cfg}|{s}"]["ref"][r]["w"] / n for s in salts] for r, n in d["refs"].items()}
            best = {}
            for s in salts:
                c = out["confirm"][f"{cfg}|{s}"]
                best[s] = {g: max((v["w"] / d["n_confirm"] for v in c[g].values()), default=0.0) for g in c}
            allbest = {s: max(b.values()) for s, b in best.items()}
            eligible = sum(refs["R1v2-c"][i] >= d["ref_line"] and allbest[s] < d["pass_line"] for i, s in enumerate(salts))
            single = {}
            for g in ("habit", "fhc", "rhythm", "blind"):
                for k in out["universal_pick"][f"{cfg}|{sname}|{g}"]:
                    v = out["universal"][f"{cfg}|{g}"][str(k)]
                    single[f"{g}:{k}"] = sum(v[str(s)]["w"] / d["n_uni"] >= d["pass_line"] for s in salts)
            top_single = max(single.items(), key=lambda kv: kv[1])
            watch = {w: single.get(f"fhc:{w}") for w in d["watch"]}
            rows.append(dict(config=cfg, set=sname, eligible=eligible,
                             refs_ge90={r: sum(x >= d["ref_line"] for x in v) for r, v in refs.items()},
                             ref_mean={r: round(statistics.mean(v), 3) for r, v in refs.items()},
                             best_simple_ge=sum(x >= d["pass_line"] for x in allbest.values()),
                             by_group={g: sum(best[s][g] >= d["pass_line"] for s in salts) for g in ("habit", "fhc", "rhythm", "blind")},
                             top_single=top_single, watch=watch))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    fresh = [r for r in rows if r["set"] == "fresh" and r["refs_ge90"]["R1v2-c"] >= 36]
    if fresh:
        pick = sorted(fresh, key=lambda r: (-r["eligible"], r["top_single"][1]))[0]
        print("按跑之前写定的挑法（fresh、R1v2-c ≥ 0.90 的图 ≥ 36/40、可用图最多、同分取单个打法最少）:", pick["config"])
    return rows


def plan():
    sets, panel = _sets(), _panel()
    per = sum(len(REFS) * 0 + n for n in REFS.values()) + sum(len(panel[g]) * SAMPLE[g] for g in GROUPS)
    print(f"候选 {len(CONFIGS)}；图 tune {len(sets['tune'])} + fresh {len(sets['fresh'])}；fresh = {sets['fresh']}")
    print(f"每个（候选，图）筛选命数 {per:,}；总 {per * len(CONFIGS) * 80:,}")


if __name__ == "__main__":
    {"plan": plan, "run": run, "summary": summary}[sys.argv[1] if len(sys.argv) > 1 else "plan"]()
