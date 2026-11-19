"""The training camp as designed: fixed cards, hidden identities.

The earlier harness generated a fresh set of arbitrary register rules each run,
which meant a player could not even know what to look for. That is not the task.
The card set is fixed and game-shaped -- attack, block, dodge, heal, and two
compound ones -- and what is randomised is which symbol maps to which card, plus
the exact numbers. NetHack, not a new physics every game.

Slots have real roles and the system evolves on its own (block clears, poison
ticks), so ending a turn without acting actually shows you something.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# slots -- roles are fixed, the player just does not know which is which
# Two tiers, split by lifetime rather than by owner. Things the traveller always
# has sit in the standing row; anything that appears, does something, and goes
# away belongs in the second row -- and an absent status shows nothing at all,
# because "not present" and "present with value zero" are different facts.
#
# Which letter denotes which property, and the order they appear in, is drawn
# fresh for every run and held fixed for its whole duration, deaths and retries
# included. Otherwise a1 is always health and half the identification problem
# has been given away for free.
STANDING_MINE_PROPS = ["hp", "cap", "atk", "energy"]
TRANSIENT_MINE_PROPS = ["block", "poison", "double", "dodge", "carry"]
# Added AFTER the shuffle, with the next free label, so every existing
# world's letters stay where they were. Appending to the list above would
# have re-permuted the row: a representation change that renames `poison`
# on four confirmed worlds is exactly what the namespaced identity stream
# exists to prevent.
EXTRA_TRANSIENT_MINE_PROPS = ["wound", "offence", "tempo"]
EXTRA_TRANSIENT_THEIRS_PROPS = ["guard", "mark", "mimic", "ward"]   # 同样追加在洗牌之后，B1 不动
STANDING_THEIRS_PROPS = ["hp", "atk", "armour"]
TRANSIENT_THEIRS_PROPS = ["charge"]
NUMERIC_PROPS = {"hp", "cap", "atk", "energy", "block", "poison", "charge",
                 "armour", "wound", "offence", "guard", "mark", "mimic", "tempo", "ward"}


class Layout:
    """One run's property-to-label assignment. Fixed for the run."""

    def __init__(self, rng: random.Random, version: int = 1):
        def assign(props, prefix):
            order = list(props)
            rng.shuffle(order)
            return {p: f"{prefix}{i+1}" for i, p in enumerate(order)}

        # numbered within each row so the display stays tidy; what varies is
        # which property lands in which position
        self.label: dict[tuple[str, str], str] = {}
        self.standing = {"me": STANDING_MINE_PROPS, "them": STANDING_THEIRS_PROPS}
        if version == 2:
            # 第 2 版（远迁移的宇宙身份）：追加的槽位也进洗牌，怪方整排 B1–B5 不再是常量。
            # 只在 identity_key 非 0 时使用，第 1 版的随机流一个字都不动。
            self.transient = {"me": TRANSIENT_MINE_PROPS + EXTRA_TRANSIENT_MINE_PROPS,
                              "them": TRANSIENT_THEIRS_PROPS + EXTRA_TRANSIENT_THEIRS_PROPS}
            for side, lower, upper in (("me", "a", "A"), ("them", "b", "B")):
                for p, l in assign(self.standing[side], lower).items():
                    self.label[(side, p)] = l
                for p, l in assign(self.transient[side], upper).items():
                    self.label[(side, p)] = l
            return
        self.transient = {"me": TRANSIENT_MINE_PROPS, "them": TRANSIENT_THEIRS_PROPS}
        for side, lower, upper in (("me", "a", "A"), ("them", "b", "B")):
            for p, l in assign(self.standing[side], lower).items():
                self.label[(side, p)] = l
            for p, l in assign(self.transient[side], upper).items():
                self.label[(side, p)] = l
        for i, p in enumerate(EXTRA_TRANSIENT_MINE_PROPS):
            self.label[("me", p)] = f"A{len(TRANSIENT_MINE_PROPS) + i + 1}"
        for i, p in enumerate(EXTRA_TRANSIENT_THEIRS_PROPS):
            self.label[("them", p)] = f"B{len(TRANSIENT_THEIRS_PROPS) + i + 1}"
        self.transient = {"me": TRANSIENT_MINE_PROPS + EXTRA_TRANSIENT_MINE_PROPS,
                          "them": TRANSIENT_THEIRS_PROPS + EXTRA_TRANSIENT_THEIRS_PROPS}

    def ordered(self, side: str, tier: str) -> list[str]:
        """Properties of one row, in this run's display order."""
        props = (self.standing if tier == "standing" else self.transient)[side]
        return sorted(props, key=lambda p: self.label[(side, p)])

    def L(self, side: str, prop: str) -> str:
        return self.label[(side, prop)]

