"""候选 v3b 的训练营（PROTO_CAMP=1；用户 11-05 晚，docs/antagonist_boss/18_candidate_v3_spec.md §8.6）。
用户：「一个世界一次吧，但回合数不能太多」→ 每个世界开头一次训练营（人和模型都是），然后进第 1–4 条命。只在候选 v3b 的完整环境 +
PROTO_TEXT=minimal 下实现（supported()）；别的环境下 PROTO_CAMP=1 照旧拒绝（antagonist_proto._validate、proto_play.play_life 原来的拒绝）。
core/ 一字不改：营地是一场真的 adventure.Fight（与地图同一套引擎、同一套原型补丁），只是对手没有机制。

营地（CampFight）：
  · 手牌 = 地图的固定手牌（antagonist_proto 装的 FixedPileCD）：每回合手里五种牌各一张；能量 2；增伤只对本回合的攻击 ×2、出过的下一回合
    不在手里（冷却一回合）；治疗与地图一样（回血封顶在上限，出过就从这一局的牌组里删掉 —— 营地自己的一份牌组，3 张）；闪 2 费。
  · 牌、名字、符号 = 这个世界第 1 张图的 Run（世界里 4 张图相同，核对 C1 查）：牌组是深拷贝（营地里付过的费用不带进地图），布局同一个对象（只读）。
  · 盾 = 地图上的盾（bp45w90 的缩放已在 camp.make_deck 里做过：Run 的牌就是缩放后的）。
  · 陪练没有机制（Enemy behaviour ""，parts = ("",)）：每个 END 打一下 sparring_hit，确定性：盾 + 2，碰到自己的攻击 / 治疗量就往上加 1
    （原营地 camp.sparring_hit_for 的「盾 + 1 或 2」去掉随机；三个数不相等同 camp.make_deck 的不变式）→ 大于盾，举盾时看得到「挡掉一部分」，
    与地图的不变式（怪的普通攻击 > 盾）一致。陪练的攻击槽在画面上一直是 ?（同地图上没有加成的怪）。
  · 血 = 地图开局的血（Run.max_hp），并且 > sparring_hit × TURNS（营地里血到不了 0：「什么都不算」）；陪练血 DUMMY_HP > 2 × 攻击 × TURNS
    （打不死它：END 一定结算）。
  · 不用随机数：Fight 的 rng 是 NoRNG（任何调用都报错）；固定手牌不洗牌，没有机制就没有抽签（核对 C7 另查全局 random 状态不变）。
  · RESET：回到起始状态（双方数值、手牌、牌组里的治疗、冷却、增伤）—— 新建一场同样的 Fight；已经看到变化的值（seen）和付过的费用照旧显示
    （同地图上一条命里的做法：看过的不再变回 ?）。**回合不退**：上限按整个营地数（RESET 之前打过的回合照算），否则 RESET 就能无限续回合。
  · LEAVE：离开营地。到了回合上限（第 TURNS 回合的 END 之后）或步数上限（STEPS）营地也结束，不另说一句话（同原营地）。
  · 画面 = 地图的画面（adventure.show），第一行换成 "Turn T    k turns left"（原营地 camp.show 的写法；T 是营地的总回合）。
  · 日志行与地图逐字同一种写法（"name  ->  a3: 203->195"、"end turn  ->  …"、"(not in hand)" / "(no effect)"、三次无效的 FORCED_END、
    "[unparseable]"）；RESET 记成 "RESET  ->  <变化>"（原营地是 "RESET -> everything reset"，minimal 下不加话，只列变化）；LEAVE 记 "LEAVE"。

文字（参与者看到的，人和模型逐字相同；常量在 proto_text：CAMP_SYSTEM / CAMP_HEADER / CAMP_LABEL / CAMP_HISTORY / CAMP_RECORD_HEAD）：
  · 系统提示（用户 11-05 晚定）：proto_text.CAMP_SYSTEM。营地期间 modelrun.CAMP_SYSTEM 临时换成它（modelrun._call_kind 按文字认种类 →
    "camp-act"），退出还原（同 proto_play.adv_system 的换法）。
  · 抬头：模型每一步的提示开头 "World w, Camp"（后面接上一个世界的信，若有）；人的横幅 "World w, Camp"。
  · 提示里营地记录的抬头 "This camp:"（地图上是 "This life:"）。
  · 营后笔记：与命末笔记同一句（LIFE_QUESTION，2000 token 上限，超长先缩一次、仍超就截断；proto_text.life_notes）；材料 "Record:" + 营地记录。
  · 之后每条命带着营地（照命的笔记带法）：notes / both 臂 "World w, Camp:" + 营后笔记（在各条命的笔记前面）；log / both 臂
    "Record of the camp:" + 营地记录（在各条命的记录前面）；第 1 条命的提示开头 "World w, Life 1"（有营地才有：要和营地分开）。
记录（模型记录的格式）：第 1 条命的记录有 camp_log / camp_used / camp_experiments / left_early / notes（营后笔记），外加 camp（本模块的版本、
上限、步数、RESET 次数、怎么结束的、数值、笔记的上限字段、复用与否）；第 2–4 条命照 modelrun 抄第 1 条命的这些键。营地打完、第 1 条命开打之前
先写一次第 1 条命的记录（camp.done）—— 中途退出再开，营地不重打（一个世界一次）；第 1 条命重打（--replay）也复用同一个营地。"""
import contextlib, copy, json

