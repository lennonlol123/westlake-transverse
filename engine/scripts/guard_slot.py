"""守势格的每图映射（候选 v3 PROTO_GUARDCODE=map；docs/antagonist_boss/18_candidate_v3_spec.md §2「守势」）—— 运行时补丁，不改 core/。

用户（11-04，15 §8）：「守和攻击不和他本身的0和1绑定，0也可以是攻」；「守势不该是世界，是地图级别」；
「第一回合默认不亮，但攻受未知，第二回合一定会亮」。取代 11-04 白天暂存的「守相印 1 / 攻相印 2、从第一回合起就印」那一版
（暂存在 7bd852b9…/scratchpad/guard_slot_stage/，审查过、byte-identity 核对通过；本文件沿用它的两个补丁点和日志改写的办法）。

规则：
  · 引擎不变：状态 ("them", "guard") 照旧 1 = 守相（攻击被反弹）/ 0 = 攻相；反弹、随机流、伤害、seen、slots_changed 一样不碰。
  · 映射每张图抽一次：normal = 守相印 1、攻相印 0（同现在）；flipped = 守相印 0、攻相印 1。各 50 %，专用流
    Random(f"guard-code-v1:{identity_key}:map:{图 salt}").randrange(2)（1 = flipped）；boss 按 boss salt 另抽：…:boss:{boss salt}。
    同一个 salt 建几次都是同一张映射；一个 Run 里所有地图战斗（layers 的敌人）用 map 那一张，Run 的 boss 敌人（boss_enemies）用 boss 那一张。
  · 印不印照旧由引擎的画面定（PROTO_DISPLAY=seen：守势格这一场第一次变化之后才印 —— 守相每个 END 都翻，所以第 1 回合不印、第 2 回合起每回合都印；
    boss 第二阶段进场的守势同引擎 / D1 的规则）。印的值 = 映射(引擎值)。
  · 参与者看得到的地方全部按映射印：
      1. adventure._row（模块全局名）：怪方状态行里守势那一格。adventure.show 每次按全局名找 _row，所以 modelrun 按值导入的 show、
         public_observation 存进日志的观察快照、humanrun 印的画面、图形界面解析的画面文字、cautious.them_slots / fixed_habits._screen /
         value_habits 读的画面都跟着变。
      2. modelrun.HarnessLog.append（类属性）：modelrun.run_fight 那一帧写的动作 / END / "(locked attack resolves)" 行
         「<tag>  ->  B2: 1->0, …」里守势那一项改成「B2: m(1)->m(0)」（换阶段那一行同样）。映射是 0↔1 的双射，所以引擎变了印出的也变，
         不删项、不加项。modelrun 没载入时不导入它，等第一次画面渲染（_row）时再补（参与者的每一行动作 / END 之前都有一次画面渲染）。
    没有守势的怪（任何阶段都没有 guard）：一个字都不改。
  · 每个敌人在建图时（antagonist_proto 包的 Run._roll_world → tag_run）记上 _guard_code = (kind, salt, 映射名)；装着本补丁却遇到没记键的
    有守势的怪 → 渲染报错（GuardCodeMissing），不悄悄按引擎值印。

接口：install() / remove() / installed() / describe() / tag_run(run, salt) / code_name(kind, salt) / code_of(f) / mapping_of(f) /
  printed(v, f) / has_guard(f) / rewrite(f, line)。install 幂等；remove 把两个对象还原成装之前的同一个对象（装之后被别人换过 → 报错、一个也不还原；
  装之前已经不是引擎自己的函数 → install 报错）。
  COUNTERPROOF（核对的反证开关，默认 None）："engine" = 画面和日志都印引擎值（无视映射）；"invert" = 用反过来的映射；
  "log_untouched" = 日志不改；"screen_untouched" = 画面不改；"print_turn1" = 第 1 回合也把守势格印出来。生产里必须是 None（describe 记下）。
没做的（不归本文件）：run_fight 的 verbose 控制台打印引擎原行（只给操作员看）；旧的中文命令行入口 core/playadv.py、core/ui.py 自己拼差行；
  RULES.md 写的是旧画面（不改）；研究者侧按引擎状态建的参与者视角（core/experimenter.py 等）仍按引擎 0/1。参与者英文规则文字还没写
  （proto_play._cli_guard 在这个开关下拒绝开打）。
守势开场攻守的预抽（候选 v3b PROTO_GUARDSTART=map，spec 18 §8.4「守势开场攻守」；11-05 加，与上面的印法互相独立）：
  · 引擎原来在每场守势战构造时从 Fight.rng 抽一次开场相位（core/adventure.py:1435，每条命一副洗牌、所以每条命不同）。
  · 开着时改成建图时预抽：地图上每一场（第 i 层第 j 个节点）Random(f"guard-start-v1:{identity_key}:map:{图 salt}:{i}:{j}").randrange(2)，
    记在敌人上（_guard_start），同一张图各场可以不同，打之前就定死，与谁怎么打、第几条命无关。
  · 只管地图（11-05 用户「boss 不急，先做地图」）：boss 敌人不记、boss 战（is_boss）不经过这里，照旧由 antagonist_boss 的派生流 / 引擎定。
  · 怎么接：antagonist_proto 包的 Run._roll_world → tag_starts(run, salt)；Run._fight 包一层（install_start）：敌人第一阶段有守势、带着预抽值时，
    交给 Fight 的 rng 换成 StartRng —— 第一次 randrange(2) 交预抽值、不碰真流，之后的调用原样转给真流（不改牌堆、标记的任何一抽）。
  · 敌人第一阶段有守势却没带预抽值 → 报错（GuardStartMissing），不悄悄从对局的随机流里抽。
  接口：install_start() / remove_start() / start_installed() / start_value(kind, salt, i=None, j=None) / tag_starts(run, salt) / START_VERSION。
boss 第一版（11-06，PROTO_BOSS=v1，docs/antagonist_boss/32_boss_v1.md；默认 none 下一个字节也不变）：
  · tag_starts 另给 boss 敌人记 start_value("boss", boss salt)（boss 的 Run 由 antagonist_boss.build_boss → antagonist_proto.build(salt) 建，
    salt 就是 boss salt）；两个阶段用同一个值（第一阶段的守势、进场的守势）。boss 战照旧不经过本模块的 _fight（antagonist_boss 的 D1 补丁在
    Fight 构造时把它交给第一阶段的守势，换阶段时交给进场的守势）；boss 敌人没记就由 antagonist_boss 报错（BossGuardStartMissing）。
"""
import pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "core"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VERSION = "guard-code-v1-2026-11-04"
STREAM = "guard-code-v1"
MAPPINGS = dict(normal={1: 1, 0: 0}, flipped={1: 0, 0: 1})   # 映射名 → {引擎值: 印出的值}
KINDS = ("map", "boss")
USER_WORDS = ("2026-11-04: guard and attack stance are not bound to 0 and 1; drawn per map (the boss separately); turn 1 unlit, "
              "turn 2 always lit")