"""Energy is what makes a turn mean anything.

Without it a "turn" is just a button that triggers end-of-turn bookkeeping, and
a player can do unlimited things before pressing it. With it, the turn becomes
the period over which a resource refills, which is also what every "each turn"
rule is anchored to. The number is shown but never named -- that it refills, and
that operations consume it, is for the player to work out."""

"""An operation that took effect must show something; only an operation that did
NOT take effect may leave the screen unchanged. Otherwise "no change" carries two
opposite meanings at once and stops being evidence. The markers are visible but
unlabelled -- you can see a state appear and vanish without being told what it is."""


# Three dodges, not two. This is the one knob that widens the gap from the top
# instead of the bottom: a brute-force line never plays the card, so the extra
# copy only dilutes its attacks, while a player who knows the wind-up gets the
# answer in hand when the wind-up actually happens. Measured over 120 decks it
# moved brute force 31% -> 17% and left informed play at 72%.
STARTING_PILE = {"attack": 3, "block": 3, "dodge": 3, "heal": 3, "buff_mark": 3}
KEEP_HAND = True    # unplayed cards carry over -- see Pile
# 10. A planned experimenter forces out every identifiable fact in 5-7 turns
# (median 6) and the curve saturates at 7, so this leaves room to fumble without
# making it free to sit through the whole thing -- which keeps LEAVE informative:
# the turn you walk out reads on whether you noticed there was nothing left to
# learn. 5 was tried and is below the floor: it cuts the block experiments from
# 56% to 15%, because testing whether block stacks needs two blocks in one turn
# and the hand only guarantees one, so a turn has to be spent holding one back.
# Guarded by check.py 6.1.
CAMP_TURNS = 10
HAND_SIZE = 5
# Both card numbers are ratios of the player's attack, so they mean the same
# thing at every run size. They were absolutes (`atk - 1` and `atk + 2..7`),
# which made the heal worth 2.4 hits at attack 5 and 1.9 at attack 8 -- the
# same card, quietly weaker, for no reason anyone chose.
#
# The 27-cell real-engine sweep put 160% on the same informed ceiling as the
# neighbouring settings, while closing the only observed >10% partial-knowledge
# leaks.  A large shield is therefore intentional: ordinary damage can be
# absorbed, while the four learned gates remain what decide a run.
BLOCK_RATIO = 160       # block = base_atk x this %
HEAL_MULT = (140, 240)  # heal drawn from this % band of base_atk
GUARANTEED = ("attack", "block")


def turns_used(camp: "Camp", budget: int = CAMP_TURNS) -> int:
    """Displayed/scored camp turns, not the next-turn cursor.

    `end_turn` advances `Camp.turn`, so finishing turn 10 leaves the cursor at
    11.  The old runners reported that cursor as eleven turns of experience.
    """
    return min(camp.turn, budget)


