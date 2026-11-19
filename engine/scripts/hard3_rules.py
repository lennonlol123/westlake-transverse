"""hard3 = hard2-ward10-test3 + 休息补给收紧到 1.2 × R1v2 掉血（2026-11-13，用户「我要收紧」→「先换1.2出一批给我」→ 先只做真人可玩的版本）。
真人入口 play_v3c1b_world.py --tier hard3；模型 run_transverse_world.py / run_hard_chain.py --tier hard3（用户「我要1.2给sol」）。
hard2_rules 与 --tier hard 不动（DS 链 1 正按 hard2-ward10-test3 在跑）。
补给表 ~/agii_runs/restamt/r1v2x120.json（scripts/rest_tighten_scan.py 生成）冻结：sha256 不对就拒绝。"""
import hashlib, pathlib
import hard2_rules

REVISION = "hard3-ward10-test3-rest120-2026-11-13"
RECORDS_SUBDIR = "ward10_test3_rest120"
HUMAN_SUFFIX = "-hard3"
RUN_TAG = "hard3-"
RESTAMT = "r1v2x120"
RESTAMT_SHA256 = "d5145e76383d785d361f304f0fac09aa08564ab30f9782de2ff8051d57d59348"
ENV = dict(hard2_rules.ENV, PROTO_RESTAMT=RESTAMT)
REFERENCE_STATUS = "recalibration_required: budgets tightened per map (rest amounts r1v2x120); E* and scene references not yet computed"


def check_table():
    p = pathlib.Path.home() / "agii_runs/restamt" / f"{RESTAMT}.json"
    try:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        raise SystemExit(f"Cannot read the rest table {p}.") from None
    if sha != RESTAMT_SHA256:
        raise SystemExit(f"The rest table {p} is not the frozen one (its sha256 differs).")
