"""Registration selector for the world pipeline scripts (REG environment variable, 2026-10-27).

REG unset (or REG=11): registration 11, every path and every rule exactly as before.
REG=12: registration 12 (six-mechanic pool, devworld.REGISTRATIONS[12]); every output goes under results/reg12/,
so nothing under results/worlds, results/sweeps or results/*.json is ever written.

The registration itself is read once by core/devworld.py (`devworld.ACTIVE_REGISTRATION`); this module only maps it to
paths and to the registration-12 rules (hard vs report-only, the R1 reference). Operator doc: docs/REGISTRATION_12.md."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import devworld  # noqa: E402
import gates  # noqa: E402

REG = devworld.ACTIVE_REGISTRATION
IS12 = REG == 12
RESULTS = ROOT / "results" / "reg12" if IS12 else ROOT / "results"
WORLDS_DIR = RESULTS / "worlds"
SWEEPS_DIR = RESULTS / "sweeps"


def cfg():
    return devworld.REGISTRATIONS[REG]


def pool():
    return tuple(cfg()["pool"])


def prototype():
    return dict(cfg()["prototype"])


def segments():
    return gates.RELEASE_SEGMENTS_12 if IS12 else gates.RELEASE_SEGMENTS


def family_maps():
    """How many maps the joint certification family has (the Bonferroni denominator, together with the line family)."""
    return gates.RELEASE_FAMILY_MAPS_12 if IS12 else gates.RELEASE_FAMILY_MAPS


def compose_rules():
    """Extra keyword rules for library.compose / check_pack / first_lawful_order. Empty under registration 11."""
    return dict(cfg().get("compose_rules", {})) if IS12 else {}


def pack_name(world, i):
    """Name of the i-th (1-based) curated pack of a world."""
    return f"{world}12-{i}" if IS12 else f"{world}-{i}"


def candidate_salts(start, skip=()):
    """Registration 12, world A: the two-round maps of one salt segment in salt order (lazy). The certification family is NOT
    the first LIB_SIZE candidates: it is the first LIB_SIZE candidates that pass the hard gates (draw in pool, R1 >= R1_MIN_12),
    so the gates stage keeps scanning until each segment holds LIB_SIZE passers (2026-10-27, user: search until 200 pass, then
    certify). `skip` = salts already evaluated."""
    assert IS12
    import search4
    from adventure import Run
    with search4.setup():
        for s in range(start, start + gates.SEGMENT_SPAN):
            if s in skip:
                continue
            r = Run(search4.SEED, validate=False); r._roll(s)
            if devworld.two_rounds(r):
                assert set(r.drawn) <= set(pool()), (s, r.drawn)
                yield s


def family_salts(limit=0):
    """Kept for callers that want a fixed candidate list (pilots, tests): the first candidates per segment, LIB_SIZE each,
    or the first `limit` overall. The real family is built by world_pipeline.stage_gates (passers, not candidates)."""
    out = []
    for start in gates.RELEASE_SEGMENTS_12:
        got = 0
        for s in candidate_salts(start):
            out.append(s); got += 1
            if limit and len(out) >= limit:
                return out
            if got >= gates.LIB_SIZE:
                break
    return out


def r1_wins(run, salt, n, stream, record_factory=None):
    """R1 (registration 12's rule-knowing reference) on one map: n single lives, cautious.Cautious(devworld.R1_VARIANT),
    knowledge ALL - {mark}, PublicBelief, display marks=0 / state_slots='seen' (restored afterwards).
    The same call as scripts/reference_baselines.cautious_check_job. Returns (wins, [(won, record), ...])."""
    import cautious
    import solver
    from adventure import TUNING
    route = solver.SCREEN_ROUTES[9]
    saved = {k: TUNING[k] for k in devworld.R1_DISPLAY}
    TUNING.update(devworld.R1_DISPLAY)
    try:
        w = 0; recs = []
        for t in range(n):
            p = cautious.Cautious(devworld.R1_VARIANT)
            rec = record_factory() if record_factory else None
            kw = dict(record=rec) if rec is not None else {}
            won = bool(solver.run_once(run, solver.ALL - {"mark"}, route, solver._trial_rng(search_seed() ^ salt, stream, t),
                                      information="observable", act_policy=p.act, heal_veto=p.heal_veto,
                                      belief_cls=cautious.PublicBelief, **kw))
            w += won; recs.append((won, rec))
        return w, recs
    finally:
        TUNING.update(saved)


def search_seed():
    return 9065
