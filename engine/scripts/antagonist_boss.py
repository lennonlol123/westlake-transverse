"""拮抗池原型的 boss 层（2026-11-02，用户 + GPT 读完三份草案后的决定 D1–D8）。不改 core/，不改 results/ 里任何已有文件，不花 API。
只有显式调用 setup_boss() 才生效；没调它的脚本（含复现旧结果的）走的仍是旧行为：旧文字、旧 _settle_phase、两场先后的 boss。
同一进程里调过 setup_boss() 之后要回到旧行为，先调 teardown_boss()（光调 antagonist_proto.setup() 不够：activate_registered 不重设
boss_switch* 键，补丁和提示文字也留着）。

公开接口（别的脚本靠这些名字）：
  CUE_TEXT                      换阶段提示文字，正好是 "The enemy has changed."
  setup_boss(no_probe=0, punish_pct=None, grace=0, switch_frac=None, switch_hp_pct=None, fix_slots=True)
                                antagonist_proto.setup() → boss 旋钮（boss_switch=1、boss_switch_hint=1、boss_no_probe；其余 None = 原型（登记 12）的值，
                                不沿用上一次 setup_boss 的值：先撤掉自己的 after-setup 钩子再 ap.setup()）
                                → 装提示文字覆盖（cue_sites()）→ 装 D1 槽位补丁（fix_slots=False = 旧 _settle_phase，存档对照用）。幂等。
  build_boss(salt, pair, reverse)   单独的 boss（路 A + P1，见下），返回 ctx（dict）。
  play_boss(ctx, who, t, stream, item=None, record=None, oracle_veto=None, deal="trial")   一条 boss 命（D2 入场），返回逐回合记录。
  play_map(run, salt, who, t, stream, item=None, record=None, oracle_veto=None, boss_entry=None, deal="trial")   一条地图命（脚本参照）。
      deal="trial"（默认，同 2026-11-03 之前）：洗牌种子从 solver._trial_rng(SEED ^ salt, stream, t) 抽，每条命一副新牌；
      deal="structural"：打这张图 / 这个 boss 的结构洗牌 run.shuffles —— 参与者入口（proto_play）打的就是这一副，同一世界的每个参与者、
      每个记忆臂都一样。尺子默认对随机发牌取平均，参与者的世界是固定的一副牌：世界级的「模型对尺子」比较要么用 structural 让尺子打同一副，
      要么如实写明混着那一副牌的运气（审查 2026-11-03）。结果记 deal。
  ORACLE_VETO / oracle_veto_on(flag)   全知的 N5 否决开关（见下「版本」；判定在 antagonist_proto.oracle_veto_on）。
  boss_settings()               setup_boss 定下的 boss 键（BOSS_KEYS → 值）；没调 setup_boss 时 None。play_boss / proto_play 按它核对。
  cue_sites()                   提示文字的每一处读取点及当前状态。
  teardown_boss()               撤掉 setup_boss 的全部效果（方法、提示文字、boss 键），幂等。
  fight_info(f)                 这一场 boss 的 D1 记录（核对用）；mark_restarts()：进场标记的加权是否从换阶段起重新计数（r1v2 的视图读它）。
  完全撤掉原型：teardown_boss() 之后再 antagonist_proto.teardown()（teardown_boss 只撤 boss 层，原型版本的补丁留着，C9 靠这一点）。

版本（2026-11-03，antagonist_proto.PROTO_VERSION）：setup_boss() 经 ap.setup() 装上原型的现行版本（删奖励、固定节点、统一画面，开关见 antagonist_proto）。
  · 画面不再按玩家各给一套：play_boss 用 ap.display_settings(who)（统一模式下人人相同：marks=0、state_slots=PROTO_DISPLAY，默认 seen）；
    读画面的玩家（R1、R1v2、习惯）按 ap.tracks_screen(who) 打开 `?` 追踪，与人看到的画面一样（seen 下这不改变它们读到的任何值）。
    存档复现：PROTO_DISPLAY=per-player = 旧的各人各画面（R1 / R1v2 / 全知 R1_DISPLAY，习惯 seen + 追踪，盲线不设）。
  · 每条 boss 命的结果、build_boss 的 ctx 都记 proto（版本与开关）和实际用的画面键 display；ctx 建好之后开关变了 play_boss 报错。
  · boss 用自己新建的 Run、在 run.trial 里满血起始牌组入场，从不打图：拿牌 / 节点开关对 boss 命没有作用（仍照记）。
  · N5（变更集 c，2026-11-03）：R1v2 按 r1v2.R1v2Policy 的默认（r1v2.ENERGY_VETO，c 版）；全知在 _policy 的 oracle 分支接上
    r1v2.oracle_heal_veto（路线的自动治疗要是付了就会让全知本回合的第一张牌付不起，这一刻不治疗；诊断参照的改动，不属于 R1v2）。
    开关：play_boss / play_map 的 oracle_veto（None = 模块的 ORACLE_VETO；它也是 None 时跟 r1v2.ENERGY_VETO，即同一个 c 开关）。
    关着时传 antagonist_proto.no_heal_veto（不是 None）：PROTO_REFS=c 下 ap.setup() 给 solver.play_fight 装了包装，所有直接调 run_once 的
    全知（antagonist_preboss*、antagonist_diag）也接同一条否决；传 None 会被它接上默认否决。
    存档复现（2026-11-03 之前的全知 / R1v2 数字）：光设 r1v2.ENERGY_VETO = False **不够**（地图命在新默认下是固定节点、统一画面）——
    要 PROTO_LOOT=1 PROTO_NODES=route PROTO_DISPLAY=per-player PROTO_REFS=b，或同一进程里 with antagonist_proto.archived()（含参照 b）。
    boss 命不打图，拿牌 / 节点开关对它没有作用；boss_check.json 的 C10 R1v2 / 全知计数在 b 参照下能否逐个复现**没有核实**（C10 是 boss 配对扫描，
    按硬规则不重跑）。
    每条命的结果记 ref：R1v2 → version / energy_veto / vetoes；全知 → heal_veto（用没用 c 的否决）/ vetoes；其余 None。
  · play_map(run, salt, who, t, stream, …)：同一套 _policy 的地图命（现行版本：固定节点、无奖励、统一画面；到图末为止）。
  · boss 规则只由 setup_boss 定：它把 boss 键登记成 antagonist_proto 的 after-setup 钩子，之后任何 ap.setup()（proto_world.verify、
    two_round_salts、archived() …）里 activate_registered(12) 改回的登记值（boss_no_probe=1 等）都会被写回。2026-11-03 审查前没有这一步：
    参与者入口 play_life 先 verify 再建 boss，于是模型 / 人的 boss 命在 boss_no_probe=1 下打，脚本参照在 0 下打。play_boss 的结果记 tuning。

路线选择（草案 1 §9）：路 A（独立 boss 驱动，不打 4 张图）+ P1（建 boss 用的 Run 时把 boss_pool_exclude 设成「池里除这一对以外的全部」）。
  · D2：boss 是独立开考，前面死过也能考。路 B / B′ 只有活到门口的命才到 boss_entry 钩子（core/solver.py:1440-1449），是幸存者筛选，所以不用。
  · 穿透只对显式指定的配对放开：排除表只在 build_boss 里临时改、马上还原（finally）；地图 Run（ap.build）从不经过这里。
  · 阶段顺序：先用 boss_switch_reverse=0 建；若抽签顺序（run.boss_stages）≠ 要的阶段顺序，用 reverse=1 再建一次。_roll 对同一 salt 与同一
    TUNING 是确定的，两次建出的抽签完全相同，只差合并先后（core/adventure.py:3271-3272）。记录用实际阶段顺序 e.parts_for(False/True)，
    不用 run.boss_stages（reverse 下它是抽签顺序，core/adventure.py:3202）。
  · 引擎行为，不改：合并后的身体沿用**第一阶段**那个敌人的名字、攻击、charge_max（core/adventure.py:3271-3278），所以同一对的两种顺序
    血量相同，攻击数值不同。洗牌流：同一 (salt, stream, t) 下两种顺序的开局手牌、抽牌堆逐张相同**只在 fix_slots=True 时成立**——引擎在第一阶段
    含守势时先 rng.randrange(2) 抽起始相位再建牌堆（core/adventure.py:1433-1438 对 :1474），会挪动整条牌流；补丁让这一抽也走派生流（见下）。
    fix_slots=False（存档）下含守势的 5 个无序配对两种顺序不配对。
随机数安全：
  · boss 用自己的 Run（salt 由调用方给，建议每个世界一个专门的 boss salt）；它的随机流（Random(salt)、pool-v1、mark-v1、midterm-v1）全是
    本 Run 自己的 Random 对象，不碰任何地图 Run 的流，也不碰全局 random。P1 的排除会改变这个 salt 抽到的机制、层结构与之后全部数值
    （草案 1 §9.4），所以这个 Run 只能当 boss 用，绝不能拿去打图。
  · setup_boss 打开 boss_switch=1 后，地图 Run 的抽签不变（合并用同两次抽签，shuffles 个数不变，core/adventure.py:3259-3266、3290-3291）；
    _selfcheck() 逐层核对这一点。
  · 每条命：rng = solver._trial_rng(SEED ^ salt, stream, t)，与 run_once 同样先分好全部洗牌种子（core/solver.py:1355），boss 用 shuffles[-1]。
    同一 (salt, stream, t) 对所有被测打法、两种顺序都一样（共同随机数，只保证开局相同；第一次走法不同之后手牌和标记抽签就分开）。
  · 守势起始相位（第一阶段的和进场的是同一个值）不从 Fight.rng 抽，而在 Fight 构造时对 rng 的**初始状态**做哈希、从派生流
    Random(blake2b("boss-guard-start-v1:…")) 抽一次（_guard_start）。初始状态只由 boss 洗牌种子决定，所以不论从哪个入口建这场 boss
    （play_boss、solver.run_once、r1v2.run_life），起点对所有打法都相同，也不随打法自己造成的洗牌 / 标记抽签而变；Fight 上不挂任何种子属性。

D1 补丁（只作用于 setup_boss(fix_slots=True) 下构造的换阶段 boss；包住 Fight 的 __post_init__ / _settle_phase / _slots_moved / end_turn，
原函数先照常跑；逐场记录放在模块的 _FIGHTS 里，不挂在 Fight 上）：
  · 离场机制的状态槽（ENEMY_STATE_SLOTS 里不在新 parts 的）清零；离场破势的开启倒数清零。清零是公开变化（画面 / 日志印成 0），与提示同时出现。
  · 进场机制按 Fight 构造时的规则初始化（core/adventure.py:1432-1441、1479-1492）：守势相位 = 构造时派生的起点，非零记入 seen；
    破势封印 = enemy.ward_start or 1，记入 seen；标记代号 = 0（构造时也是 0，第一回合无标记）；蓄力 = min(boss_charge_start, charge_max-1)
    （与构造时 boss 的规则相同；引擎原写法直接写 boss_charge_start，原型现值下两者都是 1）。
  · 进场标记的加权：引擎按这一场累计出牌 fight_kinds 加权抽代号（core/adventure.py:2173-2183），boss 开场时它是 {}（:1431）。换阶段时记下
    基线，之后每次 end_turn 抽签期间把 fight_kinds 临时换成「换阶段之后的出牌」，抽完放回原对象（cautious / r1v2 按它的增量算本回合出牌）。
    这改了参与者规则书 RULES.md:337 的「so far in this fight」：换阶段 boss 的进场标记要写成「since the enemy changed」（规则书不在本文件，未改）。
    R1 v1 的后验按累计数算（core/cautious.py:155-160），对进场标记是错设的；v1 不改，r1v2 的视图按 mark_restarts() 从提示起计数。
  · 画面对等：构造时的起始值不进 slots_changed（state_slots="seen" 下不印，直到第一次变化），所以进场初始化引起的那一下变化也从
    slots_changed 里拿掉（包住 _slots_moved）。离场的清零照常进 slots_changed。
  · 日志对等：modelrun 的日志按 state 原始差列出每个变了的槽，印不印都列（core/modelrun.py:1206-1207，RULES.md:74），构造时的起始值从不进日志。
    所以进场初始化（含引擎原写法本来就有的进场蓄力 0->1）也不进换阶段那一行：_quiet_model_log 把 modelrun.run_fight 那一帧的 before 里的
    进场槽改成起始值。之后的真变化（W: 1->2、G: 1->0）照常列出，与开场的 boss 一样。离场清零照常列出。命令行人类入口打印的是同一份日志；
    重放核对器（audit/replay.py 等）若自己重算差，要做同样的静音（未核实，模型 / 人类 boss 入口还没写）。
  · 破势上限：引擎只在第一阶段含破势时给 boss 设 ward_boss_cap（core/adventure.py:3285-3288）；fix_slots 开时 build_boss 对进场破势也设
    ward_cap=ward_boss_cap、ward_start=ward_boss_start；进场蓄力同理补 charge_max_boss（原型现值 0 = 用 charge_max，等于没改）。
  · 不动：停顿怒气 stalls（通用规则，不是机制槽）。它跨阶段带过去，抬高第二阶段印出的攻击（core/adventure.py:1676-1677、2200-2202），
    是已知混淆：顺序比较、进场动量的「攻击涨了」都混着它。不在换阶段补发牌（boss_opens_with_dodge 只在开场，保底发牌待用户定）。

C10 v2 的两个候选开关（antagonist_proto 读环境变量；默认 = 上面的现行行为，默认下新代码一个状态也不碰；docs/antagonist_boss/12_c10_v2_design.md）：
  · PROTO_INCOMING=real（§5）：_settle_phase 包装在 orig_settle 之前记下各槽值；换阶段后进场槽的值与之不同就是真实变化 —— 不调 _quiet_model_log、
    info["quiet"] 为空（引擎自己的 _slots_moved 把它加进 slots_changed，modelrun 那一行 END 差照常列出）；handover 记录另加 incoming_mode /
    incoming_changes。起点 0（守势派生起点 0、标记）什么也不做。mute（默认）= 上面 D1 的静音，handover 字典一个键都不加。
  · PROTO_THREAT=momentum（§6）：end_turn 包装在原函数体（_d1_end_turn）之后调 _threat_refresh：boss 纯动量阶段把攻击槽换成
    Fight._incoming()[0]（下一次 END 那一击，挡 / 闪之前；到顶且不在宽限时 = max(攻击, 上限 × momentum_boss_frac%)）。纯函数、
    不抽随机数、伤害不读攻击槽；写过时 fight_info(f)["threat"] 记 (turn, shown_atk, 印出值)。蓄力大招、地图穿透记仇不在内（D9）。
  · PROTO_MARKMAP=world（§7）：play_map / play_boss 入口先 ap.require_mark_table(run)；结果多 mark（ap.mark_record）。默认下不加键。
  play_map / play_boss 结果的 proto 字典多 incoming / threat / markmap 三个短键（信息性）。_selfcheck 在三个开关非默认时拒绝。
11-03 夜的两个候选开关（antagonist_proto；默认 0 / none = 现行，下面的改动在默认下什么也不做）：
  · PROTO_LADDER=1（惩罚阶梯 scripts/penalty_ladder.py）：阶梯必须在本文件 _patch_slots 换的 Fight.end_turn 之外（penalty_ladder 的次序）。
    setup_boss 的整段包在 ap.ladder_outside("switch") 里（进块撤掉 ap 装的阶梯、块里的 ap.setup() 不装、出块装上），teardown_boss 的整段包在
    ap.ladder_outside("if-lifted") 里（撤掉、换回原方法、装回；ap.teardown() 先撤过就不装回）。
  · PROTO_TUNE=m59ws2：只经 ap.setup() 写 TUNING；build_boss 用同一个 TUNING 建 boss（boss 的数受不受影响见 scripts/candidate_check.py 的记录）。
  play_map / play_boss 结果的 proto 字典另多 ladder / tune 两个短键（信息性；ctx["proto"] = ap.switches() 本来就带，建 boss 之后换开关照旧报错）。
D3（宽限期）：这里只把 grace 原样写进 TUNING（默认 0），不选值。boss_switch_grace 只压住动量 / 激怒的 boss 一击（core/adventure.py:1934-1945），
  且 grace=g 只护 g−1 次结算（草案 1 §7.2，静态读码，未核实）。「每个进场机制第一次吃到关键后果不致死」要逐机制核对，本文件不保证，
  no_probe=0 也不保证手里有需要的牌。
提示文字的读取点（cue_sites()）：adventure.BOSS_SHIFT_TEXT（core/adventure.py:119；audit/replay.py:181-182 按属性读，随之生效）；
  modelrun 按值导入（core/modelrun.py:43，渲染 :1217-1224；命令行人类入口 core/humanrun.py 打印的就是这份日志）；
  audit/parse_log.py:14（自带常量，:137 按整行相等识别）；scripts/audit_checks 下三个重放核对器按值导入（已载入才改，不主动导入）。
  图形界面 core/humangui.py 不自己渲染提示：它在子进程里跑 gui_bridge.run_worker → humanrun（core/humangui.py:216、436-437），
  文字来自 modelrun 日志；本进程的覆盖到不了那个子进程，人类 boss 入口要在 worker 里调 setup_boss()。没加任何界面代码。
boss 第一版（11-06，PROTO_BOSS=v1，docs/antagonist_boss/32_boss_v1.md；默认 none 下一个字节也不变）：
  · 守势开场（第一阶段的守势、进场的守势同一个值）不再对 rng 初态做哈希，而是读 boss 敌人建图时预抽的 _guard_start（guard_slot.tag_starts，
    按 boss salt：Random("guard-start-v1:{identity_key}:boss:{boss salt}")）；没记就 BossGuardStartMissing。于是 boss 对局里不抽任何随机数
    （固定手牌不洗牌、池里没有标记），同一个 boss 的每条命（任何 t、任何发牌）逐回合相同 —— 筛选的绊线 / 核对命照地图的办法核对。
  · 守势编码按 boss salt（guard_slot.tag_run 原来就按 Run 的 salt 给 boss 敌人记 boss 那一张映射；boss 的 Run 用 boss salt 建）。
  · 换阶段：引擎原样（一个身体一条血，switch_at = floor(boss 血 × boss_switch_frac / 100)，现值 50；攻击把 boss 血打到 <= switch_at 时只「上膛」，
    这一回合的 END 结算完才换；一下越过线很多也不截血、不拆成两下，多出来的伤害照算；同一回合把 boss 打死就没有第二阶段）；提示 "The enemy has changed."；
    D1 槽位交接照上。价钱在 penalty_ladder 表 v3c1b（换阶段第一下按机制）。
  · build_boss 的 ctx、play_boss 的结果多一个 boss_v1 键（版本、守势开场与来源、守势编码、换阶段的两个旋钮）。
boss 第二版的两个旋钮（11-06，docs/antagonist_boss/33_boss_v2_hp.md；只配 PROTO_BOSS=v1，默认 100 / none 下一个字节也不变）：
  · PROTO_BOSS_HP=150/200/250：setup_boss 把 TUNING boss_switch_hp_pct 写成这个数（没显式传 switch_hp_pct 时；显式传了且不同就报错）——引擎原式
    boss 总血 = round(两段抽出的血之和 x pct / 100)，换阶段线 = floor(总血 x 50 / 100)，都在抽数之后（随机流不动）。
  · PROTO_BOSS_TURNCAP=60：build_boss 给 boss 敌人记 _turn_cap = 60（antagonist_proto.turn_cap_of / Fight.over 补丁 / ended_by / solver.play_fight 的 cap 读它）。
  · build_boss 的 ctx、play_boss 的结果多一个 boss_v2 键（只在两个旋钮有一个不是默认时）。
boss 第四版（11-06，docs/antagonist_boss/35_boss_v4_irregular.md；只配 PROTO_BOSS=v1，默认 none / none / on / v1 下一个字节也不变）：
  · PROTO_GUARDSEQ=irr50/irr67、PROTO_CHARGESEQ=irr25/irr50：build_boss 给 boss 敌人记预抽的表 _guard_seq / _charge_seq（guard_schedule /
    charge_schedule，按 boss salt 的独立流，对局里不抽数）；_settle_phase 补丁的第一步 _seq_apply（引擎这一 END 的翻 / 涨已经做完、换阶段还没做）：
    这一 END 由守势管、表说不翻 → 把引擎的翻还原；由蓄力管、这一 END 涨了（开头 0 / 1）、表说停 → 还原。还原时照引擎会记的那样记 slots_changed / seen
    （画面照旧：守势第 2 回合起每回合印）。
  · PROTO_BOSS_CUE=off：setup_boss 写 boss_switch_hint = 0（引擎不发 boss_shift 事件，日志没有提示那一行）。
  · PROTO_BOSS_HANDOVER=x1：setup_boss 把 penalty_ladder.HANDOVER_STEPS_V3C1B 换成「每种机制 x1 不致死」（teardown_boss 还原）。
  · build_boss 的 ctx、play_boss 的结果多一个 boss_v4 键（只在这四个开关有一个不是默认时）。
用法（只做确定性核对和几条命的冒烟，不跑面板）：python3 -B scripts/antagonist_boss.py check"""
import hashlib, pathlib, random, sys, weakref

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))                    # audit.parse_log 是包内模块
import antagonist_proto as ap

