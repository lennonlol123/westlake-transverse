"""固定手牌专用的条件习惯（2026-11-03 晚；在看到任何调参结果之前定下这一组）。
起因：固定手牌小原型验证（docs/antagonist_boss/09_fixed_hand_validation_results.md）发现，不学习的组合「开场先挡一下、之后全力输出、
看到某些状态亮起就闪」在 27/40 张图上复核通过率 ≥ 0.40。冻结清单是为抽牌版设计的，固定节奏又完全不看画面；GPT（11-03 晚）要求调机制时
「已找到的组合及其变体不能轻易通吃」。这里补一组固定手牌下自然会出现的、只读通用信号的条件习惯，作为调参筛选里更严的对手。

每套 = 底子（没触发时这一回合做什么）+ 0–2 条「触发 → 反应」（这一回合改做什么）+ 低血自动治疗（路线 heal_at = 40，同清单路线的常见值）。
回合动作用 fixed_rhythms 的代号（XA = 先增伤再攻击，AB = 攻击 + 盾，B = 只举盾，D = 闪，E = 什么都不做）；一回合的动作在这一回合第一次决策时定下，
之后按动作里的顺序出、出不了的跳过（同 fixed_rhythms.make_act）。
底子（BASES）：
  XA        每回合增伤 + 攻击（全力输出）
  AB        每回合攻击 + 盾
  oB.XA     每场第 1 回合只举盾，之后 XA（已发现的那一套的底子）
  oB.AB     每场第 1 回合只举盾，之后 AB
  XA|AB     XA、AB 轮换（每场从 XA 起）
触发（只读参与者看得到的：画面上怪方状态行印出的槽、怪攻击那一格印出的数（? 不算数）、自己的血）：
  slot      除标记以外任何状态槽印着非零（同清单 except:mark；标记槽一抽出代号就一直亮，算进去会一直触发）
  anyslot   任何状态槽印着非零（含标记）
  atkup     怪的攻击印出来的数，比这一场之前印出过的最小数大；或这一场先印 `?`、现在第一次印出数（攻击格第一次变化，在这个池里只会是涨：
            动量、怒气）
  hurt      自己的血低于上限的一半
反应：D（闪）、B（只举盾）、AB（攻击 + 盾）、E（这一回合什么都不做）。
单规则：5 底子 × 4 触发 × 4 反应 = 80 套；无规则：5 套（就是底子本身）；双规则（先查第一条）：
  slot→D + atkup→AB、slot→D + atkup→B、slot→B + atkup→AB、anyslot→D + atkup→AB，各配 5 个底子 = 20 套。共 105 套。
接口：habits() → [id]；make(id) → (act_policy, route)；parse(id)。id 形如 "oB.XA|slot>D|atkup>AB"。
读画面要开人的 `?` 追踪：调用方用 antagonist_proto.screen("habit", record) 包记录器（solver.play_fight 默认关掉追踪）。"""
import itertools
import fixed_rhythms as fr

BASES = ("XA", "AB", "oB.XA", "oB.AB", "XA|AB")
TRIGGERS = ("slot", "anyslot", "atkup", "hurt")
RESPONSES = ("D", "B", "AB", "E")
PAIRS = (("slot", "D", "atkup", "AB"), ("slot", "D", "atkup", "B"), ("slot", "B", "atkup", "AB"), ("anyslot", "D", "atkup", "AB"))
HEAL_AT = 40


def habits():
    out = list(BASES)
    out += [f"{b}|{t}>{r}" for b in BASES for t in TRIGGERS for r in RESPONSES]
    out += [f"{b}|{t1}>{r1}|{t2}>{r2}" for b in BASES for (t1, r1, t2, r2) in PAIRS]
    return out


def parse(hid):
    parts = hid.split("|")
    if parts[0] == "XA" and len(parts) > 1 and parts[1] == "AB":   # "XA|AB" 底子本身含一个 |
        base, rest = "XA|AB", parts[2:]
    else:
        base, rest = parts[0], parts[1:]
    rules = [tuple(r.split(">")) for r in rest]
    assert base in BASES and all(t in TRIGGERS and a in RESPONSES for t, a in rules), hid
    return base, rules


def _screen(f):
    """画面上怪方：状态槽 {符号: 值}（只认印出的整数）与攻击那一格印的东西（整数或 None = `?` / 没印）。只读 adventure.show 的文字。"""
    import adventure, cautious
    slots = cautious.them_slots(f)
    lab = f.layout.L("them", "atk")
    atk = None
    for line in adventure.show(f).split("\n"):
        if line.startswith("Them:"):
            for tok in line.split():
                k, _, v = tok.partition("=")
                if k == lab and v.lstrip("-").isdigit():
                    atk = int(v)
    return slots, atk


def make(hid):
    """返回 (act_policy, route)。每条命新建一个（里面记着这一场的状态）。"""
    import solver
    base, rules = parse(hid)
    mark_lab = None
    st = dict(f=None, t0=0, turn=None, action=None, low=None, was_q=False)

    def base_action(k):                                    # k = 这一场的第几回合（0 起）
        if base == "XA":
            return "XA"
        if base == "AB":
            return "AB"
        if base == "oB.XA":
            return "B" if k == 0 else "XA"
        if base == "oB.AB":
            return "B" if k == 0 else "AB"
        return "XA" if k % 2 == 0 else "AB"

    def fired(trig, f, slots, atk):
        nonlocal mark_lab
        if trig in ("slot", "anyslot"):
            if mark_lab is None:
                mark_lab = f.layout.L("them", "mark")
            return any(v > 0 for k, v in slots.items() if trig == "anyslot" or k != mark_lab)
        if trig == "atkup":
            if atk is None:
                return False
            return (st["low"] is not None and atk > st["low"]) or (st["low"] is None and st["was_q"])
        s = f.state
        return s[("me", "hp")] * 2 < f.max_hp                  # hurt

    def act(f, know, kinds, belief=None, information=None):
        if st["f"] is not f:
            st.update(f=f, t0=f.turn, turn=None, action=None, low=None, was_q=False)
        if st["turn"] != f.turn:                               # 这一回合第一次决策：定动作
            slots, atk = _screen(f)
            action = base_action(f.turn - st["t0"])
            for trig, resp in rules:
                if fired(trig, f, slots, atk):
                    action = resp
                    break
            if atk is None:
                st["was_q"] = True
            else:
                st["low"] = atk if st["low"] is None else min(st["low"], atk)
            st.update(turn=f.turn, action=action)
        for kind in fr.OPTIONS[st["action"]]:
            if f.played_kinds.get(kind):
                continue
            name = kinds[kind]
            if f.can_play(name):
                return name
        return None
    return act, solver.Route(heal_at=HEAL_AT)


if __name__ == "__main__":
    hs = habits()
    print(len(hs), "habits;", hs[:3], hs[-2:])
    for h in hs:
        parse(h)
