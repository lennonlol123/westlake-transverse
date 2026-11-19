"""原型现行版本（antagonist_proto.PROTO_VERSION）的参与者入口（N6，2026-11-03，用户：「把尺子修好，按照当前的版本逻辑修，取消拿牌之类的选择」）。
模型和人玩一个原型世界（proto_world 的 spec），与脚本参照同一版：同样的固定战斗、没有奖励、同一个画面、同样的独立 boss。
不改 core/：复用 core/modelrun.py 的 run_fight、日志（HarnessLog）、笔记、交接（carry 各臂）、记录（_dump），只把世界的组成和被删掉的选择换掉。

一个世界 = 第 1–4 条命各打一张无 boss 的图 + 第 5 条命打独立 boss（一条命一张图，同 modelrun 的「每条命一张新图」）：
  · 图：每个战斗层打固定的那一场（ap.fixed_node，第 0 个节点；人人相同），休息层是自动补给。不问 `Layer i. Choose:`、`Choose one:`、
    `You may take one card:`，日志里没有 `[layer i] won, took X / chose X`；只有 `[layer i] fight begins / ended` 和
    `[layer i] automatic resupply -> …`（与 modelrun 的文字逐字相同）。打完最后一层这条命就结束（result "cleared"）；
    地图 Run 后面引擎照样接着的 boss 不打（原型的图没有 boss）。
  · boss：antagonist_boss.build_boss(boss salt, 顺序, 0) 建的独立 Run；在 run.trial() 里满血、起始 18 张、基础属性、命级计数清零入场
    （D2，与 play_boss 同样的 assert）。一个身体一条血、中途换机制；日志标签沿用 modelrun / audit.parse_log 的 `[boss 1] begins` /
    `[boss 1] fight ended`（独立 boss 只有一场）。提示 "The enemy has changed." 由 modelrun.run_fight 写在换阶段那次 `end turn -> …` 后面，
    下一次决策的历史里就有它；人类入口先印新的历史行、再印画面。D1 槽位补丁、进场初始化不进日志（_quiet_model_log 认 modelrun.run_fight
    的帧）照常生效。洗牌用 boss Run 自己的结构种子（同 modelrun 打图用 run.shuffles），同一世界的每个参与者一样。
    不论前 4 条命死没死，第 5 条命都打 boss（D2）。
  · 记忆：照 modelrun 现有的臂（carry none / notes / log / both、--no-notes、fight_notes none / write / show、世界末的信），不加新的记忆规则。
    唯一的不同：原型默认没有营地（PROTO_CAMP=0，待用户定），于是交接里没有营地那一段（营地记录、营地结论）—— 没有营地就没有这段；
    其余是 modelrun.build_handover / handover_evidence 的文字，只改下面 v1.2 的两处。PROTO_CAMP=1 时第 1 条命先打营地，交接除 RETRY_HEAD
    的第一行外与 modelrun 逐字相同。
  · 参与者文字（v1.2，用户 2026-11-03 批准这两类：「不能活着也被说成『你死了』，没有营地也不该沿用营地交接词」）：
    (1) 第 k>1 条命的 RETRY_HEAD 第一行按第 k-1 条命记录里的结果说：死了（"died at …"）= 原文 "You have been here before. You did not
        survive it."；打通（"cleared"）= "You have been here before. You came through it."；其余几行逐字。两种营地开关都这样（modelrun 不看
        结果，对每条后续命都说没活下来）。第 k-1 条命没有记录、或记录里没有可认的结果（单独打第 k 条命、跳着打）：拒绝开打（retry_head
        抛 SystemExit，英文，人类命令行看得到），不编结果，也不用中性的一句。第 k-1 条命（或这条命已有的记录）是别的世界的（同一个
        run_id 用在两个世界上）：也拒绝（英文，开打前），不把别的世界的结果、日志、笔记交给这个世界（v1.2.1，审查 2026-11-03）。
    (2) PROTO_CAMP=0：行动的系统提示 = ADV_SYSTEM_NO_CAMP（"The air is cold. You can hear other things moving in the distance.\\n\\n" + ADV_SYSTEM
        从 "Each step you may:" 起的原文；去掉写给离开营地的 "The wall has opened." / "The air outside …" / "You feel restored."）；交接和信的材料里
        每条命的标签是 "Life {n} ({res}):"（不是 "Life {n}, outside ({res}):"）。PROTO_CAMP=1：系统提示、标签逐字是 modelrun 的。
    modelrun 按系统提示的文字认调用种类（core/modelrun.py:409-410 _call_kind：ADV_SYSTEM → "adv-act"，进 USAGE_BY_KIND / 记录的 usage.by_kind
    和 TRACE），人类入口按它印系统说明，假模型和 proto_check 的分类也按 modelrun.ADV_SYSTEM 比：adv_system() 在没有营地的那条命里把
    modelrun.ADV_SYSTEM 临时换成新文字、命末还原，新文字在每一处得到原文的种类（proto_check C19 核对）。请求的其余设置（思考档位、
    prompt_cache_key、max_tokens）不按种类分。
  · 画面（N3）：ap.using_display("model" / "human")；统一模式下与脚本参照同一个画面（默认 seen）。每份记录写 proto=ap.settings()、
    display（这个玩家的画面键）、display_tuning（开打时 TUNING 里实际的值）。
  · 记录：modelrun._dump 的同一 schema，同一个 RUNS_DIR（AGII_RUNS 可覆盖）；另加 proto、proto_play、proto_world、proto_world_spec、
    proto_life、proto_camp、who、fights（每场：层、节点、敌人名）、boss（阶段顺序、换阶段回合、提示出现的位置、D1 交接记录）、
    participant_text（v1.2：用的哪个行动系统提示及其指纹、RETRY_HEAD 第一行 —— v1.2.1 起按交接里的位置读，跳过前面的信）。
    模型的 run_id 一律以 "p13-" 开头；人类的 run_id = human-<name>-<世界 id>（图形界面写死这个格式），世界 id 本身以 "p13-" 开头。
  · 已知、待用户（不在这里改）：强制结束回合（第三次无效）正好落在换阶段那一回合时，modelrun.run_fight 跳过提示的渲染，提示晚一步
    （docs/antagonist_boss/01_boss_settings_draft.md §5.4）；本入口只在记录里标出（boss.cue_late），不改行为。
  · boss 规则（v1.1，审查 2026-11-03）：boss 命在 setup_boss 定下的 boss 键下打（boss_no_probe=0 …），与脚本参照相同。v1 里 play_life 先
    proto_world.verify（→ ap.setup() → activate_registered(12)）再建 boss，boss_no_probe 被改回登记值 1，模型 / 人的 boss 命第一次踩线就按全价算，
    脚本参照不是；现在 ap.setup() 由 boss 层的钩子写回，play_life 开打前核对 TUNING 的 boss 键 == antagonist_boss.boss_settings()，记录写 boss.tuning_at_play。
  · 发牌：一个世界只有一副牌（每张图 / boss 的结构洗牌），同一世界的每个参与者、每个记忆臂都打这一副；脚本参照默认每条命一副新牌
    （antagonist_boss.play_map / play_boss 的 deal="structural" 让它们打这一副）。世界级比较混着这副牌的运气，见 antagonist_proto 说明。
  · 重打（v1.1）：一条命已有结果时，play_life 只在 overwrite=True 时重打，并在记录里写 attempt（第几次）与 previous_results —— 重打的是**同一副牌**，
    参与者已经见过它；模型入口不重打。命令行人类入口默认拒绝，--replay 才重打；图形界面的 Replay（humangui 自己要求勾选并备份）照旧放行，同样记 attempt。
  · 揭示（v1.1）：--reveal 只在这一次跑到第 5 条命、且第 1–5 条命都有结果时才印（同 humangui.validate_start 的 hi == size 且前面的命完整）；
    否则不印 —— v1 在 --lives 1-4 --reveal 之后就印出全部图的机制和 boss 的阶段顺序，然后还能打第 5 条命。

  · 参与者文字开关 PROTO_TEXT（11-05，用户定稿 docs/antagonist_boss/23_minimal_participant_text_draft.md；实现在 scripts/proto_text.py，
    版本 proto_text.VERSION）：不设 = registered，本文件的每一个输出逐字不变（VERSION 也不改，默认记录逐字相同）；PROTO_TEXT=minimal：
    行动系统提示 B1、第 k>1 条命的抬头只有 "World w, Life k"（B2，不说结果、不说符号）、记录抬头 B3、命末笔记 B4 + 字数上限（B12，与信同一
    上限、先缩一次再截断）、战后笔记 B5、笔记 / 信的系统提示 B6、信 B7–B9、带来的每条命的标签 B10、锁定那一行去掉标签（A1）、人的
    命末结果不带血量（A2）、休息行去掉 "automatic resupply"（B11，v2）、提示结构语压短（v2：Record: / Notes: / This life: / Draft: /
    B3 单复数；人的笔记提示与命的横幅 "World w, Life k"）。读记录的工具一律经 audit/participant_text.registered_record（proto_text 转出）
    按记录写的文字版本换回登记写法再解析（proto_text 说明）。调用种类与用量记账不变
    （proto_text.session）。v3b 池下（boss 先不做）一个世界是第 1–4 条命：信按 4 条命写（world_lives()）。没有营地才行（营地 + minimal 拒绝）。
    w = 这个参与者的第几个世界：模型按信的链（proto_text.world_index_from_letters），人按 --world-index（默认 1）。
    参与者命令行入口在 PROTO_TEXT=minimal 下照样拒绝（_cli_guard；放开要用户定）。

  · 人类入口在候选 v3b 下的显式开关 PROTO_HUMAN_V3B=1（11-05 夜，用户要亲自玩 v3b；docs/antagonist_boss/25_human_entry_v3b.md，
    版本 HUMAN_V3B_VERSION）：只放开人类的三个命令（human / gui / gui-worker），而且只在**恰好**这一套环境下 —— HUMAN_V3B_ENV 的 12 个
    PROTO_*（11 个 v3b 开关 + PROTO_TEXT=minimal），别的 PROTO_* 一个也不许设（PROTO_WORLDS 和开关本身除外），解析后的 ap._now() 也要等于
    HUMAN_V3B_NOW、没有营地；差一点就拒绝并点名（英文）。model 命令照旧拒绝（用户没批准模型跑）。不设这个开关：_cli_guard 与 __main__
    的流程、每一个输出、每一份记录逐字不变（human_v3b_check 的 diff，改前改后）。
    开关打开时（human_v3b_setup，命令行 __main__ 调；核对进程内直接调）：记录写到 ~/agii_runs/human_v3b/records/（AGII_HUMAN_V3B_DIR 可改，
    不许在 results/ 下；不读 AGII_RUNS），先核 tiktoken（笔记上限要它）。一个世界 = 第 1–4 条命（world_lives()）；世界文件 = proto_world
    的 spec 文件（save_worlds 的格式），--world-index N 选文件里第 N 个世界，横幅和抬头的 w 就是它在文件里的位置（--world 给 id 时 w 也按位置，
    两个都给且不一致就拒绝）；--reveal 不印任何东西（boss 没做、一个人要连着玩几个世界）；读世界文件、核世界的报错改成英文；
    记录多一个 human_entry 键（版本、世界文件路径与 sha256、世界 id 与位置、cli / gui、记录目录），其余与模型的记录同一格式。
    entry v2（11-05 夜，用户批准，18 §8.6 末行）：这个入口**必须**带训练营 PROTO_CAMP=1 —— 不设或别的值都在开打之前用一句短英文拒绝
    （HUMAN_V3B_CAMP_REFUSAL，点名 PROTO_CAMP=1；_human_v3b_require_camp，_cli_guard 与 human_v3b_setup 都先调它）；人看到的
    「[Carried over]」标签在 PROTO_TEXT=minimal 下去掉（proto_text.human_notes，运行时换 humanrun._show_once；没带东西就整块不印）。

  · 人类入口在候选 v3c 下的显式开关 PROTO_HUMAN_V3C=1（11-06，28 §9；docs/antagonist_boss/29_human_entry_v3c.md，版本 HUMAN_V3C_VERSION）：
    与 PROTO_HUMAN_V3B=1 同一套代码、同样的要求（只放开 human / gui / gui-worker；必须带 PROTO_CAMP=1；model 照旧拒绝），只换这几样：
    环境 HUMAN_V3C_ENV（= v3b 那 12 个，PROTO_TUNE=m59ws2t25c_bp45w90_c48、PROTO_COUNTER=noblock）、解析后的开关 HUMAN_V3C_NOW、
    记录目录 ~/agii_runs/human_v3c/records/（AGII_HUMAN_V3C_DIR 可改，同样不许在 results/ 下）、入口版本、拒绝文字里的开关名。
    两个开关同时设：先走 v3b 的核对（PROTO_HUMAN_V3C 是「别的 PROTO_*」→ 拒绝）。不设 PROTO_HUMAN_V3C：一切逐字不变（v3b 入口也是）。
  · 人类入口在候选 v3c1 下的显式开关 PROTO_HUMAN_V3C1=1（11-06，用户采用 v3c1；docs/antagonist_boss/31_human_entry_v3c1.md，版本 HUMAN_V3C1_VERSION）：
    同一套代码、同样的要求，只换：环境 HUMAN_V3C1_ENV（= v3c 那 12 个，PROTO_LADDER_TABLE=v3c1）、HUMAN_V3C1_NOW、记录目录
    ~/agii_runs/human_v3c1/records/（AGII_HUMAN_V3C1_DIR 可改，不许在 results/ 下）、入口版本、拒绝文字里的开关名；另加世界文件白名单：
    --worlds（或 PROTO_WORLDS）的内容 sha256 必须等于包 pack_v3c1_v1 的（HUMAN_V3C1_PACK_SHA256），否则开打之前英文拒绝（用户同意：
    入口不许悄悄接受错的包）。几个开关同时设：先走 v3b、再 v3c 的核对（PROTO_HUMAN_V3C1 是「别的 PROTO_*」→ 拒绝）。不设 PROTO_HUMAN_V3C1：
    一切逐字不变（v3b、v3c 入口也是；白名单只在 v3c1 入口上）。
  · boss 世界（11-07，用户：第 5 条命接进入口；docs/antagonist_boss/40_boss_entry.md，BOSS_WORLD_VERSION）：PROTO_TEXT=minimal 且解析后的开关正好是
    图包 pack_v3c1_v2 的 boss 环境（BOSS_WORLD_NOW，血 / 伤害除外；boss_world()）时，一个世界是第 1–5 条命（world_lives()），第 5 条命打这个世界的 boss。
    一个进程只打一个世界：进程的 PROTO_* 必须正好是这个世界存的 boss.env（boss_world_problems；各世界的血 / 伤害不同，antagonist_proto 导入时读），
    与图包重放核对同一个做法；图（第 1–4 条命）也在这套环境下打（表 v3c1b 的教学 / 考试行 = v3c1；40 号文档的核对：40 张图逐键不变）。
    参与者文字不加新话（用户 11-07）：第 5 条命的抬头照旧 "World w, Life 5"；同类配对（boss.cue）换阶段照旧 "The enemy has changed."，混合配对什么也不印；
    第二次犯规致死、45 回合上限都不说；看不到「boss」：这一场的标记写成一层的图 "[layer 1] fight begins" / "[layer 1] fight ended"、战后笔记的标签
    "layer 1"、输了 result = "died at layer 1"（人看到 "Result: not cleared (layer 1)"）；名字是引擎合并后的那一个（第一阶段敌人的名字），两段同名。
    记录多 boss_world 键（版本、boss.env、第 5 条命的标记）。不在这套环境下：上面这些一个也不跑，行为与输出逐字不变。
  · 人类入口的显式开关 PROTO_HUMAN_V3C1B=1（11-07，40 号文档，版本 HUMAN_V3C1B_VERSION）：同 v3c1 入口的写法（只放开 human / gui / gui-worker；必须带
    PROTO_CAMP=1；model 照旧拒绝），环境 = boss 世界的 21 个（BOSS_WORLD_ENV + PROTO_TEXT=minimal）+ 这个世界自己的 PROTO_BOSS_HP / PROTO_BOSS_ATK
    （HUMAN_V3C1B_BOSS；开打前先核「是图包里某个世界的那一对」，选了世界之后核「就是这个世界的」，不对就英文拒绝并写出要的两个变量）；
    记录目录 ~/agii_runs/human_v3c1b/records/（AGII_HUMAN_V3C1B_DIR 可改，不许在 results/ 下）；白名单 = pack_v3c1_v3 的 sha256（v6，41 §10；
    pack_v3c1_v2 明确拒绝）；图形界面只列这个进程的
    血 / 伤害能打的世界。--reveal 照 v3b / v3c / v3c1 入口不印任何东西（一个人要连着玩几个世界）。几个开关同时设：先走 v3b、v3c、v3c1 的核对 → 拒绝。

入口与接口：
  setup()                                   ab.setup_boss()（→ ap.setup()）；PROTO_LOOT=1 或 PROTO_NODES=route（存档开关）下拒绝：
                                            参与者入口只实现现行版本，存档的参与者路径就是 core/modelrun.py 的 main。
  play_life(model, spec, life, key, run_id=…, carry, want_notes, fight_notes, letters_from, who, verbose, overwrite)
  play_world(model, spec, lives=(1, 5), run_id=None, key=None, …)   模型；key=None 时读钥匙（真跑；核对从不走这里）
  fake_model(respond) / AttackOnly          进程内假模型：换掉 modelrun.call（唯一的 HTTP 出口）、_api_key（报错，不读钥匙）、
                                            urllib.request.urlopen（报错）；yield 给入口用的 key
  write_letter(model, run_id, carry, key=None, …)   世界末的信（modelrun.write_letter；没有营地时证据里不放营地那段；v1.1 有营地时
                                            无限递归，v1.2 修）
  human_main(argv, show_map_metadata=True)  命令行人类入口（humanrun 的键盘函数，同 humanrun.main 的换法）
  gui_main(argv) / gui_worker(argv)         图形界面：core/humangui.py 原样跑，本进程里把它的 all_packs / default_pack 换成原型世界、
                                            把它的模块全局 subprocess 换成垫片（只改写 worker 命令：humangui.py --worker → 本文件 gui-worker）；
                                            worker = gui_bridge.run_worker + human_main（PROTO_WORLDS 环境变量传世界文件）
  handover_evidence / build_handover        modelrun 同名函数的原型版本（没有营地：不放营地那段、标签 "Life {n} ({res}):"；
                                            有营地：证据直接调 modelrun 的）；第 k>1 条命的 RETRY_HEAD 换成 retry_head(上一条命的结果)
  retry_head(prev_result, life)             RETRY_HEAD，第一行按上一条命的结果；没有结果就拒绝
  retry_line(handover, letters)             交接里实际发出的 RETRY_HEAD 第一行（跳过信；记录用）
  adv_system(camp)                          这条命的行动系统提示（上下文；没有营地时临时换 modelrun.ADV_SYSTEM）
  human_v3b_setup(records_dir=None)         PROTO_HUMAN_V3B=1：核环境、设记录目录（见上）（human_v3c_setup / human_v3c1_setup / human_v3c1b_setup 同）
  boss_world() / boss_world_problems(spec)  boss 世界（40 号文档）：本进程是不是；这个世界能不能在本进程打（英文问题清单）
  _cli_guard(cmd)                           v1.3：参与者命令行入口在 PROTO_HAND=fixed 或 PROTO_INCOMING / PROTO_THREAT / PROTO_MARKMAP 非默认时拒绝（D12）
                                            11-03 夜：PROTO_LADDER=1、PROTO_TUNE 不是 none 时也拒绝（候选，采用的版本切出来之前；版本号不改）
                                            11-04：PROTO_RAGE=off（去掉怒气，候选）同样拒绝并点名（版本号不改）
                                            11-04 晚：候选 v3（PROTO_POOL / PROTO_MOMENTUM / PROTO_DOUBLER / PROTO_GUARDCODE 非默认、
                                            PROTO_LADDER_TABLE=v3，ap.v3_now()）最先查、拒绝并点名；进程内的 play_life 在一个世界里不许换它们，
                                            PROTO_GUARDCODE=map 下记录多一个 guard_code 键（版本号不改，默认路径一字不变）
命令行：
  python3 -B scripts/proto_play.py model <model> --worlds W.json [--world ID] [--lives 1-5] [--carry notes] [--run-id p13-…]   （花钱；没跑过）
  python3 -B scripts/proto_play.py human --name N --worlds W.json [--world ID] [--lives 1-5] [--auto] [--reveal]
  python3 -B scripts/proto_play.py gui --worlds W.json [humangui 的参数]
  python3 -B scripts/proto_play.py smoke <runs_dir> [out.json]        进程内冒烟（假模型 / 脚本键盘，几条命，不算通过率）
  （v3b 人类入口：HUMAN_V3B_ENV 那 12 个开关 + PROTO_HUMAN_V3B=1，再 human --name N --worlds W.json [--world-index K] 或 gui --worlds W.json）
  （v3c 人类入口：HUMAN_V3C_ENV 那 12 个开关 + PROTO_CAMP=1 + PROTO_HUMAN_V3C=1，命令同上；29 号文档）
  （v3c1 人类入口：HUMAN_V3C1_ENV 那 12 个开关 + PROTO_CAMP=1 + PROTO_HUMAN_V3C1=1，--worlds 必须是包 pack_v3c1_v1；31 号文档）
  （v3c1 + boss 人类入口：HUMAN_V3C1B_ENV 那 21 个开关 + 这个世界的 PROTO_BOSS_HP / PROTO_BOSS_ATK + PROTO_CAMP=1 + PROTO_HUMAN_V3C1B=1，
    --worlds 必须是包 pack_v3c1_v3，--world-index K；40 号文档，41 §10；或 scripts/play_v3c1b_world.sh K）

  · 训练营（11-05 晚，18 §8.6，scripts/proto_camp.py 的说明）：候选 v3b + PROTO_TEXT=minimal 下 PROTO_CAMP=1 = 每个世界开头一次营地（第 1 条命
    开打之前），人和模型都是；营后笔记照命的笔记带进第 1–4 条命。人类入口 PROTO_HUMAN_V3B=1 多许一个 PROTO_CAMP=1（不设照旧没有营地，
    输出逐字不变）。别的环境下 PROTO_CAMP=1 照旧拒绝。entry v2（11-05 夜，用户）：人类入口 PROTO_HUMAN_V3B=1 **必须**带 PROTO_CAMP=1。"""
