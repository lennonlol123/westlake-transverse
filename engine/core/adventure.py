"""Adventure A -- the mechanics half. No elements here.

Three monster behaviours, each of which makes one learned response necessary:

    poison  stacks lasting damage and ceiling loss -> spend a rest on the ceiling
    charge  builds up, then a big hit               -> keep and play `dodge`
    pierce  punishes a held shield                  -> do not mindlessly block

Each appears at least twice before the boss: the first encounter can teach and
the second can test transfer. Map node KINDS (fight / elite / rest) are visible;
the behaviour behind a fight node is not, so routing cannot avoid an unlearned
monster. Behaviours are observed, never labelled.
"""

from __future__ import annotations

import contextlib
import random
from dataclasses import dataclass, field

from camp import (Card, GUARANTEED, HAND_SIZE, Layout, NUMERIC_PROPS, Pile,
                  STARTING_PILE, make_deck)
from namegen import enemy_name

# regen is implemented but held back for adventure B. Adding it here meant a
# fourth layer pair, and the extra two fights pushed cumulative damage past what
# the health pool can absorb: every policy died and discrimination fell from 29%
# to 13%. Raising resources enough to survive eight layers then flattened the
# differences instead (3% at 160 health). Adventure B has elements carrying much
# of the discrimination, so a fourth behaviour costs less there.
# Every knob below feeds the solvability screen, and the screen re-rolls until
# it finds a run inside the band -- so changing ANY of them silently changes what
# `Run(seed)` contains. A record is reproducible as (ENGINE_VERSION, seed,
# life) under the canonical screen; solver.py records the selected salt and
# rejects non-canonical diagnostics from that cache key.
# Bump this whenever TUNING, the enemy construction or the screen changes.
# c20: the enemy armour slot is withheld until the armour has acted. It was
# printed from turn 0 and only armoured enemies carry it, so the row was one
# number wider for exactly one kind of monster -- the answer, before the
# player moved, with no value even disclosed. `act` is held to the same
# screen, or the informed ceiling is quoted from what no player can see.
# c21: `armour` leaves the rotation -- see the note below. A run is two
# fight layers shorter as a result, which is budget the replacement
# mechanics will need.
ENGINE_VERSION = "c29"

# `armour` is OUT of the rotation as of c21, kept in the file the way `steady`
# and `regen` are: the code stays so the evidence can be re-run, the monster no
# longer appears. Three separate instruments agreed it was not a mechanic.
#
#   1. Its answer -- put the doubler up, then swing -- is a DOMINANT action.
#      `buff_mark` costs 1 energy and doubles the next hit, and the attack card
#      carries no damage of its own, so mira+mira and tsun+mira BOTH deal 2A.
#      The doubler is therefore never worse than a second attack, and it is
#      what breaks armour. Nobody has to recognise the monster to answer it.
#      Priced directly, playing the doubler unconditionally costs -0.0 / 0.4 /
#      4.4 points on fights that have no armour, at 100 / 50 / 35 entry health.
#   2. The 95-point gap it used to show was measured against a partial policy
#      that never plays the doubler AT ALL -- not a player who failed to
#      recognise armour, a player who refuses a free card. Let that line play
#      it and the gap is exactly 0.0% at every entry health.
#   3. Health-cost ledger, 60 worlds / 1169 fights: the best single fixed habit
#      overspends the informed line by 2.30 bars of health across a world, of
#      which charge accounts for 1.799 and armour for 0.097.
#
# The INTENT was right and is worth keeping for a replacement: an enemy that
# flat output cannot solve at all, where not understanding is fatal rather than
# merely inefficient. What failed is that its answer was also the best generic
# play. A replacement has to make the same card WRONG somewhere else, so that
# playing it unconditionally loses -- otherwise the knowledge buys nothing.
#
# The original note, kept for the record:
# `armour` replaces `regen` in the rotation. The regenerator punishes HALVED
# output, so the line it hurts is the one that stacks block -- pure attack has
# the highest output and beats it comfortably, which is the opposite of what was
# wanted. Armour is the enemy that flat output cannot solve at all: every hit is
# reduced by a fixed amount, so a single attack lands for almost nothing and the
# only way through is to double one up. Not understanding it is not inefficient,
# it is fatal.
# `steady` is gone. It was the one behaviour that was not a gate: blocking a
# plain attacker is mitigation, and mitigation is exactly what a health pool
# absorbs, so "did you work out that the shield helps" was worth 26 points where
# every other mechanic was worth 60+. Replaced by `poison`, which is a gate for
# the same reason armour is -- what it does to you cannot be absorbed, only
# answered -- and which gives the heal card the one thing it lacked: a monster
# that requires it. Plain attackers still exist inside the other behaviours;
# what is gone is a monster whose whole identity was "nothing special".
BEHAVIOURS = ("poison", "charge", "pierce")
# Everything that HAS an implementation, whether or not it is in the
# rotation. `BEHAVIOURS` above is what a generated world may contain;
# this is what the engines can simulate and what `BEHAVIOUR_ID` numbers.
# Which behaviours may be a boss PHASE. Poison is not one: its answer happens at
# the next rest, and there is no next rest after the boss -- a poison phase
# would be a question with no executable response, which reads as difficulty and
# is not.
# DERIVED, not listed. A hand-written pool put enrage in the boss while enrage
# was not in `BEHAVIOURS`: 63% of worlds then opened the boss with a mechanic the
# journey had never shown, which is a world where "did not get through" says
# nothing about the player. A mechanic reaches the boss when it reaches the
# rotation, or not at all.
BOSS_STAGE_KINDS = frozenset(("charge", "pierce", "enrage",
                              "momentum", "counter", "guard", "mark", "mimic", "ward"))

# Which ramp step starts costing the FULL tier. One definition, because three
# places need it and they have to agree: the damage, the policy that decides
# when a shield is worth playing, and the recorder that scores a missed shield
# as a mistake. It was written as `momentum_cap - 1` in the policy, which is the
# same number only while the cap is 2 -- at cap 4 the informed line stopped
# shielding altogether and behaved exactly like one that had never heard of the
# mechanic.
MOMENTUM_FULL_AT = 2

# The one neutral cue. It names no mechanic, no correct action and no number --
# and deliberately does NOT say "what you learned may no longer hold", because
# that sentence is already the answer: it tells the player to drop a belief,
# which is exactly the ability under test.
BOSS_SHIFT = "boss_shift"
# 只有模型读它（modelrun.run_fight 写进日志）。2026-10-19 之前是中文「敌人的形态发生了变化。」，用户：模型看到的必须全部是英文。
BOSS_SHIFT_TEXT = "The enemy's form has changed."

def pays_milestone(node) -> bool:
    """Does clearing this node hand out the attribute upgrade.

    `node.reward`, NEVER `node.kind == "elite"`. Under `curriculum=4` there is
    no elite kind at all -- the test fight is elite-STRENGTH and unavoidable,
    and the loot is a MILESTONE pinned to fixed layers (4 and 10 of 15). So the
    old expression is not merely a different spelling, it is constantly false.

    `solver.run_once` was migrated to `node.reward` and the three entry points
    a human or a model actually plays through were not. For every life measured
    since:

        reference line   2 attribute upgrades,  8 card takes
        model / human    0 attribute upgrades, 10 card takes

    The model was playing a strictly harder game than the line its clear rate
    was compared against: `base_atk` never grew at all, against enemy health
    rolled from the starting value, while it carried two extra cards for the
    whole run. Clear rate, depth reached and every deck-economy number are not
    comparable across that gap.

    One definition, because the failure was a half-finished migration and the
    next one must not be able to leave callers behind.
    """
    return bool(node.reward)


def boss_stage_pool(behaviours=None) -> list:
    """Which behaviours in the rotation may be a boss phase.

    Poison is excluded and the reason is mechanical rather than thematic: its
    answer is which way the NEXT rest is spent, and there is no rest after the
    boss. A poison phase would be a question with no executable response, which
    reads as difficulty and is not.

    Glutton is excluded for the same reason and it is the same reason
    stated once more: its answer is which card was taken at the LAST reward
    screen, and there is no reward screen between the boss phases or before
    them. A glutton phase would print a bigger number at a player who has no
    move left that addresses it, which reads as difficulty and is not.
    """
    return [b for b in (behaviours if behaviours is not None else BEHAVIOURS)
            if b in BOSS_STAGE_KINDS
            and b not in TUNING["boss_pool_exclude"]]


ALL_BEHAVIOURS = ("poison", "charge", "pierce", "armour", "steady",
                  "momentum",
                  "regen", "enrage", "glutton", "wound", "counter", "guard", "mark",
                  "mimic", "ward")

# The two key sets a policy may look up, defined once. There were four hand
# written copies of these tuples across batch.py and mapdp.py by c21, and
# adding "double" to one `know` dict raised KeyError in the others -- the same
# failure `lethal_now` exists to prevent. They are DIFFERENT sets on purpose:
# `PART_KEYS` are enemy behaviours a policy reads off the monster, `KNOW_KEYS`
# adds what the player knows about their own deck, which is not a behaviour
# and must never be looked up in an enemy's parts.
PART_KEYS = ("poison", "charge", "pierce", "armour", "enrage",
             "momentum", "glutton", "wound", "counter", "guard", "mark", "mimic", "ward")
KNOW_KEYS = PART_KEYS + ("double", "tempo")
PERSISTENT_PLAYER_PROPS = frozenset(("hp", "cap", "atk", "poison", "wound"))

