"""惩罚阶梯（penalty ladder）—— 用户 2026-11-03 夜的决定，运行时补丁，不改 core/，不改任何已有文件。

用户原话：「教学可以234 考试可以248 boss是2 8 死」。
「第 k 次错」= 这一场里同一种机制第 k 次罚到你（每场重新数；boss 是一场；每种机制各数各的）。倍数乘在敌人的「普通一击」上：

            k=1                         k=2   k>=3
  teach     x2                          x3    x4
  test      x2                          x4    x8
  boss      x2，但不致死（会打到 <= 0     x8    死
            时只留 1 血）

v2（11-03 夜，用户决定 1–5，见 describe() 的 decisions）：
  1. 阶梯下穿透的「记仇」整条关掉：没有任何一击再乘 pierce_grudge（阶梯那一击、吃过 2 面盾以后的普通一击都不乘）。
  2. boss 动量的「死」照旧：到了死那一格，那一 END 举着盾也救不了（先落下、再清零，momentum_resets_before_hit 仍是 0）；闪照旧能躲。
  3. 动量按场累计（同另外四种）：第一个没举盾的 END 只是警告（印出的攻击涨了，不罚，引擎原样）；之后每个「这一击带动量惩罚」的 END
     （END 之前的连续计数 >= 1；引擎：加成在 END 落下，打完才清零）是这一场的下一个 k，举盾不把 k 清零。v2 里闪掉的那个 END 也算
     （判据只看连续计数 >= 1）—— v3 改成不算（决定 5，下面）。印出的攻击 = 这一 END 盾 / 闪之前会落下的那一击：连续计数 >= 1 时
     = 普通一击 x L(tier, k+1)（k = 这一场已经落下的动量惩罚数），否则 = 普通一击。动量计数上限回到引擎的 2（TUNING 一个键也不改）。
  4. 逐场计数挂在 Fight 对象上（不可变的值：int / tuple / 只换不改的 dict），copy.deepcopy(fight) 和 copy.copy(fight) 都带着走、
     副本和原对局之后各走各的（antagonist_boss_check._survival_lines 深拷贝对局）。
v3（11-04；用户 11-03 夜同意、docs/antagonist_boss/13_penalty_ladder.md §3「闪掉的不算一次」，§5 的待办）：
  5. 动量同蓄力：只有真落下的惩罚才算一次。连续计数 >= 1 的 END 被闪掉 → 这一场的动量 k 不变（不记事件、不进 STATS）；连续计数照引擎走：
     闪不是举盾，计数接着涨（上限 2），所以下一个 END 还是这一个 k 的那一击（印出的攻击也不变）。举着盾的 END 照旧算（盾挡一部分，惩罚落下，
     打完清零），决定 3 的其余部分（第一个没举盾的 END 只警告、按场累计、举盾不清 k、boss k>=3 死、举着盾也救不了）不变。
     v2 的「闪掉的也算」可由核对的反证临时打开（DODGED_MOMENTUM_COUNTS = True），看哪些行失败。
v3.4（11-04；用户：「boss的标记放宽一点，毕竟这个是要试的，试错机会太少，直接打死了不太符合逻辑」；lead 选的做法，用户可以推翻）：
  6. 开关 PROTO_LADDER_MARK（本模块读，同 PROTO_LADDER_TABLE，不进 antagonist_proto._now()）：fight（默认 = v3.3，逐字节不变）/ percode。
     percode 只改 boss 的标记：k = 这一场里「这个代号」（出牌那一刻引擎的 ("them", "mark")）已经罚过你的次数 + 1，于是每个新代号的第一下都是
     k=1（u1104b：x3 不致死），同一个代号重复才往上爬 x9、x27、死。地图（teach / test）的标记照旧按场数；另外四种机制不变。
     逐代号的计数挂在 Fight 上（_ladder_mark_codes = 这一场每次标记打中时的代号，按先后的 tuple，不可变，深拷贝 / 浅拷贝带着走；两种设置下
     都记，只有 percode 在 boss 上读它）。percode 下标记事件另记 code / counting 两个键（默认下事件逐字不变）。核对的反证可临时把
     MARK_COUNTING 设回 "fight"，看哪些行失败。

每种机制怎么接到引擎上（core/adventure.py；行号是 2026-11-03 的）：
  charge   k = 这一场已经落下（没被闪掉）的大招数 + 1。大招 = 普通一击 x L，照旧穿盾，闪照旧能躲。
           替换 big_mult 定价、boss 的 big_frac 70 % 下限和 big_lethal。
  pierce   k = 这一场被吃掉的盾数 + 1（fed + 1；闪掉的那一下引擎照样吃盾，照样算）。END 时举着盾：普通一击 x L，穿盾。
           替换探针 x2 / pierce_mult 定价；记仇关掉（决定 1）。
  mark     k = 这一场被标记打中的次数 + 1（mark_hits + 1）；PROTO_LADDER_MARK=percode 下 boss 改成 k = 这一场这个代号打中的次数 + 1（决定 6）。
           出了被标的牌：max(1, 敌人攻击槽) x L，当场扣血；
           盾和闪照旧没用；那张牌照旧在挨打之后生效。替换 mark_probe_mult / priced(mark_mult)。
  guard    k = 这一场被反弹的次数 + 1（reflected + 1）。反弹 = 你这一下攻击的伤害 x L。替换 guard_probe_mult / priced(guard_mult)。
  momentum k = 这一场已经落下的动量惩罚数 + 1（决定 3、5：闪掉的不算）。END 那一击 = 普通一击 x L（连续计数 0 = 普通一击，不算一次）。经
           Fight.momentum_bonus 实现，所以印出的敌人攻击 = 盾 / 闪之前落下的那一击（用户的规则：印出的攻击 = 当前威胁）。
           boss「死」= 一击 2 x 上限血（照旧按 END 一击结算：闪能救，11 点的盾救不了）。替换 momentum_probe_ratio /
           momentum_full_ratio 和 momentum_boss_frac。
  ward     没有伤害，不在阶梯上。
  「普通一击」= 引擎的 cur = 敌人攻击 + 怒气 x 停顿数 + 威胁加成（动量除外），不乘记仇（Enemy.hit_now 的第一行，用
  hit_now(fed=0, parts=()) 求，不抄公式）。动量的普通一击 = 敌人攻击 + 怒气 x 停顿数 + 激怒 / 贪食加成（原型里都是 0）。
  PROTO_RAGE=off（antagonist_proto，13 §4b）下敌人 rage = 0，普通一击就是敌人攻击（本模块不看开关，读的是同一个 enemy.rage）。
  「死」：charge / pierce（穿盾的）→ 引擎的致死标记，没闪掉就血正好归 0，不管多少血、多少盾；
          mark / guard（直接扣血）→ 这一下之后血置 0，是最终的：被标的治疗在挨打之后照旧回血，但回不来（见 describe 的 open）；
          momentum → 一击 2 x 上限血，按普通 END 一击结算（盾先吸收、闪全躲），血会是负数（与引擎平常的致死一击一样）。
  「不致死」（boss k=1）：这一下结算后血 <= 0、而之前血 > 0，就留正好 1 血；没打到 <= 0 就原样。END 一击在盾 / 闪之后判；
          标记那一下在牌的效果之前判（标记的治疗：留 1 血，再回血）。地图（teach / test）的 k=1 没有这一条：照样能打死。
  阶层：is_boss → boss；否则按 enemy.punish（teach_punish_pct=50 → teach，test_punish_pct=250 → test；别的值报错）。

实现（install() 装、remove() 撤，幂等；撤的时候把 Fight 上换掉的 5 个属性还原成装之前的同一个对象）：
  Fight._incoming        先照引擎原样算（这一次调用里临时 pierce_grudge=1、boss 下限 momentum_boss_frac / big_frac 置 0），再把
                         charge 大招、pierce 举盾那一击换成阶梯值。
  Fight.momentum_bonus   阶梯版加成（印出的攻击和伤害读同一个量，引擎原有的设计）。
  Fight.end_turn         包一层：这一 END 期间临时设 TUNING（momentum_boss_frac=0、big_frac=0、big_lethal / pierce_boss_lethal 只在
                         阶梯说「死」时为 1），临时换 adventure.settle_attack 为「不致死」版本（只在 boss k=1 时生效）并记下这一 END
                         实际结算的一击；真结算那一次（第一次调用）当场给 charge / momentum（都只算没闪掉的）的逐场计数加一，于是 END 末尾
                         引擎印攻击槽时读到的已经是新的 k。全部在 finally 里还原。
  Fight.release_committed 同上（引擎只在 end_turn 里调它；直接调也走同一套）。
  Fight.play             出被标记的牌 / 守相上攻击时：临时让引擎走「探针」分支、探针倍数 = 阶梯倍数（TUNING 的 mark_probe_mult /
                         guard_probe_mult、boss_no_probe=0、punished[5] / punished[4] 置 0，调用后按引擎的增量还原），于是扣血的次序与
                         引擎完全相同（先挨打、再生效）；不致死 / 死在调用之后改血。
  计数：next_k(f, mech) 是唯一的「下一次是第几次」（核对的反证会临时换掉它）；counts(f) 给五种机制这一场已经罚过的次数。
  不改的：TUNING 在 END / 出牌 / _incoming 之外一个键也不改；momentum_cap 一直是引擎的 2。
  次序：先 antagonist_proto.setup() / antagonist_boss.setup_boss()，再 install()；先 remove()，再 teardown_boss()。
  teardown_boss() 会把 end_turn 换回它装之前的对象，盖掉本模块的包装；remove() 发现属性不是自己的就报错，不悄悄还原。

v3.5（11-04 晚，docs/antagonist_boss/18_candidate_v3_spec.md §2–§3；用户「主要要看在已知规则的情况下，要花多久才能识别出来模式」）：
  7. 表可以按机制给行：表的键除了三个阶层（teach / test / boss = 这一阶层的回落行），还可以有 "机制/阶层"（例如 "charge/test"）；
     (机制, 阶层) 有自己的行就用它，否则用这一阶层的回落行。step(tier, k, table=None, mech=...) 必须给机制（ward 不在阶梯上，给 ward 报错）；
     本模块内部和每个调用方都传。旧表（v1 / t16 / u1104 / u1104b）没有机制行，每种机制都用阶层行 —— 结果与 v3.4 逐格相同，
     describe() 的 table / table_sha16 也逐字相同（_table_text 只多出机制行）。
     新表 v3（spec §3）：
                 教学             考试              boss
       charge    x2 / x3 / x4     x8 / x16 / x32    x9 / x27 / 死                     用户同意（boss 第一下没有「不致死」：spec 没写）
       guard     x2 / x3 / x4     x2 / x8 / x16     x3（不致死）/ x9 / x27 / 死       用户同意
       momentum  x2 / x3 / x4     x2 / x4 / x16     x3（不致死）/ x9 / x27 / 死       考试是用户的；教学、boss 是 lead 的默认
       mark      x2 / x2 / x3     x2 / x3 / x4      x2（不致死）/ x3 / x4 / x6        lead 的默认（boss 那一行没有死：第 4 次起封顶 x6）
       阶层回落行 = u1104b（教学 2/3/4、考试 2/8/16、boss 3（不致死）/9/27/死）：只有穿透用它（v3 下 PROTO_POOL=nopierce 把穿透拿出池子，
       lead 选的回落，spec 没给穿透的数）。ward 不在阶梯上。
  8. 开关 PROTO_MOMENTUM（本模块读、实现；登记 / 记录 / 文件名 / 参与者入口的拒绝在 antagonist_proto / proto_play，那边把默认叫 ramp，
     本模块把 ramp 读成 streak）：streak（默认 = v3.4，逐字节不变）/ noshield（spec §2「动量：回合结束没举盾就挨罚」）：
       · END 时没举盾（结算那一刻 block == 0）、也没闪 → 这一下 = 普通一击 x L(momentum, 阶层, k)，k = 这一场这样被罚过的次数 + 1；
       · END 时举着盾 → 只挨普通一击（盾照常吸收），不算一次；
       · 没举盾但闪了 → 躲掉，不算一次（DODGED_MOMENTUM_COUNTS 的反证照样适用）；
       · 没有警告（第一个没盾的 END 就罚）、没有连续计数、没有斜坡：Fight.momentum_bonus 恒为 0，于是印出的敌人攻击 = 普通一击（不预告），
         Fight._incoming()[0] 也是普通一击（PROTO_THREAT=momentum 印的就是它）；
       · boss「死」那一格：一击 2 x 上限血（没盾才会落到这一格；闪能躲）；boss k=1 不致死只在这一下被罚时起作用。
       · 怎么接：倍数不在 _incoming 里（那样印出的 / 预测的一击会带上惩罚），而在 END 的 settle_attack 包装里：每一次结算调用（真结算 + 引擎的
         两次反事实审计）按这一次调用的盾判 —— block == 0 → 那一击换成普通一击 x L（k 在这一 END 开始时定，三次调用同一个 k），所以引擎的
         「举盾 vs 不举盾」审计（blind_turns 等）看到的正是这条规则；只在第一次（真结算）调用上、没被闪掉时给逐场计数加一。
       · 引擎自己的连续计数 Fight.momentum 照引擎走（阶梯一个也不读它），引擎的逐命账 punished[3] 仍按引擎的连续计数 >= 2 记
         （两种模式下都不是阶梯的次数，同 v3.4 的 unchanged）。核对的反证可临时把 MOMENTUM_MODE 设回 "streak"，看哪些行失败。

v3.6（11-05，docs/antagonist_boss/18_candidate_v3_spec.md §8.1–§8.4；候选 v3b）：
  9. 反击上阶梯（"counter" 是第六种可定价的机制，EXTRA_MECHANICS；旧表没有反击行，旧代码路径一格也不变）。新表 v3b = v3 + 反击行（同守势）：
       counter   x2 / x3 / x4     x2 / x8 / x16     x3（不致死）/ x9 / x27 / 死       lead 的默认、用户「可以先试试」（§8.1、§8.4）
  10. 开关 PROTO_COUNTER（本模块读、实现；登记在 antagonist_proto）：engine（默认 = 引擎原规则，逐字节不变）/ nodouble（§8.2–§8.3）：
       · 同一回合里攻击和增伤都出了（先后不限），第二张出手的当下：(a) 增伤这一回合无效（增伤先出 → 攻击按普通伤害算；攻击先出 → 什么也不变，
         增伤旗当场清掉）；(b) 当下直接扣血 = 普通一击 x L(counter, 阶层, k)，盾、闪都没用，k = 这一场这样被罚过的次数 + 1；
         boss「死」那一格 = 血归 0（同标记 / 守势）；不致死那一格 = 打到 <= 0 时留 1 血。
       · 引擎回合末的反击重击关掉：回合末那一击是普通一击（_incoming 与 END 期间把 offences 压到 <= 1 再交给引擎；END 之后 last_offences 还原成真值）。
       · 计数挂在 Fight 上（_ladder_ctr）；每次罚也加引擎的 countered / punished[1]（逐命账与 Trace 的事件照旧有「反击」这一项）。没有槽位、没有随机。
  11. boss 换阶段（§8.4「boss 切换的时候就不能太疼」）：表 v3b 下，boss 第二阶段那种机制（第一阶段没有的）的第一次罚一律 x3 不致死 —— 那一行
       第一格已经是 x3（不致死）就照旧，否则在前面加这一格（蓄力：x3 不致死 / x9 / x27 / 死）；之后照这一行走；第一阶段的计数本来就各数各的、不带过来。
       只在 HANDOVER 为真时；11-05 用户「boss 不急，先做地图」→ 默认 False，任何表下都不生效（写好未启用）。step_for(f, mech, k=None)
       给外部读者同一个格（含这一条）。
v3.8（11-05 夜，docs/antagonist_boss/18_candidate_v3_spec.md §8.7、26_momentum_shieldonly.md；用户「可以，动量也是好改法」）：
  12. PROTO_MOMENTUM 的第三个值 shieldonly（默认 streak、noshield 逐字节不变；版本串只在 shieldonly 下换成 v3.8）：
       · 同 noshield，只差一条：END 时没举盾（结算那一刻 block == 0）→ 罚，**闪避不再躲开它**：这一下 = 普通一击 x L(momentum, 阶层, k)，
         照常算一次（k = 这一场这样被罚过的次数 + 1）；闪了也一样（没盾的那一次结算按「没闪」结算）。
       · 举着盾 → 只挨普通一击（盾照常吸收），不算一次；举着盾又闪（固定手牌下出不来：闪 2 费 = 整回合）→ 同 noshield（盾吸收、闪躲开）。
       · 其余（没有警告、没有斜坡、印出的攻击 = 普通一击、boss 死那一格、不致死那一格、引擎的连续计数不读）照 noshield。
       · 怎么接：noshield 的 settle_attack 包装里，block == 0 的那一次结算调用把 dodge 当成 False 交给引擎的 settle_attack（真结算和两次
         反事实审计同一条规则）。逐 END 记录 last_end 多一个键 dodge_voided（只在 shieldonly 下有）；记录的 dodged 是生效的闪（被作废的记 False）。
       · momentum_noshield(f) 在 noshield 和 shieldonly 下都为真（「END 没举盾就罚」这一族）；momentum_shieldonly(f) 只在 shieldonly 下为真。
v3.9（11-06，docs/antagonist_boss/18_candidate_v3_spec.md §8.8、27_counter_noblock.md；用户「我们要改动一下无槽位的机制，让他们俩的应对方式不能一样」，
     lead 的方案、用户「可以先试试」）：
  13. PROTO_COUNTER 的第三个值 noblock（试用；默认 engine、nodouble 逐字节不变；版本串只在 noblock 下换成 v3.9）：
       · 同一回合里攻击和举盾都出了（先后不限），第二张出手的当下：(a) 当下直接扣血 = 普通一击 x L(counter, 阶层, k)，盾、闪都没用，
         k = 这一场这样被罚过的次数 + 1（行同 nodouble：教学 2/3/4、考试 2/8/16）；boss 死那一格 = 血归 0、不致死那一格 = 留 1 血（boss 不做，同 nodouble）；
         (b) 这一回合的盾作废：那一刻盾置 0，这一回合之后再出的盾牌不给盾（固定手牌下一回合每种牌只能出一次，只在构造里出现），所以回合末那一击全吃
         （普通一击；没有回合末的反击重击）。
       · 攻击照常打出伤害（增伤照常翻倍：攻击 + 增伤对反击怪合法，不罚）。
       · 引擎回合末的反击重击照样关掉（攻击 + 增伤 = 两次进攻，引擎会在回合末加重击）：沿用 nodouble 的 _counter_masked（交给引擎的 offences 压到 <= 1，
         END 跑完时引擎清零就保持 0 —— v3.7 的修复，A7 每回合清零；END 之后 last_offences 还原真值）。nodouble 的出牌罚（counter_would_fire /
         _counter_play）在 noblock 下一步也不走（counter_nodouble(f) 为假）。
       · 计数挂在 Fight 上（同一个 _ladder_ctr）；作废的回合记在 _ladder_ctr_void（回合号）；每罚一次也加引擎的 countered / punished[1]。没有槽位、没有随机。
       · counter_ladder(f)：nodouble 或 noblock 下这一阶段有反击；counter_noblock(f)、noblock_would_fire(f, kind) 给外部读者（C10、参照的核对）。
v3.10（11-06，docs/antagonist_boss/18_candidate_v3_spec.md §8.9、30_counter_probe_x1.md；用户「试试 a 先」）：
  14. 新表 v3c1 = v3b，只换反击的教学、考试两行的第一格：教学 1/3/4、考试 1/8/16（每场第一次罚 x1 = 当下扣 1 x 普通一击；noblock 下盾照样作废）；
       boss 的反击行、别的行全同 v3b。别的表（v1 / t16 / u1104 / u1104b / v3 / v3b）逐字节不变；版本串只在 PROTO_LADDER_TABLE=v3c1 下换成 v3.10。
v3.11（11-06，docs/antagonist_boss/18_candidate_v3_spec.md §8.10、32_boss_v1.md；用户「可以」：boss 第一版）：
  15. 新表 v3c1b = v3c1，只换 boss 的反击行：1（不致死）/ 9 / 27 / 死（反击作第一阶段时第一次罚也 x1 不致死）。教学、考试的行（地图）与 v3c1 逐格相同。
  16. 表 v3c1b 下换阶段规则生效（HANDOVER = True；HANDOVER_TABLES）：第二阶段那种机制（第一阶段没有的）在 boss 上的第一次罚 —— 反击 x1、其他 x3，
       都不致死（打到 <= 0 留 1 血）；之后照该机制的 boss 行第一格之后的格（蓄力 3nl / 9 / 27 / 死；守势、动量 3nl / 9 / 27 / 死；反击 1nl / 9 / 27 / 死）；
       计数每种机制各数各的，第一阶段的不带过来。handover_step_v3c1b / handover_row_v3c1b；step_for 走它。别的表下（含核对临时打开 HANDOVER）照 v3.6。
       版本串只在 PROTO_LADDER_TABLE=v3c1b 下换成 v3.11；别的表逐字节不变。
公开接口：LADDER、Step、step(tier, k, table=None, mech=...)、row(tier, mech, table=None)、tier_of(f)、next_k(f, mech)、counts(f)、install(table=None)、
          remove()、installed()、describe()、last_end(f)、events(f)、big_landed(f)、momentum_punished(f)、stats()、reset_stats()、VERSION；
          v3.4：MARK_COUNTING、mark_per_code(f)、mark_code(f)、mark_code_hits(f)；v3.5：TABLES["v3"]、MOMENTUM_MODE、MOMENTUM_MODES、
          momentum_noshield(f)、has_mech_rows(table)；v3.8：momentum_shieldonly(f)、NOSHIELD_FAMILY。
用法：python3 -B scripts/penalty_ladder.py  → 打印 describe()（不装）。核对：PROTO_HAND=fixed python3 -B scripts/ladder_check.py out.json"""
import collections, contextlib, hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "core"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VERSION = "penalty-ladder-v3.7-2026-11-05"   # v3.7：nodouble 下 END 之后 offences 不再被还原（A7 跨回合涨的缺陷，v3b_rule_check R10b）。v3.6：反击上阶梯（表 v3b、PROTO_COUNTER=nodouble）、boss 第二阶段第一罚 x3 不致死（HANDOVER，写好、默认关：boss 先不做）；
                                             #       旧表 + PROTO_COUNTER=engine = v3.5 的行为（只有版本串变）
                                             # v3.5：按机制的行（表 v3，决定 7）、PROTO_MOMENTUM=noshield（决定 8）；旧表 + 默认 streak = v3.4 的行为
