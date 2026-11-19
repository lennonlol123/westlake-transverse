"""固定策略对照表（2026-10-21，STUDY fixed-panel-v1）：一份有限、写明、冻结的固定（不随经验更新）打法清单，在主实验 25 个包上
测出「不学规则能走多远」，作为模型成绩旁边的对照。只测量，不认证，不换图，不改怪。

用户（GPT 审过，2026-10-21）定的方向：不再无限追着枚举所有查表和所有组合；冻结一份明确的清单，研究的承诺只覆盖这份清单。
强固定策略存在，说明「通关」不是「理解」的充分证据；它不说明这个世界没有学习价值。

清单（冻结在 results/sweeps/fixed_panel_list.json，生成后不再改；要改就换 STUDY 名）：
  A 认证族   blind_gate(full=True) 的 100 条线 × 17 条路线 = 1,700 对（core/solver.py）。逐图早已认证过（每对 913 命 / 图），
             这里不重跑，直接从认证文件读每张图上 1,700 对里最多的单命通关数（results/release_certification.json；
             B–E 是 results/worlds/<W>/library_certification.json）。
  B 条件习惯 条件打法筛查（scripts/shortcut_screen.py，v1 + v2）里**进过复测**的全部打法：底子 × 判法 × 反应 × 路线 × 暗。
             判法按角色写（except:mark 是「除标记格以外任何一格亮了」，在每个世界换成那个世界标记格的符号），所以同一条打法
             在五个世界都有定义。等价的合并：except:mimic ≡ any（模仿格在登记的池里永远不亮）；only:mimic 永远不触发，记成 never
             （反应无关，只剩底子 + 暗规则）。
测量（B 部分）：每套打法在 25 个包上各打两次 200 轮，每轮按站序连打五张图、每张一条命、同一套打法：
  select   流 LIB_SCREEN_STREAM + "/panel-select"：只用来挑每个包上最强的那套（X 最大；并列取五张图通关总数大的，再并列取序号小的）
  confirm  流 LIB_SCREEN_STREAM + "/panel-confirm"：报告用 —— 挑出来的那套在新流上的 X 和逐站单命通关率（避开「挑最大值」的偏高）
另报：清单里在 25 包 select 上 X 总和最大的那一套（全局最强的一条），它在每个包 confirm 上的成绩；confirm 上的清单最大值（偏高，只作参考）。
X = 五条命里 ≥ 2 条通关的轮数。画面 TUNING["state_slots"] = "seen"。
范围：只对这份清单作承诺。清单外的固定打法（全部 65,536 张血量查表、AdaptiveProbe、其他组合……）可能更强，这里不声称。
声明（清单哈希 + 参数 + 模块和数据文件的哈希）只追加写进 results/sweeps/fixed_panel_declarations.jsonl。
用法：python3 scripts/fixed_panel.py → results/sweeps/fixed_panel.json

登记 12（REG=12，docs/REGISTRATION_12.md）：main12()。清单 results/sweeps/fixed_panel_list.json 只读（冻结的，不重新生成、不改写）；
部分 A 读 results/reg12/worlds/<W>/library_certification.json；输出与声明在 results/reg12/sweeps/（STUDY 带 -reg12，PILOT=1 再带 -pilot）。
包：devworld.world_pack_names（登记 12），有 results/reg12/worlds/five_pack_plan.json 就只算它列的，否则全部；PILOT=1 读拼包结果 packs.json
（构图 pack=None）。可选 WORLDS=A,…、PACKS=名字,…、PACKRUNS=…（默认 200）。"""
import collections
import datetime
import gc
import hashlib
import json
import os
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))
STUDY = "fixed-panel-v1"
SEED = 9065
WORKERS = 6
PACKRUNS = 200
CHUNK = 25                      # 每个作业：一个包 × 一条流 × 这么多套打法（五张图只构造一次）
OUT = ROOT / "results" / "sweeps"
LIST = OUT / "fixed_panel_list.json"
SCREENS = (OUT / "shortcut_screen.json", OUT / "shortcut_screen_v2.json")
ROLES = ("charge", "guard", "mark", "mimic", "ward")
HASHED = ["core/adventure.py", "core/solver.py", "core/devworld.py", "core/gates.py", "core/tune.py", "core/camp.py", "core/namegen.py", "core/cautious.py",
          "scripts/shortcut_screen.py", "scripts/fixed_panel.py", "results/worlds/five_pack_plan.json"]