# Every tunable number in one place, so `tune.py` can sweep them against the
# real engine. Hand-rolled simplified models have twice produced the opposite
# of the truth here (both times by assuming unlimited hand), so nothing gets
# decided without running the actual fight loop.
TUNING = dict(
    # Ratios, not absolutes. Each of these is compared against something that
    # scales with `base_atk` (or with health, which now scales with it too), so
    # an absolute silently meant a different thing at every attack value: rage
    # was 20% of a hit at attack 5 and 12.5% at attack 8, and the elite's "+1
    # attack" reward was worth 20% or 12.5% of your output for the same choice.
    rage_ratio=20,      # enemy attack gained per stalled turn, % of base_atk
    # The enrager gains attack for every non-attack card the PLAYER plays --
    # not for stalling, which `rage` already covers and which an attack turn
    # avoids for free. Not in BEHAVIOURS yet, so no generated world can reach
    # the branch and every existing (ENGINE_VERSION, seed, life) still means
    # what it meant.
    #
    # TWO TIERS, not a linear ramp, for the reason the piercer is two tiers.
    # Under a linear rule capped at 2, an oracle carries 0 stacks, a line that
    # probes once and corrects carries 1, and a line that never works it out
    # carries 2 -- so the cost of DISCOVERY and the value of the KNOWLEDGE are
    # both exactly one step, locked to the same number. Shrink it and the
    # knowledge is worth nothing; grow it and the unavoidable first probe
    # decides the run. Measured on the linear version: at 100% the probe cost
    # 26.1 points of a 41.1-point informed rate, and knowing was still WORSE
    # than not knowing below 75%.
    #
    # `full` is the TOTAL after the second offence, not a second addend.
    # CANDIDATE, not shipped: `enrage` is still absent from BEHAVIOURS, so no
    # generated world reaches any of this. Set from the calibration below.
    #
    #   route-optimised, one coordinate ascent per policy, reported on a stream
    #   the search did not see, 24 unscreened worlds:
    #       full 200%   stop 26.6%  missing 22.6%   knowledge +4.1% +-3.8%
    #       full 300%   stop 21.8%  missing 13.6%   knowledge +8.2% +-5.8%
    #   300 is taken because its knowledge value clears zero comfortably while
    #   200's interval only just does.
    #
    #   `allow_second_trigger` came out IDENTICAL to `missing_enrage` at both
    #   settings, to every decimal -- spending the whole gain deliberately is
    #   behaviourally the same as never having known, which is the check that
    #   the cap is not an exploit.
    #
    #   A line that classifies by printed health instead of experimenting --
    #   "thin enemy, stop spending energy on non-attacks" -- scored 1.5% against
    #   that line's 13.6%, still route-optimised. `hp_enrage` overlaps the other
    #   bands on purpose: most thin monsters are not enragers, so size cannot
    #   substitute for having worked it out.
    #
    #   Paired on ONE rolled map: cutting the enrager's two layers and a rest
    #   LOSES 11.5 points, so the behaviour pays for the layers it adds; the
    #   mechanic then costs 16.0 on identical topology.
    #
    #   Scalar-vector difference in differences, mechanic on minus off on the
    #   same worlds: within +-0.5pp with every interval covering zero, so the
    #   vector implementation adds no bias of its own.
    # Experimental arm. The enrager currently punishes every NON-attack card,
    # and measured on the reference policy's own behaviour that answer --
    # "play only attacks" -- agrees with pierce's "do not block" on 92% of real
    # decisions and with knowing nothing at all on 90%. It is not a separate
    # piece of knowledge; it is a tax on the three basic operations.
    #
    # The arm moves the trigger from "a non-attack card" to "the SECOND
    # offensive action in one turn", where offensive means attack or the
    # doubler -- the doubler exists only to make the next swing heavier, so
    # spending a turn on both is one act of over-committing, not two cards.
    #
    #     free        the first offensive action of the turn, always
    #     punished    a second one, whatever the pair: attack+attack,
    #                 doubler+attack, attack+doubler
    #     not touched attack+block, attack+heal, one attack alone, a dodge
    #
    # Measured on real trajectories, a second offensive action happens on 54%
    # of the aggressive line's turns and 38% of the informed line's, so the
    # question is asked constantly -- and the choice it poses is "seven more
    # damage now, or do not make this enemy permanently stronger", which is a
    # decision rather than a ban on defending.
    enrage_on_second_offence=0,
    enrage_probe_ratio=15,   # after the 1st non-attack, % of base_atk
    enrage_full_ratio=300,   # TOTAL after the 2nd, % of base_atk
    enrage_cap=2,            # nothing after that -- the lesson is over
    dodge_exempt_rage=1,
    # 2, not 3. At 3 the big hit failed to land in 9% of ordinary charge fights
    # and 25% of boss fights once the player had taken the attack rewards -- the
    # mechanic the boss exists to test simply never appeared. gpt-5.5 cleared a
    # whole run that way: three charge enemies, zero big hits, and its own notes
    # said "I killed it before seeing what that counter does" three times.
    charge_max=2,       # turns of wind-up before the big hit
    charge_max_elite=2, # elites wind up faster -- see make_enemy
    # Boss-only wind-up length and health scale. Separate from the journey's
    # because the boss is the EXAM and the journey is the lesson: measured, 45%
    # of wind-ups that reached the top on a boss never resolved, because the
    # player killed the phase on the turn it was due. That is the exam being
    # cancelled, not a weak punishment -- when the swing does happen it takes
    # a median 52% of the player's ceiling.
    charge_max_boss=0,      # 0 = use charge_max
    boss_charge_hp=100,     # percent, applied to a charge phase only
    # One body, one health bar, two rules. `boss_switch` builds the boss as a
    # single enemy whose behaviour changes at `boss_switch_frac` percent of its
    # health, instead of two fights in sequence. Nothing announces it: the
    # fight does not end, the hand is not redrawn, and no state resets -- which
    # is what makes it a test of dropping a rule rather than of learning a new
    # monster.
    boss_switch=0,
    boss_switch_frac=50,
    # Percent of the SUMMED two-stage budget that the single body gets. It is
    # not 100 by default reasoning: two sequential fights hand the player two
    # full hands, two full energy bars and two boss dodge guarantees, and one
    # continuous fight hands them one. Measured, keeping the summed health
    # turned the boss into a damage race -- informed play fell from 90% to 32%
    # and the strongest fixed habit BEAT it, because defending costs output and
    # output was the only thing that mattered. A continuous fight has to be
    # sized for a continuous fight.
    boss_switch_hp_pct=100,
    # Turns after the handover during which the incoming mechanic's BOSS gate
    # -- its max-health fraction -- does not apply. Its ordinary tier damage
    # does; only the execution is held back.
    #
    # Measured, this is the whole design. The informed line reached the
    # handover at 90-95% health and then died in the second half, in ONE hit of
    # 82-156 against a 203 ceiling: `momentum_boss_frac` is 65% of the ceiling,
    # and the rule that was correct in the first half -- against an enrager,
    # never play a non-attack card -- is exactly the rule that leaves you
    # holding no shield at the moment the second rule starts punishing turns
    # without one. The habit becoming wrong is the point; a first occurrence
    # that kills outright is not a lesson, it is a coin flip on what was in
    # hand. Every other mechanic in this game already has a probe rung whose
    # first appearance buys evidence and is survivable, and the handover was
    # the one place a mechanic could arrive without one.
    boss_switch_grace=0,
    # Experiment only: merge the same two draws in the opposite order. Two
    # SEQUENTIAL fights want a clock-triggered rule second, because a
    # player-triggered one gets raced past. One CONTINUOUS body may want the
    # opposite, because the second rule arrives with whatever hand the first
    # rule's correct answer left behind -- and "stop playing that card" needs
    # nothing in hand, while "start blocking" needs a shield you may not have.
    boss_switch_reverse=0,
    # Announce the handover, as a neutral cue and nothing more. Off is the
    # SILENT arm. Neither is a default: they ask different questions and the
    # matrix has to be run twice.
    #
    # Measured, the silent arm is not always a fair question. The only thing on
    # screen that can mark a handover is the first half's gain falling away --
    # and it only rose if the player made the first half's mistake, so playing
    # the first half CORRECTLY makes the change invisible. 39% of
    # `enrage -> momentum` handovers had no visible tell at all, and
    # `pierce -> momentum` and `charge -> enrage` have none ever: those two
    # mechanics do not move the printed attack.
    boss_switch_hint=0,
    # Whether the first half's accumulated threat survives the handover. Off is
    # the loud version: the attack falls back and the player can see that
    # SOMETHING changed. On is the silent version. Which of the two is the
    # better question is a measurement.
    boss_switch_keeps_bonus=0,
    # Committed intent. A wind-up that is ALREADY at the top when the turn
    # begins has entered its release: killing the enemy that turn no longer
    # cancels it, and the only answer left is the dodge. Without this, 40% of
    # the wind-ups that reached the top on a boss were simply out-raced -- the
    # exam was cancelled rather than failed, and "attack every turn" scored as
    # if it had understood the counter.
    #
    # It is NOT a discount on the first swing and NOT a shorter wind-up: the
    # two-turn warning and the full play phase both survive. What dies is only
    # the shortcut. A counter that fills DURING this turn cannot lock this
    # turn -- charge advances after the attack, so there is always a whole turn
    # of notice, and an unfilled enemy killed mid-turn still loses its action.
    charge_commits=0,
    # Arm C, and only meaningful with `charge_commits` on. A locked wind-up
    # with no dodge reachable is not an examination, it is a coin flip: measured
    # on fixed boss entries, 17.2% of locked turns had no answer available and
    # ALL of them died. So the moment the counter reaches the top, one dodge the
    # deck ALREADY owns is moved into the hand -- moved, never copied, so deck
    # size and exhaustion stay true. It is not a hint (the counter was already
    # on screen and the wind-up already took two turns), and it is not a
    # discount: the card still costs the turn, and not playing it still kills.
    charge_returns_dodge=0,
    # Arm E, the cleaner alternative to C. Every boss stage OPENS with a dodge
    # in hand -- not when the counter fills, and not only on a charge stage. The
    # hand carries, so a player who has read the wind-up holds it until the top;
    # a line that plays a dodge whenever it holds one burns it on turn one; and
    # because every stage gets one, the card's arrival says nothing about what
    # the stage is. C hands you the answer a second before the question; E hands
    # you the tool at the start and leaves the timing to you.
    #
    # Done LOCALLY, in `Fight._guarantee_dodge`, not by adding "dodge" to the
    # pile's own opening guarantee. That machinery can only displace a slot
    # whose kind is not itself guaranteed, so a hand drawn as four attacks and
    # blocks had nothing to displace and the "guarantee" silently missed 12.3%
    # of boss stages -- and fixing it there would have changed the draw rules
    # every ordinary fight and the camp share.
    boss_opens_with_dodge=0,
    # The boss charge stage opens with the counter ALREADY this high. Two turns
    # of warning become one, without shortening the cycle: `charge_max` stays
    # 2, so after the first swing it is a two-turn wind-up again. That is the
    # difference from `charge_max_boss=1`, which asks for a fresh dodge every
    # other turn and dropped informed play to 38%.
    #
    # Clamped below `charge_max` wherever it is read: a stage that opened
    # already at the top would lock on turn one, which is the un-announced
    # swing the whole committed rule is built to avoid.
    boss_charge_start=0,
    # The shield's size, as a percent of `camp.BLOCK_RATIO`. It is here and not
    # in camp.py because it is a CALIBRATION knob: pierce and enrage both
    # punish a move, and a move nobody wanted to make anyway is not a
    # temptation -- avoiding it costs the ignorant player nothing, so the
    # mechanic teaches nothing. Making defence worth choosing is what gives
    # those two punishments something to bite.
    # --- momentum ---------------------------------------------------------
    # The mirror of enrage, and the answer to the shortcut pierce cannot close
    # on its own. `pierce` punishes holding a shield; its correct play, "never
    # block", is a fixed habit that costs nothing anywhere else -- measured, a
    # blind line that never blocks cleared the pierce test fight 94.4% against
    # an informed 92.0%. A mechanic whose answer is a free universal habit
    # teaches no identification at all.
    #
    # Momentum counts turns spent WITHOUT a shield. Holding one resets it to
    # zero; a dodge does not, because a dodge answers this turn's damage and
    # this mechanic is about the ramp. So:
    #
    #     never block     punished by momentum
    #     always block    punished by pierce
    #
    # and neither habit can be held unconditionally. On screen it looks exactly
    # like enrage -- the enemy's attack number rises -- which is deliberate:
    # one experiment separates them, because a shield makes an enrager's attack
    # go UP and a momentum enemy's go DOWN.
    # FROZEN. The adventure ladder, calibrated against pierce's and against the
    # journey-teaches/boss-examines split:
    #
    #     1st unshielded turn    7.9% of the ceiling   2x a normal hit, survivable
    #     evidence then more     45.3%                 clearly maimed, not dead
    #     kept it up             3rd one kills
    #     one hit from full      never lethal
    #
    # 1600 was tried and rejected: it kills on the SECOND, which skips the
    # "maimed" step the adventure is supposed to teach with. 800 was tried and
    # rejected the other way: three hits still leave you standing.
    momentum_probe_ratio=120,  # after the 1st unshielded turn, % of base_atk
    momentum_full_ratio=1200,  # TOTAL from the 2nd on
    momentum_cap=2,
    hp_momentum=(3, 7),
    # Boss gate, the same shape as `enrage_boss_frac`: a floor on the full
    # tier rather than outright death, because a turn without a shield can be
    # forced -- no block in hand, or the energy spent on a wind-up's dodge.
    # FROZEN at 65: two of them kill, so a second deliberate unshielded turn is
    # fatal while the first stays survivable. A floor and not outright death,
    # for the same reason as `enrage_boss_frac` -- a turn without a shield can
    # be forced, by an empty hand or by energy spent on a wind-up's dodge.
    momentum_boss_frac=65,
    # Does a shield CLEAR the ramp or only step it down one?
    #
    # Clearing it made the mechanic nearly worthless as knowledge: the default
    # line already blocks 0.30 times a turn -- not from choosing to, but because
    # `act` plays a shield once it runs out of attacks -- and a single block
    # every three turns is enough to keep a ramp that resets to zero pinned
    # there. Measured, knowing momentum was worth 5.9 points of a whole run
    # while never blocking at all was worth -33.
    #
    # Stepping down by one instead asks for something the default CANNOT
    # produce: the ramp climbs every turn it is not answered, so holding it down
    # means shielding nearly every turn, and that only happens if the shield is
    # played AHEAD of the attack. The rule stays as readable either way -- the
    # printed attack goes up a step, or down a step, right after your own card.
    momentum_resets=1,
    # 举盾在**结算之前**压掉斜坡，而不是之后。
    #
    # 现状（0）下斜坡在伤害落地之后才重置，所以举对了的人照样挨这一记加成
    # 伤害，只被盾吸掉一部分。实测：懂的人 momentum 失误率 0.8%（每条命 0.02
    # 次）却照样掉血，于是把 `momentum_probe_ratio` 从 120 抬到 250，ALL 从
    # 85.9% 掉到 78.1% 而 Vmin 一点没涨 —— 加重打的是所有人。
    #
    # 置 1 之后，正确的答案真的挡得住这一击，加重就只落在没举盾的人身上。
    # CANDIDATE，默认关，因为开它要重测四张确认图并重跑搜索。
    momentum_resets_before_hit=0,
    # 斜坡只认「安静的盾」：出了攻击牌的回合，举盾不重置斜坡（原型，默认关）。
    # 斜坡被踢出六池的原因是参考策略「攻击 + 余下能量举盾」顺手就把它压住了，知识价值 ≈ 0。
    # 破势用「攻击加固封印」堵住了这条路；这个旋钮把同一条堵法搬到斜坡上，用来回答
    # 「要新怪还是修旧怪」。
    momentum_quiet_reset=0,
    # 大招被闪掉时**不重置**蓄力槽。
    #
    # 现状（0）下不管挨没挨到，满格之后一律归零，所以闪掉一次就买到两个回合的
    # 安全。置 1 之后闪掉的那一次槽位还是满的，下一回合必须接着闪 —— 会闪的人
    # 价值上升，而不是挨打的人代价上升。
    #
    # 这个方向和「把 big_mult 调大」不一样：实测 big_mult 6->9 让 ALL 从 84.0%
    # 掉到 69.0% 而 Vmin 从 32.0% 掉到 19.2% —— 幅度是所有人一起挨的旋钮。
    # CANDIDATE，默认关。
    charge_keeps_on_dodge=0,
    # 第二轮（`test` 遭遇）比第一轮（`teach`）贵多少，% 加成。
    #
    # 两轮制下每种机制出现两次：第一次给你看，第二次考你。现在这两次的数值
    # 分布完全一样 —— 实测参考线整局攻击力恒为 7.00（它的路线选上限奖励而不是
    # 攻击），牌组 18 -> 22.4，怪的血量和攻击全程在同一条带里。所以曲线是平的，
    # 「考」那一次并不比「教」那一次贵。
    #
    # 只加在 `test` 上，`teach` 原样：第一次遭遇必须活得下来，因果链才闭合得了
    # （证据要能被观察到，之后还要有一次改变行为的机会）。
    #
    # 两个分开调，因为它们打的不是一回事：血量决定机制有几个回合把题问出口，
    # 攻击决定答错有多贵。CANDIDATE，默认 0，开了要重搜。
    test_hp_pct=0,
    test_atk_pct=0,
    # 反过来的一半：第一轮（`teach`）打折。
    #
    # 只加 `test` 实测把 ALL 从 82.7% 打到 46.6%（+20%），代价全出在考试那五
    # 场连着抽血上。要的是「前面杂兵脆、后面精英厚」的梯度，不是整局更贵 ——
    # 所以第一轮往下调，把血还给玩家，再让第二轮把它拿走。
    #
    # 风险写在这里：teach 场太脆 = 机制没有回合把题问出口（charge 需要
    # `charge_max` 回合起手，momentum 的斜坡要爬）。所以扫描必须分轮报机会数，
    # 光看 ALL 会把「学不到」误读成「过关了」。CANDIDATE，默认 0，开了要重搜。
    teach_hp_pct=0,
    teach_atk_pct=0,
    # --- 期中题 -----------------------------------------------------------
    # 两轮之间一道小考，一局一道，机制由地图自己抽。
    #
    # 它分开的是「看过」和「会用」。杂兵战之后模型也许已经能把规则说出来，但
    # 出牌照旧 —— 现在这个断点会在精英把它淘汰之前先显形一次。所以这道题的两
    # 条硬要求跟数值无关：**问题必须真的问出口**（不能像 teach enrage 那样三成
    # 遭遇一次机会都不给），**答错之后必须还活着走到下一次机会**（否则它就是
    # 提前淘汰，不是小考）。
    #
    # 不告诉玩家机制名、不给正确牌、不发额外奖励 —— `kind` 仍是 "fight"，路牌
    # 上看不出区别，里程碑奖励也把它排除在外，免得插一场就把经济改了。
    #
    # 血量往上是为了让斜坡/蓄力爬得到窗口，攻击往下是为了「代价明显但不淘汰」。
    # CANDIDATE，默认关。
    midterm=0,
    mid_hp_pct=0,
    mid_atk_pct=0,
    # 期中题算不算进「每 rest_every 场一次休息」的节拍。算（默认）＝节拍诚实，
    # 小考后面紧跟一次休息；不算＝十场的休息位置和现在完全一样，代价是 5、小考、
    # 6 三场连着打。
    mid_counts_to_rest=1,
    # 强制考哪一种，"" ＝ 地图自己抽。抽签那一步照抽不误再被覆盖，所以五种机制
    # 的臂跑在**同一个世界几何**上 —— 否则「哪种机制问得出口」会和「哪张地图」
    # 混在一起，而它们的差别比机制本身还大。
    mid_mechanic="",
    # 期中题的辨识度：开局就把蓄力槽装满，窗口落在第一回合。
    # 惩罚自动「低一档」——满血满能量时挨的那一下，不需要另一个旋钮。
    # 每只怪开局带一个可见签名：规则已学会的机制，身份免费读出。
    # 实测一场战斗第一回合玩家只看得到自己的槽位，怪的每一格都印 `?` ——
    # 于是「认出这是谁」要每遇到一只新怪重付一次，那是对知识收税。
    # CANDIDATE，默认关；开了要重新量习得曲线，因为它正是「一学就会」的风险所在。
    marks=0,
    # 怪方状态槽上不上画面（2026-10-20）。之前 `_row` 只印蓄力槽，守相、标记代号、模仿、封印从不上画面，只在变化那一刻
    # 出现在日志行里 —— 但这些机制的注释都写着「印在它身上的公开槽位」，参考策略也直接读它们。三种：
    #   hidden   旧画面（只印蓄力，且只在非零时）。登记 11 的认证、pilot 都是它
    #   carrier  带这种机制的怪才印它的槽，开局就印当前值（含 0）：看见槽就认得出是哪种怪
    #   all      每只怪都印池里这几种机制的槽（含 0）：槽本身不说明是哪种怪，要等值变非零
    #   seen     只整理玩家已经拿到的信息（2026-10-20 定的规范）：守、标记、模仿、封印的槽，这一场里第一次变化之前连槽名都
    #            不印，变过之后一直印当前值（含 0）；蓄力槽照旧（非零就印），另外变过之后也一直印、含 0。画面给的不超出日志。
    #            carrier / all 开局就印当前值，造出了不懂规则的捷径（「怪身上有数字亮着就闪避」在只有这几类机制的图上过关率
    #            0 → 71–100%，scripts/public_info_check.py 之前的筛查）；seen 在同样四张图上回到 0。
    # 只改画面，不改任何规则；脚本策略和认证不读画面（scratchpad 轨迹快照：各模式下逐步相同）。
    state_slots="hidden",
    # 不上画面的格子（(side, prop) 的元组）：状态行不印、变化行不印、对应表不列。2026-11-11（用户）：v7 里本回合进攻次数（offence）
    # 和上限血（cap，没有治疗后永远不变）只是干扰。由 antagonist_proto 的 PROTO_HIDE 设；默认空 = 旧画面逐字不变。
    hidden_props=(),
    # 封印格在“第一次挡掉攻击”时上画面（11-11，用户「ok你改吧」）：seen 画面只印变过的格子；教学场封印起始 = 上限 = 1，封着时攻击
    # 不改变它的值，于是一直攻击就永远看不到它。1 = 挡掉攻击即算“起过作用”，记进 slots_changed，此后一直印（同护甲“起过作用才印”）。
    # 只改画面；默认 0 = 旧画面逐字不变。由 antagonist_proto 的 PROTO_WARDSEEN 设。
    ward_seen_on_block=0,
    # 破势只认纯举盾（11-11，用户「只把代码里的逻辑改成只出盾才能克制ward」）：1 = 封印 −1 只在这一回合出的牌全是盾牌（没有攻击、
    # 没有加成或其他牌）且盾挡住了这一击时发生；出了加成+盾的回合封印不动（不涨不落）。0（默认）= 原规则：没出攻击且盾挡住即 −1。
    # 由 antagonist_proto 的 PROTO_WARDSTRICT 设。
    ward_block_only=0,
    mid_charge_start=0,
    mid_opens_with_dodge=0,
    # --- 每轮的「答错要付多少」-------------------------------------------
    # 和血量/攻击不是一回事。血量攻击是**答对的人也要付**的消耗，实测把它当难度
    # 用会两头挨打：第二轮 +20% 血让懂的人从 82.7% 掉到 46.6%，而把第一轮调便宜
    # 来补，最强盲线从 5.7% 涨到 21.8% —— 折扣对无知比对知识更值钱，因为第一轮
    # 本来就是筛掉蛮力线的那道门。
    #
    # 这三个只缩放 `Enemy.punish` 那一组量，答对的人一分不付。所以它能让两轮真的
    # 分难度：第一轮答错便宜（可以试探），第二轮同样的错很贵。
    teach_punish_pct=100,
    mid_punish_pct=100,
    test_punish_pct=100,
    # 逐只标定,不是统一乘一个百分比。
    #
    # 「更厚更疼」和「多出几次有效决策」不是同一根杠杆,对 charge 甚至指向相反:
    # 现有 `elite` 分支是**减血 + 短蓄力**,注释里写着为什么——喂胖它会让大招
    # 永远打不出来(实测攻击 5 时 87% 打得出,拿一次攻击奖励后只剩 30%),
    # 「更早让你看见规律」才是精英该做的事,不是数字最大。
    #
    # 所以每种机制单独给一对百分比,空 dict 表示退回上面的标量。键是 behaviour。
    test_hp_by={},
    test_atk_by={},
    # 教学轮同样的逐机制攻击百分比（sweep 用；默认空 = 用 teach_atk_pct）。
    teach_atk_by={},
    # --- boss-only examination gates ------------------------------------
    # The journey teaches and the boss examines, and until now that split was
    # built for `charge` alone: `big_frac` and `big_lethal` are boss-scoped, and
    # pierce and enrage used the SAME numbers in both places. Measured, a boss
    # piercer took 39.4% of the ceiling from a repeated shield and could not
    # kill at all, and a boss enrager's second tier took 19.7% -- identical to
    # the journey. That is the boss still teaching, and it is why the paired
    # counterfactual read charge +38.2 against pierce +18.6 and enrage +5.3.
    #
    # A shield held against a piercer that has ALREADY eaten one is lethal on a
    # boss. It is the same rule the journey demonstrated at 8% and then 32%; the
    # boss only stops being forgiving about the third try.
    pierce_boss_lethal=0,
    # The enrager's full tier lands for at least this share of the ceiling on a
    # boss. Deliberately a floor and NOT outright death: enrage punishes every
    # non-attack card, and some of those -- a heal at low health, the dodge a
    # wind-up demands -- are correct plays a good player may rationally pay for.
    # At 65% two of them kill, so a second deliberate payment is fatal while the
    # first stays survivable. That is "expensive", not "executed".
    enrage_boss_frac=0,
    # How many ATTACK cards the starting deck holds, against three of each
    # other kind. It is a calibration knob and not cosmetic: `act` plays a
    # shield only once it has run out of attacks, so the deck ratio is what
    # sets the default blocking rate -- measured 0.33 a turn at three attacks,
    # entirely by accident. Any mechanic whose answer is "block sometimes" is
    # therefore answered by accident too: knowing momentum was worth 5.9 points
    # of a whole run while never blocking at all was worth -33.
    #
    # Changing it moves no randomness. `_roll_identity` builds the deck list
    # from these counts without consulting the rng, so a different ratio is the
    # same world with a different hand.
    # FROZEN at 6, against three of every other kind (18 cards).
    #
    # It is not a difficulty knob, it decides WHAT THE DEFAULT HABIT IS. `act`
    # reaches for a shield only once it has run out of attacks, so at three
    # attacks a blind line blocked 0.33 times a turn by accident -- and that was
    # enough to answer momentum for free. At six:
    #
    #     ignorant blocking   0.33 -> 0.27 a turn
    #     informed blocking   0.42 (unchanged -- it blocks on purpose)
    #     momentum's worth    5.8 -> 10.8 points of a whole run
    #
    # Nine was tried and rejected: the strongest fixed habit reached 13.8% of
    # runs, over the line, because fights get short enough that neither the ramp
    # nor the poison has time to matter.
    deck_attacks=6,
    block_pct=100,
    # What the shield COSTS, in energy, out of the two a turn gives you.
    #
    # At 1 it is not a decision at all. Attack costs 1 and `act` plays it
    # first, so the second point has nothing else to spend itself on and the
    # shield goes up whenever it is in hand -- measured, played on 32.8% of the
    # turns it was available, identically at every shield size from 60% to
    # 200%. That is why `block_pct` is inert: the card's VALUE cannot change a
    # decision that was never made on value.
    #
    # At 2 defending means giving up the swing, which is what pierce and enrage
    # need in order to punish something anyone wanted to do.
    block_cost=1,
    # 答案牌的稀缺性。牌组只在「答案稀缺 + 时机具体」的地方咬得住机制：闪避
    # 2 费、3 张、槽满那一回合才有用，所以 charge 的代价随牌组从 16% 到 37.5%；
    # 格挡 1 费、3 张、随时出都不亏，所以 momentum 只差 3.5 个点。这两个旋钮把
    # 稀缺性变成可调、进而可按世界变的量 —— 它们改的是经济，不是任何机制。
    # 费用在出过一次牌之后印在屏幕上（`cost_known`），是局内可观察的。
    dodge_cost=2,
    # 每种牌的起手张数覆盖，键是 kind；没写的用 STARTING_PILE / deck_attacks。
    deck_counts={},
    big_ignores_block=1,
    # Heal only below this fraction of max health. The screen re-rolls until the
    # reference play clears 70-90%, so a WEAK reference makes it accept easy
    # runs -- and easy runs are exactly what an uninformed player also clears.
    # Healing at a flat 10 missing burned all three heals in the first fight and
    # cost the energy that should have been attacks.
    heal_below=40,      # percent of max health
    # 5, not 4. The screen re-rolls until the reference play sits in the band,
    # so raising difficulty ACROSS THE BOARD changes nothing -- it just makes the
    # screen pick softer runs. Only a knob that punishes the wrong answer while
    # leaving the right one alone moves the gap, and the big hit is exactly that:
    # dodged it costs nothing, eaten it costs five times a normal hit.
    big_mult=6,         # how much harder the big hit lands
    pierce_off=1,              # only used when pierce_eats_block is off
    # The piercer feeds on your shield: damage = attack + the block you hold.
    # Under the old rule (attack - 1, ignoring block) holding a shield still
    # SAVED you a point, so "do not block this one" was not just unrewarded, it
    # was wrong -- measured, a player who never worked the piercer out cleared
    # 79% while one who applied the rule cleared 69%. A mechanic whose correct
    # response loses is not a mechanic.
    pierce_eats_block=0,       # alternative form: damage = attack + k x block
    # Holding a shield against the piercer multiplies the hit (and it goes
    # through the shield anyway). Two reasons for a multiple of attack rather than of
    # block: rage makes attack vary within a fight, so "x3" is separable from
    # "+15" by observation, whereas block never changes inside a run and the
    # multiplier would not be identifiable. And it is the only shape that makes
    # the piercer a real mechanic -- see the note on pierce_eats_block above.
    # 5, not 3. The jump is non-linear: 4 moved the half-informed line not at
    # all (35% -> 34%) and 5 halved it (-> 20%), while informed play stayed at
    # 92%. At attack 12 one shielded turn costs 60 -- about half your health --
    # which is a signal you only need to receive once. Raising the BIG hit
    # instead was tried and is worse: big_mult 8 drags informed play down to 62%,
    # because the dodge is not always in hand and the informed line eats it too.
    # An unmarked piercer must be discovered by interaction. The first shielded
    # hit is therefore a loud but survivable 2x signal; repeating the same
    # mistake after that signal gets the full 5x punishment. The old rule made
    # the unavoidable first probe 5x AND permanently doubled later hits, so an
    # observation-legal fully informed player could not clear reliably.
    pierce_probe_mult=2,
    pierce_mult=5,
    pierce_grudge=2,    # after a second shield, later hits stay this much harder
    pierce_returns_block=1,  # guarantee a fair next-turn correction opportunity
    # Boss-only floor for a charged hit, as a percent of maximum health. Normal
    # chargers still hit for `big_mult` times attack: dangerous and worth
    # dodging, but not a general near-one-shot. The boss may be lethal because
    # its two-turn warning is itself the final learned mechanic being tested.
    big_frac=70,
    # A connected big hit kills outright. 0 = off, 1 = boss only, 2 = every
    # charger. This is the only shape a health pool cannot absorb, and charge
    # was the one mechanic left whose cost was absorbable -- however hard the
    # hit, it was still just damage, and damage is what resting and healing
    # undo. It is not an unfair death: the wind-up is visible two turns ahead
    # and the hand keeps unplayed cards, so a player who understands it can sit
    # on a dodge and wait. The warning IS the mechanic.
    big_lethal=1,
    # Health and attack are drawn per ENEMY, inside these bands, instead of
    # coming out of a fixed formula. The screen has to satisfy three conditions
    # at once now -- informed high, every partial low, fights short -- and with
    # the numbers pinned there was simply not enough freedom to find such a run:
    # 5 seeds in 24 landed, the rest fell back to a near miss.
    #
    # What stays fixed within a run are the MECHANIC constants (how many turns
    # the wind-up takes, what a shield costs against the piercer, how fast the
    # poison stacks). Those have to be constant or no rule about them is
    # inducible from one run's evidence -- two chargers with different
    # multipliers is noise, not difficulty. The bands below are wide enough to
    # search and narrow enough to stay sane: a charger is always the fat one, an
    # armoured enemy always the thin one.
    hp_normal=(4, 9),   # enemy health as a multiple of starting attack
    hp_charge=(6, 11),  # thicker: it must live long enough to swing
    hp_regen=(2, 4),    # thinner: what it claws back is extra health
    hp_armour=(2, 5),   # thin: every hit lands for almost nothing anyway
    armour_off=0,       # armour = my attack - this
    armour_hp_scale=55, # an armoured enemy prints less health
    regen_hp_scale=60,  # a regenerating boss prints less health
    hp_elite=(4, 8),    # elite health, as a multiple of attack
    eatk_elite_mult=(140, 220),  # elite attack, % of the player's
    # Generic difficulty and mechanic difficulty pull in opposite directions and
    # have to be tuned apart. Chip damage hurts everyone equally, so it only sets
    # the ceiling; the big hit and the shield-eater hurt exactly the people who
    # did not work them out. So: raise health, raise big_mult.
    # THE one absolute is `base_atk`, and it is cosmetic: it sets how big the
    # printed numbers are and nothing else. Everything that decides difficulty
    # is a ratio, so a seed that rolls attack 8 plays the same game as one that
    # rolls 5 with larger digits.
    #
    # This used to be false, and it was the largest uncontrolled difficulty
    # variable in the system. Health was drawn from a fixed pool while enemy
    # attack scaled with the player's, so "how many hits can I take" ranged from
    # 155/5 = 31 down to 135/8 = 17 -- nearly a factor of two -- decided by a
    # coin flip. Worse, both halves are IDENTITY: `_roll(salt)` re-rolls only
    # the world, so the screen could re-roll two thousand worlds and never touch
    # the ratio. Measured: an attack-5 seed screened to 91% informed, one
    # attack-8 seed to 78%, and another to 35% at every block value tried.
    life_in_hits=29,    # max health = base_atk x this (145 at attack 5, as before)

    dodge_persists=0,   # 1 = dodge waits until it absorbs a hit
    reward_atk_ratio=20,  # elite reward: attack, % of base_atk
    reward_hp_pct=12,   # elite reward: max health, % of the starting ceiling
    # 10, not 9. At 9, 5-6% of boss fights ended before the wind-up completed --
    # the boss exists to test what you learned, and in those runs it tested
    # nothing. One extra multiple of attack costs 2 points of informed clear rate
    # and buys a guarantee. Verified by check.py 8.8.
    hp_boss=(7, 13),
    # Percent, applied to the WHOLE boss budget before it is split. `hp_boss`
    # was set when the boss was one fight; splitting it in two gave each stage
    # 40-60% of a number that was never meant to be halved, so a stage can end
    # in two turns -- measured on a real run, a 25-health enrage stage next to
    # a 77-health ordinary monster on layer 14. A stage that dies before its
    # mechanic resolves is not an examination, it is a thin ordinary fight.
    # Kept as its own knob rather than raising `hp_boss`, because `hp_boss`
    # also has to keep meaning "one boss's worth" for any single-stage config.
    boss_hp_pct=125,   # FROZEN
    # Least health ONE stage may print, as a multiple of the player's attack.
    # A percentage alone cannot promise a stage is long enough: it scales the
    # whole budget and the split still runs 40-60%, so the thin half stays
    # thin. The rush line kills for about 2x attack a turn, so 6x is three
    # turns of it. 0 turns the floor off.
    boss_stage_min=6,  # FROZEN
    # Boss attack, percent, applied AFTER the draw exactly like `wear_pct` --
    # moving the band would shift every later word in the stream and the sweep
    # would not be comparing the same maps.
    #
    # This is the half a health knob cannot do. Health alone bought 0.6 extra
    # turns for the line the model plays and cost two thirds of the informed
    # clear rate, because every extra turn is also another ordinary hit. The
    # point of a longer stage is observation time, not more attrition, so the
    # two move together: health up, base attack down, mechanic punishment
    # untouched.
    boss_wear_pct=70,  # FROZEN
    # Temporarily barred from the boss pool. Measured, a pierce stage does not
    # ask anything on its own: against a line that never blocks it fired in 18%
    # of stage-1s and 26% of stage-2s, and raising health to 200% only reached
    # ~55% -- because the trigger is the PLAYER's shield, not the clock. It
    # stays in the journey, where its teaching chain is fine, until it has a
    # boss-shaped question of its own.
    # NOT frozen, and it cannot be: the canonical three-mechanic rotation is
    # (poison, charge, pierce), and poison is not boss-capable, so excluding
    # pierce there leaves one behaviour for a two-stage boss and `_roll_world`
    # refuses to build. 171 tests said so within a minute of trying. The
    # suspension is a property of the five-mechanic development configuration,
    # so it lives in `devworld.OVERLAY` -- which is also what "suspended, not
    # deleted" should look like in the source.
    boss_pool_exclude=(),
    hp_boss_persistent_floor=3,   # floor for the class scaling, pre armour_hp_scale
    boss_hp_armour=100,      # percent, applied on top of armour_hp_scale
    boss_hp_persistent=100,  # percent, for a boss whose parts all persist
    eatk_mult=(100, 160),   # enemy attack as a % of the player's attack
    eatk_boss_mult=(120, 180),
    repeats=2,                # 每种怪有几个专属层（学一次、验一次）
    rest_every=2,             # 每几个战斗层后固定放一个休息层
    n_elites=2,               # 全图有几个精英节点
    rest_chance=70,           # 每层出现休息节点的概率（百分比）
    # Two STAGES, not two parts. A boss built by unioning two behaviours can
    # set them against each other: a charger wants the dodge held for the
    # wind-up and an enrager punishes every non-attack card, so `charge+enrage`
    # has no answer that is right for both. A world containing one is not a
    # harder question, it is an unanswerable one -- and the clear rate it
    # produces is indistinguishable from a mechanic that does not work, which
    # is exactly the reading that would be used to judge a four-mechanic
    # rotation.
    # Base attrition, percent. Scales what every enemy hits for, and therefore
    # what a player who answers every mechanic correctly still loses. It does
    # NOT touch `big_mult`, `pierce_mult`, `pierce_grudge`, `enrage_full_ratio`
    # or `poison_cap` -- those are what playing WRONG costs.
    wear_pct=100,
    # 0 = the old map: two random meetings per mechanic, two random elites that
    # also carry the loot. 1 = teach-then-test, with strength and reward pulled
    # apart. A switch rather than a replacement so the two can be compared on
    # the same salts.
    curriculum=0,
    # Whether clearing a paying node hands out an upgrade at all. A knob, not a
    # deletion: removing the rewards is a real change to the health and attack
    # economy, so it has to be measurable against keeping them rather than
    # folded into the curriculum's effect.
    elite_reward=1,
    boss_stages=2,
    # Least share of the boss health budget one phase may get, percent. A phase
    # too short to reach its own mechanic is a phase that only costs resources.
    boss_stage_floor=40,
    regen_ratio=80,     # health a regenerator claws back each turn, % of base_atk
    poison_ratio=40,    # stacks a poisoner adds each turn, % of base_atk
    # 50, not 100. Making the tick bite AND take the same off the ceiling
    # charged twice for one mechanic and dropped the informed ceiling from 61%
    # to 28%. The visible half is there so the stack counter can be connected to
    # something on screen; the ceiling half is there so the cost outlives the
    # fight. Half of each does both jobs without either doing the other's.
    poison_cap=50,      # percent of each tick that also comes off the ceiling
    # The poisoner is answered on the MAP, not in the fight. Nothing in a fight
    # touches the stacks; what it costs you is ceiling, and the only thing that
    # gives ceiling back is choosing to spend a rest on it instead of on health.
    # So "did you work out the poisoner" reads as "do your rests go the right
    # way", which is a decision no card is involved in and no other mechanic
    # shares. It is also why the two rest options must not have a dominant one.
    hp_floor_pct=14,    # the ceiling can never be eaten below this % of start
    # Rest branches are deliberately different resources, not equal arithmetic:
    # health buys the next fight; ceiling+cleanse buys the remaining run. 35 cap
    # made the latter too generous once cleanse was included, so cap recovery is
    # smaller. Its immediate value is still mostly the removed poison stacks.
    rest_cap_pct=17,    # rest, option A: ceiling recovery, % of the start
    rest_pct=35,        # rest, option B: percent of the ceiling healed
    # 1 = the rest choice is removed (registration 12, 2026-10-27): every rest layer applies exactly the
    # "recover health" effect automatically -- health += rest_pct% of the CURRENT ceiling, capped at the
    # ceiling; no ceiling repair, no cleanse. Nobody chooses: `Run.rest(mode)` ignores `mode` under this
    # knob, so models, humans and every scripted player get one rule. 0 (default) = the two-way choice.
    auto_rest=0,
    hp_poison=(3, 8),   # thicker: the poison needs turns to become the threat
    # --- 流血（原型，默认不在 rotation 里）------------------------------------
    # 一条「答案是一张牌」的持续伤害机制。poison 的答案在休息点、啃的是上限；
    # 流血的答案是治疗牌、啃的是当前血。两者都跨战斗保留 —— 这是故意的，
    # 玩家会不会把它们都理解成「持续掉血」而用同一个答案，要实测，不能靶。
    #
    # 层数在怪每回合行动时加，**不看盾也不看闪避**（和 poison 同一条规则）：
    # 若防御牌能挡住层数，原有打法就顺手解题，题等于没问。
    # 治疗清空层数。休息不清 —— 那是 poison 的答案，两个答案必须分得开。
    # 层数按玩家攻击归一（`scaled`），和 poison_ratio 同一把尺。
    wound_ratio=25,          # 每回合加的层数，% of base_atk
    wound_heal_stacks=3,     # 参考策略从几层起用治疗去清
    hp_wound=(3, 7),
    # --- 反击（原型，默认不在 rotation 里）------------------------------------
    # 直接对着猛攻来的机制。现在五种里 pierce/enrage 惩罚的是过度防御，猛攻白送；
    # 只有 charge/momentum 两条在挡纯进攻线。反击的规则：一回合里第二次**进攻**
    # 动作（攻击或加倍）触发一记重击，穿盾。答案是克制 —— 一回合只进攻一次 ——
    # 不是任何一张牌，所以它对猛攻是结构性致命，而防御牌全都不受影响。
    #
    # 线索：你身上一个「本回合进攻次数」槽（0/1/2），加上那一下重击只落在 2 的
    # 回合。它和蓄力大招长得一样，靠这个槽和它的蓄力槽分辨 —— 一次观察不够。
    # 血量带比普通怪厚：一回合最多 2× 攻击，得活到第二回合才有题可问。
    counter_mult=4,
    # 第一次是探针，便宜；之后是重复，全价 —— 和 pierce 的 probe/full 同一个形状。
    # 没有它，反击倍数一涨就把懂的人一起打死：observable 下识别反击怪只能靠挨
    # 一次，那一次若是 8 倍 × 考试轮 250%，就是在为「合理的第一次探测」送命。
    counter_probe_mult=2,
    hp_counter=(6, 10),
    # --- boss 作为考试（原型，默认关）-------------------------------------------
    # 六池第二次登记的搜图里，counter 段的「懂 − 不懂这一段」均值 17–23%、17 张图为 0：
    # boss 段血量 42、攻击 8、价钱 100%（比考试轮的 250% 还便宜），到达的人有 250 血，
    # 探针 2×8 加全价 10×8 一共 96 点，三回合就把段打穿 —— 是墙不是考试。
    #   boss_punish_pct  boss 两段的错误价钱（0 = 沿用 Enemy 默认 100）。
    #   boss_no_probe    boss 不送探针：第一次反击/穿透/反弹/标记就按全价算（探针在
    #                    教学轮和考试轮已经给过了；到 boss 还没学会，就是没学会）。
    boss_punish_pct=0,
    boss_no_probe=0,
    # --- 牌名按包重掷 -----------------------------------------------------------------
    # 牌名按 seed 固定时，所有包的 `vorth` 都是攻击牌，换包不用重认牌。`names_key` 非 0 时
    # 从 `names-v1:{names_key}` 重新拼五个假词；调用方把它设成**包**的键（`devworld.
    # build_registered` 用包的第一个 salt），于是同一个包四条命名字不变、换包就换。
    # 只换名字：种类、数值、费用、牌序都不动；参考策略、盲线、账本全按 kind 走，认证不受影响。
    # 0 = 沿用 seed 名（pilot 包 P 上的 v1 数据是这么采的，P 包永远用 seed 名）。
    names_key=0,
    # --- 宇宙身份按包重掷（远迁移，2026-10-08）---------------------------------------
    # 0 = 身份（符号布局、基础攻击、盾与治疗数值、血上限）按 seed 掷，全库一套，旧世界原样。
    # 非 0 时身份按这个键掷，且布局用第 2 版：怪方整排状态槽一起洗牌（第 1 版里 B1 蓄力、B2 守势…
    # 是追加顺序的常量，任何 seed 都一样），己方的追加槽位也进洗牌。地图的结构（层、遭遇、顺序、boss 两段）
    # 仍按 salt 掷；怪的数值（numbers-v1:{key}:{salt}）和标记代号的映射（mark-v1:{key}:{salt}）按（键，salt）
    # 重掷。经济旋钮（血上限倍数、盾倍数、休息比例、毒的比例）由 devworld.world_economy 按世界抽后写进 TUNING。
    identity_key=0,
    # 身份第几版（identity_key 非 0 时才读）：2 = 世界 B（攻击从 {5,6,7,8} 抽）；3 = B 之后的世界（{5,…,9}，布局与牌流换名字）。
    identity_version=2,
    # --- 守势（原型，默认不在 rotation 里）------------------------------------
    # 两相交替：守相时你打中它的伤害全部反弹给你（它不掉血），开相正常。相位印在
    # 它身上一个公开槽位里（0/1），每回合翻。答案是时机 —— 守相不进攻、开相进攻
    # —— 不是任何一张牌；猛攻每隔一回合就把自己的输出吃回去。
    # 第一次反弹探针价（1×，不定价、一局一次），之后 guard_mult 倍。
    # 线索唯一：没有别的机制会让你自己的攻击让你掉血。
    guard_mult=3,
    guard_probe_mult=1,
    hp_guard=(5, 9),
    # --- 标记（原型，默认不在 rotation 里）------------------------------------
    # 每回合末它标记**你这回合出得最多的那种牌**（并列按 攻/盾/闪/疗/倍 顺序），
    # 印在它身上一个公开槽位里（1..5 的代号，含义要自己归纳）。下一回合你再出那种
    # 牌，当场挨一记穿盾重击。答案每回合都变 —— 任何固定习惯都表达不出来；猛攻
    # 每回合出攻击，就每回合被标记攻击，每回合挨打。第一次探针价、一局一次。
    mark_mult=6,
    mark_probe_mult=2,
    hp_mark=(4, 8),
    # --- 模仿（原型，默认不在 rotation 里）------------------------------------
    # 你出增伤牌，它也得到「下一击翻倍」：它身上一个公开槽位在你出牌的**当下** 0→1，
    # 回合末那一击按倍数结算、穿盾，然后槽位归 0。第一次探针价（2×，不定价、一局
    # 一次），之后 mimic_mult 倍经 punish 定价。答案是「对它别增伤」，除非这回合就能
    # 用翻倍的攻击打死它 —— 打死了它的那一击就不会落下（引擎：怪死了回合不结算）。
    # 陷阱放在玩家真正做的动作上：模型 85% 的战斗里出增伤，参考策略也用。
    # 和蓄力的区分：蓄力槽每回合自己涨；这个槽只在你出增伤那一刻动。
    mimic_mult=3,
    mimic_probe_mult=2,
    hp_mimic=(5, 9),
    # --- 势：牌之间的节奏资源（原型，默认关）------------------------------------
    # 你身上一个公开槽位。本回合**没有出攻击牌** → 势 +1（上限 tempo_cap）；这一场第一张
    # 攻击牌伤害 × (1 + 势)，然后清零。触发看的是「出没出攻击牌」，不看造成了多少伤害：
    # 打在守相上伤害为 0 还被反弹，那不是等待，不给势；出了增伤没出攻击，算等待。
    # 它不奖励「答对怪的题」，只让「这回合不打」有价值；代价是怒气（停顿回合怪的攻击涨），
    # 什么时候等、什么时候放，由眼前这只怪的规则决定 —— 深度来自取舍，不来自奖励。
    tempo=0,
    tempo_cap=3,
    # --- 破势（原型，默认不在 rotation 里）------------------------------------
    # 它身上一个公开槽位「封印」（起始 1）。封着时你的攻击造成 0 伤害；出了攻击牌的回合
    # 封印 +1（上限 ward_seal_cap）；**没出攻击牌**且盾真的挡住它一击的回合封印 −1；到 0 开启，
    # 攻击照常，ward_window 回合后封回 1。一直攻击的人打不死它（封印只涨不落）；
    # 「攻击 + 余下能量举盾」也开不了（+1 −1 抵消）—— 答案是「停手、举盾、再打」。
    # 没有伤害型惩罚：不懂的代价是时间（停顿回合怪的怒气涨）和打不死。
    # 第一次打在封印上是探针（0 伤害就是证据），之后封着还打才记错。
    # 数值由 8 包 32 图的 sweep 定（results/sweeps/ward_*.json）：hp(8,11)/窗 3 时懂的人在含它的图上
    # 只有 45%（等待 → 怒气 → 消耗），hp(4,7)/窗 4 时 81%，V_ward 81%，盲筛仍 0，boss 段 86%。
    ward_window=4,
    ward_seal_cap=3,
    # Experimental curriculum: 0 keeps the shared cap above. These only
    # change how many mistaken attacks a ward can remember; every encounter
    # still starts sealed at 1, so a correct first block has the same cost.
    ward_teach_cap=0,
    ward_test_cap=0,
    ward_boss_cap=0,
    # 分段起始封印（0 = 沿用 1）。教学 1、考试 2、boss 3 之类的阶梯：考试轮开场就要两个安静的挡下回合，
    # 窗口关上后也封回本段的起始值。只改「一开始要几次正确动作」，不改答案。
    ward_teach_start=0,
    ward_test_start=0,
    ward_boss_start=0,
    hp_ward=(4, 7),
    # --- 每局从池子里抽几种机制 ----------------------------------------------
    # 0 = 全部（现状，不消耗任何随机数，已确认的世界逐位不变）。
    # k = 每个世界用自己的命名流 `pool-v1:{salt}` 抽 k 种，两轮课程只在抽到的
    # 这 k 种上排；boss 两段也只从抽到的里面选。抽到的组合要含 >= boss_stages
    # 个能当 boss 的，不够就在同一条流上重抽。
    #
    # 这是让 `met` 有信息量的那一步：五种全在的世界里，「我见过什么」对「我该
    # 准备什么」没有信息，build 因此不是决策（实测：凭已见遭遇补答案牌 53%，
    # 永远拿攻击 58%）。抽选之后，见过 charge 才意味着第二轮还会来一只。
    pool_draw=0,
    # --- 旅途上答错的地板：占上限的百分比 ---------------------------------------
    # boss 早就有这条（`big_frac` / `momentum_boss_frac` / `enrage_boss_frac`），
    # 理由写在那里：按敌人攻击的倍数算的惩罚会被更大的血池和更低的 `wear_pct`
    # 一起冲淡。实测把 wear 从 90 降到 40，猛攻盲线从 2% 涨到 82%，因为反击
    # 的 4 倍、大招的 6 倍乘的都是被磨薄了的攻击。要把伤害从「人人都付」搬到
    # 「答错才付」，惩罚就不能跟着基础攻击缩。这里把同一条地板搬到旅途上：
    # 蓄力满格那一下、反击、穿透的重复举盾、斜坡满格那一下，至少打掉上限的
    # 这个百分比。经 `punish` 定价，所以教学轮照样便宜。0 = 关。
    punish_frac=0,
    # 地板只落在**重复**错误上：同一局里第二次以上被同一种机制罚。第一次是探测
    # （或者手里恰好没有答案牌），不该致命 —— 否则测的是抽牌不是理解。上限也
    # 封顶：价乘地板不能超过整条血，教学轮 50% × 45% 和考试轮 250% × 45% 都得
    # 是「很疼但活着」和「基本死」，而不是两边都秒杀。
    punish_frac_cap=60,
    # The enrager pays for the two extra layers it adds with its own health
    # rather than with the run's budget: it dies fast, so an informed line
    # spends few turns there, while the punishment it carries is scaled to the
    # PLAYER's attack (`enrage_full_ratio`) and so does not shrink with it.
    #
    # It deliberately does NOT get its own attack band. `eatk_mult` is shared
    # by every ordinary monster, so enemy attack currently carries zero
    # information about which one you are facing; giving the enrager a lower
    # one would let a line that never experiments classify it from the first
    # damage number. Health already leaks a little -- a single threshold on
    # printed health identifies a charger 78.9% of the time against a 67.0%
    # majority-class baseline -- and this band is chosen to sit inside the
    # existing spread rather than beside it.
    hp_enrage=(3, 7),
    # Pierce was the one rotation behaviour still falling through to
    # `hp_normal`, so it could not be moved without moving every monster that
    # has no band of its own. Opened at the same (4, 9) it inherited, so adding
    # the knob changes no number until someone deliberately moves it.
    #
    # Where it would go if moved, from the three-part measurement (6 worlds,
    # 84k turns, results/mechanic_value.json):
    #
    #     mechanic   question posed   divergence   HP lost wrong/right   lethal
    #     charge          6.4%           94.9%         48.5 / 7.3        11.4%
    #     momentum        7.1%           99.5%         24.8 / 11.5       10.9%
    #     pierce          2.5%           68.9%         95.1 / 13.3       36.0%
    #     enrage          8.9%           44.9%         25.1 / 11.5        6.6%
    #
    # Pierce is the rarest question and by far the most expensive to get wrong.
    # Thickening it raises how OFTEN it is asked, not how much it costs.
    hp_pierce=(4, 9),
    # Energy a turn. Held at 2 -- this is where it has always been, and it is
    # here rather than on the dataclass so that sweeping it reaches the engine.
    #
    # 2 is what makes "two offensive cards" the exact shape of a full turn:
    # attack and the doubler cost 1 each, dodge costs 2, and enemy health is
    # sized for ~1.5 attacks landing a turn. Capping the informed line at one
    # offensive action a turn costs it about 75 points of clear rate across six
    # worlds, so the double-swing is not a habit the participant fell into, it
    # is the only line that beats the clock.
    energy=2,
    # Cards drawn up to each turn. Held at HAND_SIZE, its historical value; it
    # is here so that it can be swept at all.
    hand_size=HAND_SIZE,

    # --- glutton ---------------------------------------------------------
    # The first mechanic whose answer is at the REWARD screen. Every other
    # monster asks "which card, this turn"; this one asks "which card did you
    # put in the deck three fights ago". Poison is the precedent -- its answer
    # is which way the next REST is spent -- so an answer taken off-turn is not
    # a new kind of thing here, and the same consequence follows: glutton is
    # not boss-capable, because there is no reward screen inside a boss.
    #
    # It exists because the corrected habit gate measured a hole nothing else
    # covers. The strongest fixed habit reached 22.6% and 29.8% against a 10%
    # bar, and the single thing carrying it was greed at the reward screen: the
    # SAME blind line reads 3.8% taking nothing and 24.1% taking one attack
    # card a fight, and a pure-aggression line goes 1.3% -> 5.1% -> 11.3% at
    # 0 / +3 / +6 attack cards. Attack cards are the fuel and taking one was
    # free, in a game where every other card in hand costs a decision.
    #
    # Scaled on cards taken BEYOND the starting deck, not on the deck total, so
    # a glutton met by a player who has taken nothing is an ordinary monster.
    # That is what makes it inducible rather than merely punishing: the printed
    # attack slot moves between one glutton and the next, and the only thing
    # that moved in between is a choice the player made and can re-read in
    # their own log.
    #
    # Only attack cards count. Making every reward poisonous would delete the
    # reward screen rather than turn it into a decision, and attack cards are
    # what the measurement actually indicted.
    glutton_ratio=20,   # enemy attack per extra attack card, % of base_atk
    # A ceiling on how many extra cards are counted. Uncapped, a line that took
    # ten attack cards meets something it cannot survive at all, which prices
    # the mechanic as instant death rather than as a decision -- the same
    # reason the enrager is two tiers and not a linear ramp. CANDIDATE value:
    # nothing has been calibrated yet, because glutton is not in `BEHAVIOURS`.
    glutton_cap=6,
    # Whether EVERY monster reads the deck, or only the glutton.
    #
    # Measured, the monster version cannot be a mechanic. Its knowledge value
    # is 0.3-0.7pp under the fairest convention available -- one policy for the
    # whole world population, with the informed line still allowed to branch on
    # having met one -- because its answer is a CONSTANT. "Stop taking attack
    # cards" is adoptable without knowing gluttons exist, which is exactly what
    # the informed line and the line that has never heard of one both do:
    # `take=None`. Every other mechanic's answer is conditional on something
    # visible inside the fight, so the two lines diverge; this one's is not.
    #
    # Two earlier readings said otherwise and both were the instrument. Letting
    # each knowledge set re-optimise its route PER WORLD hands the ignorant
    # line the one thing it does not know -- whether this world has a glutton
    # at all -- through the back door that `take_choice`'s `met` gate exists to
    # close. The gate's own convention (one route, chosen under full knowledge,
    # then ablated) reads 3-12pp, but its per-world numbers swing 4% -> 35% ->
    # -1% on the SAME world across magnitudes, which is the route search's
    # winner and not the mechanic.
    #
    # What it DOES do is price greed, and that is what the gate hole needed:
    # the strongest blind attack-taking line falls 38.3% -> 6.9% while informed
    # play falls 91.6% -> 84.7%. So it belongs where `deck_attacks` lives --
    # part of the economy every world has -- rather than in `BEHAVIOURS`, where
    # a Vmin-zero mechanic would drag every world's Vmin to zero with it.
    #
    # At 1 the ratio means something ~6x larger, because it applies to every
    # monster instead of one behaviour in six. It is swept separately.
    glutton_every=0,
    # Its own band for the reason `hp_enrage` has one, and deliberately inside
    # the existing spread rather than beside it: a glutton fight has no
    # in-fight answer, so it must not also be the longest fight in the run, and
    # printed health must not identify it for a line that never worked it out.
    hp_glutton=(3, 8),
)


