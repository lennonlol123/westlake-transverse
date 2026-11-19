"""The tuning bench. Every numeric question goes through here.

Simplified hand-written models have twice given the exact opposite answer --
both times by assuming an unlimited hand, which made blocking and dodging look
worthless when in the real engine they are the difference between 21% and 68%
clear rate. Draw limits are not a detail; they are the reason defence is worth
its energy. So nothing is decided from a model: every number below comes from
running the actual fight loop over many decks.

    compare(seeds)                       how the policies stack up
    sweep("pierce_off", [1, 2, 3])       one knob against all policies
    by_boss(seeds)                       discrimination per boss combination
"""
from __future__ import annotations

import contextlib
import statistics

import adventure
from adventure import Run, TUNING, scaled


# ---------------------------------------------------------------- policies

def _pol_rush(f, r, kinds):
    if f.can_play(kinds["attack"]): return kinds["attack"]
    return None


def _pol_block(f, r, kinds):
    if f.can_play(kinds["attack"]): return kinds["attack"]
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


def _burst(f, kinds):
    """Against armour a plain hit lands for almost nothing, so the double has to
    go up first and the attack has to follow it."""
    if not f.state[("me", "double")] and f.can_play(kinds["buff_mark"]):
        return kinds["buff_mark"]
    return kinds["attack"] if f.can_play(kinds["attack"]) else None


def _pol_smart(f, r, kinds):
    """Knows what each monster needs: dodge the wind-up, burst the armour, never
    stack block against a piercer, block everything else."""
    big = ("charge" in f.parts
           and f.state[("them", "charge")] >= f.enemy.charge_max)
    if big and f.can_play(kinds["dodge"]): return kinds["dodge"]
    if "armour" in f.parts:
        c = _burst(f, kinds)
        if c: return c
    elif f.can_play(kinds["attack"]):
        return kinds["attack"]
    if "pierce" in f.parts or "regen" in f.parts:
        return None
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


def _pol_no_armour(f, r, kinds):
    """Everything except the armour: keeps chipping at the one enemy that eats
    single hits whole."""
    big = ("charge" in f.parts
           and f.state[("them", "charge")] >= f.enemy.charge_max)
    if big and f.can_play(kinds["dodge"]): return kinds["dodge"]
    if f.can_play(kinds["attack"]): return kinds["attack"]
    if "pierce" in f.parts or "regen" in f.parts: return None
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


def _pol_only_charge(f, r, kinds):
    """Learned the wind-up, never worked out the piercer -- gpt-5.5's profile on
    seed 4400. Blocks against everything, including the enemy that ignores it."""
    big = ("charge" in f.parts
           and f.state[("them", "charge")] >= f.enemy.charge_max)
    if big and f.can_play(kinds["dodge"]): return kinds["dodge"]
    if f.can_play(kinds["attack"]): return kinds["attack"]
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


def _pol_only_pierce(f, r, kinds):
    """Mirror image: knows not to block a piercer, never dodges the wind-up."""
    if f.can_play(kinds["attack"]): return kinds["attack"]
    if "pierce" in f.parts or "regen" in f.parts: return None
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


def _pol_no_regen(f, r, kinds):
    """Everything except the regenerator: still stacks block against the one
    enemy that heals faster than a halved output can kill it."""
    big = ("charge" in f.parts
           and f.state[("them", "charge")] >= f.enemy.charge_max)
    if big and f.can_play(kinds["dodge"]): return kinds["dodge"]
    if f.can_play(kinds["attack"]): return kinds["attack"]
    if "pierce" in f.parts: return None
    if f.can_play(kinds["block"]): return kinds["block"]
    return None


POLICIES = {"rush": _pol_rush, "block": _pol_block, "smart": _pol_smart,
            "charge_only": _pol_only_charge, "pierce_only": _pol_only_pierce,
            "no_regen": _pol_no_regen, "no_armour": _pol_no_armour}
LABELS = {"rush": "只攻击", "block": "攻击+攒盾", "smart": "全懂",
          "charge_only": "只懂蓄力", "pierce_only": "只懂穿透",
          "no_regen": "只差回血", "no_armour": "只差护甲"}


# ---------------------------------------------------------------- driver

