"""正式（formal，2026-11-13）：正式实验的规则。用户「可以，那就把正式实验换成40回合上限，ward不10回合死，只hard，考试开始给3ward……
给1.3」→「守势保持现在的不规律，蓄力保持不等长，ward只有出单张盾才能过，补给给1.3」→「那就40不动，这次就叫做正式」。

= hard2 的全部开关（严格封印：整回合只出盾且盾吃到攻击才降一层；不打 boss，每个世界 4 条命；无对应表；考试关蓄力 2/3/4 不等长、
守势不规律 irr50），考试关封印开局和重封都是 3 层（教学 1 层），**没有封印回合时限**（PROTO_WARDLIMIT=off；地图回合上限照旧 40），
每张图的自动休息补给 = 1.3 × R1v2 掉血的固定量（表 r1v2x130，scripts/rest_tighten_scan.py 生成，冻结：sha256 不对就拒绝）。
hard2_rules / hard3_rules 与已跑的记录不动。真人 play_v3c1b_world.py --tier formal；模型 run_transverse_world.py / run_hard_chain.py --tier formal。

2026-11-14（用户「并且我希望每张图都能有ward可以吗」→「可以」）：正式改打图包 v7hard3（scripts/pack_v7hard3_build.py：v7hard2 里没有封印的
4 张图换成有封印的，每个世界封印 4/4 张图），补给表换成 r1v2x130b（16 张保留图与 r1v2x130 相同，4 张新图按同一公式）。还没有任何正式记录，
所以 REVISION 改成 11-14、记录目录仍是 formal_v1。
同日晚（用户「世界 3再换一张偏简单的保留图……」→「你自己做决定」）：改打 v7hard4（scripts/pack_v7hard4_build.py：W3 的 2500400 → 2501026，
同缺 momentum、有封印、E* 0.01071 → 0.00893；世界偏差 −2.2/+2.8/+3.1/−1.5/−2.3 %），补给表 r1v2x130c。v7hard3 与 r1v2x130b 原样保留，没有记录用过。"""
import hashlib, pathlib
import hard2_rules

REVISION = "formal-v1-2026-11-14"
RECORDS_SUBDIR = "formal_v1"
HUMAN_SUFFIX = "-formal"
RUN_TAG = "formal-"
RESTAMT = "r1v2x130c"
RESTAMT_SHA256 = "27eb3ed3bf0768ad40ee32dd8882169c5a88ae94740b25b9ea4027287726a01e"
PACK = pathlib.Path(__file__).resolve().parents[1] / "data/pack_v3c1_v7hard4.json"
PACK_SHA256 = "2c4b1ac653b2de9ceb670971b64f1a6fff14a844f5c5608c6d00f44faeb71886"
ENV = dict(hard2_rules.ENV, PROTO_WARDLIMIT="off", PROTO_RESTAMT=RESTAMT)
REFERENCE_STATUS = ("E* under the formal rules stored per map in pack v7hard4 maps_measured (world means -2.2/+2.8/+3.1/-1.5/-2.3 %); "
                    "scene references (score_scene_hv) not yet wired to this pack")


def check_table():
    p = pathlib.Path(__file__).resolve().parents[1] / "data/restamt" / f"{RESTAMT}.json"
    try:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        raise SystemExit(f"Cannot read the rest table {p}.") from None
    if sha != RESTAMT_SHA256:
        raise SystemExit(f"The rest table {p} is not the frozen one (its sha256 differs).")