VERSION_V311 = "penalty-ladder-v3.11-2026-11-06"   # v3.11：表 v3c1b（boss 第一版：boss 反击行 1 不致死 / 9 / 27 / 死 + 换阶段第一下按机制，18 §8.10）；只在 PROTO_LADDER_TABLE=v3c1b 下是现在的版本串
VERSION_V310 = "penalty-ladder-v3.10-2026-11-06"   # v3.10：表 v3c1（反击每场第一次罚 x1，18 §8.9）；只在 PROTO_LADDER_TABLE=v3c1 下是现在的版本串
VERSION_V39 = "penalty-ladder-v3.9-2026-11-06"   # v3.9：PROTO_COUNTER=noblock（同回合攻击 + 举盾，第二张出手的当下罚、盾作废，18 §8.8）；只在 noblock 下是现在的版本串
VERSION_V38 = "penalty-ladder-v3.8-2026-11-05"   # v3.8：PROTO_MOMENTUM=shieldonly（闪避不再躲开动量的罚，18 §8.7）；只在 shieldonly 下是现在的版本串
VERSION_V35 = "penalty-ladder-v3.5-2026-11-04"   # v3.5：按机制的行（表 v3，决定 7）、PROTO_MOMENTUM=noshield（决定 8）；旧表 + 默认 streak = v3.4 的行为
                                             # v3.4：PROTO_LADDER_MARK=percode（boss 的标记按代号数 k，决定 6）；默认 fight = v3.3 的行为
                                             # v3.3：备选表 u1104b（用户 11-04 上午：教学改回 2/3/4，考试、boss 同 u1104）；describe 的 user_words 按表记
                                             # v3.2：备选表 u1104（用户 11-04 上午：教学 2/4/8、考试 2/8/16、boss 3（不致死）/9/27/死），默认 v1 不变
                                             # v3.1：备选表 t16（考试 2/4/8/16，用户 11-04 提议），PROTO_LADDER_TABLE 选表，默认 v1 不变；每行可多于 3 格（最后一格封顶）
                                             # v3：闪掉的动量 END 不算一次（决定 5）
