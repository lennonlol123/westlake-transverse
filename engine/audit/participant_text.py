"""Participant-text normalisation of life records (2026-11-05; docs/antagonist_boss/23_minimal_participant_text_draft.md §F).

Records written under the participant-text switch PROTO_TEXT=minimal (scripts/proto_text.py) say so in
`participant_text` = {"text": "minimal", "text_version": ...}. Their `adv_log` differs from the registered text in a
fixed set of line forms; every parser of participant logs (this package and the analysis scripts; list in doc 23 §F)
reads such a record through `registered_record()`, which maps those lines back,
keyed on the record's own text version. A record without that key (every record written with the registered text)
is returned unchanged -- the same object, so readings of registered records cannot change.

Standard library only (audit/tests/test_independence.py): scripts/proto_text.py re-exports these functions.
"""
from __future__ import annotations

import re

NORM_ID = "participant-text-norm-v1"

LOCKED_REGISTERED = "(locked attack resolves)  ->  "      # registered: the charge enemy's locked attack (core/modelrun.py)
LOCKED_MINIMAL = "->  "                                    # minimal A1: the same line without its label
RESUPPLY_REGISTERED = "] automatic resupply -> "         # registered: the rest layer's line (core/adventure.py resupply_line)
RESUPPLY_MINIMAL = re.compile(r"^(\[layer \d+\]) -> (.*)$", re.S)   # minimal B11: "[layer N] -> a3: 52->123"

# What each minimal text version changed in adv_log (proto_text.VERSION written into the record).
FORMS = {
    "proto-text-v1-2026-11-05": ("locked",),
    "proto-text-v2-2026-11-05": ("locked", "resupply"),
}


def text_of(rec) -> str:
    """'registered' for a record without a recorded text switch (all records before the switch existed)."""
    pt = rec.get("participant_text") if isinstance(rec, dict) else None
    return (pt.get("text") if isinstance(pt, dict) else None) or "registered"


def _line(h, forms):
    if not isinstance(h, str):
        return h
    if "locked" in forms and h.startswith(LOCKED_MINIMAL):
        return LOCKED_REGISTERED + h[len(LOCKED_MINIMAL):]
    if "resupply" in forms:
        m = RESUPPLY_MINIMAL.match(h)
        if m:
            return m.group(1) + RESUPPLY_REGISTERED[1:] + m.group(2)
    return h


def registered_log(adv_log, forms=("locked", "resupply")):
    """A minimal adv_log in the registered line forms. Exact and reversible: under the registered text no line starts
    with "->  " and no line is "[layer N] -> ..."; idempotent on lines already in the registered form."""
    return [_line(h, forms) for h in adv_log]


def registered_record(rec):
    """The record as the registered-text parsers read it. Registered records: returned as they are (same object).
    Minimal records: a shallow copy with adv_log (and auto_rests[].line) in the registered forms of the record's own
    text version, and participant_text.read_as saying so. Unknown text or version: ValueError (never guessed)."""
    text = text_of(rec)
    if text == "registered":
        return rec
    if text != "minimal":
        raise ValueError(f"unknown participant text {text!r}")
    pt = rec["participant_text"]
    if pt.get("read_as"):
        return rec
    version = pt.get("text_version")
    forms = FORMS.get(version)
    if forms is None:
        raise ValueError(f"unknown minimal participant-text version {version!r}")
    out = dict(rec)
    if isinstance(rec.get("adv_log"), list):
        out["adv_log"] = registered_log(rec["adv_log"], forms)
    if isinstance(rec.get("auto_rests"), list):
        out["auto_rests"] = [dict(r, line=_line(r["line"], forms)) if isinstance(r, dict) and "line" in r else r
                             for r in rec["auto_rests"]]
    out["participant_text"] = dict(pt, read_as=dict(text="registered", by=NORM_ID, forms=list(forms)))
    return out
