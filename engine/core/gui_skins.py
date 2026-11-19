"""Opt-in cosmetic skins; never derive artwork from opponent mechanics."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import base64
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path

VERSION = 'transverse-skins-v1-2026-11-19'
ROOT = Path(__file__).resolve().parent / 'gui'
ASSETS = ROOT / 'transverse_skins'
_current = ContextVar('gui_skin_encounter', default=None)


def enabled():
    value = os.environ.get('AGII_GUI_SKIN', '')
    if value not in ('', 'legacy', VERSION):
        raise ValueError('Unknown GUI skin version.')
    return value == VERSION


@lru_cache(maxsize=1)
def manifest():
    return json.loads((ASSETS / 'manifest.json').read_text())


def hash32(text):
    result = 0x811c9dc5
    for character in text:
        result = ((result ^ ord(character)) * 0x01000193) & 0xffffffff
    return result


def select(universe, map_seed, encounter_index, episode=1):
    """Match assign.js exactly. Episode changes scenery context, not monster choice."""
    if not (1 <= int(universe) <= 5 and 1 <= int(episode) <= 4 and 1 <= int(encounter_index) <= 8):
        raise ValueError('Invalid cosmetic encounter coordinates.')
    world = next(w for w in manifest()['worlds'] if w['universe'] == int(universe))
    index = hash32(f'{int(universe)}:{int(map_seed)}:{int(encounter_index)}') % len(world['monsters'])
    monster = world['monsters'][index]
    # Do not forward the map seed, descriptive monster names, hidden state, or rules.
    return dict(version=VERSION, universe=int(universe), episode=int(episode),
                encounter=int(encounter_index), monster_id=monster['id'])


@contextmanager
def encounter(universe, episode, map_seed, encounter_index):
    metadata = select(universe, map_seed, encounter_index, episode) if enabled() else None
    token = _current.set(metadata)
    try:
        yield metadata
    finally:
        _current.reset(token)


def public_metadata():
    metadata = _current.get()
    return dict(metadata) if metadata else None


def audit_metadata(universe, episode, map_seed, encounters):
    return dict(version=VERSION, condition='human-skinned-gui',
                source_sha256=hashlib.sha256((ASSETS / 'manifest.json').read_bytes()).hexdigest(),
                encounters=[select(universe, map_seed, i, episode) for i in range(1, len(encounters) + 1)])


@lru_cache(maxsize=1)
def public_art():
    def svg(file):
        return 'data:image/svg+xml;base64,' + base64.b64encode((ASSETS / file).read_bytes()).decode()
    return [dict(universe=w['universe'], world=w['world'], backdrop=svg(w['backdrop']),
                 monsters=[dict(id=m['id'], image=svg(m['file'])) for m in w['monsters']])
            for w in manifest()['worlds']]


def page(original):
    """Decorate the existing document without moving or wrapping any game element."""
    font = base64.b64encode((ROOT / 'retro-font.woff').read_bytes()).decode()
    css = "@font-face{font-family:'TV Mono';src:url(data:font/woff;base64," + font + ") format('woff');font-display:block;}\n"
    css += (ASSETS / 'skins.css').read_text() + '\n' + (ROOT / 'skin-adapter.css').read_text()
    script = (ROOT / 'skin-adapter.js').read_text().replace('__TV_PUBLIC_ART__', json.dumps(public_art(), separators=(',', ':')))
    original = original.replace('</head>', '<style>' + css + '</style></head>')
    # Runtime must exist before the original client starts polling.
    marker = "  <script>\n    'use strict';\n    const $"
    if marker not in original:
        raise ValueError('Cannot locate the GUI client bootstrap.')
    return original.replace(marker, '  <script>' + script + '</script>\n' + marker, 1)
