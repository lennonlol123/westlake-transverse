"""R1 v2（2026-11-02，D5）：R1 v1 原样 + 三处改动。规格写在看结果之前：docs/antagonist_boss/04_r1v2_spec.md。
  C1  只用公开信息认出动量（回合末：印出的攻击升了、结算时没举盾、本回合打出了伤害、没出非攻击牌、蓄力没满、不是换阶段那一次结算）
  C1b 认出的动量抄进 st.types（「认出了就不再设防」）
  C2  solver.act 读的 f.momentum 换成公开估计（连续没举盾的结算次数，按自己的动作和规则常量数）
  C3  收到 BOSS_SHIFT（"The enemy has changed."）时撤回「眼前这只是什么」，保留规则和事实；槽位证据从提示后重新开始
  C4  决策 / 观察代码只拿公开视图 PublicFight，并在 hidden_access_guard() 里运行（读隐藏状态就抛 HiddenRead）
      b 版（同日，审查后）：视图里不留真对局、不留任何真值副本，守卫里只许读白名单 PUBLIC；can_play 按规则书牌价；自己的攻击只认从日志推出的值，
      没有公开尺子的结算不立穿透 / 反击标志；mark_restarts() 下公开的累计出牌从提示起算。守卫是绊线，不是沙箱（见规格第 5 节）。
  C6  c 版（2026-11-03，「把尺子修好」N5）：路线的自动治疗要是付了就会让策略本回合的第一张牌付不起，这一刻就不治疗（规格 §3 C6）。
      经已有的 heal_veto 钩子，在守卫里只读视图；R1v2Policy(energy_veto=False) / ENERGY_VETO=False 给出 b 版的**策略**。
      b 版的**数字**（r1v2_smoke_b.json 等）还要存档的原型开关：with antagonist_proto.archived()，或导出
      PROTO_LOOT=1 PROTO_NODES=route PROTO_DISPLAY=per-player PROTO_REFS=b —— 光关 ENERGY_VETO，新默认（固定节点）下冒烟的 decisions 798 对存档 750
      （审查 2026-11-03；archived() 下 0 个键不同，见规格 §9c 末）。
      实际触发面（审查 2026-11-03，规格 §3 C6「实际上」）：每回合能量 2、只有闪 2 费，所以回合开头只在策略第一张是闪时否决；另一种是同一回合
      已出过一张治疗、还没出非治疗牌时挡住第二张治疗。
      energy_heal_veto(act_fn) 是同一条规则的通用工厂；oracle_heal_veto(...) 给 oracle 用（诊断参照的改动，不属于 R1v2）。
v1（core/cautious.py、devworld.R1_VARIANT / R1_DISPLAY、regsel.r1_wins）一行不改；core/ 不改。
用法：p = R1v2Policy(); with display(): solver.run_once(run, know(), route, rng, information="observable",
                                             act_policy=p.act, heal_veto=p.heal_veto, belief_cls=R1v2Belief)
      单场（boss）：won, p = play_fight(run, f, run.by_kind, route.heal_at)
冒烟核对：python3 -B scripts/r1v2.py（单进程，几十条命，不算通过率）→ results/proto13/boss_checks/r1v2_smoke_b.json
（r1v2_smoke.json 是 a 版 R1v2/2026-11-02 的冒烟记录，留档不覆盖）
c 版冒烟：python3 -B scripts/r1v2.py c → results/proto13/boss_checks/r1v2_smoke_c.json（c 与 b 同一随机流逐张对照、否决计数、oracle 工厂，不算通过率）

d 版（2026-11-04 晚，候选 v3：docs/antagonist_boss/18_candidate_v3_spec.md；c 版原文件存档在 scratchpad v3/archive/r1v2.py）：
  只在 v3 的规则真的生效时才多做事；v3 开关全关时 d 与 c 逐张相同（R 部分的 before/after 核对），版本串也照旧是 c（VERSION 由
  antagonist_proto.setup() 的 after-setup 钩子 _sync_v3 按开关设：PROTO_MOMENTUM=noshield 或 PROTO_GUARDCODE=map 时 = VERSION_D）。
  规则从哪里知道：R1v2 懂全部规则（规则书），所以「这一局动量是不是 noshield、守势格是不是按图映射」读的是规则本身是否生效
  （penalty_ladder 装着且 MOMENTUM_MODE == "noshield"；guard_slot 装着），不是这一张图 / 这一只怪的任何隐藏值。每条命开局定一次。
  V1 守势格按图映射（PROTO_GUARDCODE=map）：画面上守势那一格印的 0 / 1 是这张图的映射（normal：守 1 攻 0；flipped：守 0 攻 1），
     R1v2 不知道是哪一张，只用公开的东西认：
       · 证据：某回合出了攻击 → 被反弹（f.reflected 涨了）= 那一回合是守相；没被反弹 = 攻相（守势怪的攻击总有伤害）。
         守相每个 END 必翻（规则），所以知道一个回合的相位就知道这一段（两次换阶段提示之间）每个回合的相位；
         再配上任何一个回合印出的数 → 这张图「守相印几」。换阶段提示之后相位证据清掉（进场的守势从新的起点翻），映射本身不清（每张图 / 每个 boss 一张）。
       · 映射按 is_boss 分两份：地图战斗共用一张（同一条命里教学认出、考试接着用），boss 另一张（boss 命每条新建策略，boss 自己认）。
       · 认出之前、守势格印着数（第 2 回合起）：当它是攻相，出一次攻击 —— 就是那一次安全的试探（教学 x2、boss x3 不致死）；
         出完立刻有证据，之后按映射解码。没印的回合（第 1 回合）照旧：本回合被反弹过 = 守相，否则 0（c 版渲染层的规则推断）。
       · 解码写进决策层自己的那份视图状态 v.state[("them", "guard")]（渲染层每次同步重建这张表），solver.act 读到的就是引擎含义的 0 / 1。
     只在守卫里、只读视图的白名单字段（printed_slots、turn、fight_kinds、reflected、cues、is_boss、layout、state）。
  V2 动量 noshield（PROTO_MOMENTUM=noshield）：END 没举盾、没闪 → 普通一击 x 阶梯倍数；举着盾只挨普通一击、不算；不预告（印出的攻击 = 普通一击）。
       · 谨慎的设防（规则已知、身份未知）：这只怪还没认出是别的机制（st.types 空）或已认出是动量时，本回合还没举盾、没出闪、策略也不打算出闪 →
         先出盾（没有穿透的池里举盾从不挨罚，所以这道防几乎不花钱。PROTO_POOL=full 下没认出的怪也可能是穿透：默认出牌线在认出之前本来就
         「攻击 + 盾」，设防只多在治疗那种回合举盾；认出穿透（或任何别的机制）就不再设防，见 _decide）。
       · 识别（C1n，只给报告和 C1b 用；设防不靠它）：END 没举盾、没闪、不是满格大招、不是换阶段那一次，掉血 >= 2 x 已知的普通一击
         （公开尺子：印出的攻击；举着盾挨打时 掉血 + 盾 = 普通一击；举着盾没掉血时 普通一击 <= 盾，于是没盾的掉血 > 盾也算）→ 认出动量。
       · 交给 solver.act 的知识里去掉 momentum：它的 ramping / quiet_hold 是按连续计数的旧规则写的（f.momentum 是斜坡的计数）。
  V3 增伤冷却（PROTO_DOUBLER=turncd）：不改出牌。冷却那一回合手里没有增伤，can_play 本来就按手牌判；自己攻击的推断（_Renderer.sync）在
     END 清掉增伤标志时不误判（增伤和攻击不在两次同步之间）。这个池里 solver 的出牌线只在攻击之后才出增伤（armour / tempo 分支不在池里），
     所以 turncd 下增伤只剩「抬高标记抽到增伤的权重」这一点作用；R1v2 / 全知照旧出（不另加规则）。
  全知（oracle，诊断参照，不进 D）在本文件的 oracle v3 包装里：PROTO_MOMENTUM=noshield 时 _sync_v3 给 solver.act 包一层（只改
     information == "oracle" 且这一阶段 penalty_ladder.momentum_noshield(f) 的那一步：没举盾、没闪、不打算闪 → 先出盾，知识去掉 momentum）；
     守势它读引擎真值（全知本来就知道映射：它是懂全部、看得到全部的参照），增伤同 R1v2 不改。版本 ORACLE_V3_VERSION，
     antagonist_proto.references() 在包装装着时记 oracle_v3。

e 版（2026-11-05，v3 build 的独立审查之后；d 版原文件存档在 scratchpad v3/archive/r1v2.py.d）：
  V3 增伤冷却（PROTO_DOUBLER=turncd）改成有规则：审查实测 turncd 下 R1v2 / 全知的增伤全在攻击之后出（25 条命里 ('buff_mark', 'attack') 一次也没有）——
     冷却下那张增伤当回合就清掉，什么也不加，只触发冷却。懂规则的谨慎玩家不会这样出：出牌线是「攻击、然后增伤」（攻击之后不举盾：盾被标记避开等）
     时改成先增伤再攻击（doubler_first：同样两张、同样能量，攻击翻倍）。只在翻倍不会翻倍惩罚时改：R1v2 / R1 = 这只怪已认出、且不是守势 / 破势；
     全知 = 此刻不在守相、没封着。攻击之后本来就举盾的回合（「盾、增伤」「攻击、盾」）不改。
  R1（core/cautious.py v1，不改）在 v3 下的包装（R1_V3_VERSION，install_r1_v3 / remove_r1_v3，见「e 版：R1」一节）：审查实测 R1 在
     PROTO_GUARDCODE=map 下认出守势之后读引擎相位（0 次反弹）= 用了隐藏信息。包装让它用与 V1 同一套公开证据解码，增伤冷却下同 V3。
  版本：v3 规则生效（noshield / guardmap / turncd 任一）时 VERSION = VERSION_E，全知包装 ORACLE_V3_VERSION、R1 包装 R1_V3_VERSION；
     v3 全关时照旧是 c、包装都不装（逐字同 c 版）。d 与 e 只差 turncd 下的 V3（不开 turncd 时逐张相同）。

f 版（2026-11-05，候选 v3b，spec 18 §8.2–§8.3；e 版原文件存档在 scratchpad v3b/archive/r1v2.py.pre_v3b）：
  V4 反击「不准用增伤」（PROTO_COUNTER=nodouble，规则书层面：penalty_ladder 装着且 COUNTER_MODE == "nodouble"）：
     · 识别：同一回合攻击和增伤都出了、第二张出手的当下自己的血掉了（且这一下没有被反弹：reflected 没涨）→ 反击（belief.counter）。
       证据全是公开的：自己的出牌、自己的血（日志那一行）、反弹计数。快照在每回合开头（observe_events）和每张牌之后（observe_play）更新。
     · 谨慎（lead 给的规则书已知的谨慎打法）：没认出机制的怪一律不把攻击和增伤放在同一回合 —— R1v2 的 _guards 在 nodouble 下设防反击
       （= 变体的 counter，不是 counter_after_probe）；认出任何一种机制之后照常。回合末举盾照 V2 的 hedge。
     · 增伤先出（V3 doubler_first）的「翻倍安全」再去掉认出的反击（R1v2 / R1 / 全知三处同一条；默认池里没有反击，旧行为不变）。
  R1（core/cautious.py v1 的 e 版包装）在 nodouble 下：识别同上（运行时给 cautious.PublicBelief.observe_play 包一层，只认 R1 包装记下的
     出牌前快照；R1v2 的信念自己覆盖 observe_play，不经过它）；设防规则不变（counter_after_probe：认出反击之后一回合只进攻一次）。
  全知：solver.act 本来就按真机制对反击一回合只进攻一次；只改 doubler_first 的安全条件（这一阶段有反击 → 不先出增伤）。
  版本：nodouble 生效时 VERSION = VERSION_F、全知包装 ORACLE_V3B_VERSION、R1 包装 R1_V3B_VERSION；不开 nodouble 时同 e 版逐张相同。

g 版（2026-11-05 夜，spec 18 §8.7、docs/antagonist_boss/26_momentum_shieldonly.md；f 版原文件存档在 ~/agii_runs/v3b_momentum/archive/r1v2.py）：
  V2g 动量 shieldonly（PROTO_MOMENTUM=shieldonly，规则书层面：penalty_ladder 装着且 MOMENTUM_MODE == "shieldonly"）：END 没举盾就罚，
     闪避不躲开（闪了照样 普通一击 x 阶梯倍数、照样算一次）；举着盾只挨普通一击、不算。其余同 noshield（noshield_rule() 对这一族都为真）。
     · 谨慎的设防（V2 的 hedge 改一处）：对还没认出机制的怪（画面上没有它的槽、也没有别的证据）或认出是动量的怪，本回合还没举盾、没出闪时，
       **不靠闪**：策略这一步要出闪也换成盾（noshield 下「正要闪」算答上了，shieldonly 下不算）。已经出了闪（能量用完）就没法再举盾，原样。
       认出是别的机制（例如蓄力的计数槽印出来了）→ 照旧不设防，闪照常用。
     · 识别（C1n）：shieldonly 下闪掉的 END 也是证据（没盾、闪了照样罚：掉血 >= 2 x 普通一击 → 动量）；noshield 下闪掉的照旧不算。
     · 全知包装同一处：这一阶段有动量（读真对局）时，原出牌线这一步是闪也换成盾（ORACLE_V3C_VERSION）。
  版本：shieldonly 生效时 VERSION = VERSION_G（nodouble 也开着；b 版后缀 V3BG_SUFFIX）、全知包装 ORACLE_V3C_VERSION；R1（core/cautious.py v1 的包装）
  不改（R1 不是本条规则的参照，shieldonly 下它照旧可能对动量闪；只作诊断）。不设 shieldonly 时与 f 版逐字相同（版本串也不变）。

h 版（2026-11-06，spec 18 §8.8、docs/antagonist_boss/27_counter_noblock.md；g 版原文件存档在 ~/agii_runs/v3b_counter/archive/r1v2.py）：
  V5 反击 noblock（PROTO_COUNTER=noblock，规则书层面：penalty_ladder 装着且 COUNTER_MODE == "noblock"）：同一回合攻击和举盾都出了，第二张出手的
     当下罚（普通一击 x 阶梯倍数，直接扣血）、这一回合的盾作废；攻击 + 增伤合法。
     · 认法（lead 给的规则书已知的谨慎打法，原样就是 R1v2 已有的次序，只加识别和认出之后的打法）：
         第 1 回合：没认出的怪只举盾（v1 变体的 defend 开场：不出攻击、增伤；V2 的 hedge 先举盾）—— 对每种机制都安全，槽位类（蓄力、守势、破势）
           第 1 个 END 之后或第 2 回合起显形；
         第 2 回合起还没认出（没有槽）：照常「举盾 + 攻击」（V2 的 hedge 先举盾）—— 这就是那一次试探：反击当下罚（教学 / 考试第一下都是 x2）→ 认出反击；
           没罚 → 不是反击（规则确定、没有随机：同样的出牌之后每回合都一样安全），照常每回合举盾（对动量正确）。
         不另设「排除了反击」的状态：没罚过的「攻击 + 盾」下一回合照样安全。
     · 识别：这一张是攻击 / 盾、这一回合两种都出过、出牌前以来自己的血掉了、反弹数没涨 → belief.counter（证据同 f 版 V4：自己的出牌、血、反弹计数）。
       noblock 下回合末的 v1 反击证据（进攻 >= 2、没盾、掉血 > 1.5 x 尺子）不认：那是引擎原规则的证据，noblock 下攻击 + 增伤不罚。
     · 认出反击之后（这一场）：**同一回合永不既攻击又举盾**——每回合攻击，手里有增伤就先增伤再攻击（V3 doubler_first 的安全集合在 noblock 下
       不排除反击），从不举盾（_extra_avoid 加 block）。简单、写死：不在「攻击 + 增伤」与「只举盾」之间按数值挑。
     · 设防：noblock 下不设 f 版 V4 的「没认出之前攻击和增伤不同回合」（_guards 的防反击 = False）。
  全知包装 d（ORACLE_V3D_VERSION）：这一阶段有反击（读真对局）且 noblock 时，交给原 solver.act 的知识去掉 counter（它的「一回合只进攻一次」是引擎原规则）、
     避开 block（从不举盾）；doubler_first 的安全条件在 noblock 下不排除反击。
  R1（core/cautious.py v1 的包装）不改：noblock 下它不认反击（只装 nodouble 的识别），会对反击怪每回合「攻击 + 盾」挨罚；只作诊断。
  版本：noblock 生效时 VERSION = VERSION_H（shieldonly 同开时也是 h：V2g 照旧生效；b 版后缀 V3BH_SUFFIX）、全知包装 ORACLE_V3D_VERSION；
  R1 包装版本 = R1_V3_VERSION（noblock 下不装 nodouble 的识别）。不设 noblock 时与 g / f 版逐字相同（版本串也不变）。"""