TIERS = ("teach", "test", "boss")
MECHANICS = ("charge", "pierce", "mark", "guard", "momentum")   # ward 不在阶梯上
EXTRA_MECHANICS = ("counter",)   # v3.6：反击（候选 v3b）；旧表没有它的行，describe() 只在表里有反击行时提它
ALL_MECHANICS = MECHANICS + EXTRA_MECHANICS
DEATH_HIT_MAX_HP = 2             # 动量「死」的数额 = 2 x 上限血（印出 / 落下的就是它；charge / pierce 另走致死标记）
GRUDGE_OFF = True                # 决定 1：阶梯下记仇关掉（核对的反证会临时把它设成 False，看记仇回来时哪些行失败）
DODGED_MOMENTUM_COUNTS = False   # 决定 5（v3）：闪掉的动量 END 不算一次（核对的反证会临时把它设成 True = v2 的规则，看哪些行失败）

# 逐场计数挂在 Fight 实例上（决定 4）。值都是不可变的（int / tuple / 只整体替换的 dict），所以浅拷贝的副本加一时也不会改到原对局。
_A_BIG, _A_MOM, _A_EVENTS, _A_LAST = "_ladder_big", "_ladder_mom", "_ladder_events", "_ladder_last_end"
_A_MCODES = "_ladder_mark_codes"   # v3.4：这一场每次标记打中时的代号（tuple，按先后）
_A_CTR = "_ladder_ctr"             # v3.6：这一场 PROTO_COUNTER=nodouble 罚过的次数（v3.9：noblock 同一个计数）
_A_CTR_VOID = "_ladder_ctr_void"   # v3.9：noblock 下这一场盾被作废的那一回合（回合号；之后再出的盾牌这一回合不给盾）


class Step(collections.namedtuple("Step", "mult nonlethal death")):
    """阶梯的一格：mult = 倍数（死时 None）；nonlethal = 打到 <= 0 时留 1 血；death = 死。"""
    __slots__ = ()

    def label(self):
        if self.death:
            return "death"
        return f"x{self.mult}" + (" (never lethal: leaves 1 hp)" if self.nonlethal else "")


def _S(mult, nonlethal=False):
    return Step(int(mult), bool(nonlethal), False)


DEATH = Step(None, False, True)
LADDER = {                       # k=1, k=2, k>=3
    "teach": (_S(2), _S(3), _S(4)),
    "test": (_S(2), _S(4), _S(8)),
    "boss": (_S(2, nonlethal=True), _S(8), DEATH),
}

LADDER_T16 = dict(LADDER, test=(_S(2), _S(4), _S(8), _S(16)))   # 用户 11-04 提议：考试关每次翻倍，第 4 次起封顶 16；教学、boss 不变
# 用户 11-04 上午：「伤害系数改成教学2，4，8封顶 考试2，8，16 封顶 boss 3，9，27然后直接死 血量先不动」。boss 第一下照用户 11-03 夜的话不致死
# （「第一次试探可以比考试关伤害高一些但不致死」）——这一条是 lead 沿用的，用户可以推翻。
LADDER_U1104 = dict(teach=(_S(2), _S(4), _S(8)), test=(_S(2), _S(8), _S(16)), boss=(_S(3, nonlethal=True), _S(9), _S(27), DEATH))
LADDER_U1104B = dict(LADDER_U1104, teach=LADDER["teach"])   # 用户 11-04 上午：「那教学改成2，3，4呢」——教学 2/3/4，考试 2/8/16、boss 3（不致死）/9/27/死同 u1104
# 决定 7（v3.5）：spec 18 §3 的按机制表。三个阶层键 = 回落行（u1104b，只有穿透用：v3 下穿透出池）；"机制/阶层" = 那一种机制自己的行。
LADDER_V3 = dict(LADDER_U1104B, **{
    "charge/teach": (_S(2), _S(3), _S(4)), "charge/test": (_S(8), _S(16), _S(32)), "charge/boss": (_S(9), _S(27), DEATH),
    "guard/teach": (_S(2), _S(3), _S(4)), "guard/test": (_S(2), _S(8), _S(16)), "guard/boss": (_S(3, nonlethal=True), _S(9), _S(27), DEATH),
    "momentum/teach": (_S(2), _S(3), _S(4)), "momentum/test": (_S(2), _S(4), _S(16)),
    "momentum/boss": (_S(3, nonlethal=True), _S(9), _S(27), DEATH),
    "mark/teach": (_S(2), _S(2), _S(3)), "mark/test": (_S(2), _S(3), _S(4)), "mark/boss": (_S(2, nonlethal=True), _S(3), _S(4), _S(6))})
# v3.6（候选 v3b，spec 18 §8.1 / §8.4）：v3 + 反击行（同守势）。标记行照 v3 留着（v3b 的池里没有标记，用不到）；穿透同 v3（回落行）。
LADDER_V3B = dict(LADDER_V3, **{
    "counter/teach": (_S(2), _S(3), _S(4)), "counter/test": (_S(2), _S(8), _S(16)),
    "counter/boss": (_S(3, nonlethal=True), _S(9), _S(27), DEATH)})
# v3.10（候选 v3c 的试验，spec 18 §8.9，用户「试试 a 先」）：v3b，只把反击教学、考试两行的第一格换成 x1（每场第一次罚 = 1 x 普通一击）。boss 行不动。
LADDER_V3C1 = dict(LADDER_V3B, **{"counter/teach": (_S(1), _S(3), _S(4)), "counter/test": (_S(1), _S(8), _S(16))})
# v3.11（boss 第一版，spec 18 §8.10，用户「可以」，2026-11-06）：v3c1，只把 boss 的反击行第一格换成 x1 不致死（反击作第一阶段时第一次罚 x1 不致死，
# 与地图上「要试的机制倍数低」一致）：boss 反击 1（不致死）/ 9 / 27 / 死。教学、考试的每一行（地图）与 v3c1 逐格相同。表 v3c1b 下换阶段规则（决定 11 的
# v3c1b 版，HANDOVER_TABLES）同时生效。只在 PROTO_LADDER_TABLE=v3c1b 下用到；别的表逐字节不变。
LADDER_V3C1B = dict(LADDER_V3C1, **{"counter/boss": (_S(1, nonlethal=True), _S(9), _S(27), DEATH)})
TABLES = {"v1": LADDER, "t16": LADDER_T16, "u1104": LADDER_U1104, "u1104b": LADDER_U1104B, "v3": LADDER_V3, "v3b": LADDER_V3B, "v3c1": LADDER_V3C1,
          "v3c1b": LADDER_V3C1B}
USER_WORDS = {"v1": "教学可以234 考试可以248 boss是2 8 死",
              "t16": "那考试2，4，8，16呢（教学、boss 同 v1）",
              "u1104": "伤害系数改成教学2，4，8封顶 考试2，8，16 封顶 boss 3，9，27然后直接死 血量先不动呢（boss 第一下不致死沿用 11-03 夜）",
              "u1104b": "那教学改成2，3，4呢（考试、boss 同 u1104）",
              "v3": "主要要看在已知规则的情况下，要花多久才能识别出来模式，如果要试很久就不该给高倍率，很明显甚至不用额外试的就该给高倍率；"
                    "蓄力 教学 2/3/4、考试 8/16/32、boss 9/27/死，守势 教学 2/3/4、考试 2/8/16、boss 3（不致死）/9/27/死（用户同意）；"
                    "动量 考试 2/4/16（用户）；动量教学 / boss、标记三行是 lead 的默认（docs/antagonist_boss/18_candidate_v3_spec.md §3）；"
                    "穿透用阶层回落行（u1104b，lead 选的）",
              "v3b": "那就把破势，反击拿回来，标记拿掉；反击的怪血量可以稍微少一点，不准用增伤吧；可以先试试（用户 2026-11-05）—— "
                     "反击行同守势（lead 的默认）；其余同 v3（boss 先不做，11-05 用户）",
              "v3c1": "试试 a 先（用户 2026-11-06，18 §8.9）：反击每场第一次罚 x1（教学、考试都是；盾照样作废），之后照旧（教学 x3/x4，考试 x8/x16）；"
                      "boss 不动；其余同 v3b",
              "v3c1b": "boss 第一版（用户 2026-11-06「可以」，18 §8.10）：换阶段第一下 —— 第二阶段机制在 boss 上的第一次罚反击 x1、其他 x3，都不致死，"
                       "之后照该机制的 boss 阶梯；反击作第一阶段时第一次罚也 x1 不致死；地图的行同 v3c1"}
TABLE_NAME = __import__("os").environ.get("PROTO_LADDER_TABLE", "v1")   # 筛选用；正式采用前不进 antagonist_proto 的开关
if TABLE_NAME not in TABLES:
    raise ValueError(f"PROTO_LADDER_TABLE={TABLE_NAME!r}：只能是 {tuple(TABLES)}")

# 决定 6（v3.4）：标记怎么数 k。fight = 这一场打中的次数（默认，v3.3）；percode = boss 上按代号数（地图照旧按场）。核对的反证会临时改它。
MARK_COUNTINGS = ("fight", "percode")
MARK_COUNTING = __import__("os").environ.get("PROTO_LADDER_MARK", "fight")
if MARK_COUNTING not in MARK_COUNTINGS:
    raise ValueError(f"PROTO_LADDER_MARK={MARK_COUNTING!r}：只能是 {MARK_COUNTINGS}")
MARK_USER_WORDS = "boss的标记放宽一点，毕竟这个是要试的，试错机会太少，直接打死了不太符合逻辑（用户 2026-11-04；按代号数是 lead 选的做法）"

# 决定 8（v3.5）：动量怎么罚。streak = v3.4（连续计数 >= 1 的 END 罚、第一个没盾的 END 只警告；默认，逐字节不变）；noshield = spec 18 §2
# （END 没举盾、没闪就罚，举盾 = 普通一击不算，闪 = 躲掉不算，没有警告、没有斜坡、印出的攻击 = 普通一击）。核对的反证会临时改它。
# antagonist_proto 登记这个开关时把默认叫 ramp（同一个东西 = v3.4 的斜坡 / 连续计数）：两个名字都读成 streak。
MOMENTUM_MODES = ("streak", "noshield", "shieldonly")   # v3.8：shieldonly = noshield + 闪避不躲开动量的罚（18 §8.7）
NOSHIELD_FAMILY = ("noshield", "shieldonly")              # v3.8：「END 没举盾就罚」这一族（没有斜坡、印出的攻击 = 普通一击）
MOMENTUM_ALIASES = {"ramp": "streak"}
_MOMENTUM_ENV = __import__("os").environ.get("PROTO_MOMENTUM", "streak")
MOMENTUM_MODE = MOMENTUM_ALIASES.get(_MOMENTUM_ENV, _MOMENTUM_ENV)
if MOMENTUM_MODE not in MOMENTUM_MODES:
    raise ValueError(f"PROTO_MOMENTUM={MOMENTUM_MODE!r}：只能是 {MOMENTUM_MODES}（ramp = streak 的别名）")
if MOMENTUM_MODE == "shieldonly":                 # v3.8：版本串只在 shieldonly 下换（streak / noshield 下逐字不变）
    VERSION = VERSION_V38
SHIELDONLY_USER_WORDS = "可以，动量也是好改法（用户 2026-11-05 晚，18 §8.7：回合末只认盾，闪避不再算躲开动量）"
# 决定 10（v3.6）：反击怎么罚。engine = 引擎原规则（回合末穿盾重击；默认，逐字节不变）；nodouble = spec 18 §8.2–§8.3（见模块说明 10）。
COUNTER_MODES = ("engine", "nodouble", "noblock")   # v3.9：noblock = 同回合攻击 + 举盾就罚、盾作废（18 §8.8，试用）
COUNTER_MODE = __import__("os").environ.get("PROTO_COUNTER", "engine")
if COUNTER_MODE not in COUNTER_MODES:
    raise ValueError(f"PROTO_COUNTER={COUNTER_MODE!r}：只能是 {COUNTER_MODES}")
if COUNTER_MODE == "noblock":                     # v3.9：版本串只在 noblock 下换（engine / nodouble 下逐字不变；shieldonly 同开时也是 v3.9）
    VERSION = VERSION_V39
