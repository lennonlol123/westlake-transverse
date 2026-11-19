"""固定节奏（2026-11-03 晚，固定手牌小原型验证用）：完全不看画面、不看敌人的开环打法 —— 每场从第一次决策起，按一个周期 1–3 的
「回合动作」序列循环出牌，每场重新从头开始。GPT（11-03）：「某些固定节奏可能成为新的通解」；固定手牌下每种操作每回合都可用，
所以「周期 ≤ 3 的固定节奏」是一个能穷举的有限集合。

回合动作（16 种；v2，审查 11-03 晚：治疗和别的操作谁先谁后会改变结局 —— 治疗不超过上限、标记的一下和守势的反弹在出牌当下落下、
一场打完 play_fight 就不再问，所以先攻击把怪打死能把治疗留给后面的战斗，先挨一下再治疗又能补回这一回合的伤 —— 两种顺序都列）：
  E 直接结束  A 攻击  B 盾  H 治疗  X 增伤  D 闪（2 费，占整回合）
  HA AH  HB BH  HX XH  XA AX  AB XB
不列的：BA —— AB 弱优于它（一下打死怪时 AB 不再出那张盾；别的都与顺序无关）；BX —— 与 XB 结局完全相同（增伤只管下一张攻击，盾只管回合末）。
H 和 D 合起来 3 费，出不了；一回合每种操作最多一次（用户 11-03 晚定），所以没有 AA、BB。
某张牌这一刻出不了（治疗用完：一条命 3 次；能量不够；抽牌版里不在手里）就跳过它，照常出这一回合的下一张。
不读画面、不读敌人、不自动治疗：路线 route() 的 heal_at = 0（solver.play_fight 的自动治疗永远不触发）；路线其余字段在现行版本下
不起作用（antagonist_proto.live_route：只剩 heal_at、enrage_budget，后者只给 solver.act 用）。

接口：OPTIONS、CODES、rhythms(max_period)（只给最短周期形式）、rid(r) / parse(s)、minimal(r)、make_act(r)、route()。"""
import itertools

OPTIONS = {
    "E": (),
    "A": ("attack",), "B": ("block",), "H": ("heal",), "X": ("buff_mark",), "D": ("dodge",),
    "HA": ("heal", "attack"), "AH": ("attack", "heal"), "HB": ("heal", "block"), "BH": ("block", "heal"),
    "HX": ("heal", "buff_mark"), "XH": ("buff_mark", "heal"),
    "XA": ("buff_mark", "attack"), "AX": ("attack", "buff_mark"),
    "AB": ("attack", "block"), "XB": ("buff_mark", "block"),
}
CODES = tuple(OPTIONS)


def rhythms(max_period=3):
    """周期 1..max_period、写成最短周期形式的全部节奏（每个是回合动作代号的元组），按周期、再按 CODES 的顺序。
    16 种回合动作时共 16 + 240 + 4,080 = 4,336 条（(A, A)、(A, A, A) 这类与 (A,) 完全相同的重复去掉了，v2）。
    同一个循环的不同起点算不同的节奏（每场从第 1 回合起对齐：地图的蓄力在第 3、6、9 回合放，boss 在第 2、5、8 回合，起点有关系）。"""
    out = []
    for p in range(1, max_period + 1):
        out += [r for r in itertools.product(CODES, repeat=p) if minimal(r) == r]
    return out


def rid(r):
    return ".".join(r)


def parse(s):
    r = tuple(s.split("."))
    assert all(c in OPTIONS for c in r), s
    return r


def minimal(r):
    """节奏的最短周期形式（(A, A) → (A,)、(A, A, A) → (A,)）。"""
    for p in range(1, len(r) + 1):
        if len(r) % p == 0 and r == r[:p] * (len(r) // p):
            return r[:p]
    return r


def make_act(r):
    """给 solver.play_fight 的 act_policy（每条命新建一个：里面记着这一场的起始回合）。读的只有玩家自己的东西：
    这一场是第几回合（相对开场）、这一回合已经出成了哪些种类（f.played_kinds）、某张牌现在出不出得了（f.can_play：手里有、能量够）。"""
    seq = [OPTIONS[c] for c in r]
    state = dict(f=None, t0=0)

    def act(f, know, kinds, belief=None, information=None):
        if state["f"] is not f:
            state["f"], state["t0"] = f, f.turn
        option = seq[(f.turn - state["t0"]) % len(seq)]
        for kind in option:
            if f.played_kinds.get(kind):
                continue
            name = kinds[kind]
            if f.can_play(name):
                return name
        return None
    return act


class _LazyRoute:
    """ROUTE 第一次用到时才 import solver（本模块可以在 setup() 之前导入）。"""
    _r = None

    def __get__(self, obj, owner):
        if _LazyRoute._r is None:
            import solver
            _LazyRoute._r = solver.Route(heal_at=0)
        return _LazyRoute._r


class _Holder:
    ROUTE = _LazyRoute()


def route():
    """节奏用的路线：solver.Route(heal_at=0)，其余默认值（现行版本下不起作用）。"""
    return _Holder.ROUTE


if __name__ == "__main__":
    rs = rhythms(3)
    print(len(rs), "rhythms (minimal forms,", len(CODES), "turn actions)")