def file_hashes():
    h = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in HASHED}
    h["results/sweeps/fixed_panel_list.json"] = hashlib.sha256(LIST.read_bytes()).hexdigest()[:16]
    return h


_WH = None


def worker_hashes():
    global _WH
    if _WH is None:
        _WH = file_hashes()
    return _WH


def slot_roles(world, salt=None, pack=None):
    """这个世界的怪方状态槽：符号 → 角色（每个世界一套固定的符号排列）。登记 12 传 salt（pack 可为 None）。"""
    import devworld
    if salt is None:
        pack = f"{world}-1"
        salt = devworld.world_pack_names(world)[pack][0]
    run = devworld.build_world(world, SEED, salt, pack)
    i = next(k for k, layer in enumerate(run.layers) if layer.kinds() != ["rest"])
    f = run.fight_at(i, 0)
    return {f.layout.L("them", m): m for m in ROLES}


def canonical(b, trig, resp, ri, dark, roles):
    if ":" in trig:
        kind, lab = trig.split(":")
        trig = f"{kind}:{roles[lab]}"
    if trig == "except:mimic":
        trig = "any"
    if trig == "only:mimic":
        trig, resp = "never", "-"
    return (b, trig, resp, ri, dark or "none")


def freeze():
    """从两版筛查的复测记录生成清单。清单文件已在就只核对、不改写。"""
    import shortcut_screen as ss
    import devworld
    s1, s2 = ss.strategies(), ss.strategies2()
    roles = {w: slot_roles(w) for w in "ABCDE"}
    prov = collections.defaultdict(list)
    for path, ver in zip(SCREENS, (1, 2)):
        d = json.loads(path.read_text())
        for r in d["retest"]:
            if ver == 1:
                b, trig, resp, ri = s1[r["sid"]]; dark = None
            else:
                sid1, dark = s2[r["sid"]]; b, trig, resp, ri = s1[sid1]
            prov[canonical(b, trig, resp, ri, dark, roles[r["world"]])].append(dict(version=ver, world=r["world"], pack=r["pack"], X=r["X"], n=r["n"]))
        del d; gc.collect()
    bases = ss.bases()
    items = [dict(id=i, base=b, base_name=getattr(bases[b], "name", None) or type(bases[b]).__name__, trigger=t, response=resp,
                  route=ri, dark=dark, retested_on=sorted(prov[(b, t, resp, ri, dark)], key=lambda x: (x["world"], x["pack"], x["version"])))
             for i, (b, t, resp, ri, dark) in enumerate(sorted(prov))]
    body = dict(study=STUDY, what="frozen fixed-strategy panel, part B: every conditional habit re-tested by shortcut-screen v1 or v2, "
                                  "written in slot roles (translated to each world's symbols at run time); equivalences merged "
                                  "(except:mimic == any; only:mimic never fires -> 'never')",
                source=[str(p.relative_to(ROOT)) for p in SCREENS], slot_roles=roles, n=len(items), items=items)
    if LIST.exists():
        old = json.loads(LIST.read_text())
        if old["items"] != body["items"]:
            raise SystemExit("清单已经冻结，而这次生成的不一样：不改写。")
        return old
    LIST.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return body


def concrete(item, roles_inv):
    """角色写法 → 这个世界的判法字符串。"""
    t = item["trigger"]
    if t == "never":
        return f"only:{roles_inv['mimic']}", "dodge"
    if ":" in t:
        kind, role = t.split(":")
        return f"{kind}:{roles_inv[role]}", item["response"]
    return t, item["response"]


def panel_job(job):
    world, pack, maps, stream, ids = job[:5]
    build_pack = job[5] if len(job) > 5 else pack          # 登记 12 试跑：构图用的包名（None），结果仍按显示名 pack 记
    import gates
    import devworld
    import shortcut_screen as ss
    from adventure import TUNING
    items = json.loads(LIST.read_text())["items"]
    roles_inv = {m: lab for lab, m in (slot_roles(world) if len(job) <= 5 else slot_roles(world, maps[0], build_pack)).items()}
    runs = [devworld.build_world(world, SEED, s, build_pack) for s in maps]
    import solver
    full = gates.LIB_SCREEN_STREAM + "/panel-" + stream
    out = []
    TUNING["state_slots"] = "seen"
    for i in ids:
        it = items[i]
        base = ss.bases()[it["base"]]
        trig, resp = concrete(it, roles_inv)
        dark = None if it["dark"] == "none" else it["dark"]
        route = ss.routes()[it["route"]]
        per_map = [0] * len(maps)
        X = 0
        for t in range(PACKRUNS):
            c = 0
            for k, (run, s) in enumerate(zip(runs, maps)):
                w = bool(solver.run_once(run, solver.NONE, route, solver._trial_rng(SEED ^ s, full, t), information="observable",
                                         blind=base, act_policy=ss.make_act(base, trig, resp, dark), record=ss.TrackSeen()))
                per_map[k] += w; c += w
            X += c >= 2
        out.append(dict(id=i, X=X, per_map=per_map))
    TUNING["state_slots"] = "hidden"
    return dict(world=world, pack=pack, stream=stream, rows=out, hashes=worker_hashes())


