"""Verify the explicit public bundle, its hashes and static deployment inputs."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    for row in json.loads((ROOT / 'docs/source-manifest.json').read_text()):
        p = ROOT / 'engine' / row['file']
        assert hashlib.sha256(p.read_bytes()).hexdigest() == row['bundled_sha256'], p
    runtime = json.loads((ROOT / 'docs/runtime-manifest.json').read_text())
    for name, sha in runtime['files'].items():
        assert hashlib.sha256((ROOT / 'vendor/pyodide' / name).read_bytes()).hexdigest() == sha, name
    assert hashlib.sha256((ROOT / 'data/o200k_base.tiktoken').read_bytes()).hexdigest() == '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
    html = (ROOT / 'dist/index.html').read_text()
    assert '<title>Westlake TransVerse</title>' in html
    assert '<span class="wordmark">TransVerse</span>' in html
    assert '<h1 id="demoTitle">Westlake TransVerse</h1>' in html
    assert 'window.TVLocal.request(path, body)' in html
    # Exact HTML element, not the literal <body> example in a CSS comment.
    assert html.index('<section id="demoWelcome"') > html.index('</head>')
    assert 'src="http' not in html
    bundle = json.loads((ROOT / 'dist/engine-bundle.json').read_text())
    assert not any('/runs/' in p or '/results/' in p or p.endswith('.key') for p in bundle['files'])
    for name, text in bundle['files'].items():
        assert not re.search(r'sk-(?:or-v1-)?[A-Za-z0-9_-]{25,}', text), name
    print('Release checks passed: source/runtime hashes, exact tokenizer, branding, no private records or credential literals.')


if __name__ == '__main__':
    main()
