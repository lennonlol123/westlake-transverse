"""Build an entirely static GitHub Pages site from the reviewed local sources."""
from pathlib import Path
import base64
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist"


def main():
    OUT.mkdir(exist_ok=True)
    files = {}
    for p in sorted((ROOT / "engine").rglob("*")):
        if p.suffix not in (".py", ".json") or "__pycache__" in p.parts:
            continue
        files['engine/' + p.relative_to(ROOT / "engine").as_posix()] = p.read_text()
    files['src/browser_runtime.py'] = (ROOT / 'src/browser_runtime.py').read_text()
    (OUT / "engine-bundle.json").write_text(json.dumps(dict(version="public-browser-demo-v1", files=files), ensure_ascii=False))
    for folder in ("src", "vendor", "data", "licenses"):
        shutil.copytree(ROOT / folder, OUT / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    art = []
    def svg(file):
        return 'data:image/svg+xml;base64,' + base64.b64encode((ROOT / 'ui' / file).read_bytes()).decode()
    for world in json.loads((ROOT / 'ui/manifest.json').read_text())['worlds']:
        art.append(dict(universe=world['universe'], world=world['world'], backdrop=svg(world['backdrop']),
                        monsters=[dict(id=m['id'], image=svg(m['file'])) for m in world['monsters']]))
    html = (ROOT / 'ui/base.html').read_text()
    font = base64.b64encode((ROOT / 'ui/retro-font.woff').read_bytes()).decode()
    css = "@font-face{font-family:'TV Mono';src:url(data:font/woff;base64," + font + ") format('woff');font-display:block;}\n"
    css += '\n'.join((ROOT / 'ui' / name).read_text() for name in ['skins.css','skin-adapter.css','demo.css'])
    html = html.replace('</head>', '<meta name="description" content="Westlake TransVerse: explore, learn and transfer experience across five Universes."><style>' + css + '</style></head>')
    body = '<body data-setup-open="true" data-phase="idle">'
    assert html.count(body) == 1
    html = html.replace(body, body + '\n' + (ROOT / 'ui/demo.html').read_text(), 1)
    adapter = (ROOT / 'ui/skin-adapter.js').read_text().replace('__TV_PUBLIC_ART__', json.dumps(art, separators=(',', ':')))
    marker = "  <script>\n    'use strict';\n    const $"
    assert marker in html
    html = html.replace(marker, '<script>' + adapter + '</script><script src="src/local-api.js"></script>\n' + marker, 1)
    old = """    async function request(path, body) {
      const opts = { cache:'no-store', headers:{'X-AGII-Token':token}, signal:AbortSignal.timeout(10000) };
      if (body !== undefined) { opts.method = 'POST'; opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
      const response = await fetch(path, opts);
      let data;
      try { data = await response.json(); } catch (_) { throw new Error('The service did not respond. Try again in a moment.'); }
      if (!response.ok) throw new Error(data.error || 'The action did not complete. Try again.');
      return data;
    }"""
    assert old in html, 'Original GUI request adapter changed; review the transport.'
    html = html.replace(old, '    async function request(path, body) { return window.TVLocal.request(path, body); }', 1)
    # The export intentionally exposes no game-server routes and uses no CDN.
    assert 'await fetch(path, opts)' not in html
    assert '<title>Westlake TransVerse</title>' in html
    (OUT / 'index.html').write_text(html)
    (OUT / '.nojekyll').touch()
    shutil.copyfile(ROOT / 'THIRD_PARTY.md', OUT / 'THIRD_PARTY.md')
    print('Built static site:', OUT)
    print('No model requests, secrets, or participant records are used by the page.')


if __name__ == '__main__':
    main()
