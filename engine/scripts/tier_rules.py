"""Rule tiers on the hard pack (2026-11-13): one lookup for every entry point (human launcher, model world/chain runners, pack check).
hard = hard2-ward10-test3 (scripts/hard2_rules.py); hard3 = + rest r1v2x120; formal = the main study (scripts/formal_rules.py)."""
import pathlib
import hard2_rules
import hard3_rules
import formal_rules
import hard5_rules

# 11-14: each tier names its pack (formal moved to v7hard3: a seal on every map); hard / hard3 stay on v7hard2. 11-14 night: formal → v7hard4 (world 3 second swap).
DEFAULT_PACK = pathlib.Path.home() / "agii_runs/v3c1_pack/pack_v3c1_v7hard2.json"
DEFAULT_PACK_SHA256 = "2e6a44d14bbfbdb8ccad2ff667e19ff26f3623dcfecaed55c05e05a26f5ad503"

TIERS = {"hard": hard2_rules, "hard3": hard3_rules, "formal": formal_rules, "hard5": hard5_rules}


def rules_for(tier):
    return TIERS[tier]


def check(rules):
    """Frozen rest table, for tiers that have one."""
    if hasattr(rules, "check_table"):
        rules.check_table()


def pack_for(rules):
    """(pack path, frozen sha256) of a tier."""
    return getattr(rules, "PACK", DEFAULT_PACK), getattr(rules, "PACK_SHA256", DEFAULT_PACK_SHA256)


def pack_shas():
    """sha256 of every registered hard pack -> the tiers that play it."""
    out = {}
    for name, rules in TIERS.items():
        out.setdefault(pack_for(rules)[1], []).append(name)
    return out


def ward_limit(rules):
    v = rules.ENV.get("PROTO_WARDLIMIT", "off")
    return int(v) if v.isdigit() else v


def match_env(environ):
    """The tier whose PROTO_* switches the environment carries exactly (PROTO_RESTAMT absent = no table); None if none matches."""
    for name, rules in TIERS.items():
        if environ.get("PROTO_TURNCAP", "40") != rules.ENV.get("PROTO_TURNCAP", "40"):
            continue
        if all(environ.get(k) == v for k, v in rules.ENV.items()) and environ.get("PROTO_RESTAMT") == rules.ENV.get("PROTO_RESTAMT"):
            return name, rules
    return None