class Pile:
    """Draw pile / hand / discard, shared by the camp and the adventure so the
    two obey exactly the same rules.

    Unplayed cards STAY in hand and the hand is topped up to size each turn.
    Emptying it every turn made the wind-up unanswerable in practice: the slot is
    visible two turns ahead, but you could not hold the dodge for it, so knowing
    what was coming did not let you act on it and clearing came down to whether
    the card happened to be in that turn's four. Keeping the hand is the one
    change that converts understanding into execution: informed play went from
    58% to 72% while every half-informed line collapsed (brute force 21% -> 2%).

    It does NOT freeze the deck, which was the obvious worry. Two energy buys at
    most two cards, so about 2.5 are left over and 1.45 are drawn each turn, and
    97% of the deck is still seen inside one fight. (The first measurement said
    otherwise; it was counting distinct card NAMES, of which a deck has four.)

    Heal is exhausted when played --
    removed for the rest of the run rather than discarded -- which is what makes
    it scarce; everything else cycles.

    The opening hand is guaranteed to offer an attack and block so the training
    experiment can start. Later turns guarantee only an attack, leaving every
    other empty slot to the actual shuffled pile. Reapplying both guarantees
    every turn both discarded retained cards and, when two cards were retained,
    reserved every new slot for attack/block forever so a needed combo card
    could never be drawn. Dropping all guarantees instead permits a full hand of
    passive cards to stop the run permanently.
    """

    def __init__(self, names, deck, rng, hand_size=HAND_SIZE, guaranteed=GUARANTEED):
        self.deck, self.rng = deck, rng
        self.hand_size, self.guaranteed = hand_size, guaranteed
        self.draw = list(names)
        rng.shuffle(self.draw)
        self.hand, self.discard = [], []
        self._opening = True
        self.refill()

    def _kinds(self, names):
        return [self.deck[n].kind for n in names]

    def _return(self, pool, name):
        """Put a temporarily removed card back without creating a known top.

        A guarantee can exchange a newly drawn card for a required kind.  The
        displaced card used to be appended to ``draw``; because drawing uses
        ``pop()``, that made it deterministically next.  Counts are only an
        exact representation of a pile when its unseen order remains random,
        so cards returned to the draw pile are inserted at a uniform position.
        Discard order is immaterial because it is shuffled on recycle.
        """
        if pool is self.draw:
            pool.insert(self.rng.randrange(len(pool) + 1), name)
        else:
            pool.append(name)

    def refill(self):
        retained = len(self.hand)
        while len(self.hand) < self.hand_size:
            if not self.draw:
                if not self.discard:
                    break
                self.draw, self.discard = self.discard, []
                self.rng.shuffle(self.draw)
            self.hand.append(self.draw.pop())

        required = self.guaranteed if self._opening else self.guaranteed[:1]
        self._opening = False
        for kind in required:
            if kind in self._kinds(self.hand):
                continue
            replacement = source = None
            for pool in (self.draw, self.discard):
                # UNIFORM among the matching positions, not the first one.
                #
                # `next(...)` took the earliest index, and the draw pile is
                # consumed from the END, so "first match" meant "the copy buried
                # deepest" -- which pushes the remaining copies of that kind
                # toward the top and makes them likelier to be drawn soon. The
                # leftover pile is then no longer a uniformly random permutation
                # given its counts, which is exactly the assumption batch.py's
                # counts representation rests on.
                #
                # It cost 0.02 of total-variation distance on a poisoner at 183
                # health, well outside the 0.016 baseline between two scalar
                # samples, and it showed up as the scalar engine entering the
                # block-twice line more often than the batch one. Taking the
                # deepest copy was never a design decision; it was what
                # `next()` happens to return.
                hits = [i for i, n in enumerate(pool)
                        if self.deck[n].kind == kind]
                if hits:
                    replacement = pool.pop(hits[self.rng.randrange(len(hits))])
                    source = pool
                    break
            if replacement is None:
                continue
            swap = next((i for i in range(retained, len(self.hand))
                         if self.deck[self.hand[i]].kind not in required),
                        None)
            if swap is None:
                self._return(source, replacement)
                continue
            # The displaced card came from this refill's random draw. Returning
            # it uniformly preserves the exchangeability used by batch.py.
            self._return(self.draw, self.hand[swap])
            self.hand[swap] = replacement

    def play(self, name) -> bool:
        if name not in self.hand:
            return False
        self.hand.remove(name)
        if self.deck[name].kind != "heal":     # heal exhausts
            self.discard.append(name)
        return True

    def end_turn(self):
        if not KEEP_HAND:
            self.discard.extend(self.hand)
            self.hand = []
        self.refill()


