"""The review page: one self-contained HTML document that talks to review_server over fetch."""

from __future__ import annotations

TOKEN_PLACEHOLDER = "__TOKEN__"

PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PhotoPass Review</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f4fa; --card: #ffffff; --fg: #1c1b33; --muted: #5f5e7a; --line: #d6d5e6;
    --accent: #3d5fd9; --on-accent: #ffffff; --cta: #e8562a; --bad: #c53030;
    --mine: #2f6fde; --friends: #8a4fd6; --ignored: #6b6b7c; --undecided: #f2b23a; --on-undecided: #2a1c00;
    --rail-a: #2a2783; --rail-b: #2c4a9c; --rail-fg: #ffffff;
    --display: ui-rounded, "SF Pro Rounded", -apple-system, system-ui, sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #1f1f24; --card: #29292f; --fg: #f2f2f6; --muted: #a9a9b8; --line: #3d3d49; --accent: #6f8df7; --on-accent: #0d1330; }
  }
  * { box-sizing: border-box; }
  body { font: 15px/1.4 -apple-system, system-ui, sans-serif; margin: 0; color: var(--fg); background: linear-gradient(160deg, var(--rail-a), var(--rail-b)); display: grid; grid-template-columns: 270px minmax(0, 1fr); min-height: 100vh; }
  button { font: inherit; padding: 7px 14px; border-radius: 999px; border: 1px solid var(--line); background: transparent; color: inherit; cursor: pointer; }
  button:disabled { opacity: .4; cursor: default; }
  button:focus-visible, select:focus-visible, .chip:focus-within { outline: 2px solid var(--cta); outline-offset: 2px; }
  button.primary { background: var(--cta); color: #fff; border-color: var(--cta); font-weight: 700; }
  button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }

  #bar { color: var(--rail-fg); padding: 20px 16px; display: flex; flex-direction: column; gap: 14px; height: 100vh; position: sticky; top: 0; align-self: start; overflow-y: auto;
    background-image: radial-gradient(rgba(255,255,255,.07) 1.5px, transparent 1.6px); background-size: 22px 22px; }
  #bar h1 { font: 700 21px/1.2 var(--display); margin: 0; }
  #bar button { border-color: rgba(255,255,255,.4); width: 100%; }
  #bar button.primary { border-color: var(--cta); }
  #bar button.stat { border: 0; border-bottom: 1px solid rgba(255,255,255,.14); border-radius: 0; text-align: left; font-size: inherit; }
  #bar button.stat:hover { background: rgba(0,0,0,.2); }
  #bar button.stat[aria-pressed="true"] { background: rgba(0,0,0,.4); color: inherit; border-radius: 8px; padding-left: 8px; padding-right: 8px; }
  #status { font-weight: 600; min-height: 1.4em; overflow-wrap: anywhere; }
  #status.error { background: var(--bad); border-radius: 8px; padding: 6px 10px; }
  #counts, #breakdown { font-size: 14px; }
  #bar h2 { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; opacity: .75; margin: 10px 0 2px; }
  #bar h2:first-child { margin-top: 0; }
  #bar .stat { display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,.14); font-variant-numeric: tabular-nums; }
  #bar .stat strong { font-family: var(--display); }
  #bar .stat.attention strong { background: var(--undecided); color: var(--on-undecided); border-radius: 999px; padding: 0 8px; }
  #tripnav { display: flex; flex-direction: column; gap: 4px; }
  #tripnav a { color: inherit; text-decoration: none; padding: 6px 12px; border-radius: 999px; display: flex; justify-content: space-between; gap: 8px; align-items: center; font-size: 14px; }
  #tripnav a:hover { background: rgba(0,0,0,.25); }
  #tripnav small { opacity: .75; }
  #tripnav em { font-style: normal; background: var(--undecided); color: var(--on-undecided); border-radius: 999px; padding: 0 8px; font-size: 12px; font-weight: 700; }
  .railbuttons { display: flex; flex-direction: column; gap: 8px; }

  main { background: var(--bg); border-top-left-radius: 22px; padding: 8px 22px 48px; min-width: 0; min-height: 100vh; }
  .trip { margin-top: 22px; scroll-margin-top: 12px; }
  .empty { color: var(--muted); margin: 22px 0 0; }
  .filterbar { margin: 16px 0 0; padding: 8px 8px 8px 14px; border-radius: 999px; background: var(--card); display: flex; align-items: center; justify-content: space-between; gap: 10px; font-weight: 600; }
  .trip header { display: flex; justify-content: space-between; align-items: baseline; gap: 10px 12px; flex-wrap: wrap; margin-bottom: 4px; }
  .trip h2 { margin: 0; font: 700 21px/1.2 var(--display); }
  .trip h2 small { font: 400 14px/1.2 -apple-system, system-ui, sans-serif; color: var(--muted); }
  .trip .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .day { display: grid; grid-template-columns: 310px minmax(0, 1fr); gap: 18px; background: var(--card); border-radius: 14px; padding: 14px; margin-top: 12px; }
  .day .left { display: flex; flex-direction: column; gap: 9px; align-items: flex-start; }
  .day h3 { margin: 0; font: 700 16px/1.25 var(--display); }
  .day p { margin: 0; color: var(--muted); }
  select.states { font: inherit; font-weight: 700; padding: 6px 30px 6px 14px; border-radius: 999px; border: 1px solid transparent; color: #fff; cursor: pointer;
    appearance: none; -webkit-appearance: none;
    background-image: linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%);
    background-position: calc(100% - 17px) 55%, calc(100% - 12px) 55%; background-size: 5px 5px; background-repeat: no-repeat; }
  select.states[data-state="mine"] { background-color: var(--mine); }
  select.states[data-state="friends"] { background-color: var(--friends); }
  select.states[data-state="ignored"] { background-color: var(--ignored); }
  select.states[data-state="undecided"] { background-color: var(--undecided); color: var(--on-undecided); }
  select.states option { color: initial; background: initial; font-weight: 400; }
  .hint { font-size: 13px; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 5px 6px; align-items: center; }
  .chip { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px 2px 6px; font-size: 13px; cursor: pointer; }
  .chip:has(input:checked) { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
  .chip:has(input:disabled) { opacity: .4; cursor: default; }
  .chip.preticked { border-style: dashed; }
  .chip input { margin: 0 3px 0 0; }
  .newfriend { font-size: 13px; border-style: dashed; padding: 2px 10px; }
  .friendform { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
  .friendform input, .friendform select { font: inherit; font-size: 13px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: inherit; }
  .friendform .formerror { color: var(--bad); font-size: 13px; flex-basis: 100%; }
  .grid { display: flex; flex-wrap: wrap; gap: 8px; align-content: flex-start; }
  .tile { position: relative; width: 150px; height: 150px; border-radius: 10px; overflow: hidden; background: #8882; cursor: zoom-in; }
  .tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tile .badge { position: absolute; left: 4px; bottom: 4px; background: rgba(0,0,0,.7); color: white; font-size: 11px; padding: 1px 6px; border-radius: 8px; }
  .tile .toggle { position: absolute; right: 5px; top: 5px; padding: 0 7px; line-height: 20px; background: rgba(0,0,0,.6); color: white; border-color: transparent; }
  .tile.handled { filter: grayscale(1); opacity: .5; }
  .tile.ignored img { opacity: .25; }
  .tile.ignored .toggle { background: var(--bad); }
  .tile.kept { outline: 3px solid var(--accent); }
  .tile.kept .toggle { background: var(--accent); }
  .tile .toggle.keep { right: auto; left: 5px; }
  .busy { pointer-events: none; opacity: .5; }
  details#stock { margin-top: 28px; background: var(--card); border-radius: 14px; padding: 12px 14px; }
  details#stock summary { cursor: pointer; font: 700 17px var(--display); }
  details#stock .grid { margin-top: 10px; }
  #settings { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: none; align-items: flex-start; justify-content: center; z-index: 9; overflow-y: auto; padding: 32px 16px; }
  #settings.open { display: flex; }
  #settings form { background: var(--card); color: var(--fg); border-radius: 16px; padding: 20px 22px; width: min(640px, 100%); display: flex; flex-direction: column; gap: 12px; }
  #settings h2 { margin: 0; font: 700 20px var(--display); }
  #settings .path { margin: 0; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  #settingsFields { display: flex; flex-direction: column; gap: 12px; }
  #settings .field { display: flex; flex-direction: column; gap: 3px; }
  #settings .field.check { flex-direction: row; align-items: flex-start; gap: 8px; }
  #settings .field .name { font-weight: 600; }
  #settings .field small { color: var(--muted); }
  #settings input[type="text"], #settings select { font: inherit; padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: inherit; width: 100%; }
  #settings .formerror { color: var(--bad); margin: 0; min-height: 1.2em; }
  #settings .formbuttons { display: flex; justify-content: flex-end; gap: 8px; }
  #lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.92); display: none; align-items: center; justify-content: center; z-index: 10; }
  #lightbox.open { display: flex; }
  #lightbox .stage img, #lightbox .stage video { max-width: 98vw; max-height: 90vh; object-fit: contain; display: block; }
  #lightbox .stage img { cursor: zoom-out; }
  #lightbox.ignored .stage img, #lightbox.ignored .stage video { opacity: .3; }
  #lightbox .caption { position: absolute; bottom: 10px; left: 0; right: 0; text-align: center; color: #eee; font-size: 13px; }
  #lightbox .controls { position: absolute; top: 10px; right: 10px; display: flex; gap: 8px; }
  #lightbox .controls button { color: white; border-color: #fff6; background: rgba(0,0,0,.5); }
  @media (max-width: 900px) {
    body { display: block; }
    #bar { height: auto; position: static; }
    main { border-top-left-radius: 0; padding: 4px 14px 40px; }
    .day { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div id="bar">
  <h1>PhotoPass Review</h1>
  <div id="status">Loading...</div>
  <div class="railbuttons">
  <button type="button" id="runAll" class="primary">Organize all decided days</button>
  <button type="button" id="showHandled" aria-pressed="false" title="Photos you already kept, shared or deleted earlier. They are removed from the source folder as duplicates.">Show previously processed</button>
  <button type="button" id="openSettings">Settings</button>
  <button type="button" id="done">Done</button>
  </div>
  <div id="counts"></div>
  <div id="breakdown"></div>
  <nav id="tripnav" aria-label="Trips"></nav>
</div>
<main>
<div id="trips"></div>
<details id="stock"><summary>Stock art</summary><div class="grid" id="stockGrid"></div></details>
</main>
<div id="lightbox">
  <div class="stage"></div>
  <div class="caption"></div>
  <div class="controls"><button type="button" id="lightboxToggle">Ignore (x)</button><button type="button" id="lightboxClose">Close (Esc)</button></div>
</div>
<div id="settings" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
  <form id="settingsForm">
    <h2 id="settingsTitle">Settings</h2>
    <p class="path" id="settingsPath"></p>
    <div id="settingsFields"></div>
    <p class="formerror" id="settingsError"></p>
    <div class="formbuttons"><button type="button" id="settingsCancel">Cancel</button><button type="submit" class="primary">Save settings</button></div>
  </form>
</div>
<script>
const SAVE_DELAY_MS = 800;
const NEWLINE = String.fromCharCode(10);

const statusEl = document.getElementById('status');
const countsEl = document.getElementById('counts');
const tripsEl = document.getElementById('trips');
const tripNavEl = document.getElementById('tripnav');
const breakdownEl = document.getElementById('breakdown');
const stockEl = document.getElementById('stock');
const stockGridEl = document.getElementById('stockGrid');
const runAllButton = document.getElementById('runAll');
const showHandledButton = document.getElementById('showHandled');
const doneButton = document.getElementById('done');
const lightboxEl = document.getElementById('lightbox');
const lightboxStage = lightboxEl.querySelector('.stage');
const lightboxCaption = lightboxEl.querySelector('.caption');
const lightboxToggleButton = document.getElementById('lightboxToggle');

let friends = [];
let addedFriends = [];
let trips = [];
let stock = [];
let overrides = new Map();
let handledHashes = new Set();
let dayEntries = new Map();
let showHandled = false;
let lastCounts = null;
let undecidedAtLoad = 0;
let saveTimer = null;
let saveChain = Promise.resolve();
let savesInFlight = 0;
let revision = 0;
let lastSaveOk = true;
let running = false;
let busy = false;
let lastSaveError = '';
let finished = false;
let gallery = null;
let filter = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function dayKey(day) {
  return day.date + '|' + day.park;
}

function setStatus(text, isError) {
  statusEl.textContent = text;
  statusEl.className = isError ? 'error' : '';
}

const COUNT_LABELS = [
  ['keep', 'Keep'], ['delete', 'Delete after sharing'], ['ignore', 'Ignore'],
  ['duplicates', 'Duplicates'], ['stock', 'Stock art'], ['undecided', 'Undecided'],
];

const COUNT_FILTERS = {
  keep: ['state', 'mine'], delete: ['state', 'friends'], ignore: ['state', 'ignored'],
  duplicates: ['processed', 'all'], stock: ['stock', 'all'], undecided: ['state', 'undecided'],
};

function countRows(counts) {
  const shares = Object.keys(counts.share).sort().map((name) => ['Share with ' + name, counts.share[name], false, 'friend', name]);
  const rest = COUNT_LABELS.map(([key, label]) => [label, counts[key], key === 'undecided' && counts[key] > 0].concat(COUNT_FILTERS[key]));
  return shares.concat(rest);
}

function formatCounts(counts) {
  return countRows(counts).map(([label, value]) => label + ' ' + value).join(', ');
}

function showCounts() {
  countsEl.textContent = '';
  const rows = lastCounts ? countRows(lastCounts) : [['Undecided days', undecidedAtLoad, undecidedAtLoad > 0]];
  countsEl.appendChild(el('h2', '', 'What organizing will do'));
  for (const [label, value, attention, kind, filterValue] of rows) countsEl.appendChild(statRow(label, value, attention, kind, filterValue));
}

function statRow(label, value, attention, kind, filterValue) {
  const row = el(kind ? 'button' : 'div', 'stat' + (attention ? ' attention' : ''));
  row.appendChild(el('span', '', label));
  row.appendChild(el('strong', '', String(value)));
  if (kind) {
    row.type = 'button';
    row.title = 'Show only these';
    const active = Boolean(filter) && filter.kind === kind && filter.value === filterValue;
    row.setAttribute('aria-pressed', String(active));
    row.addEventListener('click', () => {
      if (kind === 'stock') {
        stockEl.open = true;
        stockEl.scrollIntoView({ behavior: 'smooth' });
      } else setFilter(kind, filterValue, label);
    });
  }
  return row;
}

function renderBreakdown() {
  const places = new Map();
  let photos = 0;
  let videos = 0;
  for (const trip of trips) {
    for (const day of trip.days) {
      const place = day.label || day.park;
      places.set(place, (places.get(place) || 0) + day.new.length);
      for (const item of day.new) {
        if (item.is_video) videos += 1;
        else photos += 1;
      }
    }
  }
  breakdownEl.textContent = '';
  breakdownEl.appendChild(el('h2', '', 'New by park or event'));
  for (const place of Array.from(places.keys()).sort()) breakdownEl.appendChild(statRow(place, places.get(place), false, 'place', place));
  breakdownEl.appendChild(el('h2', '', 'New by type'));
  breakdownEl.appendChild(statRow('Photos', photos, false, 'type', 'photo'));
  breakdownEl.appendChild(statRow('Videos', videos, false, 'type', 'video'));
}

function renderTripNav() {
  tripNavEl.textContent = '';
  trips.forEach((trip, index) => {
    if (!listedDays(trip).length) return;
    const link = el('a');
    link.href = '#trip-' + index;
    link.appendChild(el('span', '', trip.start === trip.end ? trip.start : trip.start + ' to ' + trip.end));
    const open = undecidedDays([trip]).length;
    link.appendChild(open ? el('em', '', String(open)) : el('small', '', 'all set'));
    link.title = open ? open + ' undecided' : 'Every day is decided';
    tripNavEl.appendChild(link);
  });
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { error: 'bad response from the server (' + response.status + ')' };
  }
  return { ok: response.ok, status: response.status, data };
}

const CHOICES = [
  ['undecided', 'Undecided'], ['with', 'I was there with friends'], ['solo', 'I was there solo'],
  ['away', 'I was not there'], ['ignored', 'Ignore date'],
];
const CHOICE_STATE = { undecided: 'undecided', with: 'mine', solo: 'mine', away: 'friends', ignored: 'ignored' };

function choiceFor(decision) {
  if (decision.state === 'mine') return decision.friends.length ? 'with' : 'solo';
  return decision.state === 'friends' ? 'away' : decision.state;
}

function effectiveState(decision) {
  if (decision.state === 'friends' && decision.friends.length === 0) return 'undecided';
  return decision.state;
}

function isIgnored(item) {
  const override = overrides.get(item.hash);
  return override !== undefined && override.action === 'ignore';
}

function isKept(item) {
  const override = overrides.get(item.hash);
  return override !== undefined && override.action === 'keep';
}

function buildSaveBody() {
  const days = [];
  for (const entry of dayEntries.values()) {
    const state = effectiveState(entry.decision);
    days.push({
      date: entry.day.date,
      park: entry.day.park,
      state,
      friends: state === 'ignored' || state === 'undecided' ? [] : entry.decision.friends.slice(),
    });
  }
  return { days, photos: Array.from(overrides.values()), friends: addedFriends.slice() };
}

function pendingSave() {
  return saveTimer !== null || savesInFlight > 0;
}

function scheduleSave() {
  if (busy) return;
  revision += 1;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, SAVE_DELAY_MS);
  setStatus('Saving...');
}

function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  saveChain = saveChain.then(performSave);
  return saveChain;
}

async function performSave() {
  const sentRevision = revision;
  savesInFlight += 1;
  setStatus('Saving...');
  try {
    const result = await postJson('/__TOKEN__/api/save', buildSaveBody());
    if (result.ok) {
      lastSaveOk = true;
      lastCounts = result.data.counts;
      showCounts();
      if (sentRevision === revision) setStatus('Saved');
    } else {
      lastSaveOk = false;
      lastSaveError = result.data.error || 'Save failed (' + result.status + ')';
      setStatus(lastSaveError, true);
    }
  } catch (error) {
    lastSaveOk = false;
    lastSaveError = 'Save failed: ' + error.message;
    setStatus(lastSaveError, true);
  } finally {
    savesInFlight -= 1;
  }
}

async function flushSave() {
  do {
    if (saveTimer !== null || !lastSaveOk) saveNow();
    await saveChain;
  } while (saveTimer !== null);
  return lastSaveOk;
}

async function refreshCounts() {
  try {
    const result = await postJson('/__TOKEN__/api/save', {});
    if (result.ok) lastCounts = result.data.counts;
  } catch (error) {
    lastCounts = null;
  }
  showCounts();
}

function setBusy(on) {
  busy = on;
  doneButton.disabled = on;
  document.getElementById('openSettings').disabled = on;
  for (const node of [tripsEl, stockEl]) {
    node.classList.toggle('busy', on);
    if (on) node.setAttribute('inert', '');
    else node.removeAttribute('inert');
  }
  if (on) setStatus('Organizing...');
}

window.addEventListener('beforeunload', (event) => {
  if (!finished && pendingSave()) {
    event.preventDefault();
    event.returnValue = 'Changes are still being saved.';
  }
});

function loadModel(state) {
  friends = state.friends;
  trips = state.trips;
  stock = state.stock;
  undecidedAtLoad = state.undecided_count;
  overrides = new Map();
  handledHashes = new Set();
  dayEntries = new Map();
  for (const trip of trips) {
    for (const day of trip.days) {
      dayEntries.set(dayKey(day), { day, decision: { state: day.decision.state, friends: day.decision.friends.slice(), choice: choiceFor(day.decision) } });
      for (const item of day.handled) handledHashes.add(item.hash);
      for (const item of day.new.concat(day.handled)) {
        if (item.ignored) overrides.set(item.hash, { hash: item.hash, action: 'ignore', name: item.name });
      }
    }
  }
  for (const item of stock) {
    if (item.keep) overrides.set(item.hash, { hash: item.hash, action: 'keep', name: item.name });
  }
}

async function loadState() {
  const response = await fetch('/__TOKEN__/api/state');
  if (!response.ok) throw new Error('state request failed (' + response.status + ')');
  loadModel(await response.json());
  renderTrips();
  renderStock();
  showCounts();
  saveChain = saveChain.then(refreshCounts);
  await saveChain;
}

function baseItems(day) {
  return showHandled ? day.new.concat(day.handled) : day.new;
}

function listedDays(trip) {
  return trip.days.filter((day) => baseItems(day).length > 0);
}

function dayMatches(day) {
  if (!filter) return true;
  const decision = dayEntries.get(dayKey(day)).decision;
  const state = effectiveState(decision);
  if (filter.kind === 'place') return (day.label || day.park) === filter.value;
  if (filter.kind === 'state') return state === filter.value;
  if (filter.kind === 'friend') return (state === 'mine' || state === 'friends') && decision.friends.includes(filter.value);
  return true;
}

function visibleItems(day) {
  if (filter && filter.kind === 'processed') return day.handled;
  const items = baseItems(day);
  if (filter && filter.kind === 'type') return items.filter((item) => Boolean(item.is_video) === (filter.value === 'video'));
  return items;
}

function shownDays(trip) {
  return trip.days.filter((day) => dayMatches(day) && visibleItems(day).length > 0);
}

function setFilter(kind, value, label) {
  const same = filter && filter.kind === kind && filter.value === value;
  filter = same ? null : { kind, value, label };
  renderTrips();
  showCounts();
  window.scrollTo(0, 0);
}

function syncTile(hash) {
  for (const tile of document.querySelectorAll('.tile')) {
    if (tile.dataset.hash !== hash) continue;
    tile.classList.toggle('ignored', overrides.has(hash) && overrides.get(hash).action === 'ignore');
    tile.classList.toggle('kept', overrides.has(hash) && overrides.get(hash).action === 'keep');
  }
}

function toggleIgnore(item) {
  if (isIgnored(item)) overrides.delete(item.hash);
  else overrides.set(item.hash, { hash: item.hash, action: 'ignore', name: item.name });
  syncTile(item.hash);
  scheduleSave();
}

function toggleKeep(item) {
  if (isKept(item)) overrides.delete(item.hash);
  else overrides.set(item.hash, { hash: item.hash, action: 'keep', name: item.name });
  syncTile(item.hash);
  scheduleSave();
}

function buildTile(item, items, options) {
  const tile = el('div', 'tile');
  tile.dataset.hash = item.hash;
  const handled = handledHashes.has(item.hash);
  if (handled) tile.classList.add('handled');
  const image = el('img');
  image.loading = 'lazy';
  image.alt = item.name;
  image.src = '/__TOKEN__/thumb/' + item.hash;
  tile.appendChild(image);
  if (item.is_video) tile.appendChild(el('span', 'badge', 'video'));
  const toggle = el('button', 'toggle' + (options.keep ? ' keep' : ''), options.keep ? 'Keep' : 'x');
  toggle.type = 'button';
  toggle.title = options.keep ? 'Keep this stock photo' : 'Ignore this photo';
  toggle.disabled = handled && !options.keep;
  toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    if (options.keep) toggleKeep(item);
    else toggleIgnore(item);
  });
  tile.appendChild(toggle);
  tile.addEventListener('click', () => openLightbox(items, items.indexOf(item), options));
  tile.classList.toggle('ignored', isIgnored(item));
  tile.classList.toggle('kept', isKept(item));
  return tile;
}

