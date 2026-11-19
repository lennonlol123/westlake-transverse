import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {loadGame} from '../src/python-host.mjs';
const root = new URL('../', import.meta.url);
const host = await loadGame(new URL('vendor/pyodide/', root),
  async p => JSON.parse(await fs.readFile(new URL('dist/' + p, root), 'utf8')),
  async p => new Uint8Array(await fs.readFile(new URL(p, root))), console.log);
const initial = host.step({universe:1, actions:[]});
assert.equal(initial.complete,false);
assert.match(initial.events[0].text,/World 1, Camp/);
const left = host.step({universe:1, actions:['leave']});
assert.equal(left.events.at(-1).kind,'note');
const first = host.step({universe:1, actions:['leave','My camp note.']});
assert.equal(first.events.at(-1).kind,'act');
assert.match(first.events.at(-1).text,/My camp note/);
assert.equal(first.events.at(-1).visual.universe,1);
const repeat = host.step({universe:1, actions:['leave','My camp note.']});
assert.deepEqual(repeat.events,first.events);
console.log('WASM: camp, note, first encounter, artwork selection and deterministic refresh passed');
const golden = JSON.parse(await fs.readFile(new URL('native-golden.json', import.meta.url),'utf8'));
const finished = host.step({universe:1, actions:golden.actions});
assert.equal(finished.complete,true);
assert.deepEqual(finished.events,golden.events,'Native Python and browser WASM must expose identical events');
const next = host.step({universe:2,actions:[],baseline:finished.files});
assert.equal(next.complete,false);
assert.match(next.events[0].text,/World 2, Life 1/);
assert.equal(next.events[0].visual.universe,2);
console.log('WASM: complete U1 matches native Python event-for-event; U2 letter handoff and skin passed');
