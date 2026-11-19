"""搜图前的门 —— 锁在代码里，不是写在聊天记录里。

================ 世界与命的单位 ================

    一个包 = 同一 seed、四个不同 salt 的四条命，按 A → B → C → D 顺序打。
    跨命不变：seed 层的一切（牌名、符号、费用、`mark` 的规则**内容**）、
              六抽四的规则、教一轮考一轮的顺序、代价的形状（探针一次便宜、重复全价）。
    跨命重掷：抽到哪四种、顺序、怪的数值、标记代号的含义（`mark-v1:{salt}`）。
    覆盖（硬门）：四张图抽到的机制并集 = 整个池子（`devworld.PROTOTYPE_POOL`，六种）。
                  缺席的机制不算已考。每种机制在包里出现几张图，必须报告。
    momentum   实现保留（`devworld.EXPERIMENTAL_POOL`），不进认证池：七池正式搜图 0/20
               过 Vmin，它的 V 均值 19%，根源是参考策略的默认填充动作就是它的答案。

================ 干净通关 ================

    普通通关   活着打完 boss。
    干净通关   普通通关，且每种**被问到**的机制在可执行机会上的错误率 < CLEAN_THR。
    分母       决策时刻答案可执行的回合（`ledger.Ledger`，不是回合末花光的能量条）：
                 charge    槽满 且 闪避可打
                 momentum  斜坡 ≥ FULL_AT−1 且 格挡可打
                 pierce    已被穿透过一次（fed ≥ 1）
                 counter   本局已挨过一次反击 且 第二次进攻可打
                 guard     守相 且 进攻可打 且 本局已被反弹过一次
                 mark      本局已被标记击中一次 且 被标记的牌种可打
                 poison    毒层 ≥ 4 且 血量 ≥ 25% 上限的休息
    首次探针   不进分母也不进分子：pierce 第一次举盾、counter 第一次双进攻、
               guard 第一次反弹、mark 第一次被击中。
    机会为零   该机制「未受测」，不算脏，必须在覆盖表里报告。
    两个通关率永远并列报告；干净通关不替代普通通关。

================ 懂规则与知识价值 ================

    ALL     参考策略、所有规则已知、固定路线 `SCREEN_ROUTES[9]`。报告，不设下限（用户放开：
            懂的人也要付血量管理和牌组规划的成本）。逐图、逐包的最低值必须报告。
    gap     ALL − 最强盲线，普通和干净各算一次，两者都要 ≥ GAP_MIN（硬门）。
    Vmin    min over m ∈ 本世界抽到的机制 of (ALL − ALL₋ₘ)，≥ VMIN_MIN（硬门，逐图）。
            不抽到的机制不进 Vmin；六种机制在整个包上的覆盖另报。
    boss    每一段必须真的考自己那条机制（硬门，逐图）：
            boss_ALL − boss_(ALL − 该段机制) ≥ BOSS_STAGE_REQ，两者都从懂的人**实际到达
            boss 的状态**出发（`solver.run_once(boss_know=…)`），普通战斗一律按 ALL 打。
            这才是同一起点的反事实；ALL 对 ALL−m 从头打到尾会把「谁到了 boss」混进来。
            流 BOSS_STREAM。
            boss 的价钱 = 考试轮价钱（`boss_punish_pct`），且不送探针（`boss_no_probe`）：
            探针在教学轮和考试轮各给过一次，到 boss 第一次踩线就是重复。第二次登记时
            boss 价钱 100%、送探针，比考试轮还便宜，counter 段 17 张图考不出任何东西。
    因果链  旧观察器（observe-v2）只认识 poison / charge / pierce（以及不在池里的 enrage、
            momentum）；counter / guard / mark 的因果链**未测**，每张图报告观察器能看见抽到的
            哪几种。不得把包称作「五项测量全部完成」。
    可玩性  ALL 无下限（登记里没有，事后不加）；逐图最低值必须显眼报告为可玩性风险
            （开发批次最低 25%）。

================ 包级盲线 ================

    一条固定规则贯穿四命：同一个 (变体, 路线) 对，路线含 take / heal_at / 休息习惯，
    不得逐图重挑。族 = `solver.blind_gate(full=True)`。
    计分   P(四命里至少通 PACK_MIN_CLEARS 命)，每次试验直接打四命数出来。
    两阶段，两条流：
      筛选   搜索流 SCREEN_STREAM，每条线每命 N_SCREEN 次 —— 只用来排序候选世界，
             报告口径是「已测线的经验最大值」，**不**构成 ≤1% 的声明。
             P(≥2/4) 按**独立的四命试验**数出来：一次试验 = 同一条线打完四命再数通了几命；
             不是四条命各自的通关率拼出来的。
      认证   独立确认流 CERT_STREAM，**整个族**每条线每命 N_CERT 次。
             声明「族里最强者的包级通过率 ≤ BLIND_MAX」当且仅当：每条线的包级通过
             次数的 Clopper–Pearson 单侧上界（α = CERT_ALPHA / |族|，Bonferroni）≤ BLIND_MAX。
             N_CERT 由此反推：0 次通过时上界 = 1 − (α/|族|)^(1/N)，
             要 ≤ 1% 需 N ≥ ln(α/|族|) / ln(1 − BLIND_MAX)。
    决定（运行前定下，不搜完再换说法）：本轮**做认证**，只对通过其余硬门的决赛包做；
    筛选阶段的数字只写「经验最大值」。
    验证批次（第四次登记）：开发批次（salt 300000 起的 20 包）已经用来发现 boss 问题、选出
    boss 旋钮，它上面的 20/20 是开发结果。认证在**全新 salt 段** SALT_START_VALIDATION 起
    的一批上做：按 salt 顺序成包，按 salt 顺序过便宜门，**最先通过的 K_CERT 个包**进认证
    —— 不按 ALL 最高、不按结果最好挑。
    联合声明：要同时声称 K_CERT 个包都过门，α 再除 K_CERT：每线每命 N = n_cert(|族| × K_CERT)。
    探针前提（硬门，逐图）：`boss_no_probe` 的理由是探针在普通战斗里给过。核的是**实际**：
    不懂 m 的人（ALL−m）到达 boss 时 m 的探针已经在他身上落过的比例 ≥ PROBE_BEFORE_BOSS_MIN
    （只对 counter / guard / mark 段；到达数 < PROBE_MIN_ARRIVALS 记「未测」不记失败）。
    开发批次上量到 counter 均 99.9% 低 98.6%、guard / mark 100%，阈值定在 95%。

================ 模型 pilot（第五次登记，跑模型之前写下） ================

    世界    `devworld.PILOT_PACK` = 400071 / 400088 / 400089 / 400102（认证包二）。理由：逐图 ALL
            最低 74%，比包一的 50% 更能保证模型有机会接触后面的题；包三（最低 95%）留作对照
            `devworld.CONTROL_PACK`。不据模型结果换包。
    链      四命 A→B→C→D，`modelrun --registered --life k --salt`，carry=notes、fight-notes=write
            （和 smoke 相同），run_id 固定。三命会截掉参考学习者曲线里最有信息的部分
            （命 3 平均 29%、命 4 56%），所以是四命。
    对照    B、C、D 各一条 Fresh：life 1、同一张图、`--reuse-camp --camp-from <链>`（训练营逐字
            相同），没有前命记忆。
    主指标  同一张图上逐机制 错误数/可执行机会数（B 表，决策时刻可执行：`modelrun.run_fight`
            对 counter/guard/mark 也在能量未花时记）。每格分子/分母。通关只作结果。
    地位    **管线 pilot**。一条链不作迁移证据，不据此调任何阈值。
    未测    counter / guard / mark 没有证据因果链观察器（A 表只认识 poison/charge/pierce）；
            81 个 boss 段的探针前提到达太少未测。盲线认证过了不等于这两项过了。
    报告    `results/transfer_report.py <model> <run-id>`。

================ 不作为本轮硬门 ================

    build          未通过（什么都不拿 ≥ 任何条件补牌规则）。独立目标。
    参考学习者曲线  仪器的正控制（need=2、识别即领答案），不是模型的及格线。报告。
                    六抽四覆盖得比七抽四快，「命 3–4 才上升」不能沿用，逐包重量。
                    已知限制：need=2 要挨两次，而探针按局只送一次，第二次就是全价 —— 晚命
                    才首次抽到的机制它学不到就死（开发批次命 4 的死亡 131/149 在未学会的
                    guard 上）。只学池子里的规则（momentum 误报已修，`learner.belief_for`）。
    规划值         `mapdp.solve` 在五机制以上的 rotation 状态枚举爆炸，未量。不阻塞搜图。

================ 图库（第九次登记，2026-09-28） ================

    单位改为图。图库 = 从全新 salt 段 SALT_START_LIBRARY 起、按 salt 顺序最先通过逐图便宜门
    （Vmin、boss 每段、探针前提、gap 普通+干净 —— 相对逐图单命盲线筛选的经验最大值）的 LIB_SIZE
    张图；不按 ALL、不按结果挑。LIB_SIZE 张作为**一个族**认证，认证之后才拼包（`library.compose`）。
    逐图认证   整个盲线族每条线在每张图上打 N 条独立单命（流 LIB_STREAM）。声明「族里最强线在该图
              的单命通关率 ≤ MAP_BLIND_MAX」当且仅当每条线的 Clopper–Pearson 单侧上界
              （α = CERT_ALPHA / (|族| · LIB_SIZE)：Bonferroni 同时覆盖全族 × 全部 LIB_SIZE 张图，
              所以认证之后从图库里任选、任拼都仍是 95% 同时置信）≤ MAP_BLIND_MAX。
    样本量     0 次通关的最小 N = ln(α') / ln(1 − MAP_BLIND_MAX)（1700 线 × 40 图：346）。但登记 8
              的认证记录里，**通过认证的**图上有的线单命通关 4/1145（0.35%，400102 有 27 条线
              ≥ 1 次）；N = 346 时这样的线只有三成概率读到 0 次，一张好图会被一条线的一次运气判死。
              所以 N 取 `n_cert_map`：最小的 N，使真实率 ≤ LIB_TOL_RATE 的线以 ≥ LIB_POWER 的概率
              通过 —— 判据仍是上界 ≤ MAP_BLIND_MAX，只是 N 大到容得下正常的零星通关。
    组合上界   四张图各 ≤ M 时，一条**无状态**盲线四命 P(≥2/4) ≤ Σ_{i<j} M_i M_j ≤ C(4,2)·M²
              = 0.96% ≤ BLIND_MAX（配对并集界，只要求四命两两独立）。三个前提，都由测试钉住：
                (1) 盲线跨命无状态：每条线都是 frozen dataclass，回合内状态在 Fight 上，
                    `Run.trial` 进出各恢复一次 —— 同一 (图, 线, 路线, 试验号) 的轨迹与之前打过什么
                    无关（BlindLinesAreStatelessAcrossLives）；
                (2) 四命独立：每条命的随机数只由 (salt, 流, 试验号) 决定，不同图不同 salt；
                (3) 按包重命名不改变任何一条盲线、也不改变懂的人的轨迹（RenamingDoesNotChangePlay）：
                    引擎与策略只按牌的**种类**取牌，名字只是字典键。
    拼包       `library.compose`：事先写死的确定性规则，组合、排列都按 salt 字典序取第一个合规的：
        覆盖         四张图抽到的机制并集 = 整个池子（七种）
        重现         每种机制至少出现在 COMPOSE_MIN_APPEAR 张图上（迁移要「见过一次、再考一次」）
        新机制节奏   每世最多 COMPOSE_NEW_SCHEDULE[世-1] 种此前没见过的机制：第 2 世 2、第 3 世 1、第 4、5 世 0，
                     七种在前三世全部见过，最后两世没有第一次遭遇，每一次机会都是复考（第十一次登记，2026-10-02）
        可玩性       站 2–4 的图 ALL ≥ COMPOSE_LATE_ALL_MIN（站 1 不限；死在后站会截掉复考读数）
        盲线         Σ_{i<j} u_i u_j ≤ BLIND_MAX，u 取各图的认证上界。五张图 10 对：五张 4% 的图是 1.6%，过不了，
                     所以这条靠的是各图**实际**的上界（图库里多数是 1.71%，五张就是 0.29%），不是 MAP_BLIND_MAX
        两个实验包（第十一次登记起叫 v1.1-1、v1.1-2；登记 10 的四世包 v1-1、v1-2 留档）不共用图。
        参考学习者曲线按拼好的包量（仪器，只报告）。概念命名：一命 = 一世（转世），一包 = 一个宇宙。
    发布族     RELEASE_SEGMENTS 五个 salt 段各 LIB_SIZE 张，共 RELEASE_FAMILY_MAPS = 200 张作为一个族：
               α = CERT_ALPHA / (|族| · 200)，每线每图 913 条命；已按 40 张族认证过的图库 1、2 不重算，**续跑**到 913
               （每条试验的随机数只由 (salt, 流, 试验号) 决定，与总次数无关；逐线通关数已落盘，补 96 次即可）。
               包在整个发布族上拼，互不共图。
    声明的边界 95% 联合覆盖的是：预先登记的图库内每张图上、预先登记的 1700 条固定策略族中每条线的**单图通关率上界**
               ≤ MAP_BLIND_MAX；再由各世独立（测试钉住）推出任意合规五图包的包级上界 ≤ BLIND_MAX。
               它**不是**「所有可能的瞎打方法都已证明过不了」：族外的策略不在声明内。发布措辞必须这样写。
    破势       进的是**待认证**七池：8/8 便宜门是 salt 700000 段上选旋钮的开发结果，不算正式通过。
    阶梯（第十次登记）分段封印上限 教学 1 / 考试 3 / boss 4，起始都是 1（`ward_*_cap`）。上限不动任何门的数字，
               只给第一次试错留补救空间（通用探索线首战 8% → 94–97%）；起始 > 1 连懂的人也杀，不用。
               旋钮是在登记 9 的图库（900000 段）上选的，所以第十次登记在 SALT_START_LIBRARY 重搜重认证，
               登记 9 的图库与它的两个包作废。**教学信息缺口**：教学轮上限 1 时攻击后封印仍显示 1，玩家能看到
               「攻击无效」，看不到「攻击会加固封印」，后半条规则到考试轮才显现；便宜门与 V 不变不等于完整
               规则在教学轮教会了（诊断器教学轮 51%）。报告必须写这一条。
              momentum、mimic 留在实验池。登记 8 的六池、PROTOTYPE_8 和六个认证包原样保留
              （`devworld.REGISTRATIONS[8]`）：正在进行的人类测试和 v1 数据不动、不并入。

================ 第十二次登记（2026-10-27，六池；独立于登记 11） ================

    池        devworld.PROTOTYPE_POOL_12 = 七池去掉毒（charge、pierce、counter、guard、mark、ward）。毒的实现留在引擎里。
    旋钮      devworld.PROTOTYPE（与登记 11 相同，不改任何 TUNING 值）。
    salt 段   RELEASE_SEGMENTS_12 五段各取按 salt 顺序最先的 LIB_SIZE 张两轮图，RELEASE_FAMILY_MAPS_12 = 200 张作为一个族认证；
              和以前用过的所有段（300000–1499999）不相交。
    硬门      覆盖（包的机制并集 = 池；单图抽到的 ⊆ 池）、逐图盲线认证（MAP_BLIND_MAX，α = CERT_ALPHA / (|族| · 200)）、
              包级界 Σ_{i<j} u_i u_j ≤ BLIND_MAX、拼包规则（COMPOSE_MIN_APPEAR、COMPOSE_NEW_SCHEDULE、PACK_SIZE）。
    仅报告    Vmin、boss 每段、探针前提、gap（普通 + 干净）、站 2–4 的可玩性（COMPOSE_LATE_ALL_MIN）、登记策略的 ALL —— 照算、落盘，不淘汰。
    参照      懂规则的参照是 R1（devworld.R1_VARIANT 的 cautious.Cautious，marks=0、state_slots="seen"、PublicBelief），
              不是读身份标签和隐藏映射的登记策略。搜图报告、拼包的 room 分数都读 R1。盲线认证不读画面，不变。
    输出      results/reg12/…（scripts/regsel.py）；登记 11 的 results/worlds、results/*.json 一个字节都不碰。
    操作文档  docs/REGISTRATION_12.md。

`results/pre_registration.json` 记录：本模块的常量、`devworld.PROTOTYPE`、流名、salt 区间、
以及 core/*.py 的 sha256 —— 搜图用的代码就是那一份。测试钉住两边一致。
"""
from __future__ import annotations