function renderGrid(entry, grid) {
  grid.textContent = '';
  const items = visibleItems(entry.day);
  for (const item of items) {
    grid.appendChild(buildTile(item, items, { keep: false }));
  }
}

function renderStock() {
  stockGridEl.textContent = '';
  stockEl.querySelector('summary').textContent = 'Stock art (' + stock.length + ')';
  for (const item of stock) {
    stockGridEl.appendChild(buildTile(item, stock, { keep: true }));
  }
}

function syncDay(entry) {
  const shown = effectiveState(entry.decision);
  const root = entry.root;
  const choice = entry.decision.choice;
  const select = root.querySelector('.states');
  select.value = choice;
  select.dataset.state = shown;
  const picksFriends = choice === 'with' || choice === 'away';
  root.querySelector('.friendpick').hidden = !picksFriends;
  for (const box of root.querySelectorAll('.chips input')) {
    box.checked = entry.decision.friends.includes(box.value);
    box.disabled = shown === 'ignored';
  }
  const hint = root.querySelector('.hint');
  hint.hidden = !(picksFriends && entry.decision.friends.length === 0);
  hint.textContent = choice === 'away' ? 'Select at least one friend, or this date stays undecided.' : 'Select the friends who were with you.';
  renderTripNav();
}

function chooseState(entry, choice) {
  const decision = entry.decision;
  decision.choice = choice;
  decision.state = CHOICE_STATE[choice];
  const picksFriends = choice === 'with' || choice === 'away';
  if (!picksFriends) decision.friends = [];
  else if (decision.friends.length === 0) {
    decision.friends = entry.day.preticked.filter((name) => friends.some((friend) => friend.name === name));
  }
  syncDay(entry);
  scheduleSave();
}