import collections, contextlib, json, math, os, pathlib, sys, weakref
from dataclasses import dataclass
# i 版（2026-11-06，boss 第一版，spec 18 §8.10、docs/antagonist_boss/32_boss_v1.md；h 版原文件存档在 ~/agii_runs/v3c1_boss/archive/r1v2.py.h）：
#   V6 换阶段之后重新认（PROTO_BOSS=v1，开关层面 bossv1_rule()）：收到 "The enemy has changed." 时 C3 照旧撤回身份判断、留规则；另外把这一场的
#      「开场回合」挪到提示之后的第一回合（st.first_turn = 那一回合）—— 于是 v1 变体的 defend 开场在那一回合再用一次：没认出的怪只举盾（不出攻击、
#      增伤）；对每种机制都安全（反击要攻击 + 盾、动量要没盾、守势要攻击、破势只是空打、蓄力从 1 起这一回合满不了），槽位类（蓄力、守势、破势）
#      在那一回合的 END 之后显形；之后还没认出（没有槽）就照常「举盾 + 攻击」= 无槽位的那一次试探（boss 上反击 x1 不致死），同地图。
#      守势按 boss 映射（V1，boss 一张）：第一阶段认出过就接着用；没认出过就照 V1 的「当攻相出一次攻击」试探（boss 第二阶段 x3 不致死）。
#   只读公开的东西（提示那一行、自己的出牌、画面），在守卫里。PROTO_BOSS 不开时一步也不走，版本串照旧（h / g / f …）。
# j 版（2026-11-06，boss 第四版，docs/antagonist_boss/35_boss_v4_irregular.md；i 版原文件存档在 ~/agii_runs/v3c1_boss/v4irr/archive/pretree/scripts/r1v2.py）：
#   只在 PROTO_BOSS_CUE=off（没有换阶段提示）或 PROTO_GUARDSEQ 不是 none（守势不规则）时多做事；都不开时与 i 逐张相同、版本串照旧。
#   V7 没有提示时自己认出换阶段（nocue_rule()；只读画面上印出的怪方状态格、回合数、自己的认怪；渲染层的 _NoCue 检测器 + 决策层的一条）：
#      (a) 出现：第 3 回合起画面上第一次出现一个这一场从没印过的状态格（槽位类机制的格在第 1–2 回合就会出现）→ 换了；
#      (b) 冻住：一个印着的格停在同一个数上，超过规则允许的回合数（规则书：守势每个 END 必翻 → 2 个回合一样；守势不规则 → 连着最多 3 个回合同相 →
#          4 个回合一样；蓄力 0 / 1 每个 END 涨 → 2 个一样，不规则蓄力最多连停一次 → 3 个一样；蓄力 2 下一个 END 必放 → 2 个一样；
#          破势 0 = 开着的窗口，ward_window 个 END 之后封回 → ward_window + 1 个回合都是 0）→ 换了（离场的格清 0 之后一直印着那个数）；
#      (a)(b) 在下一回合开头当成一次提示处理（C3 撤回 + V6 重新开场，同 i 版收到提示）；(a) 出现的那一格算「变过」，当场认；
#      (c) 新机制：已经认出一种机制、又凭证据（反弹、打空、当下的反击罚、C1n 的动量罚）认出另一种 → 换了：撤回旧的、留新的、不重新开场
#          （新的已经认出来了，再试探只会再挨一次罚）。
#      每场最多认一次（boss 只换一次）：任一条触发之后两条都关。日志 NOCUE_LOG：(fight id, 回合, 哪一条, 格 / 机制)。
#   j2（boss 第五版，docs/antagonist_boss/36_boss_v5.md；PROTO_BOSS_CUE=bytype 或 PROTO_BOSS_SLOTSWAP=vanish 时的版本串，别的情形与 j 逐张相同）：
#      (d) 消失：上一回合印着的一个状态格这一回合不印了 → 换了（PROTO_BOSS_SLOTSWAP=vanish 下离场的格从换阶段之后的第一个画面起不印）；
#      收到真的提示（PROTO_BOSS_CUE=bytype 的同类对）→ 照 i 版处理（撤回 + 重新开场），V7 的检测器这一场关掉（不重复认）；
#      bytype 下 R1v2 不事先知道这只 boss 是不是混合对：两条路都开着，先到的那个算。
#   V8 守势不规则（guardseq_rule()）：V1 的映射只用同一回合的相位证据 + 同一回合印出的数（不再按「每 END 必翻」把相位推到别的回合）；没印的回合只用
#      本回合被反弹过 = 守相（渲染层的规则推断），不再推。全知读真对局，不受影响；solver.act 只读此刻的守势格、蓄力格（核对过：core/solver.py 的
#      guarder / charged 只读当前值，没有周期假设）。R1（core/cautious.py 的 v3 包装 _r1_guard_decode）仍按每 END 必翻推 —— R1 不是本版的参照，不改。

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "scripts"))
import adventure, camp, cautious, devworld, solver
from adventure import BOSS_SHIFT, ENEMY_STATE_SLOTS, TUNING

VERSION_C = "R1v2/2026-11-03c"    # c：C6 自动治疗不挤掉本回合第一张牌（N5，通用的能量否决），写在看任何 c 版结果之前
VERSION_B0 = "R1v2/2026-11-02b"   # b：审查后的 D5 修订（视图白名单、牌价按规则书、自己的攻击按日志推、没尺子不立标志、进场标记计数）；energy_veto=False 时的版本
VERSION_D = "R1v2/2026-11-04d"    # d：c + 候选 v3 的 V1（守势格按图映射）/ V2（动量 noshield）；v3 规则不生效时与 c 逐张相同（存档 scratchpad v3/archive/r1v2.py.d）
VERSION_E = "R1v2/2026-11-05e"    # e：d + V3（PROTO_DOUBLER=turncd：出牌线是「攻击、然后增伤」时改成先增伤再攻击，见模块说明 e 版）；v3 规则不生效时与 c 逐张相同
VERSION_F = "R1v2/2026-11-05f"    # f：e + V4（PROTO_COUNTER=nodouble：反击按当下那一下认、没认出之前攻击和增伤不同回合）；nodouble 不开时与 e 逐张相同
VERSION_G = "R1v2/2026-11-05g"    # g：f + V2g（PROTO_MOMENTUM=shieldonly：设防不靠闪、闪掉的 END 也是动量证据）；shieldonly 不开时与 f 逐张相同
V3_SUFFIX = "+v3-2026-11-05e"     # b 版在 v3 规则下（PROTO_REFS=b）：b 的策略 + 同一套 V1 / V2 / V3
V3B_SUFFIX = "+v3b-2026-11-05f"   # b 版在 nodouble 下：b 的策略 + V1–V4
V3BG_SUFFIX = "+v3b-2026-11-05g"  # b 版在 shieldonly 下：b 的策略 + V1–V4 + V2g
VERSION_H = "R1v2/2026-11-06h"    # h：g + V5（PROTO_COUNTER=noblock：攻击 + 盾当下罚、盾作废；认出之后同一回合不既攻击又举盾）；noblock 不开时与 g / f 逐张相同
V3BH_SUFFIX = "+v3b-2026-11-06h"  # b 版在 noblock 下：b 的策略 + V1–V3 + V5（+ V2g，shieldonly 同开时）
VERSION_I = "R1v2/2026-11-06i"    # i：h + V6（PROTO_BOSS=v1，boss 第一版：换阶段提示之后重新开场 —— 提示后的第一回合只举盾）；PROTO_BOSS 不开时与 h 逐张相同
V3BI_SUFFIX = "+v3b-2026-11-06i"  # b 版在 PROTO_BOSS=v1 下：b 的策略 + V1–V3 + V5 + V6
VERSION_J4_NOTE = ("j3 → 2026-11-07 fix (boss v8, doc 39): the V7 (c) 'new mechanism' switch detector only counts mechanisms in the pool "
                   "(solver.MECHANICS); before it, a belief flag for a mechanism outside the pool (pierce, from v1's END evidence) could count "
                   "as a switch")
VERSION_J3 = "R1v2/2026-11-07j3"  # j3：j2 + 第七版的规则常量（PROTO_CHARGESEQ=len234：蓄力 1 最多连印 3 个回合）；PROTO_BOSS_GUARDIN=now 不需要改打法
VERSION_J2 = "R1v2/2026-11-06j2"  # j2：j + (d) 消失 + 真提示时关检测器（PROTO_BOSS_CUE=bytype / PROTO_BOSS_SLOTSWAP=vanish）
VERSION_J = "R1v2/2026-11-06j"    # j：i + V7（没有提示时自己认换阶段）/ V8（守势不规则下映射只用同一回合的证据）；两个开关都不开时与 i 逐张相同
V3BJ_SUFFIX = "+v3b-2026-11-06j"
NOCUE_LOG = []                    # V7 的认出记录（核对 / 测量读；每条命开头由调用方清空）
VERSION = VERSION_C               # 现在的版本串：_sync_v3（antagonist_proto.setup() 的钩子）按开关在 VERSION_C / VERSION_E 之间设
VERSION_B = VERSION_B0
ORACLE_V3_VERSION = "oracle-v3/2026-11-05"   # 全知的 v3 包装：PROTO_MOMENTUM=noshield（先举盾）+ PROTO_DOUBLER=turncd（先增伤）（见模块说明「全知」、e 版）
R1_V3_VERSION = "R1/v1+v3-2026-11-05"        # R1（core/cautious.py v1，不改）的 v3 包装：守势格按图解码 + 增伤冷却下先增伤（见模块说明 e 版）
ORACLE_V3B_VERSION = "oracle-v3/2026-11-05b"  # nodouble 下：doubler_first 不碰反击（f 版）
ORACLE_V3C_VERSION = "oracle-v3/2026-11-05c"  # shieldonly 下：动量阶段先举盾、不靠闪（g 版）
ORACLE_V3D_VERSION = "oracle-v3/2026-11-06d"  # noblock 下：反击阶段从不举盾、攻击 + 增伤（h 版）
R1_V3B_VERSION = "R1/v1+v3-2026-11-05b"       # nodouble 下：+ 反击按当下那一下认（f 版）
VARIANT = devworld.R1_VARIANT
GUARD = True                     # 默认每次决策都在守卫里；关掉只省时间、不改行为（守卫要么报错、要么放行）
ENERGY_VETO = os.environ.get("PROTO_REFS", "c") != "b"   # C6 的开关（默认开 = c 版；PROTO_REFS=b 关）；antagonist_proto.setup() 按 PROTO_REFS 再设一次


def know():
    return solver.ALL - {"mark"}                     # 调用时算：use_rotation 会重算 solver.ALL


@contextlib.contextmanager
def display():
    """R1 的画面（marks=0, state_slots="seen"），退出时恢复。"""
    saved = {k: TUNING[k] for k in devworld.R1_DISPLAY}
    TUNING.update(devworld.R1_DISPLAY)
    try:
        yield
    finally:
        TUNING.update(saved)


# ------------------------------------------------------------------ 守卫（D5 的运行时证明）
class HiddenRead(RuntimeError):
    """R1v2 的决策 / 观察代码读了没印出的状态。"""


HIDDEN_FIGHT = (
    "momentum", "fed", "enraged", "_phase2", "_phase2_turn", "_switch_pending", "stalls", "dealt", "punished", "punished0",
    "mark_perm", "rng", "countered", "mimic_hits", "ward_open_left", "ward_opened", "turn_marks", "blind_turns",
    "blocked_turns", "unblocked_turns", "fully_absorbed_turns", "absorbed_total", "dodge_offered", "seen", "slots_changed",
    "hp_floor", "enemy", "base_atk", "deck",
    "parts", "no_probe", "shown_atk", "threat_bonus", "momentum_bonus", "enrage_bonus", "greed_bonus",          # 属性
    "marked_kind", "committed", "_in_grace", "_arm_switch", "_settle_phase", "_punished_by", "_incoming", "_mark", "_slots_moved",        # 方法
    "release_committed", "_guarantee_dodge", "_offer_dodge", "play", "end_turn", "won", "lost", "over")
HIDDEN_ENEMY = (
    "behaviour", "hp", "atk", "charge_max", "big_mult", "rage", "pierce_off", "regen", "switch_to", "switch_at", "punish",
    "ward_cap", "ward_start", "charge_start", "opens_with_dodge", "_parts", "_parts2",
    "parts", "all_parts", "set_switch", "parts_for", "parts_at", "switched", "hit_now")
HIDDEN_PILE = ("draw", "rng")                         # 抽牌堆顺序；手牌、弃牌是公开的
HIDDEN_STATE_SIDE = "them"                            # Fight.state 里怪方的键全拦（画面上的怪方值由渲染层交出）

_INSTANCE_ONLY = {("Fight", "punished"), ("Enemy", "_parts"), ("Enemy", "_parts2"), ("Pile", "draw"), ("Pile", "rng")}   # 只在 __init__ / __post_init__ 里设的实例属性
_DEPTH = 0
_SAVED = []


class _GuardedState:
    """守卫期间 Fight.state 的样子：自己的键照读，怪方的键、整表遍历、写入都报错。"""
    __slots__ = ("_d",)

    def __init__(self, d):
        self._d = d

    def _ok(self, k):
        if not (isinstance(k, tuple) and k and k[0] == "me"):
            raise HiddenRead(f"Fight.state[{k!r}]")

    def __getitem__(self, k):
        self._ok(k); return self._d[k]

    def get(self, k, default=None):
        self._ok(k); return self._d.get(k, default)

    def __contains__(self, k):
        self._ok(k); return k in self._d

    def __setitem__(self, k, v):
        raise HiddenRead(f"write Fight.state[{k!r}]")

    def _dump(self, *a):
        raise HiddenRead("Fight.state (whole table)")
    __iter__ = keys = items = values = copy = __len__ = _dump


def _deny(owner, name):
    def get(obj):
        raise HiddenRead(f"{owner}.{name}")

    def put(obj, v):
        obj.__dict__[name] = v
    return property(get, put)


