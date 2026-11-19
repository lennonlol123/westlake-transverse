"""验证批次搜图：阶段 0–2 + boss 门 + 探针前提 + 学习者曲线（登记 4 起的规则）。放在仓库里，不放临时目录。
  用法：SALT_START=500000 NPACK=20 [KNOBS_EXTRA='{...}'] [STAGES=s1,s2,ln] OUT=... python3 scripts/search4.py
  阶段 0  从 SALT_START 起扫两轮世界，按 salt 顺序每 4 张成包，包必须覆盖整个池子（不覆盖整包丢）。
  阶段 1  逐图：ALL 普通/干净（流 ev）、Vmin（流 kv）、逐机制机会数、boss 每段反事实（流 bk，boss_know）、
          探针前提（流 pr：ALL−m 到 boss 入口时 m 的探针已落）。
  阶段 2  逐包：盲线族筛选（流 ps，每线每命 N_SCREEN 次），P(≥2/4) 按独立四命试验数；gap。
  学习者  逐包：两段式参考学习者（need=2），规则记忆跨四命；仪器读数。
硬门：覆盖、Vmin、boss 每段、探针前提、gap（普通+干净）。ALL 无下限，只报最低值。"""
import sys, os, json, statistics, collections, time, pathlib
import multiprocessing as mp
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

SEED = 9065
NPACK = int(os.environ.get("NPACK", 20)); N_INF = int(os.environ.get("N_INF", 200)); N_KNOW = int(os.environ.get("N_KNOW", 150))
N_BOSS = int(os.environ.get("N_BOSS", 200)); N_LEARN = int(os.environ.get("N_LEARN", 200)); WORKERS = int(os.environ.get("WORKERS", 6))
EXTRA = json.loads(os.environ.get("KNOBS_EXTRA", "{}")); STAGES = set(os.environ.get("STAGES", "s1,s2,ln").split(","))
START = int(os.environ.get("SALT_START", 0)) or None
POOL = tuple(json.loads(os.environ["POOL"])) if os.environ.get("POOL") else None   # 原型池覆盖（变体实验）
# 学习者的证据按场计（2026-10-21 修，core/learner.py 的 counted_beliefs）。legacy = 旧行为：每命的证据都记成 (命, 0)、同一命只算一次，
# 只为复现 2026-10-21 之前写下的学习者曲线（selected_packs.json、library 的 learner 等）
LEARN_COUNT = os.environ.get("LEARN_COUNT", "fight")
OBSERVABLE = {"poison", "charge", "pierce", "enrage", "momentum"}
PIDX = {"counter": 1, "guard": 4, "mark": 5, "mimic": 6, "ward": 7}


WORLD = os.environ.get("WORLD", "A")      # 世界（devworld.WORLDS）：身份键按世界定，默认 A = 旧身份
# 登记（REG 环境变量，devworld.ACTIVE_REGISTRATION 读）：不设 = 11，下面的 setup 和以前逐字相同；REG=12 = 六池登记（docs/REGISTRATION_12.md）
REG = int(os.environ.get("REG", "").strip() or 11)


def setup():
    import devworld, tune
    if REG != 11:
        assert devworld.ACTIVE_REGISTRATION == REG, (devworld.ACTIVE_REGISTRATION, REG)
        cfg = devworld.REGISTRATIONS[REG]
        devworld.activate(); devworld.use_rotation(POOL or cfg["pool"])
        devworld.apply_world(WORLD)
        return tune.tuned(**{**cfg["prototype"], **EXTRA})
    devworld.activate(); devworld.use_rotation(POOL or devworld.PROTOTYPE_POOL)
    from adventure import TUNING
    devworld.apply_world(WORLD)       # 身份键 + 世界经济；在 tuned 快照之前设，退出时照样保留
    return tune.tuned(**{**devworld.PROTOTYPE, **EXTRA})


