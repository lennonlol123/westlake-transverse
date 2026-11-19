"""拮抗池原型（L2）。不动登记 12 的任何文件，不改 core/，不花 API。
池 PROTO = charge, pierce, momentum, guard, mark, ward（反击换出、动量换进；三对拮抗：穿透↔动量、守势↔破势、蓄力↔标记）。
其余配置 = 登记 12 的原型（PROTOTYPE_12，auto_rest=1，momentum_full_ratio 按登记值 450），世界 A 的身份，草稿 salt 段 2000000 起。

== 版本 PROTO_VERSION = "proto13-v2-2026-11-03"（用户 2026-11-03：「把尺子修好，按照当前的版本逻辑修，取消拿牌之类的选择」）==
每个玩家 —— 脚本参照（R1 / R1v2 / 全知）、冻结习惯、盲线、模型、人 —— 都玩同一版；全部在本文件的 setup() 里装（补丁 / 包装），core/ 一字不改
（core/*.py 与登记文件的代码指纹必须一致：gates.code_fingerprint() == results/pre_registration.json["code_sha256_16"]）。
开关（环境变量，导入时读一次；括号里是默认值 = 现行版本；每个都可逆）：
  PROTO_LOOT     (0)      0 = 删掉拿牌和里程碑属性奖励（每张图只剩战斗 + 自动补给）；1 = 旧行为（有奖励）
  PROTO_NODES    (fixed)  fixed = 每层只有一场固定的战斗，人人相同（规则见 fixed_node：第 0 个节点）；route = 旧行为
                          （脚本玩家每条命按 solver 的 node_seeds 随机进一个节点，模型 / 人自己选）
  PROTO_DISPLAY  (seen)   seen / hidden = 所有玩家同一个画面：marks=0 + state_slots=该值（display_settings()）；
                          per-player = 旧的各人各画面（R1 / R1v2 / 全知 = devworld.R1_DISPLAY；习惯 = state_slots seen；盲线 / 模型 / 人 = 引擎默认 hidden）
  PROTO_CAMP     (0)      原型世界有没有营地（待用户定）：0 = 没有；1 = 参与者入口打营地。脚本参照从来不打营地，与此开关无关
  PROTO_REFS     (c)      参照版本（N5，2026-11-03 审查后加的开关）：c = R1v2 c 版（r1v2.ENERGY_VETO=True）+ 全知在**每一条**全知路径上带 N5
                          否决（setup() 包 solver.play_fight：information="oracle"、没有 act_policy / blind / heal_veto 的玩家自动接
                          r1v2.oracle_heal_veto；antagonist_boss 自己显式接）；b = R1v2 b 版 + 全知不带否决（不装包装，2026-11-03 之前的参照）。
                          setup() 按它设 r1v2.ENERGY_VETO。之前全知有两个：antagonist_boss 的带否决，antagonist_preboss* / antagonist_diag
                          直接调 run_once 的不带 —— 同名不同人；现在同一开关下所有全知是同一个参照，settings() 记下实际的 references。
  PROTO_HAND     (draw)   手牌（2026-11-03 晚加的**候选**，用户问「把抽牌机制都删掉是不是更干净」；没有采用之前默认仍是 draw = 现行版本）：
                          draw = 照旧抽牌（18 张牌组、手牌 5 张、留牌、保底）；fixed = 不抽牌：每场开局和每个 END 之后，手里正好是这条命的
                          牌组里还有的每种牌各一张（FixedPile）。同一种牌一回合最多出一次；治疗照旧出过就从这条命的牌组里删掉，一条命 3 次。
                          营地还没做固定手牌：fixed 与 PROTO_CAMP=1 一起用就拒绝；与 PROTO_LOOT=1 一起用也拒绝（拿到的牌和已有的同名，
                          固定手牌里合成一张，拿牌悄悄无效）。
                          fixed 还带两条提前结束的规则，所有玩家相同（Fight.over 补丁）：
                            · 连续出闪（用户经 GPT 11-03 晚定）：连续第 DODGE_RUN_LIMIT = 6 个出了闪的回合正常结算之后，这一场还没分出胜负 → 判负；
                              某回合没出闪，连续计数清零（FixedPile.end_turn 记）。记成「连续闪避终止」，不是被打死。
                            · 回合上限（用户 11-03 晚定「统一 40 回合上限」，留作兜底）：打满 TURN_CAP = 40 个 END 还没分出胜负 → 判负
                              （与 solver.play_fight 的 cap=40 同一个数法）。
  PROTO_INCOMING (mute)   C10 v2 候选（用户决定 2，docs/antagonist_boss/12_c10_v2_design.md §5）：mute = 现行 D1（换阶段进场槽的起始值不算变化，
                          不印、不进日志）；real = 起始值与那次 END 开始时不同就是真实变化（进 slots_changed，seen 下印出；进那一行 END 日志）；
                          起点 0 什么也不做。行为在 antagonist_boss 的 _settle_phase 包装里。
  PROTO_THREAT   (plain)  C10 v2 候选（用户决定 3，12 §6）：plain = 现行（印出的攻击 = 攻击 + 怒气 + 动量档位，boss 动量下限不印）；
                          momentum = boss 纯动量阶段每个 END 之后攻击槽 = Fight._incoming()[0]（下一次 END 那一击，挡 / 闪之前）。
                          蓄力大招、地图穿透记仇不在内（D9，待用户）。行为在 antagonist_boss 的 end_turn 包装里。
  PROTO_MARKMAP  (salt)   C10 v2 候选（用户决定 4，12 §7，D13）：salt = 现行（每个 Run 按自己的 salt 一张代号表 mark-v1:{salt}）；
                          world = 一个世界一张表（内容键 world_mark_table），4 张图和 boss 共用；装 Run._roll_world 的绊线，没绑表的 Run
                          一用代号就报错（MarkTableMissing）。绑表：proto_world.bind_world / set_mark_table。
                          这三个开关都不改伤害、随机流、发牌；参与者命令行入口在非默认下拒绝开打（proto_play._cli_guard，D12），核对的进程内调用不受影响。
  PROTO_LADDER   (0)      候选（11-03 夜，用户定的惩罚阶梯「教学可以234 考试可以248 boss是2 8 死」，scripts/penalty_ladder.py v3）：
                          1 = setup() 最后（别的补丁之后、boss 层钩子之后）装 penalty_ladder.install()，teardown() 最先撤。阶梯必须在 boss 层的
                          Fight 补丁之外（penalty_ladder 的次序：先 setup_boss 再 install、先 remove 再 teardown_boss；ladder_check 核对的就是这个次序）：
                          antagonist_boss.setup_boss / teardown_boss 用 ladder_outside() 包住自己动 Fight 的那一段（进块撤掉、出块装回），
                          于是不论先调 ap.setup() 还是 setup_boss()、之后再调多少次 ap.setup()，阶梯都只装一次、总在最外层；两种撤法的次序
                          （teardown_boss → teardown，或 teardown → teardown_boss）都对。只为固定手牌设计、只在固定手牌下核对过：
                          不是 PROTO_HAND=fixed 就拒绝。settings() 另记 ladder_describe = penalty_ladder.describe()。
                          0 = 现行：不导入 penalty_ladder，也不碰手动装的阶梯（ladder_check 照旧手动 install / remove）。
  PROTO_TUNE     (none)   候选（11-03 夜，docs/antagonist_boss/11_fixed_tune_results.md 挑出、在没见过的新图上确认的 M59+WS2）：
                          m59ws2 = TUNING 覆盖 hp_momentum=(5, 9)、ward_test_start=2（= scripts/fixed_tune.py 的 CONFIGS["M59+WS2"]）。
                          m59ws2t100 = 上面再加 test_hp_pct=100（考试战敌人血 +100%；= CONFIGS["M59+WS2+T100"]；11-04 lead 选，见 docs/antagonist_boss/14_*）。
                          setup() 在 activate_registered(12) 之后、任何建图之前写（activate_registered 把 ward_test_start 改回 0、hp_momentum 不重设，
                          所以每次 setup() 都重写；全局 TUNING，建图和打的时候都是这一套，同 fixed_tune 的做法），teardown() 还原到第一次写之前的值。
                          只改敌人的数（动量怪血量区间、考试战破势的起始封印），不改抽到的机制和顺序。none = 现行（一个键不改）。
                          注意：这一套是在旧惩罚倍数下挑、下确认的（11 §5）；阶梯下要重测。
                          11-04（审查遗留）：只在固定手牌下挑过、确认过 —— 不是 PROTO_HAND=fixed 就拒绝（之前抽牌手牌下也放行）。
  PROTO_RAGE     (on)     候选（用户 11-03 夜「删掉激怒吧」= 去掉怒气，docs/antagonist_boss/13_penalty_ladder.md §4b）：
                          on = 现行（某回合一点伤害都没打出去（出闪的回合除外），敌人这一场的攻击永久 + rage）；
                          off = 没有怒气：setup() 在 activate_registered(12) 之后、任何建图之前把 TUNING rage_ratio 写成 0（activate_registered
                          会写回 20，所以每次 setup() 都重写，同 PROTO_TUNE），并给 adventure.make_enemy 包一层：rage_ratio == 0 时建出的敌人
                          rage = 0。只写 rage_ratio=0 不够：引擎 scaled() 的 floor=1，max(1, round(7 × 0 / 100)) = 1，世界 A 的敌人 rage 照样是 1
                          （与 rage_ratio=20 时 round(20% × 7) = 1 一模一样，开关会是空操作；fin 探针 2026-11-04 实测）。包装只在建出之后改 rage
                          这一个字段，不碰随机流（scaled 不抽随机数），敌人其余字段逐字相同。kernel.py 按值导入 make_enemy，不经过包装（原型不用它）。
                          teardown() 撤包装、把 rage_ratio 还原到第一次写之前的值；archived() 里是 on（存档有怒气）。
                          只为固定手牌（阶梯候选）设计、只在固定手牌下核对过：不是 PROTO_HAND=fixed 就拒绝。于是阶梯的「普通一击」就是敌人的攻击
                          （没有激怒 / 贪食时），印出的攻击只因动量而变；C10 v2 的结算项（f._incoming()[0]）也不含怒气。
                          这三个开关（LADDER / TUNE / RAGE）的参与者命令行入口在非默认下拒绝开打（proto_play._cli_guard），核对的进程内调用不受影响。
  候选 v3（11-04 晚，docs/antagonist_boss/18_candidate_v3_spec.md；默认 = 现行版本，默认下新代码什么也不做；非默认时才进 _now() / switches() /
  out_tag() / recorded()，旧记录没有这些键 = 默认；参与者命令行入口在非默认下拒绝开打，proto_play._cli_guard）：
  PROTO_POOL     (full)   nopierce = 池里去掉穿透（PROTO = PROTO_FULL 去掉 pierce，setup() 的 use_rotation(PROTO)）：图从五种里抽四种（引擎的 pool_draw，
                          同一条 pool-v1:{salt} 流，从五个里抽，所以同一个 salt 的图与六种时不同）；boss 配对必须在这五种里（build_boss / proto_world 本来就查）。
  PROTO_MOMENTUM (ramp)   noshield = 动量改成「回合末没举盾、没闪就挨普通一击 × 阶梯倍数」（18 §2）。实现在 scripts/penalty_ladder.py（本文件只登记开关、
                          核对前提：要 PROTO_LADDER=1）。
                          shieldonly（11-05 夜，18 §8.7，准备用、默认关）= noshield，但回合末只认盾：没举盾就罚，闪了也罚（闪避不躲开动量）。
                          实现在 penalty_ladder v3.8；登记同 noshield。
  PROTO_DOUBLER  (persist) turncd = 增伤只对本回合的攻击生效（END 清掉 ("me", "double")）、出过增伤的下一回合手里没有增伤（FixedPileCD；要 PROTO_HAND=fixed）。
  PROTO_GUARDCODE (engine) map = 守势格的印法每张图抽一次（normal：守相 1 / 攻相 0；flipped：守相 0 / 攻相 1；50 %，流 guard-code-v1:{key}:map:{salt}，
                          boss 用 ...:boss:{boss salt}）；引擎不变，只改参与者看到的数字（scripts/guard_slot.py 补 adventure._row 和
                          modelrun.HarnessLog.append；Run._roll_world 的包装给每个敌人记上映射的键）。第 1 回合不印（seen 画面本来如此），
                          第 2 回合起每回合都印。要 PROTO_DISPLAY=seen。setup() 最后装、teardown() 最先撤。
  候选 v3b（11-05，18 §8.1–§8.4；同样默认 = 现行版本，非默认才进 _now() 等，参与者入口拒绝）：
  PROTO_POOL=v3b          池 = 蓄力、动量、反击、守势、破势（没有穿透、没有标记）；图从五种里抽四种；boss 只登记三对有序配对 PAIRS =
                          动量 → 蓄力、反击 → 守势、守势 → 破势 —— 11-05 用户「boss 不急，先做地图」：这三对只记在 PAIRS_V3B，没登记，boss 代码路径不变。
  PROTO_COUNTER (engine)  nodouble = 同一回合攻击 + 增伤，第二张出手的当下：增伤作废 + 当下扣「普通一击 × 阶梯倍数」（盾、闪无用）；回合末是普通一击
                          （实现在 penalty_ladder v3.6；要 PROTO_LADDER=1）。
                          noblock（11-06，18 §8.8，试用、默认关）= 同一回合攻击 + 举盾，第二张出手的当下：当下扣「普通一击 × 阶梯倍数」（盾、闪无用）+
                          这一回合的盾作废（回合末那一击全吃）；攻击 + 增伤合法（实现在 penalty_ladder v3.9；登记同 nodouble）。
  PROTO_GUARDSTART (engine) map = 地图上每场守势战的开场攻守建图时预抽（按图 salt + 层 + 节点；scripts/guard_slot.py tag_starts /
                          install_start），地图对局里不再抽随机数。boss 不在内（11-05 用户：先做地图；boss 照旧用 antagonist_boss 的派生流）。
  PROTO_TUNE=m59ws2t25c   m59ws2t25 + hp_counter (5, 9)（反击怪血少一点，18 §8.2；考试战照样 +25 %）。
  PROTO_TUNE=m59ws2t25c_bp{B}w{W}  测量网格（11-05 晚，用户「盾就是要一定比对方攻击少」；21 号文档）：m59ws2t25c + block_pct=B + wear_pct=W
                          （SHIELD_TUNINGS 六个名字；抽数之后缩放，不动随机流）。只在取到这些名字时并进 TUNINGS，别的名字下 TUNINGS 逐字不变。
  PROTO_TUNE=m59ws2t25c_bp45w90_c48  候选 v3c（11-06，用户 18 §8.8 末条「反击怪血量先试 4–8 倍攻击」；28 号文档）：= m59ws2t25c_bp45w90 + hp_counter (4, 8)
                          （COUNTER_HP_TUNINGS；randint 的宽度不变 → 随机流不变，只有反击怪的血少 1 倍攻击，考试战照样 +25 %）。
                          只在取到这个名字时并进 TUNINGS，别的名字下 TUNINGS / TUNES 逐字不变。
  PROTO_LADDER_TABLE=v3b  v3 + 反击行（同守势）。boss 第二阶段第一罚 x3 不致死（penalty_ladder 决定 11）写了、默认关着（HANDOVER=False），boss 先不做。
  boss 第一版（11-06，18 §8.10，用户「可以」；docs/antagonist_boss/32_boss_v1.md；默认 none = 现行，none 下不进 _now()，输出逐字不变）：
  PROTO_BOSS (none) v1    只在完整的 v3c1 候选 + PROTO_LADDER_TABLE=v3c1b 下（表 v3c1b 也只配 v1，_validate 拒绝别的组合）：boss 守势开场攻守
                          按 boss salt 预抽（guard_slot.tag_starts 给 boss 敌人记 start_value("boss", salt)；antagonist_boss 的 D1 补丁用它，
                          boss 对局里不抽随机数）；价钱 = 表 v3c1b（boss 反击 1 不致死 / 9 / 27 / 死；换阶段第一下 反击 x1、其他 x3，都不致死）；
                          R1v2 i 版（提示之后重新开场：第一回合只举盾）；PAIRS_V3C1B = 10 对有序配对（世界 i 用第 i 对；没登记）。地图一个字节也不变
                          （v3c1b 的教学 / 考试行 = v3c1；boss 的预抽只碰 boss 敌人）。参与者入口照旧拒绝（人类入口要求恰好是 v3c1 那一套环境）。
  PROTO_LADDER_TABLE=v3   （penalty_ladder 读）不在 LEGACY_TABLES 里的表在 PROTO_LADDER=1 下进 _now() 的 ladder_table 键；文件名照旧是 -ladtab<表名> 后缀。
  休息层：登记 12 的自动补给（auto_rest=1），不是开关；setup() 核对它。
存档复现（同一组开关 = 当时的代码路径；结果文件不覆盖，见 out_tag / refuse_overwrite）：
  PROTO_LOOT=1 PROTO_NODES=route PROTO_DISPLAY=per-player PROTO_REFS=b
      2026-11-01/02 的全部结果（antagonist_proto.json、antagonist_preboss*.json、antagonist_diag.json、antagonist_momentum_probe.json、
      boss_check.json 的 C8、r1v2_smoke_b.json）。只设 r1v2.ENERGY_VETO=False 不够（b 版冒烟在固定节点下 decisions 798 对存档 750）。
  PROTO_LOOT=0 PROTO_NODES=route PROTO_DISPLAY=per-player PROTO_REFS=b
      2026-11-02 只关奖励的重跑（results/proto13/noloot.log 第一步；没有写出任何 *_noloot.json）。注意 antagonist_noloot.sh 只导出
      PROTO_LOOT=0：新默认下它跑的是现行版本，不是那次重跑 —— 所以 OUTNAME / SRCNAME 含 "noloot" 而开关不是上面这组时，导入本文件就拒绝（_guard_stale）。
  同一进程里临时回到存档设置：with archived(): ...（含参照 b；退出时回到环境变量的设置）。
  没迁移的脚本：antagonist_diag.py、antagonist_momentum_probe.py 不看开关、不查源文件开关、无条件写存档文件名 —— 作为主程序运行时
  （含其工作进程）本文件拒绝：存档文件已存在就拒绝（不覆盖），开关不是存档那组也拒绝（_guard_stale）。要用先迁移（out_tag / refuse_overwrite / check_source）。

公开接口（别的脚本靠这些名字）：
  PROTO_VERSION、PROTO、PAIRS、SEED、SALT0、ROLES、LIST、OUT、ROOT、R1_STREAM；LOOT、NODES、DISPLAY、CAMP、REFS（当前开关）；ARCHIVE；PENDING
  setup()                  登记 12 原型 + 池 + 世界 A 牌名 → 按开关装：删奖励（loot 关时）、固定节点（fixed 时）、统一画面（seen / hidden 时）、
                           参照（PROTO_REFS）→ 最后调登记过的 after-setup 钩子（boss 层登记它的 TUNING 键：activate_registered(12) 会把
                           boss_no_probe 等改回登记值 1，钩子再写回 setup_boss 的值 —— 否则任何中途的 setup() 都悄悄换掉 boss 规则）。幂等。
                           PROTO_TUNE / PROTO_RAGE=off：activate_registered 之后、任何建图之前写调参覆盖 / rage_ratio=0（+ make_enemy 包装）；
                           PROTO_LADDER=1：钩子之后最后装阶梯（已装着不再装）。
  register_after_setup(name, fn) / unregister_after_setup(name)   上面那个钩子（antagonist_boss 用）。
  teardown()               撤掉 setup() 装的全部补丁、把画面键还原到第一次 setup() 之前；不撤 activate_registered / use_rotation（同旧行为）。
                           装了 boss 层的话先 antagonist_boss.teardown_boss() 再调它（PROTO_LADDER=1 下两种次序都可以）。幂等。
                           阶梯最先撤；调参覆盖、rage_ratio 还原到第一次写之前的值，make_enemy 换回引擎原函数。
  build(salt)              建一张图的 Run（world A，SEED）。
  settings()               本进程的版本与开关 + references（R1v2 版本、全知否决实际开没开、装在哪些路径）；写进每个输出文件的 "proto" 键。
  switches()               settings() 去掉 references（只有开关；建 boss 之后核对用：references 跟着模块旗子变，C15 这类核对会临时切换）。
  oracle_veto_on(flag=None) 全知这一条命用不用 N5 否决：flag > antagonist_boss.ORACLE_VETO（已载入且不是 None）> r1v2.ENERGY_VETO。
  no_heal_veto(f)          显式的「不否决」（行为同 heal_veto=None）：要关掉全知否决的调用方传它，免得 play_fight 的包装再接上默认否决。
  live_route(route) / habit_key(item) / blind_key(pair) / panel_classes()
                           现行版本下冻结面板的重复（审查 2026-11-03）：没奖励、固定节点、自动补给后，路线只剩 heal_at、enrage_budget 两个字段
                           还影响对局（其余 elite_at、take、take_glut、reward、rest_mode、cleanse_at、cap_safe_at 都走不到，读码见 live_route），
                           17 条路线 → 2 种，526 套习惯 → 211 种行为，1,700 对盲线 → 200 种。凡是「习惯 ≥ x 的有几套」、逐套表格、多重比较校正，
                           都要按 panel_classes() 的类数，不按条目数；面板最大值不受影响。
  core_manifest()          core/ 下全部文件（含 test_*、gui 资源、prereg；不含 __pycache__）的 sha256 清单 —— 登记指纹只盖 core/*.py 非 test。
  fixed_node(run, i)       第 i 层（run.layers 的 0 起下标）固定打的节点下标；PROTO_NODES=route 时 None（由玩家 / 路线选）。
  fixed_fight(run, i)      run.fight_at(i, fixed_node(run, i))。
  display()                当前画面模式字符串："seen" / "hidden" / "per-player"。
  display_settings(who)    这个玩家该用的 TUNING 画面键（统一模式下与 who 无关）；who ∈ WHO_DISPLAY。
  apply_display(who=None)  把 display_settings(who) 写进 TUNING，返回被覆盖的旧值（调用方还原用）。setup() 已在统一模式下调过一次（who=None）。
  using_display(who=None)  上面那个的 with 版本，退出时还原。
  tracks_screen(who)       这个玩家要不要人的 `?` 规则追踪（Fight.track_seen）；screen(who, record) 按它包一层记录器。
  camp()                   参与者入口打不打营地（PROTO_CAMP）。
  recorded(src) / check_source(src)   输入文件记下的开关 / 与本进程开关不一致就报错（旧文件没有 "proto" 键 = ARCHIVE，loot 读旧的 "loot" 键）。
  out_tag() / refuse_overwrite(path)  输出文件名后缀（存档设置 = ""，否则 "_v2…"）/ 已存在就拒绝写（不改已有结果）。
  archived()               with 版本：本进程临时换成 ARCHIVE 的开关。
  switched(**kw)           核对专用的 with 版本：进程内临时换 incoming / threat / markmap（别的开关不许），退出时还原。
  候选 v3：POOL、MOMENTUM、DOUBLER、GUARDCODE、LADDER_TABLE；PROTO_FULL、POOL_MECHS、V3_DEFAULTS、V3_KEYS、V3_RULES、LEGACY_TABLES；
  WORLD（11-07，PROTO_WORLD：世界外衣 A / k{键}，scripts/proto_worlds.py；43 号文档。默认 A = 什么也不写；非默认时 setup() 在调参之后写外衣，
           进 _now() / settings()（v3_rules.world_surface）/ 文件名后缀；只配完整的候选 v3c1）
           v3_now()（偏离默认的 v3 开关）、default_of(k)（任一开关键的默认值）、FixedPileCD
  INCOMING、THREAT、MARKMAP（当前的候选开关）；DECIDED_NOT_ADOPTED（用户已定、未采用；不进 settings()，PENDING 一字未改）
  LADDER、TUNE（11-03 夜的两个候选开关）；TUNINGS（PROTO_TUNE 的值 → TUNING 覆盖）；RAGE（11-04，PROTO_RAGE：on / off）
  ladder_outside(reinstall)  PROTO_LADDER=1 时 antagonist_boss 用：块里撤掉本模块装的阶梯、块里的 setup() 不装；出块时 "switch" = 按开关装，
                           "if-lifted" = 进块时撤过才装回。默认（0）什么也不做。
  salt_mark_table(salt) / world_mark_stream(map_salts, boss_salt, order) / world_mark_table(...)   按 salt / 按世界（D13 内容键）的代号表
  set_mark_table(run, table, source) / require_mark_table(run) / mark_record(run, salt) / MarkTableMissing   world 下绑表、开打前核对、记录

删奖励（PROTO_LOOT=0）装了什么 —— 每一条给脚本玩家发牌 / 发属性的路径：
  · solver.run_once 包一层：take_policy 一律是「不拿」（显式传别的 take_policy 直接报错）。
  · adventure.pays_milestone → 恒 False：run_once 不再走里程碑分支（不调 apply_reward）；里程碑与否对谁都没有影响。
    modelrun / playrun / playadv 是按值导入的，不受这条影响（它们有自己的提示，见下）。
  · Run.apply_reward、Run.take → 报错（原先是悄悄的空操作：模型入口照样问 `Choose one:` / `You may take one card:`，日志写 took X 而牌组没变）。
    还在问这两个提示的参与者入口会在第一次真拿的时候停下来，不会悄悄骗参与者；参与者入口本来就不该问（N6）。
  · Run._fight 绊线：开打前牌组必须是起始 18 张的子多重集（治疗出过会删），否则报错 —— 兜住 mapdp / contrast / tune 那种直接
    run.deck_list.append 的路径（原型脚本都不用它们）。
固定节点（PROTO_NODES=fixed）装了什么：Run.choose 在战斗层直接返回 fixed_node；休息层照旧（自动补给）。run_once 仍照常先分好 node_seeds，
  随机流不动，只是不再用它挑节点；route.elite_at 从此不影响打哪一场（curriculum=4 下本来也没有精英节点），heal_at 照旧。
统一画面（PROTO_DISPLAY=seen/hidden）：setup() 把 marks=0、state_slots=模式写进 TUNING，同进程里的模型 / 人类入口（modelrun 读 TUNING）也就是这个画面；
  人类图形界面在子进程（gui_bridge.run_worker）里跑，要在 worker 里调 setup()（未做，见 N6）。marks 不是画面而是「免费认怪」的签名
  （core/solver.py:1036），统一置 0：对 know=NONE 的习惯 / 盲线和 information="oracle" 的全知没有作用，对 R1 / R1v2 本来就是 0。
  脚本读画面只读怪方状态行（cautious.them_slots）；seen 模式下那一行与 `?` 追踪无关（变过的槽印真值，非零起始的槽构造时已记入 seen），
  所以 track_seen 只在 hidden 下影响脚本（蓄力印 `?`）；统一模式下读画面的玩家一律打开它（screen()），与人看到的一样。
  hidden 的已知缺口（不归本文件）：regsel.r1_wins、r1v2.display()、antagonist_diag 自己写死 R1_DISPLAY（seen），R1v2 还断言 seen。
参照（PROTO_REFS=c）装了什么：solver.play_fight 包一层 —— information == "oracle" 且 act_policy、blind、heal_veto 都是 None 的那场（全知，
  以及去掉部分知识的全知变体）接上 r1v2.oracle_heal_veto(know, kinds, enrage_budget, offence_cap, dodge_hand)（与 antagonist_boss 显式接的
  同一条规则、同一组参数）；oracle_veto_on() 为假时不接。显式传了 heal_veto 的（antagonist_boss、R1、R1v2、核对用的 no_heal_veto）原样放过。
  习惯 / 盲线 / R1 / R1v2 都带 act_policy 或 blind，从不经过这一条（C15 的核对）。
固定手牌（PROTO_HAND=fixed）装了什么：adventure.Pile → FixedPile（引擎的 Fight 按模块全局名建牌堆，所以每一条路径 —— 脚本参照、习惯、盲线、
  模型、人 —— 都拿到同一种手牌）。手牌 = 这条命的牌组（Run.deck_list 那个对象本身）里还有的每种牌各一张，按牌名字母序（原型只跑世界 A、names_key 0，
  所有图和 boss 的牌名相同，所以顺序处处相同：doln 盾、kel 治疗、mira 增伤、tsun 闪、vorth 攻击 —— 位置不比牌名多透露什么；多世界时牌名才重抽）；没有抽牌堆、弃牌堆，不洗牌，不碰随机数（于是这一场的随机流只剩守相起点、标记抽签）。补闪（charge_returns_dodge）、
  诱饵（pierce_returns_block）、开局 / boss 的保底在固定手牌下找不到可挪的牌，什么也不做；规则旋钮一个不改。
  闪一直在手里，闪掉的回合又不算停顿，「每回合都出闪」永远不挨打也永远打不完（hand_fixed_check H5 证实）。用户 11-03 晚定：所有玩家一场
  最多 40 回合，到了算输 —— Fight.over 补丁：第 TURN_CAP 个 END 之后还没分出胜负，over() 为真（won() 本来就为假：双方都活着）。
  Fight.turn 每场从 1 起、只在 end_turn 末尾加一，所以 turn - 1 = 这一场已经结束的回合数；solver.play_fight 的 `turns < cap` 数的是同一个数。
  boss 是一场（两个阶段合起来 40 回合），同脚本。参与者入口给参与者的那一句规则和到上限时的日志行还没写（要用户看英文措辞）：
  在那之前 proto_play 的命令行入口（model / human / gui）在 fixed 下拒绝开打；核对用的进程内调用不受影响。
发牌（N6 之后的已知混淆，审查 2026-11-03，不改）：参与者的一个世界打的是每张图 / boss 的**结构洗牌**（run.shuffles，同一世界所有参与者、
  所有记忆臂同一副牌）；脚本参照默认每条命从 solver._trial_rng 抽新牌（对随机发牌取平均）。世界级的「模型对尺子」比较因此混着那一副牌的运气；
  antagonist_boss.play_map / play_boss 的 deal="structural" 让尺子打参与者那一副牌（C12 用它）。另：solver.play_fight 的 40 回合上限只管脚本，
  参与者入口没有上限（到上限算输，决定结局；C12 把它算作分歧）。

待用户定、本版不动的规则（PENDING）：momentum_boss_frac；标记代号映射按 salt 还是按世界；穿透探针价 / 第一次接触致死；守势换阶段第一回合；
  换阶段保底发牌；charge_returns_dodge；big_lethal；boss_punish_pct；宽限期 boss_switch_grace；原型世界有没有营地（PROTO_CAMP 默认关）。
待定的参照决定（PENDING_REFS）：N5 的治疗否决（R1v2 c、全知）—— 用户 2026-11-03 定：c 登记为候选新版（看过 C10 之后加的，不算事先冻结），b 保留；
  主参照待新图、新随机流验证（04_r1v2_spec.md §10、§11，方案未冻结、未跑）。之前两者都不是主参照；PROTO_REFS=c 只是代码默认，b = PROTO_REFS=b。

== 历史：2026-11-01 第一轮验证（用户批准「ok验证」）==
步骤：扫 salt → 两轮图 → R1（登记 12 的懂规则参照，n=200，ev 流）≥ 0.90 才收，凑满 N_PASS 张 →
      冻结清单 526 套打法 × PACKRUNS 条单命（select 流）逐图跑，记每套的通关数 → results/proto13/antagonist_proto.json（存档设置）。
用法：N_PASS=60 SCAN_CAP=400 PACKRUNS=200 WORKERS=6 python3 -B scripts/antagonist_proto.py（输出名带 out_tag()，已有文件不覆盖）"""
import collections, contextlib, datetime, functools, hashlib, inspect, json, os, pathlib, sys
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
PROTO_FULL = ("charge", "pierce", "momentum", "guard", "mark", "ward")
# 候选 v3（docs/antagonist_boss/18_candidate_v3_spec.md §1）：PROTO_POOL=nopierce 时池里没有穿透（顺序同 PROTO_FULL 去掉 pierce）。
# PROTO 跟着开关（导入时定；archived() 里临时换回 PROTO_FULL）；默认 full 下 PROTO 就是原来那个 tuple。
POOL_MECHS = dict(full=PROTO_FULL, nopierce=tuple(m for m in PROTO_FULL if m != "pierce"),
                  v3b=("charge", "momentum", "counter", "guard", "ward"))   # 候选 v3b（18 §8.1）：标记、穿透拿出，反击拿回来（次序同引擎 BEHAVIOURS 的相对次序）