import argparse, contextlib, functools, io, json, os, pathlib, re, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
import modelrun                  # 先于 ap.setup() 导入：modelrun 按值导入的 pays_milestone 留在引擎原函数（本入口不用 modelrun.main）
import humanrun
import proto_text as pt          # 参与者文字开关 PROTO_TEXT（默认 registered：什么也不做）
from camp import Camp, turns_used
import antagonist_proto as ap
import antagonist_boss as ab
import proto_world as pw
import proto_camp as pc          # 候选 v3b 的训练营（PROTO_CAMP=1，18 §8.6）；不开营地时什么也不做

VERSION = "proto-play-v1.3-2026-11-03"    # v1.3（11-03 夜，docs/antagonist_boss/12_c10_v2_design.md §8.1）：三个候选开关 PROTO_INCOMING / PROTO_THREAT /
                                          #       PROTO_MARKMAP —— 命令行入口在非默认下拒绝（_cli_guard，D12）；进程内调用：world 下 play_life 绑世界表
                                          #       （proto_world.bind_world）再 require；一个世界里三者不能变（同手牌规则）；记录在非默认下多 mark_map /
                                          #       d1.incoming_unlogged / d1.threat；模型 run id 只对三者的偏离加后缀。默认下行为与输出一字不变
                                          # v1.2.2（11-03 晚）：PROTO_HAND=fixed（候选）下命令行入口（model / human / gui / gui-worker）拒绝开打 ——
                                          #       40 回合上限给参与者的那句规则和日志行还没定（英文措辞要用户看）；进程内调用（核对）不受影响；
                                          #       默认（draw）一字不变
                                          # v1.2.1（审查 2026-11-03）：记录的 retry_line 按位置读（信里引用那两句时 v1.2 记成信里的）；
                                          #       一个 run_id 只装一个世界（前几条命 / 这条命的记录是别的世界的就拒绝，英文）；游戏里的参与者文字不变；
                                          #       人类命令行看得到的拒绝 / 报错改成英文（lead 2026-11-03，参与者文字一律英文），提示与记录不变
                                          # v1.2：参与者文字两处（用户批准）—— RETRY_HEAD 第一行按上一条命的结果、没有营地时去掉营地措辞；
                                          #       另修 PROTO_CAMP=1 时 write_letter 的无限递归（C19 发现）
                                          # v1.1：boss 键核对（boss_no_probe 修复）、重打记 attempt、揭示的门槛
                                          # 11-05：参与者文字开关 PROTO_TEXT（proto_text.py，版本 proto_text.VERSION）—— 默认下输出与记录逐字不变，
                                          #       所以 VERSION 这一串故意不改（它写进每条记录）；minimal 下记录的 participant_text 写 text_version
                                          #       （11-05 晚 proto-text-v2：B11、结构语压短；同样只在 pt.minimal() 的分支里）
RUN_PREFIX = "p13-"
N_MAPS = pw.N_MAPS
N_LIVES = N_MAPS + 1


def world_lives():
    """一个世界几条命：PROTO_TEXT=minimal 且 v3b 池（boss 先不做）时 4（只有图）；其余 N_LIVES（4 张图 + boss，原样）。
    11-07（40 号文档）：minimal 下的 boss 世界（boss_world()：图包 pack_v3c1_v2 的 boss 环境）是 N_LIVES —— 第 5 条命打这个世界的 boss。"""
    if pt.minimal() and ap.BOSSLIFE == "off" and boss_world():   # 11-12：PROTO_BOSSLIFE=off，boss 世界也只打 4 张图
        return N_MAPS
    return N_MAPS if pt.minimal() and ap.v3_now().get("pool") == "v3b" and not boss_world() else N_LIVES
BOSS_LABEL = "boss 1"            # `[boss k] begins` 是 modelrun 与 audit/parse_log.py:21 的格式；独立 boss 只有一场
WHO = ("model", "human")
CHOICE_TEXTS = ("Choose:", "Choose one:", "You may take one card:", "You stop here:", "take nothing")
CARRIES = ("none", "notes", "log", "both", "layered")      # layered：46 号文档的分层记忆（只在 minimal 的 boss 世界、模型；11-08）
FIGHT_NOTES = ("none", "write", "show")
_READY = dict(setup=False, gui_worker=False)

# 候选 v3b 的人类入口（PROTO_HUMAN_V3B=1；11-05 夜，见说明）。不设开关时下面这些一个也不被读到。
HUMAN_V3B_VERSION = "human-v3b-entry-v2-2026-11-05"     # v2（11-05 夜，用户）：必须带 PROTO_CAMP=1（不带就短英文拒绝）；minimal 下人不再看到
                                                         # 「[Carried over]」标签（proto_text.human_notes）。v1 = human-v3b-entry-v1-2026-11-05
HUMAN_V3B_CAMP_REFUSAL = "PROTO_HUMAN_V3B=1 needs PROTO_CAMP=1 (the camp). Add PROTO_CAMP=1 to the command and start again."
HUMAN_V3B_FLAG = "PROTO_HUMAN_V3B"
HUMAN_V3B_CMDS = ("human", "gui", "gui-worker")         # model 不在里面：模型跑没批准
HUMAN_V3B_ENV = dict(PROTO_HAND="fixed", PROTO_LADDER="1", PROTO_RAGE="off", PROTO_TUNE="m59ws2t25c_bp45w90", PROTO_LADDER_TABLE="v3b",
                     PROTO_POOL="v3b", PROTO_MOMENTUM="noshield", PROTO_DOUBLER="turncd", PROTO_GUARDCODE="map", PROTO_COUNTER="nodouble",
                     PROTO_GUARDSTART="map", PROTO_TEXT="minimal")
HUMAN_V3B_FREE = ("PROTO_WORLDS", HUMAN_V3B_FLAG)        # 别的 PROTO_* 一个也不许设
HUMAN_V3B_NOW = dict(loot=False, nodes="fixed", display="seen", refs="c", hand="fixed", incoming="mute", threat="plain", markmap="salt",
                     ladder=True, tune="m59ws2t25c_bp45w90", rage="off", pool="v3b", momentum="noshield", doubler="turncd", guardcode="map",
                     counter="nodouble", guardstart="map", ladder_table="v3b")
HUMAN_V3B_DIR = pathlib.Path.home() / "agii_runs" / "human_v3b" / "records"
HUMAN_V3B_DIR_ENV = "AGII_HUMAN_V3B_DIR"
_HUMAN_V3B = {}                                          # human_v3b_setup 之后：on、records_dir；human_main 写 entry（记录的 human_entry）
                                                         # v3c 入口另有 variant="v3c"（v3b 入口不加这个键）
# 候选 v3c 的人类入口（PROTO_HUMAN_V3C=1；11-06，28 §9）。只换环境、开关、版本、记录目录；其余与 v3b 入口同一套代码。不设开关时一个也不被读到。
HUMAN_V3C_VERSION = "human-v3c-entry-v3-2026-11-06"     # v3 = v3b 入口 v2（必须带营地、不印 [Carried over]）+ 候选 v3c 的环境（28 号文档）
HUMAN_V3C_FLAG = "PROTO_HUMAN_V3C"
HUMAN_V3C_CAMP_REFUSAL = "PROTO_HUMAN_V3C=1 needs PROTO_CAMP=1 (the camp). Add PROTO_CAMP=1 to the command and start again."
HUMAN_V3C_ENV = dict(HUMAN_V3B_ENV, PROTO_TUNE="m59ws2t25c_bp45w90_c48", PROTO_COUNTER="noblock")
HUMAN_V3C_FREE = ("PROTO_WORLDS", HUMAN_V3C_FLAG)
HUMAN_V3C_NOW = dict(HUMAN_V3B_NOW, tune="m59ws2t25c_bp45w90_c48", counter="noblock")
HUMAN_V3C_DIR = pathlib.Path.home() / "agii_runs" / "human_v3c" / "records"
HUMAN_V3C_DIR_ENV = "AGII_HUMAN_V3C_DIR"
# 候选 v3c1 的人类入口（PROTO_HUMAN_V3C1=1；11-06，用户采用 v3c1：反击每场第一次罚 x1，30 号文档）。同 v3c 入口，换表 v3c1；另有世界文件白名单。
HUMAN_V3C1_VERSION = "human-v3c1-entry-v4-2026-11-06"   # v4 = v3c 入口 v3 + 表 v3c1 + 世界文件白名单（只认包 pack_v3c1_v1 的内容）
HUMAN_V3C1_FLAG = "PROTO_HUMAN_V3C1"
HUMAN_V3C1_CAMP_REFUSAL = "PROTO_HUMAN_V3C1=1 needs PROTO_CAMP=1 (the camp). Add PROTO_CAMP=1 to the command and start again."
HUMAN_V3C1_ENV = dict(HUMAN_V3C_ENV, PROTO_LADDER_TABLE="v3c1")
HUMAN_V3C1_FREE = ("PROTO_WORLDS", HUMAN_V3C1_FLAG)
HUMAN_V3C1_NOW = dict(HUMAN_V3C_NOW, ladder_table="v3c1")
HUMAN_V3C1_DIR = pathlib.Path.home() / "agii_runs" / "human_v3c1" / "records"
HUMAN_V3C1_DIR_ENV = "AGII_HUMAN_V3C1_DIR"
HUMAN_V3C1_PACK = "~/agii_runs/v3c1_pack/pack_v3c1_v1.json"
HUMAN_V3C1_PACK_SHA256 = "8bf0ff783fb3c588aca88c9323cad609265a558d815f2a7c7f58acf2f85d800f"   # 30 §8.4 的包（11-06 14:17 存盘）
# boss 世界（11-07，用户：第 5 条命接进入口；docs/antagonist_boss/40_boss_entry.md）。PROTO_TEXT=minimal + 下面这一套 boss 环境（= 图包 pack_v3c1_v2 每个世界
# 的 boss.env 去掉 PROTO_BOSS_HP / PROTO_BOSS_ATK；scripts/pack_v3c1_v2_build.py 的 BOSS_ENV）时，一个世界是第 1–5 条命，第 5 条命打这个世界的 boss。
# 一个进程只打一个世界：进程的 PROTO_* 必须正好是这个世界的 boss.env（各世界的血 / 伤害不同，antagonist_proto 在导入时读它们）—— 与图包的重放核对
# （scripts/pack_v3c1_v2_replay.py：每个世界一个子进程，环境 = boss.env）同一个做法。不在这套环境下：下面这些一个也不被读到，行为逐字不变。
BOSS_WORLD_VERSION = "boss-world-v1-2026-11-07"
BOSS_WORLD_ENV = dict({k: v for k, v in HUMAN_V3C1_ENV.items() if k != "PROTO_TEXT"}, PROTO_LADDER_TABLE="v3c1b", PROTO_BOSS="v1",
                      PROTO_BOSS_TURNCAP="45", PROTO_GUARDSEQ="irr67", PROTO_CHARGESEQ="len234", PROTO_BOSS_CUE="bytype",
                      PROTO_BOSS_SLOTSWAP="vanish", PROTO_BOSS_HANDOVER="x1m2", PROTO_BOSS_STRIKE="probe1", PROTO_BOSS_GUARDIN="now")
BOSS_WORLD_PER_WORLD = ("PROTO_BOSS_HP", "PROTO_BOSS_ATK", "PROTO_WORLD",   # 每个世界自己的（boss.env；伤害 100 时不设；PROTO_WORLD：世界外衣，43 号文档，A 不设）
                        "PROTO_HEAL")                                      # 修订 6（43 §19，11-09）：去掉治疗时 boss.env 带 PROTO_HEAL=off；包 v6 的世界不带（行为不变）
BOSS_WORLD_NOW = dict(HUMAN_V3C1_NOW, ladder_table="v3c1b", boss="v1", boss_turncap="45", guardseq="irr67", chargeseq="len234", boss_cue="bytype",
                      boss_handover="x1m2", boss_slotswap="vanish", boss_strike="probe1", boss_guardin="now")
BOSS_WORLD_NOW_FREE = ("boss_hp", "boss_atk", "world", "heal", "hide", "worknote", "wardseen", "wardstrict", "bosslife", "correspond", "mapcharge", "mapguard", "wardlimit", "wardteststart", "restamt")   # heal：修订 6（43 §19；同 BOSS_WORLD_PER_WORLD 的 PROTO_HEAL）
# 43 号文档 §14（修订 4，11-07）：破势也上 boss 的「一次试探、两次死」—— 同一套 boss 环境，只把 PROTO_BOSS_STRIKE 换成 probe1w（图包 v5 起）
BOSS_WORLD_ENV_W = dict(BOSS_WORLD_ENV, PROTO_BOSS_STRIKE="probe1w")
BOSS_WORLD_NOW_W = dict(BOSS_WORLD_NOW, boss_strike="probe1w")
BOSS_WORLD_EXTRA = ("PROTO_TEXT", "PROTO_CAMP", "PROTO_WORLDS", "PROTO_HIDE", "PROTO_WORKNOTE", "PROTO_WARDSEEN", "PROTO_WARDSTRICT", "PROTO_BOSSLIFE", "PROTO_CORRESPOND", "PROTO_MAPCHARGE", "PROTO_MAPGUARD", "PROTO_WARDLIMIT", "PROTO_WARDTESTSTART", "PROTO_RESTAMT", "PROTO_TURNCAP")   # hard5允许独立30回合上限，默认40
OPPONENT_LINE = "Opponent: {name}"   # 11-10：分层记忆下模型本场记录的第二行（人类画面本来就印这一行，humanrun.human_act）


def fight_loss_feedback(f):
    """Public terminal feedback, not an HP change or another player action."""
    if ap.ended_by(f) == "dodge_run":
        card = next(name for name, card in f.deck.items() if card.kind == "dodge")
        return f"({ap.DODGE_RUN_LIMIT} consecutive turns playing {card}: fight lost)"
    if ap.ended_by(f) == "turn_cap":
        return "(exceed round limit: fight lost)"
    if ap.ended_by(f) == "ward_limit":
        return ap.WARD_LIMIT_LOSS              # PROTO_WARDLIMIT（11-12，v8）：只说输了，不给原因
    return None
BOSS_WORLD_LABEL = "layer 1"     # 用户 11-07：参与者看不到「boss」——第 5 条命的那一场写成一层的图：[layer 1] fight begins / ended，输了 died at layer 1
# 候选 v3c1 + boss 的人类入口（PROTO_HUMAN_V3C1B=1；11-07，40 号文档）。同 v3c1 入口，环境换成 boss 世界的（另加每个世界自己的血 / 伤害），白名单换成 pack_v3c1_v2。
HUMAN_V3C1B_VERSION = "human-v3c1b-entry-v10-2026-11-09"  # v7 图包：去治疗，按链选择有／无提示环境
                                                         # v8（43 号文档 §14）：白名单换成 pack_v3c1_v5（破势也上 boss 的试探 / 死，PROTO_BOSS_STRIKE=probe1w），v4 及更早明确拒绝
                                                         # v7（43 号文档）：白名单换成 pack_v3c1_v4（8 个世界，每个世界自己的牌名 / 符号 / 数值），v3、v2 明确拒绝；
                                                         #     每个世界的表 = (PROTO_BOSS_HP, PROTO_BOSS_ATK, PROTO_WORLD)
                                                         # v6（41 号文档 §10）：白名单换成 pack_v3c1_v3（三只 boss 按新资格重挑），v2 明确拒绝
                                                         # v5 = v3c1 入口 v4 + 第 5 条命（boss）+ 每个世界自己的 boss 环境 + 白名单 pack_v3c1_v2
HUMAN_V3C1B_FLAG = "PROTO_HUMAN_V3C1B"
HUMAN_V3C1B_CAMP_REFUSAL = "PROTO_HUMAN_V3C1B=1 needs PROTO_CAMP=1 (the camp). Add PROTO_CAMP=1 to the command and start again."
HUMAN_V3C1B_ENV = dict({k: v for k, v in BOSS_WORLD_ENV_W.items() if k != "PROTO_BOSS_CUE"},
                       PROTO_TEXT="minimal", PROTO_HEAL="off")
HUMAN_V3C1B_FREE = ("PROTO_WORLDS", HUMAN_V3C1B_FLAG, "PROTO_BOSS_CUE", "PROTO_HIDE", "PROTO_WORKNOTE", "PROTO_WARDSEEN", "PROTO_WARDSTRICT", "PROTO_BOSSLIFE", "PROTO_CORRESPOND", "PROTO_MAPCHARGE", "PROTO_MAPGUARD", "PROTO_WARDLIMIT", "PROTO_WARDTESTSTART", "PROTO_RESTAMT", "PROTO_TURNCAP") + tuple(k for k in BOSS_WORLD_PER_WORLD if k != "PROTO_HEAL")
HUMAN_V3C1B_DIR = pathlib.Path.home() / "agii_runs" / "human_v3c1b" / "records"
HUMAN_V3C1B_DIR_ENV = "AGII_HUMAN_V3C1B_DIR"
HUMAN_V3C1B_PACK = "~/agii_runs/v3c1_pack/pack_v3c1_v7.json"
HUMAN_V3C1B_PACK_SHA256 = "6b4ecfbd110c98f103ac6435f48aff6bcdf27f250de7df7348b58765eac8d2bf"
HUMAN_V3C1B_HARD_PACK = "~/agii_runs/v3c1_pack/pack_v3c1_v7hard2.json"      # 11-12 主试验：只在 hard 开关下收（严格封印 + 不打 boss + 无对应表 + 考试关不规则节奏）
HUMAN_V3C1B_HARD_PACK_SHA256 = "2e6a44d14bbfbdb8ccad2ff667e19ff26f3623dcfecaed55c05e05a26f5ad503"
HUMAN_V3C1B_HARD_ENV = dict(PROTO_WARDSTRICT="blockonly", PROTO_BOSSLIFE="off", PROTO_CORRESPOND="off",
                            PROTO_MAPCHARGE="len234", PROTO_MAPGUARD="irr50", PROTO_WARDLIMIT="10", PROTO_WARDTESTSTART="3")   # hard2 修订：10回合封印时限，考试3层
HUMAN_V3C1B_HARD_RETIRED = {"10c7966a15525c154b9c353e02c101fb963789816ac0f67c3bdd5a32f70b9065":
                            "pack_v3c1_v7hard (the same maps with fixed rhythms in test fights), replaced by pack_v3c1_v7hard2"}
HUMAN_V3C1B_RETIRED = {"d6af3757db4302824e0f985b43ce80e492a573025e489767bdcc97f24a114ff3": "pack_v3c1_v2",   # 停用的包：明确拒绝（41 §10、43 号文档）
                       "67ab6dcb47ed4f6fed1a45dd14bdfb524193f0fb7a19d67590fac83149db2236": "pack_v3c1_v3",
                       "07770b5bf076dabf324f1f4b7ca8785bda1d5b858de9f53e5e498f11ef40d43c": "pack_v3c1_v4",
                       "7221f4fb4e89c22a2ffd015929d36031090eb682e76b1bd85070c209326743d7": "pack_v3c1_v5",
                       "b72c74aa665be871ff9b11a5cb7f8733ea2611b9e6a30174387a36e1204b6f5b": "pack_v3c1_v6"}