import hashlib
import math
import pathlib

CLEAN_THR = .20          # 干净通关：单机制错误率上限（严格小于）
CLEAN_MIN_OPP = 1        # 至少问到一次才计入
GAP_MIN = .50            # 懂 − 最强盲线，普通和干净都要
VMIN_MIN = .20           # 逐图、只对抽到的机制
BOSS_STAGE_REQ = .20     # 逐图、每一段 boss：懂 − 不懂这一段的机制（同一到达状态）
BLIND_MAX = .01          # 包级盲线：族里最强者 P(≥2/4) 的认证上限
PACK_MIN_CLEARS = 2      # 四命里至少通几命算「过包」
PACK_SIZE = 5             # 第十一次登记：一个包五世（原四世）
CERT_ALPHA = .05         # 族级单侧置信 95%
K_CERT = 3               # 验证批次里按 salt 顺序最先过便宜门的几个包进认证；联合声明，α 再除它
PROBE_BEFORE_BOSS_MIN = .95   # 不懂 m 的人到 boss 时 m 的探针已落过的比例（counter/guard/mark 段）
PROBE_MIN_ARRIVALS = 10       # 到达数低于此记「未测」

SCREEN_STREAM = "ps"     # 筛选（搜索流）
CERT_STREAM = "pcert"    # 认证（独立确认流）—— 和以往任何脚本用过的流名都不同
INFORMED_STREAM = "ev"
KNOW_STREAM = "kv"       # Vmin 的 ALL₋ₘ 复测
BOSS_STREAM = "bk"       # boss 段反事实（boss_know）
PROBE_STREAM = "pr"      # 探针前提核查（ALL−m 到 boss 入口）
LEARN_STREAM = "lc"      # 参考学习者曲线（仪器）

