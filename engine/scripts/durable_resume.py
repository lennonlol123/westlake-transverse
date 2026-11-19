"""Resume deterministic prototype runs by replaying durable API responses.

Replaying is local: it restores the same game and notes without another model
request or another ledger charge. Only the first missing response calls the API.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import json
import os
from pathlib import Path
import tempfile

import modelrun as mr

VERSION = "response-replay-v1"
_ACTIVE = ContextVar("transverse_checkpoint", default=None)


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_evidence(paths):
    return [dict(path=str(p), content_sha=mr._sha(Path(p).read_text()) if Path(p).exists() else None) for p in paths]


def _events(path):
    """Keep a torn final write separately, then repair only that incomplete tail."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    result, offset = [], 0
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            if i != len(lines) - 1 or line.endswith(b"\n"):
                raise RuntimeError(f"Invalid response journal at line {i + 1}: {path.name}")
            fd, backup = tempfile.mkstemp(prefix=path.name + ".torn-", dir=path.parent)
            with os.fdopen(fd, "wb") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            with path.open("r+b") as f:
                f.truncate(offset)
                f.flush()
                os.fsync(f.fileno())
            break
        result.append(event)
        offset += len(line)
    # A valid final JSON object can have lost only its newline.
    if result and offset == len(raw) and raw and not raw.endswith(b"\n"):
        with path.open("ab") as f:
            f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())
    return result


def restore_usage(event):
    """Temporarily include history in this record, never re-debit the ledger."""
    usage = event.get("usage") or {}
    by = mr.USAGE_BY_KIND.setdefault(event["kind"], dict.fromkeys(mr.USAGE, 0))
    for key in mr.USAGE:
        value = usage.get(key, 0)
        mr.USAGE[key] += value
        by[key] += value
    raw = event.get("provider_response") or {}
    details = event.get("usage_details", mr._details(raw.get("usage") or {}))
    for key, value in details.items():
        mr.USAGE_DETAILS[key] = mr.USAGE_DETAILS.get(key, 0) + value
    _ACTIVE.get()["restored"].append((event["kind"], usage, details))


def api_matches(saved, current, model, record_path):
    """Accept an explicitly recorded transport handoff, never a prompt/effort change.

    Old manifests and journals stay immutable. A handoff is scoped to named
    records and exact source/target API settings; only routing, endpoint prices
    and reported quantization may differ. New responses retain their new API.
    """
    if saved == current:
        return True
    path = Path(record_path)
    grant_path = path.parent / ".provider_handoffs.json"
    if not grant_path.exists() or not isinstance(saved, dict) or not isinstance(current, dict):
        return False
    grant = json.loads(grant_path.read_text())
    if grant.get("version") != 1 or grant.get("model") != model:
        return False
    stable = lambda api: {k: v for k, v in api.items() if k not in ("routing", "price", "quantization")}
    if stable(saved) != stable(current):
        return False
    for handoff in grant.get("handoffs", []):
        if (path.name in handoff.get("records", []) and handoff.get("source_api") == saved
                and handoff.get("target_api") == current and handoff.get("authorization")):
            routing = current.get("routing", {})
            return (len(routing.get("only", [])) == 1 and routing.get("allow_fallbacks") is False
                    and routing.get("require_parameters") is True)
    return False


def replay(model, system, user, blocks):
    state = _ACTIVE.get()
    if state is None or state["model"] != model:
        return None
    if not state["errors_restored"]:
        for event in state["errors"]:
            restore_usage(event)
        state["errors_restored"] = True
    if state["index"] == len(state["events"]):
        return None
    event = state["events"][state["index"]]
    expected = dict(model=model, system=system, user=user, kind=mr._call_kind(system), provider=mr.provider_for(model))
    for key, value in expected.items():
        if event.get(key) != value:
            raise RuntimeError(f"Resume diverged at response {state['index'] + 1} ({key}); no new request sent")
    for key, value in (("api", mr.api_settings(model)), ("request_blocks", blocks)):
        value = json.loads(json.dumps(value))
        same = (api_matches(event.get(key), value, model, state["record_path"])
                if key == "api" else event.get(key) == value)
        if key in event and not same:
            raise RuntimeError(f"Resume settings changed at response {state['index'] + 1} ({key})")
    if not isinstance(event.get("raw"), str):
        raise RuntimeError("Saved response has no replayable answer")
    state["index"] += 1
    restore_usage(event)
    return copy.deepcopy(event)


def rebuilding():
    """Reconstruct the camp too when its responses are part of this journal."""
    state = _ACTIVE.get()
    return state is not None and bool(state["events"])


def _dump(model, seed, payload, life=1, run_id=None):
    path = mr._record(model, seed, life, run_id=run_id)
    old = json.loads(path.read_text()) if path.exists() else {}
    if old and old.get("salt") is not None and payload.get("salt") is not None and old["salt"] != payload["salt"]:
        raise SystemExit(f"Refusing to overwrite {path.name} with another salt")
    payload.setdefault("protocol", mr.PROTOCOL_VERSION)
    old.update(payload)
    atomic_json(path, old)


@contextmanager
def operation(model, path, metadata, *, resume=False):
    path = Path(path)
    folder = path.parent / ".checkpoints"
    folder.mkdir(parents=True, exist_ok=True)
    # Auditors recursively discover *_life*.json as experiment records. State
    # files use their own extension so they can never masquerade as a life.
    manifest = folder / (path.stem + ".state")
    lock = folder / (path.name + ".lock")
    journal = path.with_suffix(".calls.jsonl")
    with lock.open("a+b") as f:
        if os.name == "nt":
            import msvcrt
            if f.tell() == 0:
                f.write(b"0"); f.flush()
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError(f"This record is already running: {path.name}") from None
        else:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(f"This record is already running: {path.name}") from None
        canonical = json.loads(json.dumps(dict(version=VERSION, model=model, **metadata), default=str))
        if manifest.exists():
            saved = json.loads(manifest.read_text())
            non_api = lambda data: {k: v for k, v in data.items() if k != "api"}
            if (non_api(saved) != non_api(canonical)
                    or not api_matches(saved.get("api"), canonical.get("api"), model, path)):
                raise RuntimeError("Resume configuration differs from the saved run; use its original settings")
        else:
            atomic_json(manifest, canonical)
        events = _events(journal)
        if events and not resume:
            raise RuntimeError("This run has saved responses; continue with resume=True / --resume")
        state = dict(model=model, record_path=path, events=[e for e in events if e.get("outcome") == "response"], index=0,
                     errors=[e for e in events if e.get("outcome") == "error" and e.get("usage")],
                     errors_restored=False, completed=False, restored=[])
        token = _ACTIVE.set(state)
        original_dump = mr._dump
        mr._dump = _dump
        try:
            yield state
            if state["index"] != len(state["events"]) and not state["completed"]:
                raise RuntimeError("Run ended before all saved responses were replayed")
        finally:
            # The life/letter record has already included its historical calls.
            # Process-global counters should still count only actual calls here,
            # not local replay (including when resuming in the same process).
            for kind, usage, details in state["restored"]:
                for key in mr.USAGE:
                    mr.USAGE[key] -= usage.get(key, 0)
                    mr.USAGE_BY_KIND[kind][key] -= usage.get(key, 0)
                for key, value in details.items():
                    mr.USAGE_DETAILS[key] -= value
            mr._dump = original_dump
            _ACTIVE.reset(token)
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