HUMAN_V3C1B_REPLACED = "replaced by pack_v3c1_v7 (healing removed; all bosses announce the phase change)"
HUMAN_V3C1B_BOSS = {1: ('175', None, None), 2: ('225', None, 'k19'), 3: ('225', None, 'k3'), 4: ('125', '130', 'k21'), 5: ('175', None, 'k42'), 6: ('150', '150', 'k82'), 7: ('150', '105', 'k13'), 8: ('250', None, 'k15')}
_HUMAN_ENTRIES = dict(
    v3b=dict(flag=HUMAN_V3B_FLAG, env=HUMAN_V3B_ENV, free=HUMAN_V3B_FREE, now=HUMAN_V3B_NOW, version=HUMAN_V3B_VERSION, dir=HUMAN_V3B_DIR,
             dir_env=HUMAN_V3B_DIR_ENV, camp_refusal=HUMAN_V3B_CAMP_REFUSAL, name="candidate v3b"),
    v3c=dict(flag=HUMAN_V3C_FLAG, env=HUMAN_V3C_ENV, free=HUMAN_V3C_FREE, now=HUMAN_V3C_NOW, version=HUMAN_V3C_VERSION, dir=HUMAN_V3C_DIR,
             dir_env=HUMAN_V3C_DIR_ENV, camp_refusal=HUMAN_V3C_CAMP_REFUSAL, name="candidate v3c"),
    v3c1=dict(flag=HUMAN_V3C1_FLAG, env=HUMAN_V3C1_ENV, free=HUMAN_V3C1_FREE, now=HUMAN_V3C1_NOW, version=HUMAN_V3C1_VERSION, dir=HUMAN_V3C1_DIR,
              dir_env=HUMAN_V3C1_DIR_ENV, camp_refusal=HUMAN_V3C1_CAMP_REFUSAL, name="candidate v3c1",
              pack=HUMAN_V3C1_PACK, pack_sha256=HUMAN_V3C1_PACK_SHA256),
    v3c1b=dict(flag=HUMAN_V3C1B_FLAG, env=HUMAN_V3C1B_ENV, free=HUMAN_V3C1B_FREE, now={k: v for k, v in BOSS_WORLD_NOW_W.items() if k != "boss_cue"}, version=HUMAN_V3C1B_VERSION, dir=HUMAN_V3C1B_DIR,
               dir_env=HUMAN_V3C1B_DIR_ENV, camp_refusal=HUMAN_V3C1B_CAMP_REFUSAL, name="candidate v3c1 with the boss (pack v7)",
               pack=HUMAN_V3C1B_PACK, pack_sha256=HUMAN_V3C1B_PACK_SHA256, now_free=BOSS_WORLD_NOW_FREE + ("boss_cue",), boss=HUMAN_V3C1B_BOSS,
               retired=HUMAN_V3C1B_RETIRED, hard_pack=HUMAN_V3C1B_HARD_PACK, hard_pack_sha256=HUMAN_V3C1B_HARD_PACK_SHA256))

# 参与者文字（v1.2，用户 2026-11-03）。ADV_SYSTEM_REGISTERED = 导入时 modelrun 的原文（有营地时逐字用它）。
ADV_SYSTEM_REGISTERED = modelrun.ADV_SYSTEM
NO_CAMP_OPENING = "The air is cold. You can hear other things moving in the distance.\n\n"
ADV_SYSTEM_NO_CAMP = NO_CAMP_OPENING + ADV_SYSTEM_REGISTERED[ADV_SYSTEM_REGISTERED.index("Each step you may:"):]
RETRY_DIED = "You have been here before. You did not survive it."          # modelrun.RETRY_HEAD 的第一行（原文）
RETRY_CLEARED = "You have been here before. You came through it."
assert ADV_SYSTEM_REGISTERED.startswith("The wall has opened.\n") and modelrun.RETRY_HEAD.startswith(RETRY_DIED + "\n")
# 导入时的 modelrun.handover_evidence：write_letter 写信时把 modelrun.handover_evidence 换成本文件的版本，有营地的那一支要调原函数
# （v1.1 调的是 modelrun.handover_evidence 当时的绑定 = 本文件的版本自己 → 有营地时写信无限递归；C19 发现，v1.2 修）
_MODELRUN_EVIDENCE = modelrun.handover_evidence


# ---------------------------------------------------------------- 设置
def setup():
    """现行原型版本 + boss 层（setup_boss 的默认 = 现行 boss 设置；待用户定的规则一律不动）。幂等。"""
    if ap.LOOT or ap.NODES != "fixed":
        raise SystemExit(f"This entry plays only the current prototype version (PROTO_LOOT=0, PROTO_NODES=fixed); now loot={ap.LOOT} "
                         f"nodes={ap.NODES}. The archived participant path is the main of core/modelrun.py.")
    ab.setup_boss()
    import reasoning_capture
    reasoning_capture.install()
    from adventure import TUNING
    assert TUNING["auto_rest"] == 1, TUNING["auto_rest"]
    assert modelrun.BOSS_SHIFT_TEXT == ab.CUE_TEXT, modelrun.BOSS_SHIFT_TEXT
    _READY["setup"] = True


def boss_world():
    """11-07（40 号文档）：PROTO_TEXT=minimal 且解析后的开关（除每个世界自己的 boss_hp / boss_atk）正好是 BOSS_WORLD_NOW（图包 pack_v3c1_v2 的 boss 环境）。
    是 → 一个世界第 1–5 条命，第 5 条命打 boss；参与者看到的那一场写成 [layer 1]。不是 → 什么也不变。"""
    now = {k: v for k, v in ap._now().items() if k not in BOSS_WORLD_NOW_FREE}
    if _cue_explicit():                                     # 修订 7（43 §20、50 号文档）：环境明写 PROTO_BOSS_CUE=on / off 时提示与机制类型脱钩
        now.pop("boss_cue", None)
        return pt.minimal() and now in tuple({k: v for k, v in d.items() if k != "boss_cue"} for d in (BOSS_WORLD_NOW, BOSS_WORLD_NOW_W))
    return pt.minimal() and now in (BOSS_WORLD_NOW, BOSS_WORLD_NOW_W)


BOSS_CUE_FIXED = ("on", "off")                              # 修订 7：每条链、每个世界固定给 / 不给提示（50 号文档）；不写 = 包 v6 的 bytype


def _cue_explicit(env=None):
    """环境（默认本进程）里明写了 PROTO_BOSS_CUE=on / off。包 v6 的世界都是 bytype → 假 → 下面两处的核对与原来逐字相同。"""
    return (os.environ if env is None else env).get("PROTO_BOSS_CUE") in BOSS_CUE_FIXED


def boss_world_problems(spec):
    """boss 世界里这个世界（spec，带图包的 boss.env）能不能在本进程打（英文，空 = 能）：进程的 PROTO_* 正好是这个世界的 boss.env
    （外加 BOSS_WORLD_EXTRA 和人类入口的开关），boss.env 除血 / 伤害外 = BOSS_WORLD_ENV，导入时读到的血 / 伤害 = boss.env 的。
    这样打这个世界（图和 boss）的进程与图包重放核对（pack_v3c1_v2_replay.py）的进程是同一套模块状态。"""
    env = (spec.get("boss") or {}).get("env")
    if not isinstance(env, dict):
        return [f"world {spec.get('id')} has no stored boss settings (boss.env)"]
    bad = [f"{k}={os.environ.get(k, '(unset)')} (this world needs {v})" for k, v in env.items() if os.environ.get(k) != v]
    bad += [f"{k}={v} (must be unset for this world)" for k, v in sorted(os.environ.items())
            if k.startswith("PROTO_") and k not in env and k not in BOSS_WORLD_EXTRA + (HUMAN_V3C1B_FLAG,)]
    fixed = {k: v for k, v in env.items() if k not in BOSS_WORLD_PER_WORLD}
    refs = (BOSS_WORLD_ENV, BOSS_WORLD_ENV_W)
    if _cue_explicit(env):                                  # 修订 7：提示开关按链 / 世界给（on / off），其余照旧必须等于 boss 环境
        fixed.pop("PROTO_BOSS_CUE")
        refs = tuple({k: v for k, v in d.items() if k != "PROTO_BOSS_CUE"} for d in refs)
    if fixed not in refs:
        bad.append(f"the stored boss settings of world {spec.get('id')} are not the pack_v3c1_v2 boss environment")
    if (ap.BOSS_HP, ap.BOSS_ATK) != (env.get("PROTO_BOSS_HP", "100"), env.get("PROTO_BOSS_ATK", "100")):
        bad.append(f"this process runs the boss at health {ap.BOSS_HP}% and attack {ap.BOSS_ATK}%, this world needs "
                   f"{env.get('PROTO_BOSS_HP', '100')}% and {env.get('PROTO_BOSS_ATK', '100')}%")
    if ap.WORLD != env.get("PROTO_WORLD", "A"):             # 世界外衣（43 号文档）：导入时读到的 PROTO_WORLD = boss.env 的（A = 不设）
        bad.append(f"this process runs world surface {ap.WORLD}, this world needs {env.get('PROTO_WORLD', 'A')}")
    if (spec.get("surface") or {}).get("name", "A") != env.get("PROTO_WORLD", "A"):
        bad.append(f"world {spec.get('id')} is stored with surface {(spec.get('surface') or {}).get('name', 'A')} but its boss settings name "
                   f"{env.get('PROTO_WORLD', 'A')}")
    return bad


def _api_setup(model, run_id):
    """真跑时 modelrun.main 开头做的那几件（缓存键、花费上限、档位检查）；假模型和人类入口不调。"""
    from study_models import require_active
    require_active(model)
    modelrun.CACHE_KEY = f"agii:{modelrun._slug(model)}:{run_id}"
    modelrun.BUDGET_KEY = os.environ.get("AGII_BUDGET_KEY") or f"{modelrun._slug(model)}_{run_id}"
    cap = os.environ.get("AGII_BUDGET_USD", "").strip()
    modelrun.BUDGET_USD = float(cap) if cap else None
    import prices
    if modelrun.BUDGET_USD is not None and prices.price_for(model) is None:
        raise SystemExit(f"设了花费上限 ${modelrun.BUDGET_USD}，但 prices.py 里没有 {model} 的价格。")
    modelrun.effort_for(modelrun.provider_for(model))
    modelrun._check_budget()


# ---------------------------------------------------------------- 交接（modelrun 的文字，没有营地时去掉营地那段）
def handover_evidence(carry, transcript, notes, prev_adv=(), earlier=(), camp=None):
    """modelrun.handover_evidence。camp=None 时按 transcript 是否为空判断有没有营地。没有营地：不放「In the room without doors」
    那段营地记录和「What you concluded there」那段营地结论；RETRY_LOG_HEAD 只在真有前面几条命的记录时才放；每条命的标签是
    "Life {n} ({res}):"（v1.2；modelrun 的 "Life {n}, outside ({res}):" 的 outside 指营地外面）。其余逐字相同。"""
    if camp is None:
        camp = bool(transcript)
    if camp:
        return _MODELRUN_EVIDENCE(carry, transcript, notes, prev_adv, earlier)
    carried = []
    if carry in ("log", "both"):
        lives = [f"Life {n} ({res}):\n" + "\n".join(f"  {i}. {h}" for i, h in enumerate(log, 1))
                 for n, log, res in prev_adv if log]
        if lives:
            carried += [modelrun.RETRY_LOG_HEAD] + lives
    if carry in ("notes", "both"):
        written = modelrun._prior_life_notes(earlier)
        if written:
            carried.append(written)
    return carried


def retry_head(prev_result, life):
    """第 life 条命（>1）交接里的 RETRY_HEAD，第一行说第 life-1 条命记录的结果（v1.2）：死了（"died at …"）= modelrun.RETRY_HEAD 原文；
    打通（"cleared"）= 第一行换成 RETRY_CLEARED，其余逐字。没有结果、或认不出的结果：拒绝（不编一个结果，也不退到中性的一句）。
    拒绝的话是英文：人类命令行入口会直接印出来。"""
    if prev_result == "cleared":
        return RETRY_CLEARED + modelrun.RETRY_HEAD[len(RETRY_DIED):]
    if isinstance(prev_result, str) and prev_result.startswith("died at "):
        return modelrun.RETRY_HEAD
    raise SystemExit(f"Life {life - 1} has no recorded result ({prev_result!r}), so life {life} cannot be told how it ended. "
                     f"Play life {life - 1} first.")


def build_handover(life, carry, transcript, notes, prev_adv=(), earlier=(), letters=(), camp=False):
    """第 1 条命：有营地 = modelrun.build_handover 原样；没有营地 = 只有信。第 k>1 条命：信 → retry_head(prev_adv 里第 k-1 条命的结果)
    → handover_evidence（有营地时就是 modelrun 的）—— 有营地时除 RETRY_HEAD 第一行外与 modelrun.build_handover 逐字相同。"""
    if life == 1:
        if camp:
            return modelrun.build_handover(life, carry, transcript, notes, prev_adv, earlier, letters)
        return "\n\n".join([modelrun.letters_block(letters)] if letters else [])
    prev = {n: res for n, _log, res in prev_adv}
    carried = [modelrun.letters_block(letters)] if letters else []
    carried.append(retry_head(prev.get(life - 1), life))
    carried += handover_evidence(carry, transcript, notes, prev_adv, earlier, camp=camp)
    return "\n\n".join(carried)


def retry_line(handover, letters=()):
    """交接里 RETRY_HEAD 第一行（RETRY_DIED / RETRY_CLEARED）；没有就 None。记录用。按 build_handover 的位置读：先去掉信那一段
    （letters_block(letters) + 空行），再取下一行 —— 不在全文里找第一处（审查 2026-11-03：信里引用了这两句时，第一处是信里的那句）。"""
    pre = modelrun.letters_block(letters) + "\n\n" if letters else ""
    if not handover.startswith(pre):
        return None
    line = handover[len(pre):].split("\n", 1)[0]
    return line if line in (RETRY_DIED, RETRY_CLEARED) else None


@contextlib.contextmanager
def adv_system(camp):
    """这条命的行动系统提示（v1.2）。有营地：modelrun.ADV_SYSTEM 原文，不动。没有营地：modelrun.ADV_SYSTEM 在这条命里临时换成
    ADV_SYSTEM_NO_CAMP，退出时还原 —— modelrun._call_kind（core/modelrun.py:409-410）按文字认种类，换掉模块全局，新文字在 call()
    （USAGE_BY_KIND、TRACE）、humanrun.human_act、假模型和核对的分类里都得到原文的种类 "adv-act"；只把新文字传给 run_fight 而不换全局，
    它会被记成 "debrief"。"""
    if camp:
        yield modelrun.ADV_SYSTEM
        return
    saved = modelrun.ADV_SYSTEM
    if saved != ADV_SYSTEM_REGISTERED:
        raise RuntimeError("modelrun.ADV_SYSTEM 已被别处换掉（嵌套的命？）：不再换")
    new = pt.ADV_SYSTEM if pt.minimal() else ADV_SYSTEM_NO_CAMP          # PROTO_TEXT=minimal：B1（23 号文档）
    modelrun.ADV_SYSTEM = new
    try:
        yield new
    finally:
        modelrun.ADV_SYSTEM = saved


# ---------------------------------------------------------------- 一条命
def _jsonable(x):
    return json.loads(json.dumps(x, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o)))


def _boss_record(ctx, f, adv_log, entry):
    cue = ab.CUE_TEXT
    at = [k for k, h in enumerate(adv_log) if h == cue]
    prev = [adv_log[k - 1] if k else None for k in at]
    info = ab.fight_info(f) or {}
    cue_late = [not (p or "").startswith(("end turn", modelrun.FORCED_END + "  ->  ")) for p in prev]   # §5.4；11-10 起强制结束也写结算行，提示紧跟其后不算迟到
    d1 = dict(handover=info.get("handover"), log_quieted=info.get("log_quieted"), guard0=info.get("guard0"))
    if ap.INCOMING == "real":                     # v1.3（12 §5.5，D10 待用户）：强制结束的换阶段回合没有 END 那一行，进场起点不会出现在任何日志行里
        d1["incoming_unlogged"] = sorted((info.get("handover") or {}).get("incoming_changes") or {}) if any(cue_late) else []
    if info.get("threat"):                        # v1.3（12 §6.5）：PROTO_THREAT=momentum 的刷新真写过时才有
        d1["threat"] = info["threat"]
    return _jsonable(dict(
        salt=ctx["salt"], pair=list(ctx["pair"]), phase_order=list(ctx["phase_order"]), boss_hp=ctx["boss_hp"],
        switch_at=ctx["switch_at"], boss_atk=ctx["boss_atk"], tuning=ctx["tuning"], slot_fix=ctx["slot_fix"],
        init_fixes=ctx["init_fixes"], entry=entry, switched=bool(f._phase2), switch_turn=f._phase2_turn if f._phase2 else None,
        phase2_met=bool(f._phase2), cue_text=cue, cue_lines=len(at), cue_after=prev,
        cue_late=cue_late, d1=d1))


def play_life(model, spec, life, key, *, run_id, carry="notes", want_notes=True, fight_notes="write", letters_from=(),
              who="model", verbose=False, overwrite=False, camp_turns=modelrun.CAMP_TURNS, camp_steps=modelrun.CAMP_STEPS,
              world_index=None, prev_surface=None, resume=False):
    """Persist each model response; resume=True reconstructs an interrupted life."""
    setup()
    import reasoning_capture as rc
    import durable_resume as checkpoint
    options = dict(run_id=run_id, carry=carry, want_notes=want_notes, fight_notes=fight_notes, letters_from=letters_from,
                   who=who, verbose=verbose, overwrite=overwrite, camp_turns=camp_turns, camp_steps=camp_steps,
                   world_index=world_index, prev_surface=prev_surface)
    # Human replay and the old fake-model harness retain their existing path.
    if who != "model" or overwrite or modelrun.call is not rc._call:
        if resume:
            raise ValueError("Resume is for model calls and cannot be combined with replay/overwrite")
        return _play_life(model, spec, life, key, **options)
    path = modelrun._record(model, ap.SEED, life, run_id=run_id)
    completed = json.loads(path.read_text()) if path.exists() else {}
    if completed.get("result") and not resume:
        return _play_life(model, spec, life, key, **options)  # existing no-overwrite error
    sources = [modelrun._record(model, ap.SEED, n, run_id=run_id) for n in range(1, life)]
    sources += [modelrun._letter_path(model, ap.SEED, name) for name in letters_from]
    metadata = dict(operation="life", run_id=run_id, life=life, spec=_jsonable(spec), proto=ap.settings(),
                    api=modelrun.api_settings(model), carry=carry, want_notes=want_notes, fight_notes=fight_notes,
                    world_index=world_index, prev_surface=prev_surface, camp_turns=camp_turns, camp_steps=camp_steps,
                    inputs=checkpoint.file_evidence(sources), text=pt.MODE, text_version=pt.VERSION,
                    budget_key=os.environ.get("AGII_BUDGET_KEY") or f"{modelrun._slug(model)}_{run_id}",
                    engine=modelrun.ENGINE_VERSION, protocol=modelrun.PROTOCOL_VERSION)
    with checkpoint.operation(model, path, metadata, resume=resume) as state:
        if completed.get("result"):
            if completed.get("proto_world_spec") != _jsonable(spec) or completed.get("carry") != carry:
                raise RuntimeError("Completed life belongs to another world or memory mode")
            if (not checkpoint.api_matches(completed.get("api"), modelrun.api_settings(model), model, path) or bool(completed.get("notes_written")) != bool(want_notes)
                    or completed.get("fight_notes_mode") != fight_notes):
                raise RuntimeError("Completed life's API or note settings differ from this run")
            state["completed"] = True
            return dict(completed, record=path, life=life, kind=completed["proto_life"]["kind"],
                        run=None, ctx=None, fight=None, skipped_completed=True)
        return _play_life(model, spec, life, key, **options)


