"""原型的世界外衣（surface）：每个世界自己的身份键、牌名、经济（2026-11-07，用户「八个吧」；docs/antagonist_boss/43_eight_world_pack.md §1）。

一个外衣 = core 已有的那一套世界机制里原型用得到的部分：身份键（adventure.Run._roll_identity 第 3 版：基础攻击、治疗、整排符号）、
names_key（牌名）、经济（life_in_hits、rest_pct、盾 block_pct）。怪的数值按 core 的 numbers-v1:{键}:{salt} 自动随键重掷；守势编码 / 开场、
boss 的预抽序列（scripts/guard_slot.py、antagonist_boss）的流名本来就带 identity_key。罚的倍数、原型的结构比例（wear_pct、test_hp_pct、
hp_counter、hp_momentum …）、boss 的结构旋钮每个世界一样（用户 11-07）。

  A        世界 A：身份 0（种子身份）、names_key 0、原型的经济（PROTO_WORLD 不设 = A；什么也不写，默认路径逐字不变）
  k{键}    世界 2–8：43 §1 的规则挑出、冻结在 SURFACES（derive() 按规则重算，必须逐键相同）

antagonist_proto 的开关 PROTO_WORLD 读这里：setup() 在调参之后调 apply(name, TUNING)，回到 A 时还原。
读记录的脚本（counter_noblock_score、behaviour_report、audit_proto_check）按记录 proto 块的 world 键（没有 = A）用 labels() / card_kinds()。

  python3 -B scripts/proto_worlds.py derive   （候选 v3c1 的环境，不设 PROTO_WORLD）按规则重算、和 SURFACES 比，打印表"""
import json, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = "proto-worlds-v1-2026-11-07"

# ---------------------------------------------------------------- 规则（43 §1；预登记）
EARLIER_KEYS = (0, 1, 5, 10, 17)            # 登记 12 的世界 A–E 用过的身份键（42 号试点的 1、5 也在里面）
KEY_START, N_NEW, IDENTITY_VERSION = 2, 7, 3
ATK_MAX_SAME = 2                            # K1：8 个世界里同一个基础攻击最多 2 个
SLOT_MECHS = ("charge", "guard", "ward")    # K2：原型用到的三个怪方机制指示槽
SLOT_MAX_SAME = 1                           # K2：和每个已收的世界比，同号最多 1 个
BANDS = dict(life_in_hits=(24, 34), rest_pct=(28, 42), block_x=(80, 120))   # = devworld.ECONOMY_BANDS 的 life_in_hits / rest_pct / block_pct
A_ECON = dict(life_in_hits=29, rest_pct=35, block_x=100)                    # = devworld.ECONOMY_REGISTERED
MIN_SHIFT = 0.10                            # = devworld.ECONOMY_MIN_SHIFT
PROTO_BLOCK = 45                            # 原型的盾（PROTO_TUNE m59ws2t25c_bp45w90_c48 的 block_pct）：外衣的盾 = round(45 × x / 100)
DRAW_CAP = 10000
FACT_SALT = 2500006                         # 读身份事实用的一张候选图（身份与 salt 无关）
STREAM = "economy-p13-v1"
RULES = ("keys: identity v3, ascending from 2, skipping 0/1/5/10/17; K1 at most 2 worlds per base attack (A counts); K2 the three "
         "monster mechanic indicator slots (charge, guard, ward) share at most 1 label with every accepted world (A included); K3 "
         "names_key = (key + 1) * 10^8 and the 5 card names are disjoint from every accepted world's. Economy per world and knob, "
         "stream economy-p13-v1:{key}:{knob}: life_in_hits in [24, 34], rest_pct in [28, 42], shield ratio x in [80, 120] "
         "(prototype block_pct = round(45 * x / 100)); E1 at least 10 % (min 1) from A's value (29 / 35 / 100); E2 redraw a value an "
         "earlier world took while an eligible untaken value remains; E3 shield < the weakest possible normal hit of a map enemy "
         "(_worn(round(atk * eatk_mult lo / 100))) and of the boss at attack 100 % (round(round(atk * eatk_boss_mult lo / 100) * "
         "boss_wear_pct / 100)), else redraw x (every draw recorded)")
A_NAMES = dict(vorth="attack", doln="block", tsun="dodge", kel="heal", mira="buff_mark")
A_LABELS = {"me.hp": "a3", "me.cap": "a2", "me.block": "A5", "them.hp": "b1"}   # 世界 A 的血 / 上限 / 盾 / 怪血符号（22 号文档的表；counter_noblock_score 原来写死的那几个）