if TABLE_NAME == "v3c1":                          # v3.10：版本串只在表 v3c1 下换（别的表下逐字不变）
    VERSION = VERSION_V310
if TABLE_NAME == "v3c1b":                         # v3.11：版本串只在表 v3c1b 下换（别的表下逐字不变）
    VERSION = VERSION_V311
NOBLOCK_USER_WORDS = ("我们要改动一下无槽位的机制，让他们俩的应对方式不能一样；可以先试试（用户 2026-11-06，18 §8.8：同一回合攻击和举盾都出了，"
                      "第二张出手的当下罚、这一回合的盾作废）")
COUNTER_USER_WORDS = ("不准用增伤吧；可以，那就是 double 无效的情况下还吃很多伤害；不规定顺序（用户 2026-11-05，spec 18 §8.2–§8.3）")
# 决定 11（v3.6）：boss 第二阶段那种机制的第一罚 x3 不致死。11-05 用户「boss 不急，先做地图」：写好、默认关（False），任何表下都不生效；
# 以后定了 boss 再开（核对可以临时设 True 看它的格）。
HANDOVER = False
HANDOVER_STEP = Step(3, True, False)
# v3.11（boss 第一版，18 §8.10，用户「可以」）：表 v3c1b 下换阶段规则生效（HANDOVER 在这张表下为真），第一下按机制：反击 x1 不致死、其他 x3 不致死；
# 之后照该机制的 boss 行：那一行第一格是不致死的试探格（守势 / 动量 3 不致死、v3c1b 的反击 1 不致死）→ 换成换阶段那一格，后面照旧（9 / 27 / 死）；
# 第一格不是不致死（蓄力 9 / 27 / 死）→ 在前面加这一格（3 不致死 / 9 / 27 / 死）。别的表（含 v3b 临时打开 HANDOVER 的核对）照 v3.6 的 handover_row。
HANDOVER_TABLES = ("v3c1b",)
HANDOVER_STEPS_V3C1B = dict(counter=Step(1, True, False))   # 其余机制 = HANDOVER_STEP（x3 不致死）
if TABLE_NAME in HANDOVER_TABLES:
    HANDOVER = True
HANDOVER_V3C1B_USER_WORDS = ("可以（用户 2026-11-06，18 §8.10）：第二阶段机制在 boss 上的第一次罚 —— 反击 x1、其他 x3，都不致死；之后照该机制的 boss 阶梯。"
                             "反击作第一阶段时第一次罚也 x1 不致死（与图上「要试的机制倍数低」一致）")
HANDOVER_USER_WORDS = "boss 切换的时候就不能太疼（用户 2026-11-05；第二阶段第一罚一律 x3 不致死是 lead 的落实，spec 18 §8.4）"
MOMENTUM_USER_WORDS = "还是把动量改成结束回合没盾就被干不做即时，但把倍数放到考试 2/4/16（用户 2026-11-04 晚；没有警告、boss 死那一格的数是 lead 的默认）"

_STATE = dict(installed=False, table=None)
_ORIG = {}                       # Fight 属性名 → 装之前的对象（F.__dict__ 里的那一个）
_MINE = {}                       # Fight 属性名 → 本模块装上的对象（remove 时核对）
STATS = collections.Counter()    # "mech/tier/k" → 用掉一个 k 的次数（见 events）；k>=4 记成 4+。进程级：深拷贝的副本上走的 END 也算进来
PATCHED = ("_incoming", "momentum_bonus", "end_turn", "release_committed", "play")
NEED = dict(big_ignores_block=1, punish_frac=0,             # 大招穿盾；地图上没有「重复错误的上限血下限」
            momentum_resets=1, momentum_resets_before_hit=0, momentum_quiet_reset=0,   # 举盾 → 打完再清零（决定 2、3 依赖这一条）
            boss_switch_keeps_bonus=0)                      # 换阶段时出场机制的计数归零（动量加成不带进穿透阶段）


# ---------------------------------------------------------------- 表
MECH_KEYS = tuple(f"{m}/{t}" for m in MECHANICS for t in TIERS)   # 决定 7：按机制的行的键（"机制/阶层"）
MECH_KEYS_ALL = MECH_KEYS + tuple(f"{m}/{t}" for m in EXTRA_MECHANICS for t in TIERS)   # v3.6：加反击（排在后面：旧表的规范形、文字、sha 不变）
MECH_KEYS_ALL += ("ward/boss",)   # 43 号文档 §14（修订 4，11-07）：破势只在 boss 上有行（PROTO_BOSS_STRIKE=probe1w 时 antagonist_boss 写进表）；没有这一行的表逐字不变
WARD_STRIKE = False               # 修订 4：antagonist_boss 装 probe1w 时置 True（boss 封着时出攻击牌 = 破势犯规，按张、出牌当下罚）；默认 False，什么也不变
WARD_COUNTERPROOF = None          # 核对的反证："ward_lethal_first" = 第一次就死；"ward_no_hit" = 不罚（只计数）；"ward_maps_too" = 图上也罚
_A_WARD = "_ladder_ward"          # 修订 4：这一场（这一阶段）破势罚过的次数


def _check_table(table):
    """表 → 规范形（三个阶层键在前，之后是有的机制行，按 MECHANICS × TIERS 的次序）。阶层键必须正好三个（回落行）；别的键只能是 "机制/阶层"。"""
    if not set(TIERS) <= set(table) or not set(table) <= set(TIERS) | set(MECH_KEYS_ALL):
        raise ValueError(f"阶梯表的键必须是阶层 {TIERS}（回落行，都要有）加上可选的 '机制/阶层'（{ALL_MECHANICS} × {TIERS}）：{sorted(table)}")
    keys = TIERS + tuple(k for k in MECH_KEYS_ALL if k in table)
    for t in keys:
        row = table[t]
        if len(row) < 3 or not all(isinstance(s, Step) for s in row):
            raise ValueError(f"{t}：至少 3 格 Step（k=1, k=2, …；最后一格封顶）：{row!r}")
        for s in row:
            if s.death:
                if s.mult is not None or s.nonlethal:
                    raise ValueError(f"{t}：死的一格不带倍数 / 不致死：{s!r}")
            elif not (isinstance(s.mult, int) and s.mult >= 1):
                raise ValueError(f"{t}：倍数要是 >= 1 的整数：{s!r}")
    return {t: tuple(table[t]) for t in keys}


def has_mech_rows(table):
    return any(k in table for k in MECH_KEYS_ALL)


def _table_text(table):
    # 旧表只有三个阶层键：与 v3.4 逐字相同（table_sha16 也相同）；按机制的表多出 "机制/阶层" 行（v3.6：反击行排在最后，v3 的文字不变）
    return {t: [s.label() for s in table[t]] for t in TIERS + tuple(k for k in MECH_KEYS_ALL if k in table)}


def _table_sha(table):
    return hashlib.sha256(json.dumps(_table_text(table), sort_keys=True).encode()).hexdigest()[:16]


def row(tier, mech, table=None):
    """(mech, tier) 的那一行：表里有 "mech/tier" 就用它，否则用阶层 tier 的回落行（决定 7）。mech 必须是阶梯上的机制（ward 不在）。"""
    table0 = table
    if mech == "ward" and tier == "boss" and "ward/boss" in (table or _STATE["table"] or TABLES[TABLE_NAME]):
        return (table or _STATE["table"] or TABLES[TABLE_NAME])["ward/boss"]   # 修订 4：只有表里有破势行（probe1w）时
    table = table0
    if mech not in ALL_MECHANICS:
        raise ValueError(f"阶梯只给 {ALL_MECHANICS} 定价（ward 不在阶梯上），不认识 mech={mech!r}")
    if tier not in TIERS:
        raise ValueError(f"阶层只能是 {TIERS}：{tier!r}")
    table = table or _STATE["table"] or TABLES[TABLE_NAME]   # v3.3：没装时按选中的表（原来退回 v1；ladder_table_check 的审查发现）
    return table.get(f"{mech}/{tier}", table[tier])


def step(tier, k, table=None, mech=None):
    """阶梯上 (mech, tier, k) 那一格。k >= 1；k 超过这一行的格数就用最后一格（v1 每行 3 格：k >= 3 都是第三格）。
    v3.5：mech 必须给（按机制的表每种机制一行；没给就报错，不悄悄用阶层行）。"""
    if k < 1:
        raise ValueError(f"k 从 1 起：{k}")
    if mech is None:
        raise ValueError("step() 要给 mech（v3.5：表可以按机制给行）")
    r = row(tier, mech, table)
    return r[min(k, len(r)) - 1]


def handover_on():
    """决定 11（v3.6）：boss 第二阶段第一罚 x3 不致死这一条生效没有（HANDOVER；默认 False：boss 先不做）。"""
    return bool(HANDOVER)


def handover_row(r):
    """第二阶段那种机制在 boss 上的行：第一格已经是 x3 不致死就照旧，否则在前面加这一格（决定 11）。"""
    return tuple(r) if r[0] == HANDOVER_STEP else (HANDOVER_STEP,) + tuple(r)


def handover_step_v3c1b(mech):
    """v3.11：表 v3c1b 下 mech 作第二阶段时在 boss 上的第一格（反击 x1 不致死，其他 x3 不致死）。"""
    return HANDOVER_STEPS_V3C1B.get(mech, HANDOVER_STEP)


def handover_row_v3c1b(r, mech):
    """v3.11：表 v3c1b 下第二阶段那种机制在 boss 上的行。r = 那种机制的 boss 行。第一格 = handover_step_v3c1b(mech)；之后照 r：
    r 的第一格是不致死的试探格 → 换掉它（守势 / 动量 3 不致死 / 9 / 27 / 死；反击 1 不致死 / 9 / 27 / 死）；否则在前面加（蓄力 3 不致死 / 9 / 27 / 死）。"""
    h = handover_step_v3c1b(mech)
    r = tuple(r)
    return (h,) + (r[1:] if r[0].nonlethal and not r[0].death else r)


def incoming_mech(f, mech):
    """mech 是不是这场 boss 第二阶段才进场的机制（已经换了阶段、第一阶段没有它）。只读引擎的阶段与两套规则（研究者侧 / 引擎侧）。"""
    if not (f.is_boss and getattr(f, "_phase2", False)):
        return False
    e = f.enemy
    return mech in e.parts_for(True) and mech not in e.parts_for(False)


def step_for(f, mech, k=None):
    """这一场对局上 (mech, k) 那一格（k 默认 = next_k(f, mech)）：同 step(tier_of(f), k, mech=mech)，另加决定 11（boss 第二阶段进场的机制，
    表 v3b：第一罚 x3 不致死）。本模块内部的每一次定价都走这里；外部读者（C10 等）也该用它。"""
    tier = tier_of(f)
    if k is None:
        k = next_k(f, mech)
    if tier == "boss" and handover_on() and incoming_mech(f, mech):
        if k < 1:
            raise ValueError(f"k 从 1 起：{k}")
        if TABLE_NAME in HANDOVER_TABLES:             # v3.11：表 v3c1b 的换阶段（按机制的第一格）；别的表照 v3.6
            r = handover_row_v3c1b(row("boss", mech), mech)
        else:
            r = handover_row(row("boss", mech))
        return r[min(k, len(r)) - 1]
    return step(tier, k, mech=mech)


def tier_of(f):
    """boss（is_boss）/ teach / test（按 enemy.punish 对 TUNING 的 teach_punish_pct / test_punish_pct）。认不出就报错。"""
    if f.is_boss:
        return "boss"
    from adventure import TUNING
    by = {TUNING["teach_punish_pct"]: "teach", TUNING["test_punish_pct"]: "test"}
    if len(by) != 2:
        raise ValueError("teach_punish_pct == test_punish_pct：认不出阶层")
    p = f.enemy.punish
    if p not in by:
        raise ValueError(f"enemy.punish={p} 既不是 teach 也不是 test（{by}）：阶梯不知道这一场是哪一层")
    return by[p]


# ---------------------------------------------------------------- 逐场计数（挂在 Fight 上）
def _get(f, name, default):
    return f.__dict__.get(name, default)


def momentum_noshield(f):
    """v3.5（决定 8）：这一场的动量是不是按「END 没举盾就罚」（PROTO_MOMENTUM=noshield 且这一阶段有动量）。"""
    return MOMENTUM_MODE in NOSHIELD_FAMILY and "momentum" in f.parts        # v3.8：shieldonly 也属于这一族


