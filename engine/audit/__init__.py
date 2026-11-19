"""Clean-room offline auditor of the behaviour meter's verdicts (audit-floors-v1, scoring-v1, trace-v1).

The package answers one question: did the referee judge each item correctly? It never scores the player again.
It reads only RULES.md, docs/audit/*.md, the engine (core/adventure.py, core/devworld.py, core/camp.py,
core/namegen.py) and the records. No meter code is imported (see audit/tests/test_independence.py).
"""

AUDIT_PACKAGE_VERSION = "audit-impl-3"   # audit-impl-3 (2026-11-07, user approved): boss-world boss lives (PROTO_RECORDS §7) and the momentum reading on prototype records (§8); every existing record reads as under audit-impl-2
SCORING_ID = "scoring-v1"
FLOORS_ID = "audit-floors-v1"
TRACE_ID = "trace-v1"
REST_TURN = 1000000