# ---------------------------------------------------------------- 冻结的表（derive() 的输出；43 §1）
SURFACES = {'A': {'identity_key': 0,
       'names_key': 0,
       'economy': None,
       'facts': {'base_atk': 7,
                 'max_hp': 203,
                 'shield': 5,
                 'heal': 16,
                 'cards': {'doln': 'block', 'kel': 'heal', 'mira': 'buff_mark', 'tsun': 'dodge', 'vorth': 'attack'},
                 'labels': {'me.atk': 'a4',
                            'me.block': 'A5',
                            'me.cap': 'a2',
                            'me.carry': 'A4',
                            'me.dodge': 'A2',
                            'me.double': 'A1',
                            'me.energy': 'a1',
                            'me.hp': 'a3',
                            'me.offence': 'A7',
                            'me.poison': 'A3',
                            'me.tempo': 'A8',
                            'me.wound': 'A6',
                            'them.armour': 'b2',
                            'them.atk': 'b3',
                            'them.charge': 'B1',
                            'them.guard': 'B2',
                            'them.hp': 'b1',
                            'them.mark': 'B3',
                            'them.mimic': 'B4',
                            'them.ward': 'B5'},
                 'weakest_map_hit': 6,
                 'weakest_boss_hit': 6}},
 'k2': {'identity_key': 2,
        'identity_version': 3,
        'names_key': 300000000,
        'economy': {'life_in_hits': 24, 'rest_pct': 40, 'block_x': 88, 'block_pct': 40},
        'draws': {'life_in_hits': [[29, 'E1 too close to A'], [24, 'accepted']],
                  'rest_pct': [[37, 'E1 too close to A'], [34, 'E1 too close to A'], [40, 'accepted']],
                  'block_x': [[114, 'E3 shield 5 >= weakest hit 5'],
                              [109, 'E1 too close to A'],
                              [119, 'E3 shield 5 >= weakest hit 5'],
                              [94, 'E1 too close to A'],
                              [111, 'E3 shield 5 >= weakest hit 5'],
                              [104, 'E1 too close to A'],
                              [114, 'E3 shield 5 >= weakest hit 5'],
                              [108, 'E1 too close to A'],
                              [95, 'E1 too close to A'],
                              [98, 'E1 too close to A'],
                              [103, 'E1 too close to A'],
                              [110, 'E3 shield 5 >= weakest hit 5'],
                              [88, 'accepted']]},
        'facts': {'base_atk': 6,
                  'max_hp': 144,
                  'shield': 4,
                  'heal': 12,
                  'cards': {'daivous': 'block', 'fasjeim': 'dodge', 'kogouk': 'heal', 'laisjul': 'attack', 'studral': 'buff_mark'},
                  'labels': {'me.atk': 'a1',
                             'me.block': 'A7',
                             'me.cap': 'a4',
                             'me.carry': 'A5',
                             'me.dodge': 'A3',
                             'me.double': 'A6',
                             'me.energy': 'a2',
                             'me.hp': 'a3',
                             'me.offence': 'A4',
                             'me.poison': 'A8',
                             'me.tempo': 'A2',
                             'me.wound': 'A1',
                             'them.armour': 'b2',
                             'them.atk': 'b1',
                             'them.charge': 'B1',
                             'them.guard': 'B5',
                             'them.hp': 'b3',
                             'them.mark': 'B3',
                             'them.mimic': 'B4',
                             'them.ward': 'B2'},
                  'weakest_map_hit': 5,
                  'weakest_boss_hit': 5}},
 'k3': {'identity_key': 3,
        'identity_version': 3,
        'names_key': 400000000,
        'economy': {'life_in_hits': 33, 'rest_pct': 31, 'block_x': 83, 'block_pct': 37},
        'draws': {'life_in_hits': [[33, 'accepted']],
                  'rest_pct': [[31, 'accepted']],
                  'block_x': [[95, 'E1 too close to A'],
                              [102, 'E1 too close to A'],
                              [118, 'E3 shield 4 >= weakest hit 4'],
                              [106, 'E1 too close to A'],
                              [83, 'accepted']]},
        'facts': {'base_atk': 5,
                  'max_hp': 165,
                  'shield': 3,
                  'heal': 11,
                  'cards': {'firmaen': 'block', 'jultoth': 'attack', 'mulkoul': 'heal', 'rungis': 'buff_mark', 'simha': 'dodge'},
                  'labels': {'me.atk': 'a1',
                             'me.block': 'A4',
                             'me.cap': 'a4',
                             'me.carry': 'A6',
                             'me.dodge': 'A8',
                             'me.double': 'A2',
                             'me.energy': 'a3',
                             'me.hp': 'a2',
                             'me.offence': 'A1',
                             'me.poison': 'A5',
                             'me.tempo': 'A3',
                             'me.wound': 'A7',
                             'them.armour': 'b3',
                             'them.atk': 'b2',
                             'them.charge': 'B2',
                             'them.guard': 'B1',
                             'them.hp': 'b1',
                             'them.mark': 'B3',
                             'them.mimic': 'B4',
                             'them.ward': 'B5'},
                  'weakest_map_hit': 4,
                  'weakest_boss_hit': 4}},
 'k4': {'identity_key': 4,
        'identity_version': 3,
        'names_key': 500000000,
        'economy': {'life_in_hits': 26, 'rest_pct': 28, 'block_x': 87, 'block_pct': 39},
        'draws': {'life_in_hits': [[26, 'accepted']],
                  'rest_pct': [[28, 'accepted']],
                  'block_x': [[106, 'E1 too close to A'], [117, 'E3 shield 6 >= weakest hit 6'], [87, 'accepted']]},
        'facts': {'base_atk': 7,
                  'max_hp': 182,
                  'shield': 4,
                  'heal': 15,
                  'cards': {'gretrir': 'dodge', 'kaigrai': 'block', 'neiren': 'heal', 'taidra': 'attack', 'zaivre': 'buff_mark'},
                  'labels': {'me.atk': 'a1',
                             'me.block': 'A7',
                             'me.cap': 'a4',
                             'me.carry': 'A4',
                             'me.dodge': 'A5',
                             'me.double': 'A6',
                             'me.energy': 'a2',
                             'me.hp': 'a3',
                             'me.offence': 'A2',
                             'me.poison': 'A8',
                             'me.tempo': 'A3',
                             'me.wound': 'A1',
                             'them.armour': 'b3',
                             'them.atk': 'b2',
                             'them.charge': 'B5',
                             'them.guard': 'B2',
                             'them.hp': 'b1',
                             'them.mark': 'B1',
                             'them.mimic': 'B4',
                             'them.ward': 'B3'},
                  'weakest_map_hit': 6,
                  'weakest_boss_hit': 6}},
 'k6': {'identity_key': 6,
        'identity_version': 3,
        'names_key': 700000000,
        'economy': {'life_in_hits': 25, 'rest_pct': 42, 'block_x': 80, 'block_pct': 36},
        'draws': {'life_in_hits': [[29, 'E1 too close to A'], [26, 'E2 taken by an earlier world'], [25, 'accepted']],
                  'rest_pct': [[37, 'E1 too close to A'], [32, 'E1 too close to A'], [40, 'E2 taken by an earlier world'], [42, 'accepted']],
                  'block_x': [[87, 'E2 taken by an earlier world'],
                              [106, 'E1 too close to A'],
                              [96, 'E1 too close to A'],
                              [113, 'E3 shield 4 >= weakest hit 4'],
                              [116, 'E3 shield 4 >= weakest hit 4'],
                              [92, 'E1 too close to A'],
                              [94, 'E1 too close to A'],
                              [97, 'E1 too close to A'],
                              [80, 'accepted']]},
        'facts': {'base_atk': 5,
                  'max_hp': 125,
                  'shield': 3,
                  'heal': 7,
                  'cards': {'daedri': 'block', 'faedei': 'heal', 'grakhar': 'attack', 'khaekde': 'buff_mark', 'skiston': 'dodge'},
                  'labels': {'me.atk': 'a4',
                             'me.block': 'A1',
                             'me.cap': 'a1',
                             'me.carry': 'A5',
                             'me.dodge': 'A3',
                             'me.double': 'A4',
                             'me.energy': 'a3',
                             'me.hp': 'a2',
                             'me.offence': 'A8',
                             'me.poison': 'A6',
                             'me.tempo': 'A7',
                             'me.wound': 'A2',
                             'them.armour': 'b3',
                             'them.atk': 'b1',
                             'them.charge': 'B3',
                             'them.guard': 'B4',
                             'them.hp': 'b2',
                             'them.mark': 'B5',
                             'them.mimic': 'B2',
                             'them.ward': 'B1'},
                  'weakest_map_hit': 4,
                  'weakest_boss_hit': 4}},
 'k9': {'identity_key': 9,
        'identity_version': 3,
        'names_key': 1000000000,
        'economy': {'life_in_hits': 32, 'rest_pct': 39, 'block_x': 116, 'block_pct': 52},
        'draws': {'life_in_hits': [[33, 'E2 taken by an earlier world'],
                                   [30, 'E1 too close to A'],
                                   [30, 'E1 too close to A'],
                                   [33, 'E2 taken by an earlier world'],
                                   [33, 'E2 taken by an earlier world'],
                                   [29, 'E1 too close to A'],
                                   [27, 'E1 too close to A'],
                                   [32, 'accepted']],
                  'rest_pct': [[39, 'accepted']],
                  'block_x': [[116, 'accepted']]},
        'facts': {'base_atk': 9,
                  'max_hp': 288,
                  'shield': 7,
                  'heal': 17,
                  'cards': {'diathmi': 'dodge', 'geste': 'attack', 'joumni': 'buff_mark', 'skurlin': 'heal', 'zeitrun': 'block'},
                  'labels': {'me.atk': 'a1',
                             'me.block': 'A5',
                             'me.cap': 'a3',
                             'me.carry': 'A2',
                             'me.dodge': 'A3',
                             'me.double': 'A7',
                             'me.energy': 'a4',
                             'me.hp': 'a2',
                             'me.offence': 'A1',
                             'me.poison': 'A6',
                             'me.tempo': 'A4',
                             'me.wound': 'A8',
                             'them.armour': 'b3',
                             'them.atk': 'b2',
                             'them.charge': 'B2',
                             'them.guard': 'B5',
                             'them.hp': 'b1',
                             'them.mark': 'B4',
                             'them.mimic': 'B3',
                             'them.ward': 'B1'},
                  'weakest_map_hit': 8,
                  'weakest_boss_hit': 8}},
 'k13': {'identity_key': 13,
         'identity_version': 3,
         'names_key': 1400000000,
         'economy': {'life_in_hits': 34, 'rest_pct': 41, 'block_x': 84, 'block_pct': 38},
         'draws': {'life_in_hits': [[33, 'E2 taken by an earlier world'], [34, 'accepted']],
                   'rest_pct': [[39, 'E2 taken by an earlier world'],
                                [33, 'E1 too close to A'],
                                [28, 'E2 taken by an earlier world'],
                                [32, 'E1 too close to A'],
                                [31, 'E2 taken by an earlier world'],
                                [41, 'accepted']],
                   'block_x': [[84, 'accepted']]},
         'facts': {'base_atk': 9,
                   'max_hp': 306,
                   'shield': 5,
                   'heal': 15,
                   'cards': {'biatru': 'dodge', 'fiakmi': 'buff_mark', 'limfin': 'heal', 'noulbal': 'attack', 'suhias': 'block'},
                   'labels': {'me.atk': 'a3',
                              'me.block': 'A2',
                              'me.cap': 'a2',
                              'me.carry': 'A8',
                              'me.dodge': 'A7',
                              'me.double': 'A4',
                              'me.energy': 'a4',
                              'me.hp': 'a1',
                              'me.offence': 'A5',
                              'me.poison': 'A6',
                              'me.tempo': 'A1',
                              'me.wound': 'A3',
                              'them.armour': 'b1',
                              'them.atk': 'b3',
                              'them.charge': 'B4',
                              'them.guard': 'B2',
                              'them.hp': 'b2',
                              'them.mark': 'B5',
                              'them.mimic': 'B3',
                              'them.ward': 'B1'},
                   'weakest_map_hit': 8,
                   'weakest_boss_hit': 8}},
 'k15': {'identity_key': 15,
         'identity_version': 3,
         'names_key': 1600000000,
         'economy': {'life_in_hits': 32, 'rest_pct': 29, 'block_x': 85, 'block_pct': 38},
         'draws': {'life_in_hits': [[28, 'E1 too close to A'], [28, 'E1 too close to A'], [31, 'E1 too close to A'], [32, 'accepted']],
                   'rest_pct': [[35, 'E1 too close to A'], [41, 'E2 taken by an earlier world'], [36, 'E1 too close to A'], [29, 'accepted']],
                   'block_x': [[114, 'E3 shield 5 >= weakest hit 5'],
                               [108, 'E1 too close to A'],
                               [100, 'E1 too close to A'],
                               [94, 'E1 too close to A'],
                               [115, 'E3 shield 5 >= weakest hit 5'],
                               [115, 'E3 shield 5 >= weakest hit 5'],
                               [97, 'E1 too close to A'],
                               [85, 'accepted']]},
         'facts': {'base_atk': 6,
                   'max_hp': 192,
                   'shield': 4,
                   'heal': 8,
                   'cards': {'jemfi': 'attack', 'kaimlar': 'dodge', 'leibrul': 'block', 'skumjar': 'heal', 'trovan': 'buff_mark'},
                   'labels': {'me.atk': 'a4',
                              'me.block': 'A6',
                              'me.cap': 'a2',
                              'me.carry': 'A8',
                              'me.dodge': 'A5',
                              'me.double': 'A4',
                              'me.energy': 'a1',
                              'me.hp': 'a3',
                              'me.offence': 'A2',
                              'me.poison': 'A1',
                              'me.tempo': 'A7',
                              'me.wound': 'A3',
                              'them.armour': 'b3',
                              'them.atk': 'b1',
                              'them.charge': 'B5',
                              'them.guard': 'B1',
                              'them.hp': 'b2',
                              'them.mark': 'B4',
                              'them.mimic': 'B3',
                              'them.ward': 'B2'},
                   'weakest_map_hit': 5,
                   'weakest_boss_hit': 5}}}