N_SCREEN = 20
SALT_START = 300000      # 开发批次的 salt 起点；以前所有实验都在它之下
SALT_START_VALIDATION = 400000   # 验证批次：全新 salt 段，认证只在这里做
SALT_START_VALIDATION_2 = 500000   # 第二验证批次（第七次登记）：同一规则，独立的第二组 K_CERT 个包

# ---- 图库（第九次登记） ----
LIB_SIZE = 40                 # 图库家族：按 salt 顺序最先过逐图便宜门的 40 张图，作为一个族认证
SALT_START_LIBRARY_9 = 900000   # 登记 9 的图库段：破势阶梯的旋钮在它上面选的，对登记 10 是开发批次
SALT_START_LIBRARY = 1000000    # 登记 10 的图库段：全新（300000 开发、400000/500000 验证、600000–900000 都用过）
SALT_START_LIBRARY_2 = 1100000  # 图库 2（登记 11 补充，2026-10-02）
# ---- 发布族（2026-10-02 定）：五个 salt 段各取最先过便宜门的 LIB_SIZE 张，200 张作为**一个**族做联合认证 ----
RELEASE_SEGMENTS = (1000000, 1100000, 1200000, 1300000, 1400000)
RELEASE_FAMILY_MAPS = LIB_SIZE * len(RELEASE_SEGMENTS)   # 200：α = CERT_ALPHA / (|族| · 200)，每线每图 n_cert_map(|族| · 200) = 913 条命
# ---- 第十二次登记（六池）：全新的五个 salt 段，和上面每一段都不相交 ----
RELEASE_SEGMENTS_12 = (1500000, 1600000, 1700000, 1800000, 1900000)
SALT_START_LIBRARY_12 = RELEASE_SEGMENTS_12[0]
RELEASE_FAMILY_MAPS_12 = LIB_SIZE * len(RELEASE_SEGMENTS_12)   # 200
# 登记 12 的逐图硬门（用户 2026-10-27）：R1（devworld.R1_VARIANT，公开信息的谨慎玩家）在固定的 R1_N_12 条命、固定流 R1_STREAM_12
# 上的通关率点估计 ≥ R1_MIN_12。n 和流事先声明、不随图变；Clopper–Pearson 双侧 95% 区间只存、只报告，不参与判定。
R1_MIN_12 = .90
R1_N_12 = 200
R1_STREAM_12 = INFORMED_STREAM
SEGMENT_SPAN = 100000                                          # 一段的 salt 宽度（段 = [起点, 起点 + SEGMENT_SPAN)）
MAP_BLIND_MAX = .04           # 逐图：族里最强线单命通关率的认证上界；四张图 C(4,2)·M² = 0.96% ≤ BLIND_MAX
LIB_TOL_RATE = .005           # 样本量的功效标准：真实单命通关率 ≤ 0.5% 的线要以 ≥ LIB_POWER 的概率通过
LIB_POWER = .99
LIB_STREAM = "mcert"          # 逐图认证流
LIB_SCREEN_STREAM = "ms"      # 逐图盲线筛选流（只用来算 gap 和排序，不构成声明）
COMPOSE_MIN_APPEAR = 2        # 拼包：每种机制至少出现在两张图上
COMPOSE_NEW_SCHEDULE = (None, 2, 1, 0, 0)   # 拼包：每世最多几种此前没见过的机制；第 1 世不限，最后两世 0（纯复考）
COMPOSE_LATE_ALL_MIN = .70    # 拼包：站 2–4 的图 ALL ≥ .70（站 1 不限）