COUNTERPROOFS = (None, "engine", "invert", "log_untouched", "screen_untouched", "print_turn1")
COUNTERPROOF = None
_STATE = dict(installed=False, log=False)
_ORIG = {}
_MINE = {}
_RF_CODE = [None]


class GuardCodeMissing(RuntimeError):
    pass


# ---------------------------------------------------------------- 映射
def code_name(kind, salt):
    """kind ∈ ("map", "boss") 的这个 salt 用哪张映射："normal" / "flipped"。专用流，不碰任何别的流。"""
    from adventure import TUNING
    if kind not in KINDS:
        raise ValueError(f"kind={kind!r}: one of {KINDS}")
    r = random.Random(f"{STREAM}:{TUNING['identity_key']}:{kind}:{int(salt)}")
    return "flipped" if r.randrange(2) else "normal"


def tag_run(run, salt):
    """给 run 的每个敌人记上映射的键（地图战斗 = map，boss 敌人 = boss，同一个 salt）；run.guard_code 记一份。不抽 run 的任何随机数。"""
    salt = int(salt)
    m, b = code_name("map", salt), code_name("boss", salt)
    for layer in run.layers:
        for node in layer.nodes:
            if getattr(node, "enemy", None) is not None:
                node.enemy._guard_code = ("map", salt, m)
    for e in getattr(run, "boss_enemies", ()) or ():
        e._guard_code = ("boss", salt, b)
    run.guard_code = dict(rule=VERSION, stream=STREAM, salt=salt, map=m, boss=b)
    return run.guard_code


