# Westlake TransVerse

An interactive learning and transfer game from Westlake University.
The website is **Westlake TransVerse**; the in-game title is **TransVerse**.

**Play:** https://lennonlol123.github.io/westlake-transverse/

Explore five Universes in sequence. Each Universe has four Episodes, with eight
scheduled Encounters in each Episode. A lost Encounter terminates that Episode,
so some later Encounters may be unreachable. Discover the effects of unfamiliar
operations, write notes, and carry your experience into the next Universe.

## Playing

- Open the website in a desktop or laptop browser and select **Start playing**.
- Select a card or enter an operation name; use **END** to finish a turn.
- Use the working-note field and the note prompts as you go.
- After completing a Universe and its final note, select **Continue to Universe …**.
- Progress is saved in this browser. Reload and select **Continue saved game** to resume.
- **Quit** pauses. **Export** downloads a JSON backup you can inspect or share.
- **New playthrough** replaces the local save after confirmation.

No installation, account, model API key or paid model call is needed. The first
start loads approximately 20 MB of same-site runtime and game files. Clearing
site storage or using a different browser will not preserve your local save.

This is a **public play version**, separate from the original experiment.
Actions and notes are stored in the player's browser, not uploaded to researchers.
There is no analytics or experiment-submission endpoint. GitHub provides the site
hosting and has its own access-logging and privacy practices.

## Local preview

Requires Python 3.10+ to build/serve static files. Players do not need Python.

```sh
python3 tools/build_site.py
python3 tools/check_release.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:8000/. Opening `index.html` via `file://` is not supported.
The vendored runtime is already included; no package installation is required.

## Review and verification

Start with [the architecture and review guide](docs/architecture.md).

- `engine/`: the Python engine and original human interaction loop.
- `src/browser_runtime.py`: deterministic input replay and isolated local records.
- `src/python-host.mjs`, `src/engine-worker.mjs`: Python in a browser Web Worker.
- `src/local-api.js`: the existing GUI's input transport and IndexedDB saves.
- `ui/`: the existing GUI and five supplied cosmetic skins.
- `docs/source-manifest.json`: original and bundled source hashes. The two files
  with differences have filesystem-path changes only, not rule changes.
- `docs/runtime-manifest.json`: pinned, self-hosted Pyodide assets and hashes.

To run the real WebAssembly verification locally (Node.js 22+):

```sh
python3 tools/build_site.py
node tests/wasm-smoke.mjs
```

This compares a complete scripted Universe against native Python, including
public events, then checks the next Universe's handoff. The fixture is generated
test input, **not a participant trajectory**.

## GitHub Pages

The included workflow builds and tests the static site, then publishes `dist/`.
In repository **Settings → Pages**, choose **GitHub Actions** as the source.
Pushes to `main` trigger the workflow. No repository secrets are needed.

## 中文说明

这是可直接在浏览器玩的版本：网页名为 Westlake TransVerse，游戏内只显示
TransVerse。五个 Universe 顺序游玩；进度和笔记保存在自己的浏览器，支持刷新
续玩、暂停、重新开始和下载存档。不会调用模型 API，也不会自动上传玩家记录。

代码审查入口见 `docs/architecture.md`。本机运行上面的三条 Python 命令即可；
部署时在 GitHub 的 Settings → Pages 选择 GitHub Actions。