def _install():
    for cls, names in ((adventure.Fight, HIDDEN_FIGHT), (adventure.Enemy, HIDDEN_ENEMY), (camp.Pile, HIDDEN_PILE)):
        fields = getattr(cls, "__dataclass_fields__", {})
        for n in names:
            if (cls.__name__, n) not in _INSTANCE_ONLY:
                assert n in cls.__dict__ or n in fields or hasattr(cls, n), f"{cls.__name__}.{n} 不存在：守卫清单过时"
            _SAVED.append((cls, n, n in cls.__dict__, cls.__dict__.get(n)))
            setattr(cls, n, _deny(cls.__name__, n))
    F = adventure.Fight
    _SAVED.append((F, "state", "state" in F.__dict__, F.__dict__.get("state")))
    F.state = property(lambda o: _GuardedState(o.__dict__["state"]), lambda o, v: o.__dict__.__setitem__("state", v))


def _uninstall():
    while _SAVED:
        cls, n, had, old = _SAVED.pop()
        if had:
            setattr(cls, n, old)
        else:
            delattr(cls, n)


@contextlib.contextmanager
def hidden_access_guard():
    """在这段代码里读真对局 / 真怪物 / 抽牌堆的隐藏状态就抛 HiddenRead。可嵌套；退出时（含出错）类原样恢复。
    只包 R1v2 自己的决策 / 观察代码；引擎（出牌、结算）和渲染层（PublicFight.sync）必须在它外面跑。"""
    global _DEPTH
    if _DEPTH == 0:
        try:
            _install()
        except BaseException:
            _uninstall(); raise
    _DEPTH += 1
    try:
        yield
    finally:
        _DEPTH -= 1
        if _DEPTH == 0:
            _uninstall()


def _guard():
    return hidden_access_guard() if GUARD else contextlib.nullcontext()


# ------------------------------------------------------------------ 公开视图（渲染层 = 画面 + 日志）
class _Unknown:
    """画面上是 ? 的值：只能和自己比相等，比大小就报错。"""
    __slots__ = ()

    def __repr__(self):
        return "?"

    def _no(self, other):
        raise HiddenRead("compared an unprinted value")
    __lt__ = __le__ = __gt__ = __ge__ = __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _no

    def __eq__(self, other):
        return other is self

    def __ne__(self, other):
        return other is not self

    def __hash__(self):
        return 0

    def __bool__(self):
        raise HiddenRead("truth of an unprinted value")


UNKNOWN = _Unknown()


class _Sealed:
    """`solver.act` 无条件读 f.parts（core/solver.py:386），observable 下只在短路掉的 oracle 分支里用。读得到，一用就报错。"""
    __slots__ = ()

    def _no(self, *a):
        raise HiddenRead("Fight.parts used by an observable policy")
    __contains__ = __iter__ = __len__ = __bool__ = __getitem__ = _no


SEALED = _Sealed()


class _PublicEnemy:
    __slots__ = ("charge_max",)

    def __init__(self, charge_max):
        self.charge_max = charge_max                  # 规则常量（RULES.md:301：满格 = 2）


RULE_COST = dict(attack=1, block=1, dodge=2, heal=1, buff_mark=1)   # 规则书的牌价（RULES.md:154-160、:387，每个世界固定）


class _PublicCard:
    __slots__ = ("kind", "cost")

    def __init__(self, kind):
        self.kind, self.cost = kind, RULE_COST[kind]  # 牌种：参照的知识集（driver 交的 kinds，同 v1）；价：规则书，不读 Card.cost（画面在付过一次之前印 ?）


# 决策层在守卫里能从视图读到的全部名字（2026-11-02 审查后改成白名单：别的任何名字，包括渲染层自己的东西，守卫里一读就报错）
PUBLIC = frozenset({
    "state", "turn", "hand", "deck", "layout", "is_boss", "enemy", "parts", "max_hp", "can_play",
    "reflected", "ward_wasted", "mark_hits", "fight_kinds", "played_kinds", "last_kinds", "offences", "last_offences",
    "printed_slots", "atk_start", "settle", "cues", "cue_turns", "own_atk_known", "momentum",
    "cue_new", "nocue_ack"})                           # j 版 V7：认出「出现」的那一格（公开：画面上新出现）、决策层已经凭 (c) 认出换阶段
WRITABLE = frozenset({"momentum", "nocue_ack"})       # 决策层唯一能写的（C2 的公开估计；j 版 V7 的确认）


class PublicFight:
    """一场对局的公开视图 = 决策层能看到的全部（规格第 4 节）。视图里**没有**真对局、也没有任何真值的副本：渲染层（_Renderer，在守卫之外）
    每次同步时把画面 / 日志上出现过的量写进来。守卫里读 PUBLIC 以外的任何名字就抛 HiddenRead。"""

    def __getattribute__(self, name):
        if _DEPTH and name not in PUBLIC and not (name.startswith("__") and name.endswith("__")):
            raise HiddenRead(f"PublicFight.{name} is not public")
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise HiddenRead(f"PublicFight has no public attribute {name!r}")

    def __setattr__(self, name, v):
        if _DEPTH and name not in WRITABLE:
            raise HiddenRead(f"write PublicFight.{name}")
        object.__setattr__(self, name, v)

    def can_play(self, name):
        """手里有、按规则书的牌价付得起（不读 Card.cost；付过一次之前画面印 ?，RULES.md:66）。"""
        return name in self.hand and self.state[("me", "energy")] >= self.deck[name].cost


class _Renderer:
    """渲染层 = 画面 + 日志。守卫之外运行，读真对局，只把出现过的东西写进视图。实例只放在模块的 _VIEWS 里，视图引用不到它。"""

    def __init__(self, f, v, carry=None):
        self.fref, self.v = weakref.ref(f), v         # c3：弱引用（b 版强引用 f，_VIEWS 的清理永远不触发，长跑时每场对局都留在内存里）
        self.belief = None                            # c2：这一场 play_fight 建的信念（R1v2Belief.observe_events 登记，heal_veto 取）
        s = f.state
        self.atk_last, self.hp_last = s[("them", "atk")], s[("them", "hp")]
        self.atk0 = self.atk_last                     # 开局真值：第一次变化时由日志的 before 披露
        self.atk_shown = self.hp_shown = False
        self.ev = 0
        self.t = None; self.atk_t0 = self.hp_t0 = None; self.refl_t0 = 0; self.charge_t0 = 0
        self.slot_key = None; self.seq = 0
        self.kinds_cue = {}                           # mark_restarts() 下：最近一次提示时的累计出牌（之后公开的 fight_kinds 从这里算）
        # 自己的攻击（D5）：画面在它变过之前印 ?（RULES.md:66），这里只认从日志推出的值——一张攻击牌打下去怪血掉了多少（带增伤则除以 2）。
        # 同一条命里前一场推出过、且仍等于现值时沿用（carry 由 R1v2Policy 带着）；不等就当作不知道，宁少勿多。
        self.own_atk = None
        self.kinds_prev, self.ehp_prev, self.double_prev = dict(f.fight_kinds), s[("them", "hp")], s[("me", "double")]
        for name, c in f.deck.items():
            assert c.cost == RULE_COST[c.kind], (name, c.kind, c.cost)   # 规则书与引擎一致（只是核对，结果不进视图）
        object.__setattr__(v, "deck", {name: _PublicCard(c.kind) for name, c in f.deck.items()})
        object.__setattr__(v, "layout", f.layout); object.__setattr__(v, "is_boss", f.is_boss)
        object.__setattr__(v, "enemy", _PublicEnemy(f.enemy.charge_max))
        object.__setattr__(v, "parts", SEALED)
        object.__setattr__(v, "momentum", 0)          # C2：公开估计（由 R1v2Belief 在每次结算后更新）
        object.__setattr__(v, "cues", 0); object.__setattr__(v, "cue_turns", [])
        object.__setattr__(v, "settle", None); object.__setattr__(v, "printed_slots", {})
        object.__setattr__(v, "cue_new", frozenset()); object.__setattr__(v, "nocue_ack", False)
        self.nocue = dict(hist={}, seen=set(), done=False, fid=id(f)) if nocue_rule() else None   # j 版 V7：没有提示时的检测器（只看画面）

    def sync(self, f, carry=None):
        assert self.fref() is f and _DEPTH == 0, "渲染层只能在守卫之外、对自己那一场运行"
        v, put = self.v, (lambda k, x: object.__setattr__(self.v, k, x))
        s = f.state
        if self.own_atk is None and carry and carry.get("own_atk") == s[("me", "atk")]:
            self.own_atk = carry["own_atk"]           # 同一条命前一场推出过、现值没变（变了就当不知道）
        atk, hp = s[("them", "atk")], s[("them", "hp")]
        if atk != self.atk_last:
            self.atk_shown = True                     # 日志：before->after，之后画面印真值
        if hp != self.hp_last:
            self.hp_shown = True
        self.atk_last, self.hp_last = atk, hp
        if self.own_atk is None:                      # 自己的攻击：上次同步以来只出了一张攻击牌、怪血掉了 d（日志的 before->after）
            dk = {k: n - self.kinds_prev.get(k, 0) for k, n in f.fight_kinds.items() if n != self.kinds_prev.get(k, 0)}
            d = self.ehp_prev - hp
            if dk == {"attack": 1} and d > 0:
                dbl = self.double_prev and not s[("me", "double")]      # 增伤标志（自己的，印出的）被这一下用掉了
                if not dbl or d % 2 == 0:
                    self.own_atk = d // 2 if dbl else d
                    assert self.own_atk == s[("me", "atk")], (self.own_atk, s[("me", "atk")])   # 推断规则的核对（不进视图）
        if carry is not None and self.own_atk is not None:
            carry["own_atk"] = self.own_atk
        self.kinds_prev, self.ehp_prev, self.double_prev = dict(f.fight_kinds), hp, s[("me", "double")]
        cue_turns = list(v.cue_turns)
        for t, name in f.events[self.ev:]:
            if name == BOSS_SHIFT:
                cue_turns.append(t); self.kinds_cue = dict(f.fight_kinds)
                if self.nocue is not None:            # j2：真的提示来了（bytype 的同类对）→ 检测器关掉，照 i 版处理
                    self.nocue["done"] = True
        self.ev = len(f.events)
        put("cues", len(cue_turns)); put("cue_turns", cue_turns)
        key = (tuple(s[("them", p)] for p in ENEMY_STATE_SLOTS), len(f.slots_changed), len(f.seen), f.turn,
               TUNING.get("state_slots", "hidden"))
        if key != self.slot_key:
            self.slot_key = key
            put("printed_slots", cautious.them_slots(f))          # 画面上怪方状态行
        printed = v.printed_slots
        new_turn = f.turn != self.t
        if self.nocue is not None and new_turn:       # j 版 V7 (a)(b)：每回合开头看一次画面
            hit = self._nocue_detect(f.turn, printed, f.layout, f.enemy.charge_max)
            if hit is not None:
                cue_turns.append(f.turn)
                put("cues", len(cue_turns)); put("cue_turns", cue_turns); put("cue_new", frozenset(hit[1]))
        if new_turn:
            if self.t is not None:                    # 刚结算完一个回合：日志给得出的东西
                self.seq += 1
                put("settle", dict(seq=self.seq, turn=self.t, atk_rose=atk > self.atk_t0, dealt=self.hp_t0 - hp,
                                   cue=self.t in cue_turns, charge_before=self.charge_t0))
            self.t, self.atk_t0, self.hp_t0, self.refl_t0 = f.turn, atk, hp, f.reflected
        st = {k: x for k, x in s.items() if k[0] == "me" and k[1] != "atk"}
        # 自己的血、上限：画面在变过之前印 ?。开局满血（D2 入场、每条命开局都是满血），所以变之前 血 = 上限；第一次掉血那行日志的 before
        # 就是上限。决策层只拿它们算掉血量和比例，变之前掉血量恒为 0、比例恒为 1，与只知道「血 = 上限」的玩家决策相同（读码，未在规模上核实）。
        st[("me", "atk")] = self.own_atk if self.own_atk is not None else 0   # 占位 0：只被 lethal_double（模仿分支，不在本池）读到；尺子另判，见 R1v2Belief
        st[("them", "atk")] = atk if self.atk_shown else UNKNOWN
        st[("them", "hp")] = hp if self.hp_shown else math.inf    # 只被模仿分支读（core/solver.py:475-478），本池不起作用
        st[("them", "armour")] = 0
        for p in ENEMY_STATE_SLOTS:
            lab = f.layout.L("them", p)
            if lab in printed:
                x = printed[lab]
            elif p == "guard" and f.reflected > self.refl_t0:
                x = 1                                  # 本回合被反弹过：守相此刻开着（规则推出）
            elif p == "ward" and f.ward_wasted > 0:
                x = 1                                  # 打空过而封印槽从没动过：仍是起始值（>0）
            else:
                x = 0
            st[("them", p)] = x
        if new_turn:
            self.charge_t0 = st[("them", "charge")]   # 本回合开始时印出的蓄力（下一次结算记录里的 charge_before）
        put("state", st); put("own_atk_known", self.own_atk is not None)
        put("atk_start", self.atk0 if self.atk_shown else UNKNOWN)
        put("turn", f.turn); put("hand", tuple(f.pile.hand))
        put("reflected", f.reflected); put("ward_wasted", f.ward_wasted); put("mark_hits", f.mark_hits)
        fk = dict(f.fight_kinds)
        if cue_turns and _mark_restart():             # 规则（D1）：进场标记从换阶段起重新计数 → 公开的累计也从最近一次提示算（自己的出牌）
            fk = {k: n - self.kinds_cue.get(k, 0) for k, n in fk.items()}
        put("fight_kinds", fk); put("played_kinds", dict(f.played_kinds)); put("last_kinds", dict(f.last_kinds))
        put("offences", f.offences); put("last_offences", f.last_offences); put("max_hp", f.max_hp)
        return v


def _nocue_frozen_len(mech, val, charge_max):
    """V7 (b)：规则书允许一个格停在同一个数上最多几个回合；返回「停了这么多个回合就说明换了」的回合数（None = 规则上可以一直停）。"""
    if mech == "guard":
        return 4 if guardseq_rule() else 2
    if mech == "charge":
        if val >= max(1, charge_max):
            return 2
        if _ap_switch("CHARGESEQ", "none") == "len234":   # j3（第七版）：1 最多连着印 3 个回合（多停 0 / 1 / 2）→ 4 个一样 = 换了；0 不再印
            return 4 if val >= 1 else 1
        return 3 if chargeseq_rule() else 2
    if mech == "ward" and val == 0:
        return TUNING["ward_window"] + 1
    return None


def _nocue_detect(self, t, printed, layout, charge_max):
    """V7 (a)(b)：渲染层（守卫之外）只用画面：这一回合印出的怪方状态格、回合数、规则常量。返回 (哪一条, 格) 或 None。"""
    d = self.nocue
    if d["done"] or object.__getattribute__(self.v, "nocue_ack"):
        d["done"] = True
        return None
    meaning = {layout.L("them", m): m for m in ENEMY_STATE_SLOTS}
    appeared = sorted(lab for lab in printed if lab in meaning and lab not in d["seen"])
    d["seen"] |= set(printed)
    for lab, val in printed.items():
        d["hist"].setdefault(lab, []).append(val)
    hit = None
    gone = sorted(lab for lab in d.get("last", {}) if lab in meaning and lab not in printed)
    d["last"] = dict(printed)
    if gone:
        hit = ("vanish", gone)                         # j2 (d)：上一回合印着、这一回合不印了
    elif appeared and t >= 3:
        hit = ("appear", appeared)
    else:
        for lab, vals in d["hist"].items():
            if lab not in printed or lab not in meaning:
                continue
            n = _nocue_frozen_len(meaning[lab], vals[-1], charge_max)
            if n and len(vals) >= n and len(set(vals[-n:])) == 1:
                hit = ("frozen", [lab]); break
    if hit is not None:
        d["done"] = True
        NOCUE_LOG.append(dict(fight=d["fid"], turn=t, kind=hit[0], what=list(hit[1])))
    return hit


