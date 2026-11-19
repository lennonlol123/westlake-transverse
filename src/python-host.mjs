// Shared by the browser Worker and the Node/WASM verification harness.
export async function loadGame(indexURL, readJSON, readBytes, progress = () => {}) {
  progress('Loading the browser Python runtime…');
  const {loadPyodide} = await import(new URL('pyodide.mjs', indexURL).href);
  const runtimePath = indexURL.protocol === 'file:' ? decodeURIComponent(indexURL.pathname) : indexURL.href;
  const py = await loadPyodide({indexURL:runtimePath, stdout: () => {}, stderr: () => {}});
  progress('Loading the exact note tokenizer…');
  await py.loadPackage(['tiktoken', 'ssl']);
  const bundle = await readJSON('engine-bundle.json');
  for (const [name, text] of Object.entries(bundle.files)) {
    if (name.includes('..') || name.startsWith('/')) throw new Error('Invalid engine asset path');
    const path = '/app/' + name;
    py.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')));
    py.FS.writeFile(path, text);
  }
  py.FS.mkdirTree('/token-cache');
  py.FS.writeFile('/token-cache/fb374d419588a4632f3f557e76b4b70aebbca790', await readBytes('data/o200k_base.tiktoken'));
  py.runPython(`
import os, sys
os.environ['TIKTOKEN_CACHE_DIR'] = '/token-cache'
sys.path.insert(0, '/app/src')
# Research-only solver/ledger modules import POSIX locks. They are never used
# by the human path. Fail closed if a future change attempts to use them.
import types
def unsupported_posix_lock(*args, **kwargs):
    raise RuntimeError('POSIX file locking is unavailable in the browser game')
lock_module = types.ModuleType('fcntl')
lock_module.LOCK_EX, lock_module.LOCK_SH, lock_module.LOCK_UN = 2, 1, 8
lock_module.flock = unsupported_posix_lock
sys.modules['fcntl'] = lock_module
import browser_runtime, json
`);
  return {
    step(payload) {
      py.globals.set('tv_input_json', JSON.stringify(payload));
      try { return JSON.parse(py.runPython('json.dumps(browser_runtime.step(json.loads(tv_input_json)))')); }
      finally { py.globals.delete('tv_input_json'); }
    },
    py,
  };
}
