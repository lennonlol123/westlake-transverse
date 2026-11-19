"""v7hard5: formal v7hard4 with a 30-END fight limit; all maps and other rules unchanged.

Separate tier, run IDs, ledgers and human records. No paid run is started by
adding this tier. Existing formal workers retain the 40-turn configuration.
"""
import formal_rules

REVISION = "v7hard5-turn30-2026-11-14"
RECORDS_SUBDIR = "hard5_turn30"
HUMAN_SUFFIX = "-hard5"
RUN_TAG = "hard5-"
TURN_CAP = 30
RESTAMT = formal_rules.RESTAMT
RESTAMT_SHA256 = formal_rules.RESTAMT_SHA256
PACK = formal_rules.PACK
PACK_SHA256 = formal_rules.PACK_SHA256
ENV = dict(formal_rules.ENV, PROTO_TURNCAP=str(TURN_CAP))
REFERENCE_STATUS = ("same frozen v7hard4 scene reference candidates: all 160 stored scene frontiers use at most 18 ENDs, "
                    "below the 30-END limit; only termination changed, so these successful trajectories are unaffected. "
                    "Inherited search truncation markers remain; no new global optimality claim")
check_table = formal_rules.check_table