import modelrun
import humanrun
import antagonist_proto as ap
import proto_text as pt

VERSION = "proto-camp-v1-2026-11-05"
TURNS = 6            # 回合上限（lead 默认，用户「回合数不能太多」）。量过：会规划的试验者在固定手牌下 4–5 回合看全每张牌（camp_experimenter.py）
STEPS = 60           # 步数上限 = 10 步 / 回合：一回合最多 2 张出成（能量 2）+ 2 次无效（第 3 次强制结束）+ END = 5 步，再留一倍给 RESET 和试错。
                     # 原营地 240 步 / 10 回合是按抽牌手牌（5 张、要攒牌）和 gpt-5.5 的 62 步定的；固定手牌下每回合能做的事少得多。
DUMMY_HP = 300       # 同原营地 camp.Camp.dummy_hp
SPARRING_OVER = 2    # 陪练一击 = 盾 + 2（再避开自己的攻击 / 治疗量）
FAILS = modelrun.FAILS_PER_TURN


def supported():
    """营地只做了候选 v3b + PROTO_TEXT=minimal 的这一套（固定手牌、增伤冷却、v3b 池、最简文字）。"""
    return ap.HAND == "fixed" and ap.DOUBLER == "turncd" and ap.POOL == "v3b" and pt.minimal()


def enabled():
    return ap.camp() and supported()


# ---------------------------------------------------------------- 数值
def sparring_hit(shield, atk, heal):
    h = shield + SPARRING_OVER
    while h in (atk, heal, shield):
        h += 1
    return h


def numbers(run):
    kinds = {c.kind: c for c in run.deck.values()}
    shield, heal, atk = kinds["block"].amount, kinds["heal"].amount, run.base_atk
    hit = sparring_hit(shield, atk, heal)
    hp = run.max_hp
    if not (hit > shield and hp > hit * TURNS and DUMMY_HP > 2 * atk * TURNS):
        raise RuntimeError(f"camp numbers break the invariants: shield {shield}, hit {hit}, hp {hp}, attack {atk}, dummy {DUMMY_HP}")
    from adventure import TUNING
    return dict(shield=shield, sparring_hit=hit, hp=hp, dummy_hp=DUMMY_HP, attack=atk, heal=heal, energy=TUNING["energy"],
                block_pct=TUNING.get("block_pct"), turns=TURNS, steps=STEPS)


class NoRNG:
    """营地不许用随机数：任何调用都报错。"""

    def __getattr__(self, name):
        raise RuntimeError(f"the camp uses no randomness (rng.{name} was called)")