@dataclass
class Enemy:
    name: str
    behaviour: str          # one of BEHAVIOURS, or "+"-joined for a boss
    hp: int
    atk: int
    charge_max: int = 0          # 0 = take from TUNING
    big_mult: int = 0
    rage: int = -1               # -1 = take from TUNING

    # A piercing hit is weaker but ignores block. Subtraction, not a fraction:
    # 2/3-with-rounding produced 4,4,5,5,6,6 against a visible 6,7,8,9,10,11, so
    # the damage stalled while the stat climbed and no simple rule fit. Rules
    # have to be inducible -- complexity from rounding is the same mistake as
    # the arbitrary register algebra and the block-is-exactly-twice-the-hit
    # coincidence, both of which defeated human testers.
    #
    # It must also stay STRICTLY above half the normal hit: blocking halves your
    # output and so doubles the fight, and the enemy only profits if
    # 2 x pierce > normal. Subtracting a constant satisfies this ever more
    # comfortably as rage pushes the attack up.
    pierce_off: int = -1
    regen: int = -1

    # One body, one health bar, two rules. `switch_to` is the behaviour that
    # REPLACES `behaviour` once health falls to `switch_at`, and nothing
    # announces it: no fight ends, no hand is redrawn, no state resets. The
    # only thing that happens is that the numbers start obeying a different
    # rule, and the habit the first half rewarded may now be the wrong one.
    #
    # It is stored as a threshold rather than a flag because an `Enemy` is
    # SHARED across every trial of a run. A phase written onto the object
    # would leak one trial's progress into the next -- the single most
    # repeated bug in this file's history -- so the phase is always DERIVED
    # from the health the caller is holding.
    switch_to: str = ""
    switch_at: int = 0

    # What a WRONG answer costs on this encounter, percent. It scales exactly
    # the set `wear_pct` refuses to touch -- `big_mult`, `pierce_mult`,
    # `pierce_grudge`, the enrage/momentum bonuses and `poison_cap` -- and
    # nothing else. The two knobs are the same axis split in half: `wear_pct`
    # prices what a player who answers everything correctly still loses, and
    # this prices what answering wrong adds on top.
    #
    # It exists because health does NOT separate the two rounds. Measured, a
    # 20% health rise on the five test monsters cost the informed line 36
    # points of clear rate, and discounting the teach round to pay for it
    # handed the strongest blind habit 5.7% -> 21.8% -- the discount was worth
    # more to ignorance than to knowledge, because the teach round IS the
    # filter that kills a brute-force line. Price is the axis that moves them
    # in opposite directions: a line that answers correctly never pays it.
    punish: int = 100
    ward_cap: int = 0           # 0 = shared ward_seal_cap; assigned by node role
    ward_start: int = 0         # 0 = 起始封印 1；按阶段（teach/test/boss）指定

    # 这一场开局蓄力槽就在第几格。和 `boss_charge_start` 同一条规则,包括
    # 「不是从零开始的槽位不能印成 ?」那条 —— 玩家读不到的警告不是警告。
    #
    # 它是期中题唯一能用的辨识度来源:实测一场普通战斗第一回合 `f.seen` 是**空**
    # 的,每一格都印 `?`,所以「开局就有一个真数字」这件事本身只有预装槽位做得到。
    charge_start: int = 0
    # 开局手里保证有一张闪避。和 `boss_opens_with_dodge` 同一条规则：槽满在第一
    # 回合，而第一回合的手牌是抽出来的 —— 不保证的话这道题问的是「你抽到了吗」，
    # 不是「你知道要闪吗」。你要的「一次明确可执行的选择」，缺了这一半不成立。
    opens_with_dodge: int = 0

    def __post_init__(self):
        for k in ("charge_max", "big_mult"):
            if getattr(self, k) == 0:
                setattr(self, k, TUNING[k])
        # rage and regen scale with the player's attack, which the enemy does
        # not know, so `make_enemy` passes them in. Only the dead
        # `pierce_off` path still reads a bare constant.
        if self.pierce_off == -1:
            self.pierce_off = TUNING["pierce_off"]
        if self.rage == -1:
            self.rage = 0
        if self.regen == -1:
            self.regen = 0
        self._parts = tuple(self.behaviour.split("+"))
        self._parts2 = (tuple(self.switch_to.split("+"))
                        if self.switch_to else self._parts)

    # Cached, not a property. `behaviour` never changes after construction and
    # this is read on every damage calculation of every simulated turn: 1.2M
    # calls and 7% of a screen went on re-splitting the same string.
    @property
    def parts(self) -> tuple[str, ...]:
        """The FIRST half's behaviours.

        Every in-fight reader must use `Fight.parts`, which knows the current
        health. This stays as the opening rule so that a non-switching enemy --
        every enemy on the journey -- reads exactly as it always did.
        """
        return self._parts

    @property
    def all_parts(self) -> tuple[str, ...]:
        """Everything this enemy can ever be. For world validity checks, which
        ask what a map contains rather than what is true this turn."""
        return tuple(dict.fromkeys(self._parts + self._parts2))

    def set_switch(self, to: str, at: int) -> None:
        """Both halves in one call. Setting `switch_to` alone would leave the
        cached second-half tuple pointing at the first half's behaviours, which
        is a boss that changes nothing and says nothing about it."""
        self.switch_to = to
        self.switch_at = at
        self._parts2 = tuple(to.split("+")) if to else self._parts

    def parts_for(self, phase2: bool) -> tuple[str, ...]:
        """Which rule set, given whether the handover has been APPLIED.

        Not "given the current health": health is what arms the handover, and
        the handover lands at the end of the turn. A rule that took effect the
        instant the health line was crossed settled the same turn's damage --
        so the player acted under the old rule and was punished under the new
        one, with no decision in between. That is an ambush, not an
        examination, and it was worth 70 points of informed clear rate.
        """
        return self._parts2 if phase2 else self._parts

    def parts_at(self, hp: int) -> tuple[str, ...]:
        """Which rule the health ARMS. Only `Fight._arm_switch` should ask."""
        return (self._parts2 if self.switch_to and hp <= self.switch_at
                else self._parts)

    def switched(self, hp: int) -> bool:
        return bool(self.switch_to) and hp <= self.switch_at

    def hit_now(self, stalls: int, charge: int, my_block: int,
                fed: int = 0, bonus: int = 0,
                parts: tuple[str, ...] | None = None,
                offences: int = 0, countered: int = 0,
                countered_run: int = 0, no_probe: bool = False,
                mimic: bool = False, mimic_seen: int = 0) -> tuple[int, bool]:
        """(damage, ignores_block) this turn.

        Rage counts STALLED turns -- turns in which you dealt no damage at all
        -- not turns in general. Counting turns punished defence itself: block
        is a way of spending time, so a per-turn ramp made the shield worth less
        and less until it was only ever played for lack of anything better. What
        needs punishing is refusing to fight, not defending while fighting.

        A charging enemy still swings while it winds up -- otherwise the big hit
        is perfectly predictable, gets dodged every cycle, and it never lands a
        scratch."""
        # `bonus` is the enrager's accumulated gain. It arrives as an
        # argument because an `Enemy` is SHARED across every trial of a
        # run -- writing it onto the object would leak one trial's
        # mistakes into the next, which is the single most repeated bug
        # in this file's history.
        cur = self.atk + self.rage * stalls + bonus
        if fed >= 2:
            cur *= priced(TUNING["pierce_grudge"], self.punish, over=1)
        parts = self.parts if parts is None else parts
        big = "charge" in parts and charge >= self.charge_max
        dmg = cur * priced(self.big_mult, self.punish, over=1) if big else cur
        # The big hit goes through block. Otherwise dodge and block are two
        # answers to one monster, and a player who never worked out the wind-up
        # still survives it by holding a shield -- which is exactly the "clears
        # without learning" path. Making it dodge-only also frees block to be
        # the sole answer to the pressure monster planned for B, so the two
        # defensive cards stop overlapping.
        if big and TUNING["big_ignores_block"]:
            return dmg, True
        if "pierce" in parts and my_block > 0:
            if TUNING["pierce_mult"]:
                # 探针**不定价**。探针是线索不是惩罚：教学轮 50% 把 2 倍探针四舍
                # 五入成 1 倍，线索就没了 —— 懂的人检测不到穿透怪，接着举盾，
                # pierce 错误率从 3% 涨到 21%。价钱只落在全价那一下上。
                mult = (priced(TUNING["pierce_mult"], self.punish, over=1)
                        if (fed >= 1 or no_probe) else TUNING["pierce_probe_mult"])
                return dmg * mult, True
            if TUNING["pierce_eats_block"]:
                # It feeds on the shield: damage = attack + whatever block you
                # are holding. The old rule (attack - 1, ignoring block) meant
                # blocking a piercer still SAVED you a point, so "do not block
                # this one" was not merely unrewarded, it was wrong -- measured,
                # a player who never learned the piercer cleared 79% while one
                # who applied the rule cleared 69%. A mechanic whose correct
                # response loses is not a mechanic.
                return dmg + my_block * TUNING["pierce_eats_block"], True
            return max(1, dmg - self.pierce_off), True
        if "counter" in parts and offences >= 2:
            # 反击：第二次进攻动作换来一记穿盾重击。排在大招和穿透之后，和向量
            # 引擎的 `~big & ~pierced` 一致；一场只有一种机制，顺序只为对拍。
            # 第一下探针价，之后全价（`countered` 是这一场已落下的反击数）。
            mult = (priced(TUNING["counter_mult"], self.punish, over=1)
                    if (countered >= 1 or no_probe) else TUNING["counter_probe_mult"])   # 探针不定价
            return cur * mult, True
        if "mimic" in parts and mimic:
            # 模仿：镜像翻倍那一击。第一次探针价、之后全价；穿盾。排在反击之后。
            mult = (priced(TUNING["mimic_mult"], self.punish, over=1)
                    if (mimic_seen >= 1 or no_probe) else TUNING["mimic_probe_mult"])
            return cur * mult, True
        return dmg, False