def n_cert(family_size: int, alpha: float = CERT_ALPHA, p: float = BLIND_MAX) -> int:
    """整个族每条线每命要打多少次，0 次通过才能声明 ≤ p（Bonferroni 单侧）。"""
    return math.ceil(math.log(alpha / family_size) / math.log(1 - p))


def max_clears(n: int, alpha: float, p: float = MAP_BLIND_MAX) -> int:
    """n 条命里最多通几次，Clopper–Pearson 单侧上界（α）仍 ≤ p。-1 = 连 0 次都不够。"""
    k = -1
    while _binom_cdf(k + 1, n, p) <= alpha:
        k += 1
    return k


def n_cert_map(family_size: int, alpha: float = CERT_ALPHA, p: float = MAP_BLIND_MAX,
               tol: float = LIB_TOL_RATE, power: float = LIB_POWER) -> int:
    """逐图认证每条线每图打多少次：最小的 N（≥ 0 次通关的最小样本量），使真实率 = tol 的线
    以 ≥ power 的概率通过（通过 = 上界 ≤ p，即通关次数 ≤ max_clears）。"""
    a = alpha / family_size
    n = n_cert(family_size, alpha, p)
    while _binom_cdf(max_clears(n, a, p), n, tol) < power:
        n += 1
    return n


