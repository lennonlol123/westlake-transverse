"""读槽位**数值**的固定手牌条件习惯（候选 v3，2026-11-04 晚；配合守势格的每图映射 guard_slot.py / PROTO_GUARDCODE=map：
守相印 1 或 0、攻相印 0 或 1，按图抽；蓄力 0 → 1 → 2；破势印封印层数）。底子取自 11-04 白天暂存的那一版
（7bd852b9…/scratchpad/guard_slot_stage/value_habits.py，当时配「守相 1 / 攻相 2」的画面），本版多一个触发 slot0、两组双规则。
fixed_habits 的触发只看「亮没亮」（非零）；守势一直印着 0 或 1，「亮 = 危险」那一套不再对守势成立 —— 公平起见，这里补一组只看印出的**值**的
不学习习惯，看新画面是不是只是把捷径换成了「看数字」。底子、回合动作代号、出牌机制与 fixed_habits / fixed_rhythms 完全相同。

每套 = 底子（fixed_habits.BASES：XA、AB、oB.XA、oB.AB、XA|AB）+ 1–2 条「触发 → 反应」+ 低血自动治疗（heal_at = fixed_habits.HEAL_AT）。
触发（只读画面上怪方状态行印出的整数，fixed_habits._screen → cautious.them_slots；标记槽不算，同 fixed_habits 的 slot）：
  slot0    除标记以外有一格印着正好 0
  slot1    除标记以外有一格印着正好 1
  slot2    除标记以外有一格印着 >= 2
  slotchg  除标记以外有一格的值和上一次决策时印的不同（「决策」= 这一场里每回合第一次决策，习惯在那一刻定这一回合的动作；
           一格出现或消失也算不同；每场第一个回合没有上一次，不触发）
反应：D（闪）、B（只举盾）、AB（攻击 + 盾）、E（这一回合什么都不做）—— 同 fixed_habits.RESPONSES。
单规则 5 底子 × 4 触发 × 4 反应 = 80 套；双规则（先查第一条）slot2>D + slot1>AB、slot1>D + slot2>AB（暂存版的两组）、
slot1>D + slot0>AB、slot0>D + slot1>AB（本版加：0 / 1 两种映射各一组），各配 5 个底子 = 20 套。共 100 套。
（只有底子、没有规则的 5 套就是 fixed_habits 的底子本身，不重复列；parse / make 仍接受它们，核对用来比对 fixed_habits。）
接口同 fixed_habits：habits() → [id]；make(id) → (act_policy, route)；parse(id)。id 形如 "oB.XA|slot2>D|slot1>AB"。
读画面要开人的 `?` 追踪：调用方用 antagonist_proto.screen("habit", record) 包记录器（同 fixed_habits）。
act_policy.trace：设成一个 list 时，每回合定动作那一刻记一条 (turn, 印出的槽, 触发了哪条, 动作)；只是记录，不影响出牌。"""
import fixed_habits as fh
import fixed_rhythms as fr

VERSION = "value-habits-v2-2026-11-04"   # v2（候选 v3）：加 slot0 与两组 0/1 双规则；v1 = 暂存版（slot1 / slot2 / slotchg，70 套）
BASES = fh.BASES
TRIGGERS = ("slot0", "slot1", "slot2", "slotchg")
RESPONSES = fh.RESPONSES
PAIRS = (("slot2", "D", "slot1", "AB"), ("slot1", "D", "slot2", "AB"), ("slot1", "D", "slot0", "AB"), ("slot0", "D", "slot1", "AB"))
HEAL_AT = fh.HEAL_AT


def habits():
    out = [f"{b}|{t}>{r}" for b in BASES for t in TRIGGERS for r in RESPONSES]
    out += [f"{b}|{t1}>{r1}|{t2}>{r2}" for b in BASES for (t1, r1, t2, r2) in PAIRS]
    return out


def parse(hid):
    parts = hid.split("|")
    if parts[0] == "XA" and len(parts) > 1 and parts[1] == "AB":   # "XA|AB" 底子本身含一个 |
        base, rest = "XA|AB", parts[2:]
    else:
        base, rest = parts[0], parts[1:]
    rules = [tuple(r.split(">")) for r in rest]
    assert base in BASES and all(len(x) == 2 and x[0] in TRIGGERS and x[1] in RESPONSES for x in rules), hid
    return base, rules


def base_action(base, k):
    """底子在这一场第 k 回合（0 起）的动作；与 fixed_habits.make 里的 base_action 逐字同规则。"""
    if base == "XA":
        return "XA"
    if base == "AB":
        return "AB"
    if base == "oB.XA":
        return "B" if k == 0 else "XA"
    if base == "oB.AB":
        return "B" if k == 0 else "AB"
    return "XA" if k % 2 == 0 else "AB"


def fired(trig, slots, prev, mark_lab):
    """slots = 这一次印出的 {符号: 值}，prev = 上一次决策印出的（None = 这一场第一次）。"""
    cur = {k: v for k, v in slots.items() if k != mark_lab}
    if trig == "slot0":
        return any(v == 0 for v in cur.values())
    if trig == "slot1":
        return any(v == 1 for v in cur.values())
    if trig == "slot2":
        return any(v >= 2 for v in cur.values())
    if prev is None:                                       # slotchg
        return False
    old = {k: v for k, v in prev.items() if k != mark_lab}
    return cur != old


def make(hid):
    """返回 (act_policy, route)。每条命新建一个（里面记着这一场的状态）。"""
    import solver
    base, rules = parse(hid)
    st = dict(f=None, t0=0, turn=None, action=None, prev=None, mark=None)

    def act(f, know, kinds, belief=None, information=None):
        if st["f"] is not f:
            st.update(f=f, t0=f.turn, turn=None, action=None, prev=None, mark=f.layout.L("them", "mark"))
        if st["turn"] != f.turn:                           # 这一回合第一次决策：定动作
            slots, _atk = fh._screen(f)
            action, hit = base_action(base, f.turn - st["t0"]), None
            for trig, resp in rules:
                if fired(trig, slots, st["prev"], st["mark"]):
                    action, hit = resp, trig
                    break
            if act.trace is not None:
                act.trace.append((f.turn, dict(slots), hit, action))
            st.update(turn=f.turn, action=action, prev=dict(slots))
        for kind in fr.OPTIONS[st["action"]]:
            if f.played_kinds.get(kind):
                continue
            name = kinds[kind]
            if f.can_play(name):
                return name
        return None
    act.trace = None
    return act, solver.Route(heal_at=HEAL_AT)


if __name__ == "__main__":
    hs = habits()
    print(len(hs), "habits;", hs[:3], hs[-2:])
    for h in hs:
        parse(h)