@dataclass
class Fight:
    """One fight. The deck cycles: played cards go to the discard pile and are
    reshuffled when the draw pile runs out. Heal is the exception -- it is
    removed for good, which is what makes it scarce across the whole run."""

    deck: dict[str, Card]        # name -> card definition
    deck_list: list[str]         # the run's deck, names with duplicates
    layout: Layout
    enemy: Enemy
    hp: int
    max_hp: int
    base_atk: int
    # 0 = take from TUNING, the same idiom as `charge_max` and `rage`.
    #
    # It was a plain `2`, and that is why a sweep of it silently measured
    # nothing: a dataclass BAKES its defaults into the generated `__init__` at
    # class creation, so patching `Fight.__dataclass_fields__[...].default` (or
    # assigning the class attribute) leaves every constructed fight at 2. An
    # experiment that ran four arms at 2, 3, 3 and 3 energy actually ran four
    # arms at 2, and its flat result read as "a bigger turn changes nothing".
    #
    # Every other design number lives in TUNING for exactly this reason. The
    # dict's own comment says hand-rolled models have twice produced the
    # opposite of the truth here; a monkeypatched dataclass default is the
    # third way to get a false answer from the real engine.
    max_energy: int = 0
    # 0 = take from TUNING, for the reason spelled out on `max_energy`. This
    # one was a named constant rather than a bare literal, which reads as
    # tidier and is the same defect: `camp.HAND_SIZE` is read once, at class
    # creation, so reassigning it -- or sweeping it -- moves nothing.
    hand_size: int = 0
    rng: random.Random = field(default_factory=random.Random)
    turn: int = 1
    state: dict = field(default_factory=dict)
    pile: Pile = None
    stalls: int = 0              # turns in which no damage was dealt
    dealt: int = 0               # damage dealt this turn
    seen: set = field(default_factory=set)

    is_boss: bool = False

    @property
    def no_probe(self) -> bool:
        """boss 不送探针（`boss_no_probe`）：第一次踩线就按全价。只在 boss 上。"""
        return bool(self.is_boss and TUNING["boss_no_probe"])
    poison0: int = 0             # stacks carried in from the run
    wound0: int = 0              # 流血层数，同样从局里带进来
    punished0: tuple = (0,) * 8   # 本局已被 PUNISHERS 各罚过几次
    mimic_hits: int = 0          # 模仿：这一场被镜像翻倍打了几次
    ward_open_left: int = 0      # 破势：开启还剩几回合
    ward_wasted: int = 0         # 破势：这一场打在封印上的攻击次数
    ward_opened: int = 0         # 破势：这一场解开过几次
    reflected: int = 0           # 守势：这一场被反弹了几次
    mark_hits: int = 0           # 标记：这一场被标记击中几次
    mark_hits_turn: int = 0      # 其中这一回合的
    # 代号 -> 牌种 的映射，每局重掷（`mark-v1:{salt}`）。固定映射下「背下数字对应
    # 哪类牌」就能跨命通过，测到的是表面知识不是规则。
    mark_perm: tuple = ("attack", "block", "dodge", "heal", "buff_mark")
    hp_floor: int = 0            # ceiling can never be eaten below this
    # `seen` drives the `? until it changes` display rule and nothing else. The
    # solver renders nothing, and maintaining it means walking every slot on
    # every action: 341k calls and 7% of a screen, for output no one reads.
    track_seen: bool = True
    # 怪方状态槽（ENEMY_STATE_SLOTS）这一场里**变过**的那些。和 `seen` 分开：`seen` 把开局就非零的值也算「已见」（封印 1、
    # 守相 1），而且脚本为省时间会关掉它；这一份每次出牌、每个回合末都记，只看 5 格。`state_slots="seen"` 的画面靠它：
    # 变化一出现就在日志里，画面只是把日志已经给过的值摆出来。
    slots_changed: set = field(default_factory=set)
    # --- audit only, never rendered -------------------------------------
    # Deliberately NOT part of `state`, so it cannot reach `show()`. A public
    # "absorbed" slot would hand over four things the player is supposed to work
    # out: the enemy's raw attack whenever a shield eats it whole, that poison
    # goes through block, that a charged hit is anomalous, and -- fatally for
    # the hardest gate -- that a piercer absorbs nothing. Block is a mechanic
    # you can identify by experiment (hold a shield one turn, not the next, on
    # the same enemy); armour was one you could not identify at all, which is
    # why armour got a slot and this does not.
    #
    # Whether the environment CAN be experimented on is not decided here and
    # not decided by anything the player does: invariant I9 settles it on
    # `settle_attack` itself, for every boundary case, on every test run. These
    # counters only describe what happened in a particular run.
    # Set once, by `_settle_phase`. On the Fight and never on the Enemy: one
    # `Enemy` is shared by every trial of a run.
    _phase2: bool = False
    _phase2_turn: int = 0
    _switch_pending: bool = False
    # Offensive actions taken in the CURRENT turn, for the second-offence arm.
    # On the Fight and reset every turn: an Enemy is shared across trials.
    offences: int = 0
    countered: int = 0           # 反击落下的次数（第一次是探针，之后是重复）
    last_offences: int = 0       # 上一回合的进攻次数，供回合末的检测器读
    # Structured events, append-only. A cue is produced here and TRANSLATED by
    # whoever is rendering -- the screen for a model, `observe_events` for a
    # reference policy. Pushing a formatted string straight into a log would
    # have given the model a cue the reference policies cannot see, and "two
    # rules, one of them only in the UI" is this codebase's most expensive
    # recurring defect.
    events: list = field(default_factory=list)
    blocked_turns: int = 0
    unblocked_turns: int = 0
    fully_absorbed_turns: int = 0
    absorbed_total: int = 0
    # Two different questions, deliberately separated because one number cannot
    # answer both:
    #
    #   blind_turns      ENGINE-side. A paired counterfactual on the SAME
    #                    pre-turn state: settle it once with the shield held and
    #                    once with it at zero, and compare only what the player
    #                    can see. A turn is blind when the shield absorbed
    #                    something and the visible result is identical anyway --
    #                    that is "cannot be learned however you experiment", and
    #                    it is the only thing that would justify showing the
    #                    absorbed amount. It does not depend on what the player
    #                    actually did.
    #
    #   turn_marks       the per-turn condition signature, so "did the player
    #                    ever produce a CLEAN contrast" can be asked separately.
    #                    An unshielded turn is only a control for a shielded one
    #                    if the enemy, its real attack, the wind-up phase, the
    #                    rage count, the poison stacks, the dodge and the
    #                    piercer's grudge all match; an unshielded turn that was
    #                    spent dodging, or eating a charged hit, is not a
    #                    control for anything.
    blind_turns: int = 0
    turn_marks: list = field(default_factory=list)
    broke: bool = False          # armour already broken this fight
    armour_seen: bool = False    # the armour has acted, so it may be shown
    fed: int = 0                 # number of shields a piercer has eaten
    enraged: int = 0             # non-attack cards an enrager has seen
    momentum: int = 0            # consecutive turns with no shield up
    dodge_offered: int = 0       # audit: times `charge_returns_dodge` fired

    def __post_init__(self):
        self.state = {("me", p): 0 for p in
                      ("hp", "atk", "energy", "block", "poison", "double", "dodge", "carry",
                       "wound", "offence", "tempo")}
        self.state |= {("them", p): 0 for p in
                       ("hp", "atk", "armour", "charge", "guard", "mark", "mimic", "ward")}
        self.played_kinds = {}       # 本回合各种牌出了几张（标记怪要读）
        self.last_kinds = {}         # 上一回合的，节奏盲线要读
        self.fight_kinds = {}        # 这一场累计的，标记按它加权抽
        if "guard" in self.parts:
            # 起始相位随机。固定从「开」开始的话，「只在奇数回合攻击」这条不读任何
            # 槽位的节奏习惯就能解掉守势 —— 答案得只能从槽位上读出来。
            g = self.rng.randrange(2)
            self.state[("them", "guard")] = g
            if g:
                self.seen.add(("them", "guard"))     # 非零起始不能印成 ?
        if "ward" in self.parts:
            self.state[("them", "ward")] = self.enemy.ward_start or 1   # 起始封着（按阶段）；非零起始要印出来
            self.seen.add(("them", "ward"))
        self.state[("me", "hp")] = self.hp
        self.state[("me", "cap")] = self.max_hp
        self.state[("me", "atk")] = self.base_atk
        if not self.max_energy:
            self.max_energy = TUNING["energy"]
        self.state[("me", "energy")] = self.max_energy
        self.state[("them", "hp")] = self.enemy.hp
        self.state[("them", "atk")] = self.shown_atk
        # This is the sole mitigation value. Attack rewards happen between
        # fights, so the gate is re-anchored to the player's current attack on
        # entry instead of being copied into an invisible Enemy attribute.
        self.state[("them", "armour")] = (
            _armour_for(self.base_atk) if "armour" in self.parts else 0)
        # Poison is the run's affliction, not the fight's. Clearing it between
        # fights made the poisoner worth twenty points of ceiling across a whole
        # run -- it only ever got three or four turns to build. Carried forward,
        # what it costs depends on how long you leave it, which is the shape a
        # long-range mechanic has to have.
        self.state[("me", "poison")] = self.poison0
        if self.poison0 > 0:
            # A non-zero carried stack necessarily changed in an earlier
            # fight. Re-entering combat must not turn an already observed
            # persistent value back into ``?``, even when Fight is constructed
            # directly instead of through Run._fight.
            self.seen.add(("me", "poison"))
        self.state[("me", "wound")] = self.wound0
        if self.wound0 > 0:
            self.seen.add(("me", "wound"))
        # 旧记录/夹具可能只带 6 项（mimic 之前）：补零到 PUNISHERS 的宽度，不改含义。
        self.punished = list(self.punished0) + [0] * (len(self.PUNISHERS) - len(self.punished0))
        if not self.hand_size:
            self.hand_size = TUNING["hand_size"]
        self.pile = Pile(self.deck_list, self.deck, self.rng,
                         hand_size=self.hand_size)
        if (TUNING["boss_opens_with_dodge"] if self.is_boss
                else self.enemy.opens_with_dodge):
            self.dodge_offered += self._guarantee_dodge()
        pre = (TUNING["boss_charge_start"] if self.is_boss
               else self.enemy.charge_start)
        if "charge" in self.parts and pre:
            # 期中题要的是**满**格 —— 窗口落在第一回合,不靠打够回合数攒出来,
            # 所以这里不像 boss 那样减一。`charge_max` 是上限。
            start = min(pre, self.enemy.charge_max
                        if not self.is_boss else max(0, self.enemy.charge_max - 1))
            self.state[("them", "charge")] = start
            if start:
                # Same rule the carried poison stack obeys: a slot that did not
                # start at zero must not print as `?`. A warning the player
                # cannot read is not a warning, and this one is the entire
                # mechanic.
                self.seen.add(("them", "charge"))

    @property
    def hand(self):
        return self.pile.hand

    # -- which rule is live ----------------------------------------------
    @property
    def parts(self) -> tuple[str, ...]:
        """The behaviours in force RIGHT NOW.

        For every enemy on the journey this is just `enemy.parts`. A boss that
        changes rules at a health line returns the second set below it, and it
        is derived from the health rather than stored, because one `Enemy`
        object is shared by every trial of a run.

        Every in-fight reader goes through here. `enemy.parts` on its own is
        the OPENING rule, and reading it mid-fight is how half the engine would
        keep fighting the monster the boss used to be.
        """
        return self.enemy.parts_for(self._phase2)

    def _in_grace(self) -> bool:
        """Is the incoming rule still inside its one survivable appearance?

        Only ever true after a handover. A boss that never changes rules has
        had its whole fight to show what it does, so nothing here applies to
        it.
        """
        return (self._phase2 and TUNING["boss_switch_grace"] > 0
                and self.turn - self._phase2_turn < TUNING["boss_switch_grace"])

    def _arm_switch(self) -> None:
        """The health line was crossed. The rule does NOT change yet.

        Called where the enemy's health changes, because that is what arms it.
        Applying it here settled the same turn under the new rule, so the
        player was punished for an action taken under the old one without ever
        getting a decision in between.
        """
        if not self._phase2 and self.enemy.switched(self.state[("them", "hp")]):
            self._switch_pending = True

    def _settle_phase(self) -> None:
        """Hand the fight over to the second rule, once, silently.

        Called at the END of the turn the line was crossed, so the next turn
        opens under the new rule and the player acts before anything can
        punish them for it. Nothing is printed, no fight ends, no hand is
        redrawn and no player state is touched -- energy, block, dodge, poison
        and the cards in hand all carry straight through. The only things that
        move are the counters that belong to the mechanics, and they move
        because a counter for a rule that is no longer in force is not a number
        about anything.

        The INCOMING mechanic starts from its own beginning, so the second half
        asks its question from the top rather than inheriting a count the
        player built up under a different rule. Charge is the exception and it
        is the same exception it already is at a boss opening: it starts at
        `boss_charge_start`, because a wind-up that needs its full count from
        scratch may never complete inside half a health bar.
        """
        if self._phase2 or not self._switch_pending:
            return
        self._phase2 = True
        self._phase2_turn = self.turn
        now = self.parts
        # The OUTGOING rule's accumulated threat. Dropping it is visible -- the
        # enemy's attack falls back -- which tells the player that something
        # changed without telling them what. Keeping it hides the handover
        # entirely but then the new ramp is measured on top of an old bonus and
        # neither number means anything on its own. The knob exists because
        # which of those is the better question is a measurement, not a taste.
        if not TUNING["boss_switch_keeps_bonus"]:
            if "enrage" not in now:
                self.enraged = 0
            if "momentum" not in now:
                self.momentum = 0
            if "pierce" not in now:
                self.fed = 0
        if "charge" in now:
            self.state[("them", "charge")] = TUNING["boss_charge_start"]
        if "momentum" in now:
            self.momentum = 0
        if "enrage" in now:
            self.enraged = 0
        if "pierce" in now:
            self.fed = 0
        # The printed attack slot was computed earlier in this `end_turn`, from
        # the OUTGOING rule's bonus. Leaving it there means the screen shows a
        # number the enemy will not act on for a whole turn -- and `enrage_bonus`
        # exists precisely so that the printed value and the damage are one
        # quantity: "a display that drifts from the damage would make the
        # feedback a lie and the rule uninducible". It is also the only thing
        # the player can see at the handover, so a stale slot does not merely
        # mislead, it deletes the evidence.
        self.state[("them", "atk")] = self.shown_atk
        # Once per handover, and unconditionally: whether the first half's
        # mechanic was ever triggered must not decide whether the cue appears,
        # or the cue's presence becomes a second channel that says "you made a
        # mistake earlier".
        if TUNING["boss_switch_hint"]:
            self.events.append((self.turn, BOSS_SHIFT))

    # -- outcome ---------------------------------------------------------
    # A trade is not a win. The benchmark asks whether the player REACHED the
    # end alive, so zero-for-zero is a loss -- and it stops being a corner case
    # the moment a committed wind-up can land on the turn the boss dies.
    def won(self) -> bool:
        return self.state[("them", "hp")] <= 0 and self.state[("me", "hp")] > 0
    def lost(self) -> bool: return self.state[("me", "hp")] <= 0
    def over(self) -> bool:
        return self.state[("them", "hp")] <= 0 or self.state[("me", "hp")] <= 0

    def committed(self) -> bool:
        """Is a wind-up already in release, so that killing it will not cancel it?

        Read at the top of `end_turn`, where the charge counter still holds the
        value the player saw when the turn began -- `charge` only advances after
        the attack resolves, so this can never lock a turn that gave no notice.
        """
        return (bool(TUNING["charge_commits"])
                and "charge" in self.parts
                and self.state[("them", "charge")] >= self.enemy.charge_max)

    def can_play(self, name: str) -> bool:
        return name in self.hand and self.state[("me", "energy")] >= self.deck[name].cost

    @property
    def enrage_bonus(self) -> int:
        """One definition, read by both the damage and the printed slot.

        The whole mechanic is that the number on screen moved BECAUSE of a card
        you played, so the two must be the same quantity -- a display that
        drifts from the damage would make the feedback a lie and the rule
        uninducible."""
        if self.enraged <= 0:
            return 0
        key = ("enrage_probe_ratio" if self.enraged == 1
               else "enrage_full_ratio")
        return priced(scaled(key, self.base_atk), self.enemy.punish)

    @property
    def momentum_bonus(self) -> int:
        """Same tiered shape as `enrage_bonus`, and read by the same two places
        -- the damage and the printed attack -- so the number on screen cannot
        drift from the number that lands."""
        if self.momentum <= 0:
            return 0
        key = ("momentum_probe_ratio" if self.momentum < MOMENTUM_FULL_AT
               else "momentum_full_ratio")
        return priced(scaled(key, self.base_atk), self.enemy.punish)

    @property
    def greed_bonus(self) -> int:
        """What the deck costs against a glutton.

        Counted off `deck_list`, which is the RUN's live deck rather than this
        fight's copy of it, so the heal that exhausts itself mid-fight cannot
        move the number a player is being asked to explain.

        Constant for the whole fight, unlike the other two addends, and that is
        the point: it is on the printed attack slot from turn one, before any
        card has been played, so the thing to be induced is visible at the
        moment the monster appears rather than assembled from its reactions."""
        if not TUNING["glutton_every"] and "glutton" not in self.parts:
            return 0
        mine = sum(1 for n in self.deck_list if self.deck[n].kind == "attack")
        extra = min(max(0, mine - TUNING["deck_attacks"]),
                    TUNING["glutton_cap"])
        return scaled("glutton_ratio", self.base_atk * extra) if extra else 0

    @property
    def shown_atk(self) -> int:
        """The enemy attack slot as the player reads it.

        Four places wrote this expression and the CONSTRUCTOR wrote a shorter
        one -- `enemy.atk` alone. That was correct only while every addend
        started at zero, which is true of a bonus accumulated during a fight
        and false of one set by the deck the player walked in with: a glutton
        printed its base attack on turn one and its real attack on turn two,
        so the one number the mechanic is inducible FROM was a lie exactly when
        it is first read. One definition, so the next addend cannot bring it
        back."""
        return (self.enemy.atk + self.enemy.rage * self.stalls
                + self.threat_bonus)

    @property
    def threat_bonus(self) -> int:
        """Everything that has been added to the enemy's attack by what the
        player did. ONE definition: `hit_now` takes a single `bonus`, and the
        printed attack slot is computed from the same value in four places.

        `greed_bonus` belongs here and not beside `enemy.atk`: it is not a
        property of the monster, it is a property of what the player brought.
        Two players meet the same glutton and read different numbers."""
        return self.enrage_bonus + self.momentum_bonus + self.greed_bonus

    def _mark(self, before):
        for k, v in self.state.items():
            if before[k] != v:
                self.seen.add(k)

    def _slots_moved(self, before):
        for p in ENEMY_STATE_SLOTS:
            if before.get(("them", p), 0) != self.state.get(("them", p), 0):
                self.slots_changed.add(p)

    def play(self, name: str) -> bool:
        c, s = self.deck[name], self.state
        if name not in self.hand:
            return "absent"
        if s[("me", "energy")] < c.cost:
            return False
        before = dict(s)
        s[("me", "energy")] -= c.cost
        c.cost_known = True
        self.pile.play(name)
        self.played_kinds[c.kind] = self.played_kinds.get(c.kind, 0) + 1
        self.fight_kinds[c.kind] = self.fight_kinds.get(c.kind, 0) + 1
        if "mark" in self.parts and self.marked_kind() == c.kind:
            # 出了被标记的那种牌：当场一记穿盾重击。探针价一局一次、不定价。
            mult = (priced(TUNING["mark_mult"], self.enemy.punish, over=1)
                    if (self.punished[5] >= 1 or self.no_probe) else TUNING["mark_probe_mult"])
            s[("me", "hp")] -= max(1, s[("them", "atk")]) * mult
            self.punished[5] += 1
            self.mark_hits += 1
            self.mark_hits_turn += 1
        if "mimic" in self.parts and c.kind == "buff_mark":
            # 模仿：你增伤，它也增伤 —— 槽位当场亮起，回合末那一击翻倍。
            s[("them", "mimic")] = 1
        if c.kind == "heal" and name in self.deck_list:
            # Exhausting has to reach the run's deck, not just this fight's
            # copy of it. Removing it only from the copy meant the card came
            # back for the next fight -- "two heals for the whole run", which
            # the entire health budget was calculated on, was in fact two per
            # fight.
            self.deck_list.remove(name)
        if c.kind == "heal":
            # 治疗是流血唯一的答案。清层数放在回血旁边而不是别处，是为了
            # 「出了这张牌，屏幕上两个数字一起动」—— 因果在同一格里。
            s[("me", "wound")] = 0
        if c.kind == "attack":
            dmg = (s[("me", "atk")] + c.amount) * (2 if s[("me", "double")] else 1)
            if TUNING["tempo"]:
                # 势：这一场第一张攻击牌 × (1 + 势)，然后清零。第二张攻击是基础伤害。
                dmg *= 1 + s[("me", "tempo")]
                s[("me", "tempo")] = 0
            if "ward" in self.parts and s[("them", "ward")] > 0:
                # 破势：封着时攻击落空。屏幕上 b1 不动 —— 这就是证据。
                dmg = 0
                self.ward_wasted += 1
                if TUNING.get("ward_seen_on_block"):
                    self.slots_changed.add("ward")      # 封印起过作用：此后画面印它（PROTO_WARDSEEN=acted）
            # One state value is both what the player observes and what damage
            # uses. Keeping a hidden calculation beside a displayed armour slot
            # would let the two drift after attack rewards.
            arm = s[("them", "armour")]
            if "armour" in self.parts and not self.broke:
                # The armour has now acted -- it either swallowed the hit
                # or broke on it. That is when it goes on screen; until
                # then its slot is withheld, because the slot's mere
                # PRESENCE was the whole answer. See `_row`.
                self.armour_seen = True
                self.seen.add(("them", "armour"))
                # Armour equals your attack, so a plain hit lands for nothing
                # and never gets through -- but one hit bigger than the armour
                # breaks it for the rest of the fight. That is what makes this
                # the enemy raw output cannot solve: not "slower", but zero,
                # until the one correct action happens once. Needing the double
                # ONCE rather than every swing is what fits the card budget --
                # three copies cannot feed a whole fight, but they can reliably
                # produce one opening.
                if dmg > arm:
                    self.broke = True
                    dmg -= arm
                    s[("them", "armour")] = 0
                else:
                    dmg = 0
            if "guard" in self.parts and s[("them", "guard")] >= 1 and dmg > 0:
                # 守相：伤害反弹，它不掉血。探针 1×（一局一次），之后 guard_mult。
                repeat = self.punished[4] >= 1 or self.no_probe
                mult = TUNING["guard_mult"] if repeat else TUNING["guard_probe_mult"]
                s[("me", "hp")] -= dmg * priced(mult, self.enemy.punish, over=1) \
                    if repeat else dmg * mult
                self.punished[4] += 1
                self.reflected += 1
                dmg = 0
            s[("them", "hp")] -= dmg
            self.dealt += dmg
            s[("me", "double")] = 0
            self._arm_switch()
        elif c.kind == "block":
            s[("me", "block")] += c.amount
        elif c.kind == "dodge":
            s[("me", "dodge")] = 1
        elif c.kind == "heal":
            s[("me", "hp")] = min(self.max_hp, s[("me", "hp")] + c.amount)
            # A heal does NOT cleanse. It used to, and that made the poisoner
            # worth one point: anyone heals when low, so anyone cleansed by
            # accident, and the knowledge bought nothing. Nothing removes the
            # stacks now -- the answer to the poisoner is not a card at all.
        elif c.kind == "buff_mark":
            s[("me", "double")] = 1
        elif c.kind == "block_carry":
            if s[("me", "block")] > 0:
                s[("me", "carry")] = 1
        offensive = c.kind in ("attack", "buff_mark")
        if offensive:
            self.offences += 1
            s[("me", "offence")] = self.offences      # 公开：这回合进攻了几次
        if TUNING["enrage_on_second_offence"]:
            # The first offensive action of a turn is free, every turn. Only
            # doubling down inside one turn feeds it, so defending, healing and
            # dodging cost nothing and the basic operations stay cheap.
            fed_it = "enrage" in self.parts and offensive and self.offences >= 2
        else:
            # Every non-attack card, and only a card that actually resolved --
            # a refused play costs energy nowhere else either. Ending the turn
            # is not a card and does not feed it, which is what leaves "swing,
            # or stop" as a line the player can actually take.
            fed_it = c.kind != "attack" and "enrage" in self.parts
        if fed_it:
            self.enraged = min(self.enraged + 1, TUNING["enrage_cap"])
            s[("them", "atk")] = self.shown_atk
        self._slots_moved(before)
        if self.track_seen:
            self._mark(before)
        return True

    # What the opening guarantee is allowed to take out of a full hand, in
    # order. A SURPLUS attack first -- two energy buys at most two cards, so the
    # third attack in a hand is the cheapest thing in it -- then a surplus
    # shield, then the doubler, then a spare heal, then the shield, then the
    # heal. The last attack is never taken: a hand that cannot damage anything
    # does not end the fight, and this rule is supposed to hand over a tool
    # rather than confiscate one.
    #
    # Ordered by KIND rather than by hand position on purpose. Position is
    # meaningless to the vector engine, which stores counts, so a rule that
    # displaced "the first matching slot" could not be reproduced there and the
    # two engines would deal different hands while every clear-rate differential
    # reported agreement.
    DISPLACE = (("attack", True), ("block", True), ("buff_mark", False),
                ("heal", True), ("block", False), ("heal", False))

    def _guarantee_dodge(self) -> int:
        """Open this boss stage holding a dodge. Returns 0 or 1.

        Every boss stage, charger or not: a card that only ever turned up
        against chargers would tell the player what it was fighting, which is
        the one thing the screen is not allowed to say.
        """
        p = self.pile
        if any(self.deck[n].kind == "dodge" for n in p.hand):
            return 0
        card = src = None
        for pool in (p.discard, p.draw):
            hits = [i for i, n in enumerate(pool)
                    if self.deck[n].kind == "dodge"]
            if hits:
                src = pool
                card = pool.pop(hits[p.rng.randrange(len(hits))])
                break
        if card is None:
            return 0
        if len(p.hand) < p.hand_size:
            p.hand.append(card)
            return 1
        counts = {}
        for n in p.hand:
            counts[self.deck[n].kind] = counts.get(self.deck[n].kind, 0) + 1
        for kind, surplus in self.DISPLACE:
            if counts.get(kind, 0) < (2 if surplus else 1):
                continue
            i = next(i for i, n in enumerate(p.hand)
                     if self.deck[n].kind == kind)
            p._return(p.draw, p.hand[i])
            p.hand[i] = card
            return 1
        p._return(src, card)      # nothing may be given up; put it back
        return 0

    def _offer_dodge(self) -> int:
        """Move one dodge the deck already owns into the hand. Returns 0 or 1.

        Discard first, then the draw pile, and UNIFORMLY among the matches in
        whichever pool answers. `next()` would take the earliest index, and the
        draw pile is consumed from the end, so first-match means the copy buried
        deepest -- which pushes the remaining copies toward the top and leaves
        the pile no longer a uniform permutation given its counts. That is the
        assumption `batch.py`'s counts representation rests on, and it has cost
        this codebase a measurable engine divergence once already.

        Does nothing when a dodge is already in hand, or when there is no room:
        a full hand is the player's own doing, and confiscating a card to make
        space would be a second intervention hiding inside this one.
        """
        p = self.pile
        if any(self.deck[n].kind == "dodge" for n in p.hand):
            return 0
        if len(p.hand) >= p.hand_size:
            return 0
        for pool in (p.discard, p.draw):
            hits = [i for i, n in enumerate(pool)
                    if self.deck[n].kind == "dodge"]
            if hits:
                p.hand.append(pool.pop(hits[p.rng.randrange(len(hits))]))
                return 1
        return 0

    def _incoming(self) -> tuple[int, bool, bool]:
        """This turn's enemy damage, before anything is spent on it.

        One definition, called by the ordinary turn and by the committed
        release alike. It used to be inline, which was fine while there was
        only one caller and would have drifted the moment there were two --
        the same failure `settle_attack` and `lethal_now` were written to stop.
        Returns (damage, ignores_block, shield_eaten); it mutates nothing, so
        the caller decides whether the piercer's grudge is fed.
        """
        s = self.state
        hit, ignores_block = self.enemy.hit_now(
            self.stalls, s[("them", "charge")], s[("me", "block")],
            fed=self.fed, bonus=self.threat_bonus, parts=self.parts,
            offences=self.offences,
            # 探针按**局**算一次，不按场：`punished[1]` 是本局已落下的反击数。按场
            # 算的话，每一只新的反击怪都送一次便宜的探针，猛攻族每场都白挨一记
            # —— 实测最强盲线从 13% 反弹到 38%。
            countered=self.countered + self.punished[1],
            no_probe=self.no_probe,
            mimic=s[("them", "mimic")] >= 1, mimic_seen=self.punished[6])
        # The first shield is the observable probe; a later shield is a repeated
        # error and gets the full punishment. One probe alone does not raise
        # later unshielded damage. Ignoring the evidence a second time activates
        # a persistent grudge, so the consequence is sustained danger rather
        # than an arbitrary universal one-shot.
        #
        # The flag lives on the Fight, not the Enemy. Enemies are reused across
        # `fight_at` calls, so setting it on the enemy would have carried the
        # grudge into every later fight against the same object -- the exact
        # class of leak this codebase keeps producing.
        shield_eaten = ("pierce" in self.parts
                        and s[("me", "block")] > 0)
        if (self.is_boss and TUNING["momentum_boss_frac"]
                and "momentum" in self.parts
                and self.momentum >= TUNING["momentum_cap"]
                and not self._in_grace()):
            hit = max(hit, self.max_hp * TUNING["momentum_boss_frac"] // 100)
        if (self.is_boss and TUNING["enrage_boss_frac"]
                and "enrage" in self.parts
                and self.enraged >= TUNING["enrage_cap"]
                and not self._in_grace()):
            # Read off the CEILING, like the charged hit, so a bigger health
            # pool cannot buy its way out of the mechanic.
            hit = max(hit, self.max_hp * TUNING["enrage_boss_frac"] // 100)
        if (self.is_boss and TUNING["big_frac"] and "charge" in self.parts
                and s[("them", "charge")] >= self.enemy.charge_max):
            # The big hit is a fraction of your MAXIMUM health, not a multiple
            # of the enemy's attack. A multiple can be out-scaled by a bigger
            # health pool, and the screen will happily hand you one; a fraction
            # cannot. Two of these end a run, so the wind-up has to be answered
            # rather than absorbed.
            hit = max(hit, self.max_hp * TUNING["big_frac"] // 100)
        if not self.is_boss and TUNING["punish_frac"]:
            k = self._punished_by()
            # 只罚重复：本局这种机制已经罚过 >= 1 次。第一次是探测。
            if k is not None and self.punished[k] >= 1:
                frac = min(priced(TUNING["punish_frac"], self.enemy.punish),
                           TUNING["punish_frac_cap"])
                hit = max(hit, self.max_hp * frac // 100)
        return hit, ignores_block, shield_eaten

    PUNISHERS = ("charge", "counter", "pierce", "momentum", "guard", "mark", "mimic", "ward")
    MARK_ORDER = ("attack", "block", "dodge", "heal", "buff_mark")

    def marked_kind(self):
        """这回合被标记的牌种（kind 名），没有就 None。只读公开槽位。"""
        code = self.state.get(("them", "mark"), 0)
        return self.mark_perm[code - 1] if code else None

    def _punished_by(self):
        """这一回合是哪种机制在罚（索引进 PUNISHERS），没有就 None。只读状态。"""
        s = self.state
        if ("charge" in self.parts
                and s[("them", "charge")] >= self.enemy.charge_max):
            return 0
        if "counter" in self.parts and self.offences >= 2:
            return 1
        if "pierce" in self.parts and s[("me", "block")] > 0 and self.fed >= 1:
            return 2
        if "momentum" in self.parts and self.momentum >= MOMENTUM_FULL_AT:
            return 3
        if "mimic" in self.parts and s[("them", "mimic")] >= 1:
            return 6
        if ("ward" in self.parts and s[("them", "ward")] > 0
                and self.played_kinds.get("attack", 0) >= 1):
            return 7
        return None

    def release_committed(self) -> None:
        """The locked wind-up lands on a corpse's turn.

        ONLY the swing. No poison tick, no rage, no counter advance, no fresh
        hand: the enemy is dead and the fight is over the instant this returns.
        What survives death is the attack that was already being released, and
        nothing else -- anything more would be a second mechanic smuggled in on
        the back of the timing fix.
        """
        s = self.state
        hit, ignores_block, _ = self._incoming()
        s[("me", "hp")], s[("me", "block")], _ = settle_attack(
            s[("me", "hp")], s[("me", "block")], bool(s[("me", "dodge")]),
            hit, ignores_block, lethal_now(self.is_boss))

    def end_turn(self) -> None:
        s = self.state
        if s[("them", "hp")] <= 0:
            # Killing the enemy cancels its turn -- unless the wind-up was
            # already at the top when this turn began, in which case the swing
            # is in flight and only a dodge stops it.
            if self.committed():
                self.release_committed()
            return
        before = dict(s)
        fed_before = self.fed
        hit, ignores_block, shield_eaten = self._incoming()
        # 先记账再加 `fed`：`_punished_by` 对穿透读的是「之前已经吃过盾」，把
        # 增量放在它前面会让第一次探针被记成一次被罚 —— 第二次举盾就直接踩地板。
        k = self._punished_by()
        if k is not None:
            self.punished[k] += 1
        if shield_eaten:
            self.fed += 1
        if "counter" in self.parts and self.offences >= 2:
            self.countered += 1
        if "mimic" in self.parts and s[("them", "mimic")] >= 1:
            self.mimic_hits += 1

        # Poison eats the CEILING, not the current health. Nothing heals it
        # back -- not a heal card, not a rest that restores health -- so the
        # cost is carried for the rest of the run, and a bigger health pool does
        # not buy you out of it. Stacks only ever rise and nothing but a heal
        # clears them, so the damage is superlinear in how long you ignore it.
        #
        # This is also what finally separates the two reasons to spend a heal.
        # While poison only dealt damage, a player who healed whenever low
        # cleansed by accident and the mechanic was worth one point; now healing
        # when low does not undo a single point of the ceiling already lost.
        if s[("me", "poison")] > 0:
            # Poison does two things, and it needs both. The ceiling loss is the
            # part that cannot be undone -- no heal, no rest that restores
            # health, only a rest spent on the ceiling -- and it is what makes
            # the poisoner a long-range cost rather than a fight-local one.
            #
            # But a ceiling has no slot on screen, so on its own the whole
            # mechanic was invisible: three lives in a row the stack counter was
            # watched climbing to 8 and written up as "I could not see what this
            # value does". A cost you cannot observe is not learnable, whatever
            # it does to you. So it also bites now -- straight through block,
            # the same size as the stack -- which puts the damage on screen next
            # to the counter that caused it.
            tick = s[("me", "poison")]
            s[("me", "hp")] -= tick
            self.max_hp = max(self.hp_floor,
                              self.max_hp - tick * priced(
                                  TUNING["poison_cap"], self.enemy.punish) // 100)
            s[("me", "cap")] = self.max_hp
            s[("me", "hp")] = min(s[("me", "hp")], self.max_hp)
        if "poison" in self.parts:
            s[("me", "poison")] += scaled("poison_ratio", self.base_atk)
        # 流血：先按层数扣血（穿盾，和 poison 的 tick 一样），再看这只怪要不要加层。
        # 不碰上限 —— 那是 poison 的事，两条机制的后果必须在屏幕上分得开。
        if s[("me", "wound")] > 0:
            s[("me", "hp")] -= s[("me", "wound")]
        if "wound" in self.parts:
            s[("me", "wound")] += scaled("wound_ratio", self.base_atk)

        big_now = ("charge" in self.parts
                   and s[("them", "charge")] >= self.enemy.charge_max)
        lethal = big_now and lethal_now(self.is_boss)
        # `fed_before`, not `self.fed`: the counter was just incremented for
        # THIS shield, and the rule is about a shield held after the piercer had
        # already eaten one. Reading it afterwards would make the very first
        # shield lethal and delete the identification probe the boss still owes
        # the player.
        if (self.is_boss and TUNING["pierce_boss_lethal"] and shield_eaten
                and fed_before >= 1):
            lethal = True
        held = s[("me", "block")]
        dodged = bool(s[("me", "dodge")])
        pre_attack_hp = s[("me", "hp")]
        if (TUNING["momentum_resets_before_hit"] and TUNING["momentum_resets"]
                and "momentum" in self.parts and held > 0):
            # 举盾在结算前压掉斜坡：正确答案挡得住这一击本身，而不只是下一击。
            self.momentum = 0
        s[("me", "hp")], s[("me", "block")], absorbed = settle_attack(
            pre_attack_hp, held, dodged, hit, ignores_block, lethal)
        if "ward" in self.parts:
            # 破势：出了攻击牌 → 封印加固；没出攻击且盾挡住了这一击 → 封印减一；开着的窗口倒数。
            blocked_hit = held > 0 and hit > 0 and not dodged and not ignores_block
            if s[("them", "ward")] > 0:
                if self.played_kinds.get("attack", 0):
                    s[("them", "ward")] = min(self.enemy.ward_cap or TUNING["ward_seal_cap"],
                                               s[("them", "ward")] + 1)
                elif blocked_hit and (not TUNING.get("ward_block_only")
                                      or {k for k, v in self.played_kinds.items() if v} == {"block"}):
                    s[("them", "ward")] -= 1
                    if s[("them", "ward")] == 0:
                        self.ward_open_left = TUNING["ward_window"]
                        self.ward_opened += 1
            else:
                self.ward_open_left -= 1
                if self.ward_open_left <= 0:
                    s[("them", "ward")] = self.enemy.ward_start or 1
        # --- audit: identifiability, and the conditions of this turn --------
        # The paired counterfactual: the SAME pre-turn state settled twice, once
        # with the shield and once without, through the same function the real
        # turn just used. Only health can differ, and it is the only part of the
        # outcome the player can read, so equality here means the turn taught
        # nothing about the shield however the player experimented.
        hp_held = settle_attack(pre_attack_hp, held, dodged,
                                hit, ignores_block, lethal)[0]
        hp_bare = settle_attack(pre_attack_hp, 0, dodged,
                                hit, ignores_block, lethal)[0]
        if held > 0 and absorbed > 0 and hp_held == hp_bare:
            self.blind_turns += 1
        self.turn_marks.append((
            id(self.enemy), self.enemy.atk, self.stalls,
            before[("them", "charge")], before[("me", "poison")],
            dodged, self.fed - (1 if shield_eaten else 0),
            held > 0, held > 0 and hit and absorbed >= hit))
        if held > 0:
            self.blocked_turns += 1
            self.absorbed_total += absorbed
            if hit and absorbed >= hit:
                self.fully_absorbed_turns += 1
        else:
            self.unblocked_turns += 1

        if "momentum" in self.parts:
            # Read `held`, the shield as it stood when the attack was settled --
            # not the slot afterwards, which upkeep has already cleared. A block
            # RESETS the ramp; a dodge does not, because the dodge answered this
            # turn's damage and the ramp is about the turns you spent not
            # defending. That asymmetry is the whole mechanic: it is what makes
            # "hold the dodge for the wind-up" and "hold a shield against this
            # one" two different skills rather than one.
            quiet = held > 0 and not (TUNING["momentum_quiet_reset"]
                                      and self.played_kinds.get("attack", 0))
            self.momentum = (
                max(0, self.momentum - 1) if quiet and not TUNING["momentum_resets"]
                else 0 if quiet
                else min(self.momentum + 1, TUNING["momentum_cap"]))

        if "regen" in self.parts and s[("them", "hp")] > 0:
            # It claws health back every turn, so grinding it down while also
            # blocking simply does not work. This is the one monster where
            # stacking block is plainly wrong rather than merely suboptimal --
            # and its correct answer (all-out attack) is the opposite of what
            # a steady enemy wants, so the two cannot be played the same way.
            s[("them", "hp")] += self.enemy.regen

        if "charge" in self.parts:
            big = s[("them", "charge")] >= self.enemy.charge_max
            # 闪掉的那一次不算「放出去了」—— 槽位留在满格，下一回合还要闪。
            kept = (big and TUNING["charge_keeps_on_dodge"]
                    and bool(s[("me", "dodge")]))
            s[("them", "charge")] = (s[("them", "charge")] if kept
                                     else 0 if big
                                     else s[("them", "charge")] + 1)
            if (TUNING["charge_returns_dodge"] and not big
                    and s[("them", "charge")] >= self.enemy.charge_max):
                # The counter has just reached the top, so the NEXT turn is the
                # one that answers it. Offering the card here rather than after
                # the swing is the whole point: it arrives in time to be played.
                self.dodge_offered += self._offer_dodge()

        if "guard" in self.parts:
            # 相位每回合翻；第一回合开相，第二回合起交替。翻动本身让槽位显形。
            s[("them", "guard")] = 1 - s[("them", "guard")]
        if "mimic" in self.parts:
            # 镜像那一击已经结算（或被闪掉），槽位归 0；再出增伤才再亮。
            s[("them", "mimic")] = 0
        if "mark" in self.parts:
            # 按这一场你各种牌的**累计**出牌数加权随机抽一种。
            #   均匀随机   猛攻只有 20% 的回合被标 —— 实测最强盲线从 0.5% 反弹到 9.2%
            #   标上回合最多的  被「每回合换一种」这条节奏习惯不读槽位就避开
            # 加权随机：全靡攻击的线几乎每回合被标攻击；交替的线各一半；只有读槽位
            # 才避得开。没出过牌时均匀。代号走本局的映射。
            order = self.MARK_ORDER
            weights = [self.fight_kinds.get(k, 0) for k in order]
            kind = (self.rng.choices(order, weights=weights)[0] if sum(weights)
                    else self.rng.choice(order))
            s[("them", "mark")] = self.mark_perm.index(kind) + 1
        if TUNING["tempo"] and not self.played_kinds.get("attack", 0):
            # 没出攻击牌的回合 +1（含闪避、增伤、纯防守的回合）；打在守相上出了牌，不算。
            s[("me", "tempo")] = min(TUNING["tempo_cap"], s[("me", "tempo")] + 1)
        self.last_kinds = dict(self.played_kinds)
        self.played_kinds = {}
        self.mark_hits_turn = 0
        # rage has to be visible, or the damage just seems to drift upward for
        # no reason -- same rule as everywhere else: what took effect is shown,
        # what it means is not
        # A dodge turn deals no damage by construction -- the card costs the
        # whole turn's energy -- so counting it as a stall charged the correct
        # answer twice and left the brute-force line untouched. Measured: rage
        # costs informed play 17 points of clear rate and pure attack 3.
        # gpt-5.5 read this correctly and wrote "relying on it made her hit
        # harder later"; it was not misreading the environment, the environment
        # was taxing the right move.
        if self.dealt == 0 and not (TUNING["dodge_exempt_rage"]
                                    and s[("me", "dodge")]):
            self.stalls += 1
        self.dealt = 0
        # Per TURN, so the first offensive action is free again next turn.
        self.last_offences = self.offences
        self.offences = 0
        s[("me", "offence")] = 0
        s[("them", "atk")] = self.shown_atk

        if s[("me", "carry")]:
            s[("me", "carry")] = 0
        else:
            s[("me", "block")] = 0
        # Dodge either expires like every other transient, or waits until it
        # actually absorbs something. Persisting is the alternative to letting
        # the hand carry over: the wind-up is visible two turns ahead, and the
        # point is that seeing it should let you ACT, one way or the other.
        if not TUNING["dodge_persists"] or (hit and not before[("me", "dodge")]):
            s[("me", "dodge")] = 0
        s[("me", "energy")] = self.max_energy
        if shield_eaten and TUNING["pierce_returns_block"]:
            # The card that produced the diagnostic event is offered again on
            # the very next decision. This makes correction observable and
            # testable without marking a fresh piercer in advance. It is moved,
            # never copied, so deck size and exhaustion accounting stay true.
            i = next((i for i, name in enumerate(self.pile.discard)
                      if self.deck[name].kind == "block"), None)
            if i is not None and len(self.pile.hand) < self.pile.hand_size:
                self.pile.hand.append(self.pile.discard.pop(i))
        self.pile.end_turn()
        # After this turn is fully settled and before the next one opens. The
        # player's first action under the new rule therefore comes BEFORE
        # anything the new rule can do to them.
        self._settle_phase()
        self._slots_moved(before)
        if self.track_seen:
            self._mark(before)
        self.turn += 1


# 怪身上会动的状态槽（蓄力计数、守相、标记代号、模仿、封印）。`state_slots` 决定它们怎么上画面。
ENEMY_STATE_SLOTS = ("charge", "guard", "mark", "mimic", "ward")


def _row(fight, side, tier) -> str:
    """Only what is present -- same rule as the camp: an absent status prints
    nothing, so 'not there' and 'there but zero' stay different facts."""
    props = {("me", "standing"): ("hp", "cap", "atk", "energy"),
             ("me", "transient"): ("block", "poison", "double", "dodge", "carry"),
             ("them", "standing"): ("hp", "atk", "armour"),
             ("them", "transient"): ENEMY_STATE_SLOTS}[(side, tier)]
    mode = TUNING.get("state_slots", "hidden")
    shown = set()                       # 状态槽：这一格按模式印，含 0，印真值
    if (side, tier) == ("them", "transient") and mode != "hidden":
        parts = getattr(fight, "parts", ())
        shown = ({p for p in props if p in parts} if mode == "carrier"
                 else {p for p in props if p in BEHAVIOURS} if mode == "all"
                 else set(getattr(fight, "slots_changed", ())) & set(props))
    out = []
    hidden = TUNING.get("hidden_props", ())
    for p in sorted(props, key=lambda q: fight.layout.L(side, q)):
        if (side, p) in hidden:
            continue
        v = fight.state.get((side, p), 0)
        if p in shown:
            out.append(f"{fight.layout.L(side, p)}:{v}")
            continue
        if not v or ((side, tier) == ("them", "transient") and p != "charge"):
            continue
        # A slot EVERY enemy carries discloses nothing by being on screen.
        # The armour slot is carried by one kind of enemy only, so its
        # presence -- before a single value has been disclosed -- answered
        # the question the mechanic exists to ask. Measured on c19/9323:
        # an armoured enemy printed three standing numbers from turn 0 and
        # every other enemy printed two, so `b2` present meant `play the
        # doubler` and nothing had to be understood. It is withheld until
        # the armour has done something, which is the rule the piercer
        # already lives by: discovery costs one interaction. `getattr`
        # because the camp screen shares this renderer and has no fight.
        if p == "armour" and not getattr(fight, "armour_seen", True):
            continue
        lab, sep = fight.layout.L(side, p), ("=" if tier == "standing" else ":")
        if p not in NUMERIC_PROPS:
            out.append(lab)
        else:
            out.append(f"{lab}{sep}{v if (side, p) in fight.seen else '?'}")
    return "  ".join(out)


def snapshot(fight) -> str:
    """One-line full state, for the analysis log. The model never sees this --
    it gets the same screen a human does. This exists because reading a
    transcript of nothing but diffs means reconstructing the enemy's state in
    your head, and that is where analysis goes wrong."""
    def row(side):
        out = []
        for tier in ("standing", "transient"):
            props = {("me", "standing"): ("hp", "cap", "atk", "energy"),
                     ("me", "transient"): ("block", "poison", "double", "dodge", "carry"),
                     ("them", "standing"): ("hp", "atk", "armour"),
                     ("them", "transient"): ("charge",)}[(side, tier)]
            for p in sorted(props, key=lambda q: fight.layout.L(side, q)):
                v = fight.state[(side, p)]
                if not v:
                    continue
                lab = fight.layout.L(side, p)
                out.append(f"{lab}={v}" if p in NUMERIC_PROPS else lab)
        return " ".join(out)
    return f"[我 {row('me')} | 敌 {row('them')}]"


def show(fight) -> str:
    """The fight screen, as models and people read it. English since 2026-10-19 (the user: every word a participant
    reads is English); before that the labels were 回合 / 我 / 对方 and the GUI translated them for display into
    exactly these words (core/gui/english.json): Turn / You / Them, an 8-column label."""
    lines = [f"Turn {fight.turn}"]
    for side, label in (("me", "You"), ("them", "Them")):
        lines.append(f"{label}:".ljust(8) + _row(fight, side, "standing"))
        tr = _row(fight, side, "transient")
        if tr:
            lines.append(" " * 8 + tr)
    return chr(10).join(lines)


# ---------------------------------------------------------------- the run

@dataclass
class Node:
    """One thing you can walk into. The KIND is on the signpost; the behaviour
    is not, and that is the whole point -- you are choosing blind between
    monsters, so you cannot dodge the one you never worked out."""
    kind: str                    # "fight" / "elite" / "rest"
    behaviour: str = ""          # hidden from the player
    enemy: "Enemy | None" = None
    # Three things that used to be one. `kind` is the signpost, `role` is what
    # the encounter is FOR, and `reward` is whether clearing it pays. Tying all
    # three to "elite" meant a curriculum could not be built without also
    # changing how much loot the run hands out -- and then any effect measured
    # would be structure and economy together, which is the confound this whole
    # session keeps paying for.
    role: str = ""               # "teach" / "mid" / "test" / ""
    reward: bool = False


@dataclass
class Layer:
    nodes: list["Node"]

    def kinds(self) -> list[str]:
        return [n.kind for n in self.nodes]

    def has(self, kind: str) -> bool:
        return any(n.kind == kind for n in self.nodes)

    @property
    def behaviour(self) -> str:
        """Kept for reporting only. A layer no longer HAS one behaviour."""
        return "/".join(sorted({n.behaviour for n in self.nodes if n.behaviour}))


def _milestones(n: int, k: int) -> list[int]:
    """Evenly spaced positions, so the pay does not depend on what is there.

    A milestone is a point in the run, not a monster. Tying the reward to a
    monster is what made "make the second encounter elite" also mean "hand out
    one more upgrade per mechanic".
    """
    if k <= 0 or n <= 0:
        return []
    step = n / (k + 1)
    return sorted({min(n - 1, int(round(step * (j + 1)))) for j in range(k)})


@dataclass(frozen=True)
class EncounterSpec:
    """One scheduled meeting with one mechanic, and what it is for.

    A token with an identity, not an index into a shuffled list. The ordering
    constraint -- teach before test -- is then a property of the DATA and the
    sort that respects it, rather than something checked after the fact on a
    shuffle that happened to come out right. Those two are the same until the
    day the check is forgotten or the shuffle is reused somewhere else.
    """
    mechanic: str
    role: str                    # "teach" | "mid" | "test"


def curriculum_order(rng: random.Random, behaviours=None, gap_for=("poison",),
                     gap=None) -> list:
    """A random order that respects `teach(m)` before `test(m)`.

    Built by repeatedly choosing uniformly among the specs whose predecessors
    are already placed -- a randomised topological sort, so every legal order is
    reachable and no illegal one is.

    `gap_for` names mechanics whose test may not follow their teach too closely.
    Poison is the one that needs it: its evidence appears in a fight and its
    ANSWER is which way the next rest is spent, so a test placed before any rest
    has occurred asks a question the player has had no opportunity to answer.
    The gap is expressed in encounters and set to the rest cadence, which is
    what guarantees a rest falls between them.
    """
    names = list(behaviours if behaviours is not None else BEHAVIOURS)
    gap = TUNING["rest_every"] if gap is None else gap
    todo = [EncounterSpec(m, r) for m in names for r in ("teach", "test")]
    placed, out = {}, []
    while todo:
        # A DEADLINE, not a ban. Forbidding a gap-constrained teach once it got
        # late deadlocked the sort: its test could not go first and it could not
        # go at all. What the constraint actually needs is for that teach to be
        # placed no later than the last position from which its test still has
        # room -- so at that point it becomes the only legal choice.
        due = [x for x in todo if x.role == "teach" and x.mechanic in gap_for
               and len(todo) - 1 <= gap]
        if due:
            ready = due
        else:
            ready = []
            for spec in todo:
                if spec.role == "teach":
                    ready.append(spec)
                    continue
                at = placed.get((spec.mechanic, "teach"))
                if at is None:
                    continue
                if spec.mechanic in gap_for and len(out) - at < gap:
                    continue
                ready.append(spec)
        if not ready:
            ready = [x for x in todo if x.role == "test"
                     and (x.mechanic, "teach") in placed]
        pick = rng.choice(ready)
        placed[(pick.mechanic, pick.role)] = len(out)
        out.append(pick)
        todo.remove(pick)
    return out


def make_layers(rng: random.Random, per_behaviour: int = 0,
                mid_rng: random.Random | None = None,
                behaviours=None) -> list[Layer]:
    """Each behaviour appears `per_behaviour` times, in random order.

    Twice, not once: a rising counter means nothing until you have been hit by
    what it was building towards, so the first encounter buys the observation
    and only the second can be played on purpose."""
    # Every behaviour at least `min_per_behaviour` times, then filled to a fixed
    # number of layers.
    #
    # The minimum is not cosmetic. The screen has to satisfy "informed clears,
    # every partial fails", and when the mix was free it found a much cheaper
    # way to satisfy that than making each mechanic matter: leave one out. With
    # the charger optional it duly dropped to 29 appearances in 144 layers and
    # almost never reached the boss, so "did you work out the wind-up" was worth
    # 72% -- not because the wind-up was survivable, but because it was rarely
    # asked. A test you can avoid setting is not a test, so coverage is a
    # structural guarantee rather than something the search is allowed to trade.
    # One layer per behaviour, and every fightable node in that layer IS that
    # behaviour. Blind choice then costs nothing in coverage: whatever you walk
    # into on the armour layer is the armoured one. What you are choosing is
    # ordinary or elite -- risk against growth -- which is a real decision and
    # not a guess about which monster is behind which door.
    #
    # Two earlier shapes both failed, in opposite ways. One behaviour per layer
    # with each appearing twice covered everything but cost eight fights, and
    # 0.96^8 caps an informed player at 72% however fair each fight is. Mixing
    # behaviours freely across nodes cut the fights but made coverage a lottery:
    # blind choice meant a mechanic could simply never come up, and the screen
    # -- which is rewarded for keeping partial players out -- happily leaned on
    # that. Guaranteeing the encounter and letting the CHOICE be about something
    # else is what satisfies both.
    #
    # Rest layers sit on a fixed cadence rather than appearing at random, so the
    # health budget is a known quantity and the run stops being a lottery about
    # whether a way out shows up when you need one.
    # Twice each, not once: the first encounter buys the observation and only
    # the second can be played on purpose. A single guaranteed encounter tests
    # whether you already knew, not whether you can learn -- and learning is the
    # thing being measured.
    if TUNING["curriculum"] in (1, 2, 4):
        # A course, not a bag of encounters. Each mechanic is met twice and the
        # two meetings have different jobs: the first is where it can be
        # observed, the second is where acting on the observation is worth
        # something. The order is a randomised topological sort over tokens
        # that carry that identity, so "teach before test" holds by
        # construction rather than by a check on a shuffle.
        #
        # The test is the whole layer, which is what makes it unavoidable. A
        # test a player can decline is not a test -- and declining was exactly
        # what the route family's `elite_at` was for.
        order = curriculum_order(rng, behaviours=behaviours)
        if TUNING["midterm"]:
            # After the LAST teach, so every mechanic has been seen once before
            # any of them is examined -- which on a two-round world is exactly
            # the boundary between the halves. The mechanic is drawn from the
            # world's own rng, so it is a property of the map and different maps
            # examine different things.
            #
            # The whole block is inside the flag: with `midterm` off not one
            # draw is taken, so every previously confirmed world is bit-identical.
            last_teach = max(i for i, x in enumerate(order) if x.role == "teach")
            # Its own NAMESPACED stream, like `identity-v1:{salt}:layout`, and
            # for the reason that comment gives: a draw taken from the shared
            # stream reshuffles everything after it, so the eleven-fight world
            # would not be the ten-fight world plus one encounter -- it would be
            # a different world from fight six on. Measured before this existed,
            # the same map went 74% -> 0% and another 42% -> 42%, which is the
            # signature of re-rolled monsters and not of an extra fight.
            mr = mid_rng or rng
            # The draw happens whether or not it is used. `TUNING[...] or
            # rng.choice(...)` short-circuits, so forcing a mechanic would have
            # skipped a draw and handed every forced arm a DIFFERENT world --
            # measured, it moved an already-placed teach monster from 21 health
            # to 28, four fights before the midterm.
            drawn = mr.choice(sorted({x.mechanic for x in order}))
            order = (order[:last_teach + 1]
                     + [EncounterSpec(TUNING["mid_mechanic"] or drawn, "mid")]
                     + order[last_teach + 1:])
        layers, since_rest = [], 0
        for spec in order:
            n = (mr if spec.role == "mid" else rng).choice([2, 2, 3])
            # `curriculum=1` is order only; `2` also makes the test elite
            # STRENGTH. Split because the full version quietly took the number
            # of elite-strength fights from 2 to one per mechanic -- on four
            # mechanics that is a 4-6x jump in how hard the map hits, and any
            # effect measured would be the ordering and that together.
            kind = ("elite" if (spec.role == "test"
                                and TUNING["curriculum"] == 2) else "fight")
            layers.append(Layer([Node(kind, spec.mechanic, role=spec.role)
                                 for _ in range(n)]))
            since_rest += (spec.role != "mid" or TUNING["mid_counts_to_rest"])
            if since_rest >= TUNING["rest_every"]:
                layers.append(Layer([Node("rest")]))
                since_rest = 0
        if since_rest:
            layers.append(Layer([Node("rest")]))
        # Reward eligibility is assigned SEPARATELY and its count does not move
        # with the number of mechanics. Tying loot to elite strength meant four
        # mechanics handed out four rewards where three handed out two, so any
        # measured effect of the curriculum would have been the curriculum and
        # a 50% larger economy together.
        # Reward eligibility is separated from the NUMBER of elite fights, not
        # from the idea of earning it. Sampling the paid nodes freely put the
        # loot on ordinary fights while the control required beating an elite
        # for it -- measured, that alone moved the informed rate +11.6 and the
        # ignorant rate +34.6, and it would have been read as an effect of the
        # ordering. So the pay still sits on the harder encounter: `n_elites`
        # of the TESTS, which is the curriculum's own version of "beat the
        # bigger thing to get paid", and the count does not grow with the
        # number of mechanics.
        if TUNING["curriculum"] == 4:
            # The journey teaches; the boss examines. Nothing on the way is an
            # elite, and the reward is a MILESTONE -- a fixed position in the
            # run rather than a prize for clearing a particular monster. That
            # unties it from both the elite promotion and the number of
            # mechanics, which is what kept turning a curriculum change into an
            # economy change.
            # The midterm is deliberately NOT in the pool. It pays nothing,
            # and it must not DISPLACE a payment either: with it counted, the
            # milestones land on different fights and an eleven-fight run would
            # be compared against a ten-fight run with a different economy.
            fights = [l.nodes for l in layers
                      if l.nodes[0].kind != "rest" and l.nodes[0].role != "mid"]
            for at in _milestones(len(fights), TUNING["n_elites"]):
                for x in fights[at]:
                    x.reward = bool(TUNING["elite_reward"])
            return layers
        tests = [x for l in layers for x in l.nodes if x.role == "test"]
        paid = rng.sample(tests, min(TUNING["n_elites"], len(tests)))
        for x in paid:
            # Under the curriculum the elite is not a choice any more: every
            # mechanic's second encounter is one and none of them can be
            # declined, so `elite_at` -- the route dimension that asked "is
            # this worth the risk" -- has nothing left to decide. A reward
            # attached to a fight nobody may refuse is not payment for risk,
            # it is a handout on a fixed schedule, and calling it the former
            # would keep a decision in the policy family that the map has
            # already taken away.
            x.reward = bool(TUNING["elite_reward"])
            if TUNING["curriculum"] == 1:
                # The order arm carries the CONTROL's strength budget: the same
                # two nodes are elite and paid, exactly as in the control, so
                # the only thing that differs is which encounters they are.
                x.kind = "elite"
        return layers
    order = [b for b in (behaviours if behaviours is not None else BEHAVIOURS)
             for _ in range(TUNING["repeats"])]
    rng.shuffle(order)
    layers, since_rest = [], 0
    for b in order:
        n = rng.choice([2, 2, 3])
        layers.append(Layer([Node("fight", b) for _ in range(n)]))
        since_rest += 1
        if since_rest >= TUNING["rest_every"]:
            layers.append(Layer([Node("rest")]))
            since_rest = 0
    if since_rest:
        layers.append(Layer([Node("rest")]))
    if TUNING["curriculum"] == 3:
        # Control ORDERING, but the elites restricted to second encounters --
        # the one property of the curriculum that survived every other check.
        # Under the control an elite can be a mechanic's FIRST appearance, so a
        # player can meet a rule for the first time at elite strength with no
        # warning. Isolated here because everything else about the two maps was
        # measured identical: layers, rests, enemy stats, adjacency, and the
        # mean position of both encounters.
        seen, second = set(), []
        for l in layers:
            for x in l.nodes:
                if x.kind == "rest":
                    continue
                if x.behaviour in seen:
                    second.append(x)
            for x in l.nodes:
                if x.kind != "rest":
                    seen.add(x.behaviour)
        pool = second or [x for l in layers for x in l.nodes if x.kind == "fight"]
        for x in rng.sample(pool, min(TUNING["n_elites"], len(pool))):
            x.kind = "elite"
            x.reward = True
        return layers
    fights = [x for l in layers for x in l.nodes if x.kind == "fight"]
    for x in rng.sample(fights, min(TUNING["n_elites"], len(fights))):
        x.kind = "elite"
        x.reward = True
    return layers


def scaled(ratio_key: str, base: int, floor: int = 1) -> int:
    """A design ratio applied to the scale it belongs to.

    Every difficulty number is a percentage of either the player's attack or
    the player's starting ceiling. Keeping them as percentages is what makes
    `base_atk` cosmetic: the same run at attack 8 prints bigger numbers and
    plays identically."""
    return max(floor, round(base * TUNING[ratio_key] / 100))


def priced(amount: int, punish: int, *, over: int = 0) -> int:
    """Scale what a wrong answer costs, leaving the hit it rides on alone.

    `over` is the part that is not punishment. A MULTIPLIER of 1 is the
    ordinary hit, so only the excess above 1 is priced -- otherwise halving the
    price of a charger would halve the damage of every turn it does not charge
    on, which is attrition and belongs to `wear_pct`. An additive bonus is
    punishment all the way down and prices from 0.
    """
    if punish == 100:
        return amount
    return over + round((amount - over) * punish / 100)


def _band(key: str, base: int, rng: random.Random) -> int:
    lo, hi = TUNING[key]
    return max(1, round(base * rng.randint(lo, hi) / 100))


def _worn(atk: int) -> int:
    """Base attrition: the damage a CORRECT player still takes, scaled.

    Applied after the draw, never by moving the band. `rng.randint(lo, hi)`
    consumes a variable number of words -- `_randbelow` rejects out-of-range
    values, and how often depends on the width -- so widening or narrowing a
    band shifts every later draw in the world. Measured: scaling `eatk_mult`
    by 0.8 left the layout, the boss pair and the shuffles identical and
    changed the boss health from (24, 25) to (41, 29) and every enemy name,
    because the stream had moved. A sweep built that way would not be
    comparing the same maps, and the difference would arrive as economy.

    Separate from the mechanic punishments on purpose: this is the cost of
    playing correctly, and the whole question the sweep asks is whether that
    cost and the cost of playing WRONG can be moved apart.
    """
    return max(1, round(atk * TUNING["wear_pct"] / 100))


def settle_attack(hp, block, dodge, hit, ignores_block, lethal):
    """Where damage lands -- the ONE place, called by the real turn and by the
    counterfactual audit alike.

    It exists because the audit used to recompute the same arithmetic beside
    the settlement instead of calling it. That is fine while the two agree and
    silently wrong the moment the settlement grows a cap, a floor, or any other
    clause -- and a duplicated rule that drifts is the single most common defect
    in this file's history. Returns (hp, block, absorbed).
    """
    if not hit or dodge:
        return hp, block, 0
    if lethal:
        return 0, block, 0
    if ignores_block:
        return hp - hit, block, 0
    absorbed = min(block, hit)
    return hp - (hit - absorbed), block - absorbed, absorbed


def lethal_now(is_boss: bool) -> bool:
    """Does a fired wind-up kill outright? The sole definition, for both engines.

    This was written twice -- once here and once in the vector engine -- and the
    copy dropped the `>= 2` branch, so a sweep setting `big_lethal` to 2 would
    have made ordinary wind-ups lethal in one engine and not the other while
    every differential, running at the default of 1, reported agreement. The
    rule is cheap and called once a turn, so there is no reason for a second
    copy of it to exist.
    """
    return bool(TUNING["big_lethal"]) and (TUNING["big_lethal"] >= 2 or is_boss)


def _armour_for(my_atk: int) -> int:
    """Flat reduction tied to the player's current attack.

    With the current zero offset, a plain hit lands for zero and a doubled hit
    lands for exactly one attack's worth while consuming the armour.  The
    armour is now an observable state slot, so those two facts can be joined by
    evidence rather than guessed from contradictory damage numbers.
    """
    return max(1, my_atk - TUNING["armour_off"])


def make_enemy(rng: random.Random, behaviour: str, my_atk: int,
               boss: bool = False, elite: bool = False,
               hp_budget: int = None) -> Enemy:
    """Health is scaled to the player's attack so a fight lasts 3-4 turns.

    Draw limits mean you land roughly 1.5 attacks a turn rather than 2, so the
    divisor is ~4.5x attack, not 6x. Long fights were the complaint: they are
    dull, they teach nothing after the first few turns, and every extra turn is
    another API call."""
    def _scale(hp, beh):
        # Armour divides everything you land, so printed health has to be
        # discounted the same way a regenerator's is -- otherwise an armoured
        # elite or boss is not "the monster that needs burst", it is just a wall.
        return hp * TUNING["armour_hp_scale"] // 100 if "armour" in beh else hp

    if elite:
        # An elite has less health than a normal enemy of the same behaviour, so
        # with a full wind-up its big hit never landed: measured 87% of the time
        # at attack 5 and only 30% after one attack reward. Growing stronger was
        # deleting the very mechanic the elite exists to teach. Fattening it is
        # the wrong fix (that was tried for normal chargers); shortening the
        # wind-up is what makes an elite worth its name -- it is the node that
        # shows you the pattern EARLIER, not the node with the biggest numbers.
        return Enemy(enemy_name(rng), behaviour,
                     hp=_scale(my_atk * rng.randint(*TUNING["hp_elite"]), behaviour),
                     atk=_worn(_band("eatk_elite_mult", my_atk, rng)),
                     rage=scaled("rage_ratio", my_atk),
                     regen=scaled("regen_ratio", my_atk),
                     charge_max=(TUNING["charge_max_elite"]
                                 if "charge" in behaviour else 0))
    if boss:
        # `hp_budget` replaces the DRAW, not the scaling below it. Splitting a
        # boss into phases must not also double it: two phases each drawing a
        # full `hp_boss` turned a 7-13x boss into a 14-26x one, and a clear rate
        # collapsing for that reason is indistinguishable from a mechanic that
        # does not work. The class scaling and the wind-up floor still apply per
        # phase, because both are claims about ONE fight lasting long enough.
        hp = (my_atk * rng.randint(*TUNING["hp_boss"]) if hp_budget is None
              else hp_budget)
        # Effective health budget by MECHANIC PERSISTENCE, not per boss pair.
        #
        # `armour_hp_scale` already discounts an armoured boss to 55%, and it
        # breaks once and stays broken -- so an `armour + X` boss is an X boss
        # with roughly half the printed health, while an `X + Y` boss carries
        # both punishments for the whole fight at full health. Measured over 60
        # worlds those two groups reached 83% and 31% informed conditional win
        # at the boss; equalising the health alone closed about seven eighths
        # of that, which puts most of the gap on the discount rather than on
        # the mechanic.
        #
        # Two classes, not six pair tables: a per-pair table would be six
        # hand-tuned answers, while this states the actual claim -- a one-shot
        # mechanic and a persistent one do not cost the same number of turns.
        persistent = "armour" not in behaviour
        hp = hp * TUNING["boss_hp_persistent" if persistent
                         else "boss_hp_armour"] // 100
        # A floor under the CLASS SCALING ONLY, which is why it is named for
        # that class. It is applied before `_scale`, so `armour_hp_scale` still
        # takes an armoured boss below it -- calling it a floor on boss health
        # would be false. This guard exists so that scaling the persistent class
        # down cannot undo what `hp_boss`'s lower bound guarantees, namely that
        # a boss lives long enough for its wind-up to fire.
        #
        # 5 -> 3 when the boss became two phases, and the old comment said how
        # to decide: "whether it does live long enough is settled by the firing
        # rates, not by this constant." Measured, floor by floor, over 160
        # worlds and both phases:
        #
        #     floor   phase health   turns   mechanic fired   boss total
        #       1-3        5.1x       5.4        100%           7-13x
        #         4        5.1x       5.4        100%           8-13x
        #         5        5.5x       5.6        100%          10-13x
        #
        # It never bound on firing -- a wind-up completes in `charge_max` = 2
        # turns and a phase lasts five. What it bound on was the TOTAL, because
        # applying a one-boss floor to each of two phases is a floor of twice
        # the size: the boss quietly went from 7-13x to 10-13x while every
        # threshold downstream was calibrated against the old range.
        if persistent:
            hp = max(hp, my_atk * TUNING["hp_boss_persistent_floor"])
        if "regen" in behaviour:
            # Regeneration multiplies with health rather than adding to it: at
            # 6 net damage a turn, a 54-health boss takes nine turns instead of
            # six, and rage makes those extra turns the expensive ones. Printed
            # health has to be discounted to keep the *effective* pool constant.
            hp = hp * TUNING["regen_hp_scale"] // 100
        return Enemy(enemy_name(rng), behaviour, hp=_scale(hp, behaviour),
                     atk=max(1, round(_band("eatk_boss_mult", my_atk, rng)
                                      * TUNING["boss_wear_pct"] / 100)),
                     rage=scaled("rage_ratio", my_atk),
                     regen=scaled("regen_ratio", my_atk),
                     # Here, beside the elite's, and NOT in `_roll_world`. It
                     # used to be applied afterwards by the caller, which made
                     # boss construction two pieces of code in two places -- and
                     # the second caller to appear, `kernel._enemy`, naturally
                     # copied the first piece and not the second. Its band boss
                     # then wound up for `charge_max` turns while the real one
                     # wound up for `charge_max_boss`, so a kernel sweep over
                     # that knob read a dead flat line where the real engine
                     # takes an ignorant player from 61% to 0%. One definition.
                     charge_max=(TUNING["charge_max_boss"]
                                 if "charge" in behaviour else 0))
    # A charging enemy must survive long enough to actually swing. The first fix
    # was to make it fatter -- wrong: it turned the hardest monster into the one
    # with the most health, the dodge turn cost an attack on top of that, and
    # rage punished the extra length. Shortening the wind-up instead
    # (charge_max 3 -> 2) makes the big hit land inside a normal-length fight.
    key = ("hp_enrage" if "enrage" in behaviour
           else "hp_pierce" if "pierce" in behaviour
           else "hp_glutton" if "glutton" in behaviour
           else "hp_momentum" if "momentum" in behaviour
           else "hp_charge" if "charge" in behaviour
           else "hp_regen" if "regen" in behaviour
           else "hp_armour" if "armour" in behaviour
           else "hp_wound" if "wound" in behaviour
           else "hp_counter" if "counter" in behaviour
           else "hp_guard" if "guard" in behaviour
           else "hp_mark" if "mark" in behaviour
           else "hp_mimic" if "mimic" in behaviour
           else "hp_ward" if "ward" in behaviour
           else "hp_poison" if "poison" in behaviour else "hp_normal")
    mult = rng.randint(*TUNING[key])
    return Enemy(enemy_name(rng), behaviour, hp=my_atk * mult,
                 atk=_worn(_band("eatk_mult", my_atk, rng)),
                 rage=scaled("rage_ratio", my_atk),
                 regen=scaled("regen_ratio", my_atk))


# 90-100, not 70-90. The old band capped the informed player at 90% by
# construction, and the test came from the reference play sometimes losing. That
# is the wrong place to get it from: a loss you cannot attribute teaches nothing.
# The test now comes from the GAP -- understanding everything clears ~95%, and
# each mechanic you did not work out drops you sharply below it. 24 trials, not
# 16, because 90% of 16 is 14.4 and the estimate has to be tighter than the band.
# The band is stated on the TRUE rate, but the screen only ever sees an
# estimate, and it accepts the first config that clears the bar out of up to 60
# tries -- so what gets accepted is the upper tail of the estimate, not of the
# truth. Measured: a population the screen believed was 90%+ solved at 84%.
# The threshold is therefore set above the target on purpose; the gap is the
# selection bias, not a change of intent.
SOLVE_TARGET = (0.94, 1.00)      # ESTIMATED clear rate under best-known play
# 48, not 24. Accepting a run when a NOISY estimate clears the threshold biases
# the accepted population upward -- a run whose true rate is 85% passes a 24-try
# "is it >= 90%?" test often enough to matter, and the solver duly reported 85%
# for a population the screen believed was 90%+. Winner's curse, and the fix is
# a tighter estimate rather than a higher bar.
SOLVE_TRIALS = 80
SOLVE_TRIES = 60


def _best_known(run, rng=None) -> bool:
    """Best play we know of: dodge the wind-up, never stack block against a
    piercer, block otherwise, heal when hurt. Used only to grade a generated
    run -- it is the yardstick, not a claim of optimality."""
    rng = rng or random.Random(0)
    kinds = run.by_kind
    def loop(f):
        t = 0
        while not f.over() and t < 40:
            while not f.over():
                # A heal is spent either to survive or to cleanse. Leaving the
                # cleanse out of the reference play would make the screen accept
                # runs on the basis of a player who never answers the poisoner.
                if (f.state[("me", "hp")] * 100 < f.max_hp * TUNING["heal_below"]
                        and f.can_play(kinds["heal"])):
                    f.play(kinds["heal"]); continue
                big = ("charge" in f.parts
                       and f.state[("them", "charge")] >= f.enemy.charge_max)
                if big and f.can_play(kinds["dodge"]):
                    f.play(kinds["dodge"]); continue
                if ("armour" in f.parts
                        and not f.state[("me", "double")]
                        and f.can_play(kinds["buff_mark"])):
                    f.play(kinds["buff_mark"]); continue
                if f.can_play(kinds["attack"]):
                    f.play(kinds["attack"]); continue
                if "pierce" in f.parts:
                    break
                if f.can_play(kinds["block"]):
                    f.play(kinds["block"]); continue
                break
            f.end_turn(); t += 1
        return f.won()
    # Use the same exception-safe transaction as the public solver. This used
    # to maintain a second hand-written restore list; poison was consequently
    # omitted here and in `run_once` at the same time.
    with run.trial():
        for i, layer in enumerate(run.layers):
            j, kind = run.choose(i, rng, run.hp < run.max_hp * 0.4,
                                 run.hp > run.max_hp * 0.6)
            if kind == "rest":
                # The ceiling branch no longer heals, so "chewed ceiling ->
                # take it" is no longer safe on its own: it would walk into the
                # next fight at whatever health the last one left. Cleanse when
                # poisoned and able to afford the turn, heal when hurt, take the
                # ceiling back only with health to spare. This reference has to
                # be strong -- the screen re-rolls until IT clears the band, so
                # a weak one buys easy runs.
                if run.poison and run.hp >= run.max_hp * 0.45:
                    mode = "cap"
                elif run.hp < run.max_hp * 0.75:
                    mode = "hp"
                else:
                    mode = ("cap" if run.recoverable_max_hp - run.max_hp
                            >= scaled("rest_cap_pct", run.base_max_hp) else "hp")
                run.rest(mode)
                continue
            elite = kind == "elite"
            f = run.fight_at(i, j)
            if not loop(f):
                return False
            run.absorb(f)
            if elite:
                run.apply_reward("atk" if run.hp > run.max_hp * 0.5 else "hp")
        for bf in run.boss_fights():
            if not loop(bf):
                return False
            run.absorb(bf)
        return True


def FIGHT_COST_AUDIT(seeds) -> dict[str, float]:
    """Average health a won fight costs under informed play, by node kind.

    This is what anchors the health-rest percentage. Resting has to buy back an ordinary fight,
    or the node is decoration; it must NOT buy back an elite, or growth becomes
    free and the elite stops being a bet. So the rest value is not a free knob:
    it lives in the window [ordinary fight, elite fight], and that window is
    measured, not guessed."""
    from tune import POLICIES
    pick = POLICIES["smart"]
    out: dict[str, list[int]] = {"普通": [], "精英": [], "boss": []}
    for sd in seeds:
        r = Run(sd)
        kinds = r.by_kind
        base = list(r._pristine_deck)
        r.deck_list = list(base); r.hp = r.max_hp
        atk0, mhp0 = r.base_atk, r.max_hp

        def loop(f, tag):
            t = 0
            hp0 = f.state[("me", "hp")]
            while not f.over() and t < 40:
                while not f.over():
                    if (f.state[("me", "hp")] * 100 < f.max_hp * TUNING["heal_below"]
                            and f.can_play(kinds["heal"])):
                        f.play(kinds["heal"]); continue
                    c = pick(f, r, kinds)
                    if c is None or not f.play(c):
                        break
                f.end_turn(); t += 1
            if f.won():
                out[tag].append(hp0 - f.state[("me", "hp")])
            return f.won()

        alive = True
        for i, layer in enumerate(r.layers):
            j, kind = r.choose(i, random.Random(i), r.hp < r.max_hp * 0.4,
                               r.hp > r.max_hp * 0.6)
            if kind == "rest":
                r.rest("hp"); continue
            elite = kind == "elite"
            f = r.fight_at(i, j)
            if not loop(f, "精英" if elite else "普通"):
                alive = False; break
            r.absorb(f)
            if elite:
                r.apply_reward("atk")
        if alive:
            for bf in r.boss_fights():
                if not loop(bf, "boss"):
                    break
                r.absorb(bf)
        r.base_atk, r.max_hp, r.deck_list = atk0, mhp0, list(base)
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in out.items()}


def POLICY_FIRE_AUDIT(seeds) -> dict[str, float]:
    """How often a charging enemy dies before it ever swings, per node kind.

    Run under the GREEDY brute-force line (take the attack card, take the attack
    stat), because that is the line that shortens fights. A behaviour that never
    resolves cannot be learned and cannot be tested, so the boss stops checking
    anything -- which is what happened at charge_max 3: 25% of boss fights.
    """
    from tune import POLICIES
    pick = POLICIES["rush"]
    out: dict[str, list[int]] = {"普通": [], "精英": [], "boss": []}
    for sd in seeds:
        r = Run(sd)
        kinds = r.by_kind
        base = list(r._pristine_deck)
        r.deck_list = list(base); r.hp = r.max_hp
        atk0, mhp0 = r.base_atk, r.max_hp

        def loop(f, tag):
            t = n = 0
            while not f.over() and t < 40:
                while not f.over():
                    if (f.state[("me", "hp")] * 100 < f.max_hp * TUNING["heal_below"]
                            and f.can_play(kinds["heal"])):
                        f.play(kinds["heal"]); continue
                    c = pick(f, r, kinds)
                    if c is None or not f.play(c):
                        break
                if (not f.over() and "charge" in f.parts
                        and f.state[("them", "charge")] >= f.enemy.charge_max):
                    n += 1
                f.end_turn(); t += 1
            if "charge" in f.parts:
                out[tag].append(n)
            return f.won()

        alive = True
        for i, layer in enumerate(r.layers):
            j, kind = r.choose(i, random.Random(i), r.hp < r.max_hp * 0.4,
                               r.hp > r.max_hp * 0.6)
            if kind == "rest":
                r.rest("hp"); continue
            elite = kind == "elite"
            f = r.fight_at(i, j)
            if not loop(f, "精英" if elite else "普通"):
                alive = False; break
            r.absorb(f)
            if elite:
                r.apply_reward("atk")
            else:
                r.deck_list.append(kinds["attack"])
        if alive:
            for bf in r.boss_fights():
                if not loop(bf, "boss"):
                    break
                r.absorb(bf)
        r.base_atk, r.max_hp, r.deck_list = atk0, mhp0, list(base)
    return {k: (sum(1 for x in v if x == 0) / len(v) if v else 0.0)
            for k, v in out.items()}


@dataclass
class Run:
    """One run. Numbers are rolled per seed, then screened.

    Fixing the numbers removed variance but also removed variety; rolling them
    freely produced runs that were unwinnable or trivial (clear rate ran 90% at
    one attack value and 31% at another). So: roll, measure the clear rate under
    best-known play across several shuffles, and reroll until it lands in the
    target band. Every run a player sees is therefore beatable but not free."""

    seed: int
    max_hp: int = 0
    validate: bool = True
    target: tuple = SOLVE_TARGET

    def __post_init__(self):
        self._hp_fixed = bool(self.max_hp)
        # Keep the BEST attempt, not the last one. Falling back to whatever was
        # rolled on try 60 is arbitrary -- and it bites exactly when the bar is
        # raised, because that is when seeds start failing every try. Raising
        # the threshold from 0.90 to 0.94 dropped solved clear probability from
        # 84% to 68%, and none of that came from the harder bar: it came from
        # seeds silently keeping a random configuration.
        best_salt, best_rate = None, -1.0
        for attempt in range(SOLVE_TRIES):
            salt = self.seed * 1009 + attempt
            self._roll(salt)
            if not self.validate:
                self.rate = None
                break
            self.rate = self._clear_rate()
            if self.rate > best_rate:
                best_salt, best_rate = salt, self.rate
            if self.target[0] <= self.rate <= self.target[1]:
                break
        else:
            if best_salt is not None:
                self._roll(best_salt)
                self.rate = best_rate
        # The screen plays hundreds of cards. Anything it touched has to be
        # wound back, and "anything" keeps turning out to be wider than it
        # looks: first the known-cost flags (which handed over the number that
        # names dodge on sight), then the deck list itself -- heals exhaust
        # permanently now, so sixteen simulated runs emptied the pile and the
        # player started with no healing at all.
        for c in self.deck.values():
            c.cost_known = False
        self.deck_list = list(self._pristine_deck)
        self.hp = self.max_hp
        self.seen_player = set()
        self.attempts = attempt + 1

    # -- generation ------------------------------------------------------
    # A run is rolled in two halves, and which half is which is the whole
    # transfer experiment.
    #
    #   IDENTITY -- the symbol-to-card mapping, the slot letters, the card
    #   numbers, your attack and your health -- is fixed for the seed and does
    #   not change when you die. It is what you learned.
    #
    #   WORLD -- the order you meet things in, what the map looks like, how much
    #   health each enemy has, what the boss is made of, how the deck shuffles --
    #   is rolled fresh for every life.
    #
    # Replaying the identical run (which is what the first version of `--life`
    # did) measures whether a record gets used. Re-rolling the world while
    # holding the mapping measures whether the RULES were learned, because
    # nothing about the sequence carries over -- only what the symbols mean and
    # how each kind of monster behaves. That is the transfer question.

    def _roll_identity(self, salt: int, version: int = 1) -> None:
        # Namespaced streams keep representation changes from changing game
        # mechanics. Adding a display slot consumes more Layout randomness; it
        # must not silently reroll the deck, attack or health that follows.
        # version 2（identity_key 非 0 时）：布局流换名字、整排洗牌；v1 的流一个字都不动。
        # 第 3 版（B 之后的世界）：布局流和牌流都换名字，基础攻击从五个值里抽（五个世界攻击各不相同）；
        # 第 2 版（B）和第 1 版（A）的流一个字不动。
        rng_layout = random.Random(f"identity-v{min(version, 2)}:{salt}:layout" if version < 3 else f"identity-v3:{salt}:layout")
        # v1 保持原来的调用形状（有测试用只收一个参数的替身 Layout）；v2、v3 的布局都是第 2 版洗法
        self.layout = Layout(rng_layout, version=2) if version >= 2 else Layout(rng_layout)
        if version >= 3:
            from camp import ATK_CHOICES_V3
            self.deck, self.base_atk = make_deck(random.Random(f"identity-v3:{salt}:deck"), atk_choices=ATK_CHOICES_V3)
        else:
            self.deck, self.base_atk = make_deck(
                random.Random(f"identity-v1:{salt}:deck"))
        # Costs carry no randomness, so this can be applied to the finished deck
        # without shifting a single word of the stream -- unlike the block
        # AMOUNT, which is entangled with the heal draw and is scaled inside
        # `make_deck` for that reason.
        for c in self.deck.values():
            if c.kind == "block":
                c.cost = TUNING["block_cost"]
            if c.kind == "dodge":
                c.cost = TUNING["dodge_cost"]
        self.by_kind = {c.kind: n for n, c in self.deck.items()}
        self.deck_list = [
            self.by_kind[k]
            for k, n in STARTING_PILE.items()
            for _ in range(TUNING["deck_counts"].get(
                k, TUNING["deck_attacks"] if k == "attack" else n))]
        self._pristine_deck = list(self.deck_list)
        if not self._hp_fixed:
            self.max_hp = self.base_atk * TUNING["life_in_hits"]
        self.base_max_hp = self.max_hp
        # The starting ceiling is a difficulty SCALE.  This is the ceiling the
        # player can recover to after upgrades have raised it and poison has
        # temporarily chewed it down.  Conflating the two made a ceiling rest
        # after an elite reward reduce 256 maximum health back to 232.
        self.recoverable_max_hp = self.max_hp

    def _roll_world(self, salt: int) -> None:
        rng = random.Random(salt)
        self.rng = rng
        # Kept on the run so the enemy loop can build the midterm's monster
        # from the same side stream; `make_enemy` draws, and drawing from the
        # shared one would undo what the namespace is for.
        self._mid_rng = random.Random(f"midterm-v1:{salt}")
        # 标记代号的含义每局重掷，自己的命名流；没有标记怪时不影响任何别的数字。
        # 按（世界，地图）掷：换世界后得重新弄清哪个代号是哪种牌（同一张图在两个世界里映射相同会留下背题通道）；
        # identity_key 为 0 时流名一个字不变。
        key = TUNING["identity_key"]
        self.mark_perm = tuple(random.Random(f"mark-v1:{key}:{salt}" if key else f"mark-v1:{salt}").sample(
            list(Fight.MARK_ORDER), len(Fight.MARK_ORDER)))
        self.drawn = tuple(BEHAVIOURS)
        k = TUNING["pool_draw"]
        if k and k < len(BEHAVIOURS):
            draw_rng = random.Random(f"pool-v1:{salt}")
            for _ in range(200):
                cand = tuple(draw_rng.sample(list(BEHAVIOURS), k))
                if len(boss_stage_pool(cand)) >= TUNING["boss_stages"]:
                    self.drawn = cand
                    break
            else:
                raise ValueError(f"pool_draw={k} 从 {BEHAVIOURS} 抽不出含 "
                                 f"{TUNING['boss_stages']} 个 boss 机制的组合")
        self.layers = make_layers(rng, mid_rng=self._mid_rng,
                                  behaviours=self.drawn)
        pool = boss_stage_pool(self.drawn)
        if len(pool) < TUNING["boss_stages"]:
            raise ValueError(
                f"rotation {BEHAVIOURS} offers {len(pool)} boss-capable "
                f"behaviours {pool} and the boss needs "
                f"{TUNING['boss_stages']}. Poison is not boss-capable: its "
                f"answer is at the next rest and there is none after the boss.")
        stages = rng.sample(pool, TUNING["boss_stages"])
        self.boss_stages = tuple(stages)
        # A display string, and deliberately not joinable back into a behaviour
        # spec: anything that used to split this on "+" and hand the pieces to
        # an engine is now asking for a fight that does not exist.
        self.boss_behaviour = " -> ".join(stages)
        # 世界（identity_key 非 0）：怪的**数值**（名字、血、攻击、boss 预算与分段）按世界重掷，结构（层、顺序、
        # boss 机制、标记映射、池抽样）仍按 salt。到此为止 rng 只掷过结构，所以换掉后面的流不动前面的任何一个数。
        # identity_key 为 0 时 nrng 就是 rng，旧世界一字不动。
        nrng = random.Random(f"numbers-v1:{key}:{salt}") if key else rng
        mid_nrng = random.Random(f"numbers-mid-v1:{key}:{salt}") if key else self._mid_rng
        for layer in self.layers:
            for node in layer.nodes:
                if node.kind != "rest":
                    node.enemy = make_enemy(
                        mid_nrng if node.role == "mid" else nrng,
                        node.behaviour, self.base_atk,
                        elite=(node.kind == "elite"))
                    # 两轮分别定价。`role` 早就带着 teach/test，不用新建结构。
                    # 一段代码管两轮，免得「第二轮加价」和「第一轮打折」长成
                    # 两条会各自漂移的规则。
                    if node.role in ("teach", "mid", "test"):
                        e, r = node.enemy, node.role
                        b = node.behaviour
                        hp_pct = (TUNING.get(f"{r}_hp_by") or {}).get(
                            b, TUNING[f"{r}_hp_pct"])
                        atk_pct = (TUNING.get(f"{r}_atk_by") or {}).get(
                            b, TUNING[f"{r}_atk_pct"])
                        e.punish = TUNING[f"{r}_punish_pct"]
                        if "ward" in b:
                            e.ward_cap = TUNING.get(f"ward_{r}_cap", 0)
                            e.ward_start = TUNING.get(f"ward_{r}_start", 0)
                        if r == "mid":
                            e.charge_start = TUNING["mid_charge_start"]
                            e.opens_with_dodge = TUNING["mid_opens_with_dodge"]
                        if hp_pct:
                            e.hp = max(1, round(e.hp * (100 + hp_pct) / 100))
                        if atk_pct:
                            e.atk = max(1, round(e.atk * (100 + atk_pct) / 100))
        # ONE budget, split. The share floor is what keeps each phase long
        # enough to show its mechanic -- a charger needs `charge_max` turns of
        # wind-up before the move it is asking about ever happens, and a phase
        # that dies first is a phase that taught nothing.
        budget = (self.base_atk * nrng.randint(*TUNING["hp_boss"])
                  * TUNING["boss_hp_pct"] / 100)
        floor = TUNING["boss_stage_floor"] / 100
        shares = [nrng.uniform(floor, 1.0 - floor * (len(stages) - 1))
                  for _ in stages[:-1]]
        shares.append(1.0 - sum(shares))
        built = tuple(
            make_enemy(nrng, stage, self.base_atk, boss=True,
                       hp_budget=max(
                           1,
                           self.base_atk * TUNING["boss_stage_min"],
                           round(budget * share
                                 * (TUNING["boss_charge_hp"] / 100
                                    if "charge" in stage else 1))))
            for stage, share in zip(stages, shares))
        if TUNING["boss_switch"]:
            # One body, one health bar -- MERGED from the same two draws, not
            # rolled differently. Building it with a single `make_enemy` call
            # consumed fewer words from the stream, so the shuffles moved and
            # the two structures were no longer the same world: a comparison
            # between them would have carried a different card order as well.
            #
            # The handover lands exactly where the second stage's health bar
            # used to start, so the two halves print the bands the split would
            # have given them. `boss_switch_frac` overrides that when the sweep
            # needs to ask how much of the bar the second rule should own --
            # the first measurement said the answer is not 50%.
            boss, second = ((built[1], built[0]) if TUNING["boss_switch_reverse"]
                            else (built[0], built[1]))
            boss.hp = max(1, round(sum(e.hp for e in built)
                                   * TUNING["boss_switch_hp_pct"] / 100))
            at = (boss.hp * TUNING["boss_switch_frac"] // 100
                  if TUNING["boss_switch_frac"] else second.hp)
            boss.set_switch(second.behaviour, at)
            self.boss_enemies = (boss,)
        else:
            self.boss_enemies = built
        if TUNING["boss_punish_pct"]:
            # 写在对象上而不是 make_enemy 里：不动随机流，六池登记的世界原样不变。
            for e in self.boss_enemies:
                e.punish = TUNING["boss_punish_pct"]
        for e in self.boss_enemies:
            if "ward" in e.behaviour:
                e.ward_cap = TUNING["ward_boss_cap"]
                e.ward_start = TUNING["ward_boss_start"]
        # Always the same COUNT, so the stream does not move with the structure.
        self.shuffles = [rng.randrange(1 << 30)
                         for _ in range(len(self.layers) + len(stages))]
        self.poison = 0
        self.wound = 0
        self.punished = (0,) * 8
        self.poisoned_hp_rests = 0
        self.hp = self.max_hp
        # A player's persistent slots belong to the run, not to one enemy.
        # Once one of them has visibly changed, replacing the enemy must not
        # turn its number back into ``?``. Enemy and transient slots still
        # start unrevealed in every fight.
        self.seen_player = set()

    def _roll(self, salt: int) -> None:
        if TUNING["identity_key"]:
            self._roll_identity(TUNING["identity_key"], version=TUNING["identity_version"])   # 世界的身份：牌的数值、血上限、符号按世界的键掷
        else:
            self._roll_identity(self.seed)
        if TUNING["names_key"]:
            self._rename_cards(TUNING["names_key"])
        self._roll_world(salt)

    # 身份里固定的六个假词；重掷时避开它们，也避开彼此的首字母，免得打字打混。
    BASE_NAMES = ("kel", "vorth", "mira", "tsun", "ravi", "doln")

    def _rename_cards(self, key: int) -> None:
        """只换名字：Card 对象、种类、数值、费用、牌序全部原样。`key` 是包的键。"""
        from namegen import _word
        rng = random.Random(f"names-v1:{key}")
        # 两个音节、5–7 个字母：单音节太容易拼成真英文词（量过：him / foul / sum），
        # 而名字一旦有含义就是白送的信息。不用系统词典过滤 —— 人类测试包要在别的机器上
        # 复现同一套名字。
        new = []
        while len(new) < len(self.deck):
            w = _word(rng, 2).lower()
            if (not 5 <= len(w) <= 7 or w in self.BASE_NAMES or w in new
                    or any(w[0] == x[0] for x in new)):
                continue
            new.append(w)
        mapping = dict(zip(list(self.deck), new))
        self.deck = {mapping[n]: c for n, c in self.deck.items()}
        self.by_kind = {c.kind: n for n, c in self.deck.items()}
        self.deck_list = [mapping[n] for n in self.deck_list]
        self._pristine_deck = [mapping[n] for n in self._pristine_deck]

    def _clear_rate(self) -> float:
        """Only the shuffles are redrawn -- the deck, the layers and the enemies
        are what is being graded.

        The deck has to be reset every trial, not just at the end. Heals are
        removed permanently when played, so without this the first trial ran
        with three heals and the other fifteen ran with none -- and the rate the
        screen accepted a run on was a rate for a deck the player never has.
        Restoring only after the loop (which is what the previous fix did) hides
        the leak instead of closing it."""
        keep_s, keep_d = list(self.shuffles), list(self.deck_list)
        keep_seen = set(self.seen_player)
        rng = random.Random(self.seed ^ 0x5EED)
        wins = 0
        for _ in range(SOLVE_TRIALS):
            self.deck_list = list(self._pristine_deck)
            self.shuffles = [rng.randrange(1 << 30) for _ in keep_s]
            self.hp = self.max_hp
            wins += _best_known(self, rng)
        self.shuffles, self.deck_list = keep_s, keep_d
        self.seen_player = keep_seen
        self.hp = self.max_hp
        return wins / SOLVE_TRIALS

    # -- fights ----------------------------------------------------------
    def _fight(self, enemy, shuffle, boss: bool = False) -> Fight:
        # `boss` is a CONSTRUCTOR argument, not something set afterwards: the
        # opening hand is dealt in `__post_init__`, so a flag assigned after the
        # fact arrives one hand too late for `boss_opens_with_dodge`.
        return Fight(self.deck, self.deck_list, self.layout, enemy,
                     hp=self.hp, max_hp=self.max_hp, base_atk=self.base_atk,
                     poison0=self.poison, wound0=self.wound,
                     punished0=self.punished, mark_perm=self.mark_perm,
                     rng=random.Random(shuffle),
                     is_boss=boss,
                     seen={("me", prop) for prop in self.seen_player},
                     # The floor is a share of the STARTING ceiling, so it has
                     # to come from the run: a fight only knows the ceiling it
                     # was handed, which poison has already been chewing.
                     hp_floor=scaled("hp_floor_pct", self.base_max_hp))

    # Everything that a trial may touch, in one place. Ten separate bugs in
    # this codebase have been "the evaluator left a mark on the thing it was
    # evaluating", and every previous fix was another hand-written save list in
    # another function -- which is how the list came to be missing `poison` in
    # two of them at once. A field added to the run in future is caught here or
    # nowhere.
    TRIAL_STATE = ("hp", "max_hp", "recoverable_max_hp", "base_atk", "poison",
                   "wound", "punished", "poisoned_hp_rests")

    def snapshot(self) -> dict:
        return {**{k: getattr(self, k) for k in self.TRIAL_STATE},
                "deck_list": list(self.deck_list),
                "shuffles": list(self.shuffles),
                "seen_player": set(self.seen_player),
                "cost_known": {n: c.cost_known for n, c in self.deck.items()}}

    def restore(self, snap: dict) -> None:
        for k in self.TRIAL_STATE:
            setattr(self, k, snap[k])
        self.deck_list = list(snap["deck_list"])
        self.shuffles = list(snap["shuffles"])
        self.seen_player = set(snap["seen_player"])
        for n, c in self.deck.items():
            c.cost_known = snap["cost_known"][n]

    @contextlib.contextmanager
    def trial(self, shuffles=None):
        """One evaluation attempt, isolated from every other one.

        Resets to the start of a life on the way in and restores the caller's
        state on the way out -- win, loss or exception. Anything that wants to
        simulate this run goes through here; nothing hand-rolls a save list."""
        snap = self.snapshot()
        try:
            self.hp = self.max_hp = self.recoverable_max_hp = self.base_max_hp
            self.poison = 0
            self.wound = 0
            self.punished = (0,) * 8
            self.poisoned_hp_rests = 0
            self.seen_player = set()
            self.deck_list = list(self._pristine_deck)
            for c in self.deck.values():
                c.cost_known = False
            if shuffles is not None:
                self.shuffles = list(shuffles)
            yield self
        finally:
            self.restore(snap)

    _absorbed = None

    def absorb(self, f) -> None:
        """Carry a finished fight's health AND ceiling back into the run.

        The ceiling has to come back too now that poison eats it -- writing only
        `hp` back meant the loss vanished the moment the fight ended, which is
        the same shape as every other leak in this file's history."""
        self._absorbed = f
        self.hp = f.state[("me", "hp")]
        self.max_hp = f.max_hp
        self.poison = f.state[("me", "poison")]
        self.wound = f.state[("me", "wound")]
        self.punished = tuple(f.punished)
        self.hp = min(self.hp, self.max_hp)
        self.seen_player.update(
            prop for side, prop in f.seen
            if side == "me" and prop in PERSISTENT_PLAYER_PROPS)

    def _mark_run_changes(self, before: tuple[int, int, int, int]) -> None:
        """Persist disclosure caused by map actions such as rests/rewards."""
        old_hp, old_cap, old_atk, old_poison = before
        values = (("hp", old_hp, self.hp),
                  ("cap", old_cap, self.max_hp),
                  ("atk", old_atk, self.base_atk),
                  ("poison", old_poison, self.poison))
        self.seen_player.update(prop for prop, old, new in values if old != new)

    def auto_resupply(self) -> tuple[int, int]:
        """The automatic resupply at a rest layer under `TUNING["auto_rest"]` (registration 12): an
        environment event, not a decision. Exactly the "recover health" effect of `rest("hp")` --
        health += rest_pct% of the CURRENT ceiling, capped at the ceiling -- and nothing else: the
        ceiling, the poison stacks and the audit counter `poisoned_hp_rests` are not touched.
        Returns (health before, health after)."""
        before = (self.hp, self.max_hp, self.base_atk, self.poison)
        self.hp = min(self.max_hp, self.hp + self.max_hp * TUNING["rest_pct"] // 100)
        self._mark_run_changes(before)
        return before[0], self.hp

    def rest(self, mode: str) -> None:
        """Two ways to spend a rest, and picking the wrong one is a real loss.

        "hp"  heals a percentage of the ceiling -- what you want when the next
              fight might kill you.
        "cap" gives back ceiling the poison ate -- what you want when the run is
              long and your maximum has been chewed down.
        Neither is dominant, which is the point: the rest node used to be a
        button, and a button is not a decision.

        Under `TUNING["auto_rest"]` there is no choice: `mode` is ignored and the
        automatic resupply is applied (`auto_resupply`), so a caller that still
        passes a mode -- a planner, a replay, a habit -- plays the same rule."""
        if TUNING["auto_rest"]:
            self.auto_resupply()
            return
        before = (self.hp, self.max_hp, self.base_atk, self.poison)
        if mode == "cap":
            # This is the only thing in the game that clears poison. Nothing in
            # a fight touches it, so the poisoner is answered on the map or not
            # at all -- and answering it costs you the health you could have
            # taken instead, which is what makes the node a decision.
            # Ceiling and cleanse only -- no healing. Healing here as well made
            # the node a formality rather than a decision: at 29/112 the ceiling
            # option returned 35 health against the heal option's 39, so it cost
            # four points and bought +35 maximum AND the cleanse on top. Branches
            # that differ by four points are not branches. They are orthogonal
            # now: one buys the next fight, the other buys the rest of the run.
            missing = max(0, self.recoverable_max_hp - self.max_hp)
            back = min(scaled("rest_cap_pct", self.base_max_hp), missing)
            self.max_hp += back
            self.poison = 0
            self.poisoned_hp_rests = 0
        else:
            # Audit only -- nothing in the rules reads this. Choosing health
            # while carrying a stack is the decision poison is supposed to
            # test, so how often each player does it stays worth counting even
            # though charging for it was tried twice and failed twice.
            if self.poison > 0:
                self.poisoned_hp_rests += 1
            self.hp = min(self.max_hp,
                          self.hp + self.max_hp * TUNING["rest_pct"] // 100)
        self._mark_run_changes(before)

    def choose(self, i: int, rng, want_rest: bool, want_elite: bool):
        """Which node to walk into. Returns (index, kind).

        The caller may condition on node KINDS because fight / elite / rest are
        printed on the map. It may not condition on the hidden behaviour behind
        a fight node. Selection is therefore random only WITHIN the visible kind
        the policy chose; otherwise the solver would force a player to stumble
        into a visibly marked elite that they deliberately declined."""
        layer = self.layers[i]
        rests = [k for k, n in enumerate(layer.nodes) if n.kind == "rest"]
        elites = [k for k, n in enumerate(layer.nodes) if n.kind == "elite"]
        fights = [k for k, n in enumerate(layer.nodes) if n.kind == "fight"]
        if want_rest:
            if rests:
                return rng.choice(rests), "rest"
        if want_elite and elites:
            return rng.choice(elites), "elite"
        # Declining to seek an elite means taking an ordinary fight when one is
        # visible. An elite is forced only if the layer offers no ordinary fight.
        opts = fights or elites
        if not opts:
            if not rests:
                raise ValueError(f"layer {i} contains no selectable node")
            return rng.choice(rests), "rest"       # a rest-only layer
        j = rng.choice(opts)
        return j, layer.nodes[j].kind

    def fight_at(self, i: int, node: int = 0) -> Fight:
        return self._fight(self.layers[i].nodes[node].enemy, self.shuffles[i])

    def elite_rewards(self) -> list[tuple[str, str]]:
        """(label, key). Labelled by slot symbol, never by meaning -- reading
        the reward correctly requires having worked out what the slots are, and
        taking the attack one is the only way to make that stat move at all."""
        return [(f"{self.layout.L('me', 'atk')} +?", "atk"),
                (f"{self.layout.L('me', 'cap')} +?", "hp")]

    def apply_reward(self, key: str) -> None:
        if key not in {"atk", "hp"}:
            # Invalid policy sentinels used to fall through to the health
            # branch.  That turned "per-successor" into a plausible-looking
            # reward instead of exposing an executor bug.
            raise ValueError(f"unknown elite reward: {key!r}")
        before = (self.hp, self.max_hp, self.base_atk, self.poison)
        if key == "atk":
            self.base_atk += scaled("reward_atk_ratio", self.base_atk)
        else:
            back = scaled("reward_hp_pct", self.base_max_hp)
            self.max_hp += back
            self.recoverable_max_hp += back
            self.hp += back
        self._mark_run_changes(before)

    def boss_fights(self):
        """Each boss phase in order. `absorb` between them.

        There is no `boss_fight` any more, and the rename is the point: a
        default argument here would let every existing caller keep compiling
        while silently fighting only the first phase, which is the quietest
        possible way to lose half a boss.

        What carries across a phase is what the run owns -- health, ceiling,
        poison, and the cards already spent. What resets is what the fight owns
        -- hand, energy, block, dodge, and the wind-up and rage counters. That
        split is not a rule written here; it is what `_fight` reads from the run
        versus what `Fight` starts fresh, and `absorb` is what makes the first
        half true.
        """
        previous = None
        for i, enemy in enumerate(self.boss_enemies):
            # A tripwire, because "loop twice" and "carry the run" are different
            # promises and only the first one is enforced by the call shape.
            # `list(run.boss_fights())` builds BOTH fights before the caller has
            # absorbed anything, so phase two starts from the pre-boss health --
            # a boss at half difficulty that no test of the reference evaluator
            # would notice, because the reference evaluator gets it right.
            if previous is not None and self._absorbed is not previous:
                raise RuntimeError(
                    "boss phase requested before the previous one was "
                    "absorbed. Call `run.absorb(f)` between phases, and do "
                    "not drain `boss_fights()` eagerly -- `list(...)` builds "
                    "every phase from the pre-boss health, which is a boss at "
                    "half difficulty that no test of the reference evaluator "
                    "would notice, because the reference evaluator gets it "
                    "right.")
            f = self._fight(enemy, self.shuffles[-(len(self.boss_enemies) - i)],
                            boss=True)
            previous = f
            yield f

    def reward_choices(self) -> list[str]:
        return [self.by_kind[k] for k in ("attack", "block", "dodge")]

    def take(self, name: str) -> None:
        self.deck_list.append(name)


RESUPPLY_WORDS = "automatic resupply"     # the public log word for the environment's rest under auto_rest


def resupply_line(layer: int, changed: str) -> str:
    """The one public log line of an automatic resupply (registration 12, `TUNING["auto_rest"]`), in the same
    change-list format as the rest line: `[layer N] automatic resupply -> a3: 120->155`, or
    `-> (nothing changed)` at full health. "automatic" is what says it was not the player's action; the
    model's history, the human's screen, the record and the audit parser all read this exact text."""
    return f"[layer {layer}] {RESUPPLY_WORDS} -> " + (changed or "(nothing changed)")


def run_changes(run: Run, before: tuple[int, int, int, int]) -> str:
    """Opaque, post-effect run-level changes for map actions.

    Map prompts must not bypass the `? until changed` rule by spelling out
    semantic fields such as ``health 137``.  Rest and elite rewards happen
    outside a Fight, so they need the same label-based change report explicitly.
    """
    old_hp, old_cap, old_atk, old_poison = before
    fields = (("hp", old_hp, run.hp),
              ("cap", old_cap, run.max_hp),
              ("atk", old_atk, run.base_atk),
              ("poison", old_poison, run.poison))
    return ", ".join(f"{run.layout.L('me', prop)}: {old}->{new}"
                     for prop, old, new in fields if old != new)