ORDER_V1 = ('A', 'k2', 'k3', 'k4', 'k6', 'k9', 'k13', 'k15')       # 43 §1 挑出来的（derive() 重算的就是这一份）
ORDER = ORDER_V1

# ---------------------------------------------------------------- 修订 1（43 号文档 §10，看过第 2 步的数据之后加；用户 11-07「ok」）
# 平衡规则：240 张候选在外衣下量出的 R1v2 D 中位 ∈ [0.465, 0.585]（A 的 0.525 ± 0.06）。A、k3、k13、k15 留着；k2、k4、k6、k9 换掉：
# 从键 16 起接着抽（K1–K3、E1–E3 只对已收的外衣算），预筛 = 血量预算 ÷ 基础攻击 ∈ [65.4, 104.1]（已收的 [72.7, 94.6] 两头放宽 10 %；只省时间）。
# 抽出来、量过的外衣冻结在 scripts/proto_worlds_amend1.json（surfaces：外衣表；tried：每个试过的键；order：收齐之后的世界次序）。
AMEND1_FILE = pathlib.Path(__file__).resolve().parent / "proto_worlds_amend1.json"
AMEND1_KEEP = ("A", "k3", "k13", "k15")
AMEND1_REPLACED = ("k2", "k4", "k6", "k9")
AMEND1_SLOTS = (2, 4, 5, 6)                  # 收下的新外衣依次顶替的世界
AMEND1_START = 16
BALANCE = (0.465, 0.585)
PREFILTER = (65.4, 104.1)
if AMEND1_FILE.exists():
    _a1 = json.loads(AMEND1_FILE.read_text())
    for _n, _s in _a1.get("surfaces", {}).items():
        assert _n not in SURFACES, _n
        SURFACES[_n] = _s
    if _a1.get("order"):
        ORDER = tuple(_a1["order"])