CUE_TEXT = "The enemy has changed."
WHO = ("R1", "R1v2", "oracle", "habit", "blind")
BOSS_KEYS = ("boss_switch", "boss_switch_hint", "boss_no_probe", "boss_punish_pct", "boss_switch_grace",
             "boss_switch_frac", "boss_switch_hp_pct", "boss_switch_keeps_bonus")
_STATE = dict(setup=False, slot_fix=False, keys=None)
_ORIG = {}                                         # teardown_boss 要还原的：Fight 原方法、提示原文字、boss 键原值
ORACLE_VETO = None                                 # 全知的 N5 否决：None = 跟 r1v2.ENERGY_VETO（变更集 c 的同一个开关）；True / False 强制
_REPLAY_MODS = ("replay_check", "appendix_replay", "referee_replay")


# ---------------------------------------------------------------- 设置
def setup_boss(no_probe=0, punish_pct=None, grace=0, switch_frac=None, switch_hp_pct=None, fix_slots=True):
    ap.unregister_after_setup("antagonist_boss")   # 这一次的 ap.setup() 不写回上一次的 boss 键：None 的键取原型自己的值
    if ap.BOSS_HP != "100":                        # boss 第二版（PROTO_BOSS_HP，33 号文档）：血量倍数 = 引擎的 boss_switch_hp_pct；默认 100 下这一段什么也不做
        if switch_hp_pct is not None and int(switch_hp_pct) != int(ap.BOSS_HP):
            raise ValueError(f"PROTO_BOSS_HP={ap.BOSS_HP} but setup_boss(switch_hp_pct={switch_hp_pct})")
        switch_hp_pct = int(ap.BOSS_HP)
    # PROTO_LADDER=1（候选，11-03 夜）：阶梯要在下面 _patch_slots 换的 Fight.end_turn 之外 —— 进块撤掉、块里的 ap.setup() 不装、出块装上。
    # 默认（0）下 ladder_outside 什么也不做。
    with ap.ladder_outside("switch"):
        ap.setup()                                # activate_registered(12) 不重设 boss_switch* 键（core/devworld.py:700-708），所以这里每次都重写全部 boss 键
        from adventure import TUNING
        _ORIG.setdefault("tuning", {k: TUNING[k] for k in BOSS_KEYS})   # 第一次：原型自己的值（boss_switch=0 …），teardown_boss 还原到这里
        TUNING.update(boss_switch=1, boss_switch_hint=0 if ap.BOSS_CUE == "off" else 1, boss_no_probe=int(no_probe), boss_switch_grace=int(grace))
        if ap.BOSS_HANDOVER in ("x1", "x1m2"):     # boss 第四版（35 号文档）：换阶段第一罚一律 x1 不致死；第五版 x1m2：动量 x2 不致死；默认 v1 下什么也不做
            import penalty_ladder as pl
            _ORIG.setdefault("handover_steps", dict(pl.HANDOVER_STEPS_V3C1B))
            pl.HANDOVER_STEPS_V3C1B = {m: pl.Step(1, True, False) for m in ("charge", "momentum", "counter", "guard", "ward", "pierce", "mark")}
            if ap.BOSS_HANDOVER == "x1m2":
                pl.HANDOVER_STEPS_V3C1B["momentum"] = pl.Step(2, True, False)
        for k, v in (("boss_punish_pct", punish_pct), ("boss_switch_frac", switch_frac), ("boss_switch_hp_pct", switch_hp_pct)):
            if v is not None:
                TUNING[k] = int(v)
        _patch_cue()
        _patch_slots()
        _STATE.update(setup=True, slot_fix=bool(fix_slots), keys={k: TUNING[k] for k in BOSS_KEYS})
        ap.register_after_setup("antagonist_boss", _reapply_keys)   # ap.setup() 之后写回（activate_registered 把 boss_no_probe 改回 1）
    if ap.BOSS_STRIKE in ("probe1", "probe1w"):    # boss 第六版（37 号文档）：阶梯装回之后换 boss 的四行；默认 none 下什么也不做
        _install_strike()                          # probe1w（43 号文档 §14）：另加破势那一行
    return dict(_STATE["keys"])