def _play_life(model, spec, life, key, *, run_id, carry="notes", want_notes=True, fight_notes="write", letters_from=(),
              who="model", verbose=False, overwrite=False, camp_turns=modelrun.CAMP_TURNS, camp_steps=modelrun.CAMP_STEPS,
              world_index=None, prev_surface=None):
    """一条命：life 1–4 = spec 的第 life 张图，life 5 = boss。参与者由 modelrun.act / pick / call 当时的绑定决定（模型、假模型、人）。
    world_index：PROTO_TEXT=minimal 下 B2 的 w（None = 按信的链算；默认文字下不用）。"""
    if not _READY["setup"]:
        setup()
    from adventure import TUNING
    assert who in WHO and 1 <= life <= N_LIVES and carry in CARRIES and fight_notes in FIGHT_NOTES, (who, life, carry, fight_notes)
    if who == "model" and not run_id.startswith(RUN_PREFIX):
        raise ValueError(f"模型的 run_id 要以 {RUN_PREFIX!r} 开头：{run_id!r}")
    if not str(spec["id"]).startswith(pw.ID_PREFIX):
        raise ValueError(f"A world id must start with {pw.ID_PREFIX!r}: {spec['id']!r}")
    pw.verify(spec)
    bw = boss_world()                                       # 11-07（40 号文档）：boss 世界；默认与已有的入口下 False，下面三处 bw 分支都不跑
    layered = carry == "layered"                            # 46 号文档（11-08）：分层记忆；别的 carry 下下面的 layered 分支一个也不跑
    if layered and not (pt.minimal() and bw and who in ("model", "human")):    # 11-10：人类入口也用分层记忆（同模型）
        raise SystemExit("carry=layered is only for a boss world under PROTO_TEXT=minimal (docs/antagonist_boss/46).")
    if bw:
        bad = boss_world_problems(spec)
        if bad:
            raise SystemExit(f"World {spec['id']} is played only under its own boss settings (boss.env in the world file); refused: "
                             + "; ".join(bad))
    boss_keys = ab.boss_settings()
    now_keys = {k: TUNING[k] for k in ab.BOSS_KEYS}
    if boss_keys is None or now_keys != boss_keys:          # 脚本参照与参与者同一套 boss 规则（审查 2026-11-03 的 boss_no_probe 问题）
        raise RuntimeError(f"The boss settings differ from the ones setup_boss fixed: TUNING {now_keys} vs {boss_keys}")
    seed = ap.SEED
    path = modelrun._record(model, seed, life, run_id=run_id)
    prev = json.loads(path.read_text()) if path.exists() else None
    if isinstance(prev, dict) and prev.get("proto_world") != spec["id"]:      # 一个 run_id 只装一个世界（审查 2026-11-03；开打前拒绝）
        raise SystemExit(f"{path.name} holds life {life} of world {prev.get('proto_world')!r}, not of world {spec['id']!r}. "
                         "One run id holds one world; use another run id.")
    prev_result = prev.get("result") if isinstance(prev, dict) else None
    if prev_result and not overwrite:
        raise SystemExit(f"{path.name} already has a result; it is not overwritten (a replay needs --replay).")
    attempt = int(prev.get("attempt") or 1) + 1 if prev_result else 1              # 重打的是同一副牌：记下是第几次
    previous_results = list(prev.get("previous_results") or []) + [prev_result] if prev_result else []
    if who == "model":
        import reasoning_capture
        reasoning_capture.bind(model, path)
    modelrun.TRACE.clear()
    u0 = modelrun._usage_snapshot()
    letters = modelrun.load_letters(model, seed, letters_from)
    kind = "map" if life <= N_MAPS else "boss"
    salt = spec["maps"][life - 1]["salt"] if kind == "map" else spec["boss"]["salt"]
    camp_on = ap.camp()
    if camp_on and ap.HAND == "fixed" and not pc.supported():   # v1.2.2：营地还没做固定手牌；导入时的拒绝挡不住运行中改 ap.CAMP（v3b+minimal：proto_camp）
        raise SystemExit("The camp is not implemented for PROTO_HAND=fixed.")
    w = None
    if pt.minimal():                                        # PROTO_TEXT=minimal（默认下这一段不跑）
        if camp_on and not pc.supported():
            raise SystemExit("The camp is not implemented for PROTO_TEXT=minimal.")
        if life > world_lives():
            raise SystemExit(f"Under candidate v3b a world is lives 1-{world_lives()} (maps only); the boss is not built.")
        w = world_index if world_index is not None else pt.world_index_from_letters(model, seed, letters_from)
        if layered:                                         # 46 §8 的配置断言（11-08 审查）：编号与信一致、要写笔记、第 1 个世界要有营地
            if letters_from and world_index is not None and world_index != pt.world_index_from_letters(model, seed, letters_from):
                raise SystemExit(f"world_index={world_index} does not follow the letter carried in "
                                 f"(world {pt.world_index_from_letters(model, seed, letters_from) - 1}).")
            if not want_notes:
                raise SystemExit("carry=layered needs the notes (want_notes=True): the notes are the only memory.")
            if w == 1 and not (camp_on and pc.supported()):
                raise SystemExit("carry=layered: the first world is played with the camp (PROTO_CAMP=1).")
    camp_v3b = camp_on and pc.supported() and (not layered or w == 1)   # 候选 v3b 的训练营；layered：只有参与者的第 1 个世界有营地（46 U8）
    with ap.using_display(who) as disp, adv_system(camp_on and not camp_v3b and not layered) as system, \
            (pt.session() if pt.minimal() else contextlib.nullcontext()):
        shown = {k: TUNING[k] for k in ("marks", "state_slots")}
        if kind == "map":
            run, ctx = ap.build(salt), None
        else:
            ctx = ab.build_boss(salt, tuple(spec["boss"]["order"]), 0)
            run = ctx["run"]
            assert list(ctx["phase_order"]) == list(spec["boss"]["order"]), (ctx["phase_order"], spec["boss"]["order"])
            assert ctx["tuning"] == boss_keys, (ctx["tuning"], boss_keys)
        if ap.MARKMAP == "world":                           # v1.3（12 §8.1）：一个世界一张代号表（D13），4 张图和 boss 共用
            pw.bind_world(run, spec)
        ap.require_mark_table(run)                          # salt（默认）下什么也不做
        earlier, prev_adv, prior_armour = (), (), False
        if life > 1:
            earlier = [(n, modelrun._load(model, seed, n, run_id=run_id)) for n in range(1, life)]
            earlier = [(n, d) for n, d in earlier if d]
            if not earlier:
                raise SystemExit(f"There is no record of the earlier lives of {model} / {run_id}.")
            other = [(n, d.get("proto_world")) for n, d in earlier if d.get("proto_world") != spec["id"]]
            if other:                                       # 别的世界的命：不把它的结果、日志、笔记交给这个世界（审查 2026-11-03）
                raise SystemExit(f"Run {run_id} holds life {other[0][0]} of world {other[0][1]!r}, not of world {spec['id']!r}, "
                                 f"so life {life} cannot be told how it ended. One run id holds one world; use another run id.")
            first = earlier[0][1]
            if first.get("proto_camp") is not None and bool(first["proto_camp"]) != camp_on:
                raise SystemExit(f"Life 1 of this world was played with proto_camp={first['proto_camp']}, now PROTO_CAMP={int(camp_on)}; "
                                 "the camp setting cannot change within a world.")
            if layered or first.get("carry") == "layered":  # 11-08 审查：同一个世界里记忆方式、写不写笔记、入境信（来源与内容）都不能变
                same = dict(carry=(first.get("carry"), carry), notes=(bool(first.get("notes_written")), bool(want_notes)),
                            letters_from=(list(first.get("letters_from") or []), list(letters_from or ())),
                            letters_sha=(first.get("letters_sha"), modelrun._sha(pt.letters_block(letters)) if letters else None))
                bad = [f"{k} was {a!r} in life 1, now {b!r}" for k, (a, b) in same.items() if a != b]
                if bad:
                    raise SystemExit("Within a world the memory settings cannot change: " + "; ".join(bad) + ".")
            first_hand = (first.get("proto") or {}).get("hand", "draw")      # v1.2.2：手牌规则在一个世界里也不能变（PROTO_HAND）
            if first_hand != ap.HAND:
                raise SystemExit(f"Life 1 of this world was played with the {first_hand} hand rule, now PROTO_HAND={ap.HAND}; "
                                 "the hand rule cannot change within a world.")
            now_sw = ap._now()
            for k in ("incoming", "threat", "markmap"):     # v1.3：三个候选开关在一个世界里也不能变（旧记录没有这些键 = 默认）
                was = (first.get("proto") or {}).get(k, ap.DEFAULTS[k])
                if was != now_sw[k]:
                    raise SystemExit(f"Life 1 of this world was played with PROTO_{k.upper()}={was}, now PROTO_{k.upper()}={now_sw[k]}; "
                                     "this setting cannot change within a world.")
            for k in ap.V3_KEYS:                            # 候选 v3：同上（旧记录没有这些键 = 默认；默认下两边都没有，什么也不做）
                was = (first.get("proto") or {}).get(k, ap.default_of(k))
                if was != now_sw.get(k, ap.default_of(k)):
                    raise SystemExit(f"Life 1 of this world was played with PROTO_{k.upper()}={was}, now "
                                     f"PROTO_{k.upper()}={now_sw.get(k, ap.default_of(k))}; this setting cannot change within a world.")
            was_text = (first.get("participant_text") or {}).get("text", "registered")     # 文字开关在一个世界里也不能变（旧记录 = registered）
            if was_text != pt.MODE:
                raise SystemExit(f"Life 1 of this world was played with PROTO_TEXT={was_text}, now PROTO_TEXT={pt.MODE}; "
                                 "the participant text cannot change within a world.")
            if pt.minimal() and (first.get("participant_text") or {}).get("world_index") != w:
                raise SystemExit(f"Life 1 of this world was played as world {(first.get('participant_text') or {}).get('world_index')}, "
                                 f"now world {w}; the world index cannot change within a world.")
            if ap.MARKMAP == "world" and (first.get("mark_map") or {}).get("table") != list(run.mark_perm):
                raise SystemExit("Life 1 of this world was played with another mark code table; "
                                 "the mark code table cannot change within a world.")
            prior_armour = any(d.get("behaviour", {}).get("armour", {}).get("evidence_events", 0)
                               or d.get("behaviour", {}).get("armour", {}).get("breaks", 0)
                               or d.get("opportunities", {}).get("armour", 0) for _, d in earlier)
            camp_log, notes = first.get("camp_log", []), first.get("notes", "")
            camp_experiments, camp_used, left_early = first.get("camp_experiments"), first.get("camp_used", 0), first.get("left_early", False)
            prev_adv = [(n, d.get("adv_log", []), d.get("result", "?")) for n, d in earlier]
        elif camp_v3b:                                      # 候选 v3b 的训练营：一个世界一次，第 1 条命开打之前（proto_camp）
            camp_log, camp_experiments, camp_info, notes = _camp_v3b(model, key, run, w, letters, prev, want_notes, who, verbose, seed, run_id,
                                                                     salt, spec, life)
            camp_used, left_early = camp_info["turns_used"], camp_info["left_early"]
        elif camp_on and not layered:                       # PROTO_CAMP=1：同 modelrun.main 第 1 条命的营地（layered 的世界 2 起没有营地）
            c = Camp(run.deck, run.layout, base_atk=run.base_atk, rng=modelrun.camp_rng(seed))
            camp_log, camp_experiments = modelrun._run_camp(model, key, c, camp_turns, verbose, camp_steps, modelrun.letters_block(letters))
            camp_used = turns_used(c, camp_turns)
            left_early = camp_log[-1] == "LEAVE" if camp_log else False
            notes = ""
            if want_notes:
                transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(camp_log, 1))
                notes = modelrun.call(model, "You are reporting what you learned from an experiment. Answer in prose. Do not reply with an action.",
                                      "You interacted with an unknown system. Here is the full record:\n\n" + transcript + "\n\n" + modelrun.DEBRIEF, key)
                modelrun._dump(model, seed, life=life, run_id=run_id, payload=dict(
                    camp_log=camp_log, camp_used=camp_used, camp_experiments=camp_experiments, left_early=left_early, notes=notes,
                    salt=salt, world=None, pack=None, letters_from=list(letters_from or ()), proto=ap.settings(), proto_world=spec["id"],
                    proto_camp=True))
        else:
            camp_log, camp_experiments, camp_used, left_early, notes = [], None, 0, False, ""
        transcript = "\n".join(f"  {i}. {h}" for i, h in enumerate(camp_log, 1))
        camp_ev = dict(log=camp_log, notes=notes) if camp_v3b else None
        lay = None
        if layered:                                         # 46 §2 / §8：旧记忆 = 信 + 营地笔记（第 1 个世界）+ 本世界此前的命笔记 + 对应表（世界 2 起）
            surface = ap.WORLD
            if w >= 2:
                lf = (json.loads(modelrun._letter_path(model, seed, letters_from[-1]).read_text()).get("layered") or {}) if letters_from else {}
                ps = lf.get("surface")
                if letters_from and ps is None:
                    raise SystemExit("The letter carried in was not written under carry=layered; its world's surface is unknown.")
                if prev_surface is not None and ps is not None and prev_surface != ps:
                    raise SystemExit(f"prev_surface={prev_surface!r} but the letter was written in surface {ps!r}.")
                ps = ps or prev_surface
                if ps is None:
                    raise SystemExit("World 2 and later need the previous world's surface (from the letter, or prev_surface= without a letter).")
                if ps == surface:
                    raise SystemExit(f"The previous world's surface {ps!r} is this world's own surface; consecutive worlds differ.")
                mapping = pt.correspondence(ps, surface, w) if ap.CORRESPOND == "on" else None   # PROTO_CORRESPOND=off：不给对应表，也不说别的
            else:
                ps, mapping = None, None
            camp_notes = notes if w == 1 else ""
            life_notes = [(n, d.get("adv_notes", "")) for n, d in earlier]
            memory = pt.layered_memory(w, life, letters, camp_notes, life_notes, mapping)
            lay = dict(version=pt.LAYERED_VERSION, world_index=w, surface=surface, prev_surface=ps, mapping=mapping, correspond=ap.CORRESPOND, camp_in_world=w == 1,
                       letters_from=list(letters_from or ()), life_notes_from=[n for n, t in life_notes if t], fight_note_limit=pt.FIGHT_NOTE_LIMIT,
                       history_scope="this fight", memory_sha=modelrun._sha(memory), fight_note_bodies_sha=[], boss_note=None)
            handover = memory
        elif pt.minimal():
            handover = pt.build_handover(life, carry, prev_adv, earlier, letters, w, **({"camp": camp_ev} if camp_v3b else {}))
        else:
            handover = build_handover(life, carry, transcript, notes, prev_adv, earlier, letters, camp=camp_on)

        adv_log = modelrun.HarnessLog()
        fnotes, kth_opps, fight_index = [], [], [0]
        evidence = modelrun.observe.Evidence()
        mistakes, opportunities, encounters = {}, {}, {}
        resource = {"zero_effect_exhaust": 0, "heal_plays": 0, "full_heal_turns": 0}
        planning = {"avoidable_lethal": 0, "opportunities": 0}
        behaviour = modelrun._new_behaviour_metrics()
        metric_state = {"armour_evidenced": prior_armour}
        shield_audit = {"blocked": 0, "unblocked": 0, "fully_absorbed": 0, "absorbed_total": 0, "fights": 0,
                        "blind": 0, "matched_absorb": 0, "unmatched_absorb": 0}
        auto_rests, fights = [], []
        pending, boss_log = [], []                          # layered：上一场结束后的补给行（进下一场的「本场记录」）；boss 那一场的记录

        def fight(f, label, begin, end):                    # = modelrun.main 的一场（地图那段 / boss 那段），只换标签
            if layered:
                return fight_layered(f, label, begin, end)
            fight_index[0] += 1
            for m in f.parts:
                if m in modelrun.COUNTED:
                    encounters[m] = encounters.get(m, 0) + 1
            adv_log.append(begin)
            mark = len(adv_log)
            em = modelrun._new_encounter_metric(label, f)
            behaviour["encounters"].append(em)
            won = modelrun.run_fight(model, key, system, f, adv_log, verbose,
                                     (pt.carried if pt.minimal() else modelrun._carried)(fight_notes, fnotes, handover),
                                     mistakes, opportunities, resource, planning, behaviour, em, metric_state,
                                     watcher=modelrun.observe.Watcher(evidence, kth_opps, fight_index[0]))
            if pt.minimal():                                # A1：锁定那一行 "  ->  …" → "->  …"（还没有人读到它）
                pt.fix_locked(adv_log, mark)
            feedback = fight_loss_feedback(f)
            if feedback:
                adv_log.append(feedback)
                if verbose:
                    print(f"    {feedback}", flush=True)
            adv_log.append(end)
            if _HUMAN_V3B.get("on") and who == "human":    # PROTO_HUMAN_V3B=1：写战后笔记之前补印这一场还没印的行（见 _human_v3b_flush）
                _human_v3b_flush(adv_log)
            if verbose:
                print(f"    {end}", flush=True)
            modelrun._collect_shield_audit(shield_audit, f)
            run.absorb(f)
            (pt.note_fight if pt.minimal() else modelrun._note_fight)(model, key, fight_notes, fnotes, label, f.enemy.name, adv_log[mark:],
                                                                       verbose)
            return won

        def fight_layered(f, label, begin, end):            # 46 §8：行动只看旧记忆 + 本命此前的战斗笔记 + 对应表 + 本场到目前的记录
            fight_index[0] += 1
            for m in f.parts:
                if m in modelrun.COUNTED:
                    encounters[m] = encounters.get(m, 0) + 1
            adv_log.append(begin)
            flog = modelrun.HarnessLog()
            flog.extend(pending + [begin, OPPONENT_LINE.format(name=f.enemy.name)])   # 11-10（用户选 2）：模型出牌时也看到对手名字，同人类画面的 "Opponent: …"；adv_log 不变
            pre = len(flog)
            pending.clear()
            if who == "human":                              # 11-10：人同模型只看本场记录——本场从头印（补给行、开场、对手），human_act 自己不再另印对手
                humanrun._seen_hist[0] = 0
                humanrun._fight[0] = f
                for k in [k for k in humanrun._shown if isinstance(k, tuple) and k[:1] == ("carry",)]:
                    humanrun._shown.discard(k)              # 每场开头重印记忆块（模型每次决策都带着它）
            em = modelrun._new_encounter_metric(label, f)
            behaviour["encounters"].append(em)
            import gui_skins
            with pt.history_head(pt.FIGHT_HISTORY), gui_skins.encounter(w, life, salt, fight_index[0]):
                won = modelrun.run_fight(model, key, system, f, flog, verbose, pt.layered_carry(memory, fnotes),
                                         mistakes, opportunities, resource, planning, behaviour, em, metric_state,
                                         watcher=modelrun.observe.Watcher(evidence, kth_opps, fight_index[0]))
            pt.fix_locked(flog, pre)
            feedback = fight_loss_feedback(f)
            if feedback:
                flog.append(feedback)
                if verbose:
                    print(f"    {feedback}", flush=True)
            flog.append(end)
            if _HUMAN_V3B.get("on") and who == "human":    # 写战斗笔记前补印本场最后几行（最后一次 END 的变化、fight ended）
                _human_v3b_flush(flog)
            adv_log.extend(flog[pre:])
            if verbose:
                print(f"    {end}", flush=True)
            modelrun._collect_shield_audit(shield_audit, f)
            run.absorb(f)
            this = list(flog)                               # 本场完整记录：上一场之后的补给行（行动时已在本场记录里）+ 开场到收场（11-08 审查）
            if kind == "map":
                body = pt.layered_fight_note(model, key, memory, fnotes, label, f.enemy.name, this, verbose,
                                             work_notes=_wn_block(f))
                lay["fight_note_bodies_sha"].append(modelrun._sha(body))
            else:
                boss_log[:] = this
            return won

        boss_rec = None
        if kind == "map":
            result = "cleared"
            for i, layer in enumerate(run.layers, 1):
                kinds = set(layer.kinds())
                if kinds == {"rest"}:                       # 登记 12 的自动补给：不问、不计分，日志一行环境事件（同 modelrun.main 的 resupply）
                    before = (run.hp, run.max_hp, run.base_atk, run.poison)
                    hp0, hp1 = run.auto_resupply()
                    line = modelrun.resupply_line(i, modelrun.run_changes(run, before))
                    if pt.minimal():                        # B11（proto-text-v2）："[layer N] -> …"，不说 automatic resupply
                        line = pt.resupply_line(line)
                    adv_log.append(line)
                    if layered:
                        pending.append(line)
                    auto_rests.append(dict(layer=i, hp_before=hp0, hp_after=hp1, cap=run.max_hp, scored=False, line=line))
                    if verbose:
                        print(f"  第{i}层 自动补给（环境事件，不计分）{hp0}->{hp1}", flush=True)
                    continue
                assert kinds == {"fight"}, (salt, i, kinds)
                j = ap.fixed_node(run, i - 1)               # 固定的那一场（N2）；不问参与者
                f = run.fight_at(i - 1, j)
                node = layer.nodes[j]
                fights.append(dict(layer=i, node=j, behaviour=node.behaviour, role=node.role, enemy=f.enemy.name))
                if verbose:
                    print(f"  第{i}层 战斗 ({node.behaviour}, {node.role})", flush=True)
                if not fight(f, f"layer {i}", f"[layer {i}] fight begins", f"[layer {i}] fight ended"):
                    result = f"died at layer {i}"
                    break
            hp_end = run.hp
        else:
            with run.trial():                               # D2：满血、起始牌组、命级计数清零、费用未知（同 play_boss）
                assert {k: TUNING[k] for k in ab.BOSS_KEYS} == boss_keys, "boss 键在开打前变了"
                assert run.base_atk == ctx["base_atk"] and run.hp == run.max_hp == run.base_max_hp and run.punished == (0,) * 8
                assert len(run.deck_list) == ap.life_deck_len(), len(run.deck_list)   # 18；修订 6（PROTO_HEAL=off）15
                entry = dict(hp=run.hp, max_hp=run.max_hp, deck=len(run.deck_list), base_atk=run.base_atk)
                f = next(run.boss_fights())
                if verbose:
                    print(f"  boss ({' -> '.join(ctx['phase_order'])})", flush=True)
                fights.append(dict(layer=None, node=None, behaviour="->".join(ctx["phase_order"]), role="boss", enemy=f.enemy.name))
                if bw:                                      # boss 世界：参与者看不到「boss」（用户 11-07）——这一场的标记同一层的图
                    won = fight(f, BOSS_WORLD_LABEL, f"[{BOSS_WORLD_LABEL}] fight begins", f"[{BOSS_WORLD_LABEL}] fight ended")
                else:
                    won = fight(f, BOSS_LABEL, f"[{BOSS_LABEL}] begins", f"[{BOSS_LABEL}] fight ended")
                hp_end = run.hp
            result = "cleared" if won else f"died at {BOSS_WORLD_LABEL if bw else BOSS_LABEL}"
            boss_rec = _boss_record(ctx, f, adv_log, entry)
            boss_rec["tuning_at_play"] = _jsonable(now_keys)

        adv_notes, notes_cap = "", None
        if _HUMAN_V3B.get("on") and who == "human" and not layered:   # PROTO_HUMAN_V3B=1：命末笔记之前补印（最后一层的补给行）；分层下命笔记只读战斗笔记
            _human_v3b_flush(adv_log)
        if want_notes and layered:                         # 46 U4：地图命只读本命的战斗笔记；boss 命只写命笔记（读旧记忆 + boss 的完整记录）
            if kind == "map":
                adv_notes, notes_cap, body = pt.layered_life_note(model, key, fnotes, mapping)
            else:
                adv_notes, notes_cap, body = pt.layered_boss_note(model, key, memory, f.enemy.name, boss_log, work_notes=_wn_block(f))
                lay["boss_note"] = "life note only (no fight note)"
            lay["life_note_body_sha"] = modelrun._sha(body)
        elif want_notes and pt.minimal():                  # B4 + B12：与信同一上限，先缩一次、仍超就截断
            adv_notes, notes_cap = pt.life_notes(model, key, adv_log, fnotes)
        elif want_notes:
            adv_notes = modelrun.call(model, "You are reporting what you learned. Answer in prose.",
                                      modelrun.build_life_debrief(adv_log, fnotes), key)
        payload = dict(
            engine=modelrun.ENGINE_VERSION, metrics=modelrun.METRICS_VERSION, salt=salt, world_status="proto13-prototype",
            registered=False, carry=carry, notes_written=bool(want_notes), fight_notes_carry=fight_notes, screen=None,
            adv_log=adv_log, adv_notes=adv_notes, fight_notes=fnotes, fight_notes_mode=fight_notes,
            usage=modelrun._usage_since(u0), prompt_order=modelrun.PROMPT_ORDER, api=modelrun.api_settings(model),
            life_debrief=modelrun.LIFE_DEBRIEF if want_notes else None, harness_language=modelrun.HARNESS_LANGUAGE,
            world=None, pack=None, letters_from=list(letters_from or ()),
            letters_sha=modelrun._sha(modelrun.letters_block(letters)) if letters else None,
            trace_version=modelrun.TRACE_VERSION, trace=list(modelrun.TRACE), mistakes=mistakes, opportunities=opportunities,
            kth_opportunities=kth_opps, evidence=evidence.seen, behaviour=behaviour, resource=resource, planning=planning,
            encounters=encounters, shield_audit=shield_audit, camp_log=camp_log, camp_used=camp_used,
            camp_experiments=camp_experiments, left_early=left_early, notes=notes, result=result, hp=hp_end,
            run_id=run_id, camp_from=None, rest_rule="auto_rest", auto_rests=auto_rests,
            proto=ap.settings(), proto_play=VERSION, fight_end_feedback="terminal-loss-v3", proto_world=spec["id"], proto_world_spec=spec,
            proto_life=dict(kind=kind, life=life, map=life if kind == "map" else None), proto_camp=camp_on, who=who,
            display=dict(disp), display_tuning=shown, fights=fights, boss=boss_rec, attempt=attempt, previous_results=previous_results,
            replayed=attempt > 1,
            participant_text=dict(adv_system="modelrun" if camp_on else "no-camp", adv_system_sha=modelrun._sha(system),
                                  retry_line=retry_line(handover, letters) if life > 1 else None))
        if pt.minimal():                                    # PROTO_TEXT=minimal：文字记录（默认不加键、不改值）
            payload["letters_sha"] = modelrun._sha(pt.letters_block(letters)) if letters else None
            payload["participant_text"] = dict(adv_system="minimal", adv_system_sha=modelrun._sha(system), retry_line=None, text="minimal",
                                               text_version=pt.VERSION, world_index=w,
                                               life_header=handover.split("\n", 1)[0] if life > 1 or camp_v3b else None)
            if camp_v3b:                                    # 营地（proto_camp）：营地的文字版本与抬头；营地本身（第 1 条命打的）记在 camp
                payload["participant_text"]["camp"] = dict(version=pc.VERSION, header=pt.CAMP_HEADER.format(w=w),
                                                           system_sha=modelrun._sha(pt.CAMP_SYSTEM))
                payload["camp"] = camp_info if life == 1 else (earlier[0][1].get("camp") if earlier else None)
            if notes_cap is not None:
                payload["adv_notes_cap"] = notes_cap
            if layered:
                payload["layered"] = lay
        import work_note
        if work_note.on():                                  # 工作便签（PROTO_WORKNOTE=on）：规则文字指纹与历次版本（off 下不加键）
            payload["work_note"] = work_note.export()
        if ap.MARKMAP == "world":                           # v1.3：world 下记这条命用的代号表（默认不加键）
            payload["mark_map"] = ap.mark_record(run, salt)
        if ap.GUARDCODE == "map":                           # 候选 v3：这条命的守势映射（这张图 / 这个 boss 的；默认不加键）
            gc = dict(run.guard_code)
            payload["guard_code"] = dict(gc, used=gc["boss"] if kind == "boss" else gc["map"], kind=kind)
        if bw:                                              # boss 世界（40 号文档）：这个世界的 boss 环境与第 5 条命的标记（别的环境下不加键）
            payload["boss_world"] = _jsonable(dict(version=BOSS_WORLD_VERSION, env=spec["boss"]["env"], cue=spec["boss"].get("cue"),
                                                   order=spec["boss"]["order"], salt=spec["boss"]["salt"],
                                                   life5_labels=dict(begin=f"[{BOSS_WORLD_LABEL}] fight begins",
                                                                     end=f"[{BOSS_WORLD_LABEL}] fight ended", note_tag=BOSS_WORLD_LABEL,
                                                                     result_on_loss=f"died at {BOSS_WORLD_LABEL}")))
        if _HUMAN_V3B.get("on") and who == "human":         # PROTO_HUMAN_V3B=1：人类入口的版本与世界文件（不设开关时不加键）
            payload["human_entry"] = dict(_HUMAN_V3B.get("entry") or {}, version=_HUMAN_ENTRIES[_HUMAN_V3B.get("variant", "v3b")]["version"],
                                          interface="gui" if _READY["gui_worker"] else "cli", records_dir=_HUMAN_V3B.get("records_dir"))
        import gui_skins
        if gui_skins.enabled() and who == 'human' and kind == 'map':
            payload['interface_skin'] = gui_skins.audit_metadata(w, life, salt, fights)
        modelrun._dump(model, seed, life=life, run_id=run_id, payload=_jsonable(payload))
    if verbose:
        print(f"第 {life} 条命（{kind} {salt}）：{result}，血 {hp_end}", flush=True)
    return dict(run=run, ctx=ctx, life=life, kind=kind, salt=salt, result=result, hp=hp_end, adv_log=list(adv_log), adv_notes=adv_notes,
                fight_notes=fnotes, notes=notes, camp_log=camp_log, camp_used=camp_used, left_early=left_early, fights=fights,
                boss=boss_rec, auto_rests=auto_rests, record=path, handover=handover, fight=f if kind == "boss" else None,
                **({"participant_text": payload["participant_text"]} if pt.minimal() else {}))   # minimal：返回值也写文字版本（registered_record 按它读）


