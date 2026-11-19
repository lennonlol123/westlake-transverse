"""原型世界（N7，2026-11-03）：一个世界 = 4 张无 boss 的图 + 1 个独立 boss（docs/ANTAGONIST_PROTO.md:89-92 的决定）。
把已定的世界规则写成检查器 + 确定性选择器。不改 core/，不花 API，不跑任何对局。
不替用户选：哪几对是正式 boss（调用方给配对与阶段顺序）、boss 用哪个 salt（调用方给，「每个世界一个专门的 boss salt」仍是候选）。

规则（RULES_VERSION）：
  W0 4 张图都是两轮图（devworld.two_rounds：前 4 场战斗正好是 4 种不同机制），salt 互不相同；boss salt 不与图的 salt 相同。
     后一条是实现上的护栏，不是用户定的规则：标记代号的对应只由 salt 决定（core/adventure.py:3177-3179，mark-v1:{salt}），boss salt 等于
     某张图的 salt 就会让 boss 沿用那张图的对应，等于悄悄替用户定了待定的「标记对应按 salt 还是按世界」。
     PROTO_MARKMAP=world（候选，用户决定 4；docs/antagonist_boss/12_c10_v2_design.md §7）下这条理由不再成立（一个世界一张表，
     world_mark_table(spec)，键 = spec 的内容）；规则本身保留，不改。
  W1 图 1–3 的战斗合起来覆盖池里全部六种机制（antagonist_proto.PROTO；候选 v3 PROTO_POOL=nopierce 下是五种，规则不变、池跟着开关；
     那时世界 id 的键多一个 pool，verify 拒绝在另一个池下建的 spec）
  W2 boss 的两种机制都在图 1–3 的战斗里出现过
  W3 图 4 不出图 1–3 没出过的机制
  「出现过」按玩家实际打到的战斗算：每个战斗层固定打的那个节点（antagonist_proto.fixed_node 的规则，第 0 个节点；一层的节点同机制，
  见 fixed_node 的说明）的 behaviour，并核对它的集合与 run.drawn 一致、每层各节点同机制（不一致就报错，不悄悄换口径）。
  W4（只在候选 v3b PROTO_POOL=v3b 下，用户 2026-11-05）池里每种机制至少出现在 4 张图里的 3 张（同 W1–W3 的口径：玩家实际打到的战斗、
     fixed_node 规则）。五种机制、每张图四种不同的 → 等于 4 张图各缺一种、缺的互不相同（一种四张图都有，另四种各在三张里）。
     v3b 下 spec 的 rules = RULES_VERSION_V3B（W0–W4）；默认下没有 W4 这一项、rules 与输出逐字不变。
  W1 成立时 W2、W3 必然成立（池只有六种）；三条仍分别检查、分别记录，以后池或规则变了不会漏。
选择器（确定性，与玩家无关，不抽随机数）：
  候选按调用方给的顺序编号 0..n-1（不合格的候选记进 rejected，不参与）；
  图 1–3 = 满足 W1、W2 的下标三元组 i<j<k 里字典序最小的一组，世界里的顺序就是候选顺序 i, j, k；
  图 4 = 其余合格候选里满足 W3 的下标最小的一张。
  v3b（W4）：同一个次序，只是图 4 还要让四张图满足 W4 —— 先按三元组字典序、再按图 4 的下标，取第一个满足 W1–W4 的（确定性，不抽随机数）。
  找不到就报错（不悄悄放宽规则）。候选顺序由调用方负责（例如 salt 升序，或图库顺序）。
世界 spec（dict，JSON 可存）：kind、rules、proto_version、pool、id（"p13-" + 8 位十六进制，对玩家不透露机制）、maps（4 张：salt、fights、
  drawn、teach、test）、boss（salt、order = [第一阶段, 第二阶段]）、checks（W0–W3 各自 ok 与细节）、selection（选择器给的才有）。
  boss 建法：antagonist_boss.build_boss(boss.salt, tuple(boss.order), 0)（P1；同一 salt 两种顺序抽签相同，只差合并先后）。
用法：python3 -B scripts/proto_world.py select --boss guard,ward --boss-salt 2000000 [--salts a,b,c,…] [--scan N] [--out f.json]
      python3 -B scripts/proto_world.py check f.json"""