def cert_best(world, salt):
    f = ROOT / "results" / ("release_certification.json" if world == "A" else f"worlds/{world}/library_certification.json")
    v = json.loads(f.read_text())["verdict"].get(str(salt))
    return None if v is None else dict(max_clears=v["max_clears"], n=v["n"], rate=round(v["max_clears"] / v["n"], 4), passes=v["passes"])


def declare(panel):
    decl = dict(study=STUDY, list_file=str(LIST.relative_to(ROOT)), n_part_b=panel["n"], packruns=PACKRUNS,
                streams=dict(select="LIB_SCREEN_STREAM/panel-select", confirm="LIB_SCREEN_STREAM/panel-confirm"),
                scope="25 main-study packs (results/worlds/five_pack_plan.json)", display="state_slots='seen'",
                part_a="certification family (1,700 line-route pairs), read from the certification files, not re-run",
                report=dict(per_pack="strategy with the largest X on select (ties: more single-life clears, then lower id); its X and per-station rates on confirm",
                            global_best="strategy with the largest total X over the 25 packs on select; its confirm X per pack",
                            panel_max_confirm="largest X on confirm per pack (optimistic, reference only)"),
                promise="claims about fixed strategies cover only this panel; strategies outside it may do better",
                not_certification=True, files=file_hashes())
    log = OUT / "fixed_panel_declarations.jsonl"
    old = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    same = [d for d in old if d.get("study") == STUDY]
    body = lambda d: {k: v for k, v in d.items() if k != "written"}
    if same and body(same[-1]) != body(decl):
        raise SystemExit(f"{STUDY} 已经声明过，而清单、代码或参数变了：换 STUDY 名再跑。")
    if not same:
        with log.open("a") as fh:
            fh.write(json.dumps(dict(decl, written=datetime.datetime.now().isoformat(timespec="seconds")), ensure_ascii=False) + "\n")
    return decl


def _init12(hashed):
    global HASHED, _WH
    HASHED = list(hashed); _WH = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in HASHED}