_Renderer._nocue_detect = _nocue_detect


def _mark_restart():
    m = sys.modules.get("antagonist_boss")
    return bool(m is not None and m.mark_restarts())


_VIEWS = {}


def view_for(f, carry=None):
    """这一场的公开视图（没有就建），并同步一次。必须在守卫之外调用。carry：同一条命里跨场带着的公开知识（现在只有自己的攻击）。"""
    hit = _VIEWS.get(id(f))
    if hit is not None and hit[0]() is f:
        return hit[2].sync(f, carry)
    for k in [k for k, (r, _v, _r) in _VIEWS.items() if r() is None]:
        del _VIEWS[k]
    v = object.__new__(PublicFight)
    r = _Renderer(f, v, carry)
    _VIEWS[id(f)] = (weakref.ref(f), v, r)
    return r.sync(f, carry)


def peek_view(f):
    """只给核对用：拿已有的视图，不同步。"""
    hit = _VIEWS.get(id(f))
    return hit[1] if hit is not None and hit[0]() is f else None


def _bind_belief(f, belief):
    """c2：play_fight 给这一场建的信念登记到渲染层（守卫之外；视图引用不到渲染层）。"""
    hit = _VIEWS.get(id(f))
    assert hit is not None and hit[0]() is f and _DEPTH == 0
    hit[2].belief = belief


def _belief_of(f):
    hit = _VIEWS.get(id(f))
    return hit[2].belief if hit is not None and hit[0]() is f else None


def momentum_step(est, held, attacked):
    """C2：照搬 core/adventure.py:2137-2142 的更新式，输入是自己结算时的盾和自己这回合出没出攻击。"""
    quiet = held > 0 and not (TUNING["momentum_quiet_reset"] and attacked)
    if quiet and not TUNING["momentum_resets"]:
        return max(0, est - 1)
    if quiet:
        return 0
    return min(est + 1, TUNING["momentum_cap"])


# ------------------------------------------------------------------ 候选 v3（d 版）：规则是否生效、版本钩子、全知包装
def noshield_rule():
    """这一局动量是不是「END 没举盾就罚」（规则书层面的事实：penalty_ladder 装着且 MOMENTUM_MODE == "noshield"）。没载入阶梯 = 否。"""
    pl = sys.modules.get("penalty_ladder")
    return bool(pl is not None and pl.installed() and getattr(pl, "MOMENTUM_MODE", "streak") in ("noshield", "shieldonly"))   # g 版：shieldonly 同族


def shieldonly_rule():
    """g 版：这一局动量是不是「END 只认盾，闪避不躲开」（规则书层面：penalty_ladder 装着且 MOMENTUM_MODE == "shieldonly"）。"""
    pl = sys.modules.get("penalty_ladder")
    return bool(pl is not None and pl.installed() and getattr(pl, "MOMENTUM_MODE", "streak") == "shieldonly")


def _shieldonly_switch():
    return _ap_switch("MOMENTUM", "ramp") == "shieldonly"


def guardmap_rule():
    """守势格是不是按图映射（规则书层面的事实：guard_slot 装着）。映射本身（这张图是 normal 还是 flipped）不读。"""
    gs = sys.modules.get("guard_slot")
    return bool(gs is not None and gs.installed())


def _ap_switch(name, default):
    ap = sys.modules.get("antagonist_proto")
    return getattr(ap, name, default) if ap is not None else default


def counter_rule():
    """反击是不是「同回合攻击 + 增伤，第二张出手的当下罚」（规则书层面：penalty_ladder 装着且 COUNTER_MODE == "nodouble"）。"""
    pl = sys.modules.get("penalty_ladder")
    return bool(pl is not None and pl.installed() and getattr(pl, "COUNTER_MODE", "engine") == "nodouble")


def _counter_switch():
    return _ap_switch("COUNTER", "engine") == "nodouble"


def noblock_rule():
    """h 版：反击是不是「同回合攻击 + 举盾，第二张出手的当下罚、盾作废」（规则书层面：penalty_ladder 装着且 COUNTER_MODE == "noblock"）。"""
    pl = sys.modules.get("penalty_ladder")
    return bool(pl is not None and pl.installed() and getattr(pl, "COUNTER_MODE", "engine") == "noblock")


def _noblock_switch():
    return _ap_switch("COUNTER", "engine") == "noblock"


def bossv1_rule():
    """i 版：boss 第一版的规则生效没有（开关层面：PROTO_BOSS=v1，一个进程里不变）。R1v2 懂全部规则：换阶段提示 = 敌人换了一种机制。"""
    return _ap_switch("BOSS", "none") == "v1"


def nocue_rule():
    """j 版 V7：换阶段可能没有提示（PROTO_BOSS=v1 且 PROTO_BOSS_CUE=off，或 bytype（混合对没有提示）；规则书层面，一个进程里不变）。"""
    return bossv1_rule() and _ap_switch("BOSS_CUE", "on") in ("off", "bytype")


def v7_rule():
    """j3：boss 第七版的规则（PROTO_CHARGESEQ=len234 或 PROTO_BOSS_GUARDIN=now）。"""
    return bossv1_rule() and (_ap_switch("CHARGESEQ", "none") == "len234" or _ap_switch("BOSS_GUARDIN", "quiet") == "now")


def v5_rule():
    """j2：boss 第五版的显示 / 提示规则（PROTO_BOSS_CUE=bytype 或 PROTO_BOSS_SLOTSWAP=vanish）。"""
    return bossv1_rule() and (_ap_switch("BOSS_CUE", "on") == "bytype" or _ap_switch("BOSS_SLOTSWAP", "frozen") == "vanish")


def guardseq_rule():
    """j 版 V8：boss 的守势不规则（PROTO_GUARDSEQ 不是 none：不再每 END 必翻，连着同相最多 3 个回合）。"""
    return bossv1_rule() and _ap_switch("GUARDSEQ", "none") != "none"


def chargeseq_rule():
    """j 版 V7：boss 的蓄力不规则（PROTO_CHARGESEQ 不是 none：0 / 1 时可能停一次，不连停，2 必放）。"""
    return bossv1_rule() and _ap_switch("CHARGESEQ", "none") != "none"


def boss_v4_rule():
    return nocue_rule() or guardseq_rule() or chargeseq_rule()


def v3_policy_on():
    """开关层面：R1v2 / 全知在这个进程里会不会走 v3 的代码（PROTO_MOMENTUM=noshield、PROTO_GUARDCODE=map 或 PROTO_DOUBLER=turncd）。"""
    return (_ap_switch("MOMENTUM", "ramp") in ("noshield", "shieldonly") or _ap_switch("GUARDCODE", "engine") == "map"
            or turncd_rule())


def turncd_rule():
    """增伤是不是「只对本回合生效、出过下一回合冷却」（规则书层面的事实：PROTO_DOUBLER=turncd；一个进程里不变）。"""
    return _ap_switch("DOUBLER", "persist") == "turncd"


def doubler_first(fx, c, kinds, know, avoid, piercer, attack_safe):
    """e 版 V3（PROTO_DOUBLER=turncd，三个参照共用）：c 是攻击、而出牌线在攻击之后会出增伤（不举盾）时，改成先出增伤 —— 同样两张牌、
    同样的能量，攻击翻倍；冷却下攻击之后的增伤当回合就被清掉、什么也不加（只触发冷却）。fx = 决策看到的对局（R1v2 的公开视图 / R1 的
    解码对局 / 全知的真对局），只读自己的状态、手牌、牌价。「攻击之后会出增伤」= solver.act 在攻击之后的那一步：盾在手、付得起、
    不避开、不是认出的穿透 → 先举盾（增伤本来就不出，不改）；否则走到增伤那一支（"double" in know、增伤旗没亮、增伤不避开、付得起）。
    attack_safe：这一下攻击翻倍不会翻倍任何惩罚（调用方按自己的知识定：R1v2 / R1 = 认出了、且不是守势 / 破势；全知 = 此刻不在守相、
    没封着）。其余情形原样返回 c。"""
    a, d, bl = kinds.get("attack"), kinds.get("buff_mark"), kinds.get("block")
    if c is None or a is None or d is None or c != a or not attack_safe or "double" not in know:
        return c
    s = fx.state
    if s[("me", "double")] or "buff_mark" in avoid or not fx.can_play(d):
        return c
    ca, cd = fx.deck[a].cost, fx.deck[d].cost
    if s[("me", "energy")] < ca + cd:
        return c
    if (bl is not None and bl in fx.hand and s[("me", "energy")] - ca >= fx.deck[bl].cost and "block" not in avoid
            and not piercer):
        return c
    return d


_ORACLE = {}                      # oracle v3 包装：{"act": 装之前的 solver.act, "mine": 包装}


def oracle_v3_active():
    import solver
    return bool(_ORACLE) and solver.act is _ORACLE["mine"]


def _oracle_act(f, know, kinds, information="oracle", belief=None, enrage_budget=0, offence_cap=None, avoid=()):
    """全知 v3：只改 information == "oracle" 的步，其余一律原样转给原函数。
    （1）动量 noshield 生效、这一阶段有动量（penalty_ladder.momentum_noshield(f)，读真对局 = 全知本来就读的）：本回合还没举盾、没出闪、
         原出牌线这一步也不是闪 → 先出盾（被标记的那种不出；这个池里动量那一阶段没有标记）；交给原 solver.act 的知识去掉 momentum
         （ramping / quiet_hold 是斜坡规则）。
    （2）e 版（2026-11-05）：增伤冷却（PROTO_DOUBLER=turncd）下，出牌线是「攻击、然后增伤」→ 先增伤（doubler_first；全知知道此刻是不是守相、
         封着，翻倍不会翻倍反弹）。turncd 不开时这一条一步也不走，(1) 与 2026-11-04 的包装逐字相同。"""
    nbc = bool(_V3.get("noblock") and information == "oracle" and "counter" in f.parts)   # h 版：noblock 的反击阶段（读真对局）
    if nbc:
        know = frozenset(m for m in know if m != "counter")   # 引擎原规则的「一回合只进攻一次」不适用
        avoid = frozenset(avoid) | {"block"}                  # 从不举盾：同一回合永不既攻击又举盾
        ORACLE_STATS["noblock_counter_steps"] += 1
    c = _oracle_ns(f, know, kinds, information, belief, enrage_budget, offence_cap, avoid)
    if information != "oracle" or not _V3["turncd"]:
        return c
    s = f.state
    marked = f.marked_kind() if ("mark" in know and hasattr(f, "marked_kind")) else None
    av = frozenset(avoid) | ({marked} if marked else frozenset())
    parts = f.parts
    piercer = "pierce" in know and "pierce" in parts
    safe = (not ("guard" in parts and s.get(("them", "guard"), 0) >= 1)
            and not ("ward" in parts and s.get(("them", "ward"), 0) > 0)
            and ("counter" not in parts or nbc))   # f 版：反击（任一规则下）先增伤再攻击就是第二次进攻；默认池里没有反击，旧行为不变。h 版：noblock 下攻击 + 增伤合法
    d = doubler_first(f, c, kinds, know, av, piercer, safe)
    if d != c:
        ORACLE_STATS["doubler_first"] += 1
    return d


_V3 = dict(turncd=False, counter=False, shieldonly=False, noblock=False)   # _sync_v3 按开关设（规则书层面；一个进程里不变）；shieldonly：g 版；noblock：h 版


def _oracle_ns(f, know, kinds, information, belief, enrage_budget, offence_cap, avoid):
    """（1）的那一步（2026-11-04 的 _oracle_act 原文）。"""
    orig = _ORACLE["act"]
    pl = sys.modules.get("penalty_ladder")
    if (information != "oracle" or "momentum" not in know or pl is None or not pl.installed()
            or not pl.momentum_noshield(f)):
        return orig(f, know, kinds, information=information, belief=belief, enrage_budget=enrage_budget,
                    offence_cap=offence_cap, avoid=avoid)
    kn = frozenset(m for m in know if m != "momentum")
    c = orig(f, kn, kinds, information=information, belief=belief, enrage_budget=enrage_budget, offence_cap=offence_cap, avoid=avoid)
    s = f.state
    if s[("me", "block")] > 0 or s[("me", "dodge")] or (c is not None and f.deck[c].kind == "dodge" and not pl.momentum_shieldonly(f)):
        return c                                       # g 版：shieldonly 下「正要闪」不算答上（闪避不躲开动量），换成盾
    marked = f.marked_kind() if ("mark" in know and hasattr(f, "marked_kind")) else None
    b = kinds.get("block")
    if b is None or "block" in avoid or marked == "block" or not f.can_play(b):
        return c
    ORACLE_STATS["block_first"] += c != b
    return b


_noshield_now = noshield_rule      # 信念在回合末用（每次调用读规则是否生效；一条命里不变）
_shieldonly_now = shieldonly_rule  # g 版
ORACLE_STATS = collections.Counter()   # 冒烟用：包装改了几步（block_first = 原出牌线这一步不是盾、包装换成了盾）


def install_oracle_v3():
    """幂等。solver.act 已被别人换过（不是装之前的原函数、也不是本包装）→ 报错。"""
    import solver
    cur = solver.act
    if _ORACLE and cur is _ORACLE["mine"]:
        return
    if _ORACLE:
        raise RuntimeError("solver.act 在 oracle v3 包装装着时被别人换过：不重装")
    if getattr(cur, "__module__", None) != "solver" or cur.__name__ != "act":
        raise RuntimeError(f"solver.act 已经不是 core/solver.py 的那一个（{cur!r}）：不装 oracle v3 包装")
    _ORACLE.update(act=cur, mine=_oracle_act)
    solver.act = _oracle_act


def remove_oracle_v3():
    """把 solver.act 还原成装之前的同一个对象；没装 → 什么也不做；装之后被别人换过 → 报错、不还原。"""
    import solver
    if not _ORACLE:
        return
    if solver.act is not _ORACLE["mine"]:
        raise RuntimeError("solver.act 已经不是 oracle v3 包装（装之后有别的补丁换过它）：不还原")
    solver.act = _ORACLE["act"]
    _ORACLE.clear()


def _sync_v3():
    """antagonist_proto.setup() 的 after-setup 钩子（本模块被导入时、antagonist_proto 已载入就登记；antagonist_proto.setup() 自己导入本模块）：
    按开关设版本串、装 / 撤全知的 v3 包装。v3 开关全关：VERSION = c、VERSION_B = b、包装不装（装着就撤）—— 与 c 版文件逐字同行为。"""
    global VERSION, VERSION_B
    on = v3_policy_on()
    ctr = _counter_switch()                        # f 版（候选 v3b）
    so = _shieldonly_switch()                      # g 版（18 §8.7）
    nb = _noblock_switch()                         # h 版（18 §8.8）
    VERSION = VERSION_J3 if (boss_v4_rule() and v7_rule()) else VERSION_J2 if (boss_v4_rule() and v5_rule()) else VERSION_J if boss_v4_rule() else VERSION_I if bossv1_rule() else VERSION_H if nb else VERSION_G if so else VERSION_F if ctr else VERSION_E if on else VERSION_C
    VERSION_B = (VERSION_B0 + V3BJ_SUFFIX if boss_v4_rule() else VERSION_B0 + V3BI_SUFFIX if bossv1_rule() else VERSION_B0 + V3BH_SUFFIX if nb else
                 VERSION_B0 + (V3BG_SUFFIX if so else V3B_SUFFIX if ctr else V3_SUFFIX) if (on or ctr) else VERSION_B0)
    _V3["turncd"] = turncd_rule()
    _V3["counter"] = ctr
    _V3["shieldonly"] = so
    _V3["noblock"] = nb
    (install_oracle_v3 if _ap_switch("MOMENTUM", "ramp") in ("noshield", "shieldonly") or _V3["turncd"] or ctr or nb else remove_oracle_v3)()
    (install_r1_v3 if _ap_switch("GUARDCODE", "engine") == "map" or _V3["turncd"] or ctr else remove_r1_v3)()


