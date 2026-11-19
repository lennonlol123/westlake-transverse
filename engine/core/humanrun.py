"""人类测试窗口：和模型**同一条管线**（`modelrun.main`），只把三个函数换成键盘：
    act   出牌 / END            pick  地图、休息、奖励的编号选择        call  写笔记（战后总结、命末结论）
记录用同一 schema 写到 ~/agii_runs（AGII_RUNS 可覆盖），run_id human-<name>-<pack>，`transfer_report.py` / `v1_curves.py`
直接能比。屏幕内容和模型收到的一致（系统说明每阶段只印一次、跨命交接每命只印一次，
历史只印新增的几行 —— 信息相同，不重复刷屏）。

用法：python3 humanrun.py --name lennon --pack P            四条命连着打，带自己的笔记
      python3 humanrun.py --name lennon --pack P --lives 2-4  从命 2 接着打（要有命 1 的记录）
      python3 humanrun.py --name test --pack P --auto --lives 1  随机桩子干跑，只验管线
和模型的一处不同：输入不合法（打错字）会重新提示，不计为无效行动；模型那边三次无效会被强制结束回合。
"""
import argparse, random, re, sys
import devworld, modelrun

_shown = set()          # 已经印过的系统说明 / 交接
_seen_hist = [0]        # 历史已印到第几行
_fight = [None]         # 当前这场的对象：换了一场就报一次对手的名字
AUTO = {"on": False, "rng": random.Random(7)}


def _new_history(log):
    hist = [h for h in log if not modelrun.is_observation(h)]
    new = hist[_seen_hist[0]:]
    _seen_hist[0] = len(hist)
    return new


def _show_once(key, text):
    if key not in _shown:
        print("\n" + text + "\n", flush=True)
        _shown.add(key)


def human_act(model, key, system, obj, screen, log, allow, carry=""):
    log.append(modelrun.public_observation(obj, screen))
    _show_once(("sys", system[:40]), system)
    if carry:
        _show_once(("carry", carry[:80]), "[Carried over]\n" + carry)
    for h in _new_history(log):
        print("   " + h, flush=True)
    if obj is not _fight[0]:
        # 对手的名字：模型在战后总结里收到同一个名字（"You have just finished a fight against …"），
        # 之前几条命的笔记标签也带着它。名字是 namegen 随机拼的，与机制无关（type-independent by construction）。
        _fight[0] = obj
        name = getattr(getattr(obj, "enemy", None), "name", None)
        if name:
            print(f"   Opponent: {name}", flush=True)
    print("-" * 52)
    print(screen(obj))
    print("In hand:  " + "  ".join(obj.deck[n].label(n) for n in obj.hand), flush=True)
    if AUTO["on"]:
        playable = [n for n in obj.hand if obj.can_play(n)] if hasattr(obj, "can_play") else []
        a = AUTO["rng"].choice(playable) if playable and AUTO["rng"].random() < .75 else "end"
        print(f"> {a}"); return a
    lowered = {t.lower(): t.lower() for t in allow}
    while True:
        try:
            raw = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n(Quit. Finished lives are saved.)"); sys.exit(0)
        if raw in lowered:
            return raw
        print(f"  Enter one of: {'  '.join(allow)}")


def human_pick(model, key, prompt, options, log, carry=""):
    if carry:
        _show_once(("carry", carry[:80]), "[Carried over]\n" + carry)
    for h in _new_history(log):
        print("   " + h, flush=True)
    print("\n" + prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    if AUTO["on"]:
        k = AUTO["rng"].randrange(len(options)); print(f"> {k+1}"); return k
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(Quit. Finished lives are saved.)"); sys.exit(0)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  Enter a number from 1 to {len(options)}")


