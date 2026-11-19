/* Only opaque cosmetic coordinates and already-public labels enter this module. */
(function () {
  'use strict';
  const worlds = __TV_PUBLIC_ART__;
  let context = {universe:1, episode:1, encounter:0, monster_id:null};
  const classes = [
    ['.bevel,.hud,.tray,.hud-side,.hud-turn', 'tv-panel'],
    ['.key', 'tv-button'], ['input,select,textarea,.raw-form', 'tv-field'],
    ['.choice', 'tv-card'], ['.viewport', 'tv-scene'],
    ['.hud-name,.plate-text', 'tv-tag'], ['.transcript', 'tv-record'],
    ['.slot,.hud-turn-n,.card-name,.card-mark,.note-input', 'tv-value'],
    ['.wordmark,.title-word', 'tv-display']
  ];
  function world() { return worlds.find(w => w.universe === context.universe); }
  function decorate() {
    for (const node of document.querySelectorAll('.wordmark,.title-word')) {
      if (node.textContent !== 'TransVerse') node.textContent = 'TransVerse';
    }
    for (const [selector, name] of classes) {
      for (const node of document.querySelectorAll(selector)) {
        if (!node.classList.contains(name)) node.classList.add(name);
      }
    }
    for (const button of document.querySelectorAll('#commands button')) {
      if (button.textContent.trim().toUpperCase() === 'END' && !button.classList.contains('tv-end')) button.classList.add('tv-end');
    }
    document.body.dataset.universe = String(context.universe);
    document.body.dataset.episode = String(context.episode);
    document.body.dataset.encounter = String(context.encounter);
    const dialogue = document.getElementById('context');
    const journal = document.querySelector('.journal');
    const transcript = document.getElementById('transcript');
    const inEncounter = document.body.dataset.phase === 'act';
    if (dialogue && journal && transcript) {
      dialogue.classList.toggle('tv-feedback', inEncounter);
      if (inEncounter && dialogue.parentElement !== journal) journal.insertBefore(dialogue, transcript);
      if (!inEncounter && dialogue.parentElement !== document.getElementById('viewport')) document.getElementById('viewport').append(dialogue);
      dialogue.setAttribute('aria-label', inEncounter ? 'Latest feedback' : 'Context');
    }
    const viewport = document.getElementById('viewport');
    if (viewport) {
      const value = 'url("' + world().backdrop + '")';
      if (viewport.style.backgroundImage !== value) viewport.style.backgroundImage = value;
    }
    const host = document.getElementById('idol');
    const monster = world().monsters.find(m => m.id === context.monster_id);
    if (host && monster && !host.hidden && !host.classList.contains('training-post')) {
      let image = host.querySelector('img.tv-monster');
      if (!image || image.dataset.monster !== monster.id) {
        image = document.createElement('img'); image.className = 'tv-monster';
        image.src = monster.image; image.alt = ''; image.setAttribute('aria-hidden', 'true');
        image.dataset.monster = monster.id; host.replaceChildren(image);
      }
    }
  }
  function setContext(value) {
    if (!value || !Number.isInteger(value.universe) || value.universe < 1 || value.universe > 5) return;
    context = {...context, ...value}; decorate();
  }
  function observeHeader(text) {
    const match = /^World (\d+), (?:Life (\d+)|Camp|Letter)\s*$/m.exec(text || '');
    if (match) {
      const universe = Number(match[1]);
      if (universe >= 1 && universe <= 5) setContext({universe, episode:Number(match[2] || 1)});
    }
  }
  let queued = false;
  new MutationObserver(() => {
    if (!queued) { queued = true; queueMicrotask(() => { queued = false; decorate(); }); }
  }).observe(document.body, {childList:true, subtree:true});
  window.TVSkins = Object.freeze({setContext, observeHeader, decorate,
    applyCurrent:decorate, metadata:() => ({...context})});
  decorate();
})();