import hashlib, itertools, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
import antagonist_proto as ap

RULES_VERSION = "proto13-world-rules-2026-11-03"
RULES_VERSION_V3B = "proto13-world-rules-v3b-2026-11-05"   # 候选 v3b：W0–W3 + W4（每种机制至少在 3 张图里）
W4_MIN_MAPS = 3


def _v3b():
    return getattr(ap, "POOL", "full") == "v3b"


def rules_version():
    """本进程的世界规则版本（v3b 池下加 W4）。"""
    return RULES_VERSION_V3B if _v3b() else RULES_VERSION


def _w4(infos):
    """W4：池里每种机制出现在几张图里（按 drawn = 固定节点打到的机制集合）。"""
    per = {m: sum(m in set(x["drawn"]) for x in infos) for m in ap.PROTO}
    return dict(ok=len(infos) == N_MAPS and all(v >= W4_MIN_MAPS for v in per.values()), maps_per_mechanic=per,
                min_maps=W4_MIN_MAPS, missing_per_map=[sorted(set(ap.PROTO) - set(x["drawn"])) for x in infos])
KIND = "proto13-world"
N_MAPS = 4
ID_PREFIX = "p13-"


# ---------------------------------------------------------------- 一张图
def map_info(salt):
    """一张图的公开结构以外的事实（给检查器用）：两轮与否、每个战斗层固定节点的机制 / 角色、教学与考试的层号。"""
    import devworld
    run = ap.build(salt)
    fights, teach, test = [], {}, {}
    for i, L in enumerate(run.layers):
        kinds = set(L.kinds())
        if kinds == {"rest"}:
            continue
        if kinds != {"fight"}:
            raise ValueError(f"salt {salt} 第 {i + 1} 层混着 {sorted(kinds)}：原型的图每层要么全是战斗、要么全是休息")
        beh = {n.behaviour for n in L.nodes}
        if len(beh) != 1:
            raise ValueError(f"salt {salt} 第 {i + 1} 层各节点机制不同 {sorted(beh)}：「出现过」的口径不成立")
        node = L.nodes[0]                                    # fixed_node 的规则（第 0 个）；同层各节点同机制，所以与节点规则无关
        fights.append(node.behaviour)
        (teach if node.role == "teach" else test).setdefault(node.behaviour, i + 1)
    drawn = sorted(run.drawn)
    if sorted(set(fights)) != drawn:
        raise ValueError(f"salt {salt}：战斗层的机制 {sorted(set(fights))} 与 run.drawn {drawn} 不一致")
    return dict(salt=int(salt), two_rounds=bool(devworld.two_rounds(run)), fights=fights, drawn=drawn, teach=teach, test=test)


# ---------------------------------------------------------------- 检查器
def check(infos, boss_order, boss_salt):
    """infos = 4 张图的 map_info（按世界顺序）；boss_order = (第一阶段, 第二阶段)。返回 {W0..W3: dict(ok, …)}。"""
    pool = set(ap.PROTO)
    order = tuple(boss_order)
    salts = [m["salt"] for m in infos]
    w0 = dict(ok=len(infos) == N_MAPS and all(m["two_rounds"] for m in infos) and len(set(salts)) == len(salts)
              and boss_salt not in salts, salts=salts, two_rounds=[m["two_rounds"] for m in infos], boss_salt=boss_salt)
    seen13 = set().union(*(m["drawn"] for m in infos[:3])) if len(infos) >= 3 else set()
    w1 = dict(ok=seen13 == pool, maps_1_3=sorted(seen13), missing=sorted(pool - seen13))
    w2 = dict(ok=len(order) == 2 and order[0] != order[1] and set(order) <= pool and set(order) <= seen13,
              boss=list(order), missing=sorted(set(order) - seen13))
    new4 = set(infos[3]["drawn"]) - seen13 if len(infos) == N_MAPS else set(pool)
    w3 = dict(ok=len(infos) == N_MAPS and not new4, map_4=infos[3]["drawn"] if len(infos) == N_MAPS else None, new=sorted(new4))
    out = dict(W0_two_rounds_distinct=w0, W1_maps_1_3_cover_pool=w1, W2_boss_seen_in_maps_1_3=w2, W3_map_4_no_new_mechanic=w3)
    if _v3b():                                              # 候选 v3b：W4（默认下没有这一项）
        out["W4_each_mechanic_in_3_maps"] = _w4(infos)
    return out