def has_guard(f):
    """这一场的怪在任何阶段有没有守势（没有的：画面、日志一个字不改）。"""
    e = getattr(f, "enemy", None)
    if "guard" in tuple(getattr(f, "parts", ())):
        return True
    if e is not None and hasattr(e, "parts_for"):
        return "guard" in e.parts_for(False) or "guard" in e.parts_for(True)
    return False


def code_of(f):
    """这一场用的映射名。敌人没记键 → GuardCodeMissing；键的 kind 与这一场是不是 boss 对不上 → 报错。"""
    tag = getattr(getattr(f, "enemy", None), "_guard_code", None)
    if tag is None:
        raise GuardCodeMissing("PROTO_GUARDCODE=map: this enemy carries no guard code (the Run was built before the patch, "
                               "or not through Run._roll_world)")
    kind, _salt, name = tag
    if kind != ("boss" if f.is_boss else "map"):
        raise GuardCodeMissing(f"PROTO_GUARDCODE=map: a {kind} enemy fought with is_boss={f.is_boss}")
    return name


def mapping_of(f):
    name = code_of(f)
    if COUNTERPROOF == "engine":
        return MAPPINGS["normal"]
    if COUNTERPROOF == "invert":
        return MAPPINGS["flipped" if name == "normal" else "normal"]
    return MAPPINGS[name]


def printed(v, f):
    """引擎值 v（0 / 1）在这一场印成几。"""
    m = mapping_of(f)
    if v not in m:
        raise ValueError(f"guard slot engine value {v!r} is not 0/1")
    return m[v]


# ---------------------------------------------------------------- 画面
def _label(tok):
    return tok.partition(":")[0]


def _row(fight, side, tier):
    out = _ORIG["_row"](fight, side, tier)
    if not _STATE["log"]:
        _patch_log()                                   # modelrun 后载入的情形
    if (side, tier) != ("them", "transient") or not has_guard(fight) or COUNTERPROOF == "screen_untouched":
        return out
    lab = fight.layout.L("them", "guard")
    toks = [t for t in out.split("  ") if t]
    hit = False
    for i, t in enumerate(toks):
        if _label(t) == lab:
            v = t.partition(":")[2]
            toks[i] = f"{lab}:{printed(int(v), fight)}"
            hit = True
    if not hit and COUNTERPROOF == "print_turn1" and fight.turn == 1 and "guard" in tuple(fight.parts):
        toks.append(f"{lab}:{printed(fight.state[('them', 'guard')], fight)}")
        toks.sort(key=_label)
    return "  ".join(toks)


# ---------------------------------------------------------------- 日志
def _caller_fight():
    code = _RF_CODE[0]
    fr = sys._getframe(2)
    for _ in range(3):
        if fr is None:
            return None
        if fr.f_code is code:
            return fr.f_locals.get("fight")
        fr = fr.f_back
    return None