STRIKE_PROBE = dict(charge=1, guard=1, momentum=2, counter=1)   # 第一次犯的倍数（不致死）；第二次起：死
STRIKE_PROBE_WARD = 1                                            # 43 号文档 §14：PROTO_BOSS_STRIKE=probe1w 的破势行（x1 不致死、死、死）


def _install_strike():
    """boss 第六版：penalty_ladder 的现用表里 boss 的四行换成 (试探 不致死, 死, 死)；表写回 TABLES[表名]（之后重装阶梯也拿到它）。
    换阶段格不动（PROTO_BOSS_HANDOVER 决定；x1m2：动量 x2、其他 x1，都不致死）。teardown_boss 还原。"""
    import penalty_ladder as pl
    name = pl.TABLE_NAME
    _ORIG.setdefault("strike_table", (name, pl.TABLES[name]))
    t = dict(_ORIG["strike_table"][1])
    for m, x in STRIKE_PROBE.items():
        t[f"{m}/boss"] = (pl.Step(x, True, False), pl.DEATH, pl.DEATH)
    import antagonist_proto as ap
    if ap.BOSS_STRIKE == "probe1w":                # 43 号文档 §14（修订 4）：破势也「一次试探、两次死」（只在 boss 上）
        t["ward/boss"] = (pl.Step(STRIKE_PROBE_WARD, True, False), pl.DEATH, pl.DEATH)
        _ORIG.setdefault("ward_strike", pl.WARD_STRIKE)
        pl.WARD_STRIKE = True
    pl.TABLES[name] = t
    if pl._STATE["installed"]:
        pl._STATE["table"] = pl._check_table(t)


def _reapply_keys():
    if _STATE["setup"] and _STATE.get("keys"):
        from adventure import TUNING
        TUNING.update(_STATE["keys"])


def boss_settings():
    """setup_boss 定下的 boss 键（没调就是 None）。"""
    return dict(_STATE["keys"]) if _STATE["setup"] and _STATE.get("keys") else None


def _core_module(mod):
    p = pathlib.Path(mod.__file__).resolve()
    # 已发出 / 冻结的整包副本（results/agii_human_test_v13、agii_full_project）绝不能被打补丁
    assert p.parent == ROOT / "core", f"{mod.__name__} 不是从 core/ 导入的：{p}"
    return mod


def _patch_cue():
    import adventure, modelrun
    import audit.parse_log as pl
    assert pathlib.Path(pl.__file__).resolve().parent == ROOT / "audit", pl.__file__
    mods = [_core_module(adventure), _core_module(modelrun), pl]
    mods += [m for m in (sys.modules.get(n) for n in _REPLAY_MODS) if m is not None and hasattr(m, "BOSS_SHIFT_TEXT")]   # 只改已经载入的
    cue = _ORIG.setdefault("cue", {})
    for m in mods:
        cue.setdefault((m, "BOSS_SHIFT_TEXT"), m.BOSS_SHIFT_TEXT)
        m.BOSS_SHIFT_TEXT = CUE_TEXT
    bad = [s["site"] for s in cue_sites() if s["patched"] is False]
    assert not bad, bad


def cue_sites():
    """每一处提示文字：site / how / patched（True、False，或 None = 本进程没载入或够不到）。"""
    out = []
    m = sys.modules.get("adventure")
    out.append(dict(site="core/adventure.py:119 BOSS_SHIFT_TEXT", how="常量；audit/replay.py:181-182 按属性读，随之生效",
                    patched=None if m is None else m.BOSS_SHIFT_TEXT == CUE_TEXT))
    m = sys.modules.get("modelrun")
    out.append(dict(site="core/modelrun.py:43 (rendered :1217-1224)", how="按值导入；模型日志，命令行人类入口 core/humanrun.py 打印同一份日志",
                    patched=None if m is None else m.BOSS_SHIFT_TEXT == CUE_TEXT))
    m = sys.modules.get("audit.parse_log")
    out.append(dict(site="audit/parse_log.py:14 (matched :137)", how="自带常量，整行相等",
                    patched=None if m is None else m.BOSS_SHIFT_TEXT == CUE_TEXT))
    for name, site in zip(_REPLAY_MODS, ("scripts/audit_checks/replay_check.py:20", "scripts/audit_checks/appendix_replay.py:4",
                                         "scripts/audit_checks/recon/referee_replay.py:8")):
        m = sys.modules.get(name)
        out.append(dict(site=site, how="按值导入的重放核对器；已载入才改", patched=None if m is None else m.BOSS_SHIFT_TEXT == CUE_TEXT))
    out.append(dict(site="core/humangui.py (gui_bridge.run_worker 子进程)", how="不自己渲染，转发 humanrun 的终端文字；本进程覆盖够不到子进程，"
                    "人类 boss 入口要在 worker 里调 setup_boss()", patched=None))
    return out