def _world_id(maps, boss_salt, order):
    d = dict(rules=rules_version(), maps=list(maps), boss_salt=boss_salt, order=list(order))
    if tuple(ap.PROTO) != tuple(ap.PROTO_FULL):             # 候选 v3 PROTO_POOL=nopierce：池进键（同样的图 salt 在两种池里是不同的世界）；默认下键逐字不变
        d["pool"] = list(ap.PROTO)
    key = json.dumps(d, sort_keys=True)
    return ID_PREFIX + hashlib.blake2b(key.encode(), digest_size=4).hexdigest()


def _spec(infos, boss_order, boss_salt, name=None, selection=None):
    checks = check(infos, boss_order, boss_salt)
    bad = [k for k, v in checks.items() if not v["ok"]]
    if bad:
        raise ValueError(f"世界规则不满足 {bad}：{ {k: checks[k] for k in bad} }")
    salts = [m["salt"] for m in infos]
    wid = name or _world_id(salts, boss_salt, boss_order)
    if not wid.startswith(ID_PREFIX):
        raise ValueError(f"世界 id 要以 {ID_PREFIX!r} 开头（记录的 run_id 靠它和登记的世界分开）：{wid!r}")
    return dict(kind=KIND, rules=rules_version(), proto_version=ap.PROTO_VERSION, pool=list(ap.PROTO), id=wid,
                maps=[{k: m[k] for k in ("salt", "fights", "drawn", "teach", "test")} for m in infos],
                boss=dict(salt=int(boss_salt), order=list(boss_order)), checks=checks, selection=selection)


def make_world(map_salts, boss_order, boss_salt, name=None):
    """调用方指定 4 张图（按世界顺序）+ boss 顺序 + boss salt：检查规则，满足就返回 spec，不满足报错。"""
    ap.setup()
    if len(map_salts) != N_MAPS:
        raise ValueError(f"一个世界正好 {N_MAPS} 张图，给了 {len(map_salts)}")
    return _spec([map_info(s) for s in map_salts], tuple(boss_order), int(boss_salt), name)