def rewrite(f, line):
    """run_fight 写的一行动作 / END 行：守势那一项 "L: x->y" 改成 "L: m(x)->m(y)"；不是这种行、没有守势项、没有守势的怪，原样返回。"""
    import modelrun
    tag, sep, rest = line.partition("  ->  ")
    if not sep or rest.startswith("(") or line.startswith(modelrun.OBSERVATION_PREFIX) or not has_guard(f):
        return line
    lab = f.layout.L("them", "guard")
    toks = rest.split(", ")
    if not any(t.partition(": ")[0] == lab for t in toks):
        return line
    if sum(f.layout.L(*k) == lab for k in f.state) != 1:
        raise RuntimeError(f"guard_slot: label {lab!r} is not unique among the fight's slots; the log line cannot be rewritten safely")
    out = []
    for t in toks:
        l, _s, v = t.partition(": ")
        if l == lab:
            x, _a, y = v.partition("->")
            t = f"{lab}: {printed(int(x), f)}->{printed(int(y), f)}"
        out.append(t)
    return tag + sep + ", ".join(out)


def _append(self, line):
    if isinstance(line, str) and "  ->  " in line and COUNTERPROOF != "log_untouched":
        f = _caller_fight()
        if f is not None and getattr(f, "layout", None) is not None:
            line = rewrite(f, line)
    return _ORIG["append"](self, line)


# ---------------------------------------------------------------- 装 / 撤
def _is_engine_fn(fn, rel, name):
    code = getattr(fn, "__code__", None)
    return code is not None and pathlib.Path(code.co_filename).resolve() == (ROOT / rel).resolve() and code.co_name == name


def _patch_log():
    if _STATE["log"] or not _STATE["installed"]:
        return
    mr = sys.modules.get("modelrun")
    if mr is None:
        return
    import inspect
    assert pathlib.Path(mr.__file__).resolve().parent == (ROOT / "core").resolve(), f"modelrun 不是从 core/ 导入的：{mr.__file__}"
    H = mr.HarnessLog
    cur = H.__dict__.get("append")
    if not _is_engine_fn(cur, "core/modelrun.py", "append"):
        raise RuntimeError(f"modelrun.HarnessLog.append 已经不是 core/modelrun.py 的那一个（{cur!r}）：别的补丁换过它，不装")
    rf = inspect.unwrap(mr.run_fight)
    if not _is_engine_fn(rf, "core/modelrun.py", "run_fight"):
        raise RuntimeError(f"认不出 modelrun.run_fight 的原始函数（{rf!r}）")
    _RF_CODE[0] = rf.__code__
    _ORIG["append"], _MINE["append"] = cur, _append
    H.append = _append
    _STATE["log"] = True


def installed():
    return bool(_STATE["installed"])


def install():
    """装上（幂等；装着时只补一次日志，如果 modelrun 刚载入）。"""
    import adventure
    p = pathlib.Path(adventure.__file__).resolve()
    assert p.parent == (ROOT / "core").resolve(), f"adventure 不是从 core/ 导入的：{p}"
    if _STATE["installed"]:
        _patch_log()
        return describe()
    cur = adventure.__dict__.get("_row")
    if not _is_engine_fn(cur, "core/adventure.py", "_row"):
        raise RuntimeError(f"adventure._row 已经不是 core/adventure.py 的那一个（{cur!r}）：别的补丁换过它，不装")
    _ORIG.clear(); _MINE.clear()
    _ORIG["_row"], _MINE["_row"] = cur, _row
    adventure._row = _row
    _STATE.update(installed=True, log=False)
    try:
        _patch_log()
    except Exception:
        adventure._row = _ORIG["_row"]
        _ORIG.clear(); _MINE.clear()
        _STATE.update(installed=False, log=False)
        raise
    return describe()