def stage1(salt):
    with setup():
        import gates, ledger as L
        from solver import run_once, ALL, SCREEN_ROUTES, _trial_rng
        from adventure import Run
        run = Run(SEED, validate=False); run._roll(salt); route = SCREEN_ROUTES[9]
        won = cln = 0; opp = collections.Counter(); mis = collections.Counter()
        for t in range(N_INF):
            led = L.Ledger()
            w = bool(run_once(run, ALL, route, _trial_rng(SEED ^ salt, gates.INFORMED_STREAM, t), information="observable", record=led))
            won += w; cln += L.clean(w, led, gates.CLEAN_THR, gates.CLEAN_MIN_OPP); opp.update(led.opp); mis.update(led.mis)
        allr = won / N_INF
        V = {m: allr - statistics.mean(run_once(run, ALL - {m}, route, _trial_rng(SEED ^ salt, gates.KNOW_STREAM, t), information="observable")
                                       for t in range(N_KNOW)) for m in run.drawn}
        stages = list(run.boss_stages); arrivals = [0]
        def entry(r): arrivals[0] += 1
        wins = {}
        for name, bk in [("ALL", ALL)] + [(m, ALL - {m}) for m in dict.fromkeys(stages)]:
            arrivals[0] = 0; w = 0
            for t in range(N_BOSS):
                w += bool(run_once(run, ALL, route, _trial_rng(SEED ^ salt, gates.BOSS_STREAM, t), information="observable", boss_know=bk, boss_entry=entry))
            wins[name] = (w, arrivals[0])
        arr = wins["ALL"][1]
        boss_req = {m: ((wins["ALL"][0] - wins[m][0]) / arr if arr else None) for m in dict.fromkeys(stages)}
        probe = {}
        for m in dict.fromkeys(stages):
            if m not in PIDX:
                continue
            got = [0, 0]
            def pentry(r): got[0] += 1; got[1] += r.punished[PIDX[m]] >= 1
            for t in range(N_BOSS):
                run_once(run, ALL - {m}, route, _trial_rng(SEED ^ salt, gates.PROBE_STREAM, t), information="observable", boss_entry=pentry, fight_boss=False)
            probe[m] = dict(arrivals=got[0], probed=(got[1] / got[0] if got[0] else None), measured=got[0] >= gates.PROBE_MIN_ARRIVALS)
        probe_ok = all((not v["measured"]) or v["probed"] >= gates.PROBE_BEFORE_BOSS_MIN for v in probe.values())
        extra = {}
        if REG == 12:
            # 登记 12 的懂规则参照 R1（公开信息的谨慎玩家）：同一条流 ev、同样 N_INF 条命；干净率用同一个 Ledger 口径（报告）
            if str(ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(ROOT / "scripts"))
            import regsel
            w1, rows = regsel.r1_wins(run, salt, N_INF, gates.INFORMED_STREAM, record_factory=L.Ledger)
            w0, _ = regsel.r1_wins(run, salt, N_INF, gates.INFORMED_STREAM)      # 记录器只记录、不改打法：不带记录再打一遍，计数必须相同
            assert w0 == w1, f"R1 带不带 Ledger 结果不同：{w0} vs {w1}"
            r1_clean = sum(L.clean(w, led, gates.CLEAN_THR, gates.CLEAN_MIN_OPP) for w, led in rows) / N_INF
            extra = dict(R1=w1 / N_INF, R1_clean=r1_clean, R1_wins=w1, reference="R1", r1_variant=__import__("devworld").R1_VARIANT)
        return dict(salt=salt, **extra, drawn=list(run.drawn), boss=stages, ALL=allr, clean=cln / N_INF, V=V, Vmin=min(V.values()),
                    boss_arrive=arr / N_BOSS, boss_pass_ALL=(wins["ALL"][0] / arr if arr else None), boss_req=boss_req,
                    boss_req_min=(min(v for v in boss_req.values() if v is not None) if arr else None), probe=probe, probe_ok=probe_ok,
                    observer_sees={m: m in OBSERVABLE for m in run.drawn}, opp_per_run={m: opp[m] / N_INF for m in run.drawn},
                    err={m: (mis[m] / opp[m] if opp[m] else None) for m in run.drawn})


def stage2(pack):
    with setup():
        import gates
        from solver import NONE, blind_gate, _trial_rng, run_once
        from adventure import Run
        runs = []
        for salt in pack:
            r = Run(SEED, validate=False); r._roll(salt); runs.append((salt, r))
        pairs = blind_gate(full=True); best = dict(ge2=-1); per_map_max = [0.0] * 4; n_pos = 0
        for k, (v, r) in enumerate(pairs):
            ge2 = 0; per = [0] * 4
            for t in range(gates.N_SCREEN):
                w = [bool(run_once(rr, NONE, r, _trial_rng(SEED ^ s, gates.SCREEN_STREAM, t), information="observable", blind=v)) for s, rr in runs]
                ge2 += sum(w) >= gates.PACK_MIN_CLEARS; per = [a + b for a, b in zip(per, w)]
            per = [p / gates.N_SCREEN for p in per]; per_map_max = [max(a, b) for a, b in zip(per_map_max, per)]
            g = ge2 / gates.N_SCREEN; n_pos += g > 0
            if g > best["ge2"] or (g == best["ge2"] and max(per) > best.get("single", 0)):
                best = dict(ge2=g, single=max(per), line=getattr(v, "name", None) or type(v).__name__, k=k)
        return dict(pack=list(pack), blind_screen=best, per_map_max=per_map_max, lines_with_any_pack_clear=n_pos, lines=len(pairs))