def select_world(candidates, boss_order, boss_salt, name=None):
    """确定性选择器（规则见模块说明）。candidates：候选图 salt（两轮图；不是的记进 rejected）。"""
    ap.setup()
    order = tuple(boss_order)
    if len(order) != 2 or order[0] == order[1] or not set(order) <= set(ap.PROTO):
        raise ValueError(f"boss 顺序要是池里两种不同机制：{order}")
    cands, rejected, seen = [], [], set()
    for s in candidates:
        s = int(s)
        if s in seen or s == int(boss_salt):
            rejected.append(dict(salt=s, why="duplicate" if s in seen else "equals boss salt")); continue
        seen.add(s)
        m = map_info(s)
        (cands if m["two_rounds"] else rejected).append(m if m["two_rounds"] else dict(salt=s, why="not two-round"))
    pool = set(ap.PROTO)
    sets = [set(m["drawn"]) for m in cands]
    pick = None
    for i, j, k in itertools.combinations(range(len(cands)), 3):
        u = sets[i] | sets[j] | sets[k]
        if u == pool and set(order) <= u:
            rest = [x for x in range(len(cands)) if x not in (i, j, k) and sets[x] <= u]
            if _v3b():                                      # 候选 v3b：图 4 还要让四张图满足 W4
                rest = [x for x in rest if _w4([cands[i], cands[j], cands[k], cands[x]])["ok"]]
            if rest:
                pick = (i, j, k, rest[0]); break
    if pick is None:
        raise ValueError(f"{len(cands)} 张合格候选里找不到满足 W1–W3 的 4 张图（boss {order}）；不放宽规则")
    rule = ("maps 1-3 = lexicographically first index triple covering the pool and the boss pair; "
            "map 4 = lowest remaining index adding no new mechanic")
    if _v3b():
        rule += ("; v3b (W4): the first (triple, map 4) in that order whose 4 maps put every pool mechanic in at least "
                 f"{W4_MIN_MAPS} maps")
    sel = dict(rule=rule, candidates=len(candidates),
               eligible=len(cands), rejected=rejected, picked_index=list(pick), picked_salts=[cands[x]["salt"] for x in pick])
    return _spec([cands[x] for x in pick], order, int(boss_salt), name, selection=sel)


def verify(spec):
    """重建 4 张图，核对 spec 记的结构与规则（入口开打前调用；本进程的 TUNING 不同于建 spec 时就会在这里报错）。"""
    if spec.get("kind") != KIND or spec.get("rules") != rules_version():
        raise ValueError(f"不是本版的原型世界 spec：kind={spec.get('kind')} rules={spec.get('rules')}")
    ap.setup()                                              # 同 make_world / select_world：图要在原型的 TUNING 下建（幂等）。装了 boss 层时
    #                                                         boss 键由 antagonist_boss 登记的钩子写回（审查 2026-11-03 之前这一步把 boss_no_probe 改回 1）
    if "pool" in spec and list(spec["pool"]) != list(ap.PROTO):   # 候选 v3：spec 是在另一个池下建的（PROTO_POOL）；默认下所有 spec 都是六种，不变
        raise ValueError(f"世界 {spec['id']} 是在池 {spec['pool']} 下建的，本进程的池是 {list(ap.PROTO)}（PROTO_POOL）")
    if spec.get("surface", {}).get("name", "A") != getattr(ap, "WORLD", "A"):   # 世界外衣（43 号文档）：spec 没有 surface = A（旧包），行为不变
        raise ValueError(f"世界 {spec['id']} 是外衣 {spec.get('surface', {}).get('name', 'A')} 的，本进程是 PROTO_WORLD={getattr(ap, 'WORLD', 'A')}")
    infos = [map_info(m["salt"]) for m in spec["maps"]]
    for m, i in zip(spec["maps"], infos):
        if m["fights"] != i["fights"] or m["drawn"] != i["drawn"]:
            raise ValueError(f"salt {m['salt']} 重建出的战斗 {i['fights']} 与 spec 记的 {m['fights']} 不同")
    checks = check(infos, tuple(spec["boss"]["order"]), spec["boss"]["salt"])
    bad = [k for k, v in checks.items() if not v["ok"]]
    if bad:
        raise ValueError(f"世界 {spec['id']} 不满足 {bad}")
    return checks


# ---------------------------------------------------------------- 世界代号表（PROTO_MARKMAP=world，候选；12 §7.2）
def world_mark_table(spec):
    """这个世界的标记代号表（D13 内容键：排序后的图 salt、boss salt、阶段顺序；antagonist_proto.world_mark_table 的同一个实现）。
    spec 格式不变：表不写进 spec，也不写进任何参与者看得到的东西；同内容、不同 name 的世界同表。"""
    return ap.world_mark_table([m["salt"] for m in spec["maps"]], spec["boss"]["salt"], spec["boss"]["order"])


def mark_block(spec):
    """研究者侧记录用：规则、流名、表。"""
    return dict(rule="world", stream=ap.world_mark_stream([m["salt"] for m in spec["maps"]], spec["boss"]["salt"], spec["boss"]["order"]),
                table=list(world_mark_table(spec)))