def remove():
    """撤掉：adventure._row、HarnessLog.append（补过的话）还原成装之前的同一个对象。没装 → 什么也不做。
    装之后有别的补丁换过其中任何一个 → 报错，一个也不还原。敌人身上记的键不撤（只是属性，没装时没人读）。"""
    import adventure
    if not _STATE["installed"]:
        return
    wrong = []
    if adventure.__dict__.get("_row") is not _MINE["_row"]:
        wrong.append("adventure._row")
    mr = sys.modules.get("modelrun") if _STATE["log"] else None
    if _STATE["log"] and (mr is None or mr.HarnessLog.__dict__.get("append") is not _MINE["append"]):
        wrong.append("modelrun.HarnessLog.append")
    if wrong:
        raise RuntimeError(f"{wrong} 已经不是本补丁装的那个（装之后有别的补丁换过它）：不还原，先查清次序")
    adventure._row = _ORIG["_row"]
    if _STATE["log"]:
        mr.HarnessLog.append = _ORIG["append"]
    _ORIG.clear(); _MINE.clear(); _RF_CODE[0] = None
    _STATE.update(installed=False, log=False)


def describe():
    return dict(
        version=VERSION, installed=installed(), log_patched=bool(_STATE["log"]), counterproof=COUNTERPROOF, user_words=USER_WORDS,
        mappings={k: {"guard stance (engine 1)": v[1], "attack stance (engine 0)": v[0]} for k, v in MAPPINGS.items()},
        draw=f"per map: Random('{STREAM}:{{identity_key}}:map:{{map salt}}').randrange(2) (1 = flipped); the boss: ...:boss:{{boss salt}}",
        engine="unchanged: state ('them','guard') stays 1 = guard stance / 0 = attack stance and drives reflection; rng, damage, seen, "
               "slots_changed untouched; only the printed number changes",
        when="as the engine's display prints the slot (seen: from the first change, i.e. unprinted on turn 1, printed every turn from turn 2)",
        participant_paths=[
            "screen: adventure._row (module global) -> adventure.show -> modelrun fight_screen / public_observation / humanrun / GUI "
            "screen text / script screen readers (cautious.them_slots, fixed_habits._screen, value_habits)",
            "log: modelrun.HarnessLog.append, lines appended by modelrun.run_fight's own frame (card / END / locked attack / handover END)"],
        not_covered=["run_fight verbose console (operator only)", "legacy Chinese CLIs core/playadv.py, core/ui.py",
                     "RULES.md (old display text)", "researcher-side participant models (core/experimenter.py) keep engine 0/1",
                     "participant rule text not written (proto_play._cli_guard refuses PROTO_GUARDCODE=map)"])


# ---------------------------------------------------------------- 守势开场攻守的预抽（PROTO_GUARDSTART=map）
START_VERSION = "guard-start-v1-2026-11-05"
BOSS_START_VERSION = "guard-start-boss-v1-2026-11-06"   # boss 第一版（PROTO_BOSS=v1）：boss 的开场攻守 = Random("guard-start-v1:{identity_key}:boss:{boss salt}")
START_STREAM = "guard-start-v1"
_START = dict(installed=False)
_START_ORIG = {}


class GuardStartMissing(RuntimeError):
    pass


def start_value(kind, salt, i=None, j=None):
    """预抽的开场相位（引擎值：1 = 守相）。kind = "map"（要给层 i、节点 j）/ "boss"。专用流，不碰任何别的流。"""
    from adventure import TUNING
    if kind == "map":
        key = f"{START_STREAM}:{TUNING['identity_key']}:map:{int(salt)}:{int(i)}:{int(j)}"
    elif kind == "boss":
        key = f"{START_STREAM}:{TUNING['identity_key']}:boss:{int(salt)}"
    else:
        raise ValueError(f"kind={kind!r}: one of {KINDS}")
    return random.Random(key).randrange(2)


def boss_v1():
    """boss 第一版（antagonist_proto.PROTO_BOSS=v1，32 号文档）开着没有。本模块不导入 antagonist_proto（它导入本模块），只读已载入的那一个。"""
    ap = sys.modules.get("antagonist_proto")
    return getattr(ap, "BOSS", "none") == "v1"