function chooseFriend(entry, name, ticked) {
  const others = entry.decision.friends.filter((existing) => existing !== name);
  entry.decision.friends = ticked ? others.concat([name]) : others;
  syncDay(entry);
  scheduleSave();
}

function buildStateControls(entry) {
  const select = el('select', 'states');
  select.setAttribute('aria-label', 'Decision for ' + entry.day.date + ' ' + (entry.day.label || entry.day.park));
  for (const [value, label] of CHOICES) {
    const option = el('option', '', label);
    option.value = value;
    select.appendChild(option);
  }
  select.addEventListener('change', () => chooseState(entry, select.value));
  return select;
}

function buildFriendChips(entry) {
  const chips = el('div', 'chips');
  for (const friend of friends) {
    const chip = el('label', 'chip' + (entry.day.preticked.includes(friend.name) ? ' preticked' : ''));
    if (entry.day.preticked.includes(friend.name)) chip.title = 'Already holds some of these photos';
    const box = el('input');
    box.type = 'checkbox';
    box.value = friend.name;
    box.addEventListener('change', () => chooseFriend(entry, friend.name, box.checked));
    chip.appendChild(box);
    chip.appendChild(document.createTextNode(friend.name));
    chips.appendChild(chip);
  }
  const addButton = el('button', 'newfriend', '+ new friend');
  addButton.type = 'button';
  chips.appendChild(addButton);
  const holder = el('div');
  addButton.addEventListener('click', () => {
    if (holder.firstChild) holder.textContent = '';
    else holder.appendChild(buildFriendForm(holder));
  });
  const wrapper = el('div', 'friendpick');
  wrapper.appendChild(chips);
  wrapper.appendChild(holder);
  return wrapper;
}