_play_life_core = _play_life


def _play_life(model, spec, life, key, **options):
    """一条命：工作便签（PROTO_WORKNOTE=on，scripts/work_note.py）在这条命期间装上；off 下原样调用。"""
    import work_note
    with work_note.session():
        return _play_life_core(model, spec, life, key, **options)


def _camp_v3b(model, key, run, w, letters, prev, want_notes, who, verbose, seed, run_id, salt, spec, life):
    """候选 v3b 的训练营（proto_camp）：第 1 条命已有打完的营地就复用（一个世界一次；重打第 1 条命也不重打营地），否则打营地、写营后笔记
    （命末笔记同一句与上限）、先写一次第 1 条命的记录（camp.done）。人：营地之后补印没印的行、写笔记、清 humanrun 的已印状态、印第 1 条命的横幅。"""
    import durable_resume
    if pc.reusable(prev, w) and not durable_resume.rebuilding():
        info = dict(prev["camp"], reused=True)
        return list(prev.get("camp_log") or []), prev.get("camp_experiments"), info, prev.get("notes", "")
    camp_log, exp, info = pc.run_camp(model, key, run, w, letters, verbose)
    if who == "human":                                      # 营地最后那次 END 的变化，人在写笔记之前要看到（同 _human_v3b_flush 的理由）
        _human_v3b_flush(camp_log)
    notes, cap = pc.notes(model, key, camp_log) if want_notes else ("", None)
    info["notes_cap"] = cap
    modelrun._dump(model, seed, life=life, run_id=run_id, payload=_jsonable(dict(
        camp_log=camp_log, camp_used=info["turns_used"], camp_experiments=exp, left_early=info["left_early"], notes=notes, camp=info,
        salt=salt, world=None, pack=None, proto=ap.settings(), proto_world=spec["id"], proto_camp=True, who=who,
        participant_text=dict(text="minimal", text_version=pt.VERSION, world_index=w,
                              camp=dict(version=pc.VERSION, header=pt.CAMP_HEADER.format(w=w), system_sha=modelrun._sha(pt.CAMP_SYSTEM))))))
    if who == "human":
        pc.human_reset()
        pc.banner(pt.life_header(w, life))
    return camp_log, exp, info, notes


def _lives(spec_lives):
    if isinstance(spec_lives, str):
        lo, hi = (int(x) for x in spec_lives.split("-")) if "-" in spec_lives else (int(spec_lives),) * 2
    else:
        lo, hi = spec_lives
    if not 1 <= lo <= hi <= N_LIVES:
        raise SystemExit(f"Lives must lie within 1-{N_LIVES}: {spec_lives}")
    return lo, hi


def model_run_id(spec, carry, run_id=None):
    """模型的 run_id：给定的加上 "p13-" 前缀（已有就不加）；没给就是 p13-<世界 id 去前缀>-<carry>。
    v1.3：三个候选开关（incoming / threat / markmap）偏离默认时加后缀（"-incomingreal" …）；默认和 PROTO_HAND=fixed 下后缀为空，run id 不变。"""
    run_id = run_id or f"{RUN_PREFIX}{spec['id'][len(pw.ID_PREFIX):]}-{carry}"
    run_id = run_id if run_id.startswith(RUN_PREFIX) else RUN_PREFIX + run_id
    now = ap._now()
    return run_id + "".join(f"-{k}{now[k]}" for k in ("incoming", "threat", "markmap") if now[k] != ap.DEFAULTS[k])


def play_world(model, spec, *, lives=None, run_id=None, key=None, carry="notes", want_notes=True, fight_notes="write",
               letters_from=(), verbose=True, overwrite=False, world_index=None, prev_surface=None, resume=False):
    """模型玩一个世界（默认第 1–5 条命）。key=None 时读钥匙、设缓存键 / 花费上限（真跑，花钱）；假模型用 fake_model 给的 key。"""
    setup()
    run_id = model_run_id(spec, carry, run_id)
    if key is None:
        key = modelrun._api_key(model)
        _api_setup(model, run_id)
    lo, hi = _lives(lives or (1, world_lives()))
    return [play_life(model, spec, life, key, run_id=run_id, carry=carry, want_notes=want_notes, fight_notes=fight_notes,
                      letters_from=letters_from, who="model", verbose=verbose, overwrite=overwrite,
                      resume=resume,
                      **({"world_index": world_index} if world_index is not None else {}),
                      **({"prev_surface": prev_surface} if prev_surface is not None else {})) for life in range(lo, hi + 1)]


def write_letter(model, run_id, carry, key=None, letters_from=(), verbose=True, resume=False):
    """Resume letter drafting/shortening; an already completed letter is reused."""
    setup()
    import reasoning_capture as rc
    import durable_resume as checkpoint
    if not pt.minimal() or modelrun.call is not rc._call:
        if resume:
            raise ValueError("Letter resume requires the prototype model API path under minimal text")
        return _write_letter(model, run_id, carry, key, letters_from, verbose)
    path = modelrun._letter_path(model, ap.SEED, run_id)
    if path.exists() and not resume:
        return _write_letter(model, run_id, carry, key, letters_from, verbose)
    sources = [modelrun._record(model, ap.SEED, n, run_id=run_id) for n in range(1, world_lives() + 1)]
    first = modelrun._load(model, ap.SEED, 1, run_id=run_id) or {}
    locked = list(first.get("letters_from") or [])
    if carry == "layered":
        if letters_from and list(letters_from) != locked:
            raise SystemExit("letters_from differs from the letter this world was played with")
        letters_from = locked
    sources += [modelrun._letter_path(model, ap.SEED, name) for name in letters_from]
    metadata = dict(operation="letter", run_id=run_id, carry=carry, proto=ap.settings(), api=modelrun.api_settings(model),
                    inputs=checkpoint.file_evidence(sources), text=pt.MODE, text_version=pt.VERSION,
                    budget_key=os.environ.get("AGII_BUDGET_KEY") or f"{modelrun._slug(model)}_{run_id}",
                    engine=modelrun.ENGINE_VERSION, protocol=modelrun.PROTOCOL_VERSION)
    with checkpoint.operation(model, path, metadata, resume=resume) as state:
        if path.exists():
            result = json.loads(path.read_text())
            if result.get("carry") != carry or result.get("lives") != world_lives():
                raise RuntimeError("Completed letter belongs to another memory configuration")
            if result.get("api") != modelrun.api_settings(model):
                raise RuntimeError("Completed letter's API settings differ from this run")
            state["completed"] = True
            return result
        return _write_letter(model, run_id, carry, key, letters_from, verbose)


def _write_letter(model, run_id, carry, key=None, letters_from=(), verbose=True):
    """世界末的信：modelrun.write_letter（读第 1–5 条命的记录、LETTER_QUESTION、存 <run_id>_letter.json）。没有营地的世界里，
    写信的材料（handover_evidence("both", …)）不放营地那段。key 给定时不读钥匙（假模型）。"""
    if key is None:
        from study_models import require_active
        require_active(model)
    if pt.minimal():                                        # PROTO_TEXT=minimal：B6 / B7 / B8 / B9 / B10，命数 = world_lives()（v3b 下 4）
        return pt.write_letter(model, ap.SEED, run_id, carry, lives=world_lives(), key=key if key is not None else modelrun._api_key(model),
                               letters_from=letters_from, verbose=verbose)
    first = modelrun._load(model, ap.SEED, 1, run_id=run_id)
    camp = bool(first and first.get("camp_log"))
    saved = (modelrun.handover_evidence, modelrun._api_key)
    modelrun.handover_evidence = functools.partial(handover_evidence, camp=camp)
    if key is not None:
        modelrun._api_key = lambda model="": key
    try:
        return modelrun.write_letter(model, ap.SEED, run_id, carry, lives=N_LIVES, letters_from=letters_from, verbose=verbose)
    finally:
        modelrun.handover_evidence, modelrun._api_key = saved


# ---------------------------------------------------------------- 假模型（核对用，进程内）
@contextlib.contextmanager
def fake_model(respond):
    """respond(system, user) -> 回复文字。换掉 modelrun.call（act / pick / 笔记 / 信 都经它，是唯一的 HTTP 出口）；
    modelrun._api_key 换成报错（不读 ~/.config/agii/*.key）；urllib.request.urlopen 换成报错（漏网的请求也发不出去）。"""
    import urllib.request
    saved = (modelrun.call, modelrun._api_key, urllib.request.urlopen)

    def call(model, system, user, key, blocks=None):
        if blocks is not None:
            assert "".join(t for t, _ in blocks) == user
        return respond(system, user)

    def no_key(model=""):
        raise RuntimeError("fake_model：不读钥匙")

    def no_http(*a, **k):
        raise RuntimeError("fake_model：不发 HTTP 请求")
    modelrun.call, modelrun._api_key, urllib.request.urlopen = call, no_key, no_http
    try:
        yield "fake-model-key"
    finally:
        modelrun.call, modelrun._api_key, urllib.request.urlopen = saved


def _turn_and_hand(text):
    """提示 / 画面文字里最后一屏的回合号和手牌名（只读参与者看得到的文字）。"""
    turns = re.findall(r"^Turn (\d+)", text, re.M)
    hand = text.rsplit("In hand:", 1)[1].split("\n", 1)[0] if "In hand:" in text else ""
    return (int(turns[-1]) if turns else None), re.findall(r"(\S+?)\((?:\d+|\?)\)", hand)


class AttackOnly:
    """假模型的出牌：每回合最多出两张 `card` 这个名字的牌（手里有才出），然后 END；地图选择回 1（原型里不该被问到）；笔记回一句固定的话。
    只读提示文字，不读引擎。calls 记下每次调用（kind、system 前缀、提示全文）给核对用。"""

    def __init__(self, card, per_turn=2):
        self.card, self.per_turn = card, per_turn
        self.calls, self._turn, self._n = [], None, 0

    def kind(self, system):
        return ("act" if system in (modelrun.ADV_SYSTEM, modelrun.CAMP_SYSTEM) else "pick" if system == modelrun.CHOICE_SYSTEM else "note")

    def __call__(self, system, user):
        k = self.kind(system)
        self.calls.append(dict(kind=k, camp=system == modelrun.CAMP_SYSTEM, system=system, user=user))
        if k == "pick":
            return "1"
        if k == "note":
            return "fake note"
        return self.move(user)

    def move(self, text):
        turn, hand = _turn_and_hand(text)
        if turn != self._turn:
            self._turn, self._n = turn, 0
        if self._n < self.per_turn and self.card in hand:
            self._n += 1
            return self.card
        return "END"


# ---------------------------------------------------------------- 人类：命令行
def reveal(spec, deck, show_map_metadata=True):
    title = "True settings" if show_map_metadata else "Card effects"
    print(f"\n{'=' * 58}\n{title} (revealed only after the last life):")
    for n, c in deck.items():
        print(f"  {n:<7} {c}")
    if show_map_metadata:
        for k, m in enumerate(spec["maps"], 1):
            print(f"  map {k} ({m['salt']}): " + ", ".join(m["fights"]))
        print(f"  boss   {' -> '.join(spec['boss']['order'])} ({spec['boss']['salt']})")
    if ap.MARKMAP == "world":                     # v1.3：world（候选；命令行入口在采用之前拒绝它，D12）下这个世界的代号表
        name = {c.kind: n for n, c in deck.items()}
        print("  mark codes: " + ", ".join(f"{i} = {name.get(k, k)}" for i, k in enumerate(pw.world_mark_table(spec), 1)))