@dataclass
class Card:
    kind: str
    amount: int
    cost: int = 1
    cost_known: bool = False     # shown only after you have actually paid it

    def label(self, name: str) -> str:
        """`vorth(?)` until played once, then `vorth(1)`.

        Cost is the one number on screen that would otherwise give an identity
        away for free: dodge is the only 2-cost card, so printing costs up front
        names it on sight -- and it stays named across deaths and retries, since
        the cost structure never changes even when the symbols are redrawn."""
        return f"{name}({self.cost if self.cost_known else '?'})"

    def __str__(self) -> str:
        return {
            # 揭晓时给人看。2026-10-19 起是英文，词和 GUI 原来的显示层一样（core/gui/english.json）。
            "attack":      "their health − (your attack)",
            "block":       f"your block +{self.amount}",
            "dodge":       f"immune to the next attack (costs {self.cost})",
            "heal":        f"your health +{self.amount} (nothing at full health)",
            "buff_mark":   "your next attack card deals double damage",
            "block_carry": "while you have block, it carries into the next turn",
        }[self.kind]


BASE_ATK = 6
BLOCK_AMT = 5


def sparring_hit_for(block_amt: int, rng: random.Random) -> int:
    """The sparring partner must hit HARDER than block absorbs.

    Otherwise block swallows the whole hit and looks exactly like dodge -- both
    just make health not go down, and nothing in the camp can tell them apart.
    gpt-5.5 correctly answered "not fully determined" for dodge, and the reason
    was the environment, not the model. Partial absorption is what reveals block
    to be a pool with a capacity.

    Camp health is derived from this upper bound below, so ten turns of taking
    it on the chin cannot kill the player even when the shield ratio changes."""
    return block_amt + rng.choice([1, 2])


def safe_camp_hp(block_amt: int, turns: int = CAMP_TURNS) -> int:
    """Minimum camp ceiling that survives the worst legal sparring sequence."""
    return (block_amt + 2) * turns + 1


ATK_CHOICES = (5, 6, 7, 8)            # 身份第 1、2 版的基础攻击候选（A、B 用这个，一个字不动）
ATK_CHOICES_V3 = (5, 6, 7, 8, 9)      # 第 3 版（B 之后的世界）：五个世界攻击各不相同需要至少五个值


def make_deck(rng: random.Random, atk_choices=ATK_CHOICES) -> tuple[dict[str, Card], int]:
    """Fixed card types, randomised numbers, randomised symbol assignment.

    The attack card carries no damage number of its own: it deals exactly the
    traveller's attack stat. That stat is on screen the whole time, so the one
    semantic fact the camp *can* establish is that a visible number is the source
    of the damage -- the equation is right there to be noticed. It also makes an
    attack buff later a genuine global multiplier rather than a small addend."""
    # attack / block / heal must all differ: two equal numbers on screen invite a
    # relationship that is not there, which is the same trap as block == 2*hit.
    # Rolled per run, then screened for solvability by Run. Hard relationships
    # are enforced here rather than left to the screen, because the screen only
    # measures clear rate and would happily accept a run where block is useless.
    #
    #   sparring hit > block            so camp reveals partial absorption
    #   the three numbers differ        so no two equal numbers on screen invite
    #                                   a relationship that is not there
    base_atk = rng.choice(list(atk_choices))
    block_amt = max(1, round(base_atk * BLOCK_RATIO / 100))
    lo, hi = (max(1, round(base_atk * m / 100)) for m in HEAL_MULT)
    heal_amt = rng.choice([h for h in range(lo, hi + 1)
                           if h not in (base_atk, block_amt)])
    # Scaled AFTER the heal is drawn, never before. `rng.choice` consumes a
    # number of words that depends on the length of its candidate list, and
    # that list excludes `block_amt` -- so scaling the shield up front would
    # change which heal values are legal, shift the stream, and hand back a
    # different deck, different symbol names and a different world. The
    # comparison would then be between worlds, not between shield values. Same
    # rule `_worn` obeys: scale after the draw.
    #
    # Imported here rather than at the top because `adventure` imports this
    # module; by the time any deck is built it is fully loaded.
    from adventure import TUNING
    if TUNING["block_pct"] != 100:
        block_amt = max(1, round(block_amt * TUNING["block_pct"] / 100))
        # Three distinct numbers on screen is a hard invariant, not a
        # preference -- two equal ones invite a relationship that is not there,
        # the same trap as block == 2*hit. Nudged deterministically rather than
        # redrawn, because a redraw is another RNG call and we are straight back
        # to reshuffling the world.
        while block_amt in (base_atk, heal_amt):
            block_amt += 1
    # `double` is back in the basic set now that the regenerator is in the
    # rotation. It was removed for being dead weight, and that was correct while
    # every enemy could be ground down: chip damage and burst were worth the
    # same. A regenerator that heals faster than half output can kill it makes
    # them different -- burst gets through, chipping does not -- so the card has
    # exactly one monster that requires it, which is the bar a card has to meet.
    # `carry` stays out until the pressure monster it answers exists.
    cards = [
        Card("attack", 0),
        Card("block", block_amt),
        Card("dodge", 0, cost=2),
        Card("heal", heal_amt),
        Card("buff_mark", 0),
    ]
    names = ["kel", "vorth", "mira", "tsun", "ravi", "doln"]
    rng.shuffle(names)
    names = names[:len(cards)]
    return dict(zip(names, cards)), base_atk