# ---------------------------------------------------------------- 修订 5（43 号文档 §16，看过包 v5 的总览之后加；用户 11-07「重新抽」）
# D1 任意两个世界的最大血量不同；D2 任意两个世界的（基础攻击、最大血量、盾、治疗）不全相同。只换世界 6（k62，和 k3 同血 165）；
# 从键 63 起抽（其余规则照旧，「已收的」= 另外 7 个）。抽出来、量过的外衣冻结在 scripts/proto_worlds_amend5.json（surfaces / tried / order）。
AMEND5_FILE = pathlib.Path(__file__).resolve().parent / "proto_worlds_amend5.json"
AMEND5_REPLACED, AMEND5_SLOT, AMEND5_START = "k62", 6, 63
if AMEND5_FILE.exists():
    _a5 = json.loads(AMEND5_FILE.read_text())
    for _n, _s in _a5.get("surfaces", {}).items():
        assert _n not in SURFACES, _n
        SURFACES[_n] = _s
    if _a5.get("order"):
        ORDER = tuple(_a5["order"])
# 修订 5b（43 号文档 §17，看过修订 5 的抽签之后加；用户「重新」「ok」）：D3 攻击和盾都相同的两个世界，最大血量至少差 10 %。k79 作废，从键 80 起接着抽。
AMEND5B_FILE = pathlib.Path(__file__).resolve().parent / "proto_worlds_amend5b.json"
AMEND5B_START, D3_MIN_HP_GAP = 80, 0.10
if AMEND5B_FILE.exists():
    _a5b = json.loads(AMEND5B_FILE.read_text())
    for _n, _s in _a5b.get("surfaces", {}).items():
        assert _n not in SURFACES, _n
        SURFACES[_n] = _s
    if _a5b.get("order"):
        ORDER = tuple(_a5b["order"])