POOL = os.environ.get("PROTO_POOL", "full")
PROTO = POOL_MECHS.get(POOL, PROTO_FULL)
PAIRS_FULL = (("pierce", "momentum"), ("guard", "ward"), ("charge", "mark"))
# 候选 v3b（18 §8.4，用户「可以」）：boss 三对，有序（第一阶段 → 第二阶段）：第一阶段养成的习惯在第二阶段挨罚。
PAIRS_V3B = (("momentum", "charge"), ("counter", "guard"), ("guard", "ward"))
# boss 第一版（18 §8.10，用户 11-06「可以」；PROTO_BOSS=v1，docs/antagonist_boss/32_boss_v1.md）：10 对不同的有序配对（第一阶段 → 第二阶段），
# 世界 i（~/agii_runs/v3c1_pack/pack_v3c1_v1.json 的第 i 个）用第 i 对（lead 的分配）。只记在这里给 boss 第一版的筛选用，没登记（PAIRS 照旧）。
PAIRS_V3C1B = (("momentum", "counter"), ("momentum", "guard"), ("momentum", "charge"), ("counter", "momentum"), ("guard", "ward"),
               ("charge", "ward"), ("ward", "charge"), ("ward", "guard"), ("counter", "guard"), ("charge", "counter"))
PAIRS = PAIRS_FULL   # 11-05 用户：boss 不急，先做地图 —— v3b 的三对（PAIRS_V3B）只记在这里，没登记（boss 代码路径不变；v3b 池下 PAIRS 里的穿透 / 标记对不在池里）
SEED = 9065; SALT0 = int(os.environ.get("SALT0", 2000000))
N_PASS = int(os.environ.get("N_PASS", 60)); SCAN_CAP = int(os.environ.get("SCAN_CAP", 400))
PACKRUNS = int(os.environ.get("PACKRUNS", 200)); WORKERS = int(os.environ.get("WORKERS", 6)); CHUNK = 25
R1_N = 200; R1_MIN = 0.90; R1_STREAM = "ev"
OUT = ROOT / "results" / "proto13"
LIST = ROOT / "results" / "sweeps" / "fixed_panel_list.json"
ROLES = ("charge", "guard", "mark", "mimic", "ward")

# ---------------------------------------------------------------- 版本与开关
PROTO_VERSION = "proto13-v2-2026-11-03"
VERSION_TAG = "v2"
NODE_RULE = "index0"            # 见 fixed_node
DISPLAYS = ("seen", "hidden", "per-player")
LOOT = os.environ.get("PROTO_LOOT", "0") != "0"          # 2026-11-03 起默认关（之前默认 "1"）
NODES = os.environ.get("PROTO_NODES", "fixed")
DISPLAY = os.environ.get("PROTO_DISPLAY", "seen")
CAMP = os.environ.get("PROTO_CAMP", "0") != "0"
REFS = os.environ.get("PROTO_REFS", "c")
REFS_ALL = ("c", "b")
HAND = os.environ.get("PROTO_HAND", "draw")
HANDS = ("draw", "fixed")
TURN_CAP_ENV = os.environ.get("PROTO_TURNCAP", "40")
if TURN_CAP_ENV not in ("30", "40"):
    raise ValueError(f"PROTO_TURNCAP={TURN_CAP_ENV!r}: expected 30 or 40")
TURN_CAP = int(TURN_CAP_ENV)     # 默认40保持旧记录；hard5唯一规则差异为30个END
DODGE_RUN_LIMIT = 6             # PROTO_HAND=fixed：连续第 6 个出闪的回合正常结算后仍没分出胜负就判负（用户经 GPT 11-03 晚定；不加闪避冷却）
# C10 v2 的三个候选开关（docs/antagonist_boss/12_c10_v2_design.md §3–§7；用户决定 2、3、4，10 §6）。默认 = 现行版本（mute / plain / salt），
# 默认下新代码什么也不做；采用之前参与者命令行入口在非默认下拒绝开打（proto_play._cli_guard，D12）。
INCOMING = os.environ.get("PROTO_INCOMING", "mute"); INCOMINGS = ("mute", "real")
THREAT = os.environ.get("PROTO_THREAT", "plain"); THREATS = ("plain", "momentum")
MARKMAP = os.environ.get("PROTO_MARKMAP", "salt"); MARKMAPS = ("salt", "world")
MARK_WORLD_STREAM = "mark-world-v1"
# 11-03 夜的两个候选开关（惩罚阶梯 scripts/penalty_ladder.py；调参 M59+WS2，docs/antagonist_boss/11_fixed_tune_results.md）。默认 = 现行版本
# （0 / none）：默认下不导入 penalty_ladder、TUNING 一个键也不改；采用之前参与者命令行入口在非默认下拒绝开打（proto_play._cli_guard）。
LADDER_ENV = os.environ.get("PROTO_LADDER", "0"); LADDERS = ("0", "1")
LADDER = LADDER_ENV == "1"
TUNE = os.environ.get("PROTO_TUNE", "none")
TUNINGS = dict(none={}, m59ws2=dict(hp_momentum=(5, 9), ward_test_start=2),   # = scripts/fixed_tune.py CONFIGS["M59+WS2"]（candidate_check 核对两者相同）
               m59ws2t100=dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=100),   # 11-04 lead（用户授权「你自己想办法解决」）：阶梯下考试战太短，
               # 加长考试战（只加考试战敌人的血 +100%，教学战不动）；= scripts/fixed_tune.py CONFIGS["M59+WS2+T100"]，fixed_tune2 筛选按事先写定的挑法选出
               m59ws2t25=dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=25),     # 11-04 上午用户「少加然后配合倍数」：+25% / +50%
               m59ws2t50=dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=50),     # （= CONFIGS["M59+WS2+T25"] / ["M59+WS2+T50"]）
               # 候选 v3b（18 §8.2，lead 的默认）：反击怪血 (6, 10) → (5, 9) 倍攻击（同动量）；其余同 m59ws2t25（考试战照样 +25 %）
               m59ws2t25c=dict(hp_momentum=(5, 9), ward_test_start=2, test_hp_pct=25, hp_counter=(5, 9)))
# 11-05 晚（用户：「盾就是要一定比对方攻击少」，docs/antagonist_boss/21_shield_below_attack_sweep.md）：盾低于怪的普通一击的测量网格。
# = m59ws2t25c + TUNING block_pct（盾 = 攻击 × 160 % × block_pct %，camp.make_deck 抽完治疗之后缩放）+ wear_pct（怪攻击 × wear_pct %，adventure._worn
# 抽完之后缩放）。两个都在抽数之后，不动随机流（同一批图）。wear_pct 也按比例缩放阶梯罚（普通一击 × 倍数）；block_pct 不碰罚。
# 只在 PROTO_TUNE 取到其中一个名字时并进 TUNINGS：其余名字下 TUNINGS / TUNES 与之前逐字相同（candidate_check 把整张 TUNINGS 写进输出）。
# 测量用（scripts/shield_sweep.py 核对每一场地图战 怪攻击 > 盾），不是候选；名字 = bp{block_pct}w{wear_pct}。
SHIELD_TUNINGS = {f"m59ws2t25c_bp{bp}w{w}": dict(TUNINGS["m59ws2t25c"], block_pct=bp, wear_pct=w)
                  for bp, w in ((27, 50), (45, 80), (36, 70), (45, 90), (55, 100), (36, 90))}
if TUNE in SHIELD_TUNINGS:
    TUNINGS[TUNE] = SHIELD_TUNINGS[TUNE]
# 11-06（用户 18 §8.8 末条：采用 PROTO_COUNTER=noblock，「反击怪血量先试 4–8 倍攻击（原 5–9），实测 D 再定」；28 号文档，候选 v3c）：
# = m59ws2t25c_bp45w90 + hp_counter (4, 8)。make_enemy 抽 rng.randint(*hp_counter)：(4, 8) 与 (5, 9) 宽度相同，抽数逐位相同，结果正好小 1
# → 同一批图、同样的名字 / 攻击 / 别的怪的血，只有反击怪的血少 1 倍攻击（考试战照样 +25 %，取整）。不进 SHIELD_TUNINGS（shield_sweep 的网格不变）。
# 只在 PROTO_TUNE 取到这个名字时并进 TUNINGS：其余名字下 TUNINGS / TUNES 与之前逐字相同。
COUNTER_HP_TUNINGS = {"m59ws2t25c_bp45w90_c48": dict(SHIELD_TUNINGS["m59ws2t25c_bp45w90"], hp_counter=(4, 8))}
if TUNE in COUNTER_HP_TUNINGS:
    TUNINGS[TUNE] = COUNTER_HP_TUNINGS[TUNE]