def tag_starts(run, salt):
    """给 run 的地图敌人记上预抽的开场相位（按层、节点）；boss 敌人不记（boss 先不做）。run.guard_start 记一份。不抽 run 的任何随机数。
    boss 第一版（PROTO_BOSS=v1）：boss 敌人也记 —— start_value("boss", salt)（同一个值给两个阶段：第一阶段的守势和进场的守势，antagonist_boss 的
    D1 补丁读它，Fight.rng 一次也不抽）；run.guard_start 多 boss / boss_rule 两个键。默认（none）下一个字节也不变。"""
    salt = int(salt)
    rec = dict(rule=START_VERSION, stream=START_STREAM, salt=salt, map={})
    for i, layer in enumerate(run.layers):
        for j, node in enumerate(layer.nodes):
            e = getattr(node, "enemy", None)
            if e is not None:
                e._guard_start = start_value("map", salt, i, j)
                if "guard" in getattr(e, "parts_for", lambda _p: ())(False):
                    rec["map"][f"{i}:{j}"] = e._guard_start
    if boss_v1():
        g = start_value("boss", salt)
        for e in getattr(run, "boss_enemies", ()) or ():
            e._guard_start = g
        rec.update(boss=g, boss_rule=BOSS_START_VERSION)
    run.guard_start = rec
    return rec


class StartRng(random.Random):
    """Fight 构造时交给它的 rng：第一次 randrange(2)（core/adventure.py:1435）交预抽值、不碰真流；之后的调用原样走 random.Random（同一个种子）。"""

    def __init__(self, x=None):
        super().__init__(x)
        self._g0 = None

    def randrange(self, *a, **k):
        g = getattr(self, "_g0", None)
        if g is not None:
            if a != (2,) or k:
                raise RuntimeError(f"guard_slot.StartRng: the first draw is not the guard start ({a}, {k})")
            self._g0 = None
            return g
        return super().randrange(*a, **k)


def _fight(self, enemy, shuffle, boss=False):
    orig = _START_ORIG["_fight"]
    if boss or "guard" not in enemy.parts_for(False):
        return orig(self, enemy, shuffle, boss)       # boss 战不管（boss 先不做）；没有第一阶段守势的不管
    g = getattr(enemy, "_guard_start", None)
    if g is None:
        raise GuardStartMissing("PROTO_GUARDSTART=map: a guard enemy carries no pre-drawn start (the Run was built before the patch, "
                                "or not through Run._roll_world)")
    import adventure
    rng = StartRng(shuffle)
    rng._g0 = int(g)

    class _One:                                    # Run._fight 写的是 rng=random.Random(shuffle)：只在这一次调用里、只对 adventure 的全局名 random 交出 rng（真 random 模块不动）
        def __call__(self, _x=None):
            return rng
    old = adventure.random
    shim = type(sys)("random")
    shim.__dict__.update(old.__dict__)
    shim.Random = _One()
    adventure.random = shim
    try:
        f = orig(self, enemy, shuffle, boss)
    finally:
        adventure.random = old
    assert f.rng is rng and getattr(rng, "_g0", None) is None, "守势开场相位没有被交出去"
    return f


def start_installed():
    return bool(_START["installed"])


def install_start():
    """Run._fight 包一层（幂等）。装之前 Run._fight 已经被换过 → 照样包它（antagonist_proto 的删奖励绊线也包 Run._fight，装的次序固定）。"""
    import adventure
    if _START["installed"]:
        return
    R = adventure.Run
    _START_ORIG["_fight"] = R.__dict__["_fight"]
    R._fight = _fight
    _START["installed"] = True


def remove_start():
    import adventure
    if not _START["installed"]:
        return
    R = adventure.Run
    if R.__dict__.get("_fight") is not _fight:
        raise RuntimeError("adventure.Run._fight 已经不是 guard_slot 装的那个（装之后有别的补丁换过它）：不还原")
    R._fight = _START_ORIG.pop("_fight")
    _START["installed"] = False


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), ensure_ascii=False, indent=1))