def distinct_problems(facts, accepted, d3=False):
    """修订 5 的 D1 / D2（d3=True 另加修订 5b 的 D3）：facts（候选外衣的 facts）对 accepted（外衣名）逐个比；返回不过的原因（空 = 过）。"""
    out = []
    for n in accepted:
        f = SURFACES[n]["facts"]
        if f["max_hp"] == facts["max_hp"]:
            out.append(f"D1 max HP {facts['max_hp']} equals {n}")
        if all(f[k] == facts[k] for k in ("base_atk", "max_hp", "shield", "heal")):
            out.append(f"D2 (attack, HP, shield, heal) equals {n}")
        if d3 and f["base_atk"] == facts["base_atk"] and f["shield"] == facts["shield"] \
                and abs(f["max_hp"] - facts["max_hp"]) / min(f["max_hp"], facts["max_hp"]) < D3_MIN_HP_GAP:
            out.append(f"D3 same attack {facts['base_atk']} and shield {facts['shield']} as {n}, HP {facts['max_hp']} vs {f['max_hp']} (< 10 % apart)")
    return out


def surface(name):
    if name not in SURFACES:
        raise ValueError(f"PROTO_WORLD={name!r}: only {tuple(SURFACES)}")
    return SURFACES[name]


def apply(name, TUNING):
    """把外衣写进 TUNING（A：什么也不写）。block_pct 是绝对值（原型尺度）。"""
    s = surface(name)
    if name == "A":
        return
    TUNING["identity_key"] = s["identity_key"]
    TUNING["identity_version"] = s["identity_version"]
    TUNING["names_key"] = s["names_key"]
    TUNING["life_in_hits"] = s["economy"]["life_in_hits"]
    TUNING["rest_pct"] = s["economy"]["rest_pct"]
    TUNING["block_pct"] = s["economy"]["block_pct"]