def human_main(argv=None, *, show_map_metadata=True, worlds=None):
    """命令行人类入口（同 humanrun.main 的换法：modelrun.act / pick / call 换成 humanrun 的键盘函数，_api_key 回 "human"）。
    图形界面的 worker 也走这里（gui_bridge 已把 humanrun.human_* 换成桥，这里读的是当时的绑定）。退出时还原。"""
    from world_pack_runtime import CHAIN_ENV, chain_index
    p = argparse.ArgumentParser(prog="proto_play.py human")
    p.add_argument("--name", required=True)
    p.add_argument("--world", "--pack", dest="world", default=None, help="world id (p13-…); --pack is the GUI's name for it")
    p.add_argument("--worlds", default=os.environ.get("PROTO_WORLDS"), help="world file (proto_world.save_worlds)")
    p.add_argument("--lives", default=None)
    p.add_argument("--carry", default="notes", choices=CARRIES)
    p.add_argument("--auto", action="store_true")
    p.add_argument("--reveal", action="store_true")
    p.add_argument("--replay", action="store_true", help="play again a life that already has a result (the same deal; recorded as a replay)")
    p.add_argument("--export", action="store_true")
    p.add_argument("--world-index", type=int, default=None, help="PROTO_TEXT=minimal: which world of this person's sequence (default 1)")
    p.add_argument("--chain", type=chain_index, default=chain_index(), help="replicate chain number; all bosses announce the phase change (default 1)")
    a = p.parse_args(argv)
    os.environ[CHAIN_ENV] = str(a.chain)
    if a.export:
        return humanrun.main(["--name", a.name, "--export"])
    setup()
    v3b = bool(_HUMAN_V3B.get("on"))                        # PROTO_HUMAN_V3B=1（human_v3b_setup 之后）；不设时下面三处 v3b 分支都不跑
    specs = worlds if worlds is not None else (_human_v3b_load(a.worlds) if v3b else pw.load_worlds(a.worlds))
    if v3b:
        wid, w3 = _human_v3b_pick(specs, a.world, a.world_index)
    else:
        wid = a.world or next(iter(specs))
    if wid not in specs:
        raise SystemExit(f"World {wid} is not in the world file.")
    spec = specs[wid]
    if v3b:
        if _HUMAN_ENTRIES[_HUMAN_V3B.get("variant", "v3b")].get("boss"):   # v3c1b 入口（40 号文档）：这个世界自己的血 / 伤害；不对就开打之前英文拒绝
            _human_v3c1b_world(spec, w3)                    # v7（43 号文档）：先于 verify —— 别的世界的外衣在本进程 verify 不过，先告诉人该用哪条命令
        _human_v3b_verify(spec)
        wf =pathlib.Path(a.worlds).expanduser().resolve() if a.worlds else None
        _HUMAN_V3B["entry"] = dict(worlds_file=str(wf) if wf else None,
                                   worlds_sha256=__import__("hashlib").sha256(wf.read_bytes()).hexdigest() if wf else None,
                                   world_id=wid, world_position=w3)
        if _HUMAN_V3B.get("variant") == "v3c1b":
            a.carry = "layered"                             # 11-10：v7 人类入口与模型同一记忆方式（46 号文档分层记忆）；图形界面传来的 notes 不用
            _HUMAN_V3B["entry"].update(chain_index=a.chain, cue_policy="always_on", boss_cue=spec["boss"]["env"]["PROTO_BOSS_CUE"])
            previous = modelrun._load(f"human-{a.name}", ap.SEED, 1, run_id=f"human-{a.name}-{wid}")
            old_chain = ((previous or {}).get("human_entry") or {}).get("chain_index", 1)
            if previous and old_chain != a.chain:
                raise SystemExit(f"This name already has chain {old_chain} in this world. Use another --name for chain {a.chain}.")
    lo, hi = _lives(a.lives or f"1-{world_lives()}")
    if v3b and hi > world_lives():
        raise SystemExit(f"A world here has lives 1-{world_lives()} (maps only); there is no life {hi}.")
    humanrun.AUTO["on"] = a.auto
    notes_ctx = pt.human_notes()                            # minimal：笔记提示里的对手那一句（默认下什么也不做）；先换，下面才读 humanrun.human_call
    notes_ctx.__enter__()
    saved = (modelrun._api_key, modelrun.act, modelrun.pick, modelrun.call)
    modelrun._api_key = lambda model="": "human"
    modelrun.act, modelrun.pick, modelrun.call = humanrun.human_act, humanrun.human_pick, humanrun.human_call
    last = None
    letters_from = ()
    try:
        if v3b and a.carry == "layered" and w3 >= 2:       # 11-10：世界 2 起带上一世界的信（同模型链：只带上一世界的那一封）；信还没写就先写
            prev_wid = list(specs)[w3 - 2]
            _human_letter(a.name, prev_wid, w3 - 1)
            letters_from = (f"human-{a.name}-{prev_wid}",)
        for life in range(lo, hi + 1):
            humanrun._shown.clear(); humanrun._seen_hist[0] = 0; humanrun._fight[0] = None
            salt = spec["maps"][life - 1]["salt"] if life <= N_MAPS else spec["boss"]["salt"]
            label = (f", map {salt}" if life <= N_MAPS else f", boss {salt}") if show_map_metadata else ""
            if (pt.minimal() and life == 1 and not letters_from
                    and pc.pending(f"human-{a.name}", ap.SEED, f"human-{a.name}-{wid}", w3 if v3b else a.world_index or 1)):
                pc.banner(pt.CAMP_HEADER.format(w=w3 if v3b else a.world_index or 1))      # 训练营先打：横幅 "World w, Camp"（营地完了再印第 1 条命的）
            elif pt.minimal():                              # v2：横幅同模型的抬头 "World w, Life k"（不印世界 id、图）
                print(f"\n{'#' * 58}\n{pt.life_header(w3 if v3b else a.world_index or 1, life)}\n{'#' * 58}")
            else:
                print(f"\n{'#' * 58}\nLife {life}  (universe {wid}{label})\n{'#' * 58}")
            last = play_life(f"human-{a.name}", spec, life, "human", run_id=f"human-{a.name}-{wid}", carry=a.carry, want_notes=True,
                             fight_notes="write", who="human", verbose=False, overwrite=a.replay or _READY["gui_worker"],
                             **({"letters_from": letters_from} if letters_from else {}),
                             **({"world_index": w3 if v3b else a.world_index or 1} if pt.minimal() else {}))
            if pt.minimal():
                print("\n" + pt.result_line(last["result"]))        # A2：不带血量
            else:
                print(f"\nResult: {last['result']}   Health left {last['hp']}")
        if v3b and a.carry == "layered" and last is not None and hi == world_lives():
            _human_letter(a.name, wid, w3)                  # 同模型链：第 5 条命之后马上写这个世界的信
        if a.reveal and last is not None and not v3b:       # PROTO_HUMAN_V3B=1：不揭示（boss 没做；一个人要连着玩几个世界）
            if hi == N_LIVES and _all_lives_complete(f"human-{a.name}", f"human-{a.name}-{wid}"):
                reveal(spec, last["run"].deck, show_map_metadata)
            else:
                print(f"\n(The true settings are shown only after all {N_LIVES} lives are complete.)")
    finally:
        modelrun._api_key, modelrun.act, modelrun.pick, modelrun.call = saved
        notes_ctx.__exit__(None, None, None)
    return last


def _human_letter(name, wid, w):
    """人类世界末的信（11-10）：与模型链同一个 pt.write_letter（同材料：带进来的信 + 营地笔记（世界 1）+ 本世界每条命的笔记
    + 对应表（世界 2 起）+ 同一句 LETTER_QUESTION，同上限）。人看到模型收到的整段材料（human_call 不只印最后一段）。
    已经写过就直接用；这个世界还有命没打完就拒绝（英文）。"""
    model, run_id = f"human-{name}", f"human-{name}-{wid}"
    path = modelrun._letter_path(model, ap.SEED, run_id)
    if path.exists():
        return json.loads(path.read_text())
    recs = [modelrun._load(model, ap.SEED, n, run_id=run_id) for n in range(1, world_lives() + 1)]
    if not all(r and r.get("adv_log") is not None and r.get("result") and r["result"] != "camp only" for r in recs):
        raise SystemExit(f"World {w} is not finished under the name {name!r}; finish it before the next world.")
    humanrun._shown.clear(); humanrun._seen_hist[0] = 0; humanrun._fight[0] = None
    pc.banner(pt.LETTER_HEADER.format(w=w))
    pt.HUMAN_FULL[0] = True
    try:
        return pt.write_letter(model, ap.SEED, run_id, "layered", lives=world_lives(), key="human", verbose=False, human=True)
    finally:
        pt.HUMAN_FULL[0] = False


def _wn_block(f):
    """这一场的工作便签全部版本（写笔记时附上）；off 或没写过 → ""。"""
    import work_note
    return work_note.block(work_note.versions_of(f)) if work_note.on() else ""


def _all_lives_complete(model, run_id):
    """第 1–5 条命都有结果（同 humangui.validate_start 的 prior_complete：有 result 且不是 "camp only"）。"""
    recs = [modelrun._load(model, ap.SEED, n, run_id=run_id) for n in range(1, N_LIVES + 1)]
    return all(r and r.get("result") and r["result"] != "camp only" for r in recs)