def play(seed, policy, atk_bonus=0, hp_bonus=0, heal_at=None, rest_at=None,
         reward="atk", take=None):
    """`take` is the card kind picked up after each ordinary fight. Leaving it
    None models a player who never takes a reward -- which nobody is. The card
    rewards change the draw, and the draw is what decides whether defence is
    affordable, so a bench that ignores them measures a deck no run ever has."""
    r = Run(seed)
    r.base_atk += atk_bonus
    r.max_hp += hp_bonus
    r.hp = r.max_hp
    kinds = r.by_kind
    pick = POLICIES[policy]
    # Same threshold the solvability screen uses. They drifted apart once --
    # the screen rested at 40% of max health, the bench at a flat 40 -- so the
    # screen was guaranteeing 75-88% for a policy the bench never ran, and the
    # bench reported 64%. A guarantee about a policy nobody measures is not a
    # guarantee.
    if rest_at is None:
        rest_at = r.max_hp * 0.4
    if heal_at is None:                     # same rule the screen uses
        heal_at = TUNING["heal_below"]

    def loop(f):
        t = 0
        while not f.over() and t < 40:
            while not f.over():
                if (f.state[("me", "hp")] * 100 < f.max_hp * heal_at
                        and f.can_play(kinds["heal"])):
                    f.play(kinds["heal"]); continue
                c = pick(f, r, kinds)
                if c is None or not f.play(c):
                    break
            f.end_turn(); t += 1
        return f.won()

    import random as _rnd
    node_rng = _rnd.Random(seed)
    for i, layer in enumerate(r.layers):
        j, kind = r.choose(i, node_rng, r.hp < rest_at, r.hp > r.max_hp * 0.6)
        if kind == "rest":
            r.rest("cap" if r.base_max_hp - r.max_hp >= scaled("rest_cap_pct", r.base_max_hp)
                   else "hp")
            continue
        elite = kind == "elite"
        f = r.fight_at(i, j)
        # dying early still belongs to this run's boss bucket
        if not loop(f): return 0, r.boss_behaviour
        r.absorb(f)
        if elite:
            r.apply_reward(reward)
        elif take:
            r.deck_list.append(kinds[take])
    hp_left = 0
    for f in r.boss_fights():
        if not loop(f):
            return 0, r.boss_behaviour
        r.absorb(f)
        hp_left = f.state[("me", "hp")]
    return hp_left, r.boss_behaviour


@contextlib.contextmanager
def tuned(**over):
    """Temporarily override TUNING.

    An unknown key is an error, not a new setting. Every measurement in this
    project is driven by these names, so a typo -- or a knob that has since
    been adopted and removed -- used to be a silent no-op that read exactly
    like "I set it". One sweep printed `穿透只拒绝格挡=False` in its header
    while running the opposite.
    """
    unknown = sorted(set(over) - set(TUNING))
    if unknown:
        raise KeyError(f"TUNING 里没有这些键: {unknown}")
    old = dict(TUNING)
    TUNING.update(over)
    try:
        yield
    finally:
        TUNING.clear(); TUNING.update(old)


def score(seeds, policy, **kw):
    v = [play(s, policy, **kw)[0] for s in seeds]
    return dict(hp=statistics.mean(v), clear=sum(1 for x in v if x) / len(v))


def compare(seeds=range(1, 81), **over):
    with tuned(**over):
        return {p: score(seeds, p) for p in POLICIES}


def sweep(param, values, seeds=range(1, 81), policies=("block", "smart")):
    out = {}
    for v in values:
        with tuned(**{param: v}):
            out[v] = {p: score(seeds, p) for p in policies}
    return out


def by_boss(seeds=range(1, 121), policies=("block", "smart"), **over):
    from collections import defaultdict
    agg = defaultdict(lambda: defaultdict(list))
    with tuned(**over):
        for s in seeds:
            for p in policies:
                hp, boss = play(s, p)
                key = "+".join(sorted(boss.split("+")))
                agg[key][p].append(hp)
    return {k: {p: (sum(1 for x in v if x) / len(v)) for p, v in d.items()}
            for k, d in agg.items()}


def table(res, title=""):
    if title: print(title)
    keys = list(next(iter(res.values())).keys()) if res else []
    print(f"{'':<14}" + "".join(f"{LABELS.get(k, k):>16}" for k in keys))
    print("-" * (14 + 16 * len(keys)))
    for row, d in res.items():
        cells = []
        for k in keys:
            v = d[k]
            cells.append(f"{v['hp']:.1f}血 {v['clear']:.0%}" if isinstance(v, dict)
                         else f"{v:.0%}")
        print(f"{str(row):<14}" + "".join(f"{c:>16}" for c in cells))
    print()


if __name__ == "__main__":
    table({"当前": compare()}, "三种打法（80 副牌）\n")