def oracle_v3_version():
    """全知 v3 包装此刻的版本串（f 版：nodouble 开关开着时是 ORACLE_V3B_VERSION）。"""
    return (ORACLE_V3D_VERSION if _V3["noblock"] else ORACLE_V3C_VERSION if _V3["shieldonly"] else ORACLE_V3B_VERSION if _V3["counter"]
            else ORACLE_V3_VERSION)


def r1_v3_version():
    return R1_V3B_VERSION if _V3["counter"] else R1_V3_VERSION


def _register_v3_hook():
    ap = sys.modules.get("antagonist_proto")
    if ap is not None and hasattr(ap, "register_after_setup"):
        ap.register_after_setup("r1v2_v3", _sync_v3)
        return True
    return False


_register_v3_hook()


# ------------------------------------------------------------------ e 版：R1（core/cautious.py v1，一行不改）的 v3 包装
# 审查（2026-11-05，v3 build 的独立审查 review_1 / review_2）：R1 认出守势怪之后把 "guard" 交给 solver.act，而 act 读的是真对局的
# f.state[("them", "guard")]（引擎相位）。v3 之前印出的值就是引擎值，所以这是公开的；PROTO_GUARDCODE=map 下不是（实测 24/24 条守势图命 0 次反弹）。
# spec 18 §7.2：参照只用公开信息、升版本、存旧版。core/ 不改 → 在这里给 cautious.Cautious.act 换一个包装（运行时补丁，install / remove 还原同一个对象）：
#   · 只对真对局生效（R1v2 的决策层交来的是公开视图 PublicFight，视图里的守势格已由 R1v2 自己解码 → 原样转给原函数）；
#   · 守势格按图映射（guard_slot 装着 = 规则书层面的事实）：R1 用与 R1v2 d 版 V1 同一套公开证据解码（自己出过的攻击被不被反弹 = 那一回合的
#     相位；守相每个 END 必翻；印出的数 → 这张图「守相印几」；地图 / boss 各一张；换阶段提示（日志 "The enemy has changed."）后相位证据清掉），
#     认出映射之前把印出的守势格当攻相（那一次攻击就是安全的试探）；解出的值只交给 solver.act（_GuardDecoded：只换这一格，其余原样转给真对局）；
#   · 增伤冷却（PROTO_DOUBLER=turncd）：doubler_first（认出了、且不是守势 / 破势时）。
#   其余逐行同 core/cautious.py 的 Cautious.act（v1 原文照抄：观察、设防、避标记、开局先防、safe 的补救）。两条都不生效（包装装着、规则都没开）
#   时与原函数逐张相同（e 版核对的 X0）。版本 R1_V3_VERSION，antagonist_proto.references() 在包装装着时记 r1_v3。
_R1 = {}                          # {"act": 装之前的 Cautious.act, "mine": 包装}
R1_STATS = collections.Counter()  # 冒烟用：decoded（解码过的决策）、probe_unknown（映射未知时按攻相出攻击的决策）、doubler_first
R1_COUNTERPROOF = None            # 核对的反证（默认 None）："engine" = 解码换成引擎真值（= 修之前的读法）；"invert" = 反过来解码；"off" = 不解码


class _StateOverlay:
    """真对局的 state，只把给定的键换成给定的值（读）；写入报错。"""
    __slots__ = ("_d", "_o")

    def __init__(self, d, over):
        self._d, self._o = d, over

    def __getitem__(self, k):
        return self._o[k] if k in self._o else self._d[k]

    def get(self, k, default=None):
        return self._o[k] if k in self._o else self._d.get(k, default)

    def __contains__(self, k):
        return k in self._o or k in self._d

    def __setitem__(self, k, v):
        raise RuntimeError(f"R1 v3: solver.act wrote state[{k!r}] through the decoded view")


class _GuardDecoded:
    """交给 solver.act 的对局：state 里怪方守势那一格换成 R1 解出的值（引擎含义：1 = 守相），其余属性原样转给真对局。"""
    __slots__ = ("_f", "state")

    def __init__(self, f, x):
        object.__setattr__(self, "_f", f)
        object.__setattr__(self, "state", _StateOverlay(f.state, {("them", "guard"): x}))

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_f"), name)


def _cue_count(f):
    return sum(1 for _t, name in f.events if name == BOSS_SHIFT)     # 日志上的换阶段提示（参与者看得到的那一行）


def _r1_guard_decode(self, f):
    """R1 在真对局 f 上的守势格解码（公开证据：画面上印出的守势格、自己的出牌计数 fight_kinds、反弹计数 reflected、日志的换阶段提示、回合数）。
    返回交给 solver.act 的引擎含义（1 = 守相）。状态放在策略实例的 __dict__ 里（v1 的 Cautious 没有这个字段）。"""
    gm = self.__dict__.setdefault("_r1v3", dict(code={}, fights={}, learned=[], conflicts=0))
    lab = f.layout.L("them", "guard")
    g = gm["fights"].get(id(f))
    if g is None or g["f"]() is not f:
        g = gm["fights"][id(f)] = dict(f=weakref.ref(f), cues=_cue_count(f), last=None, ev={}, pr={}, refl0=f.reflected, t=None,
                                       refl_t0=f.reflected)
    t, att, refl, cues = f.turn, f.fight_kinds.get("attack", 0), f.reflected, _cue_count(f)
    if cues != g["cues"]:                              # 换阶段：相位证据属于旧阶段，清掉（映射不清）
        g.update(cues=cues, last=None, ev={}, pr={}, refl0=refl)
    if g["t"] != t:
        g["t"], g["refl_t0"] = t, refl
    last = g["last"]
    if last is not None:
        lt, la, lr = last
        if att > la:                                   # 上次决策以来出过攻击（属于上次决策那一回合：新回合的第一次决策在任何牌之前）
            g["ev"][lt] = 1 if (refl > lr or g["ev"].get(lt) == 1) else 0
    g["last"] = (t, att, refl)
    p = cautious.them_slots(f).get(lab)
    if p is not None:
        g["pr"][t] = p
    code = gm["code"].get(f.is_boss)
    for u, su in g["ev"].items():
        for w, pw in g["pr"].items():
            cw = pw if (su ^ ((w - u) % 2)) == 1 else 1 - pw
            if code is None:
                code = gm["code"][f.is_boss] = cw
                gm["learned"].append(dict(is_boss=bool(f.is_boss), turn=t, code=cw))
            elif cw != code:
                gm["conflicts"] += 1
    if p is not None:
        if code is None:
            x = 0                                      # 认出映射之前：当攻相（出一次攻击 = 那一次试探）
            R1_STATS["probe_unknown"] += 1
        else:
            x = 1 if p == code else 0
    else:
        x = 1 if refl > g["refl_t0"] else 0            # 没印（第 1 回合等）：本回合被反弹过 = 守相
        if g["pr"] or refl > g["refl0"]:
            for u, su in g["ev"].items():
                x = su ^ ((t - u) % 2)
                break
    R1_STATS["decoded"] += 1
    if R1_COUNTERPROOF == "engine":
        x = f.state[("them", "guard")]
    elif R1_COUNTERPROOF == "invert":
        x = 1 - x
    return x


def _r1_act(self, f, know, kinds, belief=None, information="observable"):
    """R1 的 v3 包装（见本节说明）。PublicFight（R1v2 的决策层）→ 原函数。"""
    if isinstance(f, PublicFight):
        return _R1["act"](self, f, know, kinds, belief=belief, information=information)
    st, code = self._observe(f, belief)
    if belief is not None and getattr(belief, "atk0", 0) is None:
        belief.atk0 = f.state[("them", "atk")]
    guard_counter, guard_pierce = self._guards()
    b = belief
    if not st.types and belief is not None and (guard_counter or guard_pierce):
        b = cautious._Hedged(belief, belief.pierce or guard_pierce, belief.counter or guard_counter)
    know = frozenset(know) - {"mark"} - ({"guard", "ward"} - st.types)
    mark_avoid = self._avoid(code)
    open_avoid = (frozenset({"attack", "buff_mark"})
                  if self._defend_opening() and not st.types and f.turn == st.first_turn else frozenset())
    extra = self._extra_avoid(f)
    fx = f
    if guardmap_rule() and R1_COUNTERPROOF != "off":
        # 每只怪都解码（不先问 guard_slot.has_guard：那读的是怪的机制，是隐藏的）。没有守势的怪：守势格从不印、从不反弹 → 解出 0 = 引擎值
        fx = _GuardDecoded(f, _r1_guard_decode(self, f))
    c = solver.act(fx, know, kinds, information=information, belief=b, avoid=mark_avoid | open_avoid | extra)
    if (c is None and code and mark_avoid and self.mark_rule == "safe"
            and solver.act(fx, know, kinds, information=information, belief=b, avoid=open_avoid | extra) is not None):
        p = self.posterior()[code]
        playable = [k for k in reversed(cautious.KINDS) if k in kinds and k not in open_avoid | extra and f.can_play(kinds[k])]
        if playable:
            c = kinds[min(playable, key=lambda k: p[k])]
    if _V3["turncd"]:
        piercer = "pierce" in know and b is not None and getattr(b, "pierce", False)
        safe = bool(st.types) and not (st.types & {"guard", "ward", "counter"})
        d = doubler_first(fx, c, kinds, know, mark_avoid | open_avoid | extra, piercer, safe)
        if d != c:
            R1_STATS["doubler_first"] += 1
        c = d
    if _V3["counter"] and c is not None:          # f 版 V4：出牌前的快照（公开：自己的血、反弹计数、回合），交给 observe_play 的包装认反击
        _R1_SNAP[id(f)] = (weakref.ref(f), f.turn, f.state[("me", "hp")], f.reflected)
    return c


CTR_COUNTERPROOF = None           # f 版 V4 的反证（核对用，默认 None）："ignore_reflect" = 识别时不看反弹数（守相反弹会被误认成反击）
_R1_SNAP = {}                     # f 版 V4：id(真对局) → (弱引用, 回合, 出牌前的血, 出牌前的反弹数)；只有 R1 的包装写


def _r1_observe_play(self, f, atk_before, kind):
    """f 版 V4（R1）：cautious.PublicBelief.observe_play 的包装（只在 R1 v3 包装装着、nodouble 开关开着时装）。原函数什么也不认；这里只认反击：
    这一张是攻击 / 增伤、这一回合两种都出过、出牌前（R1 包装记下的快照，同一回合）以来自己的血掉了、反弹数没涨 → belief.counter。"""
    _R1["observe_play"](self, f, atk_before, kind)
    snap = _R1_SNAP.pop(id(f), None)
    if snap is None or snap[0]() is not f or not counter_rule():
        return
    _r, turn, hp0, refl0 = snap
    pk = f.played_kinds
    if (kind in ("attack", "buff_mark") and pk.get("attack", 0) >= 1 and pk.get("buff_mark", 0) >= 1 and f.turn == turn
            and f.state[("me", "hp")] < hp0 and (f.reflected == refl0 or CTR_COUNTERPROOF == "ignore_reflect")):
        self.counter = True
        R1_STATS["counter_identified"] += 1


def r1_v3_active():
    return bool(_R1) and cautious.Cautious.__dict__.get("act") is _R1["mine"]


def install_r1_v3():
    """幂等。Cautious.act 已被别人换过（不是 core/cautious.py 的那一个、也不是本包装）→ 报错。"""
    cur = cautious.Cautious.__dict__["act"]
    if _R1 and cur is _R1["mine"]:
        return
    if _R1:
        raise RuntimeError("cautious.Cautious.act 在 R1 v3 包装装着时被别人换过：不重装")
    code = getattr(cur, "__code__", None)
    if code is None or pathlib.Path(code.co_filename).resolve() != (ROOT / "core" / "cautious.py").resolve() or code.co_name != "act":
        raise RuntimeError(f"cautious.Cautious.act 已经不是 core/cautious.py 的那一个（{cur!r}）：不装 R1 v3 包装")
    _R1.update(act=cur, mine=_r1_act)
    cautious.Cautious.act = _r1_act
    if _counter_switch():                          # f 版 V4：R1 的反击识别（PublicBelief.observe_play 的包装；R1v2Belief 自己覆盖它）
        _R1.update(observe_play=cautious.PublicBelief.__dict__["observe_play"], obs_mine=_r1_observe_play)
        cautious.PublicBelief.observe_play = _r1_observe_play


def remove_r1_v3():
    """把 Cautious.act 还原成装之前的同一个对象；没装 → 什么也不做；装之后被别人换过 → 报错、不还原。"""
    if not _R1:
        return
    if cautious.Cautious.__dict__.get("act") is not _R1["mine"]:
        raise RuntimeError("cautious.Cautious.act 已经不是 R1 v3 包装（装之后有别的补丁换过它）：不还原")
    if "obs_mine" in _R1 and cautious.PublicBelief.__dict__.get("observe_play") is not _R1["obs_mine"]:
        raise RuntimeError("cautious.PublicBelief.observe_play 已经不是 R1 v3 包装（装之后有别的补丁换过它）：不还原")
    cautious.Cautious.act = _R1["act"]
    if "obs_mine" in _R1:
        cautious.PublicBelief.observe_play = _R1["observe_play"]
    _R1.clear()
    _R1_SNAP.clear()


# ------------------------------------------------------------------ C6（c 版）：自动治疗不挤掉本回合的第一张牌
def energy_heal_veto(act_fn, base=None, heal_kind="heal"):
    """规格 §3 C6，做成与策略无关的工厂。返回 veto(f)：为真 = 这一刻不出路线的自动治疗（solver.play_fight 的 heal_veto）。
    act_fn(f) -> 这一刻如果不治疗、玩家自己的策略会出的牌名（None = 什么都不出）。
    规则：base（原有的否决，例如 v1 的标记避牌）先判，它否决就否决；本回合已出过任何非治疗牌 → 不否决；
          c = act_fn(f)；c 存在、不是治疗、且 能量 − 治疗的牌价 < c 的牌价 → 否决。
    只读 f.state[("me","energy")]、f.played_kinds、f.deck[*].kind / .cost、f.turn 和 act_fn 的回答：交 PublicFight 就只读公开量
    （牌价是规则书的），交真对局（oracle）就读真牌价——oracle 本来就读全部状态，这个否决不给它新信息。
    veto.stats：calls、base（base 否决）、after_first（本回合已出过非治疗牌而放行）、checked（问过策略）、vetoed；
    veto.log：每次否决的 dict(turn, card, kind, energy, heals_this_turn)。"""
    stats = dict(calls=0, base=0, after_first=0, checked=0, vetoed=0)
    log = []

    def veto(f):
        stats["calls"] += 1
        if base is not None and base(f):
            stats["base"] += 1
            return True
        if any(n and k != heal_kind for k, n in f.played_kinds.items()):
            stats["after_first"] += 1                  # 第一张已经出了：之后的自动治疗是路线原本的习惯，不碰
            return False
        stats["checked"] += 1
        c = act_fn(f)
        if c is None:
            return False
        card = f.deck[c]
        if card.kind == heal_kind:
            return False                               # 策略自己也要治疗
        heal_cost = {x.cost for x in f.deck.values() if x.kind == heal_kind}
        assert len(heal_cost) == 1, heal_cost          # 每种牌一个价（规则书）；play_fight 出的是 kinds["heal"]
        if f.state[("me", "energy")] - heal_cost.pop() < card.cost:
            stats["vetoed"] += 1
            log.append(dict(turn=f.turn, card=c, kind=card.kind, energy=f.state[("me", "energy")], heals_this_turn=f.played_kinds.get(heal_kind, 0)))
            return True
        return False
    veto.stats, veto.log = stats, log
    return veto