_FIGHTS = {}                                      # id(Fight) → (weakref, info)：D1 的逐场记录。不挂在 Fight 上，免得多一个决策层读得到的隐藏属性


def fight_info(f):
    """这一场 boss 的 D1 记录（守势派生起点、标记基线、静音的日志键、标记抽签的有效权重）；不是 setup_boss 下建的换阶段 boss 就是 None。"""
    hit = _FIGHTS.get(id(f))
    return hit[1] if hit is not None and hit[0]() is f else None


def mark_restarts():
    """规则版本：setup_boss(fix_slots=True) 下，进场标记的加权从换阶段那一刻重新计数（D1）。r1v2 的视图按它决定公开的累计出牌从哪里算。"""
    return bool(_STATE["setup"] and _STATE["slot_fix"])


def _guard_start(rng):
    """守势起始相位（两个阶段同一个值）：对这场 Fight 的 rng **构造时的初始状态**做哈希，派生流抽一次，不消耗 rng。
    初始状态只由 boss 洗牌种子（run.shuffles[-1]）决定，所以对同一 (salt, stream, t) 的所有打法、两种顺序都相同，与谁怎么打无关。"""
    key = "boss-guard-start-v1:" + hashlib.blake2b(repr(rng.getstate()).encode(), digest_size=8).hexdigest()
    return random.Random(int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")).randrange(2)


class BossGuardStartMissing(RuntimeError):
    pass


BOSS_V1_VERSION = "boss-v1-2026-11-06"           # boss 第一版（PROTO_BOSS=v1）：play_boss / build_boss 的记录带它
BOSS_V1_GUARD0 = "boss salt (guard_slot.start_value('boss', salt), tagged at build)"
BOSS_V2_VERSION = "boss-v2-hp-2026-11-06"        # boss 第二版的旋钮（PROTO_BOSS_HP / PROTO_BOSS_TURNCAP，33 号文档）：只在非默认时进记录
BOSS_V4_VERSION = "boss-v4-irregular-2026-11-06"  # boss 第四版（35 号文档）：只在 PROTO_GUARDSEQ / CHARGESEQ / BOSS_CUE / BOSS_HANDOVER 有一个不是默认时进记录
SEQ_LEN = 64                                       # 预抽表的长度（>= boss 回合上限 60）
GUARD_MAX_SAME = 3                                 # 守势连着同一相位最多 3 个回合（连着两次不翻之后必翻）


def boss_v4_on():
    return (ap.GUARDSEQ, ap.CHARGESEQ, ap.BOSS_CUE, ap.BOSS_HANDOVER, ap.BOSS_SLOTSWAP, ap.BOSS_STRIKE, ap.BOSS_GUARDIN, ap.BOSS_ATK) != \
        ("none", "none", "on", "v1", "frozen", "none", "quiet", "100")


def scaled_atk(atk, pct):
    """boss 第八版：floor(atk x pct / 100 + 0.5)，至少 1（整数算，不经浮点）。"""
    return max(1, (atk * int(pct) * 2 + 100) // 200)


CHARGE_LEN_EXTRA = (0, 1, 2)                       # 第七版：在 1 上多停几个回合（各 1/3）


def charge_lengths(salt):
    """boss 第七版（PROTO_CHARGESEQ=len234）：第 i 个蓄力周期在 1 上多停几个回合（0 / 1 / 2，各 1/3）。流只看 boss salt。"""
    from adventure import TUNING
    rng = random.Random(f"charge-len-v1:{TUNING['identity_key']}:boss:{int(salt)}")
    return tuple(CHARGE_LEN_EXTRA[rng.randrange(len(CHARGE_LEN_EXTRA))] for _ in range(SEQ_LEN))


SLOT_MECHS = frozenset({"charge", "guard", "ward", "mark", "mimic"})   # 有怪方状态格的机制（这个池里：蓄力、守势、破势）


def mixed_pair(old, new):
    """boss 第五版：两个阶段是不是「一个有状态格、一个没有」（混合对）。"""
    return bool(set(old) & SLOT_MECHS) != bool(set(new) & SLOT_MECHS)


def guard_schedule(salt, level):
    """boss 守势的预抽表：第 t 个 END（t = 1..SEQ_LEN）翻不翻。每个 END 抽一个 u（强制翻的那一步也抽，表与上限无关地对齐）；
    翻 = 连着两次不翻之后（强制）或 u < p。流 = Random('guard-seq-v1:{identity_key}:boss:{boss salt}:{level}')，只看 boss salt。"""
    from adventure import TUNING
    p = int(level[3:]) / 100
    rng = random.Random(f"guard-seq-v1:{TUNING['identity_key']}:boss:{int(salt)}:{level}")
    out, run = [], 0
    for _ in range(SEQ_LEN):
        u = rng.random()
        flip = run >= GUARD_MAX_SAME - 1 or u < p
        run = 0 if flip else run + 1
        out.append(flip)
    return tuple(out)


def _map_release_turns(lengths=None, stalls=None, n=2):
    """前 n 次大招在第几个 END（地图战斗从计数 0 开始；开头是 2 的 END 放大招）。lengths = len234 的每周期多停回合，stalls = irr 的逐 END 停表。"""
    out, c, t, cyc, rem = [], 0, 0, 0, (lengths[0] if lengths else 0)
    while len(out) < n:
        t += 1
        if c == 2:
            out.append(t)
            if lengths:                                   # len234：放过之后印 1，新周期
                cyc += 1; rem = lengths[cyc]; c = 1
            else:
                c = 0
            continue
        if stalls and stalls[t - 1]:
            continue
        if lengths and c == 1 and rem > 0:
            rem -= 1
            continue
        c += 1
    return tuple(out)


FIXED_RELEASES = (3, 6)                                   # 固定节奏前两次大招的回合


def map_charge_lengths(salt, layer, node):
    """普通图的 len234（PROTO_MAPCHARGE，11-12 候选）：同 charge_lengths，流只看图 salt、层、节点。
    前两次大招恰好落在固定节奏的第 3、6 回合（没有被打乱）的表不用，按尝试序号换流重抽（流名带 :try{k}，k 从 0 起）。"""
    for k in range(100):
        rng = random.Random(f"map-charge-len-v1:{int(salt)}:{int(layer)}:{int(node)}:try{k}")
        out = tuple(CHARGE_LEN_EXTRA[rng.randrange(len(CHARGE_LEN_EXTRA))] for _ in range(SEQ_LEN))
        if _map_release_turns(lengths=out) != FIXED_RELEASES:
            return out
    raise RuntimeError("no irregular len234 table")


def map_guard_schedule(salt, layer, node, level):
    """普通图考试关的守势 irr50 / irr67（PROTO_MAPGUARD，11-12 候选）：同 guard_schedule 的规则（同一相位最多 GUARD_MAX_SAME 个回合），
    流只看图 salt、层、节点。前 3 个 END 每次都翻（与固定节奏无从区分）的表不用，按尝试序号换流重抽（:try{k}）。"""
    p = int(level[3:]) / 100
    for k in range(100):
        rng = random.Random(f"map-guard-seq-v1:{int(salt)}:{int(layer)}:{int(node)}:{level}:try{k}")
        out, run = [], 0
        for _ in range(SEQ_LEN):
            flip = run >= GUARD_MAX_SAME - 1 or rng.random() < p
            run = 0 if flip else run + 1
            out.append(flip)
        out = tuple(out)
        if not all(out[:3]):
            return out
    raise RuntimeError("no irregular guard table")


def charge_schedule(salt, level):
    """boss 蓄力的预抽表：第 t 个 END 停不停（只在开头是 0 / 1 的 END 上起作用；开头是 2 的照旧放大招）。不连停：上一个 END 的表是停，这一个就不停。
    流 = Random('charge-seq-v1:{identity_key}:boss:{boss salt}:{level}')。"""
    from adventure import TUNING
    q = int(level[3:]) / 100
    rng = random.Random(f"charge-seq-v1:{TUNING['identity_key']}:boss:{int(salt)}:{level}")
    out, prev = [], False
    for _ in range(SEQ_LEN):
        u = rng.random()
        stall = (not prev) and u < q
        prev = stall
        out.append(stall)
    return tuple(out)


def _seq_apply(f):
    """boss 第四版：在 _settle_phase 补丁的第一步调（引擎这一 END 的守势翻 / 蓄力涨已做完，换阶段还没做；f.parts = 管这一 END 的机制）。"""
    e = f.enemy
    gs, cs = getattr(e, "_guard_seq", None), getattr(e, "_charge_seq", None)
    if gs is None and cs is None and getattr(e, "_charge_len", None) is None:
        return
    s, t, parts = f.state, f.turn, f.parts
    log = f.__dict__.setdefault("_seq_log", [])
    if gs is not None and "guard" in parts:
        flip = gs[t - 1]
        if not flip:
            s[("them", "guard")] = 1 - s[("them", "guard")]   # 引擎每个 END 都翻：表说不翻 → 还原
            f.slots_changed.add("guard")                      # 引擎的翻会记的（画面照旧：第 2 回合起印）
            if f.track_seen:
                f.seen.add(("them", "guard"))
        log.append((t, "guard", bool(flip), s[("them", "guard")]))
    cl = getattr(e, "_charge_len", None)
    if cl is not None and "charge" in parts:          # 第七版 len234：放过大招 → 印 1（不印 0）；从 1 涨到 2 时按这一周期的表在 1 上多停
        st = f.__dict__.setdefault("_charge_len_state", dict(cycle=0, rem=cl[0]))
        v = s[("them", "charge")]
        if v == 0:                                    # 开头是 2：大招放了（引擎清 0）→ 新周期，印 1
            st["cycle"] += 1
            st["rem"] = cl[st["cycle"]]
            s[("them", "charge")] = 1
            f.slots_changed.add("charge")
            log.append((t, "charge_len", "fired", 1, st["cycle"], st["rem"]))
        elif v >= 2 and st["rem"] > 0:                # 从 1 涨到 2，但这一周期还要在 1 上停
            st["rem"] -= 1
            s[("them", "charge")] = 1
            f.slots_changed.add("charge")
            log.append((t, "charge_len", "hold", 1, st["cycle"], st["rem"]))
        else:
            log.append((t, "charge_len", "rise" if v >= 2 else "stay", v, st["cycle"], st["rem"]))
    if cs is not None and "charge" in parts:
        v = s[("them", "charge")]
        stalled = bool(v > 0 and cs[t - 1])                   # v > 0：这一 END 从 v − 1 涨上来（开头 0 / 1）；v == 0：开头是 2，放了大招
        if stalled:
            s[("them", "charge")] = v - 1
            f.slots_changed.add("charge")
            if f.track_seen:
                f.seen.add(("them", "charge"))
        log.append((t, "charge", stalled, s[("them", "charge")]))


class _FirstGuard:
    """构造期间代替 Fight.rng：第一次 randrange(2)（core/adventure.py:1435 守势起始相位）交派生值、不碰真流；其余调用原样转给真流。"""

    def __init__(self, real, g):
        self._real, self._g = real, g

    def randrange(self, *a):
        if self._g is not None:
            assert a == (2,), a
            g, self._g = self._g, None
            return g
        return self._real.randrange(*a)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _quiet_model_log(f, keys, info):
    """进场初始化不进模型 / 人类日志（同构造时：起始值从来不是一条「变化」）。modelrun.run_fight 在动作前存 before = dict(fight.state)
    （core/modelrun.py:1116、1254），换阶段那一行按 before 与当前状态的差列出（:1206-1207）；这里把那一帧的 before 里进场槽改成起始值。
    只认 modelrun.run_fight 自己的帧（且它的 fight 就是这一场）；别的驱动（solver.play_fight）没有日志，不受影响。"""
    mr = sys.modules.get("modelrun")
    if mr is None or not keys:
        return
    code = getattr(mr.run_fight, "__wrapped__", mr.run_fight).__code__
    fr = sys._getframe(2)
    while fr is not None:
        if fr.f_code is code:
            loc = fr.f_locals
            b = loc.get("before")
            if isinstance(b, dict) and loc.get("fight") is f:
                for p in sorted(keys):
                    b[("them", p)] = f.state[("them", p)]
                info["log_quieted"].append((f.turn, tuple(sorted(keys))))
            return
        fr = fr.f_back


def _threat_refresh(f, a0):
    """PROTO_THREAT=momentum（用户决定 3；12 §6）：boss 纯动量阶段，END 之后把攻击槽换成引擎下一次 END 那一击（挡 / 闪之前）。
    放在 self.turn += 1 之后，_in_grace() 读的正是这个数字要预报的那一回合；_incoming 是纯函数、不抽随机数；那一击本身不读攻击槽，
    伤害按构造不变。蓄力（D9，待用户）、穿透（依盾而定）、地图（is_boss 假）不碰。a0 = 这次 END 开始时的攻击槽。"""
    s = f.state
    if tuple(f.parts) != ("momentum",) or s[("me", "hp")] <= 0 or s[("them", "hp")] <= 0:
        return
    v = f._incoming()[0]
    if v != s[("them", "atk")]:
        info = fight_info(f)
        if info is not None:
            info.setdefault("threat", []).append((f.turn, f.shown_atk, v))
        s[("them", "atk")] = v
        if f.track_seen and v != a0:
            f.seen.add(("them", "atk"))           # 同 Fight._mark 的记法（攻击槽在第一次变化之前印 ?）


def _patch_slots():
    import adventure
    F = adventure.Fight
    if getattr(F, "_boss_slot_patch", False):
        return
    names = ("__post_init__", "_settle_phase", "_slots_moved", "end_turn")
    _ORIG["fight"] = {n: F.__dict__[n] for n in names}
    orig_post, orig_settle, orig_moved, orig_end = (_ORIG["fight"][n] for n in names)
    TUNING, SLOTS = adventure.TUNING, adventure.ENEMY_STATE_SLOTS

    def __post_init__(self):
        if not (_STATE["slot_fix"] and self.is_boss and getattr(self.enemy, "switch_to", None)):
            return orig_post(self)
        real = self.rng
        if ap.BOSS == "v1":                       # boss 第一版（PROTO_BOSS=v1，32 号文档）：开场攻守按 boss salt 建图时预抽（guard_slot.tag_starts），不看 rng
            g0 = getattr(self.enemy, "_guard_start", None)
            if g0 is None:
                raise BossGuardStartMissing("PROTO_BOSS=v1: the boss enemy carries no pre-drawn guard start (the boss Run was not built "
                                            "through antagonist_proto.build with PROTO_GUARDSTART=map)")
            info = dict(guard0=int(g0), guard0_source=BOSS_V1_GUARD0, mark_base=None, quiet=set(), log_quieted=[], mark_weights=[], handover=None)
        else:
            info = dict(guard0=_guard_start(real), mark_base=None, quiet=set(), log_quieted=[], mark_weights=[], handover=None)
        for k in [k for k, (r, _i) in _FIGHTS.items() if r() is None]:
            del _FIGHTS[k]
        _FIGHTS[id(self)] = (weakref.ref(self), info)
        if "guard" not in self.enemy.parts_for(False):
            return orig_post(self)
        proxy = _FirstGuard(real, info["guard0"])  # 第一阶段守势：起点也走派生流，于是两种顺序的洗牌流逐张相同（原写法先从 rng 抽一次，挪动整条牌流）
        self.rng = proxy
        try:
            orig_post(self)
        finally:
            self.rng = real
            if getattr(self, "pile", None) is not None and self.pile.rng is proxy:
                self.pile.rng = real
        assert proxy._g is None, "守势起始相位没有被抽"

    def _settle_phase(self):
        if ap.GUARDSEQ != "none" or ap.CHARGESEQ != "none" or ap.MAPCHARGE != "none" or ap.MAPGUARD != "none":   # boss 第四版（35 号文档）/ 普通图蓄力节奏（候选）：默认 none 下这一行什么也不做
            _seq_apply(self)
        info = _FIGHTS.get(id(self))
        info = info[1] if info is not None and info[0]() is self else None
        if not _STATE["slot_fix"] or info is None or self._phase2 or not self._switch_pending:
            return orig_settle(self)
        real = ap.INCOMING == "real"              # PROTO_INCOMING（12 §5）：每次调用时读（ap.switched / archived 能切）
        pre_slots = {p: self.state[("them", p)] for p in SLOTS} if real else None   # 必须在 orig_settle 之前：引擎原函数已经会写进场蓄力
        old = set(self.parts)
        orig_settle(self)                         # 引擎原样：计数、进场蓄力、印出的攻击、提示事件
        new = set(self.parts); s = self.state; inc = new - old
        if ap.BOSS_CUE == "bytype" and mixed_pair(old, new) and self.events and self.events[-1] == (self.turn, adventure.BOSS_SHIFT):
            self.events.pop()                     # boss 第五版：混合对不出提示（同类对照引擎原样出）；默认 on 下这一行什么也不做
        for p in SLOTS:                           # 离场的槽清零：不再印成「有效」（这是公开变化，画面 / 日志都有）
            if p in old and p not in new:
                s[("them", p)] = 0
        if "ward" in old - new:
            self.ward_open_left = 0
        quiet = set()
        if "guard" in inc:                        # 构造时的规则：起始相位（派生流，构造时已抽好），非零记入 seen
            g = info["guard0"]
            s[("them", "guard")] = g; quiet.add("guard")
            if g:
                self.seen.add(("them", "guard"))
        if "ward" in inc:                         # 构造时：enemy.ward_start or 1，记入 seen
            s[("them", "ward")] = self.enemy.ward_start or 1; self.ward_open_left = 0
            self.seen.add(("them", "ward")); quiet.add("ward")
        if "mark" in inc:                         # 构造时：代号 0；加权计数从这里重新开始（fight_kinds 本身不动，见 end_turn）
            s[("them", "mark")] = 0; quiet.add("mark")
            info["mark_base"] = dict(self.fight_kinds)
        if "mimic" in inc:
            s[("them", "mimic")] = 0; quiet.add("mimic")
        if "charge" in inc:                       # 构造时 boss 的规则：min(boss_charge_start, charge_max-1)
            pre = TUNING["boss_charge_start"]
            start = min(pre, max(0, self.enemy.charge_max - 1)) if pre else 0
            s[("them", "charge")] = start; quiet.add("charge")
            if start:
                self.seen.add(("them", "charge"))
        if real:                                  # PROTO_INCOMING=real：起始值与 END 开始时不同 = 真实变化（引擎的 _slots_moved 把它加进 slots_changed，
            #                                       modelrun 那一行 END 差照常列出）；起点 0 什么也不做。不静音、不伪造
            changes = {p: [pre_slots[p], s[("them", p)]] for p in sorted(inc & set(SLOTS)) if s[("them", p)] != pre_slots[p]}
            info["quiet"] = set()
            info["handover"] = dict(turn=self.turn, incoming=sorted(inc), outgoing=sorted(old - new), quiet=[],
                                    incoming_mode="real", incoming_changes=changes)
        else:
            info["quiet"] = {p for p in quiet if p not in self.slots_changed}
            info["handover"] = dict(turn=self.turn, incoming=sorted(inc), outgoing=sorted(old - new), quiet=sorted(quiet))
            _quiet_model_log(self, quiet, info)

    def _slots_moved(self, before):
        orig_moved(self, before)
        info = _FIGHTS.get(id(self))
        if info is not None and info[0]() is self and info[1]["quiet"]:
            self.slots_changed -= info[1]["quiet"]  # 起始值不算「变过」，与构造时同（state_slots="seen" 的画面）
            info[1]["quiet"] = set()
        if ap.BOSS_GUARDIN == "now" and info is not None and info[0]() is self:      # boss 第七版：进场的守势格当场就印（默认 quiet 下什么也不做）
            h = info[1].get("handover")
            if h is not None and h["turn"] == self.turn and "guard" in h["incoming"]:
                self.slots_changed.add("guard")
                h["guard_printed_now"] = True
        if ap.BOSS_SLOTSWAP == "vanish" and info is not None and info[0]() is self:   # boss 第五版：离场的格从此不印（默认 frozen 下什么也不做）
            h = info[1].get("handover")
            if h is not None and h["turn"] == self.turn and not h.get("vanished"):
                gone = set(h["outgoing"]) & set(SLOTS)
                self.slots_changed -= gone
                h["vanished"] = sorted(gone)

    def _d1_end_turn(self):
        info = _FIGHTS.get(id(self)) if _FIGHTS else None
        base = info[1]["mark_base"] if info is not None and info[0]() is self else None
        if base is None or "mark" not in self.parts:
            return orig_end(self)
        real = self.fight_kinds; frozen = dict(real)
        self.fight_kinds = {k: v - base.get(k, 0) for k, v in real.items()}   # 进场标记：只按换阶段之后的出牌加权（同 boss 开场从 {} 起）
        info[1]["mark_weights"].append((self.turn, dict(self.fight_kinds)))
        try:
            return orig_end(self)
        finally:
            assert real == frozen, "end_turn 改了 fight_kinds"
            self.fight_kinds = real               # 原对象放回：cautious / r1v2 按它的增量算本回合出了什么

    def end_turn(self):
        if ap.THREAT != "momentum" or not self.is_boss:   # 默认（PROTO_THREAT=plain）：直接走原来的函数体，多一次全局读、不碰状态
            return _d1_end_turn(self)
        a0 = self.state[("them", "atk")]
        r = _d1_end_turn(self)
        _threat_refresh(self, a0)
        return r

    F.__post_init__, F._settle_phase, F._slots_moved, F.end_turn = __post_init__, _settle_phase, _slots_moved, end_turn
    F._boss_slot_patch = True


def teardown_boss():
    """撤掉 setup_boss() 的全部效果，同一进程里回到旧行为：Fight 的四个方法换回原函数、提示文字换回原文字（adventure / modelrun /
    parse_log / 已载入的重放核对器）、TUNING 的 boss 键回到第一次 setup_boss 时 antagonist_proto.setup() 之后的值（boss_switch=0 等）、
    清掉逐场记录。之后再 ap.setup() 建的地图 Run 就是两场先后的 boss、旧文字、旧 _settle_phase。幂等。"""
    import adventure
    from adventure import TUNING
    F = adventure.Fight
    # PROTO_LADDER=1（候选）：阶梯在 boss 层之外 —— 先撤，换回 Fight 的原方法，再装回（ap.teardown() 已经撤过就不装回）。默认（0）什么也不做。
    with ap.ladder_outside("if-lifted"):
        for n, fn in _ORIG.pop("fight", {}).items():
            setattr(F, n, fn)
        if "_boss_slot_patch" in F.__dict__:
            delattr(F, "_boss_slot_patch")
        for (mod, attr), v in _ORIG.pop("cue", {}).items():
            setattr(mod, attr, v)
        if "strike_table" in _ORIG:                # boss 第六版：换过的表还原
            import penalty_ladder as pl
            name, t0 = _ORIG.pop("strike_table")
            pl.TABLES[name] = t0
            if pl._STATE["installed"]:
                pl._STATE["table"] = pl._check_table(t0)
        if "ward_strike" in _ORIG:                 # 43 号文档 §14：probe1w 打开的破势犯规还原
            import penalty_ladder as pl
            pl.WARD_STRIKE = _ORIG.pop("ward_strike")
        if "handover_steps" in _ORIG:              # boss 第四版：PROTO_BOSS_HANDOVER=x1 换过的表还原
            import penalty_ladder as pl
            pl.HANDOVER_STEPS_V3C1B = _ORIG.pop("handover_steps")
        ap.unregister_after_setup("antagonist_boss")
        if "tuning" in _ORIG:
            TUNING.update(_ORIG.pop("tuning"))
        _FIGHTS.clear()
        _STATE.update(setup=False, slot_fix=False, keys=None)


# ---------------------------------------------------------------- 建 boss
def build_boss(salt, pair, reverse):
    """pair = (第一阶段, 第二阶段)（reverse=0 时的阶段顺序）；reverse=1 得到反过来的顺序。ctx["phase_order"] 是实际顺序。"""
    assert _STATE["setup"], "先调 setup_boss()"
    import adventure
    from adventure import TUNING
    pair = tuple(pair)
    assert len(pair) == 2 and pair[0] != pair[1] and set(pair) <= set(adventure.BEHAVIOURS), pair
    want = (pair[1], pair[0]) if reverse else pair
    saved = {k: TUNING[k] for k in ("boss_pool_exclude", "boss_switch_reverse")}
    try:
        TUNING["boss_pool_exclude"] = tuple(m for m in adventure.BEHAVIOURS if m not in pair)   # P1：池里只剩这一对（穿透也随之放开）
        TUNING["boss_switch_reverse"] = 0
        run = ap.build(salt)
        drawn_order = tuple(run.boss_stages)
        eng_rev = int(drawn_order != want)
        if eng_rev:
            TUNING["boss_switch_reverse"] = 1
            run = ap.build(salt)
            assert tuple(run.boss_stages) == drawn_order
    finally:
        TUNING.update(saved)
    assert len(run.boss_enemies) == 1, "boss_switch 没开"
    e = run.boss_enemies[0]
    order = ("+".join(e.parts_for(False)), "+".join(e.parts_for(True)))
    assert order == want, (order, want)
    fixed = []
    if _STATE["slot_fix"]:
        if "ward" in order[1] and "ward" not in order[0]:
            e.ward_cap, e.ward_start = TUNING["ward_boss_cap"], TUNING["ward_boss_start"]; fixed.append("ward_cap")
        if "charge" in order[1] and "charge" not in order[0] and TUNING["charge_max_boss"]:
            e.charge_max = TUNING["charge_max_boss"]; fixed.append("charge_max")
    out = dict(run=run, salt=salt, pair=pair, reverse=int(bool(reverse)), engine_reverse=eng_rev, drawn_order=drawn_order,
               phase_order=order, boss_hp=e.hp, switch_at=e.switch_at, boss_atk=e.atk, base_atk=run.base_atk,
               base_max_hp=run.base_max_hp, slot_fix=_STATE["slot_fix"], init_fixes=fixed,
               tuning={k: TUNING[k] for k in BOSS_KEYS}, proto=ap.switches(), references=ap.references())
    if ap.BOSS == "v1":                           # boss 第一版：守势开场（boss salt 预抽）与守势编码（boss salt）记进 ctx；默认下 ctx 逐字不变
        assert getattr(e, "_guard_start", None) is not None, "PROTO_BOSS=v1: boss enemy not tagged with its guard start"
        out["boss_v1"] = dict(version=BOSS_V1_VERSION, guard_start=int(e._guard_start), guard_start_rule=BOSS_V1_GUARD0,
                              guard_code=getattr(run, "guard_code", {}).get("boss"), switch_frac=TUNING["boss_switch_frac"],
                              switch_hp_pct=TUNING["boss_switch_hp_pct"])
    if ap.BOSS_HP != "100" or ap.BOSS_TURNCAP != "none":   # boss 第二版（33 号文档）：默认下不进 ctx、不碰敌人
        assert TUNING["boss_switch_hp_pct"] == int(ap.BOSS_HP), ("PROTO_BOSS_HP not applied", TUNING["boss_switch_hp_pct"], ap.BOSS_HP)
        if ap.BOSS_TURNCAP != "none":
            e._turn_cap = int(ap.BOSS_TURNCAP)
        out["boss_v2"] = dict(version=BOSS_V2_VERSION, hp_pct=int(ap.BOSS_HP), turn_cap=getattr(e, "_turn_cap", None) or ap.TURN_CAP,
                              map_turn_cap=ap.TURN_CAP, boss_hp=e.hp, switch_at=e.switch_at)
    if ap.BOSS_ATK != "100":                         # boss 第八版（39 号文档）：boss 的基础攻击乘倍数；默认 100 下这一段什么也不做
        e._atk_x1 = e.atk
        e.atk = scaled_atk(e.atk, ap.BOSS_ATK)
        out["boss_atk"] = e.atk
    if boss_v4_on():                                 # boss 第四版（35 号文档）：默认下不进 ctx、不碰敌人
        if ap.GUARDSEQ != "none":
            e._guard_seq = guard_schedule(salt, ap.GUARDSEQ)
        if ap.CHARGESEQ == "len234":               # 第七版：等长不一的蓄力周期
            e._charge_len = charge_lengths(salt)
        elif ap.CHARGESEQ != "none":
            e._charge_seq = charge_schedule(salt, ap.CHARGESEQ)
        out["boss_v4"] = dict(version=BOSS_V4_VERSION, guardseq=ap.GUARDSEQ, chargeseq=ap.CHARGESEQ, cue=ap.BOSS_CUE, handover=ap.BOSS_HANDOVER,
                              **({"slotswap": ap.BOSS_SLOTSWAP, "mixed": mixed_pair(order[0].split("+"), order[1].split("+"))}
                                 if (ap.BOSS_SLOTSWAP != "frozen" or ap.BOSS_CUE == "bytype" or ap.BOSS_HANDOVER == "x1m2") else {}),
                              **({"strike": ap.BOSS_STRIKE} if ap.BOSS_STRIKE != "none" else {}),
                              **({"atk_pct": int(ap.BOSS_ATK), "atk_x1": e._atk_x1, "atk": e.atk} if ap.BOSS_ATK != "100" else {}),
                              **({"guardin": ap.BOSS_GUARDIN, "charge_len": getattr(e, "_charge_len", None)}
                                 if (ap.BOSS_GUARDIN != "quiet" or ap.CHARGESEQ == "len234") else {}),
                              switch_hint=TUNING["boss_switch_hint"], guard_seq=getattr(e, "_guard_seq", None), charge_seq=getattr(e, "_charge_seq", None))
    return out


# ---------------------------------------------------------------- 一条命的记录
class Trace:
    """逐回合记录（草案 3 要的量）；可再包一个调用方的 record，钩子照转。
    每回合：turn、phase（1/2，按回合开始时引擎是否已换阶段）、parts（引擎真实的当前机制，判分事实来源）、开局血量 / 怪血 / 能量 / 手牌种类、
    slots（画面上印出的怪方状态槽，cautious.them_slots 读画面文字）、atk、acts（按序出的牌种，不含 play_fight 直接出的治疗）、
    played（本回合各牌种张数，含治疗）、block / dodge（结算前）、hp_end / them_hp_end / taken、events（引擎事件 boss_shift + 审计计数
    的正增量 + punished[i] 增量）、truth（没印出的引擎真值：momentum、stalls、fed —— 只给判分用，打法读不到）。"""
    belief = None
    COUNTERS = ("reflected", "mark_hits", "ward_wasted", "ward_opened", "fed", "dodge_offered", "mimic_hits", "countered")

    def __init__(self, inner=None, track_seen=False):
        self.inner, self.track = inner, track_seen
        self.turns = []; self.cur = None; self.hp_at_switch = None; self.switch_turn = None; self.n_ev = 0

    def _fwd(self, name, *a):
        h = getattr(self.inner, name, None) if self.inner is not None else None
        if h is not None:
            h(*a)

    def enter(self, run, f, kinds):
        if self.track:
            f.track_seen = True                   # 读画面的习惯要看到人看到的画面（同 shortcut_screen.TrackSeen）
        if self.inner is not None:
            self.inner.belief = self.belief
        self.hp0 = f.state[("me", "hp")]
        self._fwd("enter", run, f, kinds)

    def before_decision(self, f):
        import cautious
        s = f.state
        self.cur = dict(turn=f.turn, phase=2 if f._phase2 else 1, parts=list(f.parts), hp=s[("me", "hp")], them_hp=s[("them", "hp")],
                        energy=s[("me", "energy")], hand=[f.deck[n].kind for n in f.hand], slots=cautious.them_slots(f),
                        atk=s[("them", "atk")], acts=[],          # atk = 攻击槽的值（画面在它第一次变化前印 ?；脚本关了 seen 追踪，这里不判）
                        _c={k: getattr(f, k) for k in self.COUNTERS}, _p=list(f.punished))
        pl = sys.modules.get("penalty_ladder")
        if pl is not None and pl.installed() and pl.MOMENTUM_MODE in ("noshield", "shieldonly"):   # 候选 v3：这一 END 之前阶梯已罚的动量次数（after_end_turn 取走）；shieldonly（18 §8.7）同
            self.cur["_mom_k"] = pl.momentum_punished(f)
        self.turns.append(self.cur)
        self._fwd("before_decision", f)

    def before_play(self, f, c):
        self.cur["acts"].append(f.deck[c].kind); self._fwd("before_play", f, c)

    def after_play(self, f, c, atk_before):
        self._fwd("after_play", f, c, atk_before)

    def before_end_turn(self, f):
        self.cur["played"] = dict(f.played_kinds)  # 含 play_fight 直接出的治疗（它不经 before_play）
        self.cur["block"] = f.state[("me", "block")]; self.cur["dodge"] = f.state[("me", "dodge")]
        self._fwd("before_end_turn", f)

    def after_end_turn(self, f, hp_before, block_before, charge_before):
        c = self.cur; s = f.state
        ev = [name for _t, name in f.events[self.n_ev:]]; self.n_ev = len(f.events)
        ev += [k for k in self.COUNTERS if getattr(f, k) > c["_c"][k]]
        ev += [f"punished[{i}]" for i, (a, b) in enumerate(zip(c.pop("_p"), f.punished)) if b > a]
        c.pop("_c")
        truth = dict(momentum=f.momentum, stalls=f.stalls, fed=f.fed)
        pl = sys.modules.get("penalty_ladder")
        if pl is not None and pl.installed() and pl.MOMENTUM_MODE in ("noshield", "shieldonly"):   # shieldonly（18 §8.7）同一条读法
            # 候选 v3（PROTO_MOMENTUM=noshield，2026-11-05 审查后）：引擎自己的连续计数 Fight.momentum 和它记的 punished[3]（连续 >= 2）不是这条规则的量
            # （阶梯一个也不读它们）。这里 punished[3] 改记「这一 END 阶梯真的按 noshield 罚了一次」（penalty_ladder.momentum_punished 涨了），
            # truth.momentum 改记阶梯这一场已罚的次数；引擎的那两个另记 truth.momentum_engine_streak / events 里的 engine_punished[3]。默认（streak）下一个字节也不变。
            k0, k1 = c.pop("_mom_k", 0), pl.momentum_punished(f)
            if "punished[3]" in ev:
                ev[ev.index("punished[3]")] = "engine_punished[3]"
            if k1 > k0:
                ev.append("punished[3]")
            truth.update(momentum=k1, momentum_engine_streak=f.momentum, momentum_rule=pl.MOMENTUM_MODE)   # noshield 下 = "noshield"（逐字不变）
        c.update(hp_end=s[("me", "hp")], them_hp_end=s[("them", "hp")], taken=hp_before - s[("me", "hp")], events=ev, truth=truth)
        if f._phase2 and self.switch_turn is None:
            self.switch_turn, self.hp_at_switch = f._phase2_turn, s[("me", "hp")]
        self._fwd("after_end_turn", f, hp_before, block_before, charge_before)

    def leave(self, f, won):
        self._fwd("leave", f, won)

    def rest(self, run, mode):
        self._fwd("rest", run, mode)


# ---------------------------------------------------------------- 一条 boss 命（D2）
def oracle_veto_on(flag=None):
    """全知这一条命用不用 N5 的否决：显式 flag > 模块的 ORACLE_VETO > r1v2.ENERGY_VETO（变更集 c 的开关，默认开）。"""
    return ap.oracle_veto_on(flag)                 # 同一判定：flag > ORACLE_VETO（本模块）> r1v2.ENERGY_VETO


def _policy(ctx, who, item, oracle_veto=None):
    """出牌的那一半（知识、路线、策略）。画面不在这里：play_boss / play_map 统一用 ap.display_settings(who) / ap.tracks_screen(who)。
    ref = 记版本用的对象（R1v2 的策略、全知的否决函数；没有就是 None），见 _ref_record。"""
    import cautious, devworld, solver
    route9 = solver.SCREEN_ROUTES[9]
    if who == "R1":
        p = cautious.Cautious(devworld.R1_VARIANT)
        return dict(know=solver.ALL - {"mark"}, route=route9,
                    kw=dict(information="observable", act_policy=p.act, heal_veto=p.heal_veto, belief_cls=cautious.PublicBelief))
    if who == "R1v2":
        import inspect, r1v2                       # 接口：R1v2Policy(.act, .heal_veto)、R1v2Belief
        P = r1v2.R1v2Policy
        p = P(devworld.R1_VARIANT) if len(inspect.signature(P).parameters) else P()
        return dict(know=getattr(r1v2, "KNOW", solver.ALL - {"mark"}), route=route9, ref=p,
                    kw=dict(information="observable", act_policy=p.act, heal_veto=p.heal_veto, belief_cls=r1v2.R1v2Belief))
    if who == "oracle":
        kw, veto = dict(information="oracle", heal_veto=ap.no_heal_veto), None   # 关着：显式「不否决」（None 会被 ap 的 play_fight 包装接上默认否决）
        if oracle_veto_on(oracle_veto):            # N5：同 play_fight 对全知会走的选择（solver.act，oracle 信息，路线的 enrage_budget）
            import r1v2
            veto = kw["heal_veto"] = r1v2.oracle_heal_veto(solver.ALL, ctx["run"].by_kind, route9.enrage_budget)
        return dict(know=solver.ALL, route=route9, kw=kw, ref=veto)
    if who == "habit":                             # 冻结清单的一项，路径同 antagonist_preboss.habit_job
        import shortcut_screen as ss, fixed_panel as fp
        base = ss.bases()[item["base"]]
        roles_inv = {m: ctx["run"].layout.L("them", m) for m in ap.ROLES}
        trig, resp = fp.concrete(item, roles_inv)
        dark = None if item["dark"] == "none" else item["dark"]
        return dict(know=solver.NONE, route=ss.routes()[item["route"]],
                    kw=dict(information="observable", blind=base, act_policy=ss.make_act(base, trig, resp, dark)))
    if who == "blind":                             # (line, route)，同 solver.blind_gate 的一对
        line, route = item
        return dict(know=solver.NONE, route=route, kw=dict(information="observable", blind=line))
    raise ValueError(who)


def _ref_record(who, cfg):
    """参照版本的记录（N5）：R1v2 → 策略版本、开没开 c 的否决、否决次数；全知 → 用没用 c 的否决、否决次数；其余 None。"""
    r = cfg.get("ref")
    if who == "R1v2":
        return dict(version=getattr(r, "version", None), energy_veto=getattr(r, "energy_veto", None),
                    vetoes=len(getattr(r, "energy_vetoes", ())))
    if who == "oracle":
        return dict(heal_veto="r1v2.oracle_heal_veto (change set c, N5)" if r is not None else None,
                    vetoes=r.stats["vetoed"] if r is not None else 0)
    return None


DEALS = ("trial", "structural")


class _DealRng:
    """deal="structural" 时交给 solver.run_once 的 rng：先依次交出这张图的结构洗牌种子 run.shuffles（run_once 先分洗牌种子，
    core/solver.py:1353；参与者入口 run.fight_at 用的就是 run.shuffles[i]），之后转给平常的逐命流（节点种子；固定节点下只有休息层用到，
    自动补给与它无关）。"""

    def __init__(self, head, tail):
        self.head, self.tail = list(head), tail

    def randrange(self, *a):
        if self.head:
            assert a == (1 << 30,), a
            return self.head.pop(0)
        return self.tail.randrange(*a)


def play_map(run, salt, who, t, stream, item=None, record=None, oracle_veto=None, boss_entry=None, deal="trial"):
    """一条地图命（脚本参照；现行版本：每层固定节点、无奖励、统一画面，由 ap.setup() 的开关决定），到图末为止
    （原型的图没有 boss：fight_boss=False）。出牌同 play_boss（_policy；全知的 N5 否决按 oracle_veto）；随机流同 antagonist_proto._lives：
    solver._trial_rng(SEED ^ salt, stream, t)，deal="structural" 时洗牌换成这张图的结构种子（参与者的那一副，见模块说明）；
    读画面的玩家按 ap.tracks_screen 打开 `?` 追踪（ap.screen）。"""
    import solver
    ap.require_mark_table(run)                    # PROTO_MARKMAP=world：没绑表就拒绝（salt 下什么也不做）
    assert who in WHO and deal in DEALS, (who, deal)
    rng = solver._trial_rng(ap.SEED ^ salt, stream, t)
    if deal == "structural":
        rng = _DealRng(run.shuffles, rng)
    cfg = _policy(dict(run=run), who, item, oracle_veto)
    with ap.using_display(who) as disp:
        won = solver.run_once(run, cfg["know"], cfg["route"], rng, record=ap.screen(who, record), boss_entry=boss_entry,
                              fight_boss=False, **cfg["kw"])
    s = ap.settings()
    out = dict(who=who, t=t, stream=stream, salt=salt, won=bool(won), deal=deal,
               proto=dict(version=s["version"], loot=s["loot"], nodes=s["nodes"], display=s["display"], refs=s["refs"], hand=s["hand"],
                          turn_cap=s["turn_cap"], dodge_run_limit=s["dodge_run_limit"],   # hand 等三项：11-03 晚（PROTO_HAND）
                          incoming=s["incoming"], threat=s["threat"], markmap=s["markmap"],    # 12：三个候选开关（信息性键）
                          ladder=s["ladder"], tune=s["tune"]),                                  # 11-03 夜：PROTO_LADDER / PROTO_TUNE（信息性键）
               display=dict(disp), track_seen=ap.tracks_screen(who), ref=_ref_record(who, cfg))
    if ap.MARKMAP == "world":                     # 默认（salt）下不加键
        out["mark"] = ap.mark_record(run, salt)
    return out


def play_boss(ctx, who, t, stream, item=None, record=None, oracle_veto=None, deal="trial"):
    import solver
    from adventure import TUNING
    ap.require_mark_table(ctx["run"])             # PROTO_MARKMAP=world：没绑表就拒绝（salt 下什么也不做）
    assert who in WHO and deal in DEALS, (who, deal)
    now = {k: TUNING[k] for k in BOSS_KEYS}
    assert now == ctx["tuning"] == boss_settings() and _STATE["slot_fix"] == ctx["slot_fix"], ("建 boss 之后改过设置", now, ctx["tuning"], boss_settings())
    assert ap.switches() == ctx["proto"], ("建 boss 之后换过原型开关", ap.switches(), ctx["proto"])
    run = ctx["run"]
    if deal == "structural":
        shuffles = list(run.shuffles)                                  # 参与者入口打的那一副（proto_play：with run.trial() 不换种子）
    else:
        rng = solver._trial_rng(ap.SEED ^ ctx["salt"], stream, t)
        shuffles = [rng.randrange(1 << 30) for _ in run.shuffles]      # 同 run_once：先分好全部种子，boss 用最后一个
    cfg = _policy(ctx, who, item, oracle_veto)
    disp = ap.display_settings(who)
    tr = Trace(record, track_seen=ap.tracks_screen(who))
    saved = {k: TUNING[k] for k in disp}
    try:
        TUNING.update(disp)
        with run.trial(shuffles=shuffles):        # D2：满血（基础上限）、固定 18 张起始牌组、命级计数清零（探针还回来）、seen_player 清空
            assert run.base_atk == ctx["base_atk"] and run.hp == run.max_hp == run.base_max_hp and run.punished == (0,) * 8
            assert len(run.deck_list) == ap.life_deck_len(), len(run.deck_list)   # 18；修订 6（PROTO_HEAL=off）15
            f = next(run.boss_fights())
            hp0 = f.state[("me", "hp")]
            route = cfg["route"]
            won = solver.play_fight(run, f, cfg["know"], run.by_kind, route.heal_at, record=tr,
                                    enrage_budget=route.enrage_budget, **cfg["kw"])
            hp_end = f.state[("me", "hp")]
    finally:
        TUNING.update(saved)
    out = dict(who=who, t=t, stream=stream, deal=deal, salt=ctx["salt"], pair=list(ctx["pair"]), reverse=ctx["reverse"],
               phase_order=list(ctx["phase_order"]), won=bool(won), hp0=hp0, hp_at_switch=tr.hp_at_switch, hp_end=hp_end,
               turns=len(tr.turns), switch_turn=tr.switch_turn, trace=tr.turns,
               proto=dict(version=ctx["proto"]["version"], loot=ctx["proto"]["loot"], nodes=ctx["proto"]["nodes"],
                          display=ctx["proto"]["display"], refs=ctx["proto"]["refs"], hand=ctx["proto"]["hand"], turn_cap=ctx["proto"]["turn_cap"],
                          dodge_run_limit=ctx["proto"]["dodge_run_limit"],
                          incoming=ctx["proto"]["incoming"], threat=ctx["proto"]["threat"], markmap=ctx["proto"]["markmap"],   # 12：信息性键
                          ladder=ctx["proto"]["ladder"], tune=ctx["proto"]["tune"]),   # 11-03 夜：PROTO_LADDER / PROTO_TUNE（信息性键）
               tuning=dict(now), display=disp, track_seen=tr.track, ref=_ref_record(who, cfg))
    if ap.MARKMAP == "world":                     # 默认（salt）下不加键
        out["mark"] = ap.mark_record(run, ctx["salt"])
    if ap.BOSS == "v1":                           # boss 第一版：只在 PROTO_BOSS=v1 下加键
        out["boss_v1"] = ctx["boss_v1"]
    if "boss_v2" in ctx:                          # boss 第二版：只在两个旋钮有一个不是默认时
        out["boss_v2"] = dict(ctx["boss_v2"], ended_by=ap.ended_by(f))
    if "boss_v4" in ctx:                          # boss 第四版：只在四个开关有一个不是默认时
        out["boss_v4"] = dict(version=BOSS_V4_VERSION, seq_log=list(f.__dict__.get("_seq_log", [])))
    return out


# ---------------------------------------------------------------- 确定性核对 + 冒烟（几条命）
def _selfcheck():
    import adventure, solver
    from adventure import TUNING
    if (ap.INCOMING, ap.THREAT, ap.MARKMAP) != ("mute", "plain", "salt"):    # 12 §7.3：候选开关下不跑（这份自检的期望按现行版本写）
        raise SystemExit(f"PROTO_INCOMING / PROTO_THREAT / PROTO_MARKMAP are candidate switches not yet adopted; this self-check runs only "
                         f"under the defaults (now incoming={ap.INCOMING} threat={ap.THREAT} markmap={ap.MARKMAP}); "
                         f"the switches are checked by scripts/c10fix_check.py")
    ap.setup(); old = ap.build(2000000)
    old_sig = ([L.behaviour for L in old.layers], list(old.shuffles), list(old.boss_stages))
    setup_boss()
    new = ap.build(2000000)
    assert ([L.behaviour for L in new.layers], list(new.shuffles), list(new.boss_stages)) == old_sig, "boss_switch 动了地图抽签"
    assert TUNING["boss_pool_exclude"] == ("pierce",)
    print("提示:", [(s["site"], s["patched"]) for s in cue_sites()])
    for pair in (("pierce", "momentum"), ("guard", "ward"), ("charge", "mark")):
        for rev in (0, 1):
            ctx = build_boss(2000000, pair, rev)
            assert TUNING["boss_pool_exclude"] == ("pierce",)
            again = build_boss(2000000, pair, rev)
            assert (again["boss_hp"], again["switch_at"], list(again["run"].shuffles)) == (ctx["boss_hp"], ctx["switch_at"], list(ctx["run"].shuffles))
            res = [play_boss(ctx, w, t, "boss-smoke") for w in ("R1", "oracle") for t in range(3)]
            res.append(play_boss(ctx, "blind", 0, "boss-smoke", item=solver.blind_gate(full=True)[0]))
            sw = [r for r in res if any(x["phase"] == 2 for x in r["trace"])]   # 换阶段那一回合末就死了的命没有第二阶段的决策
            for r in sw:                          # 换阶段后第一回合：离场槽为 0，提示事件在换阶段那一回合
                k = next(i for i, x in enumerate(r["trace"]) if x["phase"] == 2)
                pre, post = r["trace"][k - 1], r["trace"][k]
                assert "boss_shift" in pre["events"], pre["events"]
                assert not any(v for lab, v in post["slots"].items()
                               if lab in {new.layout.L("them", p) for p in ctx["phase_order"][0].split("+")}), post["slots"]
            print(f"{pair} rev={rev} 实际顺序 {ctx['phase_order']} 抽签 {ctx['drawn_order']} 血 {ctx['boss_hp']} 换线 {ctx['switch_at']} "
                  f"补 {ctx['init_fixes']}：" + " ".join(f"{r['who']}{'W' if r['won'] else 'L'}@{r['switch_turn']}" for r in res))
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        _selfcheck()
    else:
        print(__doc__)
