"""Account-wide request gate for GPT 6.1 Sol via OpenRouter (2026-11-11).

OpenRouter limits new accounts to 20 requests per minute for this model, across every key and process. Three GPT
chains in parallel exceeded it; chain 3 used up its six transport retries on HTTP 429 and paused. Every GPT request
from any process first takes a slot here: at most LIMIT sends in any rolling WINDOW seconds, shared through a locked
file. Routing only; the participant's text and the request body are unchanged.
"""
import fcntl
import json
import os
from pathlib import Path
import time

LIMIT = 18
WINDOW = 60.0
PATH = Path(os.environ.get("AGII_GPT_RATE_FILE")
            or Path(__file__).resolve().parents[1] / "runs/transverse_v2/gpt-6.1-sol-flex/.rate_gate.json")


def acquire(limit=LIMIT, window=WINDOW, path=None, clock=time.time, sleep=time.sleep):
    """Block until a send slot is free, then record this send. Returns the seconds waited."""
    path = Path(path or PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    waited = 0.0
    while True:
        with open(str(path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                stamps = json.loads(path.read_text()) if path.exists() else []
            except ValueError:
                stamps = []
            now = clock()
            stamps = [t for t in stamps if now - t < window]
            if len(stamps) < limit:
                stamps.append(now)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(stamps))
                tmp.replace(path)
                return waited
            pause = max(0.5, window - (now - min(stamps)) + 0.05)
        sleep(pause)
        waited += pause