def bind_world(run, spec):
    """把这个世界的表绑到 run 上（只在 PROTO_MARKMAP=world 下可调；ap.set_mark_table 在 salt 下报错）。"""
    ap.set_mark_table(run, world_mark_table(spec), f"world:{spec['id']}")


def world_runs(spec):
    """脚本按世界重放用：verify → 4 张图的 Run + boss ctx（antagonist_boss.build_boss，要先 setup_boss）；world 下 5 个 Run 都绑这个世界的表，
    salt 下不绑（每个 Run 按自己的 salt）。返回 dict(maps=[run × 4], boss=ctx, table=world 下的表或 None)。"""
    import antagonist_boss as ab
    verify(spec)
    runs = [ap.build(m["salt"]) for m in spec["maps"]]
    ctx = ab.build_boss(spec["boss"]["salt"], tuple(spec["boss"]["order"]), 0)
    assert list(ctx["phase_order"]) == list(spec["boss"]["order"]), (ctx["phase_order"], spec["boss"]["order"])
    table = None
    if ap.MARKMAP == "world":
        table = world_mark_table(spec)
        for run in runs + [ctx["run"]]:
            bind_world(run, spec)
    return dict(maps=runs, boss=ctx, table=table)


# ---------------------------------------------------------------- 存取
def save_worlds(path, specs, overwrite=False):
    path = pathlib.Path(path)
    if path.exists() and not overwrite:
        raise SystemExit(f"{path} 已存在：不覆盖（换一个文件名）")
    ids = [s["id"] for s in specs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"世界 id 重复：{ids}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(kind=KIND + "-list", rules=rules_version(), worlds=list(specs)), ensure_ascii=False, indent=1))
    return path


def load_worlds(path):
    """{id: spec}，按文件里的顺序。"""
    if not path:
        raise SystemExit("没有世界文件：给 --worlds 或设 PROTO_WORLDS")
    from world_pack_runtime import load_pack
    data = load_pack(path)
    specs = data["worlds"] if isinstance(data, dict) and "worlds" in data else [data]
    out = {}
    for s in specs:
        if s.get("kind") != KIND:
            raise ValueError(f"{path}：不是原型世界 spec")
        out[s["id"]] = s
    return out


def two_round_salts(n, start=None, cap=4000):
    """从 start（默认 SALT0）起按 salt 升序扫出 n 张两轮图（候选清单的一个确定性来源；不跑任何对局）。"""
    import devworld
    ap.setup()
    out, s = [], ap.SALT0 if start is None else int(start)
    while len(out) < n and s < (ap.SALT0 if start is None else int(start)) + cap:
        if devworld.two_rounds(ap.build(s)):
            out.append(s)
        s += 1
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("select")
    q.add_argument("--boss", required=True, help="第一阶段,第二阶段（例如 guard,ward）")
    q.add_argument("--boss-salt", type=int, required=True)
    q.add_argument("--salts", default="", help="候选图 salt，逗号分隔、按优先顺序；不给就从 SALT0 起扫 --scan 张两轮图")
    q.add_argument("--scan", type=int, default=40)
    q.add_argument("--name", default=None)
    q.add_argument("--out", default=None)
    c = sub.add_parser("check")
    c.add_argument("file")
    a = p.parse_args()
    if a.cmd == "select":
        cands = [int(x) for x in a.salts.split(",") if x] or two_round_salts(a.scan)
        spec = select_world(cands, tuple(a.boss.split(",")), a.boss_salt, a.name)
        print(json.dumps({k: spec[k] for k in ("id", "maps", "boss")}, ensure_ascii=False))
        if a.out:
            print("→", save_worlds(a.out, [spec]))
    else:
        for wid, spec in load_worlds(a.file).items():
            print(wid, {k: v["ok"] for k, v in verify(spec).items()})