@dataclass
class Camp:
    """A sparring partner that hits back gently, and unlimited patience."""

    deck: dict[str, "Card"]
    layout: "Layout"
    max_hp: int = 120
    dummy_hp: int = 300
    sparring_hit: int = 0
    max_energy: int = 2
    base_atk: int = 5
    turn: int = 1
    state: dict = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    pile: "Pile" = None
    seen: set = field(default_factory=set)

    def __post_init__(self):
        self.reset()

    @property
    def hand(self):
        return self.pile.hand

    def reset(self):
        # poison and charge stay at zero: no camp card can produce them, and
        # that is deliberate -- they are what comes alive later.
        blk = next((c.amount for c in self.deck.values() if c.kind == "block"), 5)
        # Training is a consequence-free experiment.  Tie its health budget to
        # the same knob that controls the dummy's hit, rather than relying on a
        # stale fixed 120 that became lethal when BLOCK_RATIO increased.
        self.max_hp = max(self.max_hp, safe_camp_hp(blk))
        if not self.sparring_hit:
            self.sparring_hit = sparring_hit_for(blk, self.rng)

        self.state = {("me", p): 0 for p in
                      STANDING_MINE_PROPS + TRANSIENT_MINE_PROPS
                      + EXTRA_TRANSIENT_MINE_PROPS}
        self.state |= {("them", p): 0 for p in
                       STANDING_THEIRS_PROPS + TRANSIENT_THEIRS_PROPS
                       + EXTRA_TRANSIENT_THEIRS_PROPS}
        self.state[("me", "hp")] = self.max_hp
        self.state[("me", "cap")] = self.max_hp
        self.state[("me", "energy")] = self.max_energy
        self.state[("me", "atk")] = self.base_atk
        self.state[("them", "hp")] = self.dummy_hp
        self.state[("them", "atk")] = self.sparring_hit
        self.turn = 1
        # same draw rules as the adventure -- the camp has to teach the game
        # that is actually played, not a simplified one
        by_kind = {c.kind: n for n, c in self.deck.items()}
        names = [by_kind[k] for k, n in STARTING_PILE.items()
                 for _ in range(n) if k in by_kind]
        self.pile = Pile(names, self.deck, self.rng)

    def can_play(self, name: str) -> bool:
        return (name in self.pile.hand
                and self.state[("me", "energy")] >= self.deck[name].cost)

    def _mark(self, before):
        for k, v in self.state.items():
            if before[k] != v:
                self.seen.add(k)

    def play(self, name: str) -> bool:
        """False when it could not be paid for -- no state change, no reason
        given either: why it failed is part of what has to be learned."""
        c = self.deck[name]
        s = self.state
        if name not in self.pile.hand:
            return "absent"
        if s[("me", "energy")] < c.cost:
            return False
        before = dict(s)
        s[("me", "energy")] -= c.cost
        c.cost_known = True          # you just paid it, so now you know
        self.pile.play(name)

        if c.kind == "attack":
            # damage IS the attack stat -- c.amount stays 0 for the basic card
            # and is reserved for later cards that add on top of it
            dmg = (s[("me", "atk")] + c.amount) * (2 if s[("me", "double")] else 1)
            s[("them", "hp")] -= dmg
            s[("me", "double")] = 0
        elif c.kind == "block":
            s[("me", "block")] += c.amount
        elif c.kind == "dodge":
            s[("me", "dodge")] = 1
        elif c.kind == "heal":
            s[("me", "hp")] = min(self.max_hp, s[("me", "hp")] + c.amount)
        elif c.kind == "buff_mark":
            s[("me", "double")] = 1
        elif c.kind == "block_carry":
            if s[("me", "block")] > 0:
                s[("me", "carry")] = 1
        self._mark(before)
        return True

    def end_turn(self) -> None:
        """The system's own dynamics -- only visible if you stop acting."""
        s = self.state
        before = dict(s)
        if s[("me", "poison")] > 0:
            s[("me", "hp")] -= s[("me", "poison")]

        if not s[("me", "dodge")]:
            hit = s[("them", "atk")]
            absorbed = min(s[("me", "block")], hit)
            s[("me", "block")] -= absorbed
            s[("me", "hp")] -= hit - absorbed

        if s[("me", "carry")]:
            s[("me", "carry")] = 0
        else:
            s[("me", "block")] = 0
        s[("me", "dodge")] = 0
        s[("me", "energy")] = self.max_energy
        self.pile.end_turn()
        self._mark(before)
        self.turn += 1


