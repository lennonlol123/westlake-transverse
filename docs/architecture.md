# Browser port and review guide

This release reuses the formal-v1-2026-11-14 / v7hard4 maps and human interaction
loop. It is a public play interface and does not add records to the formal study.

## The transport boundary

The existing GUI's `request(path, body)` calls a browser-local adapter instead of
a Python HTTP server. The adapter sends confirmed text inputs to a Web Worker.
Pyodide 0.29.0 executes the existing human loop, using the same `TerminalBridge`
prompt events as the local GUI. There is no JavaScript implementation of combat.

Python's synchronous input is adapted by deterministic replay. At each input,
the Worker restores the previous Universes' completed records in an isolated
virtual `.play` directory, replays the current Universe's confirmed inputs,
and pauses at the next missing input. The pause is a dedicated `BaseException`,
not EOF, an invalid action, an elapsed turn or a loss. Input replay does not run
inference and has no model cost. Long Universes may incur increasing replay time.

Inputs and the prior-Universe snapshot are stored in IndexedDB before the next
state is displayed. A failed compute or storage operation does not acknowledge
the action. Refresh reconstructs the same prompt from confirmed inputs. The
original GUI still controls which log segment and notes are displayed; storing
older records for replay does not add them to later observations.

## Rule and memory continuity

- Five Universes, four Episodes each, eight scheduled Encounters per Episode.
- Original HP inheritance and frozen `r1v2x130c` resupply table.
- Strict Ward; test start and re-seal three layers; no ten-turn Ward deadline.
- Forty-turn Encounter limit, original consecutive-evasion loss and feedback.
- Test Guard `irr50`, test Charge `len234`, no boss, no correspondence table.
- Original familiarization, within-Universe notes and Universe Letter handoff.
- Exact `tiktoken` 0.9.0 / `o200k_base` note counting, with the verified vocabulary
  cached locally. No approximate character-count substitution is used.

The cosmetic adapter chooses art from Universe, seed and Encounter index only.
No mechanism/design name is displayed. Five skins share the same data typography
and layout. Action feedback is in Record rather than over the opponent art.

## Source preservation and browser constraints

`source-manifest.json` records every vendored Python/data file. Only
`antagonist_proto.py` and `formal_rules.py` have path substitutions, so the
frozen table and pack are read from bundled data instead of a user's home.
Original local research files and records are not edited by this port.

The original research modules import POSIX `fcntl`, which Pyodide lacks. A
browser-only import shim makes research locking operations fail if called;
it does not pretend to acquire a lock. The single-Worker human path never uses
that functionality. Parallel research solvers and model runners are not
supported by this website. All model networking is explicitly disabled.

## Static assets and privacy

The complete runtime, fonts, art, frozen maps and tokenizer are served from this
site. No runtime CDN, external font URL, analytics, player-data upload, password,
API credential or server-side persistence is used. Source and bundled maps are
publicly inspectable; this is a playable demonstration, not an anti-cheating
research platform. The original experiment's participant records are excluded.

## Checks

- `tools/check_release.py`: source/runtime/tokenizer hashes, naming and bundle contents.
- `tests/wasm-smoke.mjs`: real WASM camp, notes, Encounter and deterministic refresh;
  complete U1 event-for-event comparison with native Python; U2 letter handoff.
- `docs/native-validation.json`: U1–U5 end-to-end scripted native-loop checks,
  including each Universe's four result files and Letter. These scripts deliberately
  lose Encounters; they validate continuation and termination, not playing skill.

To update the engine, review and re-vendor sources, rebuild the fixture in native
Python, and rerun the comparison. Do not silently edit the frozen maps or table.
