"""Transport the existing human terminal frontend without adding game knowledge.

Only already-public labels, screens and choices cross this boundary. The original
human_* functions still render every byte and validate every input. In particular,
the bridge must never query can_play(), state, card effects or enemy behaviour.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys


class TerminalBridge(io.TextIOBase):
    def __init__(self, send, receive):
        self.send = send
        self.receive = receive
        self.parts = []
        self.context = {}
        self.pending_lines = []

    def write(self, text):
        self.parts.append(text)
        return len(text)

    def flush(self):
        pass  # print(flush=True) must not split a complete input screen.

    def take_text(self):
        text = "".join(self.parts)
        self.parts.clear()
        return text

    def input(self, prompt="> "):
        if self.pending_lines:
            line = self.pending_lines.pop(0)
        else:
            self.send(dict(type="prompt", text=self.take_text(), **self.context))
            value = self.receive()
            if not isinstance(value, str):
                raise EOFError
            if self.context.get("kind") == "note":
                # Exactly the CLI's first-blank-line termination semantics.
                lines = []
                for item in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                    if not item.strip():
                        break
                    lines.append(item)
                self.pending_lines = lines + [""]
                line = self.pending_lines.pop(0)
            else:
                line = value
        # Terminal input echoes are public too; keep them in the visible record.
        self.write(prompt + line + "\n")
        return line

    @contextlib.contextmanager
    def install(self, human):
        old_act, old_pick, old_call = human.human_act, human.human_pick, human.human_call
        missing = object()
        old_input = getattr(human, "input", missing)

        def act(model, key, system, obj, screen, log, allow, carry=""):
            # Capture the exact renderer result used by human_act, once.
            shown = screen(obj)
            choices = [dict(value=n, label=obj.deck[n].label(n), group="hand")
                       for n in obj.hand]
            choices += [dict(value=t.lower(), label=t, group="command")
                        for t in allow if t in ("END", "RESET", "LEAVE")]
            self.context = dict(kind="act", screen=shown, choices=choices)
            import gui_skins
            visual = gui_skins.public_metadata()
            if visual:
                self.context['visual'] = visual
            return old_act(model, key, system, obj, lambda _: shown, log, allow, carry)

        def pick(model, key, prompt, options, log, carry=""):
            self.context = dict(kind="pick", choices=[
                dict(value=str(i), label=f"{i}. {o}", group="option")
                for i, o in enumerate(options, 1)])
            return old_pick(model, key, prompt, options, log, carry)

        def call(model, system, user, key, blocks=None):
            # blocks 只是给模型接口切缓存用的（内容 = user 全文），人看到的文字不变，这里不用。
            self.context = dict(kind="note", choices=[])
            return old_call(model, system, user, key)

        human.human_act, human.human_pick, human.human_call = act, pick, call
        human.input = self.input
        try:
            with contextlib.redirect_stdout(self):
                yield self
        finally:
            human.human_act, human.human_pick, human.human_call = old_act, old_pick, old_call
            if old_input is missing:
                del human.input
            else:
                human.input = old_input


def run_worker(argv):
    import humanrun
    wire = sys.stdout

    def send(event):
        wire.write(json.dumps(event, ensure_ascii=False) + "\n")
        wire.flush()

    def receive():
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return json.loads(line)["value"]

    bridge = TerminalBridge(send, receive)
    try:
        with bridge.install(humanrun):
            # GUI participants never receive map IDs or the full map reveal.
            # This controls printing only; engine seeds and saved records stay intact.
            humanrun.main(argv, show_map_metadata=False)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            send(dict(type="error", text="The game cannot continue. Check the universe and the records being continued."))
            return 1
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        send(dict(type="error", text="The game hit an error. Finished lives are kept; close this and start again."))
        return 1
    tail = bridge.take_text()
    if tail:
        send(dict(type="output", text=tail))
    send(dict(type="done", text=""))
    return 0