class CampFight:
    """一个营地：当前这一场 Fight、营地总回合 turn、RESET 次数。"""

    def __init__(self, run):
        import adventure
        self.num = numbers(run)
        self.deck = copy.deepcopy(run.deck)
        for c in self.deck.values():
            c.cost_known = False
        self.deck_list0 = list(run.deck_list)
        self.layout, self.base_atk = run.layout, run.base_atk
        self.turn, self.resets = 1, 0
        self._adv = adventure
        self.fight = self._new(set())

    def _new(self, seen):
        A = self._adv
        enemy = A.Enemy(name="", behaviour="", hp=DUMMY_HP, atk=self.num["sparring_hit"])
        f = A.Fight(self.deck, list(self.deck_list0), self.layout, enemy, hp=self.num["hp"], max_hp=self.num["hp"],
                    base_atk=self.base_atk, rng=NoRNG(), is_boss=False, seen=set(seen))
        if f.parts != ("",) or f.state[("them", "atk")] != self.num["sparring_hit"]:
            raise RuntimeError(f"camp sparring partner is not mechanism-free: parts {f.parts}")
        return f

    def reset(self):
        self.fight = self._new(self.fight.seen)
        self.resets += 1

    def end_turn(self):
        self.fight.end_turn()
        self.turn += 1


def screen(cf):
    """地图的画面，第一行是营地的总回合和剩几回合（原营地 camp.show 的写法）。"""
    head, _, rest = modelrun.fight_screen(cf.fight).partition("\n")
    left = TURNS - cf.turn + 1
    return f"Turn {cf.turn}    {left} turn{'' if left == 1 else 's'} left" + ("\n" + rest if rest else "")


def _changes(layout, before, after):
    from adventure import TUNING
    return [f"{layout.L(k[0], k[1])}: {before[k]}->{after[k]}" for k in after if before[k] != after[k] and k not in TUNING["hidden_props"]]


@contextlib.contextmanager
def system():
    """营地期间 modelrun.CAMP_SYSTEM = proto_text.CAMP_SYSTEM（调用种类 "camp-act"），提示里记录的抬头 = "This camp:"；退出还原。"""
    saved = modelrun.CAMP_SYSTEM
    if saved != _CAMP_SYSTEM_REGISTERED:
        raise RuntimeError("modelrun.CAMP_SYSTEM was already replaced (a nested camp?)")
    modelrun.CAMP_SYSTEM = pt.CAMP_SYSTEM
    try:
        with pt.history_head(pt.CAMP_HISTORY):
            yield pt.CAMP_SYSTEM
    finally:
        modelrun.CAMP_SYSTEM = saved


_CAMP_SYSTEM_REGISTERED = modelrun.CAMP_SYSTEM


def carry(w, letters):
    return "\n\n".join([pt.CAMP_HEADER.format(w=w)] + ([pt.letters_block(letters)] if letters else []))