KEYS_WRITTEN = ("identity_key", "identity_version", "names_key", "life_in_hits", "rest_pct", "block_pct")


def describe(name):
    """记录用（只在非 A 时进 settings()）：外衣的键、经济、事实、规则版本。"""
    s = surface(name)
    return dict(module=VERSION, name=name, identity_key=s["identity_key"], identity_version=s.get("identity_version"),
                names_key=s["names_key"], economy=s["economy"], facts=s.get("facts"), written_to_tuning=list(KEYS_WRITTEN),
                written="by antagonist_proto.setup() after the tuning overrides (PROTO_TUNE), before any map is built; restored when the world is A")


# ---------------------------------------------------------------- 修订 6：去掉治疗、血量补回（43 §19；2026-11-09，PROTO_HEAL=off）
# 只被 antagonist_proto 在 PROTO_HEAL=off 时读；默认（on）下这一段一个也不被调用，别的输出逐字不变。
HEALOFF_VERSION = "heal-off-v1-2026-11-09"
HEALOFF_ORDER = ("A", "k19", "k3", "k21", "k42", "k82", "k13", "k15")   # 包 v6 的世界顺序 1→8（43 §18）；规则 4 按这个顺序让后面的世界让路
HEALOFF_CARDS = 3                                                       # 原来每条命的治疗张数（core camp.STARTING_PILE["heal"]）


def _healoff_ok(a, sh, m, accepted):
    for a2, sh2, m2 in accepted:
        if m == m2:
            return False
        if a == a2 and sh == sh2 and abs(m - m2) / min(m, m2) < D3_MIN_HP_GAP:
            return False
    return True


