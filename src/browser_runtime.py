"""Browser-only transport for the unmodified human interaction loop.

Each step reconstructs the current Universe from confirmed text inputs. No rule
or action is inferred here. Pausing is a BaseException so it cannot be confused
with invalid input, EOF, a loss, or a model answer. This also runs in CPython for
verification. Only the isolated .play directory is ever written.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
SAVE = ROOT / ".play"
PACK = ENGINE / "data/pack_v3c1_v7hard4.json"
VERSION = "public-browser-demo-v1"


class AwaitInput(BaseException):
    pass


def _fresh_engine():
    for name, mod in list(sys.modules.items()):
        file = getattr(mod, "__file__", None)
        if file and Path(file).is_relative_to(ENGINE):
            del sys.modules[name]
    for p in (ENGINE, ENGINE / "core", ENGINE / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def step(payload):
    universe = payload.get("universe", 1)
    actions = payload.get("actions", [])
    baseline = payload.get("baseline", {})
    if type(universe) is not int or not 1 <= universe <= 5:
        raise ValueError("Choose Universe 1–5.")
    if (not isinstance(actions, list) or len(actions) > 20000
            or any(not isinstance(a, str) or len(a) > 50000 for a in actions)):
        raise ValueError("Invalid saved input history.")
    if not isinstance(baseline, dict) or len(baseline) > 50:
        raise ValueError("Invalid previous Universe records.")
    for key, value in baseline.items():
        if (not isinstance(key, str) or Path(key).name != key
                or not key.endswith(".json") or not isinstance(value, str)
                or len(value) > 5_000_000):
            raise ValueError("Invalid record filename or contents.")
    shutil.rmtree(SAVE, ignore_errors=True)
    SAVE.mkdir(parents=True)
    for key, value in baseline.items():
        (SAVE / key).write_text(value)
    # The frozen pack and rule environments are the same as the local launcher.
    raw = json.loads(PACK.read_text())
    spec = raw["worlds"][universe - 1]
    env = spec["boss"].get("env_by_cue", {}).get("on", spec["boss"].get("env", {}))
    for key in list(os.environ):
        if key.startswith("PROTO_"):
            del os.environ[key]
    os.environ.update(env)
    os.environ.update(PROTO_TEXT="minimal", PROTO_CAMP="1", PROTO_HUMAN_V3C1B="1",
                      PROTO_HIDE="a7capatk", PROTO_WORKNOTE="on", PROTO_WARDSEEN="acted",
                      PROTO_WARDSTRICT="blockonly", PROTO_BOSSLIFE="off", PROTO_CORRESPOND="off",
                      PROTO_MAPCHARGE="len234", PROTO_MAPGUARD="irr50", PROTO_WARDLIMIT="off",
                      PROTO_WARDTESTSTART="3", PROTO_RESTAMT="r1v2x130c",
                      AGII_HUMAN_V3C1B_DIR=str(SAVE), AGII_GUI_SKIN="transverse-skins-v1-2026-11-19",
                      AGII_CHAIN_INDEX="1")
    _fresh_engine()
    import proto_play as game
    import gui_bridge
    import humanrun
    import proto_text
    import modelrun
    # Even an accidental future call cannot send a model request from this port.
    def no_network(*args, **kwargs):
        raise RuntimeError("Model/network calls are disabled in the public game.")
    game._cli_guard("gui-worker")
    game.human_v3c1b_setup()
    game.setup()
    modelrun.urllib.request.urlopen = no_network
    modelrun._api_key = lambda *args: "human"
    game._READY["gui_worker"] = True
    events, cursor = [], 0

    def send(event):
        i = len(events) + 1
        events.append(dict(event, id=i, prompt_id=i))

    def receive():
        nonlocal cursor
        if cursor == len(actions):
            raise AwaitInput
        value = actions[cursor]
        cursor += 1
        return value

    bridge = gui_bridge.TerminalBridge(send, receive)
    complete = False
    try:
        with proto_text.human_notes(), bridge.install(humanrun):
            game.human_main(["--name", "Player", "--worlds", str(PACK),
                             "--world-index", str(universe), "--lives", "1-4"],
                            show_map_metadata=False)
        tail = bridge.take_text()
        if tail:
            send(dict(type="output", text=tail))
        send(dict(type="done", text=""))
        complete = True
    except AwaitInput:
        pass
    if cursor != len(actions):
        raise ValueError("Saved inputs extend beyond this Universe's completion.")
    files = {p.name: p.read_text() for p in sorted(SAVE.glob("*.json"))}
    return dict(version=VERSION, universe=universe, complete=complete,
                prompt_id=None if complete else events[-1]["prompt_id"],
                events=events, files=files)