TUNES = tuple(TUNINGS)
# 11-04（用户 11-03 夜：去掉怒气，13 §4b）：PROTO_RAGE。默认 on = 现行版本：默认下不改 TUNING、不包 make_enemy。
RAGE = os.environ.get("PROTO_RAGE", "on"); RAGES = ("on", "off")
# 候选 v3（11-04 晚，docs/antagonist_boss/18_candidate_v3_spec.md；用户「试试吧」）的开关。默认 = 现行版本，默认下新代码什么也不做、
# _now() / switches() / out_tag() / recorded() 一个键也不加（旧记录没有这些键 = 默认）；采用之前参与者命令行入口拒绝开打（proto_play._cli_guard）。
#   PROTO_POOL      full / nopierce   §1：地图和 boss 都不抽穿透（use_rotation(PROTO)，五种里抽四种）
#   PROTO_MOMENTUM  ramp / noshield   §2：动量 = 回合末没举盾、没闪就挨普通一击 x 阶梯倍数（实现在 penalty_ladder，本文件只登记、核对前提）
#   PROTO_DOUBLER   persist / turncd  §4：增伤只对本回合的攻击生效（END 清掉），出过增伤的下一回合手里没有增伤（FixedPileCD）
#   PROTO_GUARDCODE engine / map      §2 守势：守相印 1 / 攻相印 0（normal）或反过来（flipped），每张图按 salt 抽一次、boss 按 boss salt
#                                     （scripts/guard_slot.py；画面、日志的守势那一格按映射印，引擎不变）
#   PROTO_LADDER_TABLE=v3             penalty_ladder 读的表名；v3（及以后不在 LEGACY_TABLES 里的表）在 PROTO_LADDER=1 下也进 _now() 的 ladder_table
#                                     键（旧表 t16 / u1104 / u1104b 照旧只在 out_tag 的 -ladtab 后缀和 ladder_rule 里，现有文件名、记录逐字不变）
MOMENTUM = {"streak": "ramp"}.get(os.environ.get("PROTO_MOMENTUM", "ramp"), os.environ.get("PROTO_MOMENTUM", "ramp"))   # penalty_ladder 把默认叫 streak（同一个东西）：两个名字都读成 ramp
MOMENTUMS = ("ramp", "noshield", "shieldonly")   # shieldonly：18 §8.7（penalty_ladder v3.8）
DOUBLER = os.environ.get("PROTO_DOUBLER", "persist"); DOUBLERS = ("persist", "turncd")
GUARDCODE = os.environ.get("PROTO_GUARDCODE", "engine"); GUARDCODES = ("engine", "map")
POOLS = tuple(POOL_MECHS)
COUNTER = os.environ.get("PROTO_COUNTER", "engine"); COUNTERS = ("engine", "nodouble", "noblock")   # 候选 v3b（18 §8.2–§8.3；实现在 penalty_ladder v3.6）；noblock：18 §8.8（v3.9，试用）
GUARDSTART = os.environ.get("PROTO_GUARDSTART", "engine"); GUARDSTARTS = ("engine", "map")   # 候选 v3b（18 §8.4；scripts/guard_slot.py）
LADDER_TABLE = os.environ.get("PROTO_LADDER_TABLE", "v1")
BOSS = os.environ.get("PROTO_BOSS", "none"); BOSSES = ("none", "v1")   # boss 第一版（18 §8.10；32 号文档）：none = 现行（boss 守势开场照旧按每条命的派生流）
# boss 第二版的两个旋钮（11-06，用户「boss 可以延长」→ lead 的网格；docs/antagonist_boss/33_boss_v2_hp.md）。只配 PROTO_BOSS=v1；默认 100 / none = boss 第一版，
# 默认下不进 _now()、什么也不装，输出逐字不变。
#   PROTO_BOSS_HP      100 / 150 / 200 / 250：boss 总血 = 引擎原式 round(两段抽出的血之和 x pct / 100)（TUNING boss_switch_hp_pct；抽数之后，不动随机流），
#                      换阶段线照旧 floor(总血 x 50 / 100)；antagonist_boss.setup_boss 写这个键。
#   PROTO_BOSS_TURNCAP none / 60：boss 这一场的回合上限（图照旧 TURN_CAP = 40）。antagonist_boss.build_boss 给 boss 敌人记 _turn_cap；Fight.over 补丁、ended_by、
#                      solver.play_fight 的 cap（没显式传 cap 的调用）都按它。参与者不被告知（同 40）。
BOSS_HP = os.environ.get("PROTO_BOSS_HP", "100"); BOSS_HPS = ("100", "125", "150", "175", "200", "225", "250", "300", "350", "400")   # 225：第八版 b（39 号文档 §10）   # 300–400：第七版的网格（38 号文档）；125 / 175：第八版（39 号文档）
BOSS_TURNCAP = os.environ.get("PROTO_BOSS_TURNCAP", "none"); BOSS_TURNCAPS = ("none", "60", "45")   # 45：boss 第八版（39 号文档）
# boss 第八版（11-07，用户「boss控制在30回合左右就可以」；docs/antagonist_boss/39_boss_v8.md）：
#   PROTO_BOSS_ATK  100 / 125 / 150 / 175 / 200：boss 敌人的基础攻击（普通一击的底数；蓄力大招、反击 / 动量 / 蓄力的阶梯罚都从它来）乘这个百分数，
#                   取整 = floor(atk x pct / 100 + 0.5)，至少 1；建 boss 之后改（不动随机流）；图不变。守势的罚是自己攻击的反弹，不从它来，不乘。
BOSS_ATK = os.environ.get("PROTO_BOSS_ATK", "100"); BOSS_ATKS = ("100", "125", "150", "175", "200")
BOSS_ATKS += tuple(str(x) for x in range(105, 200, 5) if x % 25)   # 43 号文档 §11（修订 2，11-07）：网格加密，105–195 每 5 一档（只放开取值）
# 世界外衣（11-07，用户「八个吧」；docs/antagonist_boss/43_eight_world_pack.md）：PROTO_WORLD = A（默认：身份 0、names_key 0、原型的经济；什么也不写，
# 不进 _now()，输出逐字不变）或 scripts/proto_worlds.SURFACES 里的 k{键}（身份键、牌名、life_in_hits、rest_pct、盾）。只配完整的候选 v3c1（图）/ v3c1b（boss）。
WORLD = os.environ.get("PROTO_WORLD", "A")
# 修订 6（11-09，用户「也去掉」「直接加血比较好」；43 §19）：PROTO_HEAL = on（默认：现行，不进 _now()、什么也不装，输出逐字不变）/ off：
#   每条命牌组里治疗 0 张（TUNING deck_counts heal = 0；牌表里仍有这种牌，core modelrun 按用途找得到）→ 手里、营地、boss 都没有，谁都打不出来；
#   可用血量 B 按牌组算，自然不含治疗；上限血 M′ = M + 3h（按世界顺序让路满足 D1 / D3）、补给比例 r′（每次补给不超过原来），见 proto_worlds.healoff。
#   只配完整的候选 v3c1（图）/ v3c1b（boss），且只配包 v6 的 8 个表层。
HEAL = os.environ.get("PROTO_HEAL", "on"); HEALS = ("on", "off")
# 画面减项（11-11，用户「先去掉 A7」「把现在用不着的最大血量给删掉」）：PROTO_HIDE = none（默认：旧画面，不进 _now()，输出逐字不变）/
#   a7cap：本回合进攻次数（me.offence，v7 里没有规则读它）和上限血（me.cap，没有治疗后永远不变）不上画面——状态行、变化行、对应表都不出现。
#   只改画面（TUNING hidden_props），规则一个字不变；记录的 proto 里带 hide，审计按它重放。
#   a7capatk（11-11，用户同意）：再加双方攻击力（me.atk、them.atk）。两个都不变、按「变了才印」永远是 ?；敌方攻击力还随机制分布（世界 1：
#   攻击 9 的 14 场里封印 6 场），直接印出来就是身份线索，所以删而不印。
HIDE = os.environ.get("PROTO_HIDE", "none")
HIDES = {"none": (), "a7cap": (("me", "offence"), ("me", "cap")),
         "a7capatk": (("me", "offence"), ("me", "cap"), ("me", "atk"), ("them", "atk"))}
# 工作便签（11-11，用户「你来做」；scripts/work_note.py）：PROTO_WORKNOTE = off（默认：不装，输出逐字不变）/ on：每次选动作可写一张
#   至多 200 token 的工作便签（11-11 由 100 改 200），整场可见、场末清空，写笔记时只附最后一版。只改参与者文字与记录，规则一个字不变。
WORKNOTE = os.environ.get("PROTO_WORKNOTE", "off"); WORKNOTES = ("off", "on")
# 封印格显示（11-11，用户「ok你改吧」）：PROTO_WARDSEEN = changed（默认：旧画面，变过才印，不进 _now()）/ acted：封印第一次挡掉攻击时
#   就上画面、此后一直印（教学场起始 = 上限 = 1，一直攻击时数值不变，旧画面永远看不到它）。只改画面，规则一个字不变。
WARDSEEN = os.environ.get("PROTO_WARDSEEN", "changed"); WARDSEENS = ("changed", "acted")
# 破势解法（11-11，用户）：PROTO_WARDSTRICT = any（默认：原规则，没出攻击且盾挡住即降封印）/ blockonly：这一回合只出盾牌才降封印，
#   加成+盾不算（封印不动）。改规则；默认下不进 _now()，输出逐字不变。尚未过三道门。
WARDSTRICT = os.environ.get("PROTO_WARDSTRICT", "any"); WARDSTRICTS = ("any", "blockonly")
# 世界里的 boss 命（11-12，用户「先把之前世界的 boss 去掉吧，意义不大」）：PROTO_BOSSLIFE = on（默认：boss 世界第 1–5 条命，第 5 条命打 boss）
#   / off：boss 世界也只打第 1–4 条命（4 张图），信在第 4 条命后写。图、规则一个字不变；默认下不进 _now()，输出逐字不变。
BOSSLIFE = os.environ.get("PROTO_BOSSLIFE", "on"); BOSSLIFES = ("on", "off")
# 跨世界对应表（11-12，用户「那就什么都不说」）：PROTO_CORRESPOND = on（默认：世界 2 起，记忆、命笔记、信的材料里附上一个世界与这个世界的
#   牌名 / 状态标签对应表）/ off：不附，也不加任何替代的话（参与者凭自己的经验重新认牌；学得多快就是迁移的效率）。规则一个字不变；默认下不进 _now()。
CORRESPOND = os.environ.get("PROTO_CORRESPOND", "on"); CORRESPONDS = ("on", "off")
# 普通图考试关的不规则节奏（11-12，用户「只有蓄力怪的考试关有 len234 这样不等长，然后 0/1 节奏怪是有 irr50」；候选，未定）。只挂在考试关
#   （role == "test"）的节点敌人上，教学关照旧；表按「图 salt + 层 + 节点」预抽（antagonist_boss.map_charge_lengths / map_guard_schedule），
#   同一张图人人相同，图仍完全确定；画面照旧印蓄力格 / 守势格。默认下都不进 _now()。
#   PROTO_MAPCHARGE none / len234：蓄力怪的考试关同 boss 第七版：大招后印 1，在 1 上多停 0 / 1 / 2 回合（各 1/3），两次大招隔 2 / 3 / 4 回合，
#                   不再印 0。前两次大招恰好落在固定节奏的第 3、6 回合的表换流重抽。
#   PROTO_MAPGUARD  none / irr50 / irr67：守势怪（0/1 两相）的考试关同 boss 第四版：每个 END 以 p 翻相（不再每个 END 必翻），同一相位最多 3 个回合。
#                   前 3 个 END 恰好每次都翻（看不出不规则）的表换流重抽。
MAPCHARGE = os.environ.get("PROTO_MAPCHARGE", "none"); MAPCHARGES = ("none", "len234")
MAPGUARD = os.environ.get("PROTO_MAPGUARD", "none"); MAPGUARDS = ("none", "irr50", "irr67")
# 封印时限（11-12，用户「把 ward 改成五个回合破不了就死」；只用于 v8，默认 off 下不进 _now()、什么也不改）：
#   PROTO_WARDLIMIT off / N（1–40）：有封印的一场里，连续 N 个回合「回合开始时封着、END 之后仍封着」→ 这一场判负（ended_by = "ward_limit"，
#   双方都活着）。封印降到 0 或开着的回合把计数清零；窗口关上重新封住后从 0 重数。参与者看到的只有「(fight lost)」（用户 11-12：只说输了，不给原因）。
#   计数挂在固定手牌的牌堆上（同连续闪避），要 PROTO_HAND=fixed、PROTO_DOUBLER=turncd（牌堆认得自己的 Fight）。
WARDLIMIT = os.environ.get("PROTO_WARDLIMIT", "off")
WARDLIMITS = ("off",) + tuple(str(n) for n in range(1, 41))
WARD_LIMIT_LOSS = "(fight lost)"
# Only test-fight seal start is overridden; the default preserves old records.
WARDTESTSTART = os.environ.get("PROTO_WARDTESTSTART", "default")
WARDTESTSTARTS = ("default", "1", "2", "3")
# 休息补给按图收紧（11-13，用户「我要收紧」：懂规则不优化也能过 → 收紧血量预算）。PROTO_RESTAMT off（默认 = 原样，什么也不装）/ 表名 NAME：
#   读 ~/agii_runs/restamt/NAME.json 的 "amounts" {salt: 每次补多少血}；自动补给变成 hp += 这张图的固定量（封顶上限血），不再是上限血 × rest_pct%。
#   只动补给，不动上限血（大招等伤害按上限血算，降上限会连伤害一起降）。表里没有这张图 → 拒绝。已接：真人入口 --tier hard3（scripts/hard3_rules.py）、审计；模型启动器未接。
RESTAMT = os.environ.get("PROTO_RESTAMT", "off")
RESTAMT_DIR = ROOT / "data/restamt"
_RESTAMT_TABLE = {}
# boss 第四版（11-06，用户「好主意试试」；docs/antagonist_boss/35_boss_v4_irregular.md）：只配 PROTO_BOSS=v1，只动 boss（图一个字节也不变）；默认 = 现行，
# 默认下不进 _now()、什么也不装，输出逐字不变。
#   PROTO_GUARDSEQ  none / irr50 / irr67：boss 的守势不再每个 END 必翻：第 t 个 END 翻不翻按建 boss 时从 boss salt 预抽的表（每个 END 翻的概率 p），
#                   连着同一相位最多 3 个回合（连着两次不翻之后下一次必翻）；画面照旧（第 2 回合起每回合印，编码同前）。
#   PROTO_CHARGESEQ none / irr25 / irr50：boss 的蓄力在开头是 0 或 1 的 END 上按预抽的表停一次（不涨，概率 q）；开头是 2 的 END 照旧放大招；
#                   最多连停一次。
#   PROTO_BOSS_CUE  on / off：off = 换阶段不出提示（TUNING boss_switch_hint = 0，没有 "The enemy has changed." 那一行）。
#   PROTO_BOSS_HANDOVER v1 / x1：x1 = 换阶段之后第二阶段机制的第一次罚一律 x1 不致死（表 v3c1b 的换阶段格；v1 = 反击 x1、其他 x3）。
GUARDSEQ = os.environ.get("PROTO_GUARDSEQ", "none"); GUARDSEQS = ("none", "irr50", "irr67")
CHARGESEQ = os.environ.get("PROTO_CHARGESEQ", "none"); CHARGESEQS = ("none", "irr25", "irr50", "len234")
# boss 第七版（11-07，用户「蓄力改成1,1,1,2这样与1,2和1,1,2这样不等长的」；docs/antagonist_boss/38_boss_v7.md）：
#   PROTO_CHARGESEQ=len234  boss 的蓄力：大招之后（和蓄力阶段开头）计数印 1，在 1 上再停 0 / 1 / 2 个回合（各 1/3，建 boss 时按 boss salt 预抽），
#                           然后印 2，印 2 的那一回合 END 放大招（同前）。两次大招之间 2 / 3 / 4 个回合；不再印 0。
#   PROTO_BOSS_GUARDIN=now  boss 第二阶段进场的守势格在换阶段之后的第一个画面就印（不等它第一次翻动）；quiet = 现行。
BOSS_GUARDIN = os.environ.get("PROTO_BOSS_GUARDIN", "quiet"); BOSS_GUARDINS = ("quiet", "now")
BOSS_CUE = os.environ.get("PROTO_BOSS_CUE", "on"); BOSS_CUES = ("on", "off", "bytype")
BOSS_HANDOVER = os.environ.get("PROTO_BOSS_HANDOVER", "v1"); BOSS_HANDOVERS = ("v1", "x1", "x1m2")
# boss 第五版（11-06，用户「对消失就行」「那也可以同时有无槽位，但这种情况下要语言提示」；docs/antagonist_boss/36_boss_v5.md）：
#   PROTO_BOSS_CUE=bytype        两个阶段一个有槽一个没槽（混合对）→ 不出提示；都有槽或都没槽（同类对）→ 照 boss 第一版出 "The enemy has changed."。
#   PROTO_BOSS_SLOTSWAP=vanish   换阶段那一 END 之后，离场机制的状态格不再印（从换阶段之后的第一个画面起）；frozen = 现行（清 0 之后照旧印着）。
#   PROTO_BOSS_HANDOVER=x1m2     换阶段第一罚：动量 x2 不致死，其他 x1 不致死。
BOSS_SLOTSWAP = os.environ.get("PROTO_BOSS_SLOTSWAP", "frozen"); BOSS_SLOTSWAPS = ("frozen", "vanish")
# boss 第六版（11-06，用户「第一次可以试探，第二次一定会死」；docs/antagonist_boss/37_boss_v6_strike.md）：
#   PROTO_BOSS_STRIKE=probe1  boss 上每种机制（两个阶段各数各的）：第一次犯 = 试探（x1，动量 x2，不致死）；第二次犯 = 这条命当场结束（任何血量都死）。
#                             实现：boss 的四行（蓄力 / 守势 / 动量 / 反击）换成 (试探, 死, 死)；换阶段格照 PROTO_BOSS_HANDOVER（x1m2 时动量 x2）。破势不在阶梯上。
BOSS_STRIKE = os.environ.get("PROTO_BOSS_STRIKE", "none"); BOSS_STRIKES = ("none", "probe1", "probe1w")   # probe1w：43 号文档 §14（破势也上 boss 的试探 / 死）
LEGACY_TABLES = ("v1", "t16", "u1104", "u1104b")   # v3 之前的表：不进 _now()（见上）
V3_DEFAULTS = dict(pool="full", momentum="ramp", doubler="persist", guardcode="engine", counter="engine", guardstart="engine",   # counter / guardstart：候选 v3b
                   boss="none",                     # boss：boss 第一版（PROTO_BOSS=v1，32 号文档；默认 none 下不进 _now()，输出逐字不变）
                   boss_hp="100", boss_turncap="none",   # boss 第二版的两个旋钮（33 号文档；默认下不进 _now()）
                   guardseq="none", chargeseq="none", boss_cue="on", boss_handover="v1",   # boss 第四版（35 号文档；默认下不进 _now()）
                   boss_slotswap="frozen",                                               # boss 第五版（36 号文档；默认下不进 _now()）
                   boss_strike="none",                                                   # boss 第六版（37 号文档；默认下不进 _now()）
                   boss_guardin="quiet",                                                 # boss 第七版（38 号文档；默认下不进 _now()）
                   boss_atk="100",                                                       # boss 第八版（39 号文档；默认下不进 _now()）
                   world="A",                                                            # 世界外衣（43 号文档；默认 A 下不进 _now()）
                   heal="on",                                                            # 修订 6（43 §19；默认 on 下不进 _now()）
                   hide="none",                                                          # 画面减项（11-11；默认 none 下不进 _now()）
                   worknote="off",                                                       # 工作便签（11-11；默认 off 下不进 _now()）
                   wardseen="changed",                                                   # 封印格显示（11-11；默认 changed 下不进 _now()）
                   wardstrict="any",                                                     # 破势解法（11-11；默认 any 下不进 _now()）
                   bosslife="on",                                                        # 世界里的 boss 命（11-12；默认 on 下不进 _now()）
                   correspond="on",                                                      # 跨世界对应表（11-12；默认 on 下不进 _now()）
                   mapcharge="none",                                                     # 考试关蓄力节奏（11-12 候选；默认 none 下不进 _now()）
                   mapguard="none",                                                      # 考试关守势节奏（11-12 候选；默认 none 下不进 _now()）
                   wardlimit="off", wardteststart="default",
                   restamt="off")                                                        # 休息补给按图收紧（11-13 扫描；默认 off 下不进 _now()）                              # 非默认时记录封印时限和考试初始层数