def momentum_shieldonly(f):
    """v3.8：这一场的动量是不是 shieldonly（END 没举盾就罚，闪避不躲开；PROTO_MOMENTUM=shieldonly 且这一阶段有动量）。"""
    return MOMENTUM_MODE == "shieldonly" and "momentum" in f.parts


def mark_per_code(f):
    """v3.4（决定 6）：这一场的标记是不是按代号数 k（PROTO_LADDER_MARK=percode 且是 boss）。"""
    return MARK_COUNTING == "percode" and bool(f.is_boss)


def mark_code(f):
    """此刻引擎的标记代号（("them", "mark")；0 = 还没标）。"""
    return f.state.get(("them", "mark"), 0)


def mark_code_hits(f):
    """这一场每次标记打中时的代号（tuple，按先后；装着阶梯时两种设置下都记）。"""
    return _get(f, _A_MCODES, ())


def counts(f):
    """这一场五种机制各已经罚过几次（= 下一次的 k - 1）。pierce / mark / guard 是引擎自己的逐场字段。
    v3.4：PROTO_LADDER_MARK=percode 下 boss 的 mark = 此刻这个代号这一场已经打中的次数（代号在 END 才重抽，回合内不变）。"""
    mark = mark_code_hits(f).count(mark_code(f)) if mark_per_code(f) else f.mark_hits
    out = dict(charge=_get(f, _A_BIG, 0), pierce=f.fed, mark=mark, guard=f.reflected, momentum=_get(f, _A_MOM, 0))
    if COUNTER_MODE in ("nodouble", "noblock"):    # v3.6：反击（nodouble 下才有这个键；默认下 counts() 逐字不变）；v3.9：noblock 同
        out["counter"] = _get(f, _A_CTR, 0)
    if WARD_STRIKE:                                # 修订 4：probe1w 下才有这个键
        out["ward"] = _get(f, _A_WARD, 0)
    return out


def next_k(f, mech):
    """这一场 mech 下一次罚你是第几次（k >= 1）。全模块只从这里取 k。"""
    return counts(f)[mech] + 1


def last_end(f):
    """这一场最近一个 END 的记录（装着时每个 END 都记）：mech / tier / k / step / hit（实际结算的一击，盾和闪之前）/ printed（END 前的攻击槽）/ ..."""
    return _get(f, _A_LAST, None)


def events(f):
    """这一场用掉过一个 k 的阶梯事件（END 的 charge（落下的）/ pierce（吃盾的，闪掉也算）/ momentum（连续计数 >= 1、落下的；v3 起闪掉的
    不算），出牌的 mark / guard），按先后。"""
    return list(_get(f, _A_EVENTS, ()))


def big_landed(f):
    return _get(f, _A_BIG, 0)


def momentum_punished(f):
    return _get(f, _A_MOM, 0)


def counter_punished(f):
    """v3.6：这一场 PROTO_COUNTER=nodouble 罚过的次数。"""
    return _get(f, _A_CTR, 0)


def counter_nodouble(f):
    """v3.6（决定 10）：这一场此刻的反击是不是按「同回合攻击 + 增伤，第二张出手的当下罚」（PROTO_COUNTER=nodouble 且这一阶段有反击）。"""
    return COUNTER_MODE == "nodouble" and "counter" in f.parts


def counter_noblock(f):
    """v3.9：这一场此刻的反击是不是按「同回合攻击 + 举盾，第二张出手的当下罚、盾作废」（PROTO_COUNTER=noblock 且这一阶段有反击）。"""
    return COUNTER_MODE == "noblock" and "counter" in f.parts


def counter_ladder(f):
    """v3.9：这一阶段的反击由阶梯管（nodouble 或 noblock）：引擎回合末的反击重击关掉（_counter_masked）。"""
    return counter_nodouble(f) or counter_noblock(f)


def noblock_would_fire(f, kind):
    """v3.9：出 kind 这一张（假设出得成）会不会触发 noblock 的反击：这一阶段有反击（noblock）、kind 是攻击 / 盾、这一回合还没出过 kind、另一种已经出过。
    只读公开的自己这一回合的出牌（played_kinds）和规则。"""
    if not counter_noblock(f) or kind not in ("attack", "block"):
        return False
    other = "block" if kind == "attack" else "attack"
    pk = f.played_kinds
    return pk.get(kind, 0) == 0 and pk.get(other, 0) >= 1


def block_void_now(f):
    """v3.9：noblock 下这一回合的盾已经被作废（这一回合之后出的盾牌不给盾）。"""
    return counter_noblock(f) and _get(f, _A_CTR_VOID, None) == f.turn


def counter_would_fire(f, kind):
    """出 kind 这一张（假设出得成）会不会触发 nodouble 的反击：这一阶段有反击、kind 是攻击 / 增伤、这一回合还没出过 kind、另一种已经出过。只读公开的
    自己这一回合的出牌（played_kinds）和规则。"""
    if not counter_nodouble(f) or kind not in ("attack", "buff_mark"):
        return False
    other = "buff_mark" if kind == "attack" else "attack"
    pk = f.played_kinds
    return pk.get(kind, 0) == 0 and pk.get(other, 0) >= 1


def _event(f, rec):
    setattr(f, _A_EVENTS, _get(f, _A_EVENTS, ()) + (rec,))
    _stat(rec["mech"], rec["tier"], rec["k"])


def stats():
    return dict(sorted(STATS.items()))


def reset_stats():
    STATS.clear()


def _stat(mech, tier, k):
    STATS[f"{mech}/{tier}/k{k if k < 4 else '4+'}"] += 1


# ---------------------------------------------------------------- 临时改动（都在 finally 里还原）
@contextlib.contextmanager
def _tuning(**kv):
    from adventure import TUNING
    old = {k: TUNING[k] for k in kv}            # 键不存在就 KeyError：宁可吵
    TUNING.update(kv)
    try:
        yield
    finally:
        TUNING.update(old)