def run_camp(model, key, run, w, letters=(), verbose=False):
    """营地的循环（modelrun._run_camp 的同一套：步数上限、每回合三次无效强制结束、experiments 统计），在 Fight 上跑。
    返回 (camp_log, camp_experiments, info)。"""
    cf = CampFight(run)
    log = modelrun.HarnessLog()
    stats = modelrun._empty_camp_experiments(cf.fight)
    allow = list(cf.deck) + ["END", "RESET", "LEAVE"]
    head = carry(w, letters)
    step = fails = 0
    ended = None
    with system() as sysprompt:
        while True:
            if cf.turn > TURNS:
                ended = "turns"
                break
            if step >= STEPS:
                ended = "steps"
                break
            step += 1
            f = cf.fight
            for name, st in stats["cards"].items():
                if f.can_play(name):
                    st["playable_steps"] += 1
            a = modelrun.act(model, key, sysprompt, f, lambda _o: screen(cf), log, allow, head)
            if a is None:
                log.append("[unparseable]")
                fails += 1
                if fails >= FAILS:
                    before = dict(cf.fight.state)
                    cf.end_turn(); fails = 0
                    ch = _changes(cf.layout, before, cf.fight.state)   # 2026-11-10：自动结算也写出变化（同地图）
                    log.append(f"{modelrun.FORCED_END}  ->  {', '.join(ch) if ch else '(nothing changed)'}")
                continue
            if a == "leave":
                log.append("LEAVE")
                ended = "leave"
                break
            before = dict(f.state)
            if a == "reset":
                cf.reset(); fails = 0
                tag, after = "RESET", cf.fight.state
            elif a == "end":
                cf.end_turn(); fails = 0
                tag, after = "end turn", cf.fight.state
            else:
                r = f.play(a)
                st = stats["cards"][a]
                st["attempts"] += 1
                if r is True:
                    st["successes"] += 1
                    if st["first_success_step"] is None:
                        st["first_success_step"] = step
                elif r == "absent":
                    st["absent"] += 1
                else:
                    st["insufficient_energy"] += 1
                if r is not True:
                    log.append(f"{a}  ->  " + ("(not in hand)" if r == "absent" else "(no effect)"))
                    fails += 1
                    if fails >= FAILS:
                        before = dict(cf.fight.state)
                        cf.end_turn(); fails = 0
                        ch = _changes(cf.layout, before, cf.fight.state)
                        log.append(f"{modelrun.FORCED_END}  ->  {', '.join(ch) if ch else '(nothing changed)'}")
                    continue
                tag, after = a, f.state
            ch = _changes(cf.layout, before, after)
            log.append(f"{tag}  ->  {', '.join(ch) if ch else '(nothing changed)'}")
            if verbose:
                print(f"  camp T{cf.turn} {log[-1]}", flush=True)
    stats = modelrun._finish_camp_experiments(stats)
    info = dict(version=VERSION, turns_cap=TURNS, steps_cap=STEPS, steps=step, turns_used=min(cf.turn, TURNS), resets=cf.resets,
                ended=ended, left_early=ended == "leave", numbers=cf.num, world_index=w, header=pt.CAMP_HEADER.format(w=w),
                system_sha=modelrun._sha(pt.CAMP_SYSTEM), done=True, reused=False)
    return log, stats, info


def notes(model, key, camp_log):
    """营后笔记：命末笔记同一句、同一上限与缩写 / 截断（proto_text.life_notes，种类 debrief）。"""
    import work_note
    return pt.life_notes(model, key, camp_log, [], work_note.block(work_note.versions_of(camp=True)) if work_note.on() else "")   # 工作便签（on 时）


def evidence(rec):
    """一条记录里的营地（给 proto_text 的交接 / 信）：{log, notes, w}；没有营地 → None。"""
    c = (rec or {}).get("camp")
    if not isinstance(c, dict) or not c.get("done"):
        return None
    return dict(log=list(rec.get("camp_log") or []), notes=rec.get("notes") or "", w=c.get("world_index"))


def reusable(prev, w):
    """第 1 条命已有的记录里打完的营地（同一个版本、同一个世界序号）→ 复用，不重打。"""
    c = (prev or {}).get("camp") if isinstance(prev, dict) else None
    return bool(isinstance(c, dict) and c.get("done") and c.get("version") == VERSION and c.get("world_index") == w)


def pending(model, seed, run_id, w):
    """人的入口：第 1 条命开打之前营地还要不要打（横幅用）。"""
    return enabled() and not reusable(modelrun._load(model, seed, 1, run_id=run_id), w)


def human_reset():
    """人的界面：营地结束、第 1 条命开始之前清掉 humanrun 的「已印」状态（同 proto_play.human_main 每条命开头的那三行）。"""
    humanrun._shown.clear(); humanrun._seen_hist[0] = 0; humanrun._fight[0] = None


def banner(text):
    print(f"\n{'#' * 58}\n{text}\n{'#' * 58}")


def describe():
    return dict(version=VERSION, turns=TURNS, steps=STEPS, dummy_hp=DUMMY_HP, sparring_over=SPARRING_OVER, system=pt.CAMP_SYSTEM,
                header=pt.CAMP_HEADER, label=pt.CAMP_LABEL, history=pt.CAMP_HISTORY, record_head=pt.CAMP_RECORD_HEAD,
                question=pt.LIFE_QUESTION)


if __name__ == "__main__":
    print(json.dumps(describe(), indent=1))