def human_call(model, system, user, key, blocks=None):
    """笔记。模型收到 system + 完整记录 + 问题；人看屏幕上的记录，这里只印问题部分。"""
    question = user.rsplit("\n\n", 1)[-1] if "\n\n" in user else user
    # 战后总结：把模型也收到的那一句（对手是谁）印出来；记录本身在屏幕上已经看过了。
    about = user.split(". ", 1)[0] + "." if user.startswith("You have just finished a fight against ") else ""
    print("\n" + "=" * 52 + "\n[Write your notes]  " + system.split(".")[0] + ("\n" + about if about else "") + "\n" + question)
    print("(One point per line. Submit an empty note to skip.)")
    if AUTO["on"]:
        print("> (auto) nothing"); return "auto: nothing learned"
    lines = []
    while True:
        try:
            s = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not s.strip():
            break
        lines.append(s)
    return "\n".join(lines)


def reveal(r, *, show_map_metadata=True):
    title = "True settings" if show_map_metadata else "Card effects"
    print(f"\n{'='*58}\n{title} (revealed only after the last life):")
    for n, c in r["run"].deck.items():
        print(f"  {n:<7} {c}")
    if show_map_metadata:
        for i, l in enumerate(r["run"].layers, 1):
            print(f"  layer {i} {l.behaviour}")
        print(f"  boss   {r['run'].boss_behaviour}")


def main(argv=None, *, show_map_metadata=True):
    """GUI（humangui/gui_bridge）走这里：show_map_metadata=False 时不打印图的编号和整图揭晓。引擎种子固定 9065。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--pack", choices=("P", "C") + tuple(devworld.PACK_NAMES), default="P",
                    help="universe to play: P or C (registration 8), or a pack name from the current library (devworld.PACK_NAMES)")
    ap.add_argument("--lives", default=None, help="which lives to play, e.g. 1-5 or 2-5 (default: the whole universe)")
    ap.add_argument("--carry", default="notes")
    ap.add_argument("--auto", action="store_true"); ap.add_argument("--reveal", action="store_true", help="after the last life, reveal the true settings")
    ap.add_argument("--export", action="store_true", help="zip every record under this name onto the Desktop, to send back")
    a = ap.parse_args(argv)
    if a.export:
        import glob, zipfile, os, pathlib as _p
        files = sorted(glob.glob(str(modelrun.RUNS_DIR / f"human-{a.name}_*.json")))
        out = _p.Path.home() / "Desktop" / f"agii_human_{a.name}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files: z.write(f, os.path.basename(f))
        print(f"{len(files)} life records -> {out}"); sys.exit(0)
    AUTO["on"] = a.auto
    if a.pack in ("P", "C"):
        pack = devworld.PILOT_PACK if a.pack == "P" else devworld.CONTROL_PACK
    else:
        if a.pack not in devworld.PACK_NAMES:
            sys.exit(f"Universe {a.pack} has not been composed yet (devworld.LIBRARY_PACKS is empty: certify, then run scripts/compose_lib.py)")
        pack = devworld.PACK_NAMES[a.pack]
    lives = a.lives or f"1-{len(pack)}"
    lo, hi = (int(x) for x in lives.split("-")) if "-" in lives else (int(lives),) * 2
    modelrun._api_key = lambda model="": "human"
    modelrun.act, modelrun.pick, modelrun.call = human_act, human_pick, human_call
    model, run_id = f"human-{a.name}", f"human-{a.name}-{a.pack}"
    last = None
    for life in range(lo, hi + 1):
        _shown.clear(); _seen_hist[0] = 0; _fight[0] = None
        map_label = f", map {pack[life-1]}" if show_map_metadata else ""
        print(f"\n{'#'*58}\nLife {life}  (universe {a.pack}{map_label})\n{'#'*58}")
        last = modelrun.main(model, 9065, modelrun.CAMP_TURNS, a.carry, True, verbose=False,
                             life=life, salt=pack[life - 1], run_id=run_id, registered=True)
        print(f"\nResult: {last['result']}   Health left {last['hp']}")
    if a.reveal and last is not None:
        reveal(last, show_map_metadata=show_map_metadata)


if __name__ == "__main__":
    main()
