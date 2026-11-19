"""拮抗池原型诊断（2026-11-01，用户：「先查」）：懂规则参照 R1 在含动量 / 破势的图上为什么过不了 90 %。只测量，不改任何登记的东西。
同一批 68 张两轮图（results/proto13/antagonist_proto.json），同一条随机流（R1 门的 ev 流，逐命同种子），四种玩家：
  R1            登记 12 的懂规则参照，原样（Cautious + PublicBelief）。应逐图复现原型文件里的 R1。
  R1+动量识别   同上，只给 PublicBelief 补上基类 FightBelief 的那条动量识别（公开：没举盾、没出非攻击牌的回合末，怪的攻击数字涨了）。
                诊断用的仪器变体，不是登记的参照。PublicBelief 重写了回合末观察、没调父类，所以 R1 从来认不出动量。
  求解器-公开   solver.act 自己的懂规则打法（知识 ALL − 标记，FightBelief，只看公开信息），不经 Cautious。
  全知          solver.act，information="oracle"：从第一回合就知道每只怪是什么、标记代号的含义（特权信息，上限参照）。
每条命记每一场：机制、教学 / 复考 / boss、进场和离场血量、赢没赢 → 死在哪一场、各机制掉多少血。
用法：WORKERS=6 python3 -B scripts/antagonist_diag.py → results/proto13/antagonist_diag.json"""
import collections, datetime, json, os, pathlib, statistics, sys
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
import antagonist_proto as ap

N = int(os.environ.get("N", 200)); WORKERS = int(os.environ.get("WORKERS", 6))
VARIANTS = ("R1", "R1+momentum", "solver-public", "oracle")
OUT = ROOT / "results" / "proto13"


class Rec:
    belief = None

    def __init__(self):
        self.fights = []; self.cur = None; self.seen = collections.Counter()

    def enter(self, run, f, kinds):
        b = "+".join(sorted(f.parts)) or "plain"
        role = "boss" if f.is_boss else ("teach" if self.seen[b] == 0 else "test")
        if not f.is_boss:
            self.seen[b] += 1
        self.cur = [b, role, f.state[("me", "hp")]]

    def before_decision(self, f): pass
    def before_play(self, f, c): pass
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, *a): pass

    def leave(self, f, won):
        self.fights.append(self.cur + [f.state[("me", "hp")], bool(won)])

    def rest(self, run, mode): pass


def momentum_belief():
    import cautious

    class MomentumPublicBelief(cautious.PublicBelief):
        def observe_end_turn(self, f, hp_before, block_before, poison_before, charge_before=0, atk_before=None, played_non_attack=False):
            super().observe_end_turn(f, hp_before, block_before, poison_before, charge_before, atk_before, played_non_attack)
            if charge_before >= max(1, f.enemy.charge_max):
                return
            if atk_before is not None and not played_non_attack and block_before <= 0 and f.state[("them", "atk")] > atk_before:
                self.momentum = True          # 与 solver.FightBelief 同一条规则
    return MomentumPublicBelief


def job(arg):
    salt, variant = arg
    ap.setup()
    import cautious, devworld, solver, regsel
    from adventure import TUNING
    run = ap.build(salt); route = solver.SCREEN_ROUTES[9]
    MB = momentum_belief()
    saved = {k: TUNING[k] for k in devworld.R1_DISPLAY}; TUNING.update(devworld.R1_DISPLAY)
    out = []
    try:
        for t in range(N):
            rng = solver._trial_rng(regsel.search_seed() ^ salt, ap.R1_STREAM, t); rec = Rec()
            if variant in ("R1", "R1+momentum"):
                p = cautious.Cautious(devworld.R1_VARIANT)
                won = solver.run_once(run, solver.ALL - {"mark"}, route, rng, information="observable", act_policy=p.act, heal_veto=p.heal_veto,
                                      belief_cls=cautious.PublicBelief if variant == "R1" else MB, record=rec)
            elif variant == "solver-public":
                won = solver.run_once(run, solver.ALL - {"mark"}, route, rng, information="observable", record=rec)
            else:
                won = solver.run_once(run, solver.ALL, route, rng, information="oracle", record=rec)
            out.append((bool(won), rec.fights))
    finally:
        TUNING.update(saved)
    return salt, variant, out


def main():
    t0 = datetime.datetime.now()
    proto = json.loads((OUT / "antagonist_proto.json").read_text())
    maps = [r for r in proto["evaluated"] if r["two_rounds"]]
    jobs = [(r["salt"], v) for r in maps for v in VARIANTS]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(job, jobs, chunksize=1))
    by = {(s, v): o for s, v, o in res}
    mism = [r["salt"] for r in maps if abs(sum(w for w, _ in by[(r["salt"], "R1")]) / N - r["R1"]) > 1e-9]
    summary = {}
    for v in VARIANTS:
        rates = {r["salt"]: sum(w for w, _ in by[(r["salt"], v)]) / N for r in maps}
        deaths = collections.Counter(); loss = collections.defaultdict(list)
        for r in maps:
            for won, fights in by[(r["salt"], v)]:
                for b, role, h0, h1, w in fights:
                    loss[(b, role)].append(h0 - h1)
                if not won and fights:
                    deaths[(fights[-1][0], fights[-1][1])] += 1
        tot_d = sum(deaths.values())
        summary[v] = dict(rates=rates, pass90=sum(x >= .9 for x in rates.values()), median=statistics.median(rates.values()),
                          by_mech={m: dict(n=sum(m in r["drawn"] for r in maps),
                                           pass90=sum(rates[r["salt"]] >= .9 for r in maps if m in r["drawn"]),
                                           median=statistics.median([rates[r["salt"]] for r in maps if m in r["drawn"]]))
                                   for m in proto["pool"]},
                          deaths={f"{b}/{role}": n / tot_d for (b, role), n in deaths.most_common()},
                          hp_loss={f"{b}/{role}": round(statistics.mean(x), 1) for (b, role), x in sorted(loss.items())})
    out = dict(study="antagonist-diag-v1", n=N, stream=ap.R1_STREAM, variants=list(VARIANTS), r1_reproduced=not mism, r1_mismatch=mism,
               maps=[r["salt"] for r in maps], summary=summary, minutes=round((datetime.datetime.now() - t0).total_seconds() / 60, 1))
    (OUT / "antagonist_diag.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"R1 逐图复现原型：{'是' if not mism else '否 ' + str(mism)}；{out['minutes']} 分钟")
    for v in VARIANTS:
        s = summary[v]
        print(f"\n{v}: ≥.90 的图 {s['pass90']}/{len(maps)}，中位 {s['median']:.2f}")
        print("   含该机制的图 过门/张数 中位: " + "  ".join(f"{m} {d['pass90']}/{d['n']} {d['median']:.2f}" for m, d in s["by_mech"].items()))
        print("   死在哪（占死亡）: " + "  ".join(f"{k} {x:.0%}" for k, x in list(s["deaths"].items())[:7]))


if __name__ == "__main__":
    main()