V3_KEYS = tuple(V3_DEFAULTS) + ("ladder_table",)    # _now() 里出现的次序（只出现非默认的）
V3_RULES = dict(
    pool=dict(v3b="pool v3b: charge, momentum, counter, guard, ward (no pierce, no mark); a map draws 4 of these 5 (pool_draw, "
                  "pool-v1:{salt}); maps only for now (boss pairs not registered, boss paths unchanged)",
              nopierce="no pierce anywhere: the rotation is the prototype pool without pierce (adventure.BEHAVIOURS = solver.MECHANICS = "
                       "PROTO); a map draws 4 of these 5 mechanics (pool_draw, pool-v1:{salt}); the boss pair must lie in the same 5"),
    momentum=dict(noshield="momentum: an END with no shield held and no dodge takes the normal hit x the ladder multiplier (k = such hits this "
                           "fight + 1); a held shield takes the normal hit only (not counted); a dodge avoids it (not counted); no warning, no "
                           "streak, no ramp; the printed attack is the normal hit; boss death = 2 x max hp (dodge avoids, a shield prevents it). "
                           "Implemented by scripts/penalty_ladder.py (needs PROTO_LADDER=1)",
                  shieldonly="momentum (PROTO_MOMENTUM=shieldonly, spec 18 section 8.7): an END with no shield held takes the normal hit x the "
                             "ladder multiplier (k = such hits this fight + 1) whether or not the player dodged -- the dodge does not avoid it; a "
                             "held shield takes the normal hit only (not counted); otherwise as noshield: no warning, no streak, no ramp; the "
                             "printed attack is the normal hit; boss death = 2 x max hp (a shield prevents it). Implemented by "
                             "scripts/penalty_ladder.py v3.8 (needs PROTO_LADDER=1)"),
    doubler=dict(turncd="doubler: x2 only for attacks in the turn it is played (the flag is cleared at END); a doubler played in a turn is "
                        "absent from the fixed hand in the next turn and back the turn after; no cooldown at fight start (FixedPileCD)"),
    counter=dict(noblock="counter (PROTO_COUNTER=noblock, spec 18 section 8.8, trial): when both the attack and the shield (block) are played "
                         "in one turn (either order), at the moment the second is played the player loses normal hit x the ladder multiplier at "
                         "once (block and dodge do nothing; k = such punishments this fight + 1) and the shield is void for this turn (block "
                         "set to 0; a later block card this turn gives no block), so the END hit is taken in full; the attack deals its "
                         "normal damage and attack + doubler is legal; the engine's end-of-turn counter heavy hit is off (the END hit is "
                         "the normal hit); no slot. Implemented by scripts/penalty_ladder.py v3.9 (needs PROTO_LADDER=1)",
                 nodouble="counter (PROTO_COUNTER=nodouble): when both the attack and the doubler are played in one turn (either order), at "
                          "the moment the second is played the doubler is void for this turn and the player loses normal hit x the ladder "
                          "multiplier at once (block and dodge do nothing; k = such punishments this fight + 1); the engine's end-of-turn "
                          "counter heavy hit is off (the END hit is the normal hit); no slot. Implemented by scripts/penalty_ladder.py v3.6 "
                          "(needs PROTO_LADDER=1)"),
    guardstart=dict(map="guard starting stance pre-drawn when the map is built: per map guard fight Random('guard-start-v1:{identity_key}:"
                        "map:{map salt}:{layer}:{node}'); nothing is drawn during map play (scripts/guard_slot.py tag_starts / install_start); "
                        "bosses not covered (maps first, user 2026-11-05)"),
    boss=dict(v1="boss first version (spec 18 section 8.10, docs/antagonist_boss/32_boss_v1.md): one body one health bar (boss_switch=1), "
                 "the switch armed when the boss health falls to switch_at = floor(boss hp x boss_switch_frac / 100) and applied at the end of "
                 "that turn, cue 'The enemy has changed.', D1 slot handover; the boss guard code AND the boss guard starting stance both come "
                 "from the boss salt (Random('guard-start-v1:{identity_key}:boss:{boss salt}'), tagged when the boss Run is built; no draw "
                 "during the boss fight); prices from ladder table v3c1b (boss counter 1nl/9/27/death; the second phase mechanic's first "
                 "punishment x1 never lethal for counter, x3 never lethal otherwise); R1v2 version i re-opens after the cue; the 10 ordered "
                 "pairs PAIRS_V3C1B (world i gets pair i); needs the full v3c1 candidate with PROTO_LADDER_TABLE=v3c1b"),
    boss_hp={p: (f"boss hp multiplier (docs/antagonist_boss/33_boss_v2_hp.md): boss total hp = round(sum of the two drawn stage hp x {p} / 100) "
                 "(the engine's boss_switch_hp_pct, applied after the draw: no random stream moves); one body, one health bar for both "
                 "stages; the switch line stays floor(boss hp x 50 / 100); needs PROTO_BOSS=v1") for p in ("125", "150", "175", "200", "225", "250", "300", "350", "400")},
    boss_atk={p: (f"boss attack x{int(p) / 100} (docs/antagonist_boss/39_boss_v8.md): the boss enemy's base attack = floor(atk x {p} / 100 "
                  "+ 0.5), at least 1, set after the boss is built (no random stream moves); the normal hit, the charge big hit and the "
                  "counter / momentum / charge ladder prices derive from it; guard's price is the player's own reflected attack and is not "
                  "scaled; maps unchanged; needs PROTO_BOSS=v1") for p in BOSS_ATKS if p != "100"},
    boss_turncap={"45": "boss turn cap 45 (docs/antagonist_boss/39_boss_v8.md), otherwise as the 60 cap; needs PROTO_BOSS=v1",
                  "60": "boss turn cap 60 (docs/antagonist_boss/33_boss_v2_hp.md): the boss fight ends as a loss after 60 ENDs with both alive "
                        "(maps keep TURN_CAP 40; Fight.over, ended_by and solver.play_fight's cap read the boss enemy's _turn_cap, tagged by "
                        "antagonist_boss.build_boss); participants are not told (as with 40); needs PROTO_BOSS=v1"},
    guardseq={k: (f"boss guard irregular (docs/antagonist_boss/35_boss_v4_irregular.md): at each END of a boss guard stage the stance flips "
                  f"only if the pre-drawn schedule says so (each END flips with probability 0.{k[3:]}, drawn when the boss is built from "
                  "Random('guard-seq-v1:{identity_key}:boss:{boss salt}:{level}'); nothing drawn in play); never more than 3 turns in a row "
                  "in one stance (after two non-flips the next END flips); display unchanged (printed from turn 2, code per boss); maps "
                  "unchanged; needs PROTO_BOSS=v1") for k in ("irr50", "irr67")},
    chargeseq=dict({k: (f"boss charge irregular (docs/antagonist_boss/35_boss_v4_irregular.md): at an END of a boss charge stage that begins at "
                   f"0 or 1 the counter stalls (does not rise) if the pre-drawn schedule says so (probability 0.{k[3:]}, drawn when the boss is "
                   "built from Random('charge-seq-v1:{identity_key}:boss:{boss salt}:{level}')); never two stalls in a row; an END that "
                   "begins at 2 always fires the big hit; maps unchanged; needs PROTO_BOSS=v1") for k in ("irr25", "irr50")},
               len234="boss v7 charge lengths (docs/antagonist_boss/38_boss_v7.md): after a big hit (and at the start of a charge stage) "
                         "the counter shows 1, stays at 1 for 0, 1 or 2 extra turns (1/3 each, pre-drawn from the boss salt: "
                         "Random('charge-len-v1:{identity_key}:boss:{boss salt}')), then shows 2; the big hit lands at the END of the turn "
                         "showing 2; 0 is never shown; maps unchanged; needs PROTO_BOSS=v1"),
    boss_cue={"off": "no switch cue: TUNING boss_switch_hint = 0 (no 'The enemy has changed.' line); needs PROTO_BOSS=v1",
              "bytype": "switch cue by pair type (docs/antagonist_boss/36_boss_v5.md): a boss whose two stages differ in having an enemy "
                        "state slot (one of charge / guard / ward, the other momentum / counter) shows no cue; a boss whose stages both have "
                        "a slot or both have none shows 'The enemy has changed.' at the switch as in boss v1; needs PROTO_BOSS=v1"},
    boss_handover={"x1": "the first punishment of the second-stage mechanism after the switch is x1 never lethal for every mechanism "
                         "(ladder table v3c1b handover step); needs PROTO_BOSS=v1",
                   "x1m2": "the first punishment of the second-stage mechanism after the switch is x2 never lethal for momentum and x1 never "
                           "lethal for every other mechanism (docs/antagonist_boss/36_boss_v5.md); needs PROTO_BOSS=v1"},
    boss_guardin={"now": "boss v7 (docs/antagonist_boss/38_boss_v7.md): an incoming stage-2 guard slot is printed from the first screen after "
                         "the switch (its start value; not held back until its first flip); needs PROTO_BOSS=v1"},
    boss_strike={"probe1": "boss strike rule (docs/antagonist_boss/37_boss_v6_strike.md): on the boss each mechanism is counted on its own "
                           "(stage 1 and stage 2 separately); its first offence is a probe (x1, x2 for momentum, never lethal), its second "
                           "offence ends the life at once (death at any hp); ward is not on the ladder; needs PROTO_BOSS=v1",
                 "probe1w": "boss strike rule probe1 plus ward (docs/antagonist_boss/43_eight_world_pack.md section 14): on the boss, an attack "
                            "card played while the seal is up is a ward offence, counted per card at play time and per stage; the first is a "
                            "probe (one normal hit at once, shield and dodge do not help, never lethal), the second ends the life at once; the "
                            "engine's own ward effects (the attack does no damage, the seal grows at END) are unchanged; maps unchanged; needs PROTO_BOSS=v1"},
    boss_slotswap={"vanish": "at the switch the outgoing mechanism's enemy state slot stops being printed from the first screen after the "
                             "switch (removed from the fight's changed-slot set, value 0); docs/antagonist_boss/36_boss_v5.md; needs PROTO_BOSS=v1"},
    guardcode=dict(map="guard slot code per map: normal (guard stance prints 1, attack stance 0) or flipped (guard stance 0, attack 1), 50/50 "
                       "from Random('guard-code-v1:{identity_key}:map:{map salt}'), the boss from ...:boss:{boss salt}; engine unchanged; "
                       "turn 1 unprinted (seen display), printed every turn from turn 2; every screen and log line (scripts/guard_slot.py)"))
V3_RULES["hide"] = dict(a7cap="screen: the attacks-this-turn count (me.offence) and the maximum-health slot (me.cap) are never printed (status row, change lines, correspondence table); rules unchanged",
                        a7capatk="screen: as a7cap, and both attack slots (me.atk, them.atk) are never printed either; rules unchanged")
V3_RULES["wardlimit"] = {n: (f"ward time limit (v8): a fight with a seal is lost after {n} consecutive turns that start sealed and are still "
                                f"sealed after END (count reset when the seal reaches 0 or is open; restarts after it reseals); the participant "
                                f"sees only {WARD_LIMIT_LOSS!r}") for n in WARDLIMITS[1:]}
V3_RULES["mapcharge"] = dict(len234="map charge, test fights only (teach fights keep 0-1-2-release): after a release the counter prints 1 and stays on 1 for 0 / 1 / 2 extra turns (1/3 each, pre-drawn per map salt, layer and node; a table whose first two releases fall on turns 3 and 6 is redrawn), so releases are 2 / 3 / 4 turns apart; 0 is no longer printed")
V3_RULES["mapguard"] = dict(irr50="map guard, test fights only (teach fights flip every END): each END flips the guard phase with probability 0.5, never the same phase for more than 3 turns (pre-drawn per map salt, layer and node; a table that flips on each of the first 3 ENDs is redrawn)",
                            irr67="map guard, test fights only: as irr50 with probability 0.67")
V3_RULES["correspond"] = dict(off="participant text: from world 2 on, no correspondence table (previous world's card names and status labels against this world's) in the memory, the life-note material or the letter material; nothing replaces it; rules unchanged")
V3_RULES["bosslife"] = dict(off="world: lives 1-4 only (the four maps); the boss life is not played and the letter is written after life 4")
V3_RULES["wardstrict"] = dict(blockonly="ward: the seal drops by 1 only on a turn whose cards are all block cards (no attack, no doubler or other card) and the block absorbed the hit; a doubler + block turn leaves the seal unchanged")
class _RestamtRules(dict):
    def __missing__(self, name):
        sha = hashlib.sha256((RESTAMT_DIR / f"{name}.json").read_bytes()).hexdigest()
        return (f"rest resupply tightened per map: table {name!r} (~/agii_runs/restamt/{name}.json, sha256 {sha}) gives each map a fixed "
                f"amount per automatic resupply, capped at max HP; max HP and all damage unchanged")


V3_RULES["restamt"] = _RestamtRules()
V3_RULES["wardteststart"] = {n: f"ward test fights start and reseal at {n} layers; teach and boss fights unchanged"
                            for n in WARDTESTSTARTS[1:]}
V3_RULES["wardseen"] = dict(acted="screen: the seal slot is printed from the first attack it blocks onwards (a teach seal starts at its cap, so blocking does not change its value); rules unchanged")
V3_RULES["worknote"] = dict(on="participant text: each action reply may carry a working note (NOTE:, at most 200 tokens, replaces the previous one, shown at every step, cleared when the fight ends; the final version attached when notes are written); rules unchanged")
V3_RULES["heal"] = dict(
    off="no heal (docs/antagonist_boss/43_eight_world_pack.md section 19, revision 6): every life's deck holds 0 heal cards (TUNING "
        "deck_counts heal = 0; the heal kind stays in the card table), so no heal is ever in hand, in the camp or at the boss and no player "
        "can play one; the HP budget B counts the deck's heals, now 0; the maximum HP is M + 3h (h = one heal's amount; adjusted by the "
        "fewest points, worlds in pack order, so that D1 and D3 still hold) and the resupply percentage is the largest r' with "
        "floor(M' r' / 100) <= floor(M r / 100); participants are not told")


SWITCH_RULES = dict(            # 研究者侧说明，只在有开关非默认时写进 switches()["switch_rules"]
    incoming=dict(mute="boss handover: incoming start values are not changes (D1: kept out of slots_changed and the log)",
                  real="boss handover: an incoming slot whose value differs from its value at the start of that END is a change "
                       "(listed in the END line, kept on the seen display); a start equal to the old value is no change"),
    threat=dict(plain="enemy attack slot = attack + rage + ramp tiers; the boss momentum floor is not printed",
                momentum="boss, momentum-only phase: after every END the attack slot = Fight._incoming()[0], the next END hit "
                         "before block/dodge; charge and the map pierce grudge are not covered (pending the user)"),
    markmap=dict(salt="mark code table per Run salt: Random('mark-v1:{salt}') (identity_key 0)",
                 world="one table per world, keyed on content: Random('mark-world-v1:{identity_key}:{sorted map salts}:"
                       "{boss salt}:{order}').sample(MARK_ORDER, 5); the 4 maps and the boss share it"))
ARCHIVE = dict(loot=True, nodes="route", display="per-player", refs="b", hand="draw",
               incoming="mute", threat="plain", markmap="salt", ladder=False, tune="none", rage="on")   # 没有 "proto" 键的旧文件就是在这组开关下跑的（2026-11-03 之前）
NOLOOT_1102 = dict(loot=False, nodes="route", display="per-player", refs="b", hand="draw",
                   incoming="mute", threat="plain", markmap="salt", ladder=False, tune="none", rage="on")   # 2026-11-02 只关奖励的那次（antagonist_noloot.sh 当时的状态）
DEFAULTS = dict(loot=False, nodes="fixed", display="seen", refs="c", hand="draw", incoming="mute", threat="plain", markmap="salt",
                ladder=False, tune="none", rage="on")
SWITCH_KEYS = tuple(DEFAULTS)
_UNMIGRATED = {"antagonist_diag.py": "antagonist_diag.json", "antagonist_momentum_probe.py": "antagonist_momentum_probe.json"}
PENDING = ("momentum_boss_frac", "mark code mapping per salt vs per world", "pierce probe price / first-contact lethality",
           "guard handover first turn", "hand guarantee at the switch", "charge_returns_dodge", "big_lethal", "boss_punish_pct",
           "boss_switch_grace", "camp in the prototype world (PROTO_CAMP, default off)")
PENDING_REFS = ("N5 heal veto for R1v2 c and the oracle (PROTO_REFS=c): registered by the user 2026-11-03 as a candidate R1 version (added after "
                "seeing C10, so not a pre-frozen spec); b (PROTO_REFS=b) kept; neither is primary until validation on fresh maps and a fresh "
                "stream (docs/antagonist_boss/04_r1v2_spec.md sections 10-11; protocol drafted, not frozen, not run)",)
# 用户已定、还没采用的（12 §4.1；审查 B1）：PENDING 一字不改（mark_rule_check 的 M0 读它的原字符串，默认输出也写整份 PENDING），
# 这里只是模块常量，不进 settings()；c10fix_check / C10 v2 的输出记它。采用的那一版再一起改 PENDING 和 M0（12 §15）。
DECIDED_NOT_ADOPTED = (
    "guard handover first turn -> user decision 2 (2026-11-03 evening): PROTO_INCOMING=real; default mute until a version adopts it",
    "mark code mapping per salt vs per world -> user decision 4: PROTO_MARKMAP=world (D13 content key); default salt until adopted",
    "momentum floor printed -> user decision 3: PROTO_THREAT=momentum; default plain until adopted")
SCREEN_READERS = ("R1", "R1v2", "R1+momentum", "habit")   # 读画面（cautious.them_slots）的玩家
WHO_DISPLAY = ("R1", "R1v2", "R1+momentum", "oracle", "habit", "blind", "model", "human")


def _validate():
    if NODES not in ("fixed", "route"):
        raise ValueError(f"PROTO_NODES={NODES!r}：只能是 fixed / route")
    if DISPLAY not in DISPLAYS:
        raise ValueError(f"PROTO_DISPLAY={DISPLAY!r}：只能是 {DISPLAYS}")
    if REFS not in REFS_ALL:
        raise ValueError(f"PROTO_REFS={REFS!r}：只能是 {REFS_ALL}")
    if HAND not in HANDS:
        raise ValueError(f"PROTO_HAND={HAND!r}：只能是 {HANDS}")
    if HAND == "fixed" and CAMP and not (POOL == "v3b" and DOUBLER == "turncd"):
        # 11-05 晚（18 §8.6）：候选 v3b 的固定手牌营地在 scripts/proto_camp.py（还要 PROTO_TEXT=minimal，proto_play 开打前查）；别的固定手牌组合照旧拒绝
        raise ValueError("PROTO_HAND=fixed 还没给营地做固定手牌（营地用 camp.Pile）：不能和 PROTO_CAMP=1 一起用")
    if HAND == "fixed" and LOOT:
        raise ValueError("PROTO_HAND=fixed 不能和 PROTO_LOOT=1 一起用：拿到的牌与已有的同名，固定手牌里合成一张，拿牌悄悄无效")
    if INCOMING not in INCOMINGS:
        raise ValueError(f"PROTO_INCOMING={INCOMING!r}：只能是 {INCOMINGS}")
    if THREAT not in THREATS:
        raise ValueError(f"PROTO_THREAT={THREAT!r}：只能是 {THREATS}")
    if MARKMAP not in MARKMAPS:
        raise ValueError(f"PROTO_MARKMAP={MARKMAP!r}：只能是 {MARKMAPS}")
    if LADDER_ENV not in LADDERS:
        raise ValueError(f"PROTO_LADDER={LADDER_ENV!r}：只能是 {LADDERS}")
    if LADDER and HAND != "fixed":
        raise ValueError("PROTO_LADDER=1 只为固定手牌设计、只在固定手牌下核对过（scripts/ladder_check.py）：要和 PROTO_HAND=fixed 一起用")
    if TUNE not in TUNES:
        raise ValueError(f"PROTO_TUNE={TUNE!r}：只能是 {TUNES} 或盾低于攻击的测量网格 {tuple(SHIELD_TUNINGS)} 或候选 v3c 的 {tuple(COUNTER_HP_TUNINGS)}")
    if TUNE != "none" and HAND != "fixed":
        raise ValueError(f"PROTO_TUNE={TUNE} 是在固定手牌下挑出、确认的（docs/antagonist_boss/11_fixed_tune_results.md）：要和 PROTO_HAND=fixed 一起用")
    if RAGE not in RAGES:
        raise ValueError(f"PROTO_RAGE={RAGE!r}：只能是 {RAGES}")
    if RAGE == "off" and HAND != "fixed":
        raise ValueError("PROTO_RAGE=off 只为固定手牌（阶梯候选，13 §4b）设计、只在固定手牌下核对过：要和 PROTO_HAND=fixed 一起用")
    # 候选 v3（18）
    if POOL not in POOLS:
        raise ValueError(f"PROTO_POOL={POOL!r}：只能是 {POOLS}")
    if MOMENTUM not in MOMENTUMS:
        raise ValueError(f"PROTO_MOMENTUM={MOMENTUM!r}：只能是 {MOMENTUMS}")
    if MOMENTUM != "ramp" and not LADDER:
        raise ValueError(f"PROTO_MOMENTUM={MOMENTUM} 由惩罚阶梯实现（scripts/penalty_ladder.py）：要和 PROTO_LADDER=1 一起用")
    if DOUBLER not in DOUBLERS:
        raise ValueError(f"PROTO_DOUBLER={DOUBLER!r}：只能是 {DOUBLERS}")
    if DOUBLER != "persist" and HAND != "fixed":
        raise ValueError("PROTO_DOUBLER=turncd 的冷却做在固定手牌里（FixedPileCD）：要和 PROTO_HAND=fixed 一起用")
    if GUARDCODE not in GUARDCODES:
        raise ValueError(f"PROTO_GUARDCODE={GUARDCODE!r}：只能是 {GUARDCODES}")
    if GUARDCODE != "engine" and DISPLAY != "seen":
        raise ValueError("PROTO_GUARDCODE=map 只为统一 seen 画面写（第 1 回合不印、第 2 回合起每回合印）：要和 PROTO_DISPLAY=seen 一起用")
    if COUNTER not in COUNTERS:
        raise ValueError(f"PROTO_COUNTER={COUNTER!r}：只能是 {COUNTERS}")
    if COUNTER != "engine" and not LADDER:
        raise ValueError("PROTO_COUNTER=nodouble 由惩罚阶梯实现（scripts/penalty_ladder.py v3.6）：要和 PROTO_LADDER=1 一起用" if COUNTER == "nodouble"
                         else f"PROTO_COUNTER={COUNTER} 由惩罚阶梯实现（scripts/penalty_ladder.py v3.9）：要和 PROTO_LADDER=1 一起用")
    if GUARDSTART not in GUARDSTARTS:
        raise ValueError(f"PROTO_GUARDSTART={GUARDSTART!r}：只能是 {GUARDSTARTS}")
    # boss 第一版（PROTO_BOSS=v1，32 号文档）：只在完整的 v3c1 候选 + 表 v3c1b 下；表 v3c1b 也只配 PROTO_BOSS=v1（boss 的价钱只在这一套下定义过）
    if BOSS not in BOSSES:
        raise ValueError(f"PROTO_BOSS={BOSS!r}：只能是 {BOSSES}")
    need = dict(HAND="fixed", POOL="v3b", MOMENTUM="noshield", DOUBLER="turncd", GUARDCODE="map", COUNTER="noblock", GUARDSTART="map",
                LADDER_TABLE="v3c1b")
    if BOSS == "v1" and (not LADDER or any(globals()[k] != v for k, v in need.items())):
        raise ValueError("PROTO_BOSS=v1（boss 第一版）只在完整的 v3c1 候选 + PROTO_LADDER_TABLE=v3c1b 下：要 PROTO_LADDER=1 和 "
                         + " ".join(f"PROTO_{k}={v}" for k, v in need.items()))
    if BOSS_HP not in BOSS_HPS:
        raise ValueError(f"PROTO_BOSS_HP={BOSS_HP!r}：只能是 {BOSS_HPS}")
    if BOSS_TURNCAP not in BOSS_TURNCAPS:
        raise ValueError(f"PROTO_BOSS_TURNCAP={BOSS_TURNCAP!r}：只能是 {BOSS_TURNCAPS}")
    for name, val, ok in (("GUARDSEQ", GUARDSEQ, GUARDSEQS), ("CHARGESEQ", CHARGESEQ, CHARGESEQS), ("BOSS_CUE", BOSS_CUE, BOSS_CUES),
                          ("BOSS_HANDOVER", BOSS_HANDOVER, BOSS_HANDOVERS), ("BOSS_SLOTSWAP", BOSS_SLOTSWAP, BOSS_SLOTSWAPS),
                          ("BOSS_STRIKE", BOSS_STRIKE, BOSS_STRIKES), ("BOSS_GUARDIN", BOSS_GUARDIN, BOSS_GUARDINS),
                          ("BOSS_ATK", BOSS_ATK, BOSS_ATKS)):
        if val not in ok:
            raise ValueError(f"PROTO_{name}={val!r}：只能是 {ok}")
    if (GUARDSEQ, CHARGESEQ, BOSS_CUE, BOSS_HANDOVER, BOSS_SLOTSWAP, BOSS_STRIKE, BOSS_GUARDIN, BOSS_ATK) != \
            ("none", "none", "on", "v1", "frozen", "none", "quiet", "100") \
            and BOSS != "v1":
        raise ValueError("PROTO_GUARDSEQ / PROTO_CHARGESEQ / PROTO_BOSS_CUE / PROTO_BOSS_HANDOVER（boss 第四版，35 号文档）只配 PROTO_BOSS=v1")
    if (BOSS_HP != "100" or BOSS_TURNCAP != "none") and BOSS != "v1":
        raise ValueError("PROTO_BOSS_HP / PROTO_BOSS_TURNCAP（boss 第二版的旋钮，33 号文档）只配 PROTO_BOSS=v1")
    if WORLD != "A":                                        # 世界外衣（43 号文档）：只配完整的候选 v3c1（图）/ v3c1b（boss）
        import proto_worlds
        proto_worlds.surface(WORLD)
        need_w = dict(HAND="fixed", RAGE="off", TUNE="m59ws2t25c_bp45w90_c48", POOL="v3b", MOMENTUM="noshield", DOUBLER="turncd",
                      GUARDCODE="map", COUNTER="noblock", GUARDSTART="map")
        if not LADDER or LADDER_TABLE not in ("v3c1", "v3c1b") or any(globals()[k] != v for k, v in need_w.items()):
            raise ValueError(f"PROTO_WORLD={WORLD}（世界外衣）只配完整的候选 v3c1：要 PROTO_LADDER=1、PROTO_LADDER_TABLE=v3c1 / v3c1b 和 "
                             + " ".join(f"PROTO_{k}={v}" for k, v in need_w.items()))
    if MAPCHARGE not in MAPCHARGES:
        raise ValueError(f"PROTO_MAPCHARGE={MAPCHARGE!r}：只能是 {MAPCHARGES}")
    if WARDLIMIT not in WARDLIMITS:
        raise ValueError(f"PROTO_WARDLIMIT={WARDLIMIT!r}：只能是 off 或 1–40")
    if RESTAMT != "off" and (not RESTAMT.replace("_", "").replace("-", "").isalnum() or not (RESTAMT_DIR / f"{RESTAMT}.json").exists()):
        raise ValueError(f"PROTO_RESTAMT={RESTAMT!r}：要 off 或 ~/agii_runs/restamt/ 下已有的表名")
    if WARDTESTSTART not in WARDTESTSTARTS:
        raise ValueError(f"PROTO_WARDTESTSTART={WARDTESTSTART!r}：只能是 {WARDTESTSTARTS}")
    if WARDLIMIT != "off" and (HAND != "fixed" or DOUBLER != "turncd"):
        raise ValueError(f"PROTO_WARDLIMIT={WARDLIMIT} 要 PROTO_HAND=fixed、PROTO_DOUBLER=turncd（计数挂在认得 Fight 的固定手牌牌堆上）")
    if MAPGUARD not in MAPGUARDS:
        raise ValueError(f"PROTO_MAPGUARD={MAPGUARD!r}：只能是 {MAPGUARDS}")
    if CORRESPOND not in CORRESPONDS:
        raise ValueError(f"PROTO_CORRESPOND={CORRESPOND!r}：只能是 {CORRESPONDS}")
    if BOSSLIFE not in BOSSLIFES:
        raise ValueError(f"PROTO_BOSSLIFE={BOSSLIFE!r}：只能是 {BOSSLIFES}")
    if WARDSTRICT not in WARDSTRICTS:
        raise ValueError(f"PROTO_WARDSTRICT={WARDSTRICT!r}：只能是 {WARDSTRICTS}")
    if WARDSEEN not in WARDSEENS:
        raise ValueError(f"PROTO_WARDSEEN={WARDSEEN!r}：只能是 {WARDSEENS}")
    if WORKNOTE not in WORKNOTES:
        raise ValueError(f"PROTO_WORKNOTE={WORKNOTE!r}：只能是 {WORKNOTES}")
    if HIDE not in HIDES:
        raise ValueError(f"PROTO_HIDE={HIDE!r}：只能是 {tuple(HIDES)}")
    if HEAL not in HEALS:
        raise ValueError(f"PROTO_HEAL={HEAL!r}：只能是 {HEALS}")
    if HEAL == "off":                                       # 修订 6（43 §19）：只配完整的候选 v3c1 / v3c1b，只配包 v6 的 8 个表层
        import proto_worlds
        proto_worlds.healoff(WORLD)
        need_h = dict(HAND="fixed", RAGE="off", TUNE="m59ws2t25c_bp45w90_c48", POOL="v3b", MOMENTUM="noshield", DOUBLER="turncd",
                      GUARDCODE="map", COUNTER="noblock", GUARDSTART="map")
        if not LADDER or LADDER_TABLE not in ("v3c1", "v3c1b") or any(globals()[k] != v for k, v in need_h.items()):
            raise ValueError("PROTO_HEAL=off（修订 6）只配完整的候选 v3c1：要 PROTO_LADDER=1、PROTO_LADDER_TABLE=v3c1 / v3c1b 和 "
                             + " ".join(f"PROTO_{k}={v}" for k, v in need_h.items()))
    if LADDER and LADDER_TABLE == "v3c1b" and BOSS != "v1":
        raise ValueError("PROTO_LADDER_TABLE=v3c1b 是 boss 第一版的表（换阶段的价钱）：要和 PROTO_BOSS=v1 一起用（只打地图请用 v3c1）")