def main12():
    """登记 12：冻结清单 B 在登记 12 的包上（两条流各 PACKRUNS 轮）；部分 A 读登记 12 的认证文件。"""
    global HASHED, PACKRUNS
    t0 = datetime.datetime.now()
    import regsel
    import devworld
    assert regsel.IS12
    pilot = bool(os.environ.get("PILOT"))
    PACKRUNS = int(os.environ.get("PACKRUNS", PACKRUNS))
    out_dir = regsel.SWEEPS_DIR; out_dir.mkdir(parents=True, exist_ok=True)
    study = STUDY + "-reg12" + ("-pilot" if pilot else "")
    panel = json.loads(LIST.read_text())                   # 冻结的清单，只读
    worlds = [w for w in os.environ.get("WORLDS", "ABCDE").replace(",", "") if w.strip()]   # "ABCDE" 或 "A,B"：都按字母拆（2026-10-28 修：原先默认值被当成一个世界名）
    want = set(x for x in os.environ.get("PACKS", "").split(",") if x)
    plan_f = regsel.WORLDS_DIR / "five_pack_plan.json"
    plan = json.loads(plan_f.read_text())["packs_per_world"] if plan_f.exists() else None
    packs = []                                              # (世界, 显示名, 五张图, 构图包名)
    for w in worlds:
        if pilot:
            f = regsel.WORLDS_DIR / w / "packs.json"
            named = [(f"{w}12-c{i + 1}", tuple(p), None) for i, p in enumerate(json.loads(f.read_text())["packs"])] if f.exists() else []
        else:
            named = [(n, tuple(m), n) for n, m in devworld.world_pack_names(w, 12).items() if plan is None or n in plan.get(w, [])]
        packs += [(w, n, m, bp) for n, m, bp in named if not want or n in want]
    if not packs:
        raise SystemExit("登记 12 下没有包可算")
    HASHED = [h for h in HASHED if not h.startswith("results/")] + ["scripts/regsel.py", "results/sweeps/fixed_panel_list.json"] + \
             [str(f.relative_to(ROOT)) for f in [plan_f] + [regsel.WORLDS_DIR / w / n for w in worlds for n in ("packs.json", "selected_packs.json", "library_certification.json")] if f.exists()]
    files = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in HASHED}
    decl = dict(study=study, registration=12, list_file=str(LIST.relative_to(ROOT)), n_part_b=panel["n"], packruns=PACKRUNS,
                streams=dict(select="LIB_SCREEN_STREAM/panel-select", confirm="LIB_SCREEN_STREAM/panel-confirm"),
                packs=[(w, n, list(m)) for w, n, m, _ in packs], display="state_slots='seen'",
                part_a="registration-12 certification family, read from results/reg12/worlds/<W>/library_certification.json, not re-run",
                promise="claims about fixed strategies cover only this panel; strategies outside it may do better", not_certification=True, files=files)
    log = out_dir / "fixed_panel_declarations.jsonl"
    old = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    same = [d for d in old if d.get("study") == study]
    body = lambda d: {k: v for k, v in d.items() if k != "written"}
    if same and body(same[-1]) != body(decl) and not pilot:
        raise SystemExit(f"{study} 已经声明过，而清单、代码或参数变了：换 STUDY 名再跑。")
    if not same or (pilot and body(same[-1]) != body(decl)):
        with log.open("a") as fh:
            fh.write(json.dumps(dict(decl, written=datetime.datetime.now().isoformat(timespec="seconds")), ensure_ascii=False) + "\n")
    ids = list(range(panel["n"]))
    jobs = [(w, n, m, stream, ids[i:i + CHUNK], bp) for stream in ("select", "confirm") for (w, n, m, bp) in packs for i in range(0, len(ids), CHUNK)]
    with ProcessPoolExecutor(WORKERS, initializer=_init12, initargs=(HASHED,)) as ex:
        res = list(ex.map(panel_job, jobs))
    bad = [r for r in res if r.pop("hashes") != files]
    if bad:
        raise SystemExit(f"工作进程读到的文件和声明对不上（{len(bad)} 个作业）：结果不写。")
    m = collections.defaultdict(dict)
    for r in res:
        for row in r["rows"]:
            m[(r["world"], r["pack"], r["stream"])][row["id"]] = row
    key = lambda row: (row["X"], sum(row["per_map"]), -row["id"])
    total = collections.Counter()
    for (w, n, maps, _) in packs:
        for i, row in m[(w, n, "select")].items():
            total[i] += row["X"]
    g = max(total, key=lambda i: (total[i], -i))

    def cert_best12(world, salt):
        f = regsel.WORLDS_DIR / world / "library_certification.json"
        v = json.loads(f.read_text())["verdict"].get(str(salt)) if f.exists() else None
        return None if v is None else dict(max_clears=v["max_clears"], n=v["n"], rate=round(v["max_clears"] / v["n"], 4), passes=v["passes"])
    out = dict(study=study, registration=12, declaration=decl, global_best=dict(id=g, item=panel["items"][g], select_total_X=total[g]), packs={})
    for (w, n, maps, _) in packs:
        sel, con = m[(w, n, "select")], m[(w, n, "confirm")]
        best = max(sel.values(), key=key); b = best["id"]
        out["packs"][f"{w}/{n}"] = dict(
            maps=list(maps), part_a_cert_best_single_life=[cert_best12(w, s) for s in maps],
            best=dict(id=b, item=panel["items"][b], select_X=best["X"], confirm_X=con[b]["X"], n=PACKRUNS,
                      confirm_station_rates=[round(x / PACKRUNS, 4) for x in con[b]["per_map"]]),
            global_best=dict(confirm_X=con[g]["X"], confirm_station_rates=[round(x / PACKRUNS, 4) for x in con[g]["per_map"]]),
            panel_max_confirm=max(r["X"] for r in con.values()),
            station_max_confirm=[round(max(r["per_map"][k] for r in con.values()) / PACKRUNS, 4) for k in range(len(maps))],
            matrix={st: {str(i): [row["X"]] + row["per_map"] for i, row in sorted(m[(w, n, st)].items())} for st in ("select", "confirm")})
    out["minutes"] = round((datetime.datetime.now() - t0).total_seconds() / 60, 1)
    f = out_dir / ("fixed_panel_pilot.json" if pilot else "fixed_panel.json")
    f.write_text(json.dumps(out, ensure_ascii=False))
    for k, v in out["packs"].items():
        print(f"{k:<12} 最强 #{v['best']['id']:<4} select {v['best']['select_X']:>3} → confirm {v['best']['confirm_X']:>3}/{PACKRUNS}  逐站 "
              + " ".join(f"{x:.0%}" for x in v["best"]["confirm_station_rates"]) + f"   全局那套 confirm {v['global_best']['confirm_X']:>3}")
    print(f"→ {f.relative_to(ROOT)}（{out['minutes']} 分钟）")