def healoff_table():
    """43 §19 的推算：每个世界 dict(max_hp=M, heal=h, rest_pct=r, max_hp_new=M′, adjust, rest_pct_new=r′, rest_each, rest_each_new)。
    M′ = M + 3h，再按规则 4（世界顺序 1→8，与前面冲突就改动最少的整数，先 −1 再 +1 …）满足 D1、D3；
    r′ = 满足 floor(M′·r′/100) ≤ floor(M·r/100) 的最大整数（规则 5）。"""
    out, accepted = {}, []
    for n in HEALOFF_ORDER:
        s = surface(n)
        f = s["facts"]
        r = (s.get("economy") or A_ECON)["rest_pct"]
        m, h, a, sh = f["max_hp"], f["heal"], f["base_atk"], f["shield"]
        base = m + HEALOFF_CARDS * h
        for d in [0] + [x for k in range(1, 100) for x in (-k, k)]:
            if _healoff_ok(a, sh, base + d, accepted):
                break
        else:
            raise RuntimeError(f"heal-off: no max HP near {base} satisfies D1/D3 for {n}")
        m2 = base + d
        accepted.append((a, sh, m2))
        each = m * r // 100
        r2 = max(x for x in range(1, 101) if m2 * x // 100 <= each)
        out[n] = dict(max_hp=m, heal=h, rest_pct=r, max_hp_new=m2, adjust=d, rest_pct_new=r2, rest_each=each, rest_each_new=m2 * r2 // 100)
    return out


def healoff(name):
    """一个世界的修订 6 数值（healoff_table 的一行）；不在包 v6 的 8 个世界里就拒绝。"""
    t = healoff_table()
    if name not in t:
        raise ValueError(f"PROTO_HEAL=off is defined only for the pack-v6 worlds {HEALOFF_ORDER}, not {name!r}")
    return t[name]


def world_of_record(rec):
    return ((rec or {}).get("proto") or {}).get("world", "A")


def labels(name):
    """血 / 上限 / 盾的符号（读记录的脚本用）。A = 原来写死的那三个。"""
    if name == "A":
        return dict(A_LABELS)
    f = surface(name)["facts"]["labels"]
    return {k: f[k] for k in A_LABELS}


def card_kinds(name):
    """牌名 → 牌种（读记录的脚本的后备）。A = 原来写死的那一组。"""
    if name == "A":
        return dict(A_NAMES)
    return dict(surface(name)["facts"]["cards"])


# ---------------------------------------------------------------- 按规则重算（候选 v3c1 环境，不设 PROTO_WORLD）
def _need(knob):
    return max(1, round(A_ECON[knob] * MIN_SHIFT))


def _eligible(knob):
    lo, hi = BANDS[knob]
    return [x for x in range(lo, hi + 1) if abs(x - A_ECON[knob]) >= _need(knob)]


def _facts(key, econ):
    """在原型的 TUNING 下（调用方装好 setup()）临时写这个外衣、建一张图、读身份事实；写过的键还原。"""
    import antagonist_proto as ap
    from adventure import TUNING
    keep = {k: TUNING[k] for k in KEYS_WRITTEN}
    try:
        if key:
            TUNING.update(identity_key=key, identity_version=IDENTITY_VERSION, names_key=(key + 1) * 10 ** 8,
                          life_in_hits=econ["life_in_hits"], rest_pct=econ["rest_pct"], block_pct=econ["block_pct"])
        run = ap.build(FACT_SALT)
        lab = {f"{s}.{p}": run.layout.L(s, p) for s, p in sorted(run.layout.label)}
        cards = {n: c.kind for n, c in sorted(run.deck.items())}
        amount = {c.kind: c.amount for c in run.deck.values()}
        atk = run.base_atk
        lo = TUNING["eatk_mult"][0]
        map_min = max(1, round(max(1, round(atk * lo / 100)) * TUNING["wear_pct"] / 100))
        boss_min = max(1, round(max(1, round(atk * TUNING["eatk_boss_mult"][0] / 100)) * TUNING["boss_wear_pct"] / 100))
        assert TUNING["teach_atk_pct"] == 0 and TUNING["test_atk_pct"] == 0 and not TUNING["teach_atk_by"] and not TUNING["test_atk_by"]
        return dict(base_atk=atk, max_hp=run.max_hp, shield=amount["block"], heal=amount["heal"], cards=cards, labels=lab,
                    weakest_map_hit=map_min, weakest_boss_hit=boss_min)
    finally:
        TUNING.update(keep)


def derive():
    import devworld
    out = {"A": dict(identity_key=0, names_key=0, economy=None)}
    fa = _facts(0, None)
    taken_slots = [tuple(fa["labels"][f"them.{m}"] for m in SLOT_MECHS)]
    taken_atk = [fa["base_atk"]]
    taken_names = [set(fa["cards"])]
    taken_econ = {k: [] for k in BANDS}
    trace = []
    key = KEY_START
    order = ["A"]
    while len(order) < 1 + N_NEW:
        if key in EARLIER_KEYS:
            key += 1
            continue
        idf = devworld.identity_facts(key, IDENTITY_VERSION)
        slots = tuple(idf["labels"][("them", m)] for m in SLOT_MECHS)
        why = None
        if taken_atk.count(idf["atk"]) >= ATK_MAX_SAME:
            why = f"K1 base attack {idf['atk']} already used {ATK_MAX_SAME} times"
        elif any(sum(a == b for a, b in zip(slots, t)) > SLOT_MAX_SAME for t in taken_slots):
            why = f"K2 slots {slots} share more than {SLOT_MAX_SAME} with an accepted world"
        if why is None:
            econ, draws = {}, {}
            for knob in ("life_in_hits", "rest_pct", "block_x"):
                rng = random.Random(f"{STREAM}:{key}:{knob}")
                elig = _eligible(knob)
                draws[knob] = []
                for _ in range(DRAW_CAP):
                    x = rng.randint(*BANDS[knob])
                    if abs(x - A_ECON[knob]) < _need(knob):
                        draws[knob].append([x, "E1 too close to A"]); continue
                    if x in taken_econ[knob] and any(v not in taken_econ[knob] for v in elig):
                        draws[knob].append([x, "E2 taken by an earlier world"]); continue
                    if knob == "block_x":
                        e = dict(econ, block_x=x, block_pct=round(PROTO_BLOCK * x / 100))
                        f = _facts(key, e)
                        if not f["shield"] < min(f["weakest_map_hit"], f["weakest_boss_hit"]):
                            draws[knob].append([x, f"E3 shield {f['shield']} >= weakest hit {min(f['weakest_map_hit'], f['weakest_boss_hit'])}"]); continue
                    draws[knob].append([x, "accepted"])
                    econ[knob] = x
                    break
                else:
                    raise SystemExit(f"key {key}: {knob} not drawn in {DRAW_CAP}")
            econ["block_pct"] = round(PROTO_BLOCK * econ["block_x"] / 100)
            f = _facts(key, econ)
            if set(f["cards"]) & set().union(*taken_names):
                why = f"K3 card names {sorted(f['cards'])} clash with an accepted world"
        if why is not None:
            trace.append(dict(key=key, accepted=False, why=why))
            key += 1
            continue
        name = f"k{key}"
        out[name] = dict(identity_key=key, identity_version=IDENTITY_VERSION, names_key=(key + 1) * 10 ** 8, economy=econ, draws=draws, facts=f)
        trace.append(dict(key=key, accepted=True))
        order.append(name)
        taken_slots.append(slots); taken_atk.append(f["base_atk"]); taken_names.append(set(f["cards"]))
        for k in BANDS:
            taken_econ[k].append(econ[k])
        key += 1
    out["A"]["facts"] = fa
    return out, tuple(order), trace


def next_candidate(accepted, key):
    """修订 1：从 key 起找下一个过 K1–K3 的键，按 §1 的流与 E1–E3 抽经济（只对 accepted 里的外衣算「已用」）。
    返回 (候选外衣 dict, 下一个要试的键, 跳过的键的记录)。调用方装好原型的 setup()（候选 v3c1，不设 PROTO_WORLD）。"""
    import devworld
    acc = [SURFACES[n] for n in accepted]
    taken_slots = [tuple(a["facts"]["labels"][f"them.{m}"] for m in SLOT_MECHS) for a in acc]
    taken_atk = [a["facts"]["base_atk"] for a in acc]
    taken_names = [set(a["facts"]["cards"]) for a in acc]
    taken_econ = {k: [a["economy"][k] for a in acc if a["economy"]] for k in BANDS}
    skipped = []
    while True:
        if key in EARLIER_KEYS or f"k{key}" in SURFACES:
            skipped.append(dict(key=key, why="used by an earlier world / already tried")); key += 1; continue
        idf = devworld.identity_facts(key, IDENTITY_VERSION)
        slots = tuple(idf["labels"][("them", m)] for m in SLOT_MECHS)
        if taken_atk.count(idf["atk"]) >= ATK_MAX_SAME:
            skipped.append(dict(key=key, why=f"K1 base attack {idf['atk']} already used {ATK_MAX_SAME} times by accepted surfaces")); key += 1; continue
        if any(sum(a == b for a, b in zip(slots, t)) > SLOT_MAX_SAME for t in taken_slots):
            skipped.append(dict(key=key, why=f"K2 slots {slots} share more than {SLOT_MAX_SAME} with an accepted surface")); key += 1; continue
        econ, draws = {}, {}
        for knob in ("life_in_hits", "rest_pct", "block_x"):
            rng = random.Random(f"{STREAM}:{key}:{knob}")
            elig = _eligible(knob)
            draws[knob] = []
            for _ in range(DRAW_CAP):
                x = rng.randint(*BANDS[knob])
                if abs(x - A_ECON[knob]) < _need(knob):
                    draws[knob].append([x, "E1 too close to A"]); continue
                if x in taken_econ[knob] and any(v not in taken_econ[knob] for v in elig):
                    draws[knob].append([x, "E2 taken by an accepted surface"]); continue
                if knob == "block_x":
                    e = dict(econ, block_x=x, block_pct=round(PROTO_BLOCK * x / 100))
                    f = _facts(key, e)
                    if not f["shield"] < min(f["weakest_map_hit"], f["weakest_boss_hit"]):
                        draws[knob].append([x, f"E3 shield {f['shield']} >= weakest hit {min(f['weakest_map_hit'], f['weakest_boss_hit'])}"]); continue
                draws[knob].append([x, "accepted"])
                econ[knob] = x
                break
            else:
                raise SystemExit(f"key {key}: {knob} not drawn in {DRAW_CAP}")
        econ["block_pct"] = round(PROTO_BLOCK * econ["block_x"] / 100)
        f = _facts(key, econ)
        if set(f["cards"]) & set().union(*taken_names):
            skipped.append(dict(key=key, why=f"K3 card names clash with an accepted surface")); key += 1; continue
        return dict(identity_key=key, identity_version=IDENTITY_VERSION, names_key=(key + 1) * 10 ** 8, economy=econ, draws=draws, facts=f), key + 1, skipped


def budget_ratio(key, econ, salts):
    """修订 1 的预筛：这个外衣下 salts 每张图的 map_difficulty B 的中位数 ÷ 基础攻击。"""
    import statistics, antagonist_proto as ap, map_difficulty as md
    from adventure import TUNING
    keep = {k: TUNING[k] for k in KEYS_WRITTEN}
    try:
        TUNING.update(identity_key=key, identity_version=IDENTITY_VERSION, names_key=(key + 1) * 10 ** 8,
                      life_in_hits=econ["life_in_hits"], rest_pct=econ["rest_pct"], block_pct=econ["block_pct"])
        Bs, atk = [], None
        for s in salts:
            run = ap.build(s)
            Bs.append(md._budget(run)["B"]); atk = run.base_atk
        return statistics.median(Bs) / atk
    finally:
        TUNING.update(keep)


def main(argv):
    if argv[:1] != ["derive"]:
        print(__doc__)
        return
    for p in (str(ROOT / "core"), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import antagonist_proto as ap
    if ap.WORLD != "A":
        raise SystemExit("run derive without PROTO_WORLD")
    ap.setup()
    got, order, trace = derive()
    frozen = {k: v for k, v in SURFACES.items()}
    frozen = {k: SURFACES[k] for k in ORDER_V1}
    same = json.dumps(got, sort_keys=True) == json.dumps(frozen, sort_keys=True) and order == ORDER_V1
    print(json.dumps(dict(version=VERSION, rules=RULES, order=order, trace=trace, surfaces=got, equal_to_frozen=same), ensure_ascii=False, indent=1))
    if "--write" not in argv and not same:
        sys.exit(3)


if __name__ == "__main__":
    main(sys.argv[1:])