def v3_now():
    """候选 v3 的开关里偏离默认的那些（次序 V3_KEYS）；ladder_table 只在 PROTO_LADDER=1 且表不是 LEGACY_TABLES 之一时出现。默认下是 {}。"""
    g = globals()
    out = {k: g[k.upper()] for k in V3_DEFAULTS if g[k.upper()] != V3_DEFAULTS[k]}
    if LADDER and LADDER_TABLE not in LEGACY_TABLES:
        out["ladder_table"] = LADDER_TABLE
    return out


def default_of(k):
    """一个开关键的默认值（DEFAULTS 或 V3_DEFAULTS；ladder_table 的「默认」= 不出现，记成 None）。给按键查默认的外部脚本用。"""
    if k in DEFAULTS:
        return DEFAULTS[k]
    if k in V3_DEFAULTS:
        return V3_DEFAULTS[k]
    if k == "ladder_table":
        return None
    raise KeyError(k)


def _now():
    return dict(loot=LOOT, nodes=NODES, display=DISPLAY, refs=REFS, hand=HAND, incoming=INCOMING, threat=THREAT, markmap=MARKMAP,
                ladder=LADDER, tune=TUNE, rage=RAGE, **v3_now())


def _env(sw):
    return " ".join(f"PROTO_{k.upper()}={int(v) if isinstance(v, bool) else v}" for k, v in sw.items())


def _guard_stale():
    """没迁移的脚本 / 过时的配方，拒绝而不是悄悄跑现行版本（审查 2026-11-03）。导入时和每次 setup() 时查。
    · 主程序是 _UNMIGRATED 里的脚本（工作进程的 __main__ 也是它）：它们无条件写存档文件名 —— 那个文件已存在就拒绝；开关不是 ARCHIVE 也拒绝。
    · 环境变量 OUTNAME / SRCNAME 含 "noloot"（antagonist_noloot.sh 的文件名）而开关不是 2026-11-02 那组（NOLOOT_1102）：拒绝。"""
    main = sys.modules.get("__main__")
    name = pathlib.Path(getattr(main, "__file__", None) or "").name
    if name in _UNMIGRATED:
        out = OUT / _UNMIGRATED[name]
        if out.exists():
            raise SystemExit(f"{name} 没迁移到原型现行版本（无 out_tag / refuse_overwrite / check_source），会覆盖已有结果 {out.relative_to(ROOT)}：拒绝。")
        if _now() != ARCHIVE:
            raise SystemExit(f"{name} 没迁移：只能在存档开关下跑（{_env(ARCHIVE)}），现在 {_now()}")
    for var in ("OUTNAME", "SRCNAME"):
        if "noloot" in os.environ.get(var, "") and _now() != NOLOOT_1102:
            raise SystemExit(f"{var}={os.environ[var]!r} 是 2026-11-02 只关奖励那次的文件名，但开关是 {_now()}；"
                             f"要复现那次就导出 {_env(NOLOOT_1102)}（antagonist_noloot.sh 只导出 PROTO_LOOT=0），否则换一个文件名")


_validate()
_guard_stale()


def switches():
    """本进程的版本与开关（不含 references）。"""
    return dict(version=PROTO_VERSION, loot=LOOT, nodes=NODES, node_rule=NODE_RULE if NODES == "fixed" else "route",
                display=DISPLAY, display_tuning=display_settings() if DISPLAY != "per-player" else "per-player",
                camp=CAMP, rest="automatic resupply (auto_rest=1)", refs=REFS, hand=HAND,
                hand_rule=FixedPile.RULE if HAND == "fixed" else "draw (registration 12 pile)",
                turn_cap=TURN_CAP if HAND == "fixed" else "none for participants; scripts stop at solver.play_fight cap=40",
                dodge_run_limit=DODGE_RUN_LIMIT if HAND == "fixed" else None,
                ladder=LADDER, tune=TUNE, rage=RAGE, **_candidate_rules(),   # 11-03 夜 / 11-04：放在三个 C10 v2 开关之前（c10fix_check X0 要它们是最后三个键）
                **_v3_rules(),                                                # 候选 v3：只在非默认时加键（默认下 switches() 逐字不变）
                incoming=INCOMING, threat=THREAT, markmap=MARKMAP,
                **_switch_rules())


def _v3_rules():
    """候选 v3 偏离默认时 switches() 另带的键：v3_now() 的每个键 + v3_rules（研究者侧说明）+ 守势映射 / 增伤手牌的模块版本。默认下 {}。"""
    now = v3_now()
    if not now:
        return {}
    rules = {k: V3_RULES[k][v] for k, v in now.items() if k in V3_RULES}
    if "ladder_table" in now:
        rules["ladder_table"] = f"penalty ladder table {now['ladder_table']!r} (PROTO_LADDER_TABLE; see ladder_rule)"
    if GUARDCODE == "map":
        import guard_slot
        rules["guardcode_module"] = guard_slot.VERSION
    if DOUBLER == "turncd":
        rules["doubler_hand_rule"] = FixedPileCD.RULE
    if GUARDSTART == "map":
        import guard_slot
        rules["guardstart_module"] = guard_slot.START_VERSION
    if BOSS == "v1":                                        # boss 第一版：配对（没登记，只给筛选用）
        rules["boss_pairs"] = [list(p) for p in PAIRS_V3C1B]
    if WORLD != "A":                                        # 世界外衣（43 号文档）
        import proto_worlds
        rules["world_surface"] = proto_worlds.describe(WORLD)
    if HEAL == "off":                                       # 修订 6（43 §19）：这个世界的 M′ / r′
        import proto_worlds
        rules["heal_off"] = dict(module=proto_worlds.HEALOFF_VERSION, world=WORLD, **proto_worlds.healoff(WORLD))
    return dict(now, v3_rules=rules)


RAGE_RULE = ("no rage: TUNING rage_ratio = 0 (written by setup() after activate_registered(12), before any map is built) and "
             "adventure.make_enemy wrapped so that an enemy built while rage_ratio == 0 has rage 0 (the engine's scaled() floors at 1, "
             "so rage_ratio = 0 alone still gives rage 1); only the rage field changes, no random stream moves; a stalled turn no longer "
             "raises the enemy attack, so the ladder's normal hit is the enemy attack and the printed attack changes only through momentum; "
             "teardown() restores rage_ratio and make_enemy (docs/antagonist_boss/13_penalty_ladder.md section 4b, user 2026-11-03 night)")


def _candidate_rules():
    """PROTO_LADDER / PROTO_TUNE / PROTO_RAGE 偏离默认时 switches() 另带的说明（研究者侧，静态：不随阶梯此刻装没装而变）；默认下不加键。"""
    out = {}
    if LADDER:
        import penalty_ladder as pl
        d = pl.describe(pl.TABLES[pl.TABLE_NAME])      # 11-04：原来写死 pl.LADDER，PROTO_LADDER_TABLE=t16 时也记成 v1（实际装的是 t16，见 ladder_describe）
        out["ladder_rule"] = dict(module="scripts/penalty_ladder.py", version=pl.VERSION, table_name=pl.TABLE_NAME, table=d["table"], table_sha16=d["table_sha16"],
                                  order="installed last by setup(), outside the boss layer's Fight patches; removed first by teardown()")
    if TUNE != "none":
        effective = dict(TUNINGS[TUNE])
        if WARDTESTSTART != "default":
            effective["ward_test_start"] = int(WARDTESTSTART)
        out["tune_rule"] = dict(name=TUNE, overrides={k: list(v) if isinstance(v, tuple) else v for k, v in effective.items()},
                                source=("docs/antagonist_boss/21_shield_below_attack_sweep.md: measurement grid (not a candidate), m59ws2t25c + "
                                        "block_pct / wear_pct so that every map enemy's normal attack exceeds the shield (user 2026-11-05)"
                                        if TUNE in SHIELD_TUNINGS else
                                        "docs/antagonist_boss/28_candidate_v3c.md: candidate v3c, m59ws2t25c_bp45w90 + hp_counter (4, 8) "
                                        "(user 2026-11-06: counter enemy health 4-8 x attack under PROTO_COUNTER=noblock; same randint width, "
                                        "same random stream)"
                                        if TUNE in COUNTER_HP_TUNINGS else
                                        "docs/antagonist_boss/11_fixed_tune_results.md: M59+WS2 (scripts/fixed_tune.py CONFIGS), "
                                        "picked and confirmed on unseen maps under the old punishment multipliers"),
                                when="written by setup() after activate_registered(12), before any map is built (build and play time); "
                                     "teardown() restores the values from before the first write")
    if RAGE != "on":
        out["rage_rule"] = dict(name=RAGE, overrides=dict(rage_ratio=0), make_enemy="rage = 0 when rage_ratio == 0 (scaled() floor bypassed)",
                                rule=RAGE_RULE)
    return out


def _switch_rules():
    """三个候选开关（incoming / threat / markmap）有任何一个偏离默认时，switches() 另带 switch_rules（研究者侧说明）；默认下不加（默认输出不变）。"""
    now = dict(incoming=INCOMING, threat=THREAT, markmap=MARKMAP)
    if all(v == DEFAULTS[k] for k, v in now.items()):
        return {}
    return dict(switch_rules={k: SWITCH_RULES[k][v] for k, v in now.items()})


def settings():
    """本进程的版本与开关 + 参照实际用的版本；写进每个输出文件的 "proto" 键。PROTO_LADDER=1 时另记 ladder_describe = penalty_ladder.describe()
    （跟着阶梯此刻的状态走，同 references；默认下不加键）。"""
    out = dict(switches(), references=references())
    if LADDER:
        import penalty_ladder as pl
        out["ladder_describe"] = pl.describe()
    return out


# ---------------------------------------------------------------- 参照（N5）
def no_heal_veto(f):
    """显式的「这一场不否决自动治疗」，行为同 heal_veto=None；让 setup() 装的 play_fight 包装认得出「调用方明确不要否决」。"""
    return False


def oracle_veto_on(flag=None):
    """全知这一条命用不用 N5 的否决：显式 flag > antagonist_boss.ORACLE_VETO（已载入且不是 None）> r1v2.ENERGY_VETO（setup() 按 PROTO_REFS 设）。"""
    if flag is not None:
        return bool(flag)
    abm = sys.modules.get("antagonist_boss")
    if abm is not None and getattr(abm, "ORACLE_VETO", None) is not None:
        return bool(abm.ORACLE_VETO)
    import r1v2
    return bool(r1v2.ENERGY_VETO)


def references():
    """参照此刻实际的版本（跟着模块旗子走，不只是开关）：R1v2 的版本；全知的 N5 否决 —— "every oracle path"（play_fight 包装装着且开着）/
    "antagonist_boss paths only"（开着但没装包装：只有 antagonist_boss 显式接）/ "none"。"""
    import r1v2
    on = oracle_veto_on()
    out = dict(r1v2=r1v2.VERSION if r1v2.ENERGY_VETO else r1v2.VERSION_B,
               oracle_veto=("every oracle path" if on and "play_fight" in _ORIG else "antagonist_boss paths only" if on else "none"),
               oracle_veto_rule="r1v2.oracle_heal_veto (change set c, N5)")
    if getattr(r1v2, "oracle_v3_active", lambda: False)():   # 候选 v3（PROTO_MOMENTUM=noshield / PROTO_DOUBLER=turncd）：全知的 v3 包装装着时才加键（默认下逐字不变）
        out["oracle_v3"] = getattr(r1v2, "oracle_v3_version", lambda: r1v2.ORACLE_V3_VERSION)()   # f 版：nodouble 下是 ORACLE_V3B_VERSION
    if getattr(r1v2, "r1_v3_active", lambda: False)():       # 候选 v3（PROTO_GUARDCODE=map / PROTO_DOUBLER=turncd）：R1 的 v3 包装装着时才加键（11-05，审查后）
        out["r1_v3"] = getattr(r1v2, "r1_v3_version", lambda: r1v2.R1_V3_VERSION)()
    return out


def camp():
    """参与者入口打不打营地（PROTO_CAMP，待用户定，默认不打）。脚本参照从来不打营地。"""
    return CAMP


# ---------------------------------------------------------------- 画面
def display():
    return DISPLAY


def _per_player(who):
    """存档（2026-11-03 之前）各玩家的画面键，逐个照抄当时的脚本。"""
    import devworld
    r1 = dict(devworld.R1_DISPLAY)                         # marks=0, state_slots="seen"
    return {"R1": r1, "R1v2": r1, "R1+momentum": r1, "oracle": r1, "habit": dict(state_slots="seen"),
            "blind": {}, "model": {}, "human": {}}[who]


def display_settings(who=None):
    """这个玩家该用的 TUNING 画面键。统一模式（seen / hidden）下与 who 无关：marks=0、state_slots=模式；per-player 下按存档。"""
    if DISPLAY != "per-player":
        return dict(marks=0, state_slots=DISPLAY)
    if who is None:
        return {}
    assert who in WHO_DISPLAY, who
    return _per_player(who)


def apply_display(who=None):
    from adventure import TUNING
    new = display_settings(who)
    prev = {k: TUNING[k] for k in new}
    TUNING.update(new)
    return prev


@contextlib.contextmanager
def using_display(who=None):
    from adventure import TUNING
    prev = apply_display(who)
    try:
        yield display_settings(who)
    finally:
        TUNING.update(prev)


def tracks_screen(who):
    """要不要人的 `?` 规则追踪（Fight.track_seen；solver.play_fight 为省时间默认关掉）。统一模式下读画面的玩家都开；
    per-player 下只有习惯开（存档）。seen 画面下它不改变 cautious.them_slots 读到的任何值，只在 hidden 下有影响（蓄力印 `?`）。"""
    if DISPLAY == "per-player":
        return who == "habit"
    return who in SCREEN_READERS


class ScreenRecord:
    """solver.play_fight 的记录器包装：进场时打开 track_seen（人看到的 `?` 规则），其余钩子和属性原样转给里面那个（可以是 None）。"""
    _HOOKS = ("before_decision", "before_play", "after_play", "before_end_turn", "after_end_turn", "leave", "rest")

    def __init__(self, inner=None):
        object.__setattr__(self, "_inner", inner)

    def __setattr__(self, k, v):                            # play_fight 写 record.belief：两边都写
        object.__setattr__(self, k, v)
        if self._inner is not None:
            setattr(self._inner, k, v)

    def enter(self, run, f, kinds):
        f.track_seen = True
        h = getattr(self._inner, "enter", None) if self._inner is not None else None
        if h is not None:
            h(run, f, kinds)

    def __getattr__(self, name):                            # 只在本对象没有这个属性时才到这里
        inner = object.__getattribute__(self, "_inner")
        if inner is not None:
            return getattr(inner, name)
        if name in ScreenRecord._HOOKS:
            return lambda *a, **k: None
        raise AttributeError(name)                          # run_once 的 getattr(record, "auto_rest", None) 拿到 None


def screen(who, record=None):
    """按 tracks_screen(who) 给记录器包一层 ScreenRecord；不需要时原样返回（可能是 None）。"""
    return ScreenRecord(record) if tracks_screen(who) else record


# ---------------------------------------------------------------- 固定节点
def fixed_node(run, i):
    """第 i 层（run.layers 的 0 起下标；modelrun 的「Layer i」是 i+1）固定打的节点。PROTO_NODES=route 时返回 None。
    规则 = 第 0 个节点（NODE_RULE "index0"）。依据（core/adventure.py make_layers / _roll_world，2026-11-03 读码 + 300 张图核对）：
      · 一层的 2–3 个节点同机制、同角色（teach / test）、同 kind（curriculum=4 下全是 fight）：[Node(...) for _ in range(n)]；
      · 里程碑按层发（_milestones 选中的层里 for x in fights[at]: x.reward = True），不按节点 —— 300 张图 2,400 个战斗层里 0 层的
        reward / 机制 / 角色随节点而变；
      · 敌人数值由同一条流按节点顺序逐个独立抽（make_enemy），同分布、可交换：第 0 个与随机一个同分布（300 张图上血 / 攻击均值
        teach 6.49 / 8.12 对 6.44 / 8.02，test 6.42 / 8.08 对 6.49 / 8.05），不抽新的随机数，不挪任何流；
      · 也是 modelrun 回复解析两次失败时的取值（第一个选项）和现有分析代码一直用的 run.fight_at(i, 0)。"""
    run.layers[i]                                           # 越界照常报错
    return 0 if NODES == "fixed" else None


def fixed_fight(run, i):
    j = fixed_node(run, i)
    assert j is not None, "PROTO_NODES=route：节点由玩家选，没有固定的一场"
    return run.fight_at(i, j)


# ---------------------------------------------------------------- 补丁（setup 装，teardown 撤）
_ORIG = {}                                                  # 被换掉的原对象