def clopper_pearson_upper(k: int, n: int, alpha: float) -> float:
    """单侧上界；k=0 时的闭式，其它 k 用二分搜 Beta 分位（不依赖 scipy）。"""
    if n == 0:
        return 1.0
    if k == 0:
        return 1 - alpha ** (1 / n)
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def clopper_pearson_two_sided(k: int, n: int, conf: float = .95) -> tuple[float, float]:
    """双侧 Clopper–Pearson 区间（每侧 (1 − conf)/2）：上界 = clopper_pearson_upper(k, n, a/2)，下界由对称性
    1 − clopper_pearson_upper(n − k, n, a/2)。k = 0 时下界 0，k = n 时上界 1。"""
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else 1 - clopper_pearson_upper(n - k, n, a)
    hi = 1.0 if k == n else clopper_pearson_upper(k, n, a)
    return lo, hi


def r1_gate_12(wins: int, n: int) -> dict:
    """登记 12 的 R1 硬门：点估计 wins/n ≥ R1_MIN_12（n 必须是声明的 R1_N_12）。返回计数、率、双侧 95% CP 区间和判定。"""
    if n != R1_N_12:
        raise ValueError(f"R1 门声明 n = {R1_N_12}，这里 n = {n}")
    lo, hi = clopper_pearson_two_sided(wins, n)
    return dict(wins=wins, n=n, rate=wins / n, ci95=[lo, hi], min=R1_MIN_12, stream=R1_STREAM_12, passes=wins / n >= R1_MIN_12)


def _binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def code_fingerprint(root: pathlib.Path | None = None) -> dict:
    root = root or pathlib.Path(__file__).parent
    out = {}
    for f in sorted(root.glob("*.py")):
        if f.name.startswith("test_"):
            continue
        out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
    return out