def oracle_heal_veto(know, kinds, enrage_budget=0, offence_cap=None, dodge_hand=False):
    """oracle 用的 C6（诊断参照的改动，不属于 R1v2；规格 §3 C6「范围」）。act_fn = play_fight 对 oracle 会走的同一个选择：
    dodge_hand 时先 grabs_dodge，否则 solver.act(..., information="oracle")（oracle 下 solver.act 不读信念：信念只出现在 information == "observable" 的分支里，core/solver.py:401-488）。
    用法：solver.play_fight(run, f, know, kinds, route.heal_at, information="oracle", enrage_budget=route.enrage_budget,
                            heal_veto=oracle_heal_veto(know, kinds, route.enrage_budget))；调用方要在输出里记下用了它。"""
    def act_fn(f):
        if dodge_hand and solver.grabs_dodge(f, kinds):
            return kinds["dodge"]
        return solver.act(f, know, kinds, information="oracle", enrage_budget=enrage_budget, offence_cap=offence_cap)
    return energy_heal_veto(act_fn)


# ------------------------------------------------------------------ 信念
FLAGS = ("pierce", "counter", "momentum", "enrage", "mimic")


@dataclass
class R1v2Belief(cautious.PublicBelief):
    """v1 的 PublicBelief + C1（公开动量识别）+ C3（提示撤回）。所有判断只读 PublicFight，在守卫里做。"""
    cues: int = 0
    withdrawn: tuple = ()        # 撤回过的标志（按次序）
    momentum_turn: int = None    # 第一次认出动量的结算回合（只给报告用）
    settles: int = 0
    no_ruler: int = 0            # 没有公开尺子的结算次数（没披露的怪攻、没有干净挨打、自己的攻击还没从日志推出）
    ruler_skips: int = 0         # 其中 v1 会凭自己攻击的真值立穿透 / 反击标志、v2 不立的次数

    def __post_init__(self):
        # play_fight 在 marks 开着时会读 f.parts 给信念预置身份（core/solver.py:1036-1051）；R1 的画面必须是 R1_DISPLAY
        assert TUNING["marks"] == 0 and TUNING.get("state_slots") == "seen", "R1v2 要在 display() 下跑"

    def _take_cues(self, v):
        if v.cues > self.cues:
            self.withdrawn += tuple(m for m in FLAGS if getattr(self, m))
            for m in FLAGS:
                setattr(self, m, False)
            v.momentum = 0                             # 引擎在换阶段时把动量计数清零（core/adventure.py:1568-1575）
            self.cues = v.cues

    def observe_events(self, f):
        v = view_for(f)
        _bind_belief(f, self)                          # c2：play_fight 每回合开头、在任何治疗检查之前调这里
        with _guard():
            if self.atk0 is None:
                self.atk0 = v.atk_start
            self._take_cues(v)
            if counter_rule() or noblock_rule():       # f 版 V4：回合开头的快照（自己的血、反弹数）；h 版 V5 同
                self.__dict__["_ctr_snap"] = (v.turn, v.state[("me", "hp")], v.reflected)

    def observe_play(self, f, atk_before, kind):
        v = view_for(f)                                # 只同步（日志按每张牌写）；v1 这里什么都不认
        if counter_rule():                             # f 版 V4：反击按当下那一下认（只读视图：自己的出牌、血、反弹数）
            with _guard():
                self._ctr_check(v, kind)
        elif noblock_rule():                           # h 版 V5：攻击 + 盾，第二张出手的当下自己的血掉了、反弹数没涨 → 反击
            with _guard():
                self._ctr_check(v, kind, pair=("attack", "block"))

    def _ctr_check(self, v, kind, pair=("attack", "buff_mark")):
        snap = self.__dict__.get("_ctr_snap")
        hp, refl, pk = v.state[("me", "hp")], v.reflected, v.played_kinds
        if (snap is not None and snap[0] == v.turn and kind in pair and pk.get(pair[0], 0) >= 1
                and pk.get(pair[1], 0) >= 1 and hp < snap[1] and (refl == snap[2] or CTR_COUNTERPROOF == "ignore_reflect")):
            self.counter = True
            self.__dict__["_ctr_hits"] = self.__dict__.get("_ctr_hits", 0) + 1
        self.__dict__["_ctr_snap"] = (v.turn, hp, refl)

    def observe_end_turn(self, f, hp_before, block_before, poison_before, charge_before=0,
                         atk_before=None, played_non_attack=False):
        v = view_for(f)
        with _guard():
            r = v.settle
            if r is None or r["seq"] == self.settles:
                return                                 # 没有新的结算（怪死在本回合，end_turn 直接返回）：对局已结束
            self.settles = r["seq"]
            self.atk0 = v.atk_start                    # H3：开局值随第一次变化披露
            charge0 = r["charge_before"]               # H7：回合开始时印出的蓄力
            atk = v.state[("them", "atk")]
            visible = atk if (self.atk0 is not None and atk != self.atk0) else None
            no_ruler = visible is None and not self.clean_hit and not v.own_atk_known   # v1 此时拿自己攻击的真值当尺子（core/cautious.py:97）
            keep = (self.pierce, self.counter)
            cautious.PublicBelief.observe_end_turn(self, v, hp_before, block_before, poison_before, charge0)
            if no_ruler:                               # D5：没有公开的尺子就不凭它立标志（clean_hit、worst 照记）
                self.no_ruler += 1
                if (self.pierce, self.counter) != keep:
                    self.pierce, self.counter = keep; self.ruler_skips += 1
            if self.counter != keep[1] and noblock_rule():   # h 版 V5：回合末的 v1 反击证据（进攻 >= 2）在 noblock 下不是证据
                self.counter = keep[1]
                self.__dict__["_nb_end_counter_skips"] = self.__dict__.get("_nb_end_counter_skips", 0) + 1
            if (charge0 < max(1, v.enemy.charge_max) and not r["cue"] and not played_non_attack
                    and block_before <= 0 and r["atk_rose"] and r["dealt"] > 0):          # C1 (a)-(f)
                if not self.momentum and self.momentum_turn is None:
                    self.momentum_turn = r["turn"]
                self.momentum = True
            if _noshield_now():
                self._c1n(v, r, hp_before, block_before, poison_before, charge0)   # d 版 V2（只在 noshield 规则生效时）
            v.momentum = momentum_step(v.momentum, block_before, v.last_kinds.get("attack", 0) > 0)   # C2
            self._take_cues(v)                         # C3：换阶段那次结算的证据属于旧机制，一并撤回

    def _c1n(self, v, r, hp_before, block_before, poison_before, charge0):
        """d 版 V2 的识别（C1n，见模块说明）。尺子（这一场的普通一击）：印出的攻击 > 举盾挨打的 掉血 + 盾 > 举盾没掉血的上界（<= 盾）。
        状态放在实例的 __dict__ 里（不是 dataclass 字段：v3 关时信念对象逐字同 c 版）。"""
        d = self.__dict__
        exact, hi = d.get("_atk_exact"), d.get("_atk_hi")
        atk = v.state[("them", "atk")]
        if atk is not UNKNOWN:
            exact = atk                                # noshield 下动量加成恒 0：印出的攻击 = 普通一击
        dodged = v.last_kinds.get("dodge", 0) >= 1 and not _shieldonly_now()   # g 版：shieldonly 下闪掉的 END 也是证据（闪不躲开动量）
        big = charge0 >= max(1, v.enemy.charge_max)
        if not (r["cue"] or dodged or big):
            loss = min(hp_before - poison_before, v.max_hp) - v.state[("me", "hp")]
            if block_before > 0:
                if loss > 0:
                    exact = loss + block_before        # 举着盾：只挨普通一击，盾先吸收
                else:
                    hi = block_before if hi is None else min(hi, block_before)
            elif loss > 0:
                d["_c1n_bare"] = d.get("_c1n_bare", 0) + 1
                punished = (loss >= 2 * exact) if exact is not None else (hi is not None and loss > hi)
                if punished:
                    d["_c1n_hits"] = d.get("_c1n_hits", 0) + 1
                    if not self.momentum and self.momentum_turn is None:
                        self.momentum_turn = r["turn"]
                    self.momentum = True
        d["_atk_exact"], d["_atk_hi"] = exact, hi