def learn(arg):
    pack, t0, t1 = arg
    with setup():
        import gates, solver, learner
        from solver import run_once, _trial_rng, SCREEN_ROUTES
        from adventure import Run
        rows = []
        for t in range(t0, t1):
            rules = learner.LearnedRules(solver.CARD_SKILLS, need=2); won, known = [], []
            for life, salt in enumerate(pack, 1):
                run = Run(SEED, validate=False); run._roll(salt); fight_no = [0]
                bc = (learner.belief_for(rules, lambda: (life, fight_no[0]), poison_this_fight=False) if LEARN_COUNT == "legacy" else learner.counted_beliefs(rules, life))
                won.append(bool(run_once(run, rules, SCREEN_ROUTES[9], _trial_rng(SEED ^ salt, f"{gates.LEARN_STREAM}{t}", life), information="observable",
                                         belief_cls=bc)))
                known.append(len(rules.known - set(solver.CARD_SKILLS)))
            rows.append(dict(t=t, won=won, known=known, learned_life={m: w[0] for m, w in rules.learned_at.items()}))
        return dict(pack=list(pack), rows=rows)


def cell(job):
    kind, arg = job
    return (kind, {"s1": stage1, "s2": stage2, "ln": learn}[kind](arg))


if __name__ == "__main__":
    t0 = time.time()
    with setup():
        import devworld, gates
        from adventure import Run
        START = START or gates.SALT_START_VALIDATION
        pool = set(POOL or devworld.PROTOTYPE_POOL); packs, cur, dropped, scanned = [], [], 0, 0
        for s in range(START, START + 200000):
            r = Run(SEED, validate=False); r._roll(s); scanned += 1
            if not devworld.two_rounds(r):
                continue
            cur.append((s, set(r.drawn)))
            if len(cur) == gates.PACK_SIZE:
                if set().union(*(d for _, d in cur)) == pool:
                    packs.append([s for s, _ in cur])
                else:
                    dropped += 1
                cur = []
            if len(packs) >= NPACK:
                break
        salts = [s for p in packs for s in p]
    print(f"阶段 0：{len(packs)} 个包（salt ≥ {START}，扫 {scanned} 个 salt，按顺序成包），覆盖不全丢掉 {dropped} 个", flush=True)
    print(f"变体旋钮 {EXTRA}  池 {POOL or '登记池'}  阶段 {sorted(STAGES)}", flush=True)
    LB = 20
    jobs = ([("s2", p) for p in packs if "s2" in STAGES] + [("s1", s) for s in salts if "s1" in STAGES]
            + [("ln", (p, a, min(a + LB, N_LEARN))) for p in packs for a in range(0, N_LEARN, LB) if "ln" in STAGES])
    with mp.Pool(WORKERS) as pool_:
        res = pool_.map(cell, jobs, chunksize=1)
    S1 = {r["salt"]: r for k, r in res if k == "s1"}; S2 = {tuple(r["pack"]): r for k, r in res if k == "s2"}
    LN = collections.defaultdict(list)
    for k, r in res:
        if k == "ln":
            LN[tuple(r["pack"])].extend(r["rows"])
    nan = float("nan")
    print(f"\n阶段 1+2（N_INF={N_INF}, N_KNOW={N_KNOW}, N_BOSS={N_BOSS}, 盲筛 N={gates.N_SCREEN}, 学习者 N={N_LEARN}）")
    print(f"{'包':>3}{'ALL均':>7}{'ALL低':>7}{'干净均':>7}{'干净低':>7}{'Vmin':>7}{'boss低':>7}{'盲P≥2/4':>8}{'盲单图':>7}{'gap普':>7}{'gap净':>7}  学习者四命通关       门")
    finalists = []; summary = []
    for i, p in enumerate(packs, 1):
        maps = [S1[s] for s in p] if "s1" in STAGES else []
        if not maps:
            continue
        alls = [m["ALL"] for m in maps]; clns = [m["clean"] for m in maps]; vmin = min(m["Vmin"] for m in maps); bmin = min(m["boss_req_min"] for m in maps)
        b = S2[tuple(p)]["blind_screen"] if tuple(p) in S2 else dict(ge2=nan, single=nan, line=None)
        if tuple(p) not in S2:
            S2[tuple(p)] = dict(blind_screen=b, per_map_max=[nan] * 4)
        gap_p = statistics.mean(alls) - b["ge2"]; gap_c = statistics.mean(clns) - b["ge2"]
        ok = dict(Vmin=vmin >= gates.VMIN_MIN, boss=bmin >= gates.BOSS_STAGE_REQ, probe=all(m["probe_ok"] for m in maps), gap=(gap_p >= gates.GAP_MIN and gap_c >= gates.GAP_MIN))
        curve = [statistics.mean(r["won"][k] for r in LN[tuple(p)]) if LN[tuple(p)] else nan for k in range(4)]
        kn = [statistics.mean(r["known"][k] for r in LN[tuple(p)]) if LN[tuple(p)] else nan for k in range(4)]
        flag = " ".join(f"{k}{'✓' if v else '✗'}" for k, v in ok.items())
        if all(ok.values()):
            finalists.append(p); flag += " → 决赛"
        print(f"{i:>3}{statistics.mean(alls):>7.0%}{min(alls):>7.0%}{statistics.mean(clns):>7.0%}{min(clns):>7.0%}{vmin:>7.0%}{bmin:>7.0%}{b['ge2']:>8.1%}{max(S2[tuple(p)]['per_map_max']):>7.0%}{gap_p:>+7.0%}{gap_c:>+7.0%}  " + "/".join(f"{c:.0%}" for c in curve) + f"  {flag}")
        summary.append(dict(pack=p, ALL=alls, clean=clns, Vmin=vmin, boss_min=bmin, blind=b, gap=[gap_p, gap_c], learner_won=curve, learner_known=kn, ok=ok))
    if S1:
        cov = collections.Counter(m for p in packs for s in p for m in S1[s]["drawn"])
        print(f"\n六种机制在 {len(packs)} 个包 {4*len(packs)} 张图上的出现次数：" + "  ".join(f"{m}:{c}" for m, c in sorted(cov.items())))
        Vs = collections.defaultdict(list)
        for m_ in S1.values():
            for m, v in m_["V"].items():
                Vs[m].append(v)
        print("V 按机制：" + "  ".join(f"{m}: 均 {statistics.mean(v):.0%} 低 {min(v):.0%} <20%: {sum(x<.2 for x in v)}/{len(v)}" for m, v in sorted(Vs.items())))
        pr = [v["probed"] for m_ in S1.values() for v in m_["probe"].values() if v["measured"]]; um = sum(not v["measured"] for m_ in S1.values() for v in m_["probe"].values())
        if pr:
            print(f"探针前提：{len(pr)} 段量到，均 {statistics.mean(pr):.1%} 低 {min(pr):.1%}；{um} 段到达太少记未测")
        lo = sorted((m_["ALL"], s) for s, m_ in S1.items())[:5]
        print(f"可玩性风险：逐图 ALL 最低 " + "  ".join(f"{s}:{a:.0%}" for a, s in lo) + f"；<70% 的图 {sum(m_['ALL']<.7 for m_ in S1.values())}/{len(S1)}")
    print(f"决赛包 {len(finalists)} 个；按 salt 顺序最先通过的 {gates.K_CERT} 个进认证：{finalists[:gates.K_CERT]}")
    out = os.environ.get("OUT", str(ROOT / "results" / "validation_stage12.json"))
    json.dump(dict(what="validation batch: stages 0-2 + boss + probe premise + learner", seed=SEED, extra=EXTRA, pool=POOL, stages=sorted(STAGES), salt_start=START,
                   packs=packs, finalists=finalists, summary=summary, stage1=S1, stage2={",".join(map(str, k)): v for k, v in S2.items()},
                   learner={",".join(map(str, k)): v for k, v in LN.items()}, n_inf=N_INF, n_know=N_KNOW, n_boss=N_BOSS, n_learn=N_LEARN),
              open(out, "w"), ensure_ascii=False, indent=1, default=str)
    print(f"\n{time.time()-t0:.0f}s  -> {out}")
