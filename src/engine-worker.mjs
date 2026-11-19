import {loadGame} from './python-host.mjs';
const root = new URL('../', import.meta.url);
const ready = loadGame(new URL('vendor/pyodide/', root),
  async path => { const r = await fetch(new URL(path, root)); if (!r.ok) throw new Error('Missing game asset: ' + path); return r.json(); },
  async path => { const r = await fetch(new URL(path, root)); if (!r.ok) throw new Error('Missing tokenizer'); return new Uint8Array(await r.arrayBuffer()); },
  text => postMessage({progress:text}));
let queue = Promise.resolve();
self.onmessage = ({data}) => {
  queue = queue.then(async () => {
    try { const game = await ready; postMessage({id:data.id, result:game.step(data.payload)}); }
    catch (error) { postMessage({id:data.id, error:String(error.message || error)}); }
  });
};