function buildFriendForm(holder) {
  const form = el('div', 'friendform');
  const nameInput = el('input');
  nameInput.placeholder = 'Name';
  const method = el('select');
  for (const [value, label] of [['folder', 'Shared folder'], ['photos-album', 'Photos album']]) {
    const option = el('option', '', label);
    option.value = value;
    method.appendChild(option);
  }
  const target = el('input');
  target.size = 28;
  const syncPlaceholder = () => { target.placeholder = method.value === 'folder' ? 'Folder path' : 'Album name'; };
  method.addEventListener('change', syncPlaceholder);
  syncPlaceholder();
  const submit = el('button', 'primary', 'Add');
  submit.type = 'button';
  const cancel = el('button', '', 'Cancel');
  cancel.type = 'button';
  const message = el('span', 'formerror');
  cancel.addEventListener('click', () => { holder.textContent = ''; });
  submit.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const where = target.value.trim();
    if (!name || !where) {
      message.textContent = 'Enter a name and a ' + (method.value === 'folder' ? 'folder path' : 'album name');
      return;
    }
    if (friends.some((friend) => friend.name === name)) {
      message.textContent = name + ' is already in the list';
      return;
    }
    const entry = { name, share: method.value };
    entry[method.value === 'folder' ? 'path' : 'album'] = where;
    try {
      const result = await postJson('/__TOKEN__/api/friends', { friends: [entry] });
      if (!result.ok) {
        message.textContent = result.data.error || 'Could not add friend (' + result.status + ')';
        return;
      }
    } catch (error) {
      message.textContent = 'Could not add friend: ' + error.message;
      return;
    }
    friends = friends.concat([{ name, share: method.value, location: where }]);
    addedFriends = addedFriends.concat([entry]);
    renderTrips();
  });
  for (const node of [nameInput, method, target, submit, cancel, message]) form.appendChild(node);
  return form;
}

