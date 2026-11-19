"""Local, dependency-free browser GUI for humanrun.py.

Run: python core/humangui.py
The worker executes the original human frontend; HTTP only carries public text.

引擎与外观解耦：引擎种子固定为登记的 9065（GUI 不接受任何种子参数），外观在浏览器里按
(宇宙, 世, 第几场) 从 GUI 包各部件独立抽取（core/gui/look.js），服务端不参与外观。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
GAME_SEED = 9065          # 登记的引擎种子；外观与它无关


def all_packs():
    """可选的宇宙（包）：登记 8 的 P/C 和当前登记图库拼出的包，名字 → 各世的图。"""
    import devworld
    packs = {"P": tuple(devworld.PILOT_PACK), "C": tuple(devworld.CONTROL_PACK)}
    packs.update({k: tuple(v) for k, v in devworld.PACK_NAMES.items()})
    return packs


def default_pack():
    import devworld
    return next(iter(devworld.PACK_NAMES), "P")


def participant_name(value):
    if (not isinstance(value, str) or not value.strip()
            or any(ch in '<>:"/\\|?*' or unicodedata.category(ch) == "Cc" for ch in value)):
        raise ValueError('The name cannot be empty or contain path separators, control characters or <>:"|?*.')
    return value


def life_range(value, size=5):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9](?:-[1-9])?", value):
        raise ValueError(f"Lives: enter a range such as 1-{size} or 2-{size}, or a single number from 1 to {size}.")
    ends = [int(v) for v in value.split("-")]
    lo, hi = ends[0], ends[-1]
    if lo > hi:
        raise ValueError("The first life cannot come after the last one.")
    if hi > size:
        raise ValueError(f"This universe has only {size} lives.")
    return lo, hi


def record_path(name, pack, life):
    import modelrun
    return modelrun._record(f"human-{name}", GAME_SEED, life, run_id=f"human-{name}-{pack}")


def validate_start(data, *, auto=False):
    import modelrun
    packs = all_packs()
    name = participant_name(data.get("name"))
    pack = data.get("pack") or default_pack()
    if pack not in packs:
        raise ValueError("Choose an existing universe.")
    size = len(packs[pack])
    lives = data.get("lives") or f"1-{size}"
    lo, hi = life_range(lives, size)
    carry = data.get("carry", "notes")
    if carry not in ("notes", "none", "log", "both"):
        raise ValueError("Choose an existing carry option.")
    earlier = []
    for life in range(1, lo):
        try:
            record = modelrun._load(f"human-{name}", GAME_SEED, life,
                                    run_id=f"human-{name}-{pack}")
        except (OSError, ValueError):
            raise ValueError(f"The record of life {life} cannot be read.") from None
        if record is not None and not isinstance(record, dict):
            raise ValueError(f"The record of life {life} cannot be read.")
        earlier.append(record)
    if lo > 1 and not any(earlier):
        raise ValueError(f"To continue from life {lo}, a record of at least one of lives 1 to {lo - 1} is needed.")
    for life in range(lo, hi + 1):
        path = record_path(name, pack, life)
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ValueError("An existing record cannot be read. Use another name; the old record stays.") from None
            if not isinstance(old, dict):
                raise ValueError("An existing record cannot be read. Use another name; the old record stays.")
            if old.get("result") and data.get("restart") is not True:
                raise ValueError(f"Life {life} already has a record. Tick Replay to play it again; the old record is backed up first.")
    args = ["--name", name, "--pack", pack, "--lives", lives, "--carry", carry]
    if auto:
        args.append("--auto")
    # START.md requires all four lives before disclosure. Missing or unfinished
    # earlier lives may still resume, exactly as the engine permits, but cannot
    # unlock a reveal at the end of that partial run.
    prior_complete = all(r and r.get("result") and r["result"] != "camp only"
                         for r in earlier)
    if data.get("reveal") is True and hi == size and prior_complete:
        args.append("--reveal")
    return name, pack, args


def stable_record_bytes(path):
    """Read a complete, unchanged JSON checkpoint, including during a run."""
    def version(stat):
        return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino

    for attempt in range(4):
        try:
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            record = json.loads(raw)
            if (isinstance(record, dict) and version(before) == version(after)
                    and len(raw) == after.st_size and path.read_bytes() == raw
                    and version(path.stat()) == version(after)):
                return raw
        except (OSError, ValueError):
            pass
        if attempt < 3:
            time.sleep(.02)
    raise ValueError("The record is being written or cannot be read. Try again shortly.")


def participant_record_name(filename, name):
    """Match a whole human-run filename, including the original legacy forms.

    A name can itself contain underscores and digits. Prefix matching therefore
    confuses ``alice`` with ``alice_9065``; every remaining filename field must
    follow the engine's grammar, including its exact participant namespace.
    """
    import modelrun
    model = re.escape(modelrun._slug(f"human-{name}"))
    namespace = re.escape(f"human-{name}-") + "(?:" + "|".join(re.escape(p) for p in sorted(all_packs(), key=len, reverse=True)) + ")"
    return re.fullmatch(
        model + r"_-?\d+_[A-Za-z][A-Za-z0-9.-]*"
        + r"(?:(?:_" + namespace + r")?_life\d+)?\.json", filename) is not None


def backup_target_records(name, pack, lives):
    """Preserve bytes before an original worker may overwrite its checkpoints."""
    import modelrun
    lo, hi = life_range(lives, len(all_packs()[pack]))
    snapshots = []
    for life in range(lo, hi + 1):
        path = record_path(name, pack, life)
        if path.exists():
            snapshots.append((path.name, stable_record_bytes(path)))
    if not snapshots:
        return None
    folder = modelrun.RUNS_DIR / ".gui-backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = folder / f"{stamp}-{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in snapshots:
            bundle.writestr(name, raw)
    return target


class Session:
    def __init__(self, *, startup=None):
        self.lock = threading.RLock()
        self.proc = None
        self.status = "idle"
        self.events = []
        self.next_id = 0
        self.prompt_id = None
        self.prompt_kind = None
        supplied = startup or {}
        self.startup = dict(name="", pack=default_pack(), lives="", carry="notes", reveal=True,
                            auto=False, restart=False)
        self.startup.update({key: supplied[key] for key in self.startup
                             if key != "restart" and key in supplied})
        self.auto = self.startup["auto"] is True
        self.name = self.startup["name"]
        self.pack = self.startup["pack"]
        self.config = {key: self.startup[key] for key in
                       ("lives", "carry", "reveal", "auto", "restart")}

    def _event(self, event):
        self.next_id += 1
        event = dict(event, id=self.next_id)
        if event["type"] == "prompt":
            self.prompt_id = self.next_id
            self.prompt_kind = event["kind"]
            event["prompt_id"] = self.prompt_id
        self.events.append(event)

    def start(self, data):
        with self.lock:
            if self.status == "running":
                raise RuntimeError("A game is already in progress.")
            config = dict(self.startup, **data)
            name, pack, args = validate_start(config, auto=self.auto)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            backup = backup_target_records(name, pack, config["lives"] or f"1-{len(all_packs()[pack])}")
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "humangui.py"), "--worker", *args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, cwd=str(ROOT.parent), env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.proc = proc
            self.name, self.pack = name, pack
            self.config = dict(lives=config["lives"] or f"1-{len(all_packs()[pack])}", carry=config["carry"],
                               reveal=config.get("reveal") is True, auto=self.auto,
                               restart=config.get("restart") is True)
            self.events = []
            self.prompt_id = self.prompt_kind = None
            self.status = "running"
            threading.Thread(target=self._read, args=(proc,), daemon=True).start()
            # Drain diagnostics separately; never send engine internals to UI.
            threading.Thread(target=self._drain_errors, args=(proc,), daemon=True).start()
        return {"message": "Old records backed up. The game has started." if backup else "The game has started."}

    def _drain_errors(self, proc):
        for line in proc.stderr:
            if sys.stderr:
                sys.stderr.write(line)

    def _read(self, proc):
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                with self.lock:
                    if self.proc is not proc or self.status == "stopped":
                        break
                    if event.get("type") not in ("prompt", "output", "done", "error"):
                        continue
                    self._event(event)
                    if event["type"] == "done":
                        self.status = "complete"
                        self.prompt_id = None
                    elif event["type"] == "error":
                        self.status = "error"
                        self.prompt_id = None
        finally:
            proc.wait()
            with self.lock:
                if self.proc is proc and self.status == "running":
                    self.status = "error"
                    self.prompt_id = None
                    self._event(dict(type="error", text="The game was interrupted. Finished lives are kept."))

    def snapshot(self, after):
        with self.lock:
            packs = all_packs()
            return dict(status=self.status, name=self.name, pack=self.pack,
                        config=dict(self.config),
                        packs=list(packs), pack_sizes={k: len(v) for k, v in packs.items()},
                        events=[dict(e) for e in self.events if e["id"] > after],
                        prompt_id=self.prompt_id)

    def submit(self, data):
        with self.lock:
            if self.status != "running" or self.prompt_id is None:
                raise RuntimeError("Nothing is waiting for input.")
            if data.get("prompt_id") != self.prompt_id:
                raise RuntimeError("That input was already submitted. Wait for the screen to update.")
            value = data.get("value")
            if not isinstance(value, str):
                raise ValueError("Malformed input.")
            if self.prompt_kind != "note" and ("\n" in value or "\r" in value):
                # 工作便签（PROTO_WORKNOTE=on，scripts/work_note.py）：出牌时第二行起可以是 "NOTE: …"（界面的便签框附上的）；别的多行照旧拒收。
                first, _sep, rest = value.replace("\r\n", "\n").partition("\n")
                if not (self.prompt_kind == "act" and "\r" not in value.replace("\r\n", "\n") and "\n" not in first
                        and rest.lstrip().upper().startswith("NOTE:")):
                    raise ValueError("Enter the operation name or number on one line.")
            try:
                self.proc.stdin.write(json.dumps({"value": value}, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (OSError, BrokenPipeError):
                raise RuntimeError("The game process has exited. Wait for the screen to update.") from None
            self.prompt_id = None
        return {"message": "Submitted."}

    def stop(self):
        with self.lock:
            proc = self.proc
            if self.status == "running":
                self.status = "stopped"
                self.prompt_id = None
                self._event(dict(type="output", text="\n(Quit. Finished lives are saved.)\n"))
                if proc and proc.poll() is None:
                    proc.terminate()
        if proc and proc.poll() is None:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        return {"message": "Quit. Finished lives are kept."}

    def export(self, data):
        import modelrun
        name = participant_name(data.get("name"))
        with self.lock:
            files = sorted(path for path in modelrun.RUNS_DIR.iterdir()
                           if path.is_file() and participant_record_name(path.name, name)
                           ) if modelrun.RUNS_DIR.exists() else []
            if not files:
                raise ValueError("There are no records to export under this name.")
            snapshots = [(path.name, stable_record_bytes(path)) for path in files]
            desktop = Path.home() / "Desktop"
            desktop.mkdir(parents=True, exist_ok=True)
            out = desktop / f"agii_human_{name}.zip"
            staging = desktop / f".agii-export-{uuid.uuid4().hex}.tmp"
            try:
                with zipfile.ZipFile(staging, "x", zipfile.ZIP_DEFLATED) as bundle:
                    for filename, raw in snapshots:
                        bundle.writestr(filename, raw)
                os.replace(staging, out)
            finally:
                staging.unlink(missing_ok=True)
        return {"message": f"Records of {len(files)} lives -> {out}"}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, startup=None):
        self.token = secrets.token_urlsafe(32)
        self.session = Session(startup=startup)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value, content_type="application/json; charset=utf-8"):
        raw = (json.dumps(value, ensure_ascii=False).encode("utf-8")
               if not isinstance(value, bytes) else value)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        token = self.headers.get("X-AGII-Token", "")
        return secrets.compare_digest(token, self.server.token)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {"error": "Local access only."})
        url = urlparse(self.path)
        if url.path == "/":
            import gui_skins
            if gui_skins.enabled():
                return self.reply(200, gui_skins.page((ROOT / "gui" / "index.html").read_text()).encode(), "text/html; charset=utf-8")
            return self.reply(200, (ROOT / "gui" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/favicon.ico":
            return self.reply(204, b"", "image/x-icon")
        # Public cosmetic artwork only; no arbitrary filesystem or JSON access.
        if re.fullmatch(r"/art/world-(?:0[1-9]|[12][0-9])\.png", url.path):
            asset = ROOT / "gui" / url.path.lstrip("/")
            if asset.is_file():
                return self.reply(200, asset.read_bytes(), "image/png")
            return self.reply(404, {"error": "No such page."})
        if not self.authorized():
            return self.reply(403, {"error": "Open the game through the launcher."})
        if url.path == "/api/state":
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
            except ValueError:
                return self.reply(400, {"error": "Malformed request."})
            return self.reply(200, self.server.session.snapshot(after))
        return self.reply(404, {"error": "No such page."})

    def do_POST(self):
        if not self.valid_host() or not self.authorized():
            return self.reply(403, {"error": "Open the game through the launcher."})
        methods = {"/api/start": self.server.session.start,
                   "/api/input": self.server.session.submit,
                   "/api/export": self.server.session.export,
                   "/api/stop": lambda _: self.server.session.stop()}
        if self.path not in methods:
            return self.reply(404, {"error": "No such action."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("Malformed request length.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Malformed request.")
            result = methods[self.path](data)
        except (ValueError, TypeError) as exc:
            return self.reply(400, {"error": str(exc) if isinstance(exc, ValueError) else "Malformed request."})
        except RuntimeError as exc:
            return self.reply(409, {"error": str(exc)})
        except Exception:
            return self.reply(500, {"error": "The action did not complete. Check file permissions or restart."})
        return self.reply(200, result)


def parse_startup_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--name", default="")
    parser.add_argument("--pack", choices=tuple(all_packs()), default=default_pack(), help="universe (pack)")
    parser.add_argument("--lives", default="", help="life range, default the whole universe")
    parser.add_argument("--carry", choices=("notes", "none", "log", "both"), default="notes")
    parser.add_argument("--auto", action="store_true", help="random dry run of the text frontend; pipeline check only")
    reveal = parser.add_mutually_exclusive_group()
    reveal.add_argument("--reveal", dest="reveal", action="store_true")
    reveal.add_argument("--no-reveal", dest="reveal", action="store_false")
    parser.set_defaults(reveal=True)
    return parser.parse_args(argv)


def main():
    if "--worker" in sys.argv[1:]:
        from gui_bridge import run_worker
        return run_worker(sys.argv[sys.argv.index("--worker") + 1:])
    args = parse_startup_args()
    startup = {key: getattr(args, key) for key in ("name", "pack", "lives", "carry", "auto", "reveal")}
    server = Server(("127.0.0.1", args.port), startup=startup)
    url = f"http://127.0.0.1:{server.server_port}/#token={server.token}"
    print(url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.session.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
