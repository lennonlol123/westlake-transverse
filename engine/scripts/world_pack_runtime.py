"""Use the v7 pack's cued environment and reference measurements for every chain."""
import copy
import json
import os
from pathlib import Path

CHAIN_ENV = "AGII_CHAIN_INDEX"
V7_VERSION = "v3c1-pack-v7-2026-11-09"
V7HARD_VERSION = "v3c1-pack-v7hard-2026-11-12"   # v7 的世界 1–5、换两张图、hard 测量与 E*（scripts/pack_v7hard_build.py）
V7HARD2_VERSION = "v3c1-pack-v7hard2-2026-11-12"  # 同 v7hard 的图，考试关蓄力 len234 / 守势 irr50 下的测量与 E*（scripts/pack_v7hard2_build.py）
V7HARD3_VERSION = "v3c1-pack-v7hard3-2026-11-14"
V7HARD4_VERSION = "v3c1-pack-v7hard4-2026-11-14"  # v7hard3 的 W3 2500400 换成 2501026（scripts/pack_v7hard4_build.py）  # v7hard2 的 4 张无封印图换成有封印的、正式规则下的测量与 E*（scripts/pack_v7hard3_build.py）
STUDY_WORLD_LIMIT = 5  # Current study uses worlds 1–5; the full pack stays intact.


def chain_index(value=None):
    value = os.environ.get(CHAIN_ENV, "1") if value is None else value
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("Chain number must be a positive integer (1, 2, ...).")
    return int(value)


def select_world(spec, chain=None, cue=None):
    """Materialize env/measured; an explicit cue override is for offline diagnostics."""
    result = copy.deepcopy(spec)
    boss = result.get("boss", {})
    if "env_by_cue" not in boss:
        return result
    number = chain_index(chain)
    selected = "on" if cue is None else cue
    if selected not in ("on", "off"):
        raise ValueError("The boss cue must be on or off.")
    boss["env"] = copy.deepcopy(boss["env_by_cue"][selected])
    boss["measured"] = copy.deepcopy(boss["measured_by_cue"][selected])
    boss["cue"] = selected == "on"
    result["chain"] = dict(index=number, cue=selected,
                           cue_policy="always_on" if cue is None else "diagnostic_override")
    return result


def load_pack(path, chain=None, cue=None):
    data = json.loads(Path(path).expanduser().read_text())
    if data.get("version") in (V7_VERSION, V7HARD_VERSION, V7HARD2_VERSION, V7HARD3_VERSION, V7HARD4_VERSION):
        data["worlds"] = [select_world(w, chain, cue) for w in data["worlds"]]
    return data