def _no_take(run, know, met):
    return None


def _no_milestone(node):
    return False


def _refuse_take(self, name):
    raise RuntimeError(f"原型 {PROTO_VERSION}：拿牌已删（PROTO_LOOT=0），入口不能再问 `You may take one card:`（想拿 {name!r}）")


def _refuse_reward(self, key):
    raise RuntimeError(f"原型 {PROTO_VERSION}：里程碑属性奖励已删（PROTO_LOOT=0），入口不能再问 `Choose one:`（想拿 {key!r}）")


def _install_noloot():
    import adventure, solver
    if "run_once" in _ORIG:
        return
    R = adventure.Run
    _ORIG.update(run_once=solver.run_once, pays_milestone=adventure.pays_milestone,
                 take=R.__dict__["take"], apply_reward=R.__dict__["apply_reward"], _fight=R.__dict__["_fight"])
    orig, sig = solver.run_once, inspect.signature(solver.run_once)

    @functools.wraps(orig)
    def run_once(*a, **kw):
        tp = sig.bind_partial(*a, **kw).arguments.get("take_policy")
        if tp not in (None, _no_take):
            raise ValueError(f"原型 {PROTO_VERSION}：拿牌已删（PROTO_LOOT=0），不能再传 take_policy")
        if "take_policy" not in kw and len(a) < list(sig.parameters).index("take_policy") + 1:
            kw["take_policy"] = _no_take                    # run_once 里 take_policy 优先于路线和盲线的拿牌
        return orig(*a, **kw)
    solver.run_once = run_once
    adventure.pays_milestone = _no_milestone                 # solver.run_once 按属性读它（core/solver.py:1422）
    R.take, R.apply_reward = _refuse_take, _refuse_reward
    orig_fight = _ORIG["_fight"]

    def _fight(self, enemy, shuffle, boss=False):
        have, start = collections.Counter(self.deck_list), collections.Counter(self._pristine_deck)
        if have - start:
            raise RuntimeError(f"原型 {PROTO_VERSION}：拿牌已删，牌组却多了 {dict(have - start)}（有路径绕过了补丁直接往 deck_list 加牌）")
        return orig_fight(self, enemy, shuffle, boss)
    R._fight = _fight
    solver._proto_noloot = True


def _remove_noloot():
    import adventure, solver
    if "run_once" not in _ORIG:
        return
    solver.run_once = _ORIG.pop("run_once")
    adventure.pays_milestone = _ORIG.pop("pays_milestone")
    R = adventure.Run
    R.take, R.apply_reward, R._fight = _ORIG.pop("take"), _ORIG.pop("apply_reward"), _ORIG.pop("_fight")
    if hasattr(solver, "_proto_noloot"):
        del solver._proto_noloot


def _install_nodes():
    import adventure
    if "choose" in _ORIG:
        return
    orig = _ORIG["choose"] = adventure.Run.__dict__["choose"]

    def choose(self, i, rng, want_rest, want_elite):
        layer = self.layers[i]
        if any(n.kind == "rest" for n in layer.nodes):      # 休息层（自动补给）照旧
            return orig(self, i, rng, want_rest, want_elite)
        j = fixed_node(self, i)
        return j, layer.nodes[j].kind
    adventure.Run.choose = choose


def _remove_nodes():
    import adventure
    if "choose" in _ORIG:
        adventure.Run.choose = _ORIG.pop("choose")


ORACLE_AUTO = dict(attached=0)                              # 包装自动接上否决的场数（核对用）


def _install_oracle_veto():
    """PROTO_REFS=c：solver.play_fight 包一层（run_once 按模块全局名调它，所以 run_once 里的每一场都经过这里）。
    全知那场（information == "oracle"、没有 act_policy / blind / heal_veto）接上 r1v2.oracle_heal_veto；其余原样。"""
    import solver
    if "play_fight" in _ORIG:
        return
    orig = _ORIG["play_fight"] = solver.play_fight
    names = list(inspect.signature(orig).parameters)[5:]    # cap, count, information, blind, enrage_budget, record, dodge_hand, ...

    @functools.wraps(orig)
    def play_fight(run, f, know, kinds, heal_at, *rest, **kw):
        if rest:                                            # 位置参数传到 cap 之后的（run_once / antagonist_boss 都按关键字传，很少走这里）
            kw.update(zip(names, rest))
        if (kw.get("heal_veto") is None and kw.get("act_policy") is None and kw.get("blind") is None
                and kw.get("information", "oracle") == "oracle" and oracle_veto_on()):
            import r1v2
            kw["heal_veto"] = r1v2.oracle_heal_veto(know, kinds, kw.get("enrage_budget", 0), kw.get("offence_cap"), kw.get("dodge_hand", False))
            ORACLE_AUTO["attached"] += 1
        return orig(run, f, know, kinds, heal_at, **kw)
    solver.play_fight = play_fight


def _install_boss_turncap():
    """PROTO_BOSS_TURNCAP（boss 第二版，33 号文档）：solver.play_fight 包一层 —— 没显式传 cap、且这一场的敌人记了 _turn_cap（boss）的，cap = 它
    （solver.play_fight 默认 cap=40，与 Fight.over 补丁同一个数法）。显式传了 cap 的调用（核对的控制场景）原样。默认 none 下不装。"""
    import solver
    if "play_fight_turncap" in _ORIG:
        return
    orig = _ORIG["play_fight_turncap"] = solver.play_fight

    @functools.wraps(orig)
    def play_fight(run, f, know, kinds, heal_at, *rest, **kw):
        c = getattr(f.enemy, "_turn_cap", None)
        if c and not rest and "cap" not in kw:
            kw["cap"] = c
            BOSS_TURNCAP_AUTO["attached"] += 1
        return orig(run, f, know, kinds, heal_at, *rest, **kw)
    solver.play_fight = play_fight


def _remove_boss_turncap():
    import solver
    if "play_fight_turncap" in _ORIG:
        assert solver.play_fight.__wrapped__ is _ORIG["play_fight_turncap"], "solver.play_fight re-wrapped above the boss turn cap wrapper"
        solver.play_fight = _ORIG.pop("play_fight_turncap")


BOSS_TURNCAP_AUTO = collections.Counter()


def _remove_oracle_veto():
    import solver
    if "play_fight" in _ORIG:
        solver.play_fight = _ORIG.pop("play_fight")


class FixedPile:
    """PROTO_HAND=fixed 的牌堆（候选）：不抽牌。每场开局和每个 END 之后（end_turn → refill），手里正好是这条命的牌组里还有的每种牌各一张。
    · names 是 Fight 传进来的 deck_list 本身（= Run.deck_list 同一个对象，core/adventure.py Run._fight），不是副本：出过的治疗由 Fight.play
      从里面删掉（:1723-1729），下一次 refill 就看得到 —— 一条命 3 次治疗，删完就不再出现；一回合最多 1 次（手里只有一张）。
    · 按牌名字母序排。原型（世界 A、names_key 0）里所有图和 boss 牌名相同，顺序处处相同，位置不比牌名多透露什么；多世界时牌名重抽。
    · draw / discard 永远是空表：引擎的补闪（_offer_dodge、_guarantee_dodge）、诱饵（pierce_returns_block）只从这两堆挪牌，于是什么也不做；
      不洗牌、不碰 rng。接口与 camp.Pile 相同（hand / draw / discard / hand_size / guaranteed / play / end_turn / refill / _kinds / _return）。"""
    RULE = "fixed hand: one card of each kind still in the life's deck, refreshed at fight start and after every END; heal exhausts as before"

    def __init__(self, names, deck, rng, hand_size=None, guaranteed=None):
        import camp
        self.deck, self.rng, self.names = deck, rng, names
        self.hand_size = camp.HAND_SIZE if hand_size is None else hand_size
        self.guaranteed = camp.GUARANTEED if guaranteed is None else guaranteed
        self.draw, self.discard, self.hand = [], [], []
        self._opening = False
        self.refill()

    def _kinds(self, names):
        return [self.deck[n].kind for n in names]

    def _return(self, pool, name):
        pool.append(name)

    def refill(self):
        one = {}
        for n in sorted(set(self.names)):
            one.setdefault(self.deck[n].kind, n)
        self.hand[:] = sorted(one.values())                 # 原地换：与 camp.Pile 一样，整场同一个 hand 对象

    def play(self, name):
        if name not in self.hand:
            return False
        self.hand.remove(name)
        return True

    def end_turn(self):
        # 连续出闪的计数（DODGE_RUN_LIMIT）。Fight.end_turn 在敌人那一击结算之后、回合号加一之前调这里，每个 END 一次
        # （怪在这一回合被打死时 Fight.end_turn 提前返回，不调 —— 那一场已经赢了）。回合开头手里一定有闪（闪不会用完），
        # 所以 END 时闪不在手里 ⇔ 这一回合出了闪；闪 2 费、能量 2，出闪的回合不会再出别的。
        dodge = next((n for n in sorted(set(self.names)) if self.deck[n].kind == "dodge"), None)
        self.dodge_run = self.dodge_run + 1 if dodge is not None and dodge not in self.hand else 0
        if WARDLIMIT != "off":                              # 封印时限：Fight.end_turn 在封印结算之后才调这里，读到的是这一 END 之后的封印格
            f = getattr(self, "fight", None)
            if f is not None and "ward" in f.parts:
                post = f.state[("them", "ward")]
                pre = 1 if self.ward_prev is None else self.ward_prev   # 一场开头封着
                self.ward_run = self.ward_run + 1 if pre > 0 and post > 0 else 0
                self.ward_prev = post
        self.refill()

    dodge_run = 0                                           # 类属性作默认值：实例在第一次 END 时写自己的
    ward_run = 0                                            # PROTO_WARDLIMIT：同上（off 下实例从不写）
    ward_prev = None


def ended_by(f):
    """这一场怎么结束的：'won' / 'died'（自己血 ≤ 0）/ 'dodge_run'（连续闪避终止）/ 'turn_cap'（回合上限）/ None（还没结束）。
    后两种只在 PROTO_HAND=fixed 下会发生；双方都活着才算。"""
    s = f.state
    if s[("me", "hp")] <= 0:
        return "died"
    if s[("them", "hp")] <= 0:
        return "won"
    if HAND != "fixed":
        return None
    if getattr(f.pile, "dodge_run", 0) >= DODGE_RUN_LIMIT:
        return "dodge_run"
    if ward_limited(f):
        return "ward_limit"
    if f.turn - 1 >= turn_cap_of(f):
        return "turn_cap"
    return None


def ward_limited(f):
    """PROTO_WARDLIMIT=N：这一场封着的连续回合数到了 N（off 下永远假）。"""
    return WARDLIMIT != "off" and getattr(f.pile, "ward_run", 0) >= int(WARDLIMIT)


def turn_cap_of(f):
    """这一场的回合上限：boss 敌人记了 _turn_cap（PROTO_BOSS_TURNCAP，antagonist_boss.build_boss 记）就用它，否则 TURN_CAP（默认下永远是 TURN_CAP）。"""
    return getattr(f.enemy, "_turn_cap", None) or TURN_CAP


def timed_out(f):
    """这一场是不是因为提前结束的规则（连续闪避终止或回合上限）结束的：双方都还活着（只在 PROTO_HAND=fixed 下会发生）。"""
    return ended_by(f) in ("dodge_run", "turn_cap", "ward_limit")


class FixedPileCD(FixedPile):
    """候选 v3 PROTO_DOUBLER=turncd 的固定手牌（18 §4）。在 FixedPile 之上两条，都在 Fight.end_turn 调 pile.end_turn() 的那一刻做
    （敌人那一击、动量 / 蓄力 / 守相 / 标记都已结算，换阶段、_slots_moved、_mark 还没做 —— 所以引擎自己的 seen、modelrun 那一行 END 差都看得到）：
      · 增伤只对本回合的攻击生效：END 时把这一场的 ("me", "double") 清成 0（引擎原来留到下一次攻击）；
      · 冷却一回合：这一回合出过增伤（refill 时发到手里、END 时不在手里）→ 下一回合 refill 不发增伤；再下一回合恢复（冷却那一回合手里本来就没有，
        不算出过）。每场新建牌堆，开局没有冷却；boss 是一场（换阶段不新建牌堆），冷却跨阶段照算。
    Fight 由构造它的那一帧找（Fight.__post_init__ 里 `self.pile = Pile(...)`，往上找局部变量 self 是 adventure.Fight 的帧）；找不到就报错。
    存的是 Fight 本身（不是 weakref）：copy.deepcopy(fight) 时牌堆跟着指向副本。不碰随机数；其余同 FixedPile。
    CP（核对的反证开关，默认 None）："no_clear" = END 不清增伤；"no_cooldown" = 不冷却；"long_cooldown" = 冷却两回合。生产里必须是 None。"""
    RULE = (FixedPile.RULE + "; doubler (PROTO_DOUBLER=turncd): its x2 counts only for attacks in the turn it is played (the flag is cleared "
            "at END), and a doubler played in a turn is left out of the next turn's hand (back the turn after; no cooldown at fight start)")
    CP = None
    CPS = (None, "no_clear", "no_cooldown", "long_cooldown")

    def __init__(self, names, deck, rng, hand_size=None, guaranteed=None):
        self.fight = self._owner()
        self.cooldown = 0                                   # 还要空几回合（0 = 下一次 refill 照发）
        self._offered = False                               # 这一回合开局手里有没有增伤
        super().__init__(names, deck, rng, hand_size, guaranteed)

    @staticmethod
    def _owner():
        import adventure
        fr = sys._getframe(2)
        for _ in range(4):
            if fr is None:
                break
            me = fr.f_locals.get("self")
            if isinstance(me, adventure.Fight):
                return me
            fr = fr.f_back
        raise RuntimeError("FixedPileCD: no adventure.Fight is constructing this pile (PROTO_DOUBLER=turncd needs the fight's state)")

    def _doubler(self):
        return next((n for n in sorted(set(self.names)) if self.deck[n].kind == "buff_mark"), None)

    def refill(self):
        super().refill()
        d = self._doubler()
        if self.cooldown and d in self.hand:
            self.hand.remove(d)
        self._offered = d is not None and d in self.hand

    def end_turn(self):
        d = self._doubler()
        played = self._offered and d not in self.hand
        if self.CP != "no_clear":
            self.fight.state[("me", "double")] = 0
        if self.CP == "no_cooldown":
            self.cooldown = 0
        elif played:
            self.cooldown = 2 if self.CP == "long_cooldown" else 1
        elif self.cooldown:                                 # 这一回合是冷却回合（refill 时扣下了增伤）：用掉一回合
            self.cooldown -= 1
        super().end_turn()                                  # 连续闪避计数 + refill（refill 读上面定好的冷却）


def _pile_class():
    return FixedPileCD if DOUBLER == "turncd" else FixedPile


def _install_hand():
    import adventure
    if "Pile" in _ORIG:
        if adventure.Pile is not _pile_class():            # 同一进程里换了 DOUBLER（archived() / 核对）：只换牌堆类
            adventure.Pile = _pile_class()
        return
    F = adventure.Fight
    _ORIG["Pile"], _ORIG["over"] = adventure.Pile, F.__dict__["over"]
    adventure.Pile = _pile_class()
    orig_over = _ORIG["over"]

    def over(self):
        # 连续第 DODGE_RUN_LIMIT 个出闪的回合结算之后 / 打满 TURN_CAP 个 END：一场结束，won() 为假（双方都活着）
        # boss 第二版：boss 敌人记了 _turn_cap（PROTO_BOSS_TURNCAP）就按它（turn_cap_of；没记 = TURN_CAP，默认下逐字同前）
        return (orig_over(self) or getattr(self.pile, "dodge_run", 0) >= DODGE_RUN_LIMIT or ward_limited(self)   # 封印时限（off 下恒假）
                or self.turn - 1 >= turn_cap_of(self))
    F.over = over


def _remove_hand():
    import adventure
    if "Pile" in _ORIG:
        adventure.Pile = _ORIG.pop("Pile")
        adventure.Fight.over = _ORIG.pop("over")


def _install_tune():
    """PROTO_TUNE：把 TUNINGS[TUNE] 写进 TUNING。第一次写之前的值记在 _ORIG["tune"]（teardown 还原到这里）；之后每次 setup() 重写
    （activate_registered 把 ward_test_start 改回 0，hp_momentum 不重设）。"""
    from adventure import TUNING
    over = dict(TUNINGS[TUNE])
    if WARDTESTSTART != "default":
        over["ward_test_start"] = int(WARDTESTSTART)
    if "tune" in _ORIG and set(_ORIG["tune"]) != set(over):
        TUNING.update(_ORIG.pop("tune"))
    if "tune" not in _ORIG:
        _ORIG["tune"] = {k: TUNING[k] for k in over}        # 键不存在就 KeyError：宁可吵
    TUNING.update(over)


def _remove_tune():
    from adventure import TUNING
    if "tune" in _ORIG:
        TUNING.update(_ORIG.pop("tune"))


def _install_rage():
    """PROTO_RAGE=off：TUNING rage_ratio = 0（第一次写之前的值记在 _ORIG["rage"]，teardown 还原到这里；之后每次 setup() 重写，
    activate_registered 会写回 20），再给 adventure.make_enemy 包一层（只装一次）：rage_ratio == 0 时把建出的敌人的 rage 置 0 ——
    引擎 scaled() 的 floor=1 让 rage_ratio=0 单独写仍是 rage 1。Run._roll_world 按模块全局名调 make_enemy，所以 ap.build、
    antagonist_boss.build_boss、直接 adventure.Run(...)._roll(s) 都经过它；只改 rage 一个字段，不抽随机数。"""
    import adventure
    from adventure import TUNING
    if "rage" not in _ORIG:
        _ORIG["rage"] = TUNING["rage_ratio"]                # 键不存在就 KeyError：宁可吵
    TUNING["rage_ratio"] = 0
    if "make_enemy" in _ORIG:
        return
    orig = _ORIG["make_enemy"] = adventure.make_enemy

    @functools.wraps(orig)
    def make_enemy(*a, **kw):
        e = orig(*a, **kw)
        if TUNING["rage_ratio"] == 0:
            e.rage = 0
        return e
    adventure.make_enemy = make_enemy


def _remove_rage():
    import adventure
    from adventure import TUNING
    if "make_enemy" in _ORIG:
        adventure.make_enemy = _ORIG.pop("make_enemy")
    if "rage" in _ORIG:
        TUNING["rage_ratio"] = _ORIG.pop("rage")


_LADDER_HOLD = [0]                                          # > 0：setup() 先不装阶梯（ladder_outside 块里）


def _install_ladder():
    """PROTO_LADDER=1：装 penalty_ladder（它的默认表 LADDER）。本模块已装着 → 什么也不做；别处手动装着 → 报错（两处同时管一个补丁会撤错）。"""
    import penalty_ladder as pl
    if "ladder" in _ORIG and pl.installed():
        return
    if pl.installed():
        raise RuntimeError("penalty_ladder 已经被别处手动装着（不是 PROTO_LADDER 装的）：先 penalty_ladder.remove()，或者不设 PROTO_LADDER")
    pl.install()
    _ORIG["ladder"] = True


def _remove_ladder():
    """撤掉本模块装的阶梯（别处手动装的不碰）；撤了返回 True。装好之后有别的补丁换过 Fight 的那几个属性 → penalty_ladder.remove() 报错，
    不悄悄还原（例如没经过 ladder_outside 就把 boss 层装 / 撤在阶梯之下）。"""
    if "ladder" not in _ORIG:
        return False
    import penalty_ladder as pl
    pl.remove()
    del _ORIG["ladder"]
    return True


def _sync_ladder():
    if LADDER:
        if not _LADDER_HOLD[0]:
            _install_ladder()
    else:
        _remove_ladder()


@contextlib.contextmanager
def ladder_outside(reinstall):
    """PROTO_LADDER=1：阶梯要在 boss 层的 Fight 补丁之外（penalty_ladder 的次序）。antagonist_boss.setup_boss / teardown_boss 用它包住自己
    动 Fight 的那一段：进块时撤掉本模块装的阶梯（Fight 的属性回到装之前那一层）、块里的 setup() 不装；出块时
      reinstall="switch"    按开关装（setup_boss：块里那次 ap.setup() 没装）；
      reinstall="if-lifted" 进块时撤过才装回（teardown_boss：先 teardown() 撤过阶梯再 teardown_boss 时不会装回来）。
    默认（PROTO_LADDER=0，本模块没装阶梯）什么也不做、不导入 penalty_ladder。块里抛异常：不装回，异常照常抛出。"""
    if reinstall not in ("switch", "if-lifted"):
        raise ValueError(f"reinstall={reinstall!r}：只能是 switch / if-lifted")
    if not LADDER and "ladder" not in _ORIG:
        yield
        return
    lifted = _remove_ladder()
    _LADDER_HOLD[0] += 1
    try:
        yield
    finally:
        _LADDER_HOLD[0] -= 1
    if reinstall == "switch":
        _sync_ladder()
    elif lifted:
        _install_ladder()


def _install_world():
    """PROTO_WORLD 非 A：把外衣写进 TUNING（proto_worlds.apply）。第一次写之前的值记在 _ORIG["world"]（回到 A / teardown 还原到这里）；
    每次 setup() 重写（setup 开头把 names_key 写回 0，调参把 block_pct 写回 45）。"""
    import proto_worlds
    from adventure import TUNING
    if "world" not in _ORIG:
        _ORIG["world"] = {k: TUNING[k] for k in proto_worlds.KEYS_WRITTEN}
    proto_worlds.apply(WORLD, TUNING)


def _remove_world():
    from adventure import TUNING
    if "world" in _ORIG:
        TUNING.update(_ORIG.pop("world"))


def life_deck_len():
    """一条新命的起始牌组张数：登记值 18；PROTO_HEAL=off（修订 6）时少 3 张治疗 = 15。各处「满血、整副起始牌组」的断言读这里。"""
    return 18 - 3 if HEAL == "off" else 18