# ------------------------------------------------------------------ 出牌
class R1v2Policy(cautious.Cautious):
    """v1 的 Cautious，决策层只看 PublicFight（C4），_observe 加 C1b、C3。每条命新建一个。"""
    version = VERSION

    def __init__(self, variant=VARIANT, guard=None, energy_veto=None):
        super().__init__(variant)
        self.guard = GUARD if guard is None else guard
        self.energy_veto = ENERGY_VETO if energy_veto is None else bool(energy_veto)
        self.version = VERSION if self.energy_veto else VERSION_B
        self.withdrawals = []                          # (回合, 撤回的已认出机制)；每次处理提示记一条，撤回的可以是空
        self.carry = {}                                # 同一条命里跨场的公开知识（自己的攻击，从日志推出后）
        self._ctx = None                               # 最近一次 act 收到的 (know, kinds)：C6 问「这一刻出哪张」时用同一份
        self._veto_belief = None                       # C6 判断期间：这一场的信念（守卫之外从渲染层取出）
        self._protect = None                           # C6 刚否决时被保护的牌名（下一次 act 核对它是不是真的出了）
        self.veto_kept = self.veto_changed = 0
        self._energy = energy_heal_veto(self._intended, base=lambda v: cautious.Cautious.heal_veto(self, v))
        self.veto_stats, self.energy_vetoes = self._energy.stats, self._energy.log
        # d 版（候选 v3）：这条命里 v3 的规则生效没有（规则书层面，开局定一次；见模块说明 V1 / V2）。都不生效时下面的代码一步也不走。
        self.noshield, self.guardmap = noshield_rule(), guardmap_rule()
        self.turncd = turncd_rule()                    # e 版 V3（PROTO_DOUBLER=turncd）
        self.nodouble = counter_rule()                 # f 版 V4（PROTO_COUNTER=nodouble）
        self.shieldonly = shieldonly_rule()            # g 版 V2g（PROTO_MOMENTUM=shieldonly）
        self.noblock = noblock_rule()                  # h 版 V5（PROTO_COUNTER=noblock）
        self.reopen = bossv1_rule()                    # i 版 V6（PROTO_BOSS=v1）：换阶段提示之后重新开场
        self.nocue, self.guardseq = nocue_rule(), guardseq_rule()   # j 版 V7 / V8（都不开时一步也不走）
        if self.reopen and (self.nocue or self.guardseq or chargeseq_rule()):
            self.version = ((VERSION_J3 if v7_rule() else VERSION_J2 if v5_rule() else VERSION_J) if self.energy_veto else VERSION_B0 + V3BJ_SUFFIX)
        elif self.reopen:
            self.version = (VERSION_I if self.energy_veto else VERSION_B0 + V3BI_SUFFIX)
        elif self.noblock:
            self.version = (VERSION_H if self.energy_veto else VERSION_B0 + V3BH_SUFFIX)
        elif self.shieldonly:
            self.version = (VERSION_G if self.energy_veto else VERSION_B0 + V3BG_SUFFIX)
        elif self.nodouble:
            self.version = (VERSION_F if self.energy_veto else VERSION_B0 + V3B_SUFFIX)
        elif self.noshield or self.guardmap or self.turncd:
            self.version = (VERSION_E if self.energy_veto else VERSION_B0 + V3_SUFFIX)
        self.gcode = {}                                # V1：{is_boss: 守相印的数（0 / 1）}，认出之后不变
        self._gf = {}                                  # V1：每场的相位证据 id(视图) → [视图, 记录]
        self.v3 = collections.Counter()                # d 版的计数（冒烟 / 报告用；不影响出牌）
        self.guard_learned = []                        # V1：每次认出映射 dict(is_boss, turn, code, how)
        self.guard_last = None                         # V1：最近一次解码 (id(视图), 回合, 印出的数, 解码, 映射已知)（冒烟对照真值用）

    def _g(self):
        return hidden_access_guard() if self.guard else contextlib.nullcontext()

    def act(self, f, know, kinds, belief=None, information="observable"):
        assert information == "observable"
        self._ctx = (know, kinds)
        v = view_for(f, self.carry)
        with self._g():
            self._v3_prep(v)
            c = self._decide(v, know, kinds, belief)
        if self._protect is not None:                  # C6 刚否决过：同一状态下策略应出同一张（核对，不改出牌）
            kept = c == self._protect
            self.veto_kept += kept; self.veto_changed += not kept; self._protect = None
        return c

    def _intended(self, v):
        """C6 第 3 步：这一刻如果不治疗，策略会出哪张（同一视图、同一信念、同一知识与牌名；在守卫里被调用）。"""
        if self._ctx is not None:
            kn, kinds = self._ctx
        else:                                          # 这条命还没调过 act：知识同 know()，牌名同 run.by_kind 的构造（core/adventure.py:3151）
            kn, kinds = know(), {c.kind: n for n, c in v.deck.items()}
        return self._decide(v, kn, kinds, self._veto_belief)

    # ---------------------------------------------------------------- d 版（候选 v3）
    def _decide(self, v, know, kinds, belief):
        """这一刻出哪张（act 与 C6 的 _intended 同一条路）。v3 规则不生效 = c 版原样的 Cautious.act。e 版：turncd 下再过一道 _dfirst。"""
        if self.noblock:                               # h 版 V5：solver.act 的「认出反击 → 一回合只进攻一次」是引擎原规则，noblock 下不交给它
            know = frozenset(m for m in know if m != "counter")
        c = self._decide_d(v, know, kinds, belief)
        return self._dfirst(v, c, know, kinds, belief) if self.turncd else c

    def _dfirst(self, v, c, know, kinds, belief):
        """e 版 V3：doubler_first，知识 / 避牌同 Cautious.act 交给 solver.act 的那一份（在守卫里，只读视图）。翻倍安全 = 这只怪认出了、且不是守势 / 破势。"""
        st = self._st(v)
        mode = TUNING.get("state_slots", "hidden")
        code = v.state.get(("them", "mark"), 0) if mode != "hidden" else 0
        kn = frozenset(know) - {"mark"} - ({"guard", "ward"} - st.types)
        if self.noshield:
            kn = kn - {"momentum"}
        guard_counter, guard_pierce = self._guards()
        piercer = "pierce" in kn and ((belief is not None and getattr(belief, "pierce", False)) or (not st.types and guard_pierce))
        safe = bool(st.types) and not (st.types & ({"guard", "ward"} if self.noblock else {"guard", "ward", "counter"}))   # f 版：认出的反击也不先出增伤（h 版：noblock 下攻击 + 增伤合法）
        d = doubler_first(v, c, kinds, kn, self._avoid(code) | self._extra_avoid(v), piercer, safe)
        if d != c:
            self.v3["doubler_first"] += 1
        return d

    def _guards(self):
        """f 版 V4：nodouble 下没认出机制之前设防反击（一回合只进攻一次：攻击和增伤不同回合）；不开 nodouble 时同 v1。
        h 版 V5：noblock 下不设防反击（引擎原规则的「一回合只进攻一次」不是 noblock 的答案；试探就是「攻击 + 盾」那一回合）。"""
        gc, gp = cautious.Cautious._guards(self)
        if getattr(self, "noblock", False):
            return (False, gp)
        return (True, gp) if getattr(self, "nodouble", False) else (gc, gp)

    def _extra_avoid(self, f):
        """h 版 V5：noblock 下认出反击的那一场从不举盾（同一回合永不既攻击又举盾；攻击 + 增伤照出）。别的情形同 v1（空）。"""
        base = cautious.Cautious._extra_avoid(self, f)
        if getattr(self, "noblock", False) and "counter" in self._st(f).types:
            self.v3["noblock_no_block_steps"] += 1
            return base | frozenset({"block"})
        return base

    def _decide_d(self, v, know, kinds, belief):
        """d 版的 _decide（原文）。"""
        if not self.noshield:
            return cautious.Cautious.act(self, v, know, kinds, belief=belief, information="observable")
        kn = frozenset(m for m in know if m != "momentum")   # V2：solver.act 的 ramping / quiet_hold 是斜坡规则
        c = cautious.Cautious.act(self, v, kn, kinds, belief=belief, information="observable")
        st = self._st(v)
        if st.types and "momentum" not in st.types:
            return c                                   # 认出是别的机制：不设防
        if v.state[("me", "block")] > 0 or v.state[("me", "dodge")] or (c is not None and v.deck[c].kind == "dodge" and not self.shieldonly):
            return c                                   # 已经举着盾 / 出了闪 / 正要闪：这一 END 不会被罚（g 版：shieldonly 下「正要闪」不算，换成盾）
        b = kinds.get("block")
        if b is None or not v.can_play(b):
            return c
        if c != b:
            self.v3["hedge_block_first"] += 1
        return b

    def _gfight(self, v):
        g = self._gf.get(id(v))
        if g is None or g[0] is not v:
            g = self._gf[id(v)] = [v, dict(cues=v.cues, last=None, ev={}, pr={}, refl0=v.reflected)]
        return g[1]

    def _v3_prep(self, v):
        """V1：在决策层自己的那份视图状态里，把守势格印出的数解码成引擎含义（1 = 守相）。规则不生效 → 什么也不做。在守卫里调。"""
        if not self.guardmap:
            return
        lab = v.layout.L("them", "guard")
        g = self._gfight(v)
        t, att, refl = v.turn, v.fight_kinds.get("attack", 0), v.reflected
        if v.cues != g["cues"]:                        # 换阶段：相位证据属于旧阶段，清掉（映射不清）
            g.update(cues=v.cues, last=None, ev={}, pr={}, refl0=refl)
        last = g["last"]
        if last is not None:
            lt, la, lr = last
            if att > la:                               # 上次观察以来出过攻击（都属于上次观察那一回合：新回合的第一次观察在任何牌之前）
                g["ev"][lt] = 1 if (refl > lr or g["ev"].get(lt) == 1) else 0
        g["last"] = (t, att, refl)
        p = v.printed_slots.get(lab)
        if p is not None:
            g["pr"][t] = p
        code = self.gcode.get(v.is_boss)
        for u, su in g["ev"].items():                  # 相位证据 + 印出的数 → 映射；已知时只核对一致（不一致计数，不改）
            for w, pw in g["pr"].items():
                if getattr(self, "guardseq", False) and w != u:
                    continue                           # j 版 V8：守势不规则 → 只用同一回合的相位证据和印出的数
                cw = pw if (su ^ ((w - u) % 2)) == 1 else 1 - pw
                if code is None:
                    code = self.gcode[v.is_boss] = cw
                    self.guard_learned.append(dict(is_boss=bool(v.is_boss), turn=t, code=cw,
                                                   how="probe" if u == t or u == t - 1 else "history"))
                elif cw != code:
                    self.v3["guard_code_conflict"] += 1
        if p is not None:
            if code is None:
                x = 0                                  # 认出映射之前：当攻相，出一次攻击就是那一次试探
                self.v3["guard_unknown_decisions"] += 1
            else:
                x = 1 if p == code else 0
        else:
            x = v.state.get(("them", "guard"), 0)      # 没印（第 1 回合等）：渲染层的规则推断（本回合被反弹过 = 守相）
            if (g["pr"] or refl > g["refl0"]) and not getattr(self, "guardseq", False):   # j 版 V8：不规则下不按周期推
                for u, su in g["ev"].items():
                    x = su ^ ((t - u) % 2)             # 这一段里知道某回合的相位 → 按每 END 必翻推到本回合
                    break
        v.state[("them", "guard")] = x
        self.guard_last = (id(v), t, p, x, code is not None)

    def heal_veto(self, f):
        v = view_for(f, self.carry)
        if not self.energy_veto:
            with self._g():
                self._v3_prep(v)
                return cautious.Cautious.heal_veto(self, v)           # b 版原样
        b = _belief_of(f)
        assert b is not None, "C6 要经 solver.play_fight 的回合循环：R1v2Belief.observe_events 每回合开头登记信念"
        n0 = self._energy.stats["vetoed"]
        self._veto_belief = b
        try:
            with self._g():
                self._v3_prep(v)
                out = self._energy(v)
        finally:
            self._veto_belief = None
        if self._energy.stats["vetoed"] > n0:
            self._protect = self._energy.log[-1]["card"]
        return out

    def _st(self, f):
        st = super()._st(f)
        if not hasattr(st, "cues"):
            st.cues, st.last, st.moved = 0, None, set()
        return st

    def _observe(self, f, belief):
        """v1 core/cautious.py:193-224 逐行照抄，改动只有标 v2 的三处。f 是 PublicFight。"""
        st = self._st(f)
        if f.cues != st.cues:                          # v2 C3：提示 → 撤回这一场的身份判断；槽位证据从这里重新开始
            st.cues = f.cues
            self.withdrawals.append((f.turn, tuple(sorted(st.types))))
            st.types, st.identified_turn = set(), None
            if getattr(self, "reopen", False):         # i 版 V6（PROTO_BOSS=v1）：提示之后的第一回合 = 新的开场（v1 变体的 defend 开场：只举盾，
                st.first_turn = f.turn                 # 不出攻击、增伤），之后同开场的认法（槽位类第二回合起显形；无槽位的「举盾 + 攻击」试探）
                self.v3["reopen_after_cue"] += 1
            st.last, st.moved = dict(f.printed_slots), set()
            if getattr(self, "nocue", False):          # j 版 V7 (a)：新出现的那一格当成「变过」（当场认）
                for lab in f.cue_new:
                    st.last.pop(lab, None)
            st.poison0 = f.state[("me", "poison")]
            st.kinds_seen = dict(f.fight_kinds)        # mark_restarts() 下视图的累计从提示起重算；基线跟着换，增量不丢
        prev_types = set(st.types)
        mode = TUNING.get("state_slots", "hidden")
        code = f.state.get(("them", "mark"), 0) if mode != "hidden" else 0
        shown = f.printed_slots                        # v2 C4：渲染层交出的画面槽（v1 在这里自己调 them_slots(f)）
        if st.last is not None:                        # v2 C3：提示之后只认在两次观察之间变过的槽
            st.moved |= {lab for lab, val in shown.items() if st.last.get(lab) != val}
            st.last = dict(shown)
            shown = {lab: val for lab, val in shown.items() if lab in st.moved}
        meaning = {f.layout.L("them", m): m for m in adventure.ENEMY_STATE_SLOTS}
        st.types |= {meaning[lab] for lab, v in shown.items() if lab in meaning and (v or mode != "all")}
        if f.state[("me", "poison")] > st.poison0:
            st.types.add("poison")
        if f.reflected > st.reflected:
            st.types.add("guard")
        if f.ward_wasted > st.wasted:
            st.types.add("ward")
        st.reflected, st.wasted = f.reflected, f.ward_wasted
        if belief is not None:
            st.types |= {m for m in ("pierce", "counter", "momentum") if getattr(belief, m, False)}   # v2 C1b：多抄 momentum
            self.counter_seen |= bool(belief.counter)
        if getattr(self, "nocue", False) and prev_types and not f.cues and not f.nocue_ack:   # j 版 V7 (c)：已认出一种、又认出另一种
            new = (st.types - prev_types) & set(solver.MECHANICS)   # j4：只认池里有的机制（规则书）；池外的（例如穿透）不算「换了」
            if new and prev_types - new:
                old = prev_types - new
                st.types = set(new)
                self.withdrawals.append((f.turn, tuple(sorted(old))))
                st.last, st.moved = dict(f.printed_slots), set()   # 离场的格还印着：之后只认变过的格（同提示之后）
                if belief is not None:
                    for m in old & set(FLAGS):
                        setattr(belief, m, False)
                f.nocue_ack = True                     # 渲染层的 (a)(b) 关掉（一场只认一次）
                NOCUE_LOG.append(dict(fight=None, turn=f.turn, kind="new_mechanism", what=sorted(new), old=sorted(old)))
        if st.types and st.identified_turn is None:
            st.identified_turn = f.turn
        now = dict(getattr(f, "fight_kinds", {}))
        played_now = [k for k in cautious.KINDS if now.get(k, 0) > st.kinds_seen.get(k, 0)]
        hits = getattr(f, "mark_hits", 0)
        if st.code and len(played_now) == 1:
            self.plays.append((st.code, played_now[0], hits > st.hits_seen)); self._post = None
        if f.turn != st.turn:
            st.turn = f.turn
            if code:
                self.draws.append((code, now)); self._post = None
        st.code, st.kinds_seen, st.hits_seen = code, now, hits
        return st, code


# ------------------------------------------------------------------ 调用入口
def run_life(run, route, rng, policy=None, **kw):
    """一条命（四图 + 原样的 boss，与 regsel.r1_wins 同一个调用，只换成 v2）。返回 (won, policy)。"""
    p = policy or R1v2Policy()
    with display():
        won = solver.run_once(run, know(), route, rng, information="observable", act_policy=p.act, heal_veto=p.heal_veto,
                              belief_cls=R1v2Belief, **kw)
    return bool(won), p


def play_fight(run, f, kinds, heal_at, policy=None, **kw):
    """单场（给 antagonist_boss.play_boss）：solver.play_fight 的回合循环 + v2。返回 (won, policy)。"""
    p = policy or R1v2Policy()
    with display():
        won = solver.play_fight(run, f, know(), kinds, heal_at, information="observable", act_policy=p.act,
                                heal_veto=p.heal_veto, belief_cls=R1v2Belief, **kw)
    return bool(won), p


# ------------------------------------------------------------------ 冒烟核对（不算通过率）
class _Diag:
    """记录器（在守卫之外，核对用，可以读真值；它的结果不回到出牌里）。"""
    belief = None

    def __init__(self, policy):
        self.p = policy; self.trace = []
        self.n = dict(decisions=0, est_checks=0, est_mismatch=0, momentum_belief_turns=0, momentum_belief_turns_not_momentum=0,
                      slot_checks=0, slot_mismatch=0, cue_fights=0)
        self.mismatch_examples = []

    def enter(self, run, f, kinds):
        self.f = f

    def before_decision(self, f):
        v = peek_view(f)
        self.n["decisions"] += 1
        if "momentum" in f.parts:
            self.n["est_checks"] += 1
            if v.momentum != f.momentum:
                self.n["est_mismatch"] += 1
                if len(self.mismatch_examples) < 5:
                    self.mismatch_examples.append(dict(kind="est", turn=f.turn, est=v.momentum, true=f.momentum))
        b = self.belief                                # 回合开头（observe_events 之后）信念与当时真机制的对照，只计数
        if b is not None and b.momentum:
            self.n["momentum_belief_turns"] += 1
            if "momentum" not in f.parts:
                self.n["momentum_belief_turns_not_momentum"] += 1
                if len(self.mismatch_examples) < 5:
                    self.mismatch_examples.append(dict(kind="momentum_belief", turn=f.turn, parts=list(f.parts)))
        st = self.p._fights.get(id(v))
        types = st.types if st is not None and st.f is v else set()
        for p in ("charge", "mark") + tuple(m for m in ("guard", "ward") if m in types):
            self.n["slot_checks"] += 1
            pub, true = v.state[("them", p)], f.state[("them", p)]
            same = (pub >= 1) == (true >= 1) if p == "guard" else (pub > 0) == (true > 0) if p == "ward" else pub == true
            if not same:
                self.n["slot_mismatch"] += 1
                if len(self.mismatch_examples) < 5:
                    self.mismatch_examples.append(dict(kind=p, turn=f.turn, pub=pub, true=true))

    def before_play(self, f, c):
        self.trace.append(c)

    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass

    def after_end_turn(self, f, *a): pass

    def leave(self, f, won):
        v = peek_view(f)
        if v is not None and v.cues:
            self.n["cue_fights"] += 1
        self.trace.append("|")

    def rest(self, run, mode): pass


class _Trace:
    """只记出牌序列（给 v1 用：不碰视图）。"""
    belief = None

    def __init__(self, d):
        self.d = d

    def enter(self, run, f, kinds): pass
    def before_decision(self, f): pass
    def before_play(self, f, c): self.d.trace.append(c)
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): pass
    def after_end_turn(self, f, *a): pass
    def leave(self, f, won): self.d.trace.append("|")
    def rest(self, run, mode): pass


def _add(tot, n):
    for k, x in n.items():
        tot[k] = tot.get(k, 0) + x