function buildDay(trip, day) {
  const entry = dayEntries.get(dayKey(day));
  const root = el('div', 'day');
  entry.root = root;
  const left = el('div', 'left');
  left.appendChild(el('h3', '', day.date + ' ' + (day.label || day.park)));
  left.appendChild(el('p', '', day.new.length + ' new, ' + day.handled_count + ' previously processed'));
  left.appendChild(buildStateControls(entry));
  left.appendChild(el('span', 'hint', ''));
  left.appendChild(buildFriendChips(entry));
  const grid = el('div', 'grid');
  entry.grid = grid;
  root.appendChild(left);
  root.appendChild(grid);
  renderGrid(entry, grid);
  syncDay(entry);
  return root;
}

function firstDecidedDay(trip) {
  return listedDays(trip).find((day) => effectiveState(dayEntries.get(dayKey(day)).decision) !== 'undecided');
}

function applyFirstDay(trip) {
  const source = firstDecidedDay(trip);
  if (!source) {
    setStatus('Decide a day in this trip first', true);
    return;
  }
  const sourceDecision = dayEntries.get(dayKey(source)).decision;
  for (const day of listedDays(trip)) {
    const entry = dayEntries.get(dayKey(day));
    if (entry.decision === sourceDecision) continue;
    entry.decision = { state: sourceDecision.state, friends: sourceDecision.friends.slice(), choice: sourceDecision.choice };
    if (entry.root && entry.root.isConnected) syncDay(entry);
  }
  scheduleSave();
}