def _install_heal():
    """PROTO_HEAL=off（修订 6，43 §19）：TUNING deck_counts 里治疗 0 张、rest_pct = r′；Run._roll_identity 包一层，掷完身份后把上限血换成 M′
    （先核对这条命的 M、h 就是 proto_worlds 表里这个世界的数，不是就报错）。第一次写之前的值记在 _ORIG["heal"]；每次 setup() 重写。"""
    import proto_worlds
    from adventure import TUNING, Run
    t = proto_worlds.healoff(WORLD)
    if "heal" not in _ORIG:
        _ORIG["heal"] = dict(deck_counts=TUNING["deck_counts"], rest_pct=TUNING["rest_pct"], roll=Run._roll_identity)
    if TUNING["rest_pct"] not in (t["rest_pct"], t["rest_pct_new"]):
        raise RuntimeError(f"PROTO_HEAL=off: TUNING rest_pct {TUNING['rest_pct']} is not world {WORLD}'s {t['rest_pct']}")
    TUNING["deck_counts"] = dict(TUNING["deck_counts"], heal=0)          # 新 dict：不改登记值的那个对象
    TUNING["rest_pct"] = t["rest_pct_new"]
    if "wrap" in _ORIG["heal"]:                                          # 重复 setup()（audit 进程内用）：装回同一个函数对象（audit 按身份查补丁点）
        Run._roll_identity = _ORIG["heal"]["wrap"]
        return
    orig = _ORIG["heal"]["roll"]

    def _roll_identity(self, *a, **kw):
        orig(self, *a, **kw)
        if self._hp_fixed:
            return
        amount = {c.kind: c.amount for c in self.deck.values()}["heal"]
        if (self.max_hp, amount) != (t["max_hp"], t["heal"]):
            raise RuntimeError(f"PROTO_HEAL=off: this run has max HP {self.max_hp} and heal {amount}, world {WORLD} should have "
                               f"{t['max_hp']} and {t['heal']} (proto_worlds.healoff)")
        self.max_hp = self.base_max_hp = self.recoverable_max_hp = t["max_hp_new"]
    _roll_identity._heal_off = True
    _ORIG["heal"]["wrap"] = Run._roll_identity = _roll_identity


def _install_restamt():
    """PROTO_RESTAMT=NAME：Run._roll 包一层记下 salt；Run.auto_resupply 换成「hp += 表里这张图的量，封顶上限血」。每次 setup() 重读表。"""
    from adventure import Run
    _RESTAMT_TABLE.clear()
    _RESTAMT_TABLE.update({int(k): int(v) for k, v in json.loads((RESTAMT_DIR / f"{RESTAMT}.json").read_text())["amounts"].items()})
    if "restamt" in _ORIG:
        return
    roll, sup = Run.__dict__["_roll"], Run.__dict__["auto_resupply"]

    def _roll(self, salt):
        self._restamt_salt = salt
        return roll(self, salt)

    def auto_resupply(self):
        salt = getattr(self, "_restamt_salt", None)
        if salt not in _RESTAMT_TABLE:
            raise RuntimeError(f"PROTO_RESTAMT={RESTAMT}: map salt {salt} is not in the table")
        before = (self.hp, self.max_hp, self.base_atk, self.poison)
        self.hp = min(self.max_hp, self.hp + _RESTAMT_TABLE[salt])
        self._mark_run_changes(before)
        return before[0], self.hp
    _ORIG["restamt"] = dict(roll=roll, sup=sup)
    Run._roll, Run.auto_resupply = _roll, auto_resupply


def _remove_restamt():
    from adventure import Run
    o = _ORIG.pop("restamt", None)
    if o is not None:
        Run._roll, Run.auto_resupply = o["roll"], o["sup"]
    _RESTAMT_TABLE.clear()


def _remove_heal():
    from adventure import TUNING, Run
    if "heal" in _ORIG:
        o = _ORIG.pop("heal")
        Run._roll_identity = o["roll"]
        TUNING["deck_counts"] = o["deck_counts"]
        TUNING["rest_pct"] = o["rest_pct"]


_AFTER_SETUP = {}                                           # name → fn：setup() 最后调（boss 层登记它的 TUNING 键）


def register_after_setup(name, fn):
    _AFTER_SETUP[name] = fn


def unregister_after_setup(name):
    _AFTER_SETUP.pop(name, None)


def setup():
    import devworld
    from adventure import TUNING
    _guard_stale()
    devworld.activate_registered(12)          # PROTOTYPE_12：auto_rest=1，别的旋钮同登记 12（含 marks=1；统一画面在下面覆盖；boss_no_probe=1，boss 层的钩子在最后写回）
    devworld.use_rotation(PROTO)
    TUNING["names_key"] = 0
    import solver, r1v2
    assert set(solver.MECHANICS) == set(PROTO), solver.MECHANICS   # ALL 另含 double/tempo（玩家自己牌的知识）
    assert TUNING["auto_rest"] == 1 and TUNING["curriculum"] == 4, (TUNING["auto_rest"], TUNING["curriculum"])
    (_install_tune if TUNE != "none" or WARDTESTSTART != "default" else _remove_tune)()   # 原规则默认不变
    (_install_rage if RAGE == "off" else _remove_rage)()    # PROTO_RAGE：同上（每次 setup 都重写 rage_ratio=0，make_enemy 包装只装一次）；on 下什么也不做
    if WORLD != "A" or "world" in _ORIG:                    # 世界外衣（43 号文档）：调参之后、任何建图之前；A（默认）下什么也不做
        (_install_world if WORLD != "A" else _remove_world)()
    TUNING["hidden_props"] = HIDES[HIDE]                     # 画面减项（PROTO_HIDE；默认 () = 旧画面）
    TUNING["ward_seen_on_block"] = int(WARDSEEN == "acted")  # 封印格显示（PROTO_WARDSEEN；默认 0 = 旧画面）
    TUNING["ward_block_only"] = int(WARDSTRICT == "blockonly")  # 破势解法（PROTO_WARDSTRICT；默认 0 = 原规则）
    if HEAL == "off" or "heal" in _ORIG:                    # 修订 6（43 §19）：外衣之后（r′ 覆盖外衣的补给）、任何建图之前；on（默认）下什么也不做
        (_install_heal if HEAL == "off" else _remove_heal)()
    if RESTAMT != "off" or "restamt" in _ORIG:              # 休息补给按图收紧（11-13 扫描）：off（默认）下什么也不做
        (_install_restamt if RESTAMT != "off" else _remove_restamt)()
    (_remove_noloot if LOOT else _install_noloot)()
    (_install_nodes if NODES == "fixed" else _remove_nodes)()
    r1v2.ENERGY_VETO = REFS == "c"                          # R1v2 c / b（PROTO_REFS）
    (_install_oracle_veto if REFS == "c" else _remove_oracle_veto)()
    (_install_hand if HAND == "fixed" else _remove_hand)()
    if BOSS_TURNCAP != "none":                              # boss 第二版（33 号文档）：全知否决包装之后装；none（默认）下什么也不做
        _install_boss_turncap()
    _sync_markmap()                                         # PROTO_MARKMAP=world：Run._roll_world 的绊线；salt（默认）下撤掉 / 什么也不装
    if DISPLAY != "per-player":
        _ORIG.setdefault("display", {k: TUNING[k] for k in ("marks", "state_slots")})   # 第一次：装画面之前的值，teardown 还原到这里
        apply_display()
        if DISPLAY == "hidden" and not _ORIG.get("_warned"):
            _ORIG["_warned"] = True
            print("PROTO_DISPLAY=hidden：regsel.r1_wins、r1v2.display()、antagonist_diag 仍写死 R1_DISPLAY（seen），R1v2 断言 seen —— "
                  "这些参照还不在统一画面上（见模块说明）", file=sys.stderr, flush=True)
    elif "display" in _ORIG:
        TUNING.update(_ORIG.pop("display"))
    for fn in list(_AFTER_SETUP.values()):                  # boss 层：把 activate_registered 改回登记值的 boss 键写回 setup_boss 的值
        fn()
    _sync_ladder()                                          # PROTO_LADDER=1：最后装（别的补丁、boss 层钩子之后；已装着就不再装）；0 下什么也不做
    _sync_guardcode()                                       # 候选 v3 PROTO_GUARDCODE=map：在别的补丁之后装画面 / 日志补丁（只动 _row、HarnessLog.append）；engine 下什么也不做


def teardown():
    """撤掉 setup() 的补丁（阶梯、删奖励、固定节点、全知否决包装、手牌、绊线、怒气包装）、调参覆盖、rage_ratio 和统一画面。幂等。
    不撤 activate_registered / use_rotation / names_key，不动 r1v2.ENERGY_VETO（那是参照的旗子，不是引擎补丁）。
    阶梯（PROTO_LADDER=1）最先撤：它在最外层。装了 boss 层时 teardown_boss() 在前在后都可以（teardown_boss 用 ladder_outside 撤 / 装回）。"""
    from adventure import TUNING
    _remove_guardcode()                                     # 候选 v3：最后装的最先撤（没装着什么也不做）
    r1 = sys.modules.get("r1v2")                            # 候选 v3：全知的 v3 包装（r1v2 的 after-setup 钩子装的 solver.act 包装；没装着什么也不做）
    if r1 is not None and hasattr(r1, "remove_oracle_v3"):
        r1.remove_oracle_v3()
    if r1 is not None and hasattr(r1, "remove_r1_v3"):     # 候选 v3：R1 的 v3 包装（cautious.Cautious.act 的包装；没装着什么也不做）
        r1.remove_r1_v3()
    _remove_ladder()
    _remove_noloot()
    _remove_nodes()
    _remove_boss_turncap()                                  # boss 第二版：在全知否决包装外面，先撤（没装着什么也不做）
    _remove_oracle_veto()
    _remove_hand()
    _remove_markmap()
    _remove_restamt()                                       # 休息补给收紧（没装着什么也不做）
    _remove_heal()                                          # 修订 6：在外衣之前撤（没装着什么也不做）
    _remove_world()                                         # 世界外衣：在调参之前撤（没装着什么也不做）
    _remove_tune()
    _remove_rage()
    if "display" in _ORIG:
        TUNING.update(_ORIG.pop("display"))


@contextlib.contextmanager
def switched(**kw):
    """核对专用：进程内临时换 incoming / threat / markmap（别的开关不许），退出时还原（12 §4.3）。
    在块外建的 boss ctx 进块后 antagonist_boss.play_boss 的 ap.switches() == ctx["proto"] 断言会失败，逼着在块里重建（故意的）。"""
    names = dict(incoming=("INCOMING", INCOMINGS), threat=("THREAT", THREATS), markmap=("MARKMAP", MARKMAPS))
    bad = set(kw) - set(names)
    if bad:
        raise ValueError(f"switched() only takes {sorted(names)}: {sorted(bad)}")
    for k, v in kw.items():
        if v not in names[k][1]:
            raise ValueError(f"{k}={v!r}: allowed {names[k][1]}")
    g = globals(); old = {k: g[names[k][0]] for k in kw}
    try:
        for k, v in kw.items():
            g[names[k][0]] = v
        _sync_markmap()
        yield switches()
    finally:
        for k, v in old.items():
            g[names[k][0]] = v
        _sync_markmap()


# ---------------------------------------------------------------- 标记代号表（PROTO_MARKMAP；12 §4.3、§7；D13）
class MarkTableMissing(RuntimeError):
    pass


class _UnboundMarkTable(tuple):
    """PROTO_MARKMAP=world 下 Run 建好、还没绑世界表时的占位。元素 = 按 salt 的表（C 层的相等 / repr / pickle 照常），
    但 Python 层的取用（引擎的 marked_kind、END 写代号的 index、tuple(...)、迭代、in）一律报错：world 下忘了绑表，第一次用代号就大声失败，
    不会悄悄按 salt 跑（审查 B3）。"""

    def __new__(cls, items, salt):
        o = super().__new__(cls, items)
        o.salt = salt
        return o

    def _missing(self, *a, **k):
        raise MarkTableMissing(f"PROTO_MARKMAP=world: the Run for salt {self.salt} has no world mark table; "
                               f"bind it with antagonist_proto.set_mark_table before the first fight")
    __getitem__ = __iter__ = index = __contains__ = _missing

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):                         # antagonist_boss_check._survival_lines 的 deepcopy 安全
        return self

    def __reduce__(self):
        return (_UnboundMarkTable, (tuple(tuple.__iter__(self)), self.salt))


def _install_markmap():
    """只在 MARKMAP == "world" 或（候选 v3）GUARDCODE == "map" 时装（审查 A5：默认下什么也不装；两件事各看各的开关，guard_slot.tag_run 只给敌人
    加一个属性、不抽随机数）。包 Run._roll_world：引擎原样抽完（mark-v1 那一抽用它自己的 Random，
    别的流一个不动），再把 mark_perm 换成占位、mark_source 清空。ap.build、antagonist_boss.build_boss、直接 adventure.Run(...)._roll(s) 都经过它。"""
    import adventure
    if "roll_world" in _ORIG:
        return
    R = adventure.Run
    _ORIG["roll_world"] = orig = R.__dict__["_roll_world"]

    def _roll_world(self, salt):
        orig(self, salt)
        if MARKMAP == "world":
            self.mark_perm = _UnboundMarkTable(self.mark_perm, salt)
            self.mark_source = None
        if GUARDCODE == "map":                              # 候选 v3：给这张图的每个敌人记上守势映射的键（图 salt / boss salt）
            import guard_slot
            guard_slot.tag_run(self, salt)
        if GUARDSTART == "map":                             # 候选 v3b：地图上每场守势战的开场攻守建图时预抽（图 salt + 层 + 节点；boss 不管）
            import guard_slot
            guard_slot.tag_starts(self, salt)
    R._roll_world = _roll_world


def _remove_markmap():
    import adventure
    if "roll_world" in _ORIG:
        adventure.Run._roll_world = _ORIG.pop("roll_world")


def _sync_markmap():
    # 候选 v3：PROTO_GUARDCODE=map 也要这个包装（同一个包装做两件事，各看各的开关；默认 engine 下与原来逐字相同：只在 world 下装）
    (_install_markmap if (MARKMAP == "world" or GUARDCODE == "map" or GUARDSTART == "map") else _remove_markmap)()


def _sync_guardcode():
    """PROTO_GUARDCODE=map：装 guard_slot（adventure._row、modelrun.HarnessLog.append；幂等）。engine：本模块装过就撤，没装过什么也不导入。
    候选 v3b PROTO_GUARDSTART=map：装 guard_slot.install_start（Run._fight 的包装；幂等）；engine 下同理。"""
    if GUARDCODE == "map":
        import guard_slot
        guard_slot.install()
        _ORIG["guardcode"] = True
    else:
        _remove_guardcode()
    if GUARDSTART == "map":
        import guard_slot
        guard_slot.install_start()
        _ORIG["guardstart"] = True
    else:
        _remove_guardstart()


def _remove_guardcode():
    _remove_guardstart()
    if _ORIG.pop("guardcode", None):
        import guard_slot
        guard_slot.remove()


def _remove_guardstart():
    if _ORIG.pop("guardstart", None):
        import guard_slot
        guard_slot.remove_start()


def salt_mark_table(salt):
    """引擎的约定（core/adventure.py Run._roll_world：mark-v1:{key}:{salt}，key 为 0 时 mark-v1:{salt}）独立重写；
    给独立 boss / 单张图在 world 下当替身表用，也是默认（salt）下每个 Run 的表。"""
    import random
    from adventure import TUNING, Fight
    key = TUNING["identity_key"]
    return tuple(random.Random(f"mark-v1:{key}:{salt}" if key else f"mark-v1:{salt}").sample(list(Fight.MARK_ORDER), 5))


def world_mark_stream(map_salts, boss_salt, order):
    """D13：内容键（排序后的图 salt、boss salt、阶段顺序；identity_key 总在流名里 —— 新流，不需要兼容旧写法）。"""
    from adventure import TUNING
    return (f"{MARK_WORLD_STREAM}:{TUNING['identity_key']}:" + "|".join(str(int(s)) for s in sorted(int(x) for x in map_salts))
            + f":{int(boss_salt)}:" + ">".join(order))


def world_mark_table(map_salts, boss_salt, order):
    import random
    from adventure import Fight
    return tuple(random.Random(world_mark_stream(map_salts, boss_salt, order)).sample(list(Fight.MARK_ORDER), 5))


def set_mark_table(run, table, source):
    from adventure import Fight
    if MARKMAP != "world":
        raise RuntimeError("set_mark_table is only for PROTO_MARKMAP=world")
    if sorted(table) != sorted(Fight.MARK_ORDER):
        raise ValueError(f"not a mark table: {table}")
    run.mark_perm = tuple(table)
    run.mark_source = str(source)


def require_mark_table(run):
    """每个开打入口都调（antagonist_boss.play_map / play_boss、proto_play.play_life）；salt（默认）下什么也不做。"""
    if MARKMAP == "world" and (isinstance(run.mark_perm, _UnboundMarkTable) or not getattr(run, "mark_source", None)):
        raise MarkTableMissing(f"PROTO_MARKMAP=world: this Run has no world mark table (salt {getattr(run.mark_perm, 'salt', '?')})")


def mark_record(run, salt):
    """记录用（只在 world 下写进记录，默认记录不加键）；getattr，默认路径调到也不会崩（审查 B2）。"""
    return dict(rule=MARKMAP, source=getattr(run, "mark_source", None) or f"salt:{salt}",
                table=list(tuple.__iter__(run.mark_perm)))


@contextlib.contextmanager
def archived():
    """本进程临时换成 ARCHIVE 的开关（loot 开、route 节点、per-player 画面、参照 b：R1v2 b 版、全知不带否决）并重装；退出时换回
    环境变量的开关并重装。antagonist_boss.ORACLE_VETO 在里面临时置 None（跟 r1v2.ENERGY_VETO = False 走），退出时还原。
    退出后进程处在 setup() 之后的状态（不管进来之前调没调过）。boss 层（antagonist_boss）的 TUNING 键由它登记的钩子保持不变。
    存档里没有阶梯、不调参、有怒气：块里阶梯撤掉、调参键和 rage_ratio 还原、make_enemy 是引擎原函数；退出时按环境变量的开关装回
    （阶梯仍在 boss 层之外）。"""
    g = globals(); keys = dict(loot="LOOT", nodes="NODES", display="DISPLAY", refs="REFS", hand="HAND",
                               incoming="INCOMING", threat="THREAT", markmap="MARKMAP", ladder="LADDER", tune="TUNE", rage="RAGE")
    old = {k: g[v] for k, v in keys.items()}
    v3_old = {k.upper(): g[k.upper()] for k in V3_DEFAULTS} | dict(PROTO=PROTO, PAIRS=PAIRS)   # 候选 v3：存档里一个也没有（池是六种）
    abm = sys.modules.get("antagonist_boss")
    ov = getattr(abm, "ORACLE_VETO", None) if abm is not None else None
    teardown()
    try:
        for k, v in ARCHIVE.items():
            g[keys[k]] = v
        for k, v in V3_DEFAULTS.items():
            g[k.upper()] = v
        g["PROTO"] = POOL_MECHS[V3_DEFAULTS["pool"]]
        g["PAIRS"] = PAIRS_FULL
        if abm is not None:
            abm.ORACLE_VETO = None
        setup()
        yield settings()
    finally:
        teardown()
        for k, v in old.items():
            g[keys[k]] = v
        for k, v in v3_old.items():
            g[k] = v
        if abm is not None:
            abm.ORACLE_VETO = ov
        setup()


# ---------------------------------------------------------------- 输入 / 输出文件
def recorded(src):
    """输入文件是在哪组开关下跑的。没有 "proto" 键 = ARCHIVE（loot 取旧的 "loot" 键，缺省 True）。
    有 "proto" 键但没有 "refs" 的（2026-11-03 本开关之前写的）按 c 读：当时 R1v2 默认 c、antagonist_boss 的全知带否决；
    但那时 antagonist_preboss* / antagonist_diag 直接调 run_once 的全知不带否决 —— 这样的 boss 前结果文件一个也没有写出过。"""
    p = src.get("proto") or {}
    return dict(loot=bool(p.get("loot", src.get("loot", ARCHIVE["loot"]))), nodes=p.get("nodes", ARCHIVE["nodes"]),
                display=p.get("display", ARCHIVE["display"]), refs=p.get("refs", "c" if p else ARCHIVE["refs"]),
                hand=p.get("hand", "draw"),                 # PROTO_HAND 之前的文件都是抽牌
                incoming=p.get("incoming", "mute"), threat=p.get("threat", "plain"), markmap=p.get("markmap", "salt"),   # 12：之前的文件都是默认
                ladder=bool(p.get("ladder", False)), tune=p.get("tune", "none"),   # 11-03 夜：之前的文件都是默认（不装阶梯、不调参）
                rage=p.get("rage", "on"),                   # 11-04：之前的文件都有怒气
                **{k: p[k] for k in V3_KEYS if k in p and p[k] != default_of(k)})   # 候选 v3：没有这个键 = 默认（同 _now() 只记非默认）


def check_source(src, name="源文件"):
    rec = recorded(src); now = _now()
    if rec != now:
        raise AssertionError(f"{name}的开关 {rec} 与本进程 {now} 不一致；要接着用它，导出 {_env(rec)} 再跑")