# ---------------------------------------------------------------- 人类：图形界面
class _SubprocessShim:
    """humangui 的模块全局 subprocess 的替身：Popen 只改写 worker 命令（[python, -u, …/core/humangui.py, --worker, *args] →
    [python, -u, 本文件, gui-worker, *args]），其余参数（管道、cwd、env、编码）原样；别的属性转给真的 subprocess 模块。"""

    def __init__(self, real, humangui_file, popen=None):
        self._real, self._file, self._popen = real, str(humangui_file), popen or real.Popen

    def rewrite(self, cmd):
        cmd = list(cmd)
        if len(cmd) >= 4 and cmd[2] == self._file and cmd[3] == "--worker":
            return [cmd[0], cmd[1], str(pathlib.Path(__file__).resolve()), "gui-worker", *cmd[4:]]
        raise RuntimeError(f"humangui 的子进程命令和预期不同，不改写也不启动：{cmd}")

    def Popen(self, cmd, *a, **kw):
        return self._popen(self.rewrite(cmd), *a, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


def install_gui(specs, worlds_path, popen=None):
    """在本进程里把 core/humangui.py 指向原型世界：all_packs / default_pack（模块全局函数，validate_start、snapshot、备份、导出都按名字查）
    换成原型世界（每个世界 5 条命：4 张图 + boss），subprocess 换成 _SubprocessShim；PROTO_WORLDS 写进环境（worker 继承 os.environ 的拷贝）。
    返回 undo()。core/humangui.py 一字不改。"""
    import humangui
    saved = (humangui.all_packs, humangui.default_pack, humangui.subprocess, os.environ.get("PROTO_WORLDS"))
    packs = {wid: tuple(m["salt"] for m in s["maps"]) + (s["boss"]["salt"],) for wid, s in specs.items()}
    if world_lives() == N_MAPS:                            # minimal + v3b：一个世界只有 4 张图（boss 先不做）
        packs = {wid: p[:N_MAPS] for wid, p in packs.items()}
    humangui.all_packs = lambda: dict(packs)
    humangui.default_pack = lambda: next(iter(packs))
    humangui.subprocess = _SubprocessShim(saved[2], pathlib.Path(humangui.__file__).resolve().parent / "humangui.py", popen)
    os.environ["PROTO_WORLDS"] = str(pathlib.Path(worlds_path).resolve())

    def undo():
        humangui.all_packs, humangui.default_pack, humangui.subprocess = saved[:3]
        if saved[3] is None:
            os.environ.pop("PROTO_WORLDS", None)
        else:
            os.environ["PROTO_WORLDS"] = saved[3]
    return undo


def gui_main(argv=None):
    """python3 scripts/proto_play.py gui --worlds W.json [--port …] [--name …] [--pack <world id>] …（其余参数原样交给 humangui）。"""
    p = argparse.ArgumentParser(prog="proto_play.py gui")
    from world_pack_runtime import CHAIN_ENV, chain_index
    p.add_argument("--worlds", required=True)
    p.add_argument("--chain", type=chain_index, default=chain_index())
    a, rest = p.parse_known_args(argv)
    os.environ[CHAIN_ENV] = str(a.chain)
    import humangui
    if _HUMAN_V3B.get("on"):                                # PROTO_HUMAN_V3B=1：英文报错；开页面之前核每个世界
        specs = _human_v3b_load(a.worlds)
        if _HUMAN_ENTRIES[_HUMAN_V3B.get("variant", "v3b")].get("boss"):   # v3c1b 入口：只列这个进程的血 / 伤害能打的世界（一个进程一套 boss 环境）
            specs = _human_v3c1b_gui_worlds(specs)          # v7（43 号文档）：先筛再 verify —— 别的世界的外衣在本进程 verify 不过
        for s in specs.values():
            _human_v3b_verify(s)
    else:
        specs = pw.load_worlds(a.worlds)
    install_gui(specs, a.worlds)
    sys.argv = [str(pathlib.Path(humangui.__file__).resolve()), *rest]
    return humangui.main()


def gui_worker(argv):
    """图形界面的子进程：gui_bridge.run_worker 原样（桥、事件、错误处理），只把它调的 humanrun.main 换成 human_main。"""
    import gui_bridge
    setup()
    saved = humanrun.main
    humanrun.main = human_main
    _READY["gui_worker"] = True                              # humangui 自己管重打（要勾 Replay、先备份）：这里放行，记录照样写 attempt
    try:
        with pt.human_notes():                               # minimal：先换笔记提示，桥再把它包起来（默认下什么也不做）
            return gui_bridge.run_worker(argv)
    finally:
        humanrun.main = saved
        _READY["gui_worker"] = False


# ---------------------------------------------------------------- 冒烟（单进程，几条命，不算通过率）
class _Keys:
    """命令行人类入口的脚本键盘（代替 humanrun 的 input）：读已经印出来的文字，策略同 AttackOnly；写笔记时回空行。"""

    def __init__(self, buf, card):
        self.buf, self.pos, self.p = buf, 0, AttackOnly(card)

    def __call__(self, prompt=""):
        text = self.buf.getvalue()
        new, self.pos = text[self.pos:], len(text)
        if ("[Write your notes]" if not pt.minimal() else pt.NOTE_SYSTEM) in new.rsplit("In hand:", 1)[-1]:
            return ""
        return self.p.move(new).lower() if "In hand:" in new else "end"


class _Wire(io.StringIO):
    """gui_bridge.run_worker 的 stdout（事件流）。"""

    def events(self):
        return [json.loads(x) for x in self.getvalue().splitlines() if x.strip()]


class _GuiStdin:
    """gui_bridge.run_worker 的 stdin：按最后一个 prompt 事件回答（act：AttackOnly 的走法，只读事件里的画面和选项；note：空；pick：1）。"""

    def __init__(self, wire, card):
        self.wire, self.p = wire, AttackOnly(card)

    def readline(self):
        ev = [e for e in self.wire.events() if e.get("type") == "prompt"][-1]
        if ev["kind"] == "note":
            v = ""
        elif ev["kind"] == "pick":
            v = "1"
        else:
            hand = "In hand: " + "  ".join(c["label"] for c in ev["choices"] if c["group"] == "hand")
            v = self.p.move(ev.get("screen", "") + "\n" + hand).lower()
        return json.dumps({"value": v}) + "\n"


def _choice_free(texts):
    return not any(t in x for x in texts for t in CHOICE_TEXTS) and not any(re.search(r"Layer \d+\. ", x) for x in texts)


def smoke(runs_dir, out=None):
    import gates, devworld, solver, urllib.request
    t0 = time.time()
    setup()
    runs_dir = pathlib.Path(runs_dir).resolve(); runs_dir.mkdir(parents=True, exist_ok=True)
    rep = dict(study="proto-play-smoke", version=VERSION, date="2026-11-03", proto=ap.settings(), world_rules=pw.RULES_VERSION,
               note="in-process smoke with a fake model / scripted keyboard; no API, no key read, no pass rates", checks={},
               files={rel: __import__("hashlib").sha256((ROOT / rel).read_bytes()).hexdigest()[:16] for rel in
                      ("scripts/proto_play.py", "scripts/proto_world.py", "scripts/antagonist_boss.py", "scripts/antagonist_proto.py",
                       "scripts/r1v2.py", "core/modelrun.py", "core/humanrun.py", "core/humangui.py", "core/gui_bridge.py")})
    ok_all = [True]

    def verdict(name, ok, **detail):
        ok_all[0] &= bool(ok)
        rep["checks"][name] = dict(status="PASS" if ok else "FAIL", **_jsonable(detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(_jsonable(detail), ensure_ascii=False)[:600]}", flush=True)

    saved_runs, saved_open = modelrun.RUNS_DIR, urllib.request.urlopen
    modelrun.RUNS_DIR = runs_dir

    def no_http(*a, **k):
        raise RuntimeError("smoke：不发 HTTP 请求")
    urllib.request.urlopen = no_http
    try:
        attack = ap.build(ap.SALT0).by_kind["attack"]
        # S1 世界：选择器、检查器、确定性、反例
        cands = pw.two_round_salts(30)
        w1 = pw.select_world(cands, ("pierce", "momentum"), ap.SALT0)
        w1b = pw.select_world(cands, ("pierce", "momentum"), ap.SALT0)
        w2 = pw.select_world(cands, ("pierce", "ward"), ap.SALT0 + 1)
        bad_cover = next(([a, b, c] for a, b, c in __import__("itertools").combinations(cands[:12], 3)
                          if set().union(*(pw.map_info(s)["drawn"] for s in (a, b, c))) != set(ap.PROTO)), None)
        rejected, w1_salts = [], [m["salt"] for m in w1["maps"]]
        for args in (([*bad_cover, cands[-1]], ("guard", "ward"), ap.SALT0),          # W1：图 1–3 不覆盖六种
                     (w1_salts, ("guard", "poison"), ap.SALT0),                         # W2：boss 机制不在池里 / 不在图 1–3
                     (w1_salts, ("guard", "ward"), w1_salts[0])):                       # W0：boss salt 与图相同
            try:
                pw.make_world(*args); rejected.append(False)
            except ValueError:
                rejected.append(True)
        worlds_file = pw.save_worlds(runs_dir / "worlds_smoke.json", [w1, w2], overwrite=True)
        specs = pw.load_worlds(worlds_file)
        verdict("S1_world_rules", w1 == w1b and all(v["ok"] for w in (w1, w2) for v in w["checks"].values()) and all(rejected)
                and all(w["id"].startswith("p13-") for w in (w1, w2)) and list(specs) == [w1["id"], w2["id"]],
                w1=dict(id=w1["id"], maps=[(m["salt"], m["drawn"]) for m in w1["maps"]], boss=w1["boss"], picked=w1["selection"]["picked_index"]),
                w2=dict(id=w2["id"], maps=[m["salt"] for m in w2["maps"]], boss=w2["boss"]), rejected_bad_worlds=rejected)

        # S2 模型入口（假模型），notes 臂，第 1–5 条命
        fake = AttackOnly(attack)
        starts, res = [], []
        with fake_model(fake) as key:
            for life in range(1, N_LIVES + 1):
                starts.append(len(fake.calls))
                res += play_world("fake-model", w1, lives=(life, life), run_id=f"p13-smoke-notes", key=key, carry="notes",
                                  verbose=False, overwrite=True)
        starts.append(len(fake.calls))
        texts = [c["user"] for c in fake.calls]
        logs = [h for r in res for h in r["adv_log"]]
        node0 = all(fr["node"] == 0 and fr["enemy"] == ap.build(r["salt"]).layers[fr["layer"] - 1].nodes[0].enemy.name
                    for r in res[:N_MAPS] for fr in r["fights"])
        recs = [json.loads(r["record"].read_text()) for r in res]
        first_act = {r["life"]: next((c["user"] for c in fake.calls[starts[k]:starts[k + 1]] if c["kind"] == "act"), "") for k, r in enumerate(res)}
        result_of = {r["life"]: r["result"] for r in res}
        act_systems = {c["system"] for c in fake.calls if c["kind"] == "act"}
        mem = all(first_act[k].startswith(retry_head(result_of[k - 1], k)) and f"What you concluded after life {k - 1}" in first_act[k]
                  and "In the room without doors" not in first_act[k] and "What you concluded there" not in first_act[k] for k in range(2, N_LIVES + 1))
        mem = mem and act_systems == {ADV_SYSTEM_NO_CAMP} and modelrun.ADV_SYSTEM is ADV_SYSTEM_REGISTERED
        verdict("S2_model_entry_no_choices", not any(c["kind"] == "pick" for c in fake.calls) and _choice_free(texts)
                and not any(re.search(r"\] won, (took|chose) ", h) for h in logs) and node0
                and all(r["record"].name.split(f"_{modelrun.ENGINE_VERSION}_")[1].startswith("p13-") for r in res),
                lives=[(r["life"], r["kind"], r["salt"], r["result"], len(r["fights"]), len(r["auto_rests"])) for r in res],
                calls=dict(act=sum(c["kind"] == "act" for c in fake.calls), pick=sum(c["kind"] == "pick" for c in fake.calls),
                           note=sum(c["kind"] == "note" for c in fake.calls)),
                resupply_lines=sum("automatic resupply" in h for h in logs), records=[r["record"].name for r in res])
        # S2b 整张图打通的路径（for … else、最后一层的补给）：测试用的假模型偷看真对局（solver.act 的 oracle 走法；只在核对里，参与者入口不变）
        cur, orig_rf = {}, modelrun.run_fight

        @functools.wraps(orig_rf)                           # __wrapped__：antagonist_boss._quiet_model_log 照样认得 run_fight 的帧
        def run_fight_peek(model, key, system, fight, *a, **k):
            cur["f"] = fight
            return orig_rf(model, key, system, fight, *a, **k)

        def oracle_respond(system, user):
            if system != modelrun.ADV_SYSTEM:
                return "fake note"
            f = cur["f"]
            c = solver.act(f, solver.ALL, {card.kind: n for n, card in f.deck.items()}, information="oracle")
            return c or "END"
        modelrun.run_fight = run_fight_peek
        try:
            with fake_model(oracle_respond) as key:
                reso = play_world("fake-model", w1, lives=(1, N_LIVES), run_id="p13-smoke-peek", key=key, carry="none", want_notes=False,
                                  fight_notes="none", verbose=False, overwrite=True)
        finally:
            modelrun.run_fight = orig_rf
        clr = [r for r in reso[:N_MAPS] if r["result"] == "cleared"]
        verdict("S2b_full_map_clear_path", bool(clr) and all(len(r["fights"]) == 8 and len(r["auto_rests"]) == 4
                                                             and r["adv_log"][-1].startswith("[layer 12] automatic resupply") for r in clr)
                and all(r["result"] in ("cleared",) or r["result"].startswith("died at ") for r in reso),
                results=[r["result"] for r in reso], last_line_cleared=[r["adv_log"][-1] for r in clr][:2])
        verdict("S3_records_and_display", all(d["proto"] == ap.settings() and d["display"] == ap.display_settings("model")
                                              and d["display_tuning"] == dict(marks=0, state_slots="seen") and d["proto_world"] == w1["id"]
                                              and d["proto_camp"] is False and d["rest_rule"] == "auto_rest" for d in recs),
                display=recs[0]["display"], display_tuning=recs[0]["display_tuning"], proto=recs[0]["proto"])
        verdict("S4_memory_notes_arm_no_camp", mem, life2_head=first_act[2][:300], results=result_of,
                retry_lines={k: retry_line(first_act[k]) for k in range(2, N_LIVES + 1)}, act_system_no_camp=act_systems == {ADV_SYSTEM_NO_CAMP})
        b = res[-1]; br = b["boss"]
        sw = br["switched"]
        cue_prompt = next((k for k, c in enumerate(fake.calls[starts[4]:starts[5]]) if c["kind"] == "act" and ab.CUE_TEXT in c["user"]), None)
        cue_turn = _turn_and_hand(fake.calls[starts[4] + cue_prompt]["user"])[0] if cue_prompt is not None else None
        verdict("S5_boss_life", b["kind"] == "boss" and br["entry"] == dict(hp=203, max_hp=203, deck=18, base_atk=7)
                and br["phase_order"] == ["pierce", "momentum"] and recs[-1]["salt"] == w1["boss"]["salt"]
                and (not sw or (br["cue_lines"] == 1 and br["cue_late"] == [False] and (cue_turn is None and b["result"] != "cleared"
                                                                                       or cue_turn == br["switch_turn"] + 1))),
                switched=sw, switch_turn=br["switch_turn"], cue_lines=br["cue_lines"], cue_after=br["cue_after"],
                first_prompt_with_cue_turn=cue_turn, result=b["result"], entry=br["entry"], phase_order=br["phase_order"])

        # S6 log 臂 + 换阶段日志静音（世界 2：pierce → ward，进场封印的初始化不进日志）
        fake2 = AttackOnly(attack)
        starts2, res2 = [], []
        with fake_model(fake2) as key:
            for life in range(1, N_LIVES + 1):
                starts2.append(len(fake2.calls))
                res2 += play_world("fake-model", w2, lives=(life, life), run_id="p13-smoke-log", key=key, carry="log", want_notes=False,
                                   fight_notes="none", verbose=False, overwrite=True)
        a2 = next(c["user"] for c in fake2.calls[starts2[1]:] if c["kind"] == "act")
        b2 = res2[-1]; br2 = b2["boss"]
        quiet = (br2["d1"]["handover"] or {}).get("quiet", [])
        k = b2["adv_log"].index(ab.CUE_TEXT) if br2["switched"] and ab.CUE_TEXT in b2["adv_log"] else None
        sw_line = b2["adv_log"][k - 1] if k else ""
        lay = b2["run"].layout
        quiet_ok = all(f"{lay.L('them', p)}: " not in sw_line for p in quiet)
        verdict("S6_log_arm_and_quiet_handover", modelrun.RETRY_LOG_HEAD in a2 and f"Life 1 ({res2[0]['result']}):" in a2 and ", outside (" not in a2
                and "In the room without doors" not in a2
                and not any(c["kind"] == "note" for c in fake2.calls) and (not br2["switched"] or (quiet == ["ward"] and bool(br2["d1"]["log_quieted"]) and quiet_ok)),
                switched=br2["switched"], quiet=quiet, log_quieted=br2["d1"]["log_quieted"], switch_line=sw_line, result=b2["result"])

        # S7 营地开（PROTO_CAMP=1，待用户定）：第 1 条命打营地，第 2 条命的交接与 modelrun 逐字相同
        saved_camp = ap.CAMP
        ap.CAMP = True
        try:
            fake3 = AttackOnly(attack)
            with fake_model(fake3) as key:
                r1 = play_world("fake-model", w1, lives=(1, 1), run_id="p13-smoke-camp", key=key, carry="both", verbose=False, overwrite=True)[0]
                n0 = len(fake3.calls)
                r2 = play_world("fake-model", w1, lives=(2, 2), run_id="p13-smoke-camp", key=key, carry="both", verbose=False, overwrite=True)[0]
            d1 = json.loads(r1["record"].read_text())
            earlier = [(1, d1)]
            verbatim = modelrun.build_handover(2, "both", "\n".join(f"  {i}. {h}" for i, h in enumerate(d1["camp_log"], 1)), d1["notes"],
                                               [(1, d1["adv_log"], d1["result"])], earlier, ())
            expect = retry_head(d1["result"], 2) + verbatim[len(modelrun.RETRY_HEAD):]     # 除 RETRY_HEAD 第一行外是 modelrun 的原文
            a3 = next(c["user"] for c in fake3.calls[n0:] if c["kind"] == "act")
            adv3 = {c["system"] for c in fake3.calls if c["kind"] == "act" and not c["camp"]}
            verdict("S7_camp_switch_on", any(c["camp"] for c in fake3.calls) and bool(r1["camp_log"]) and d1["proto_camp"] is True
                    and d1["proto"]["camp"] is True and verbatim.startswith(modelrun.RETRY_HEAD) and r2["handover"] == expect
                    and a3.startswith(expect) and "In the room without doors" in a3 and adv3 == {modelrun.ADV_SYSTEM} == {ADV_SYSTEM_REGISTERED},
                    camp_steps=len(r1["camp_log"]), camp_used=r1["camp_used"], life1=d1["result"], retry_line=retry_line(r2["handover"]),
                    same_as_modelrun=r2["handover"] == verbatim)
        finally:
            ap.CAMP = saved_camp

        # S8 世界末的信（modelrun.write_letter；没有营地时材料里没有营地那段）
        fake4 = AttackOnly(attack)
        with fake_model(fake4) as key:
            letter = write_letter("fake-model", "p13-smoke-notes", "notes", key=key, verbose=False)
        mat = fake4.calls[-1]["user"]
        verdict("S8_letter", letter["letter"] == "fake note" and "In the room without doors" not in mat and f"Life 5 ({res[-1]['result']}):" in mat
                and ", outside (" not in mat and modelrun.LETTER_QUESTION in mat, material_chars=len(mat))

        # S9 命令行人类入口（脚本键盘；humanrun 的 human_act / human_call 原样）
        buf = io.StringIO()
        keys = _Keys(buf, attack)
        humanrun.input = keys
        try:
            with contextlib.redirect_stdout(buf):
                last = human_main(["--name", "smoke-cli", "--world", w1["id"], "--lives", "1-5", "--reveal", "--replay"], worlds=specs)
        finally:
            del humanrun.input
        text = buf.getvalue()
        hb = last["boss"]
        cue_at = text.find("   " + ab.CUE_TEXT)
        before_turn = re.findall(r"^Turn (\d+)", text[:cue_at], re.M)[-1:] if cue_at >= 0 else []
        after_turn = re.findall(r"^Turn (\d+)", text[cue_at:], re.M)[:1] if cue_at >= 0 else []
        hrecs = [json.loads(modelrun._record("human-smoke-cli", ap.SEED, n, run_id=f"human-smoke-cli-{w1['id']}").read_text()) for n in range(1, 6)]
        verdict("S9_human_cli", _choice_free([text]) and f"Life 5  (universe {w1['id']}, boss " in text and "automatic resupply" in text
                and (not hb["switched"] or (cue_at >= 0 and before_turn == [str(hb["switch_turn"])]
                                            and (after_turn == [str(hb["switch_turn"] + 1)] or last["result"] != "cleared" and not after_turn)))
                and all(d["who"] == "human" and d["display"] == ap.display_settings("human") for d in hrecs) and "True settings" in text
                and ADV_SYSTEM_NO_CAMP in text and "The wall has opened" not in text and ", outside (" not in text,
                switched=hb["switched"], switch_turn=hb["switch_turn"], turn_before_cue=before_turn, turn_after_cue=after_turn,
                results=[d["result"] for d in hrecs], printed_chars=len(text),
                retry_lines=[d["participant_text"]["retry_line"] for d in hrecs])

        # S10 图形界面 worker（进程内：gui_bridge.run_worker 原样，stdin / stdout 换成脚本）
        wire = _Wire()
        old_in, os.environ["PROTO_WORLDS"] = sys.stdin, str(worlds_file)
        sys.stdin = _GuiStdin(wire, attack)
        try:
            with contextlib.redirect_stdout(wire):
                code = gui_worker(["--name", "smoke-gui", "--pack", w1["id"], "--lives", "1-5", "--carry", "notes", "--reveal"])
        finally:
            sys.stdin = old_in
            os.environ.pop("PROTO_WORLDS", None)
        evs = wire.events()
        g5 = json.loads(modelrun._record("human-smoke-gui", ap.SEED, 5, run_id=f"human-smoke-gui-{w1['id']}").read_text())
        prompts = [e for e in evs if e.get("type") == "prompt"]
        cue_ev = [e for e in prompts if ab.CUE_TEXT in e.get("text", "")]
        cue_scr = _turn_and_hand(cue_ev[0].get("screen", ""))[0] if cue_ev else None
        alltext = "\n".join(e.get("text", "") for e in evs)
        verdict("S10_gui_worker", code == 0 and evs[-1]["type"] == "done" and not any(e.get("kind") == "pick" for e in prompts)
                and _choice_free([alltext]) and ", map " not in alltext and ", boss " not in alltext and "Life 5  (universe " in alltext
                and ADV_SYSTEM_NO_CAMP in alltext and "The wall has opened" not in alltext
                and (not g5["boss"]["switched"] or (len(cue_ev) >= 1 and cue_scr == g5["boss"]["switch_turn"] + 1)
                     or (g5["boss"]["cue_lines"] == 1 and g5["result"] != "cleared" and not cue_ev)),
                exit=code, events=len(evs), prompts=len(prompts), switched=g5["boss"]["switched"], cue_prompt_screen_turn=cue_scr,
                result=g5["result"])

        # S11 图形界面服务端：humangui 原样，只换 all_packs / default_pack / subprocess（垫片改写 worker 命令）
        import humangui
        launched = []

        class _Proc:
            stdout, stderr, stdin = iter(()), iter(()), io.StringIO()

            def wait(self, timeout=None): return 0
            def poll(self): return 0
            def terminate(self): pass

        def fake_popen(cmd, *a, **kw):
            launched.append(dict(cmd=cmd, env_worlds=kw.get("env", {}).get("PROTO_WORLDS"), cwd=kw.get("cwd")))
            return _Proc()
        undo = install_gui(specs, worlds_file, popen=fake_popen)
        try:
            packs = humangui.all_packs()
            name, pack, args = humangui.validate_start(dict(name="smoke-srv", pack=w1["id"], reveal=True))   # Session 的默认 reveal=True
            humangui.Session().start(dict(name="smoke-srv", pack=w1["id"]))
            time.sleep(0.05)
        finally:
            undo()
        cmd = launched[0]["cmd"] if launched else []
        verdict("S11_gui_server_shim", packs == {w["id"]: tuple(m["salt"] for m in w["maps"]) + (w["boss"]["salt"],) for w in (w1, w2)}
                and cmd[2:4] == [str(pathlib.Path(__file__).resolve()), "gui-worker"] and cmd[4:] == args
                and launched[0]["env_worlds"] == str(pathlib.Path(worlds_file).resolve()) and launched[0]["cwd"] == str(ROOT)
                and humangui.subprocess.__name__ == "subprocess" and humangui.all_packs.__module__ == "humangui",
                cmd=[pathlib.Path(cmd[2]).name if len(cmd) > 2 else None, *cmd[3:]], expected_args=args, lives_size=len(packs.get(w1["id"], ())),
                env_worlds_ok=bool(launched) and launched[0]["env_worlds"] == str(pathlib.Path(worlds_file).resolve()),
                cwd_ok=bool(launched) and launched[0]["cwd"] == str(ROOT), restored=humangui.subprocess.__name__ == "subprocess")

        # S12 N5：全知的否决（地图 play_map / boss play_boss）；没触发否决的命逐张相同；play_map 与 antagonist_proto._lives 同一条命相同
        msalts = [m["salt"] for m in w1["maps"][:2]]
        same_lives, diffs, vetoes, refs = 0, [], 0, {}
        for s in msalts:
            run = ap.build(s)
            for t in range(3):
                for who in ("R1", "oracle"):
                    cap = ap._Cap()
                    r = ab.play_map(run, s, who, t, "proto-play-smoke", record=cap)      # 默认否决：ap._lives 的全知经 play_fight 包装接同一条
                    old = ap._lives(run, s, who, t + 1, "proto-play-smoke")[t]
                    same_lives += ap._sig([(r["won"], cap)]) == ap._sig([old])
                    if ap._sig([(r["won"], cap)]) != ap._sig([old]):
                        diffs.append((s, t, who))
                c_off, c_on = ap._Cap(), ap._Cap()
                off = ab.play_map(run, s, "oracle", t, "proto-play-smoke-veto", record=c_off, oracle_veto=False)
                on = ab.play_map(run, s, "oracle", t, "proto-play-smoke-veto", record=c_on)
                vetoes += on["ref"]["vetoes"]
                refs["map_oracle"] = on["ref"]
                if on["ref"]["vetoes"] == 0 and ap._sig([(off["won"], c_off)]) != ap._sig([(on["won"], c_on)]):
                    diffs.append((s, t, "oracle-veto-0-differs"))
        boss_same, boss_veto_lives, boss_v = 0, 0, 0
        for pair in (("pierce", "momentum"), ("guard", "ward"), ("charge", "mark")):
            for rev in (0, 1):
                ctx = ab.build_boss(ap.SALT0, pair, rev)
                for t in range(2):
                    off = ab.play_boss(ctx, "oracle", t, "proto-play-smoke-boss", oracle_veto=False)
                    on = ab.play_boss(ctx, "oracle", t, "proto-play-smoke-boss")
                    boss_v += on["ref"]["vetoes"]
                    if on["ref"]["vetoes"] == 0:
                        boss_same += json.dumps(off["trace"], sort_keys=True, default=str) == json.dumps(on["trace"], sort_keys=True, default=str)
                    else:
                        boss_veto_lives += 1
                    refs["boss_oracle"], refs["boss_oracle_off"] = on["ref"], off["ref"]
                refs["boss_R1v2"] = ab.play_boss(ctx, "R1v2", 0, "proto-play-smoke-boss")["ref"]
        import r1v2
        verdict("S12_oracle_veto_N5", not diffs and same_lives == 2 * len(msalts) * 3 and boss_same + boss_veto_lives == 12
                and refs["boss_R1v2"]["version"] == r1v2.VERSION and refs["boss_oracle_off"]["heal_veto"] is None
                and refs["boss_oracle"]["heal_veto"] is not None,
                map_lives_same_as_ap_lives=same_lives, map_oracle_vetoes=vetoes, boss_lives_no_veto_identical=boss_same,
                boss_lives_with_veto=boss_veto_lives, boss_oracle_vetoes=boss_v, refs=refs, diffs=diffs)

    finally:
        modelrun.RUNS_DIR, urllib.request.urlopen = saved_runs, saved_open
    rep.update(ok=ok_all[0], seconds=round(time.time() - t0, 1), runs_dir="(scratch, not kept)")
    print(f"{'ALL PASS' if ok_all[0] else 'FAIL'}（{rep['seconds']} 秒）", flush=True)
    if out:
        p = ap.refuse_overwrite(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=1))
        print(f"→ {p}")
    return rep


# ---------------------------------------------------------------- 命令行
def _model_cli(argv):
    p = argparse.ArgumentParser(prog="proto_play.py model")
    p.add_argument("model")
    p.add_argument("--worlds", required=True)
    p.add_argument("--world", default=None)
    p.add_argument("--lives", default=f"1-{N_LIVES}")
    p.add_argument("--carry", choices=CARRIES, default="notes")
    p.add_argument("--no-notes", dest="notes", action="store_false")
    p.add_argument("--fight-notes", choices=FIGHT_NOTES, default="write")
    p.add_argument("--run-id", default=None)
    p.add_argument("--letters-from", default="")
    p.add_argument("--write-letter", action="store_true")
    p.add_argument("--resume", action="store_true", help="Reuse completed lives and continue from saved model responses")
    a = p.parse_args(argv)
    specs = pw.load_worlds(a.worlds)
    spec = specs[a.world or next(iter(specs))]
    letters_from = [x for x in a.letters_from.split(",") if x]
    if a.write_letter:
        return write_letter(a.model, model_run_id(spec, a.carry, a.run_id), a.carry, letters_from=letters_from, resume=a.resume)
    print(f"proto={ap.settings()} world={spec['id']} model={a.model} carry={a.carry} notes={a.notes} fight-notes={a.fight_notes}", flush=True)
    for r in play_world(a.model, spec, lives=a.lives, run_id=a.run_id, carry=a.carry, want_notes=a.notes, fight_notes=a.fight_notes,
                        letters_from=letters_from, resume=a.resume):
        print(f"第 {r['life']} 条命（{r['kind']} {r['salt']}）：{r['result']}  → {r['record'].name}")


PARTICIPANT_CMDS = ("gui-worker", "gui", "human", "model")


# ---------------------------------------------------------------- 人类入口：候选 v3b（PROTO_HUMAN_V3B=1）
def _human_v3b_problems(variant="v3b"):
    """开关打开时环境与要求差在哪里（英文，空 = 恰好是这一套）：开关 = 1；HUMAN_V3B_ENV 的 12 个逐字；别的 PROTO_* 一个也没有；
    解析后的开关 == HUMAN_V3B_NOW；营地只许 PROTO_CAMP=1（entry v2 起必须带，_human_v3b_require_camp 先核）；PROTO_TEXT=minimal；引擎种子与图形界面的相同。
    variant="v3c"（11-06）：同样的核对，换成 HUMAN_V3C_FLAG / HUMAN_V3C_ENV / HUMAN_V3C_NOW。"""
    E = _HUMAN_ENTRIES[variant]
    bad = []
    if variant == "v3c1b" and os.environ.get("PROTO_BOSS_CUE") != "on":
        bad.append("PROTO_BOSS_CUE must be on: all bosses announce the phase change")
    if os.environ.get(E["flag"]) != "1":
        bad.append(f"{E['flag']}={os.environ.get(E['flag'])!r} (must be 1)")
    env = {k: v for k, v in os.environ.items() if k.startswith("PROTO_") and k not in E["free"]}
    if env.get("PROTO_CAMP") == "1":                       # 11-05 晚（18 §8.6）：训练营可以加（PROTO_CAMP=1）；别的值照旧「必须不设」
        env.pop("PROTO_CAMP")
    bad += [f"{k}={env[k] if k in env else '(unset)'} (needs {v})" for k, v in E["env"].items() if env.get(k) != v]
    bad += [f"{k}={v} (must be unset)" for k, v in sorted(env.items()) if k not in E["env"]]
    if E.get("boss"):                                       # v3c1b（40 号文档）：血 / 伤害要是图包里某个世界的那一对（哪个世界：选了世界之后再核）
        pair = (os.environ.get("PROTO_BOSS_HP"), os.environ.get("PROTO_BOSS_ATK"), os.environ.get("PROTO_WORLD"))   # v7：加外衣
        if pair not in set(E["boss"].values()):
            bad.append(f"{_boss_vars(pair)} is not the boss setting of any world of the pack ("
                       + "; ".join(f"world {w}: {_boss_vars(p)}" for w, p in sorted(E["boss"].items())) + ")")
    if not bad:
        now = ap._now()
        bad += [f"switch {k} resolves to {now.get(k)!r} (needs {v!r})" for k, v in E["now"].items() if now.get(k) != v]
        bad += [f"unexpected switch {k}={v!r}" for k, v in now.items() if k not in E["now"] and k not in E.get("now_free", ())]
        if ap.camp() and not pc.supported():
            bad.append("the camp is on")
        if not pt.minimal():
            bad.append(f"participant text {pt.MODE} (needs minimal)")
        import humangui
        if humangui.GAME_SEED != ap.SEED:
            bad.append(f"engine seed {ap.SEED} differs from the GUI's {humangui.GAME_SEED}")
    return bad


def _human_v3b_require_camp(variant="v3b"):
    """entry v2（11-05 夜，用户）：v3b 人类入口必须带训练营。PROTO_CAMP 不是 "1"（不设、0、2 …）就在任何东西开始之前用一句短英文拒绝。
    v3c 入口同样（拒绝的话点名 PROTO_HUMAN_V3C）。"""
    if os.environ.get("PROTO_CAMP") != "1":
        raise SystemExit(_HUMAN_ENTRIES[variant]["camp_refusal"])


def _human_v3b_flush(log):
    """人写笔记之前，把这条命的记录里还没印的行印出来（与 humanrun.human_act 印新行的写法相同）。humanrun 只在下一次出牌时才印新行，
    所以一场结束的那一行（最后一次 END 的变化、`[layer N] fight ended`）和最后一层的补给行，人在写笔记时还没见过，死了的那一场就永远
    见不到；模型的战后笔记 / 命末笔记提示里却有整场 / 整条命的记录（human_v3b_check H4 发现）。只在 PROTO_HUMAN_V3B=1 下调。"""
    for h in humanrun._new_history(log):
        print("   " + h, flush=True)


def _human_v3b_refuse(bad, variant="v3b"):
    E = _HUMAN_ENTRIES[variant]
    raise SystemExit(f"{E['flag']}=1 opens the human entry only under the exact {E['name']} environment ("
                     + " ".join(f"{k}={v}" for k, v in E["env"].items())
                     + (", plus the world's own PROTO_BOSS_HP / PROTO_BOSS_ATK" if E.get("boss") else "") + ", no other PROTO_* variable"
                     + (", plus PROTO_CAMP=1" if os.environ.get("PROTO_CAMP") == "1" else "") + "); refused: " + "; ".join(bad))   # entry v2：到这里 PROTO_CAMP 一定是 1


def human_v3b_setup(records_dir=None, variant="v3b"):
    """PROTO_HUMAN_V3B=1 的人类入口：核环境（不对就拒绝），记录目录 = records_dir / AGII_HUMAN_V3B_DIR / ~/agii_runs/human_v3b/records
    （不许在 results/ 下），核 tiktoken（笔记上限 B12 要它）。之后 human_main / gui_main / play_life 走 v3b 的分支。返回记录目录。
    entry v2：先核 PROTO_CAMP=1（_human_v3b_require_camp）。variant="v3c"：human_v3c_setup（AGII_HUMAN_V3C_DIR / ~/agii_runs/human_v3c/records）。"""
    E = _HUMAN_ENTRIES[variant]
    _human_v3b_require_camp(variant)
    bad = _human_v3b_problems(variant)
    if bad:
        _human_v3b_refuse(bad, variant)
    d = pathlib.Path(records_dir or os.environ.get(E["dir_env"]) or E["dir"]).expanduser().resolve()
    if d == ROOT / "results" or (ROOT / "results") in d.parents:
        raise SystemExit(f"Records must not go under results/: {d}")
    try:
        modelrun.letter_tokens("check")
    except SystemExit:
        raise SystemExit("The note limit needs the tiktoken package: run  python3 -m pip install tiktoken  and start again.") from None
    except Exception as e:
        raise SystemExit(f"tiktoken could not load its o200k_base encoding ({type(e).__name__}); it is downloaded once, so the first "
                         "start needs a network connection.") from None
    modelrun.RUNS_DIR = d
    _HUMAN_V3B.clear()
    _HUMAN_V3B.update(on=True, records_dir=str(d))
    if variant != "v3b":                                    # v3c：记录的 human_entry.version、报错里的候选名（v3b 不加这个键）
        _HUMAN_V3B["variant"] = variant
    return d


def human_v3c_setup(records_dir=None):
    """PROTO_HUMAN_V3C=1 的人类入口（11-06，28 §9）：同 human_v3b_setup，换成候选 v3c 的环境、开关、版本、记录目录。"""
    return human_v3b_setup(records_dir, variant="v3c")


def human_v3c1_setup(records_dir=None):
    """PROTO_HUMAN_V3C1=1 的人类入口（11-06，31 号文档）：同 human_v3b_setup，换成候选 v3c1 的环境、开关、版本、记录目录（世界文件白名单在 _human_v3b_load）。"""
    return human_v3b_setup(records_dir, variant="v3c1")


def human_v3c1b_setup(records_dir=None):
    """v7 人类入口：使用所选世界和链的环境，记录写入人类记录目录。"""
    return human_v3b_setup(records_dir, variant="v3c1b")


def _boss_vars(pair):
    hp, atk, world = (tuple(pair) + (None,))[:3]
    return (f"PROTO_BOSS_HP={hp or '(unset)'} " + (f"PROTO_BOSS_ATK={atk}" if atk else "(PROTO_BOSS_ATK unset)")
            + (" " + (f"PROTO_WORLD={world}" if world else "(PROTO_WORLD unset)") if len(tuple(pair)) == 3 else ""))


def _human_v3c1b_world(spec, w):
    """v3c1b 入口：选中的世界（文件里第 w 个）要在它自己的 boss 环境下打（boss_world_problems）；表 HUMAN_V3C1B_BOSS 与世界文件存的 boss.env 也要一致。
    不对就开打之前英文拒绝，并写出这个世界要的两个变量。"""
    from world_pack_runtime import STUDY_WORLD_LIMIT
    if not 1 <= w <= STUDY_WORLD_LIMIT:
        raise SystemExit(f"World {w}: this study uses worlds 1-{STUDY_WORLD_LIMIT} only.")
    E = _HUMAN_ENTRIES["v3c1b"]
    env = (spec.get("boss") or {}).get("env") or {}
    want = E["boss"].get(w)
    bad = boss_world_problems(spec)
    if env.get("PROTO_BOSS_CUE") != "on":
        bad.append(f"world {w} needs the cued boss environment")
    if want is None or (env.get("PROTO_BOSS_HP"), env.get("PROTO_BOSS_ATK"), env.get("PROTO_WORLD")) != want:
        bad.append(f"world {w} of the world file does not carry the boss setting this entry expects for world {w}")
    if bad:
        raise SystemExit(f"World {w} ({spec.get('id')}) is played with {_boss_vars(want or (None, None, None))}; refused: " + "; ".join(bad)
                         + f". Start again with {_boss_vars(want or (None, None, None))} in the command.")


def _human_v3c1b_gui_worlds(specs):
    """v3c1b 入口的图形界面：只列这个进程的血 / 伤害能打的世界（世界序号仍按文件里的位置）；一个也没有就英文拒绝。"""
    from world_pack_runtime import STUDY_WORLD_LIMIT
    E = _HUMAN_ENTRIES["v3c1b"]
    ok = {wid: s for w, (wid, s) in enumerate(specs.items(), 1)
          if w <= STUDY_WORLD_LIMIT and not boss_world_problems(s) and E["boss"].get(w) == ((s["boss"].get("env") or {}).get("PROTO_BOSS_HP"),
                                                                  (s["boss"].get("env") or {}).get("PROTO_BOSS_ATK"),
                                                                  (s["boss"].get("env") or {}).get("PROTO_WORLD"))}
    if not ok:
        raise SystemExit(f"No world of the world file is played with {_boss_vars((os.environ.get('PROTO_BOSS_HP'), os.environ.get('PROTO_BOSS_ATK'), os.environ.get('PROTO_WORLD')))} ("
                         + "; ".join(f"world {w}: {_boss_vars(p)}" for w, p in sorted(E["boss"].items()) if w <= STUDY_WORLD_LIMIT) + ").")
    return ok


def _human_v3b_pack_check(path, raw):
    """v3c1 入口（只有它的 _HUMAN_ENTRIES 带 pack_sha256）：世界文件的内容 sha256 必须是那个包的；不是就英文拒绝。别的入口什么也不做。"""
    E = _HUMAN_ENTRIES[_HUMAN_V3B.get("variant", "v3b")]
    sha = __import__("hashlib").sha256(raw).hexdigest()
    if sha in (E.get("retired") or {}):                     # v3c1b 入口（41 §10）：停用的包，明确拒绝
        raise SystemExit(f"The world file {path} is {E['retired'][sha]}, which was {HUMAN_V3C1B_REPLACED}. Start again with --worlds {E['pack']}")
    if E.get("hard_pack_sha256") and sha in HUMAN_V3C1B_HARD_RETIRED:  # 停用的 hard 包（v7hard → v7hard2，11-12）
        raise SystemExit(f"The world file {path} is {HUMAN_V3C1B_HARD_RETIRED[sha]}. Start again with --tier hard.")
    import tier_rules
    if E.get("hard_pack_sha256") and sha in tier_rules.pack_shas():     # hard 包（v7hard2 / v7hard3）：只在登记过的档位下打
        # 11-13：hard 包只在登记过的档位下打（scripts/tier_rules.py：hard = hard2-w10s3，hard3 = + 补给 r1v2x120，formal = 正式：
        # 无封印时限 + 补给表）——环境里的 PROTO_* 必须正好是其中一档；有补给表的档位核表的 sha256。
        # 11-14：而且这个文件必须是该档位自己的图包（formal 只打 v7hard3，hard / hard3 只打 v7hard2）。
        matched = tier_rules.match_env(os.environ)
        bad = [] if matched else [k for k, v in HUMAN_V3C1B_HARD_ENV.items() if os.environ.get(k) != v] or ["PROTO_RESTAMT"]
        if matched:
            tier_rules.check(matched[1])
            if tier_rules.pack_for(matched[1])[1] != sha:
                raise SystemExit(f"The world file {path} is not the pack of tier {matched[0]}; start it with --tier {matched[0]}.")
        if bad:
            raise SystemExit(f"The world file {path} is the hard pack; it is played only with "
                             + " ".join(f"{k}={v}" for k, v in HUMAN_V3C1B_HARD_ENV.items()) + " (start it with --tier hard).")
        return
    if E.get("pack_sha256") and sha != E["pack_sha256"]:
        raise SystemExit(f"The world file {path} is not the {E['name']} pack (its sha256 differs). Start again with --worlds {E['pack']}")


def _human_v3b_load(path):
    """世界文件（proto_world.save_worlds 的格式，或单个 spec）→ {id: spec}；读不了就英文拒绝。"""
    if not path:
        raise SystemExit("No world file: give --worlds FILE (or set PROTO_WORLDS).")
    if _HUMAN_ENTRIES[_HUMAN_V3B.get("variant", "v3b")].get("pack_sha256"):    # v3c1 入口：先核内容（v3b / v3c 入口不进这里）
        try:
            raw = pathlib.Path(path).expanduser().read_bytes()
        except OSError as e:
            raise SystemExit(f"Cannot read the world file {path} ({type(e).__name__}).") from None
        _human_v3b_pack_check(path, raw)
    try:
        specs = pw.load_worlds(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise SystemExit(f"Cannot read the world file {path} ({type(e).__name__}).") from None
    if not specs:
        raise SystemExit(f"The world file {path} holds no world.")
    if _HUMAN_V3B.get("variant") == "v3c1b":
        from world_pack_runtime import STUDY_WORLD_LIMIT
        specs = dict(list(specs.items())[:STUDY_WORLD_LIMIT])
    return specs


def _human_v3b_pick(specs, world=None, index=None):
    """(世界 id, 它在文件里的位置 w，从 1 起)。只给 index：文件里第 index 个；只给 id：那个世界；都给：必须一致；都不给：第 1 个。"""
    ids = list(specs)
    if index is not None and not 1 <= index <= len(ids):
        raise SystemExit(f"World index {index}: the world file has worlds 1-{len(ids)}.")
    if world is None:
        wid = ids[(index or 1) - 1]
    elif world not in specs:
        raise SystemExit(f"World {world} is not in the world file.")
    else:
        wid = world
    w = ids.index(wid) + 1
    if index is not None and index != w:
        raise SystemExit(f"World {wid} is world {w} of the world file, not world {index}.")
    return wid, w


def _human_v3b_verify(spec):
    """proto_world.verify（重建 4 张图、核规则 W0–W4）；不过就英文拒绝（原报错是中文）。"""
    if not str(spec.get("id", "")).startswith(pw.ID_PREFIX):
        raise SystemExit(f"A world id must start with {pw.ID_PREFIX!r}: {spec.get('id')!r}")
    try:
        pw.verify(spec)
    except (ValueError, KeyError, TypeError, AttributeError, AssertionError) as e:
        raise SystemExit(f"World {spec.get('id')} does not pass the world check under these switches ({type(e).__name__}); "
                         f"use a world file built under {_HUMAN_ENTRIES[_HUMAN_V3B.get('variant', 'v3b')]['name']}.") from None


def _cli_guard(cmd):
    """参与者命令行入口（model / human / gui / gui-worker）的拒绝（英文，开打前、任何 API 之前）：PROTO_HAND=fixed（v1.2.2）；
    v1.3：PROTO_INCOMING / PROTO_THREAT / PROTO_MARKMAP 任何一个非默认（D12，候选规则，采用之前不给参与者玩）。GUI 子进程继承环境变量，同样被拒。
    11-03 夜：PROTO_LADDER=1 / PROTO_TUNE 不是 none（惩罚阶梯、M59+WS2 调参，候选，采用的版本切出来之前不给参与者玩）—— 先查它们，
    拒绝时点名（PROTO_LADDER=1 一定和 PROTO_HAND=fixed 一起，否则导入时就拒绝了）；都是默认时下面照旧。版本号不改（默认路径不变）。
    11-04：PROTO_RAGE=off（去掉怒气，13 §4b，候选）加进同一张表；三者（11-04 起 PROTO_TUNE 也是）都只许和 PROTO_HAND=fixed 一起。
    别的命令（smoke、无参数）不受影响；核对的进程内调用不经过这里。"""
    if cmd not in PARTICIPANT_CMDS:
        return
    if cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3B_FLAG) is not None:   # 11-05 夜：人类入口在候选 v3b 下的显式开关（model 不受影响）
        _human_v3b_require_camp()                          # entry v2：必须带 PROTO_CAMP=1（短英文拒绝，先于其余核对）
        bad = _human_v3b_problems()
        if bad:
            _human_v3b_refuse(bad)
        return
    if cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C_FLAG) is not None:   # 11-06：候选 v3c 的人类入口（同上，换 v3c 的一套；model 不受影响）
        _human_v3b_require_camp("v3c")
        bad = _human_v3b_problems("v3c")
        if bad:
            _human_v3b_refuse(bad, "v3c")
        return
    if cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C1_FLAG) is not None:  # 11-06：候选 v3c1 的人类入口（同上，换 v3c1 的一套；model 不受影响）
        _human_v3b_require_camp("v3c1")
        bad = _human_v3b_problems("v3c1")
        if bad:
            _human_v3b_refuse(bad, "v3c1")
        return
    if cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C1B_FLAG) is not None:  # 11-07：候选 v3c1 + boss 的人类入口（40 号文档；model 不受影响）
        _human_v3b_require_camp("v3c1b")
        bad = _human_v3b_problems("v3c1b")
        if bad:
            _human_v3b_refuse(bad, "v3c1b")
        return
    v3 = ap.v3_now()                                     # 候选 v3（18）：先查、点名；默认下是 {}，下面照旧
    if v3 and (v3.get("pool") == "v3b" or "counter" in v3 or "guardstart" in v3 or v3.get("ladder_table") == "v3b"
               or ap.TUNE == "m59ws2t25c"):              # 候选 v3b（18 §8.1–§8.4，11-05）：同样拒绝，点名新开关（v3 的那一句不变）
        raise SystemExit("PROTO_POOL=v3b / PROTO_COUNTER / PROTO_GUARDSTART / PROTO_LADDER_TABLE=v3b / PROTO_TUNE=m59ws2t25c_bp45w90 are "
                         "candidate rules (candidate v3b). Their participant text (PROTO_TEXT=minimal) is written and checked, but participant "
                         "play stays refused until the user opens it; refused under "
                         f"{ap._env(v3)}{' PROTO_TEXT=' + pt.MODE if pt.minimal() else ''}.")
    if v3:
        raise SystemExit("PROTO_POOL / PROTO_MOMENTUM / PROTO_DOUBLER / PROTO_GUARDCODE / PROTO_LADDER_TABLE=v3 are candidate rules "
                         "(candidate v3) whose participant rule text is not written yet, so participant play is refused under "
                         f"{ap._env(v3)}.")
    if pt.minimal():                                        # 11-05：文字开关本身也还没放开（用户定）
        raise SystemExit("PROTO_TEXT=minimal is the candidate participant text; participant play under it is refused until the user opens it.")
    now = ap._now()
    cand = [f"PROTO_{k.upper()}={int(now[k]) if isinstance(now[k], bool) else now[k]}" for k in ("ladder", "tune", "rage")
            if now[k] != ap.DEFAULTS[k]]
    if cand:
        raise SystemExit("PROTO_LADDER / PROTO_TUNE / PROTO_RAGE are candidate rules not yet adopted (the penalty ladder; the M59+WS2 "
                         f"tuning; no rage), so participant play is refused under {' '.join(cand)}.")
    if ap.HAND == "fixed":
        raise SystemExit("PROTO_HAND=fixed is a candidate rule set: the 40-turn limit is not yet explained to participants, "
                         "so participant play is refused under it.")
    now = ap._now()
    off = [f"PROTO_{k.upper()}={now[k]}" for k in ("incoming", "threat", "markmap") if now[k] != ap.DEFAULTS[k]]
    if off:
        raise SystemExit("PROTO_INCOMING / PROTO_THREAT / PROTO_MARKMAP are candidate rules not yet adopted, so participant play is "
                         f"refused under {' '.join(off)}.")


if __name__ == "__main__":
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    _cli_guard(cmd)
    if cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3B_FLAG) is not None:   # 只在开关打开时（_cli_guard 已核过环境）
        human_v3b_setup()
    elif cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C_FLAG) is not None:   # 11-06：候选 v3c（_cli_guard 已核过环境）
        human_v3c_setup()
    elif cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C1_FLAG) is not None:  # 11-06：候选 v3c1（_cli_guard 已核过环境）
        human_v3c1_setup()
    elif cmd in HUMAN_V3B_CMDS and os.environ.get(HUMAN_V3C1B_FLAG) is not None:  # 11-07：候选 v3c1 + boss（_cli_guard 已核过环境）
        human_v3c1b_setup()
    if cmd == "gui-worker":
        sys.exit(gui_worker(rest))
    if cmd == "gui":
        sys.exit(gui_main(rest))
    if cmd == "human":
        human_main(rest)
    elif cmd == "model":
        _model_cli(rest)
    elif cmd == "smoke":
        r = smoke(rest[0], rest[1] if len(rest) > 1 else None)
        sys.exit(0 if r["ok"] else 1)
    else:
        print(__doc__)