def smoke(lives=4, maps=3, boss_lives=6, out="r1v2_smoke_b.json", energy_veto=False):
    """b 版的冒烟（energy_veto=False 默认 = b 版原样；c 版的冒烟是 smoke_c）。几条命：守卫从不触发；开 / 关守卫出牌序列一致；
    动量估计与引擎计数一致的次数；公开槽值与真值；守卫能抓到 v1。已有的输出文件不覆盖。"""
    global GUARD
    _no_overwrite(out)
    import antagonist_proto as ap
    ap.setup()
    res = dict(study="r1v2-smoke", version=VERSION if energy_veto else VERSION_B, note="no pass rates computed or recorded", lives_per_map=lives)
    route = solver.SCREEN_ROUTES[9]
    salts = []
    s = ap.SALT0
    while len(salts) < maps and s < ap.SALT0 + 200:
        run = ap.build(s)
        if "momentum" in run.drawn:
            salts.append(s)
        s += 1
    tot = {}; same_trace = 0; diff_trace = 0; withdrawals = 0
    for salt in salts:
        run = ap.build(salt)
        for t in range(lives):
            traces = []
            for g in (True, False):
                GUARD = g
                p = R1v2Policy(guard=g, energy_veto=energy_veto); d = _Diag(p)
                rng = solver._trial_rng(ap.SEED ^ salt, "r1v2-smoke", t)
                run_life(run, route, rng, policy=p, record=d)
                traces.append(d.trace)
                if g:
                    _add(tot, d.n); res.setdefault("examples", []).extend(d.mismatch_examples[:2])
            GUARD = True
            same_trace += traces[0] == traces[1]; diff_trace += traces[0] != traces[1]
    res.update(map_salts=salts, maps=tot, guard_on_off_same_trace=same_trace, guard_on_off_diff_trace=diff_trace)
    # C5 / C4：图上没有动量时 C1-C3 都不会发生（无提示、本池里不认成动量），v2 的出牌序列应与 v1 逐张相同
    nm = []; s = ap.SALT0
    while len(nm) < maps and s < ap.SALT0 + 200:
        if "momentum" not in ap.build(s).drawn:
            nm.append(s)
        s += 1
    same = diff = 0
    for salt in nm:
        run = ap.build(salt)
        for t in range(lives):
            rng1, rng2 = (solver._trial_rng(ap.SEED ^ salt, "r1v2-smoke-v1", t) for _ in range(2))
            d2 = _Diag(R1v2Policy(energy_veto=energy_veto)); run_life(run, route, rng2, policy=d2.p, record=d2)
            d1 = _Diag(None); p1 = cautious.Cautious(VARIANT)
            with display():
                solver.run_once(run, know(), route, rng1, information="observable", act_policy=p1.act, heal_veto=p1.heal_veto,
                                belief_cls=cautious.PublicBelief, record=_Trace(d1))
            same += d1.trace == d2.trace; diff += d1.trace != d2.trace
    res.update(no_momentum_salts=nm, v1_v2_same_trace=same, v1_v2_diff_trace=diff)
    # boss：换阶段开、提示开（原型侧 D1 补丁不在本文件；这里是引擎原样的换阶段），独立一条命（run.trial 重置）
    saved = {k: TUNING[k] for k in ("boss_switch", "boss_switch_hint")}
    bt = {}; bsalts = []
    try:
        TUNING.update(boss_switch=1, boss_switch_hint=1)
        s = ap.SALT0; want = ["x->momentum", "momentum->x", "slot->slot"]      # 进场动量、离场动量、两个带槽机制各一对
        while want and s < ap.SALT0 + 200:
            run = ap.build(s)
            e = run.boss_enemies[0]
            if len(run.boss_enemies) == 1 and e.switch_to:
                a, b = "+".join(e.parts_for(False)), "+".join(e.parts_for(True))
                kind = "x->momentum" if b == "momentum" else "momentum->x" if a == "momentum" else "slot->slot"
                if kind in want:
                    want.remove(kind); bsalts.append((s, a, b))
            s += 1
        for salt, a, b in bsalts:
            run = ap.build(salt)
            for t in range(boss_lives):
                rng = solver._trial_rng(ap.SEED ^ salt, "r1v2-smoke-boss", t)
                shuffles = [rng.randrange(1 << 30) for _ in run.shuffles]
                with run.trial(shuffles=shuffles):
                    p = R1v2Policy(energy_veto=energy_veto); d = _Diag(p)
                    for bf in run.boss_fights():
                        won, _ = play_fight(run, bf, run.by_kind, route.heal_at, policy=p, record=d)
                        run.absorb(bf)
                        if not won:
                            break
                    _add(bt, d.n); withdrawals += len(p.withdrawals)
    finally:
        TUNING.update(saved)
    res.update(boss_pairs=[dict(salt=s_, phase1=a, phase2=b) for s_, a, b in bsalts], boss=bt, boss_policy_withdrawals=withdrawals)
    # 反证：守卫抓得到隐藏读（直接读 f.momentum；v1 的 Cautious.act 在真对局上）
    run = ap.build(salts[0])
    caught = {}
    with display(), run.trial(shuffles=[1] * len(run.shuffles)):
        i0 = next(k for k, layer in enumerate(run.layers) if layer.kinds() != ["rest"])
        f = run.fight_at(i0, 0)
        for name, fn in (("f.momentum", lambda: f.momentum), ("f.parts", lambda: f.parts),
                         ("f.state[them atk]", lambda: f.state[("them", "atk")]), ("enemy.behaviour", lambda: run.boss_enemies[0].behaviour),
                         ("v1 Cautious.act", lambda: cautious.Cautious(VARIANT).act(f, know(), run.by_kind, belief=cautious.PublicBelief()))):
            try:
                with hidden_access_guard():
                    fn()
                caught[name] = False
            except HiddenRead as ex:
                caught[name] = str(ex)
        restored = isinstance(adventure.Fight.__dict__.get("parts"), property) and f.momentum == 0 and "state" not in adventure.Fight.__dict__
    res.update(guard_negative_controls=caught, classes_restored=restored)
    d = ROOT / "results" / "proto13" / "boss_checks"; d.mkdir(parents=True, exist_ok=True)
    (d / out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def _out_dir():
    d = ROOT / "results" / "proto13" / "boss_checks"; d.mkdir(parents=True, exist_ok=True)
    return d


def _no_overwrite(out):
    path = pathlib.Path(out) if pathlib.Path(out).is_absolute() else _out_dir() / out
    if path.exists():
        raise SystemExit(f"{path} 已存在：已有结果文件不覆盖（换一个 out）")
    return path


class _DiagC(_Diag):
    """c 版冒烟的记录器：在 _Diag 之外，每回合末记下本回合自己出过的牌种（含 play_fight 直接出的自动治疗，它不经 before_play）。"""

    def before_end_turn(self, f):
        self.trace.append(tuple(sorted(f.played_kinds.items())))


class _OracleTrace:
    """oracle 的出牌序列（真对局，不碰视图）。"""
    belief = None

    def __init__(self):
        self.trace = []

    def enter(self, run, f, kinds): pass
    def before_decision(self, f): pass
    def before_play(self, f, c): self.trace.append(c)
    def after_play(self, f, c, atk_before): pass
    def before_end_turn(self, f): self.trace.append(tuple(sorted(f.played_kinds.items())))
    def after_end_turn(self, f, *a): pass
    def leave(self, f, won): self.trace.append("|")
    def rest(self, run, mode): pass


def _veto_unit():
    """工厂的单元核对：桩对象只有 energy_heal_veto 读的那几个名字。"""
    class _Stub:
        def __init__(self, energy, played):
            self.state, self.played_kinds, self.turn = {("me", "energy"): energy}, played, 1
            self.deck = {n: _PublicCard(k) for n, k in (("A", "attack"), ("B", "block"), ("D", "dodge"), ("H", "heal"), ("X", "buff_mark"))}
    cases = [  # (能量, 本回合已出, 策略想出, base 否决, 应否决, 说明)
        (2, {}, "D", False, True, "dodge costs 2: after a 1-cost heal it is unaffordable"),
        (2, {}, "A", False, False, "attack costs 1: still affordable after the heal"),
        (2, {}, "B", False, False, "block costs 1"),
        (1, {}, "A", False, True, "1 energy: the heal would eat the first card"),
        (1, {"heal": 1}, "A", False, True, "only heals played so far: the first card is still protected"),
        (1, {"attack": 1}, "B", False, False, "a non-heal card already played this turn: not protected"),
        (1, {"heal": 1, "block": 1}, "A", False, False, "non-heal already played"),
        (2, {}, "H", False, False, "the policy itself wants to heal"),
        (2, {}, None, False, False, "the policy would play nothing"),
        (2, {}, "A", True, True, "base veto (v1 mark-avoid) decides first"),
    ]
    rows = []
    for energy, played, want, base, exp, why in cases:
        v = energy_heal_veto(lambda f, w=want: w, base=(lambda f: True) if base else None)
        got = v(_Stub(energy, dict(played)))
        rows.append(dict(energy=energy, played=played, intended=want, base=base, expected=exp, got=got, ok=got == exp, why=why))
    return rows


def smoke_c(lives=4, maps=4, boss_lives=4, out="r1v2_smoke_c.json"):
    """c 版冒烟（规格 §9c，实现之后写；不算、不记输赢或通过率）：
      工厂单元核对；同一随机流下 c 与 b 逐张对照（含自动治疗）——一条命里否决一次都没触发时必须逐张相同；
      否决之后策略是否出了被保护的那张（veto_kept）；守卫从不触发；动量估计 / 公开槽值与真值（同 _Diag）；
      oracle 工厂：几条 boss 命上 oracle 原样对 oracle + oracle_heal_veto，没触发否决的命必须逐张相同。"""
    import antagonist_proto as ap
    path = _no_overwrite(out)
    ap.setup()
    route = solver.SCREEN_ROUTES[9]
    res = dict(study="r1v2-smoke-c", version=VERSION, baseline=VERSION_B, date="2026-11-03",
               note="no pass rates or wins computed or recorded; written after implementation",
               proto_loot=bool(ap.LOOT), display=dict(devworld.R1_DISPLAY), route="SCREEN_ROUTES[9]", heal_at=route.heal_at,
               files={rel: __import__("hashlib").sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
                      for rel in ("scripts/r1v2.py", "scripts/antagonist_proto.py", "scripts/antagonist_boss.py", "core/solver.py", "core/cautious.py",
                                  "docs/antagonist_boss/04_r1v2_spec.md")})   # 规格也记哈希（审查 2026-11-03：c 版之前没记，「写在看结果之前」无从核对）
    unit = _veto_unit()
    res.update(veto_unit=unit, veto_unit_ok=all(r["ok"] for r in unit))
    hidden = []

    def compare(play, tag):
        """play(energy_veto) -> (policy, diag)；返回这一对的对照行。"""
        out_ = {}
        for ev in (False, True):
            try:
                out_[ev] = play(ev)
            except HiddenRead as ex:
                hidden.append(f"{tag} energy_veto={ev}: {ex}"); return None
        (pb, db), (pc, dc) = out_[False], out_[True]
        return dict(tag=tag, vetoes=len(pc.energy_vetoes), veto_kinds=[x["kind"] for x in pc.energy_vetoes],
                    veto_ctx=[f'{x["kind"]}@energy{x["energy"]}/heals{x["heals_this_turn"]}' for x in pc.energy_vetoes], kept=pc.veto_kept,
                    changed=pc.veto_changed, b_vetoes=len(pb.energy_vetoes), same=db.trace == dc.trace, n=dc.n, stats=dict(pc.veto_stats))

    def summarise(rows):
        rows = [r for r in rows if r is not None]
        z = [r for r in rows if r["vetoes"] == 0]; v = [r for r in rows if r["vetoes"]]
        tot = {}
        for r in rows:
            _add(tot, r["n"]); _add(tot, {"veto_" + k: x for k, x in r["stats"].items()})
        kinds = collections.Counter(k for r in rows for k in r["veto_kinds"])
        return dict(lives=len(rows), no_veto_lives=len(z), no_veto_same_as_b=sum(r["same"] for r in z),
                    no_veto_lives_where_policy_was_asked=sum(bool(r["stats"]["checked"]) for r in z),
                    vetoed_lives=len(v), vetoed_lives_differ_from_b=sum(not r["same"] for r in v),
                    vetoes=sum(r["vetoes"] for r in rows), veto_kinds=dict(kinds),
                    veto_contexts=dict(collections.Counter(c for r in rows for c in r["veto_ctx"])), veto_kept=sum(r["kept"] for r in rows),
                    veto_changed=sum(r["changed"] for r in rows), b_mode_vetoes=sum(r["b_vetoes"] for r in rows), counts=tot)

    # 地图：含蓄力的图在前（错序最常见的地方），凑够 maps 张两轮图
    salts = []; s = ap.SALT0
    while len(salts) < maps and s < ap.SALT0 + 200:
        run = ap.build(s)
        if devworld.two_rounds(run) and ("charge" in run.drawn) == (len(salts) < maps // 2 + maps % 2):
            salts.append(s)
        s += 1
    rows = []
    for salt in salts:
        run = ap.build(salt)
        for t in range(lives):
            def play(ev, run=run, salt=salt, t=t):
                p = R1v2Policy(energy_veto=ev); d = _DiagC(p)
                run_life(run, route, solver._trial_rng(ap.SEED ^ salt, "r1v2-smoke-c", t), policy=p, record=d)
                return p, d
            rows.append(compare(play, f"map {salt} t{t}"))
    res.update(map_salts=[dict(salt=x, drawn=list(ap.build(x).drawn)) for x in salts], maps=summarise(rows))
    # boss：antagonist_boss 的设置（D1 补丁、提示），独立一条命（D2），同 play_boss 的随机流约定
    import antagonist_boss as ab
    from adventure import TUNING
    saved_disp = {k: TUNING[k] for k in devworld.R1_DISPLAY}
    ab.setup_boss()
    pairs = (("charge", "ward"), ("ward", "charge"), ("charge", "momentum"), ("momentum", "charge"), ("guard", "charge"))
    brows = []; orows = []
    try:
        for pr in pairs:
            ctx = ab.build_boss(2000000, pr, 0); run = ctx["run"]
            for t in range(boss_lives):
                def shuffles(stream, t=t, run=run):
                    rng = solver._trial_rng(ap.SEED ^ ctx["salt"], stream, t)
                    return [rng.randrange(1 << 30) for _ in run.shuffles]

                def play(ev, run=run, t=t):
                    with run.trial(shuffles=shuffles("r1v2-smoke-c-boss")):
                        f = next(run.boss_fights())
                        p = R1v2Policy(energy_veto=ev); d = _DiagC(p)
                        play_fight(run, f, run.by_kind, route.heal_at, policy=p, record=d, enrage_budget=route.enrage_budget)
                    return p, d
                brows.append(compare(play, f"boss {pr[0]}->{pr[1]} t{t}"))
                tr = {}; vstats = None
                for use in (False, True):
                    TUNING.update(devworld.R1_DISPLAY)
                    try:
                        with run.trial(shuffles=shuffles("r1v2-smoke-c-oracle")):
                            f = next(run.boss_fights())
                            hv = oracle_heal_veto(solver.ALL, run.by_kind, route.enrage_budget) if use else ap.no_heal_veto   # 不是 None：PROTO_REFS=c 下 ap 的包装会给 None 接上否决
                            rec = _OracleTrace()
                            solver.play_fight(run, f, solver.ALL, run.by_kind, route.heal_at, information="oracle",
                                              enrage_budget=route.enrage_budget, heal_veto=hv, record=rec)
                            tr[use] = rec.trace
                            if use:
                                vstats = dict(hv.stats); vkinds = [f'{x["kind"]}@energy{x["energy"]}/heals{x["heals_this_turn"]}' for x in hv.log]
                    finally:
                        TUNING.update(saved_disp)
                orows.append(dict(tag=f"{pr[0]}->{pr[1]} t{t}", vetoes=vstats["vetoed"], veto_kinds=vkinds, same=tr[False] == tr[True], stats=vstats))
    finally:
        ab.teardown_boss()
        TUNING.update(saved_disp)
    res.update(boss_pairs=[list(x) for x in pairs], boss_salt=2000000, boss=summarise(brows))
    oz = [r for r in orows if r["vetoes"] == 0]; ov = [r for r in orows if r["vetoes"]]
    ot = {}
    for r in orows:
        _add(ot, r["stats"])
    res.update(oracle=dict(lives=len(orows), no_veto_lives=len(oz), no_veto_same_as_plain=sum(r["same"] for r in oz), vetoed_lives=len(ov),
                           vetoed_lives_differ=sum(not r["same"] for r in ov), veto_contexts=dict(collections.Counter(k for r in orows for k in r["veto_kinds"])),
                           stats=ot, note="diagnostic-reference change; the veto reads only the oracle's own energy, own plays this turn, card costs and its own choice"))
    res.update(hidden_reads=hidden)
    m, b = res["maps"], res["boss"]
    res["checks"] = dict(
        veto_unit=res["veto_unit_ok"],
        guard_never_tripped=not hidden,
        no_veto_lives_identical_to_b=m["no_veto_same_as_b"] == m["no_veto_lives"] and b["no_veto_same_as_b"] == b["no_veto_lives"],
        b_mode_never_vetoes=m["b_mode_vetoes"] == 0 and b["b_mode_vetoes"] == 0,
        veto_kept_equals_vetoes=m["veto_kept"] == m["vetoes"] and b["veto_kept"] == b["vetoes"],
        est_matches_engine=m["counts"].get("est_mismatch", 0) == 0 and b["counts"].get("est_mismatch", 0) == 0,
        public_slots_match=m["counts"].get("slot_mismatch", 0) == 0 and b["counts"].get("slot_mismatch", 0) == 0,
        oracle_no_veto_identical=res["oracle"]["no_veto_same_as_plain"] == res["oracle"]["no_veto_lives"])
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("version", "proto_loot", "checks", "maps", "boss", "oracle")}, ensure_ascii=False, indent=1, default=str))
    print("->", path)
    return res


if __name__ == "__main__":
    smoke_c() if sys.argv[1:] == ["c"] else smoke()