def main():
    t0 = datetime.datetime.now()
    import devworld
    panel = freeze()
    print(f"清单 B：{panel['n']} 套（{LIST.relative_to(ROOT)}）", flush=True)
    decl = declare(panel)
    plan = json.loads((ROOT / "results" / "worlds" / "five_pack_plan.json").read_text())
    packs = [(w, p, tuple(devworld.world_pack_names(w)[p])) for w in "ABCDE" for p in plan["packs_per_world"][w]]
    ids = list(range(panel["n"]))
    jobs = [(w, p, maps, stream, ids[i:i + CHUNK]) for stream in ("select", "confirm") for (w, p, maps) in packs for i in range(0, len(ids), CHUNK)]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = []
        for k, r in enumerate(ex.map(panel_job, jobs), 1):
            res.append(r)
            if k % 50 == 0:
                print(f"  {k}/{len(jobs)} 作业", flush=True)
    bad = [r for r in res if r.pop("hashes") != decl["files"]]
    if bad:
        raise SystemExit(f"工作进程读到的文件和声明对不上（{len(bad)} 个作业）：结果不写。")
    m = collections.defaultdict(dict)                     # (世界, 包, 流) → id → 行
    for r in res:
        for row in r["rows"]:
            m[(r["world"], r["pack"], r["stream"])][row["id"]] = row
    key = lambda row: (row["X"], sum(row["per_map"]), -row["id"])
    total = collections.Counter()
    for (w, p, maps) in packs:
        for i, row in m[(w, p, "select")].items():
            total[i] += row["X"]
    g = max(total, key=lambda i: (total[i], -i))
    out = dict(study=STUDY, declaration=decl, global_best=dict(id=g, item=panel["items"][g], select_total_X=total[g]), packs={})
    for (w, p, maps) in packs:
        sel, con = m[(w, p, "select")], m[(w, p, "confirm")]
        best = max(sel.values(), key=key)
        b = best["id"]
        out["packs"][f"{w}/{p}"] = dict(
            maps=list(maps),
            part_a_cert_best_single_life=[cert_best(w, s) for s in maps],
            best=dict(id=b, item=panel["items"][b], select_X=best["X"], confirm_X=con[b]["X"], n=PACKRUNS,
                      confirm_station_rates=[round(x / PACKRUNS, 4) for x in con[b]["per_map"]]),
            global_best=dict(confirm_X=con[g]["X"], confirm_station_rates=[round(x / PACKRUNS, 4) for x in con[g]["per_map"]]),
            panel_max_confirm=max(r["X"] for r in con.values()),
            station_max_confirm=[round(max(r["per_map"][k] for r in con.values()) / PACKRUNS, 4) for k in range(5)],
            matrix={s: {str(i): [row["X"]] + row["per_map"] for i, row in sorted(m[(w, p, s)].items())} for s in ("select", "confirm")})
    out["minutes"] = round((datetime.datetime.now() - t0).total_seconds() / 60, 1)
    f = OUT / "fixed_panel.json"
    f.write_text(json.dumps(out, ensure_ascii=False))
    print(f"全局最强一套：#{g} {panel['items'][g]}（select 上 25 包 X 总和 {total[g]}）")
    for k, v in out["packs"].items():
        print(f"{k:<7} 最强 #{v['best']['id']:<4} select {v['best']['select_X']:>3} → confirm {v['best']['confirm_X']:>3}/200  逐站 "
              + " ".join(f"{x:.0%}" for x in v["best"]["confirm_station_rates"]) + f"   全局那套 confirm {v['global_best']['confirm_X']:>3}")
    print(f"→ {f.relative_to(ROOT)}（{out['minutes']} 分钟）")


if __name__ == "__main__":
    if os.environ.get("REG", "").strip() == "12":
        main12()
    elif os.environ.get("REG", "").strip() not in ("", "11"):
        raise SystemExit("REG 只能是 11 或 12")
    else:
        main()