def out_tag():
    """输出文件名后缀：存档开关 → ""（旧文件名，但已存在就拒绝覆盖）；否则 "_v2" + 偏离现行默认的开关。"""
    now = _now()
    if now == ARCHIVE:
        return ""
    # 候选 v3 的键（只在非默认时出现在 now 里）接在旧键之后；ladder_table 不在这里（下面的 -ladtab 后缀照旧给出表名）
    dev = "".join(f"-{k}{int(v) if isinstance(v, bool) else v}" for k, v in now.items()
                  if k != "ladder_table" and v != default_of(k))
    if LADDER and os.environ.get("PROTO_LADDER_TABLE", "v1") != "v1":
        # 11-04：阶梯表（penalty_ladder 的 PROTO_LADDER_TABLE）不是默认 v1 时文件名带表名。11-04 凌晨 t16 那批文件早于这一条，名字里没有
        # （它们实际装的表记在 proto.ladder_describe，c10v2 v1.3 的汇总按它核对）。
        dev += f"-ladtab{os.environ['PROTO_LADDER_TABLE']}"
    if LADDER and os.environ.get("PROTO_LADDER_MARK", "fight") != "fight":
        # 11-04：penalty_ladder v3.4 的 PROTO_LADDER_MARK（boss 的标记按代号数 k，决定 6）不是默认 fight 时文件名带上（-markpercode）
        dev += f"-mark{os.environ['PROTO_LADDER_MARK']}"
    return f"_{VERSION_TAG}{dev}"


def refuse_overwrite(path):
    path = pathlib.Path(path)
    if path.exists():
        raise SystemExit(f"{path} 已存在：不覆盖已有结果（换一个 OUTNAME）")
    return path


# ---------------------------------------------------------------- 建图
def build(salt):
    import adventure, devworld
    run = adventure.Run(SEED, validate=False); run._roll(salt)
    if MAPCHARGE != "none" or MAPGUARD != "none":           # 考试关的不规则节奏（候选）：给考试节点敌人挂预抽表（boss 用同名属性，_seq_apply 照做）
        import antagonist_boss as ab
        for i, layer in enumerate(run.layers):
            for k, node in enumerate(layer.nodes):
                if node.kind == "rest" or node.role != "test":
                    continue
                mechs = node.behaviour.split("+")
                if MAPCHARGE == "len234" and "charge" in mechs:
                    node.enemy._charge_len = ab.map_charge_lengths(salt, i, k)
                if MAPGUARD != "none" and "guard" in mechs:
                    node.enemy._guard_seq = ab.map_guard_schedule(salt, i, k, MAPGUARD)
    return run


def teach_index(run):
    fights = [L for L in run.layers if L.nodes[0].kind != "rest"]
    return {L.behaviour: i for i, L in enumerate(fights) if L.nodes[0].role == "teach"}


# ---------------------------------------------------------------- 冻结面板在现行版本下的重复（审查 2026-11-03）
LIVE_ROUTE_FIELDS = ("heal_at", "enrage_budget")


def live_route(route):
    """路线里在本进程开关下还影响对局的部分。现行版本（PROTO_LOOT=0、PROTO_NODES=fixed、auto_rest=1）下只剩 heal_at、enrage_budget：
    读码 core/solver.py run_once（:1335-1480）与 play_fight —— elite_at 只进 Run.choose 的 want_elite（固定节点的 choose 不看它，休息层自动）；
    rest_mode / cleanse_at / cap_safe_at 只在非自动休息的分支；reward 只在 pays_milestone 分支（删奖励后恒 False）；take / take_glut 只在
    拿牌分支（删奖励后 take_policy 恒「不拿」）。boss 命（antagonist_boss.play_boss）只读 heal_at、enrage_budget。别的开关下返回整条路线。"""
    if LOOT or NODES != "fixed":
        return route
    return tuple(getattr(route, k) for k in LIVE_ROUTE_FIELDS)


def habit_key(item):
    """一套冻结习惯在本进程开关下的行为键：底子、触发、反应、暗格判法、live_route(路线)（habit_job / antagonist_boss._policy 用到的全部字段）。"""
    import shortcut_screen as ss
    return (item["base"], item["trigger"], item["response"], item["dark"], live_route(ss.routes()[item["route"]]))


def blind_key(pair):
    """一对盲线 (line, route) 的行为键：repr(line)（冻结 dataclass，全部字段）、live_route(route)。repr 相同的线逐字段相同，所以类数是上界。"""
    line, route = pair
    return (repr(line), live_route(route))


def _classes(keys):
    by = collections.defaultdict(list)
    for i, k in enumerate(keys):
        by[k].append(i)
    hist = collections.Counter(len(v) for v in by.values())
    return dict(n=len(keys), distinct=len(by), multiplicity_histogram=dict(sorted(hist.items())), max_multiplicity=max(hist),
                classes=sorted(by.values()))


def panel_classes():
    """路线、冻结习惯（LIST 的 526 项）、盲线（solver.blind_gate(full=True) 的 1,700 对）在本进程开关下各有几种不同的行为（按上面的键）。
    classes：每类的条目下标（习惯 = items 下标，盲线 = blind_gate 列表下标）。现行版本下 17 → 2、526 → 211、1,700 → 200（2026-11-03）。"""
    import shortcut_screen as ss, solver
    items = json.loads(LIST.read_text())["items"]
    routes = ss.routes()
    return dict(switches=_now(), live_route_fields=list(LIVE_ROUTE_FIELDS) if not (LOOT or NODES != "fixed") else "all",
                routes=_classes([live_route(r) for r in routes]), habits=_classes([habit_key(it) for it in items]),
                blind=_classes([blind_key(p) for p in solver.blind_gate(full=True)]))


def core_manifest():
    """core/ 下全部文件（含 test_*、gui/、prereg/；不含 __pycache__）的 sha256 前 16 位，外加最新的修改时间。"""
    root = ROOT / "core"
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return dict(files={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in files},
                newest=dict(path=str(newest.relative_to(ROOT)), mtime=datetime.datetime.fromtimestamp(newest.stat().st_mtime).isoformat(timespec="seconds")))


# ---------------------------------------------------------------- 2026-11-01 第一轮验证（main）
def gate_job(salt):
    setup()
    import devworld, regsel
    run = build(salt)
    if not devworld.two_rounds(run):
        return dict(salt=salt, two_rounds=False)
    wins, _ = regsel.r1_wins(run, salt, R1_N, R1_STREAM)          # regsel 自己写死 R1_DISPLAY（= 统一 seen 画面的值）
    return dict(salt=salt, two_rounds=True, drawn=list(run.drawn), boss=list(run.boss_stages),
                teach=teach_index(run), R1=wins / R1_N, passes=wins / R1_N >= R1_MIN)


def habit_job(job):
    salt, ids = job
    setup()
    import shortcut_screen as ss, solver, gates, fixed_panel as fp
    items = json.loads(LIST.read_text())["items"]
    run = build(salt)
    i0 = next(k for k, layer in enumerate(run.layers) if layer.kinds() != ["rest"])
    f = run.fight_at(i0, 0)
    roles_inv = {m: f.layout.L("them", m) for m in ROLES}
    full = gates.LIB_SCREEN_STREAM + "/panel-select"
    out = []
    with using_display("habit"):
        for i in ids:
            it = items[i]; base = ss.bases()[it["base"]]
            trig, resp = fp.concrete(it, roles_inv)
            dark = None if it["dark"] == "none" else it["dark"]
            route = ss.routes()[it["route"]]
            w = 0
            for t in range(PACKRUNS):
                w += bool(solver.run_once(run, solver.NONE, route, solver._trial_rng(SEED ^ salt, full, t), information="observable",
                                          blind=base, act_policy=ss.make_act(base, trig, resp, dark), record=ss.TrackSeen()))
            out.append((i, w))
    return salt, out


def main():
    t0 = datetime.datetime.now(); OUT.mkdir(parents=True, exist_ok=True)
    f = refuse_overwrite(OUT / f"antagonist_proto{out_tag()}.json")
    setup()
    items = json.loads(LIST.read_text())["items"]
    evaluated = []; passers = []; salt = SALT0
    with ProcessPoolExecutor(WORKERS) as ex:
        while len(passers) < N_PASS and salt - SALT0 < SCAN_CAP:
            batch = list(range(salt, min(salt + 2 * WORKERS, SALT0 + SCAN_CAP))); salt = batch[-1] + 1
            for r in ex.map(gate_job, batch):
                evaluated.append(r)
                if r.get("passes"): passers.append(r["salt"])
            print(f"扫到 {salt}: 候选 {len(evaluated)}，两轮 {sum(r['two_rounds'] for r in evaluated)}，R1≥.90 {len(passers)}/{N_PASS}", flush=True)
        passers = passers[:N_PASS]
        jobs = [(s, list(range(i, min(i + CHUNK, len(items))))) for s in passers for i in range(0, len(items), CHUNK)]
        mat = collections.defaultdict(dict)
        for n, (s, rows) in enumerate(ex.map(habit_job, jobs, chunksize=2)):
            for i, w in rows: mat[s][str(i)] = w
            if n % 50 == 0: print(f"清单作业 {n}/{len(jobs)}", flush=True)
    by = {r["salt"]: r for r in evaluated}
    maps = {}
    for s in passers:
        m = mat[s]; best = max(m, key=lambda i: (m[i], -int(i)))
        cls = collections.defaultdict(int)
        for i, w in m.items():
            it = items[int(i)]; cls[f"resp={it['response']}"] = max(cls[f"resp={it['response']}"], w); cls[f"dark={it['dark']}"] = max(cls[f"dark={it['dark']}"], w)
        r = by[s]; drawn = set(r["drawn"])
        maps[str(s)] = dict(salt=s, drawn=r["drawn"], boss=r["boss"], teach=r["teach"], R1=r["R1"],
                            pairs_complete=[p for p in PAIRS if set(p) <= drawn], boss_is_pair=bool(r["boss"]) and any(set(r["boss"]) == set(p) for p in PAIRS),
                            habit_max=max(m.values()) / PACKRUNS, best_habit=dict(id=int(best), **{k: items[int(best)][k] for k in ("base_name", "trigger", "response", "route", "dark")}),
                            class_max={k: v / PACKRUNS for k, v in cls.items()}, matrix=m)
    files = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in
             ("core/adventure.py", "core/solver.py", "core/devworld.py", "core/cautious.py", "scripts/shortcut_screen.py", "scripts/fixed_panel.py", "scripts/antagonist_proto.py", "results/sweeps/fixed_panel_list.json")}
    out = dict(study="antagonist-proto-v1", proto=settings(), loot=LOOT, pool=list(PROTO), pairs=[list(p) for p in PAIRS],
               base="registration 12 prototype (auto_rest=1), world A identity, momentum_full_ratio as registered (450)",
               salt0=SALT0, scan_cap=SCAN_CAP, r1=dict(n=R1_N, min=R1_MIN, stream=R1_STREAM), packruns=PACKRUNS, n_habits=len(items), files=files,
               evaluated=evaluated, passers=passers, maps=maps, minutes=round((datetime.datetime.now() - t0).total_seconds() / 60, 1))
    f.write_text(json.dumps(out, ensure_ascii=False))
    hm = [v["habit_max"] for v in maps.values()]
    print(f"R1 过门 {len(passers)}/{sum(r['two_rounds'] for r in evaluated)} 张两轮图；清单最强单命通关率：≥.9 {sum(x>=.9 for x in hm)}，≥.5 {sum(x>=.5 for x in hm)}，<.3 {sum(x<.3 for x in hm)}，共 {len(hm)}；→ {f.relative_to(ROOT)}（{out['minutes']} 分钟）", flush=True)


# ---------------------------------------------------------------- 核对（单进程，几百条命，不算通过率）
class _Cap:
    """记录器：每场打的是哪个敌人对象、进 boss 门时的牌组 / 攻击 / 上限。"""
    belief = None

    def __init__(self):
        self.enemies = []; self.door = None; self.hp = []

    def enter(self, run, f, kinds):
        if not f.is_boss:
            self.enemies.append(f.enemy)

    def __call__(self, run):                                # boss_entry
        self.door = dict(extra=dict(collections.Counter(run.deck_list) - collections.Counter(run._pristine_deck)),
                         atk=run.base_atk, cap=run.max_hp, base_cap=run.base_max_hp)

    def before_decision(self, f): pass
    def before_play(self, f, c): pass
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, *a): pass
    def leave(self, f, won): self.hp.append((f.turn, f.state[("me", "hp")], f.state[("them", "hp")]))
    def rest(self, run, mode): pass


def _sig(lives):
    """逐命：输赢、打过的敌人对象、每场结束时的回合数 / 双方血量。"""
    return [(w, [id(e) for e in c.enemies], c.hp) for w, c in lives]


def _lives(run, salt, who, n, stream="proto-check", record=None, track=None):
    """who 的 n 条单命（到 boss 门口为止），返回 [(won, cap)]。track 给定时强制开 / 关 `?` 追踪（核对 seen 下它无影响）。"""
    import cautious, devworld, solver, shortcut_screen as ss, fixed_panel as fp
    out = []
    with using_display(who):
        for t in range(n):
            cap = _Cap(); rng = solver._trial_rng(SEED ^ salt, stream, t)
            rec = (ScreenRecord(cap) if track else cap) if track is not None else screen(who, cap)
            kw = dict(information="observable", record=rec, boss_entry=cap, fight_boss=False)
            if who == "R1":
                p = cautious.Cautious(devworld.R1_VARIANT)
                won = solver.run_once(run, solver.ALL - {"mark"}, solver.SCREEN_ROUTES[9], rng, act_policy=p.act, heal_veto=p.heal_veto,
                                      belief_cls=cautious.PublicBelief, **kw)
            elif who == "R1v2":
                import r1v2
                kw.pop("information")
                won, _p = r1v2.run_life(run, solver.SCREEN_ROUTES[9], rng, **kw)
            elif who == "oracle":
                kw["information"] = "oracle"
                won = solver.run_once(run, solver.ALL, solver.SCREEN_ROUTES[9], rng, **kw)
            elif who == "habit":
                it = json.loads(LIST.read_text())["items"][0]; base = ss.bases()[it["base"]]
                i0 = next(k for k, layer in enumerate(run.layers) if layer.kinds() != ["rest"])
                trig, resp = fp.concrete(it, {m: run.fight_at(i0, 0).layout.L("them", m) for m in ROLES})
                won = solver.run_once(run, solver.NONE, ss.routes()[it["route"]], rng, blind=base,
                                      act_policy=ss.make_act(base, trig, resp, None if it["dark"] == "none" else it["dark"]), **kw)
            elif who == "blind":
                line, route = solver.blind_gate(full=True)[0]
                won = solver.run_once(run, solver.NONE, route, rng, blind=line, **kw)
            out.append((bool(won), cap))
    return out


def _selfcheck():
    import adventure, devworld, solver
    from adventure import TUNING
    t0 = datetime.datetime.now(); setup()
    assert _now() == DEFAULTS, "核对要在默认开关下跑（不导出 PROTO_*）"
    rep = dict(proto=settings(), checks={}); ok_all = True

    def verdict(name, ok, **detail):
        nonlocal ok_all
        ok_all &= bool(ok); rep["checks"][name] = dict(status="PASS" if ok else "FAIL", **detail)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    salts = (2000011, 2000007); runs = {s: build(s) for s in salts}
    assert all(devworld.two_rounds(r) for r in runs.values())
    who_all = ("R1", "R1v2", "oracle", "habit", "blind"); N = 8
    cur = {(s, w): _lives(runs[s], s, w, N) for s in salts for w in who_all}
    # K1 删奖励：每种脚本玩家进 boss 门时牌组只少不多、攻击 / 上限不变；里程碑层确实存在（原函数）
    milestones = {s: sum(_ORIG["pays_milestone"](L.nodes[0]) for L in runs[s].layers if L.nodes[0].kind != "rest") for s in salts}
    doors = [c.door for v in cur.values() for _w, c in v if c.door is not None]
    verdict("K1_loot_off", all(not d["extra"] and d["atk"] == runs[s].base_atk and d["cap"] == d["base_cap"]
                               for s in salts for w in who_all for _w, c in cur[(s, w)] for d in [c.door] if d is not None) and milestones == {s: 2 for s in salts},
            lives=sum(len(v) for v in cur.values()), at_door=len(doors), milestone_layers=milestones)
    # K2 固定节点：每种脚本玩家每条命打的都是每层第 0 个节点的那个敌人（同一个对象）
    exp = {s: [L.nodes[0].enemy for L in runs[s].layers if L.nodes[0].kind != "rest"] for s in salts}
    bad = [(s, w) for (s, w), v in cur.items() for _w, c in v if any(a is not b for a, b in zip(c.enemies, exp[s])) or len(c.enemies) > len(exp[s])]
    multi = {s: sum(len(L.nodes) > 1 for L in runs[s].layers) for s in salts}
    verdict("K2_fixed_node", not bad, mismatched=bad[:5], layers_with_choice=multi)
    # K3 统一画面：setup 后 TUNING 就是统一画面；每种玩家（含模型 / 人）拿到同一组键；读画面的玩家都开 `?` 追踪
    ds = {w: display_settings(w) for w in WHO_DISPLAY}
    verdict("K3_one_display", (TUNING["marks"], TUNING["state_slots"]) == (0, "seen") and len({json.dumps(d, sort_keys=True) for d in ds.values()}) == 1
            and all(tracks_screen(w) for w in SCREEN_READERS), display=ds["model"], screen_readers=list(SCREEN_READERS))
    # K4 seen 画面下 `?` 追踪不改变读画面的玩家的任何一步（R1 v1 / R1v2：开 / 关各一遍，逐命逐场比）
    same = {}
    for w in ("R1", "R1v2"):
        for s in salts:
            a = _lives(runs[s], s, w, 12, "proto-check-track", track=True); b = _lives(runs[s], s, w, 12, "proto-check-track", track=False)
            same[f"{w}/{s}"] = _sig(a) == _sig(b)
    verdict("K4_track_noop_under_seen", all(same.values()), compared=same)
    # K5 存档复现：archived() 下 R1 v1 在 2000011 上 200 条命（ev 流）的赢数与死因表 = antagonist_preboss.json（同 boss_check 的 C8）
    import regsel, antagonist_diag as ad
    pre = json.loads((OUT / "antagonist_preboss.json").read_text())
    with archived():
        run = build(2000011); lives = []
        with using_display("R1"):
            for t in range(pre["n"]):
                rec = ad.Rec(); p = __import__("cautious").Cautious(devworld.R1_VARIANT)
                won = solver.run_once(run, solver.ALL - {"mark"}, solver.SCREEN_ROUTES[9], solver._trial_rng(regsel.search_seed() ^ 2000011, R1_STREAM, t),
                                      information="observable", act_policy=p.act, heal_veto=p.heal_veto, belief_cls=__import__("cautious").PublicBelief,
                                      record=rec, fight_boss=False)
                lives.append((bool(won), rec.fights))
        dt = collections.Counter(f"{f[-1][0]}/{f[-1][1]}" for w, f in lives if not w and f)
        st = pre["maps"]["2000011"]
        arch = _lives(runs[2000011], 2000011, "R1", N)                # 同一 Run 对象，存档开关
        arch_nodes = sum(any(a is not b for a, b in zip(c.enemies, exp[2000011])) for _w, c in arch)
        arch_loot = sum(bool(c.door and c.door["extra"]) for _w, c in arch)
        in_arch = (LOOT, NODES, DISPLAY, TUNING["marks"], TUNING["state_slots"], REFS, __import__("r1v2").ENERGY_VETO, "play_fight" in _ORIG)
    verdict("K5_archive_reproduces", sum(w for w, _ in lives) == round(st["rate"]["R1"] * pre["n"]) and dict(dt) == st["deaths"]["R1"]
            and arch_nodes > 0 and arch_loot > 0 and in_arch == (True, "route", "per-player", 1, "hidden", "b", False, False),
            wins=sum(w for w, _ in lives), stored=round(st["rate"]["R1"] * pre["n"]), deaths=dict(dt), stored_deaths=st["deaths"]["R1"],
            archive_lives_off_node0=f"{arch_nodes}/{N}", archive_lives_with_takes=f"{arch_loot}/{N}", settings_inside=in_arch)
    # K6 回到现行版本后同样的命逐条复现（archived() 进出不留痕）
    again = {(s, w): _lives(runs[s], s, w, N) for s in salts for w in ("R1", "oracle")}
    verdict("K6_archived_roundtrip", all(_sig(again[k]) == _sig(cur[k]) for k in again) and settings() == rep["proto"],
            keys=[f"{s}/{w}" for s, w in again])
    # K7 teardown：补丁和画面全撤，原函数回来；再 setup 又装上
    teardown()
    back = dict(run_once=not hasattr(solver.run_once, "__wrapped__") and not hasattr(solver, "_proto_noloot"),
                play_fight=not hasattr(solver.play_fight, "__wrapped__"),
                pays=adventure.pays_milestone.__module__ == "adventure", choose=adventure.Run.choose.__module__ == "adventure",
                take=adventure.Run.take.__module__ == "adventure", reward=adventure.Run.apply_reward.__module__ == "adventure",
                fight=adventure.Run._fight.__module__ == "adventure", display=(TUNING["marks"], TUNING["state_slots"]) == (1, "hidden"))
    setup()
    verdict("K7_teardown", all(back.values()) and adventure.Run.choose.__module__ == __name__ and hasattr(solver.run_once, "__wrapped__")
            and hasattr(solver.play_fight, "__wrapped__"),
            restored=back)
    import gates
    fp_ok = gates.code_fingerprint() == json.loads((ROOT / "results" / "pre_registration.json").read_text())["code_sha256_16"]
    verdict("K8_core_fingerprint", fp_ok)
    rep.update(ok=ok_all, seconds=round((datetime.datetime.now() - t0).total_seconds(), 1))
    print(f"{'ALL PASS' if ok_all else 'FAIL'}（{rep['seconds']} 秒）")
    return rep


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"]:
        r = _selfcheck()
        if sys.argv[2:3]:
            p = pathlib.Path(sys.argv[2]); p.parent.mkdir(parents=True, exist_ok=True)
            refuse_overwrite(p).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
            print(f"→ {p}")
    else:
        main()