def _row(camp, side, tier) -> str:
    """Only what is actually present. A counter shows a value; a flag shows only
    its name -- absent statuses print nothing at all.

    A value stays `?` until it has been seen to change. Printing it from the
    start hands over a shortcut that survives across runs: the biggest number on
    screen is health, a small one next to it is attack. Symbols are redrawn every
    run, magnitudes are not. Waiting for the first change costs exactly one
    observation -- the size of that first change is unknown, everything after it
    is not -- and it lines up with the rule the rest of the design already
    follows: a quantity that never moves is not identifiable, so it does not get
    to show a number either."""
    out = []
    for p in camp.layout.ordered(side, tier):
        v = camp.state[(side, p)]
        if not v:
            continue
        lab = camp.layout.L(side, p)
        sep = "=" if tier == "standing" else ":"
        if p not in NUMERIC_PROPS:
            out.append(lab)
        else:
            seen = (side, p) in getattr(camp, "seen", ())
            out.append(f"{lab}{sep}{v if seen else '?'}")
    return "  ".join(out)


def show(camp, turns_left: int | None = None) -> str:
    """The camp screen, as models and people read it. English since 2026-10-19 (the user: every word a participant
    reads is English); before that it read 回合 N / 剩余 N 回合 / 我 / 对方 with a 7-column label, and the GUI
    translated it for display into these words (core/gui/english.json) -- except that one remaining turn now reads
    "1 turn left"."""
    left = "" if turns_left is None else f"    {turns_left} turn{'' if turns_left == 1 else 's'} left"
    lines = [f"Turn {camp.turn}" + left]
    for side, name in (("me", "You"), ("them", "Them")):
        lines.append(f"{name}:".ljust(8) + _row(camp, side, "standing"))
        tr = _row(camp, side, "transient")
        if tr:
            lines.append(" " * 8 + tr)
    return chr(10).join(lines)


if __name__ == "__main__":
    rng = random.Random(7)
    deck, base_atk = make_deck(rng)
    camp = Camp(deck, Layout(rng), base_atk=base_atk)
    print("这一局的隐藏映射:")
    for n, c in camp.deck.items():
        print(f"  {n:<7} {c}")
    print(f"\n初始:\n{show(camp.state)}\n")

    script = [("play", "kel"), ("play", "vorth"), ("end", None),
              ("play", "mira"), ("end", None)]
    for kind, arg in script:
        before = dict(camp.state)
        if kind == "play":
            camp.play(arg); tag = arg
        else:
            camp.end_turn(); tag = "结束回合"
        ch = [f"{k}: {before[k]}→{camp.state[k]}"
              for k in SLOTS if before[k] != camp.state[k]]
        print(f"  {tag:<10} {'， '.join(ch) if ch else '(没有变化)'}")
