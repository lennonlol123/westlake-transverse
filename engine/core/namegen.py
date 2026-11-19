"""Names for enemies -- pronounceable, memorable, and carrying zero information.

A name exists so a run reads like something happened to someone, and so notes can
refer to a specific encounter. It must never hint at the enemy's type: every name
is drawn from one shared pool with no dependence on type, so a model cannot learn
to read the label instead of the behaviour.
"""

from __future__ import annotations

import random

SIMPLE = ["k", "v", "m", "t", "r", "d", "s", "z", "b", "n", "l", "p", "g", "h", "j", "f"]
CLUSTER = ["th", "gr", "vr", "kh", "dr", "br", "tr", "kr", "sh", "st", "fl", "sk"]
NUCLEI = ["a", "e", "i", "o", "u", "ae", "ei", "ou", "ai", "ia"]
CODAS = ["", "", "", "n", "l", "r", "s", "th", "m", "k"]

# A handful of real surnames mixed into the pool, purely for fun -- they show up
# occasionally among the invented ones. Edit freely; the only rule is that they
# stay type-independent like every other name, and that given names remain
# invented so no complete real person's name is ever produced.
TRIBUTE = ["Lennon", "Dylan", "Clapton", "Sakamoto", "Bowie", "Floyd",
           "Evans", "Coltrane", "Hosono", "Khalil", "Kant", "Murakami",
           "Kitano", "Kanei"]
# Kanei is rarer than the rest -- one fifth the weight of any other entry.
TRIBUTE_WEIGHTS = [1.0] * (len(TRIBUTE) - 1) + [0.2]
TRIBUTE_RATE = 0.03

# never emit these, whatever the dice say
BANNED = {"ass", "cum", "fuk", "fuc", "sex", "tit", "cok", "dik", "nig", "jew",
          "rap", "pis", "sht", "hel", "god", "die", "kil"}


def _word(rng: random.Random, n_syl: int) -> str:
    """Build syllable by syllable, keeping it pronounceable.

    A consonant cluster may only open a syllable when the previous one ended in
    a vowel -- otherwise you get things like "Ziststoskurn".
    """
    while True:
        out, prev_coda = "", ""
        for i in range(n_syl):
            onset = rng.choice(CLUSTER) if (not prev_coda and rng.random() < 0.4) \
                    else rng.choice(SIMPLE)
            coda = rng.choice(CODAS) if i < n_syl - 1 else rng.choice(CODAS + ["n", "l"])
            out += onset + rng.choice(NUCLEI) + coda
            prev_coda = coda
        if len(out) > 9 or any(b in out for b in BANNED):
            continue
        return out.capitalize()


def enemy_name(rng: random.Random) -> str:
    """One given name + one surname. Type-independent by construction.

    A tribute name may land in either position, and both positions are drawn
    independently -- so two of them can occasionally show up together.
    """
    parts = [_word(rng, rng.choice([1, 2])), _word(rng, 2)]
    for i in (0, 1):
        if rng.random() < TRIBUTE_RATE:
            # never the same tribute twice -- "Lennon Lennon" reads as a bug
            pool = [t for t in TRIBUTE if t not in parts]
            w = [x for t, x in zip(TRIBUTE, TRIBUTE_WEIGHTS) if t not in parts]
            parts[i] = rng.choices(pool, w)[0]
    return " ".join(parts)


def name_stream(seed: int, n: int) -> list[str]:
    """Reproducible batch -- same seed always yields the same run's cast."""
    rng = random.Random(seed)
    seen, out = set(), []
    while len(out) < n:
        nm = enemy_name(rng)
        if nm not in seen:
            seen.add(nm); out.append(nm)
    return out


if __name__ == "__main__":
    print("一个 run 的登场名单 (seed=7):\n")
    for i, nm in enumerate(name_stream(7, 12), 1):
        print(f"  {i:>2}. {nm}")

    # the property that matters: names must not correlate with type
    print("\n同一类型的敌人，名字之间应当毫无共性:")
    rng = random.Random(1)
    for t in ("抗物理", "抗魔法", "穿透"):
        print(f"  {t:<6} {' / '.join(enemy_name(rng) for _ in range(3))}")
    print("\n^ 名字与类型无关，模型无法靠命名模式推断类型。")

    hits = [n for n in name_stream(11, 60) if n.split()[1] in TRIBUTE]
    print(f"\n60 个名字里出现的致敬姓氏 ({len(hits)} 个):")
    for n in hits:
        print(f"  {n}")