@contextlib.contextmanager
def _swap(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


# ---------------------------------------------------------------- 阶梯的量
def _normal_end(f):
    """END 的普通一击：引擎自己的 cur（敌人攻击 + 怒气 x 停顿 + 威胁加成）—— hit_now 不带任何机制。fed=0：不乘记仇（决定 1）。"""
    hit, _ib = f.enemy.hit_now(f.stalls, 0, 0, fed=0 if GRUDGE_OFF else f.fed, bonus=f.threat_bonus, parts=())
    return hit


def _normal_momentum(f):
    return f.enemy.atk + f.enemy.rage * f.stalls + f.enrage_bonus + f.greed_bonus


def _death_hit(f):
    return DEATH_HIT_MAX_HP * f.max_hp


def _end_trigger(f):
    """这一 END 由哪种阶梯机制罚、k 是几；没有就 (None, 0)。只读状态。"""
    s, parts = f.state, f.parts
    trig = []
    if "charge" in parts and s[("them", "charge")] >= f.enemy.charge_max:
        trig.append(("charge", next_k(f, "charge")))
    if "pierce" in parts and s[("me", "block")] > 0:
        trig.append(("pierce", next_k(f, "pierce")))
    if "momentum" in parts and (s[("me", "block")] <= 0 if MOMENTUM_MODE in NOSHIELD_FAMILY else f.momentum >= 1):
        trig.append(("momentum", next_k(f, "momentum")))   # noshield（决定 8）：这一 END 没举盾（闪了也算触发，结算时躲掉、不算一次）
    if len(trig) > 1:
        raise NotImplementedError(f"一个 END 上有两种阶梯机制 {trig}：原型里一个阶段只有一种机制，阶梯没定义叠加")
    return trig[0] if trig else (None, 0)


# ---------------------------------------------------------------- 补丁
@contextlib.contextmanager
def _counter_masked(f):
    """决定 10：nodouble 下引擎回合末的反击重击关掉 —— 交给引擎的 offences 压到 <= 1（只在这一阶段有反击时）。退出时还原真值。"""
    if COUNTER_COUNTERPROOF == "at_end" or not counter_ladder(f) or f.offences <= 1:      # v3.9：noblock 下同样关掉引擎的回合末重击
        yield
        return
    off0 = f.offences
    f.offences = 1
    try:
        yield
    finally:
        # v3.7（v3b_rule_check R10b）：END 跑完时引擎已把 offences 清零（新回合）—— 那就保持 0，只在没跑到清零时（单独调用 _incoming 等）
        # 还原真值。v3.6 无条件还原：反击罚过一次以后 A7（这一回合的进攻数）跨回合一直涨，只在反击怪上出现（泄露机制），计分的反击错误也被放大。
        if f.offences == 1:
            f.offences = off0


def _incoming(self):
    off = dict(pierce_grudge=1) if GRUDGE_OFF else {}
    with _tuning(momentum_boss_frac=0, big_frac=0, **off), _counter_masked(self):   # boss 下限由阶梯取代；记仇关掉（也挡住 END 之外的直接调用）
        hit, ib, eaten = _ORIG["_incoming"](self)
    mech, k = _end_trigger(self)
    if mech in ("charge", "pierce"):
        st = step_for(self, mech, k)
        hit = _death_hit(self) if st.death else _normal_end(self) * st.mult
        ib = True
    return hit, ib, eaten


def _momentum_bonus_get(self):
    if MOMENTUM_MODE in NOSHIELD_FAMILY:
        return 0                                    # 决定 8：没有斜坡、不预告 —— 印出的攻击 = 普通一击；没盾的惩罚在 END 结算里落下
    if self.momentum <= 0:
        return 0                                    # 连续计数 0：不带惩罚（第一个没举盾的 END 是警告）
    st = step_for(self, "momentum")
    normal = _normal_momentum(self)
    target = _death_hit(self) if st.death else normal * st.mult
    return max(0, target - normal)


_DEPTH = [0]


def _settle_scope(f, inner):
    """一个 END（或单独调用的 release_committed）的阶梯结算。"""
    import adventure
    if _DEPTH[0]:
        return inner(f)                            # release_committed 在 end_turn 里：外层已经设好
    s = f.state
    mech, k = _end_trigger(f)
    tier = tier_of(f) if mech else None
    st = step_for(f, mech, k) if mech else None
    cap = bool(st is not None and st.nonlethal)
    nos = momentum_noshield(f)                     # 决定 8：没盾的 END 在这里按这一次结算调用的盾换成阶梯那一击
    so = momentum_shieldonly(f)                    # v3.8：shieldonly —— 没盾的那一次结算不认闪
    if nos:
        mst = step_for(f, "momentum")              # 这一 END 开始时定 k：真结算与两次反事实审计同一个 k
        mtarget = _death_hit(f) if mst.death else _normal_momentum(f) * mst.mult
    orig_settle = adventure.settle_attack
    calls = []

    def settle_attack(hp, block, dodge, hit, ignores_block, lethal):
        pun = bool(nos and block <= 0)
        if pun:
            hit = mtarget                           # 没举盾：普通一击 x L（死 = 2 x 上限血）；闪照样全躲（noshield）
            if so:
                dodge = False                       # v3.8 shieldonly：闪避不躲开动量的罚（这一次结算按没闪算）
        r = orig_settle(hp, block, dodge, hit, ignores_block, lethal)
        c = (pun and mst.nonlethal) if nos else cap  # noshield：不致死只在这一下被罚时起作用（举着盾挨的普通一击照常能打死）
        capped = bool(c and hit and not dodge and not lethal and hp > 0 >= r[0])
        if capped:
            r = (1, r[1], r[2])
        if not calls:
            # 第一次调用是真结算（后面两次是引擎的反事实审计，同一套规则）：这一 END 用掉的 k 当场记上，
            # END 末尾引擎印攻击槽（shown_atk → momentum_bonus）时读到的就是新的计数。
            if mech == "momentum" and (pun or not nos) and ((hit and not dodge) or DODGED_MOMENTUM_COUNTS):
                setattr(f, _A_MOM, _get(f, _A_MOM, 0) + 1)          # 连续计数 >= 1、落下的 END：举着盾也算（决定 3），闪掉的不算（决定 5，v3）
            elif mech == "charge" and hit and not dodge:
                setattr(f, _A_BIG, _get(f, _A_BIG, 0) + 1)          # 大招：只算落下的
        calls.append(dict(hp=hp, block=block, dodge=bool(dodge), hit=hit, ignores_block=bool(ignores_block), lethal=bool(lethal),
                          hp_after=r[0], capped=capped))
        return r

    tun = dict(momentum_boss_frac=0, big_frac=0,
               big_lethal=int(bool(st is not None and st.death and mech == "charge")),
               pierce_boss_lethal=int(bool(st is not None and st.death and mech == "pierce")))
    printed, turn, hp0 = s[("them", "atk")], f.turn, s[("me", "hp")]
    dodge0 = bool(s[("me", "dodge")])              # v3.8：这一 END 开始时玩家举着闪没有（只给 shieldonly 的 dodge_voided 用）
    off0 = f.offences                              # v3.6：nodouble 下 END 期间交给引擎的 offences 压到 <= 1（反击重击关掉），之后 last_offences 还原真值
    masked = counter_ladder(f) and off0 > 1 and COUNTER_COUNTERPROOF != "at_end"   # v3.9：noblock 同
    _DEPTH[0] += 1
    try:
        with _tuning(**tun), _swap(adventure, "settle_attack", settle_attack), _counter_masked(f):
            out = inner(f)
    finally:
        _DEPTH[0] -= 1
    if masked and f.last_offences == 1 and f.turn == turn + 1:
        f.last_offences = off0                     # 公开量（自己这一回合出了几张进攻牌）照真值
    first = calls[0] if calls else None
    landed = bool(first is not None and first["hit"] and not first["dodge"])
    used = bool(first is not None and (mech == "pierce" or (mech == "charge" and landed)
                                       or (mech == "momentum" and (landed or DODGED_MOMENTUM_COUNTS))))
    rec = dict(turn=turn, mech=mech, tier=tier, k=k, step=st.label() if st else None, printed=printed, hp_before=hp0,
               hit=None if first is None else first["hit"], ignores_block=None if first is None else first["ignores_block"],
               lethal=None if first is None else first["lethal"], held=None if first is None else first["block"],
               dodged=None if first is None else first["dodge"], hp_after_hit=None if first is None else first["hp_after"],
               capped=bool(first and first["capped"]), landed=landed, counted=used)
    if so:                                         # v3.8：只在 shieldonly 下加这个键（别的模式下记录逐字不变）
        rec["dodge_voided"] = bool(first is not None and first["block"] <= 0 and dodge0)
    setattr(f, _A_LAST, rec)
    if mech is not None and used:
        _event(f, rec)
    return out


def _end_turn(self):
    return _settle_scope(self, _ORIG["end_turn"])


def _release_committed(self):
    return _settle_scope(self, _ORIG["release_committed"])


def _play(self, name):
    orig = _ORIG["play"]
    c = self.deck.get(name)
    if c is None:
        return orig(self, name)                    # 引擎自己报错
    s, parts = self.state, self.parts
    will = name in self.hand and s[("me", "energy")] >= c.cost
    mark_hit = will and "mark" in parts and self.marked_kind() == c.kind
    guard_try = will and "guard" in parts and c.kind == "attack" and s[("them", "guard")] >= 1
    if will and counter_would_fire(self, c.kind):
        if mark_hit or guard_try:
            raise NotImplementedError("反击和标记 / 守势同时生效：原型里一个阶段只有一种机制，阶梯没定义叠加")
        return _counter_play(self, name, c)
    if will and COUNTER_MODE == "noblock" and noblock_would_fire(self, c.kind):     # v3.9（noblock 下才走）
        if mark_hit or guard_try:
            raise NotImplementedError("反击和标记 / 守势同时生效：原型里一个阶段只有一种机制，阶梯没定义叠加")
        return _counter_noblock_play(self, name, c)
    if will and COUNTER_MODE == "noblock" and c.kind == "block" and block_void_now(self) and COUNTER_COUNTERPROOF != "nb_later_block_works":
        blk0 = s[("me", "block")]
        out = orig(self, name)
        if out is True:
            s[("me", "block")] = blk0                  # v3.9：这一回合的盾已作废，后出的盾牌不给盾
        return out
    if will and ward_would_fire(self, c.kind):        # 修订 4（probe1w）：boss 封着时出攻击牌
        if mark_hit or guard_try:
            raise NotImplementedError("破势和标记 / 守势同时生效：原型里一个阶段只有一种机制，阶梯没定义叠加")
        return _ward_play(self, name, c)
    if not (mark_hit or guard_try):
        return orig(self, name)
    if "mark" in parts and "guard" in parts:
        raise NotImplementedError("标记和守势同时生效：原型里一个阶段只有一种机制，阶梯没定义叠加")
    tier = tier_of(self)
    code = s[("them", "mark")] if mark_hit else None   # v3.4：出牌那一刻的代号（出牌不改它；END 才重抽）
    if mark_hit:
        mech, idx = "mark", 5
        base = max(1, s[("them", "atk")])
    else:
        mech, idx = "guard", 4
        base = None                                 # 反弹的底数是这一下攻击的伤害，引擎在牌里算（增伤、封印之后）
    k = next_k(self, mech)
    st = step_for(self, mech, k)
    mult = 1 if st.death else st.mult
    hp0, count0 = s[("me", "hp")], (self.mark_hits if mark_hit else self.reflected)
    old_p = self.punished[idx]
    self.punished[idx] = 0                          # 让引擎走探针分支：倍数 = TUNING 的 *_probe_mult = 阶梯倍数
    try:
        with _tuning(boss_no_probe=0, **{f"{mech}_probe_mult": mult}):
            out = orig(self, name)
    finally:
        self.punished[idx] = old_p + self.punished[idx]   # 引擎在 0 上加了几次，就在原值上加几次（与不装时同一个计数）
    hit_now = (self.mark_hits if mark_hit else self.reflected) - count0
    if hit_now <= 0:
        return out                                  # 守相上攻击却没反弹（伤害 0：封印、护甲）
    assert hit_now == 1, (mech, hit_now)
    hp_final = s[("me", "hp")]
    if mark_hit:
        setattr(self, _A_MCODES, mark_code_hits(self) + (code,))   # v3.4：两种设置下都记（只有 percode 在 boss 上读）
        hit = base * mult
        # 自查：引擎扣的正是 base x mult（先挨打，再是牌的效果；只有治疗动自己的血）
        want = min(self.max_hp, hp0 - hit + c.amount) if c.kind == "heal" else hp0 - hit
        assert hp_final == want, ("标记一击与阶梯不符", hp0, hit, hp_final, want, c.kind)
    else:
        hit = hp0 - hp_final                        # 攻击牌除了反弹不动自己的血
    after_hit = hp0 - hit
    capped = death = False
    if st.death:
        s[("me", "hp")] = 0                         # 死是最终的：被标的治疗也回不来
        death = True
    elif st.nonlethal and hp0 > 0 >= after_hit:
        if mark_hit and c.kind == "heal":
            # 引擎：hp = min(上限, 挨打后的血 + 回血量)。挨打后 <= 0、1 + 回血量 <= 上限时 min 两边都不起作用，所以差值直接加上
            assert 1 + c.amount <= self.max_hp, (c.amount, self.max_hp)
        s[("me", "hp")] = hp_final + (1 - after_hit)
        capped = True
    rec = dict(turn=self.turn, mech=mech, tier=tier, k=k, step=st.label(), card=c.kind, base=base, hit=None if death else hit,
               hp_before=hp0, hp_after_hit=0 if death else (1 if capped else after_hit), hp_final=s[("me", "hp")],
               capped=capped, death=death, landed=True, counted=True)
    if mark_hit and MARK_COUNTING == "percode":     # v3.4：默认下事件逐字不变
        rec.update(code=code, counting="percode" if mark_per_code(self) else "fight")
    _event(self, rec)
    return out


def ward_would_fire(f, kind):
    """修订 4（43 §14）：这一张是不是一次破势犯规 —— probe1w 装着、boss（反证 ward_maps_too 时任何一场）、这一阶段有破势、封印开着、出的是攻击牌。"""
    return (WARD_STRIKE and kind == "attack" and "ward" in f.parts and f.state[("them", "ward")] > 0
            and (f.is_boss or WARD_COUNTERPROOF == "ward_maps_too"))


def _reveal(self, before):
    """阶梯在引擎记 seen（Fight._mark）之后才改自己的血 / 盾：这里补记，画面上这一格不再停在 `?`（2026-11-09，52 号文档）。"""
    seen = getattr(self, "seen", None)
    if seen is not None:
        for k, v in before.items():
            if self.state[k] != v:
                seen.add(k)


def _ward_play(self, name, c):
    """修订 4：先交给引擎出牌（封着：伤害 0、落空计数 +1；回合末封印 +1 照旧），然后当下扣血 = 普通一击 x L(ward, boss, k)，盾、闪没用；
    死 → 血归 0；不致死 → 打到 <= 0 留 1 血。k = 这一场（阶段）破势罚过的次数 + 1；换阶段进场时第一格照换阶段格（x1m2：x1 不致死）。"""
    orig = _ORIG["play"]
    s = self.state
    cp = WARD_COUNTERPROOF
    tier = tier_of(self) if self.is_boss else "boss"
    k = next_k(self, "ward")
    st = step_for(self, "ward", k) if self.is_boss else row("boss", "ward")[min(k, len(row("boss", "ward"))) - 1]
    if cp == "ward_lethal_first":
        st = DEATH
    base = _normal_end(self)
    hp0 = s[("me", "hp")]
    out = orig(self, name)
    if out is not True:
        return out
    assert s[("me", "hp")] == hp0, ("封着时的攻击动了自己的血", hp0, s[("me", "hp")])
    hit = None if st.death else base * st.mult
    if cp == "ward_no_hit":
        hit = 0
    _before = {("me", "hp"): hp0, ("me", "block"): s[("me", "block")] if ("me", "block") in s else None}
    capped = death = False
    if st.death and cp != "ward_no_hit":
        s[("me", "hp")] = 0
        death = True
    else:
        after = hp0 - hit
        if st.nonlethal and hp0 > 0 >= after:
            after = 1
            capped = True
        s[("me", "hp")] = after
    setattr(self, _A_WARD, _get(self, _A_WARD, 0) + 1)
    rec = dict(turn=self.turn, mech="ward", tier=tier, k=k, step=st.label(), card=c.kind, base=base, hit=None if death else hit,
               hp_before=hp0, hp_after_hit=0 if death else s[("me", "hp")], hp_final=s[("me", "hp")], capped=capped, death=death,
               landed=True, counted=True, rule="probe1w", seal=s[("them", "ward")])
    _event(self, rec)
    _reveal(self, {k: v for k, v in _before.items() if v is not None})
    return out


COUNTER_COUNTERPROOF = None   # 核对的反证（默认 None）："keep_double" = 增伤不作废；"blockable" = 盾先吸收；"no_hit" = 不罚；"at_end" = 当下不罚、
                              # 引擎回合末的重击照旧（= 关掉 nodouble 的 END 改动）；"first_order_only" = 只在「增伤先出、攻击后出」时罚


def _counter_play(self, name, c):
    """决定 10（PROTO_COUNTER=nodouble）：这一张是这一回合攻击 + 增伤里第二张出手的。先作废增伤（增伤先出：攻击之前清旗；攻击先出：出完清旗），
    再交给引擎出牌（攻击照普通伤害），然后当下扣血 = 普通一击 x L(counter, 阶层, k)，盾、闪没用；死 → 血归 0；不致死 → 留 1 血。"""
    orig = _ORIG["play"]
    s = self.state
    cp = COUNTER_COUNTERPROOF
    if cp == "first_order_only" and c.kind == "buff_mark":
        return orig(self, name)
    if cp == "at_end":
        return orig(self, name)
    tier = tier_of(self)
    k = next_k(self, "counter")
    st = step_for(self, "counter", k)
    base = _normal_end(self)                       # 普通一击（同 END 的：敌人攻击 + 怒气 x 停顿 + 威胁加成；PROTO_RAGE=off 下 = 敌人攻击）
    dbl0 = s[("me", "double")]
    if c.kind == "attack" and cp != "keep_double":
        s[("me", "double")] = 0                    # 增伤先出：这一下攻击按普通伤害
    hp0 = s[("me", "hp")]
    out = orig(self, name)
    if out is not True:
        s[("me", "double")] = dbl0                 # 引擎没出成（不该发生：调用方先查过 will）：原样还原
        return out
    if c.kind == "buff_mark" and cp != "keep_double":
        s[("me", "double")] = 0                    # 攻击先出：增伤作废（这一回合没有攻击可翻倍了；冷却照 FixedPileCD 走）
    hp1 = s[("me", "hp")]
    assert hp1 == hp0, ("攻击 / 增伤动了自己的血", hp0, hp1)
    hit = None if st.death else base * st.mult
    if cp == "no_hit":
        hit = 0
    _before = {("me", "hp"): hp0, ("me", "block"): s[("me", "block")] if ("me", "block") in s else None}
    if cp == "blockable" and hit:
        absorbed = min(hit, s[("me", "block")])
        s[("me", "block")] -= absorbed
        hit -= absorbed
    capped = death = False
    if st.death and cp != "no_hit":
        s[("me", "hp")] = 0
        death = True
    else:
        after = hp0 - hit
        if st.nonlethal and hp0 > 0 >= after:
            after = 1
            capped = True
        s[("me", "hp")] = after
    setattr(self, _A_CTR, _get(self, _A_CTR, 0) + 1)
    self.countered += 1                            # 引擎的逐场 / 逐命账照旧有「反击落下了一次」（Trace 的 countered、punished[1] 事件）
    self.punished[1] += 1
    rec = dict(turn=self.turn, mech="counter", tier=tier, k=k, step=st.label(), card=c.kind, second=c.kind, base=base,
               hit=None if death else hit, hp_before=hp0, hp_after_hit=0 if death else s[("me", "hp")], hp_final=s[("me", "hp")],
               capped=capped, death=death, landed=True, counted=True, doubler_void=True)
    _event(self, rec)
    _reveal(self, {k: v for k, v in _before.items() if v is not None})
    return out


def _counter_noblock_play(self, name, c):
    """决定 13（v3.9，PROTO_COUNTER=noblock）：这一张是这一回合攻击 + 盾里第二张出手的。先交给引擎出牌（攻击照常打、增伤照常翻倍；盾照常加上），
    然后：当下扣血 = 普通一击 x L(counter, 阶层, k)，盾、闪没用；这一回合的盾作废（置 0，之后的盾牌不给盾）；死 → 血归 0；不致死 → 留 1 血。
    核对的反证（COUNTER_COUNTERPROOF）：nb_keep_block = 盾不作废；nb_blockable = 盾先吸收那一下（再作废）；nb_no_hit = 不罚（盾照样作废）；
    nb_first_order_only = 只在「攻击先出、盾后出」时罚；nb_later_block_works = 之后出的盾牌照常给盾（在 _play 里读）。"""
    orig = _ORIG["play"]
    s = self.state
    cp = COUNTER_COUNTERPROOF
    if cp == "nb_first_order_only" and c.kind == "attack":
        return orig(self, name)
    tier = tier_of(self)
    k = next_k(self, "counter")
    st = step_for(self, "counter", k)
    base = _normal_end(self)                       # 普通一击（同 END 的；PROTO_RAGE=off 下 = 敌人攻击）
    hp0 = s[("me", "hp")]
    out = orig(self, name)
    if out is not True:
        return out                                 # 引擎没出成（不该发生：调用方先查过 will）
    hp1 = s[("me", "hp")]
    assert hp1 == hp0, ("攻击 / 盾动了自己的血", hp0, hp1)
    blk = s[("me", "block")]
    hit = None if st.death else base * st.mult
    if cp == "nb_no_hit":
        hit = 0
    absorbed = 0
    if cp == "nb_blockable" and hit:
        absorbed = min(hit, blk)
        hit -= absorbed
    _before = {("me", "hp"): hp0, ("me", "block"): blk}
    capped = death = False
    if st.death and cp != "nb_no_hit":
        s[("me", "hp")] = 0
        death = True
    else:
        after = hp0 - hit
        if st.nonlethal and hp0 > 0 >= after:
            after = 1
            capped = True
        s[("me", "hp")] = after
    if cp != "nb_keep_block":
        s[("me", "block")] = 0                     # 这一回合的盾作废（回合末那一击全吃）
        setattr(self, _A_CTR_VOID, self.turn)
    setattr(self, _A_CTR, _get(self, _A_CTR, 0) + 1)
    self.countered += 1                            # 引擎的逐场 / 逐命账照旧有「反击落下了一次」（Trace 的 countered、punished[1] 事件）
    self.punished[1] += 1
    rec = dict(turn=self.turn, mech="counter", tier=tier, k=k, step=st.label(), card=c.kind, second=c.kind, base=base,
               hit=None if death else hit, hp_before=hp0, hp_after_hit=0 if death else s[("me", "hp")], hp_final=s[("me", "hp")],
               capped=capped, death=death, landed=True, counted=True, rule="noblock", block_voided=blk, block_after=s[("me", "block")])
    _event(self, rec)
    _reveal(self, {k: v for k, v in _before.items() if v is not None})
    return out


# ---------------------------------------------------------------- 装 / 撤
def installed():
    return bool(_STATE["installed"])


def install(table=None):
    """装上阶梯（table 默认 LADDER；核对用的反证可以传别的表）。已经装着同一张表 → 什么也不做；装着别的表 → 报错（先 remove()）。"""
    import adventure
    p = pathlib.Path(adventure.__file__).resolve()
    assert p.parent == ROOT / "core", f"adventure 不是从 core/ 导入的：{p}"
    table = _check_table(TABLES[TABLE_NAME] if table is None else table)
    if _STATE["installed"]:
        if _STATE["table"] != table:
            raise RuntimeError("阶梯已经装着另一张表：先 remove()")
        return describe()
    from adventure import TUNING
    bad = {k: TUNING[k] for k, v in NEED.items() if TUNING[k] != v}
    if bad:
        raise RuntimeError(f"阶梯是按 {NEED} 写的，现在 {bad}：先核对再装")
    F = adventure.Fight
    for n in PATCHED:
        if n not in F.__dict__:
            raise RuntimeError(f"Fight 上没有 {n}")
    for a in (_A_BIG, _A_MOM, _A_EVENTS, _A_LAST, _A_MCODES, _A_CTR, _A_CTR_VOID):
        if hasattr(F, a):
            raise RuntimeError(f"Fight 类上已经有 {a}：逐场计数的属性名撞了")
    _ORIG.clear(); _MINE.clear()
    _ORIG.update({n: F.__dict__[n] for n in PATCHED})
    _MINE.update(_incoming=_incoming, momentum_bonus=property(_momentum_bonus_get, doc="penalty ladder: momentum bonus"),
                 end_turn=_end_turn, release_committed=_release_committed, play=_play)
    for n in PATCHED:
        setattr(F, n, _MINE[n])
    _STATE.update(installed=True, table=table)
    return describe()


def remove():
    """撤掉阶梯：Fight 的 5 个属性还原成装之前 F.__dict__ 里的同一个对象（STATS 留着，reset_stats() 清）。没装 → 什么也不做。
    装着时建的 Fight 实例上留着 _ladder_* 计数属性，撤掉之后没有任何代码读它们。
    属性已经不是本模块装的（例如中途 teardown_boss() 换掉了 end_turn）→ 报错，一个也不还原。"""
    import adventure
    if not _STATE["installed"]:
        return
    F = adventure.Fight
    wrong = [n for n in PATCHED if F.__dict__.get(n) is not _MINE[n]]
    if wrong:
        raise RuntimeError(f"Fight.{wrong} 已经不是阶梯装的那个（装之后有别的补丁换过它，例如 teardown_boss()）：不还原，先查清次序")
    for n in PATCHED:
        setattr(F, n, _ORIG[n])
    _ORIG.clear(); _MINE.clear()
    _STATE.update(installed=False, table=None)


def describe(table=None):
    """设置记录（写进输出文件用）：阶梯表、各机制怎么接、什么被替换、什么不变、待定的问题。"""
    t = _STATE["table"] if table is None and _STATE["installed"] else _check_table(TABLES[TABLE_NAME] if table is None else table)
    extra = {}
    if MARK_COUNTING != "fight":                    # v3.4：默认（fight）下 describe() 逐字不变
        extra = dict(mark_counting=MARK_COUNTING, mark_counting_env="PROTO_LADDER_MARK=percode", mark_counting_user_words=MARK_USER_WORDS,
                     mark_counting_rule="decision 6 (v3.4, user 2026-11-04, per-code counting is the lead's choice): at the boss only, mark "
                                        "k = the number of times THIS code (the engine mark code shown when the marked card is played) has "
                                        "already punished you this fight + 1, so every new code's first hit is k=1 (never lethal) and only a "
                                        "repeated code climbs the boss row; map fights (teach / test) keep per-fight counting; the other four "
                                        "mechanics are unchanged; per-code hits live on the Fight as an immutable tuple of codes "
                                        f"({_A_MCODES}); mark events carry code / counting")
    if has_mech_rows(t):                            # v3.5（决定 7）：旧表（没有机制行）下 describe() 逐字不变
        extra.update(table_rows_rule="decision 7 (v3.5, docs/antagonist_boss/18_candidate_v3_spec.md section 3): a 'mechanic/tier' row prices that "
                                     "mechanic at that tier; a mechanic without its own row uses the tier row (fallback); ward is not on the ladder",
                     table_fallback_used_by=[m for m in MECHANICS if any(f"{m}/{x}" not in t for x in TIERS)])
    if MOMENTUM_MODE == "shieldonly":               # v3.8：只在 shieldonly 下（noshield 那一支逐字不变）
        extra.update(momentum_mode=MOMENTUM_MODE, momentum_mode_env="PROTO_MOMENTUM=shieldonly", momentum_user_words=MOMENTUM_USER_WORDS,
                     momentum_shieldonly_user_words=SHIELDONLY_USER_WORDS,
                     momentum_rule="v3.8 (spec 18 section 8.7; noshield except for the dodge): an END settled with no shield held (block 0) is "
                                   "the next momentum k whether or not the player dodged: that END's hit = normal x L(momentum, tier, k) (boss "
                                   "death step = 2 x max hp) and the dodge does not avoid it (the no-shield settlement is made with dodge False); "
                                   "a held shield takes only the normal hit (block absorbs) and does not count; no warning END, no streak, no "
                                   "ramp: Fight.momentum_bonus is 0, so the printed enemy attack and Fight._incoming()[0] are the normal hit; "
                                   "the multiplier is applied inside the END's settle_attack per call (the engine's held-vs-bare audit sees the "
                                   "rule), k fixed at the start of the END, counted on the real settlement only; the engine streak "
                                   "Fight.momentum and punished[3] are left to the engine and read by nothing on the ladder")
    elif MOMENTUM_MODE != "streak":                 # v3.5（决定 8）：默认（streak）下 describe() 逐字不变
        extra.update(momentum_mode=MOMENTUM_MODE, momentum_mode_env="PROTO_MOMENTUM=noshield", momentum_user_words=MOMENTUM_USER_WORDS,
                     momentum_rule="decision 8 (v3.5, spec 18 section 2): an END settled with no shield held (block 0) and not dodged is the next "
                                   "momentum k: that END's hit = normal x L(momentum, tier, k) (boss death step = 2 x max hp); a held shield "
                                   "takes only the normal hit (block absorbs) and does not count; a dodge avoids the hit and does not count; "
                                   "no warning END, no streak, no ramp: Fight.momentum_bonus is 0, so the printed enemy attack and "
                                   "Fight._incoming()[0] are the normal hit; the multiplier is applied inside the END's settle_attack per call "
                                   "(the engine's held-vs-bare audit sees the rule), k fixed at the start of the END, counted on the real "
                                   "settlement only; the engine streak Fight.momentum and punished[3] are left to the engine and read by nothing "
                                   "on the ladder")
    out = dict(
        version=VERSION, installed=installed(), table_name=TABLE_NAME, table=_table_text(t), table_sha16=_table_sha(t),
        user_words=USER_WORDS[TABLE_NAME],          # v3.3：按表（原来写死 v1 的原话）
        decisions_2026_11_03_night=[
            "1 pierce grudge OFF under the ladder: no hit is multiplied by pierce_grudge (ladder hits and ordinary hits after 2 eaten shields)",
            "2 boss momentum death as implemented: a shield held that END does not save you (hit lands before the reset); a dodge avoids that END's hit",
            "3 momentum counted cumulatively per fight: streak 0 = warning only; every END with streak >= 1 whose hit lands is the next k "
            "(a shield held that END does not stop it and it still counts; a held shield never resets k); printed attack = normal x L(k+1) "
            "while the streak >= 1; engine momentum cap 2 everywhere",
            "4 per-fight counters live on the Fight instance (copy.deepcopy / copy.copy carry them)",
            "5 (v3, user 2026-11-03 night, 13 section 3) a dodged momentum END does not count toward k, like charge: only punishments that "
            "land count; the streak follows the engine (a dodge is not a held shield, so the streak goes on, cap 2), so the next END is "
            "the same k and the printed attack does not change"],
        counting="per fight (resets each fight; the boss is one fight), per mechanic; mistake k = the k-th time this fight that the same mechanic punishes you",
        tiers="boss = Fight.is_boss; otherwise enemy.punish == teach_punish_pct (50) -> teach, == test_punish_pct (250) -> test; anything else raises",
        normal_hit="engine cur = enemy atk + rage x stalls + threat bonus, never x pierce_grudge; momentum: without its own bonus; "
                   "under PROTO_RAGE=off the enemy rage is 0, so the normal hit is the enemy attack",
        mechanics=dict(
            charge="k = big hits landed (not dodged) this fight + 1; big hit = normal x L, ignores block, dodge avoids; replaces big_mult pricing, big_frac, big_lethal",
            pierce="k = shields eaten this fight + 1 (fed + 1; a dodged pierce still eats the shield); END hit while holding block = normal x L through block; "
                   "replaces pierce probe x2 / pierce_mult; grudge off",
            mark="k = mark hits this fight + 1; hit on playing the marked kind = max(1, enemy atk slot) x L, block/dodge useless, card effect after the hit; replaces mark_probe_mult / mark_mult",
            guard="k = reflections this fight + 1; reflected = your attack's damage x L; replaces guard_probe_mult / guard_mult",
            momentum="k = momentum punishments landed this fight + 1; an END is a momentum punishment when the streak before it is >= 1 and the hit "
                     "lands (block held included; a dodged END does not count, v3; the first unshielded END is only a warning); END hit = normal x L via "
                     "Fight.momentum_bonus, so printed attack == pre-block hit; replaces momentum_probe_ratio / momentum_full_ratio / momentum_boss_frac",
            ward="no damage; not on the ladder"),
        nonlethal="boss k=1 only: if the hit would take hp from > 0 to <= 0, hp is left at exactly 1 (END hits: after block/dodge; mark: before the card's own effect); "
                  "teach / test k=1 can kill",
        death=dict(charge="engine lethal flag: hp to exactly 0 unless dodged, whatever the hp or block",
                   pierce="engine lethal flag: hp to exactly 0 unless dodged, whatever the hp or block",
                   mark="hp set to 0 after the play, final (a marked heal does not bring it back)",
                   guard="hp set to 0 after the play",
                   momentum=f"printed and landed hit = {DEATH_HIT_MAX_HP} x max hp; settled like any END hit (block absorbs, dodge avoids), so hp goes negative"),
        momentum_cap="engine value (2), never changed; only streak >= 1 matters to the ladder",
        state_on_fight=f"per-fight counters / events / last END record are instance attributes {[_A_BIG, _A_MOM, _A_EVENTS, _A_LAST]} with immutable values",
        unchanged=["engine per-life accounting punished[] (still incremented as before)", "everything outside play / END / _incoming; core/ untouched"],
        open=["dodges: a dodged momentum END and a dodged big hit do not count (v3); a dodged pierce counts (the engine eats the shield)",
              "boss momentum after two momentum punishments: every END with streak >= 1 is death unless dodged, a shield held that END does not save you; "
              "a dodge neither counts nor resets the streak, so the only way out is to dodge every END until the boss dies, and under PROTO_HAND=fixed "
              "six dodge turns in a row end the fight as a loss (correct play = shield every END, never punished)",
              "mark death vs the rule 'the card still applies after the hit' (a marked heal at boss k>=3 would otherwise revive)",
              f"momentum death number: {DEATH_HIT_MAX_HP} x max hp, so a held shield saves only if block >= max hp at full hp",
              "STATS is process-wide and also counts ENDs played on deep-copied fights (e.g. antagonist_boss_check._survival_lines)"],
        **extra)
    if any(k.startswith("counter/") for k in t):  # v3.6：表里有反击行（v3b）时才加（旧表、v3 下逐字不变）
        out["counter_rows"] = "v3.6 (spec 18 sections 8.1/8.4, lead's default, user 'try it'): counter rows = guard rows (teach 2/3/4, test 2/8/16, " \
                              "boss 3 never lethal / 9 / 27 / death)"
        if all(t.get(k) == LADDER_V3C1B[k] for k in ("counter/teach", "counter/test", "counter/boss")):   # v3.11：只在表 v3c1b 的反击行下（别的表逐字不变）
            out["counter_rows"] = "v3.11 (spec 18 section 8.10, boss first version, user 'ok'): table v3c1b = v3c1 except the boss counter row: " \
                                  "the first counter punishment at the boss costs x1 never lethal (also when counter is the first phase), " \
                                  "then 9 / 27 / death; teach 1/3/4 and test 1/8/16 as v3c1"
        elif all(t.get(k) == LADDER_V3C1[k] for k in ("counter/teach", "counter/test", "counter/boss")):   # v3.10：只在表 v3c1 的反击行下换（v3b 逐字不变）
            out["counter_rows"] = "v3.10 (spec 18 section 8.9, user 'try a first'): table v3c1 = v3b except that the first counter punishment " \
                                  "in each fight costs x1 (teach 1/3/4, test 1/8/16: the immediate hit = 1 x the normal hit; under noblock the " \
                                  "shield is still void that turn); boss counter row unchanged (3 never lethal / 9 / 27 / death)"
    if COUNTER_MODE == "noblock":                   # v3.9（决定 13）：只在 noblock 下（nodouble 那一支逐字不变）
        out.update(counter_mode=COUNTER_MODE, counter_mode_env="PROTO_COUNTER=noblock", counter_user_words=NOBLOCK_USER_WORDS,
                   counter_rule="decision 13 (v3.9, spec 18 section 8.8, trial): in a turn, when both the attack and the shield (block) have "
                                "been played (either order), at the moment the second of them is played: the player loses normal x L(counter, "
                                "tier, k) hp at once, block and dodge do nothing (death step: hp to 0; never-lethal step: leaves 1 hp), and the "
                                "shield is void for this turn (block set to 0 at that moment; a later block card this turn gives no block), so "
                                "the END hit is taken in full (the normal hit); the attack deals its normal damage (the doubler applies as "
                                "usual: attack + doubler is legal against counter); k = such punishments this fight + 1 (counted on the Fight, "
                                "also added to the engine's countered / punished[1]); the engine's end-of-turn counter heavy hit is off "
                                "(offences handed to the engine are capped at 1 while counter is active; last_offences restored to the true "
                                "count after END; the offence count is 0 at the start of every turn); no slot, no randomness")
        out["mechanics"] = dict(out["mechanics"], counter=(
            "PROTO_COUNTER=noblock: k = counter punishments this fight + 1; hit at the play of the second of attack/block = normal x L, "
            "straight from hp; the shield is void that turn (END hit taken in full); the attack and the doubler work as usual"))
    elif COUNTER_MODE != "engine":                  # v3.6（决定 10）：默认（engine）下 describe() 逐字不变
        out.update(counter_mode=COUNTER_MODE, counter_mode_env="PROTO_COUNTER=nodouble", counter_user_words=COUNTER_USER_WORDS,
                   counter_rule="decision 10 (v3.6, spec 18 sections 8.2-8.3): in a turn, when both the attack and the doubler have been "
                                "played (either order), at the moment the second of them is played: the doubler is void for this turn (doubler "
                                "first: the attack deals normal damage; attack first: the doubler flag is cleared) and the player loses normal x "
                                "L(counter, tier, k) hp at once, block and dodge do nothing (death step: hp to 0; never-lethal step: leaves 1 hp); "
                                "k = such punishments this fight + 1 (counted on the Fight, also added to the engine's countered / punished[1]); "
                                "the engine's end-of-turn counter heavy hit is off (offences handed to the engine are capped at 1 while counter "
                                "is active; last_offences restored to the true count after END), so the END hit is the normal hit; no slot, "
                                "no randomness")
        out["mechanics"] = dict(out["mechanics"], counter=(
            "PROTO_COUNTER=nodouble: k = counter punishments this fight + 1; hit at the play of the second of attack/doubler = normal x L, "
            "straight from hp; the doubler is void that turn; END hit normal"))
    if handover_on() and TABLE_NAME in HANDOVER_TABLES:   # v3.11：表 v3c1b 的换阶段（别的表照 v3.6 的那一支）
        out.update(handover=True, handover_user_words=HANDOVER_V3C1B_USER_WORDS,
                   handover_rule="v3.11 (spec 18 section 8.10, table v3c1b): at the boss, the mechanic that comes in with the second phase "
                                 "(not in the first phase) has its first punishment at x1 never lethal if it is counter and x3 never lethal "
                                 "otherwise (never lethal = a hit that would take hp to <= 0 leaves exactly 1 hp); its later punishments follow "
                                 "that mechanic's boss row after the first step (charge x3 nl / x9 / x27 / death; guard and momentum "
                                 "x3 nl / x9 / x27 / death; counter x1 nl / x9 / x27 / death); counts are per mechanic per fight, so nothing "
                                 "from the first phase carries over; ward is not on the ladder",
                   handover_rows={m: [s.label() for s in handover_row_v3c1b(row("boss", m, t), m)] for m in ("charge", "guard", "momentum", "counter")})
    elif handover_on():                             # v3.6（决定 11）：默认关（boss 先不做）；只在临时打开时加
        out.update(handover=True, handover_user_words=HANDOVER_USER_WORDS,
                   handover_rule="decision 11 (v3.6, spec 18 section 8.4): at the boss, the mechanic that comes in with the second phase "
                                 "(not in the first phase) is priced on its boss row with x3 never lethal as its first step: a row whose "
                                 "first step already is x3 never lethal is unchanged, otherwise that step is prepended (charge: x3 nl / x9 / "
                                 "x27 / death); counts are per mechanic, so nothing from the first phase carries over")
    if MOMENTUM_MODE == "noshield":                 # v3.5：streak 的说明换成 noshield 的（默认下这三处逐字不变）
        out["mechanics"] = dict(out["mechanics"], momentum=(
            "PROTO_MOMENTUM=noshield: k = no-shield momentum punishments landed this fight + 1; an END with no shield held (block 0) and not "
            "dodged takes normal x L(momentum, tier, k); a held shield takes the normal hit and does not count; a dodge avoids and does not "
            "count; no warning, no streak; momentum_bonus 0 (printed attack = normal); replaces momentum_probe_ratio / momentum_full_ratio / "
            "momentum_boss_frac"))
        out["death"] = dict(out["death"], momentum=(
            f"printed attack stays the normal hit; an unshielded END at the death step takes {DEATH_HIT_MAX_HP} x max hp (dodge avoids, a held "
            "shield means no punishment at all), so hp goes negative"))
        out["open"] = out["open"] + ["noshield: the engine streak (Fight.momentum) still runs and punished[3] still follows it; neither is a ladder "
                                     "count and the ladder reads neither"]
    if MOMENTUM_MODE == "shieldonly":               # v3.8：只在 shieldonly 下
        out["mechanics"] = dict(out["mechanics"], momentum=(
            "PROTO_MOMENTUM=shieldonly: k = no-shield momentum punishments landed this fight + 1; an END with no shield held (block 0) takes "
            "normal x L(momentum, tier, k) and counts, dodged or not (the dodge does not avoid it); a held shield takes the normal hit and does "
            "not count; no warning, no streak; momentum_bonus 0 (printed attack = normal); replaces momentum_probe_ratio / momentum_full_ratio / "
            "momentum_boss_frac"))
        out["death"] = dict(out["death"], momentum=(
            f"printed attack stays the normal hit; an unshielded END at the death step takes {DEATH_HIT_MAX_HP} x max hp (a dodge does not "
            "avoid it; a held shield means no punishment at all), so hp goes negative"))
        out["open"] = out["open"] + ["shieldonly: the engine streak (Fight.momentum) still runs and punished[3] still follows it; neither is a "
                                     "ladder count and the ladder reads neither",
                                     "shieldonly: a shield and a dodge held at the same END (not reachable under PROTO_HAND=fixed: the dodge costs "
                                     "the whole turn) is settled as under noshield (block absorbs, the dodge avoids)"]
    return out


if __name__ == "__main__":
    print(json.dumps(describe(), ensure_ascii=False, indent=1))
