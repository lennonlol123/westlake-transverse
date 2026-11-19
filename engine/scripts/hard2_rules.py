"""Current hard2 rules; frozen maps and historical measurements stay immutable."""
REVISION = "hard2-ward10-test3-2026-11-13"
RECORDS_SUBDIR = "ward10_test3"
RUN_TAG = "hard-w10s3-"
HUMAN_SUFFIX = "-hard-w10s3"
ENV = dict(PROTO_WARDSTRICT="blockonly", PROTO_BOSSLIFE="off", PROTO_CORRESPOND="off",
           PROTO_MAPCHARGE="len234", PROTO_MAPGUARD="irr50",
           PROTO_WARDLIMIT="10", PROTO_WARDTESTSTART="3")
REFERENCE_STATUS = "recalibration_required: historical hard2 references have no seal deadline and test start 2"