function undecidedDays(selectedTrips) {
  const lines = [];
  for (const trip of selectedTrips) {
    for (const day of listedDays(trip)) {
      if (effectiveState(dayEntries.get(dayKey(day)).decision) === 'undecided') lines.push(day.date + ' ' + (day.label || day.park));
    }
  }
  return lines;
}

function formatSummary(summary, photos) {
  const keys = ['placed', 'shared', 'deleted', 'duplicates', 'stock', 'ignored', 'undecided'];
  const lines = ['Organized: ' + keys.map((key) => key + ' ' + summary[key]).join(', ')];
  if (photos) {
    lines.push(
      'Photos: imported ' + photos.imported + ', purged ' + photos.purged +
      ', added to friend albums ' + photos.added_to_friend_albums +
      ', friend imports ' + photos.friend_imports
    );
    const failed = photos.failed_by_friend || {};
    for (const friend of Object.keys(failed).sort()) {
      lines.push('Photos could not add ' + failed[friend] + ' photos for ' + friend + '; they are retried the next time that photo is downloaded');
    }
  }
  return lines.join(' | ');
}

async function runDecided(trip) {
  if (running) return;
  running = true;
  setRunDisabled(true);
  try {
    if (!(await flushSave())) {
      setStatus('Fix the error above before organizing: ' + lastSaveError, true);
      return;
    }
    const selected = trip ? [trip] : trips;
    const undecided = undecidedDays(selected);
    const lines = [trip ? 'Organize trip ' + trip.start + ' to ' + trip.end + '?' : 'Organize all decided days?'];
    lines.push(lastCounts ? formatCounts(lastCounts) : 'No counts yet');
    lines.push(undecided.length ? 'Undecided, these are skipped:' : 'No undecided days.');
    for (const line of undecided) lines.push('  ' + line);
    lines.push('Files are moved into place.');
    if (!window.confirm(lines.join(NEWLINE))) return;
    setBusy(true);
    const result = await postJson('/__TOKEN__/api/run', { trip: trip ? { start: trip.start, end: trip.end } : null });
    if (!result.ok) {
      setStatus(result.data.error || 'Organizing failed (' + result.status + ')', true);
      return;
    }
    let reloadError = null;
    try {
      await loadState();
    } catch (error) {
      reloadError = error;
    }
    if (reloadError) setStatus('Organized, but reloading the page state failed: ' + reloadError.message, true);
    else setStatus(formatSummary(result.data.summary, result.data.photos));
  } catch (error) {
    setStatus('Organizing failed: ' + error.message, true);
  } finally {
    setBusy(false);
    running = false;
    setRunDisabled(false);
  }
}

function setRunDisabled(disabled) {
  for (const button of document.querySelectorAll('.runbutton')) button.disabled = disabled;
}

function buildTrip(trip) {
  const section = el('section', 'trip');
  section.id = 'trip-' + trips.indexOf(trip);
  const header = el('header');
  const heading = el('h2', '', trip.start + ' to ' + trip.end + ' ');
  const newCount = trip.days.reduce((total, day) => total + day.new.length, 0);
  const handledCount = trip.days.reduce((total, day) => total + day.handled_count, 0);
  heading.appendChild(el('small', '', trip.resort + ', ' + newCount + ' new, ' + handledCount + ' previously processed'));
  header.appendChild(heading);
  const actions = el('div', 'actions');
  const apply = el('button', '', 'Apply first day to whole trip');
  apply.type = 'button';
  apply.addEventListener('click', () => applyFirstDay(trip));
  const run = el('button', 'runbutton', 'Organize this trip');
  run.type = 'button';
  run.addEventListener('click', () => runDecided(trip));
  actions.appendChild(apply);
  actions.appendChild(run);
  header.appendChild(actions);
  section.appendChild(header);
  for (const day of shownDays(trip)) section.appendChild(buildDay(trip, day));
  return section;
}

function renderTrips() {
  tripsEl.textContent = '';
  if (filter) {
    const banner = el('p', 'filterbar', 'Showing only: ' + filter.label + ' ');
    const clear = el('button', '', 'Show everything');
    clear.type = 'button';
    clear.addEventListener('click', () => setFilter(filter.kind, filter.value, filter.label));
    banner.appendChild(clear);
    tripsEl.appendChild(banner);
  }
  let hidden = 0;
  let built = 0;
  for (const trip of trips) {
    for (const day of trip.days) if (!showHandled) hidden += day.handled_count;
    if (shownDays(trip).length) {
      tripsEl.appendChild(buildTrip(trip));
      built += 1;
    }
  }
  if (!built) {
    const none = filter ? 'Nothing matches.' : hidden ? 'Nothing new to decide.' : 'No PhotoPass photos found in the source folder. Settings shows which folder that is.';
    tripsEl.appendChild(el('p', 'empty', none));
  }
  if (hidden && !filter) {
    tripsEl.appendChild(el('p', 'empty', hidden + ' previously processed photos are hidden; they are removed as duplicates when you organize. "Show previously processed" lists them.'));
  }
  renderTripNav();
  renderBreakdown();
}

function lightboxItem() {
  return gallery.items[gallery.index];
}

function showLightbox() {
  const item = lightboxItem();
  lightboxStage.textContent = '';
  const media = item.is_video ? el('video') : el('img');
  if (item.is_video) media.controls = true;
  media.src = '/__TOKEN__/media/' + item.hash;
  lightboxStage.appendChild(media);
  const ignored = isIgnored(item);
  lightboxEl.classList.toggle('ignored', ignored);
  const position = (gallery.index + 1) + ' of ' + gallery.items.length;
  const time = item.time ? ' (' + item.time + ')' : '';
  const hint = gallery.options.keep ? '' : '  x ignores';
  lightboxCaption.textContent = position + ': ' + item.name + time + (ignored ? '  IGNORED' : '') + '  arrows step, click or Esc closes' + hint;
  lightboxToggleButton.hidden = Boolean(gallery.options.keep);
  lightboxToggleButton.disabled = handledHashes.has(item.hash);
  lightboxToggleButton.textContent = ignored ? 'Restore (x)' : 'Ignore (x)';
}

function stepLightbox(offset) {
  const count = gallery.items.length;
  gallery.index = (gallery.index + offset + count) % count;
  showLightbox();
}

function toggleLightboxIgnore() {
  if (gallery.options.keep || handledHashes.has(lightboxItem().hash)) return;
  toggleIgnore(lightboxItem());
  showLightbox();
}

function onLightboxKey(event) {
  if (busy) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === 'Escape') closeLightbox();
  else if (event.key === 'ArrowLeft') stepLightbox(-1);
  else if (event.key === 'ArrowRight') stepLightbox(1);
  else if (event.key === 'x') toggleLightboxIgnore();
  else return;
  event.preventDefault();
}

function openLightbox(items, index, options) {
  gallery = { items, index, options };
  document.addEventListener('keydown', onLightboxKey);
  lightboxEl.classList.add('open');
  showLightbox();
}

function closeLightbox() {
  document.removeEventListener('keydown', onLightboxKey);
  lightboxEl.classList.remove('open');
  lightboxStage.textContent = '';
  gallery = null;
}

lightboxEl.addEventListener('click', (event) => {
  const onPhoto = event.target.tagName === 'IMG' && lightboxStage.contains(event.target);
  if (event.target === lightboxEl || event.target === lightboxStage || onPhoto) closeLightbox();
});
document.getElementById('lightboxClose').addEventListener('click', closeLightbox);
lightboxToggleButton.addEventListener('click', toggleLightboxIgnore);

runAllButton.classList.add('runbutton');
runAllButton.addEventListener('click', () => runDecided(null));

showHandledButton.addEventListener('click', () => {
  showHandled = !showHandled;
  showHandledButton.setAttribute('aria-pressed', String(showHandled));
  renderTrips();
});

doneButton.addEventListener('click', async () => {
  if (!(await flushSave()) && !window.confirm('The last save failed. Finish anyway?')) return;
  try {
    const check = await postJson('/__TOKEN__/api/save', {});
    const names = (check.ok && check.data.unsaved_friends) || [];
    const verb = names.length === 1 ? ' is' : ' are';
    if (names.length && !window.confirm(names.join(', ') + verb + ' not selected on any day and will not be saved. Finish anyway?')) return;
  } catch (error) {
    setStatus('Done failed: ' + error.message, true);
    return;
  }
  try {
    const result = await postJson('/__TOKEN__/api/done', {});
    if (!result.ok) {
      setStatus(result.data.error || 'Done failed (' + result.status + ')', true);
      return;
    }
  } catch (error) {
    setStatus('Done failed: ' + error.message, true);
    return;
  }
  finished = true;
  document.body.textContent = 'Review finished. You can close this tab.';
});

const settingsEl = document.getElementById('settings');
const settingsFieldsEl = document.getElementById('settingsFields');
const settingsErrorEl = document.getElementById('settingsError');
const SETTING_FIELDS = [
  ['source', 'Source folder', 'Where PhotoPass downloads are read from.', 'text'],
  ['destination', 'Destination folder', 'Where photos from dates you were at are filed.', 'text'],
  ['layout', 'Folder layout', 'flat is "<date> - <park>"; the others nest date and park. Folders already filed are not moved.', 'choice'],
  ['stock_art', 'Stock art', 'delete removes Disney stock art; keep files it under "_Stock art".', 'choice'],
  ['default_timezone', 'Default timezone', 'Used for a park the tool does not know, for example America/New_York.', 'text'],
  ['shared_root', 'Shared folder root', 'A folder friend with no path of their own gets <root>/<name>. Leave empty for none.', 'text'],
  ['import_to_photos', 'Import into Photos', 'After organizing, add each filed date to the Photos app as an album. macOS only.', 'check'],
  ['photos_folder', 'Photos folder name', 'The folder in Photos that holds those albums.', 'text'],
  ['purge_after_import', 'Delete local folder after import', 'Remove a filed date from the destination once Photos confirms it took every file.', 'check'],
];

function buildSettingsForm(view) {
  document.getElementById('settingsPath').textContent = 'Saved in ' + view.path;
  settingsFieldsEl.textContent = '';
  for (const [key, label, help, kind] of SETTING_FIELDS) {
    const field = el('label', 'field' + (kind === 'check' ? ' check' : ''));
    let control;
    if (kind === 'choice') {
      control = el('select');
      for (const choice of view.choices[key]) {
        const option = el('option', '', choice);
        option.value = choice;
        control.appendChild(option);
      }
      control.value = view.settings[key];
    } else {
      control = el('input');
      control.type = kind === 'check' ? 'checkbox' : 'text';
      if (kind === 'check') control.checked = Boolean(view.settings[key]);
      else control.value = view.settings[key];
      if (kind === 'check' && key === 'import_to_photos' && !view.photos_available) control.disabled = true;
    }
    control.id = 'setting-' + key;
    control.dataset.key = key;
    control.dataset.kind = kind;
    const text = el('span');
    text.appendChild(el('span', 'name', label));
    text.appendChild(document.createElement('br'));
    text.appendChild(el('small', '', help));
    if (kind === 'check') {
      field.appendChild(control);
      field.appendChild(text);
    } else {
      field.appendChild(text);
      field.appendChild(control);
    }
    settingsFieldsEl.appendChild(field);
  }
}

function closeSettings() {
  settingsEl.classList.remove('open');
}

async function openSettings() {
  if (busy) return;
  if (!(await flushSave())) {
    setStatus('Fix the error above before opening settings: ' + lastSaveError, true);
    return;
  }
  try {
    const response = await fetch('/__TOKEN__/api/settings');
    if (!response.ok) throw new Error('settings request failed (' + response.status + ')');
    buildSettingsForm(await response.json());
  } catch (error) {
    setStatus('Could not load settings: ' + error.message, true);
    return;
  }
  settingsErrorEl.textContent = '';
  settingsEl.classList.add('open');
  settingsFieldsEl.querySelector('input, select').focus();
}

async function submitSettings(event) {
  event.preventDefault();
  const settings = {};
  for (const control of settingsFieldsEl.querySelectorAll('[data-key]')) {
    settings[control.dataset.key] = control.dataset.kind === 'check' ? control.checked : control.value.trim();
  }
  let result;
  try {
    result = await postJson('/__TOKEN__/api/settings', { settings });
  } catch (error) {
    settingsErrorEl.textContent = 'Could not save: ' + error.message;
    return;
  }
  if (!result.ok) {
    settingsErrorEl.textContent = result.data.error || 'Could not save (' + result.status + ')';
    return;
  }
  closeSettings();
  filter = null;
  try {
    await loadState();
    setStatus('Settings saved');
  } catch (error) {
    setStatus('Settings saved, but reloading the photos failed: ' + error.message, true);
  }
}

document.getElementById('openSettings').addEventListener('click', openSettings);
document.getElementById('settingsCancel').addEventListener('click', closeSettings);
document.getElementById('settingsForm').addEventListener('submit', submitSettings);
settingsEl.addEventListener('click', (event) => {
  if (event.target === settingsEl) closeSettings();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && settingsEl.classList.contains('open')) closeSettings();
});

loadState().then(() => setStatus('')).catch((error) => setStatus('Could not load: ' + error.message, true));
</script>
</body>
</html>
"""


def render_page(token: str) -> str:
    return PAGE_TEMPLATE.replace(TOKEN_PLACEHOLDER, token)
