/* =====================================================
   Spotify AI Playlist Generator & Power-User Suite
   Frontend JavaScript (Vanilla ES6)
   ===================================================== */

const API = {
  authStatus: () => fetch('/api/auth/status').then(r => r.json()),
  manualToken: (url) => fetch('/api/auth/manual-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ callback_url: url }),
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Fehler beim Token-Austausch');
    }
    return r.json();
  }),
  devices: () => fetch('/api/devices').then(r => r.json()),
  generate: (body) => fetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Request failed');
    }
    return r.json();
  }),
  userPlaylists: () => fetch('/api/library/playlists').then(async r => {
    if (!r.ok) throw new Error('Konnte Playlists nicht laden');
    return r.json();
  }),
  mergePlaylists: (body) => fetch('/api/merge-playlists', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Merge failed');
    }
    return r.json();
  }),
  inspectFilter: (body) => fetch('/api/inspect/filter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Filter failed');
    }
    return r.json();
  }),
  inspectDuplicates: (playlistId, apply = false) => fetch('/api/inspect/duplicates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlist_id: playlistId, apply }),
  }).then(r => r.json()),
  inspectReorder: (playlistId, trackUris, sortBy, mood = '') => fetch('/api/inspect/reorder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlist_id: playlistId, track_uris: trackUris, sort_by: sortBy, mood_for_vibe: mood }),
  }).then(r => r.json()),
  inspectBulkRemove: (playlistId, trackUris) => fetch('/api/inspect/bulk-remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlist_id: playlistId, track_uris: trackUris }),
  }).then(r => r.json()),
  inspectSaveAsNew: (body) => fetch('/api/inspect/save-as-new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || 'Speichern fehlgeschlagen');
    }
    return r.json();
  }),
  setWeight: (artistId, artistName, weight) => fetch('/api/artists/weights', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ artist_id: artistId, artist_name: artistName, weight }),
  }).then(r => r.json()),
  deleteWeight: (artistId) => fetch(`/api/artists/weights/${artistId}`, { method: 'DELETE' }),
  listWeights: () => fetch('/api/artists/weights').then(r => r.json()),
};

// State
let userPlaylistsCache = [];
let artistWeights = {}; // artist_id -> float
let currentTracks = [];
let currentStrategy = {};
let mixerCurrentTracks = [];
let inspectorTracks = [];
let inspectorCurrentPlaylistId = '';

const $ = id => document.getElementById(id);

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  setupRangeDisplays();
  await checkConfig();
  await checkAuth();
  await loadWeights();
  await refreshDevices();

  // Generator Tab Listeners
  $('generate-btn').addEventListener('click', onGenerate);
  $('create-spotify-btn').addEventListener('click', () => onCreateSpotify(false));
  $('refresh-devices').addEventListener('click', refreshDevices);

  // Mixer Tab Listeners
  $('mixer-refresh-pl').addEventListener('click', loadMixerPlaylists);
  $('mixer-search-pl').addEventListener('input', filterMixerPlaylists);
  $('mixer-run-btn').addEventListener('click', onRunMixer);
  $('mixer-save-spotify-btn').addEventListener('click', onSaveMixerToSpotify);

  // Inspector Tab Listeners
  $('insp-playlist-select').addEventListener('change', onInspectorPlaylistChange);
  $('insp-refresh-btn').addEventListener('click', loadInspectorPlaylists);
  $('insp-query').addEventListener('input', debounceInspectFilter);
  $('insp-min-pop').addEventListener('input', debounceInspectFilter);
  $('insp-year-from').addEventListener('input', debounceInspectFilter);
  $('insp-year-to').addEventListener('input', debounceInspectFilter);
  $('insp-weight-filter').addEventListener('change', debounceInspectFilter);
  $('insp-sort-by').addEventListener('change', debounceInspectFilter);
  $('insp-apply-ai-btn').addEventListener('click', () => runInspectFilter(true));
  $('insp-check-dupes-btn').addEventListener('click', onCheckDuplicates);
  $('insp-apply-reorder-btn').addEventListener('click', onReorderSpotify);
  $('insp-remove-filtered-btn').addEventListener('click', onBulkRemoveFiltered);
  $('insp-save-as-new-btn').addEventListener('click', openSubPlaylistModal);

  // Modal Listeners
  $('modal-cancel-btn').addEventListener('click', () => $('subplaylist-modal').style.display = 'none');
  $('modal-confirm-btn').addEventListener('click', onConfirmSaveAsNew);

  // Settings / Manual OAuth
  $('submit-manual-token').addEventListener('click', onSubmitManualToken);
});

// ─────────────────────────────────────────────
// Tabs Navigation
// ─────────────────────────────────────────────
function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(btn => {
    btn.addEventListener('click', () => {
      tabs.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      btn.classList.add('active');
      const target = $(btn.dataset.tab);
      if (target) {
        target.style.display = 'block';
        if (btn.dataset.tab === 'tab-mixer' && userPlaylistsCache.length === 0) {
          loadMixerPlaylists();
        } else if (btn.dataset.tab === 'tab-inspector' && $('insp-playlist-select').options.length <= 1) {
          loadInspectorPlaylists();
        }
      }
    });
  });
}

function setupRangeDisplays() {
  const binds = [
    { input: 'mixer-min-pop', label: 'val-mixer-min-pop' },
    { input: 'mixer-min-vibe', label: 'val-mixer-min-vibe' },
    { input: 'insp-min-pop', label: 'val-insp-min-pop' },
  ];
  binds.forEach(b => {
    const el = $(b.input);
    const lbl = $(b.label);
    if (el && lbl) {
      el.addEventListener('input', () => { lbl.textContent = el.value; });
    }
  });
}

// ─────────────────────────────────────────────
// Auth & Health
// ─────────────────────────────────────────────
async function checkConfig() {
  const r = await fetch('/health').then(r => r.json()).catch(() => ({}));
  if (!r.spotify_configured || !r.gemini_configured) {
    $('config-warning').style.display = 'flex';
  }
}

async function checkAuth() {
  const { authenticated, user } = await API.authStatus().catch(() => ({ authenticated: false }));
  const section = $('auth-section');
  if (authenticated && user) {
    section.innerHTML = `
      <div class="user-pill">
        ${user.image ? `<img class="user-avatar" src="${user.image}" alt="" />` : '👤'}
        <span>${escHtml(user.display_name || user.id)}</span>
        <a href="/logout" class="muted small" style="margin-left:4px">Log out</a>
      </div>`;
    $('oauth-helper-banner').style.display = 'none';
  } else {
    section.innerHTML = `<a href="/login" class="btn btn-login btn-sm">Connect Spotify</a>`;
    $('oauth-helper-banner').style.display = 'flex';
  }
}

async function onSubmitManualToken() {
  const url = $('manual-callback-url').value.trim();
  if (!url) { toast('Bitte URL eingeben', 'error'); return; }
  try {
    const res = await API.manualToken(url);
    toast(res.message || 'Erfolgreich verbunden!', 'success');
    $('manual-callback-url').value = '';
    await checkAuth();
    await refreshDevices();
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

async function refreshDevices() {
  const btn = $('refresh-devices');
  if (btn) btn.textContent = '⟳';
  try {
    const { devices } = await API.devices();
    const sel = $('device-select');
    sel.innerHTML = '<option value="">— Gerät wählen —</option>';
    (devices || []).forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.name;
      opt.textContent = `${d.type === 'Computer' ? '💻' : d.type === 'Smartphone' ? '📱' : '🔊'} ${d.name}${d.is_active ? ' ●' : ''}`;
      if (d.is_active) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch (e) {
    $('device-select').innerHTML = '<option value="">Nicht verbunden</option>';
  }
  if (btn) btn.textContent = '↻';
}

// ─────────────────────────────────────────────
// Artist Weights Management
// ─────────────────────────────────────────────
async function loadWeights() {
  try {
    const list = await API.listWeights();
    artistWeights = {};
    list.forEach(w => { artistWeights[w.artist_id] = w.weight; });
    renderWeightsList(list);
  } catch (e) {
    console.warn('Weights load error:', e);
  }
}

function renderWeightsList(list) {
  const el = $('artist-weights-list');
  if (!list || list.length === 0) {
    el.innerHTML = '<p class="muted small center">Noch keine Gewichtungen gespeichert.</p>';
    return;
  }
  el.innerHTML = list.map(w => `
    <div class="weight-item" data-id="${w.artist_id}">
      <span class="artist-name" title="${escHtml(w.artist_name)}">${escHtml(w.artist_name)}</span>
      <input type="range" min="0" max="2" step="0.1" value="${w.weight}"
        oninput="onSidebarWeightChange('${w.artist_id}', '${escHtml(w.artist_name)}', this)" />
      <span class="mini-badge ${w.weight === 0 ? 'banned' : w.weight < 0.5 ? 'soft' : w.weight > 1 ? 'boosted' : ''}">${w.weight.toFixed(1)}</span>
      <button class="btn-icon" onclick="onDeleteWeight('${w.artist_id}')" title="Reset">✕</button>
    </div>
  `).join('');
}

async function onSidebarWeightChange(artistId, artistName, input) {
  const weight = parseFloat(input.value);
  artistWeights[artistId] = weight;
  await API.setWeight(artistId, artistName, weight);
  await loadWeights();
  if (currentTracks.length) recalcGeneratorClientSide();
  if (inspectorTracks.length) debounceInspectFilter();
}

async function onDeleteWeight(artistId) {
  await API.deleteWeight(artistId);
  delete artistWeights[artistId];
  await loadWeights();
  if (currentTracks.length) recalcGeneratorClientSide();
  if (inspectorTracks.length) debounceInspectFilter();
}

async function quickSetArtistWeight(artistId, artistName, weight) {
  artistWeights[artistId] = weight;
  await API.setWeight(artistId, artistName, weight);
  toast(`${artistName}: Gewicht ${weight}`, 'info');
  await loadWeights();
  if (currentTracks.length) recalcGeneratorClientSide();
  if (inspectorTracks.length) debounceInspectFilter();
}

// ─────────────────────────────────────────────
// TAB 1: AI GENERATOR
// ─────────────────────────────────────────────
async function onGenerate() {
  const prompt = $('prompt-input').value.trim();
  if (!prompt) { toast('Bitte Mood-Prompt eingeben', 'error'); return; }

  const btn = $('generate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⟳</span> Analysiere...';
  $('empty-state').style.display = 'none';
  $('loading-state').style.display = 'flex';
  $('results-section').style.display = 'none';
  $('playlist-created').style.display = 'none';

  try {
    const result = await API.generate({
      prompt,
      limit: parseInt($('limit-input').value) || 40,
      sort_mode: $('sort-mode').value,
      create_on_spotify: false,
      playlist_name: '',
      device_name: $('device-select').value,
      start_playback: false,
    });
    currentTracks = result.tracks;
    currentStrategy = result.search_strategy;
    renderGeneratorResults(result);
    $('create-spotify-btn').disabled = false;
    toast(`Gefunden: ${result.tracks.length} Songs!`, 'success');
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
    $('empty-state').style.display = 'flex';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">✨</span> Playlist generieren';
    $('loading-state').style.display = 'none';
  }
}

async function onCreateSpotify() {
  if (!currentTracks.length) return;
  const btn = $('create-spotify-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⟳</span> Speichere...';

  try {
    const prompt = $('prompt-input').value.trim();
    const result = await API.generate({
      prompt,
      limit: parseInt($('limit-input').value) || 40,
      sort_mode: $('sort-mode').value,
      create_on_spotify: true,
      playlist_name: $('playlist-name').value.trim() || `🎵 ${prompt.slice(0, 35)}`,
      device_name: $('device-select').value,
      start_playback: $('start-playback').checked,
    });
    if (result.playlist) {
      $('playlist-created').style.display = 'flex';
      $('playlist-created-text').textContent = `Playlist "${result.playlist.name}" mit ${result.playlist.tracks_added} Songs erstellt!`;
      $('playlist-link').href = result.playlist.url;
      toast('In Spotify gespeichert! ✅', 'success');
    }
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">➕</span> In Spotify speichern';
  }
}

function renderGeneratorResults(result) {
  $('results-section').style.display = 'block';
  $('results-title').textContent = $('playlist-name').value.trim() || `🎵 ${$('prompt-input').value.trim().slice(0, 35)}`;
  $('results-meta').textContent = `${result.tracks.length} Songs · ${result.total_found} durchsucht · Modus: ${$('sort-mode').value}`;
  $('mood-badge').textContent = result.mood_description || '';

  const strategy = result.search_strategy || {};
  const tags = [
    ...(strategy.genres || []).map(g => `🎸 ${g}`),
    ...(strategy.decade_tags || []).map(d => `📅 ${d}`),
    `⚡ ${strategy.energy_level || 'medium'}`,
  ];
  $('strategy-content').innerHTML = tags.map(t => `<span class="strategy-tag">${escHtml(t)}</span>`).join('');
  renderTrackList($('track-list'), result.tracks);
}

function recalcGeneratorClientSide() {
  if (!currentTracks.length) return;
  const limit = parseInt($('limit-input').value) || 40;
  const mode = $('sort-mode').value;

  const annotated = currentTracks.map(t => ({
    ...t,
    artist_weight: artistWeights[t.artist_id] ?? 1.0,
    final_score: t.popularity * (artistWeights[t.artist_id] ?? 1.0),
  })).filter(t => t.artist_weight > 0);

  if (mode === 'hidden_gems') {
    annotated.sort((a, b) => (b.popularity < 55 ? b.final_score : 0) - (a.popularity < 55 ? a.final_score : 0));
  } else {
    annotated.sort((a, b) => b.final_score - a.final_score);
  }

  const counts = {};
  const result = [];
  for (const t of annotated) {
    const c = counts[t.artist_id] || 0;
    const cap = t.artist_weight < 0.5 ? 2 : (mode === 'balanced' ? 3 : limit);
    if (t.artist_weight < 0.5 && t.popularity < 70 && c >= 1) continue;
    if (c >= cap) continue;
    result.push(t);
    counts[t.artist_id] = c + 1;
    if (result.length >= limit) break;
  }
  currentTracks = result;
  renderTrackList($('track-list'), result);
}

// ─────────────────────────────────────────────
// TAB 2: PLAYLIST-MIXER
// ─────────────────────────────────────────────
async function loadMixerPlaylists() {
  const container = $('mixer-playlists-list');
  container.innerHTML = '<p class="muted small center">Lade Playlists von Spotify...</p>';
  try {
    const res = await API.userPlaylists();
    userPlaylistsCache = res.playlists || [];
    renderMixerPlaylistChecklist(userPlaylistsCache);
  } catch (e) {
    container.innerHTML = `<p class="muted small center">Fehler: ${e.message}</p>`;
  }
}

function renderMixerPlaylistChecklist(playlists) {
  const container = $('mixer-playlists-list');
  if (!playlists.length) {
    container.innerHTML = '<p class="muted small center">Keine Playlists gefunden</p>';
    return;
  }
  container.innerHTML = playlists.map(pl => `
    <label class="pl-item" title="${escHtml(pl.name)} (${pl.track_count} Songs)">
      <input type="checkbox" class="mixer-pl-cb" value="${pl.id}" data-name="${escHtml(pl.name)}" />
      ${pl.image ? `<img class="pl-item-cover" src="${pl.image}" alt="" />` : '<div class="pl-item-cover"></div>'}
      <div class="pl-item-info">
        <div>${escHtml(pl.name)}</div>
        <div class="pl-item-meta">${pl.track_count} Songs · ${escHtml(pl.owner)}</div>
      </div>
    </label>
  `).join('');
}

function filterMixerPlaylists() {
  const q = $('mixer-search-pl').value.toLowerCase();
  const filtered = userPlaylistsCache.filter(p => p.name.toLowerCase().includes(q));
  renderMixerPlaylistChecklist(filtered);
}

async function onRunMixer() {
  const prompt = $('mixer-prompt').value.trim();
  if (!prompt) { toast('Bitte Ziel-Vibe/Mood eingeben', 'error'); return; }

  const selectedIds = Array.from(document.querySelectorAll('.mixer-pl-cb:checked')).map(cb => cb.value);
  const includeLiked = $('mixer-include-liked').checked;

  if (selectedIds.length === 0 && !includeLiked) {
    toast('Wähle mindestens 1 Playlist oder "Liked Songs" als Quelle aus', 'error');
    return;
  }

  $('mixer-empty-state').style.display = 'none';
  $('mixer-loading-state').style.display = 'flex';
  $('mixer-results').style.display = 'none';
  $('mixer-run-btn').disabled = true;

  try {
    const body = {
      prompt,
      playlist_ids: selectedIds,
      include_liked_songs: includeLiked,
      min_popularity: parseInt($('mixer-min-pop').value) || 0,
      min_vibe_score: parseFloat($('mixer-min-vibe').value) || 0.0,
      limit: parseInt($('mixer-limit').value) || 40,
      sort_mode: $('mixer-sort').value,
      create_on_spotify: false,
      use_ai_scoring: $('mixer-use-ai').checked,
    };
    const res = await API.mergePlaylists(body);
    mixerCurrentTracks = res.tracks;
    $('mixer-results-title').textContent = $('mixer-target-name').value.trim() || `Mixer: ${prompt.slice(0, 30)}`;
    $('mixer-results-stats').textContent = `${res.tracks.length} finale Songs (aus ${res.total_candidates} Gesamtsongs, ${res.after_popularity_filter} nach Vorfilter)`;
    renderTrackList($('mixer-track-list'), res.tracks);
    $('mixer-results').style.display = 'block';
    toast(`Merge erfolgreich: ${res.tracks.length} Banger gefunden!`, 'success');
  } catch (e) {
    toast(`Merge-Fehler: ${e.message}`, 'error');
    $('mixer-empty-state').style.display = 'flex';
  } finally {
    $('mixer-loading-state').style.display = 'none';
    $('mixer-run-btn').disabled = false;
  }
}

async function onSaveMixerToSpotify() {
  if (!mixerCurrentTracks.length) return;
  const prompt = $('mixer-prompt').value.trim();
  const name = $('mixer-target-name').value.trim() || `Mixer: ${prompt.slice(0, 30)}`;
  const selectedIds = Array.from(document.querySelectorAll('.mixer-pl-cb:checked')).map(cb => cb.value);

  const btn = $('mixer-save-spotify-btn');
  btn.disabled = true;
  btn.textContent = 'Speichere...';

  try {
    const res = await API.mergePlaylists({
      prompt,
      playlist_ids: selectedIds,
      include_liked_songs: $('mixer-include-liked').checked,
      min_popularity: parseInt($('mixer-min-pop').value) || 0,
      min_vibe_score: parseFloat($('mixer-min-vibe').value) || 0.0,
      limit: parseInt($('mixer-limit').value) || 40,
      sort_mode: $('mixer-sort').value,
      create_on_spotify: true,
      target_playlist_name: name,
      start_playback_after: $('mixer-start-play').checked,
      use_ai_scoring: false, // already scored
    });
    if (res.playlist) {
      toast(`Playlist "${res.playlist.name}" in Spotify angelegt! ✅`, 'success');
      window.open(res.playlist.url, '_blank');
    }
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 In Spotify anlegen';
  }
}

// ─────────────────────────────────────────────
// TAB 3: PLAYLIST INSPECTOR
// ─────────────────────────────────────────────
async function loadInspectorPlaylists() {
  const sel = $('insp-playlist-select');
  sel.innerHTML = '<option value="">Lade Playlists...</option>';
  try {
    const res = await API.userPlaylists();
    userPlaylistsCache = res.playlists || [];
    sel.innerHTML = '<option value="">— Playlist wählen —</option>';
    userPlaylistsCache.forEach(pl => {
      const opt = document.createElement('option');
      opt.value = pl.id;
      opt.textContent = `${pl.name} (${pl.track_count} Songs)`;
      sel.appendChild(opt);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Fehler beim Laden</option>';
  }
}

function onInspectorPlaylistChange() {
  inspectorCurrentPlaylistId = $('insp-playlist-select').value;
  if (!inspectorCurrentPlaylistId) {
    $('insp-empty-state').style.display = 'flex';
    $('insp-track-table-wrap').style.display = 'none';
    return;
  }
  runInspectFilter(false);
}

let filterTimer = null;
function debounceInspectFilter() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => runInspectFilter(false), 250);
}

async function runInspectFilter(applyAI = false) {
  if (!inspectorCurrentPlaylistId) return;

  $('insp-loading-state').style.display = 'flex';
  $('insp-empty-state').style.display = 'none';

  const body = {
    playlist_id: inspectorCurrentPlaylistId,
    query: $('insp-query').value.trim(),
    min_popularity: parseInt($('insp-min-pop').value) || 0,
    max_popularity: 100,
    year_from: parseInt($('insp-year-from').value) || 0,
    year_to: parseInt($('insp-year-to').value) || 9999,
    weight_filter: $('insp-weight-filter').value,
    sort_by: $('insp-sort-by').value,
    mood_for_vibe: applyAI ? $('insp-mood-prompt').value.trim() : '',
    limit: 300,
  };

  try {
    const res = await API.inspectFilter(body);
    inspectorTracks = res.tracks;
    renderInspectorList(res.tracks);
    $('insp-count-badge').textContent = `${res.total} Songs`;
    $('insp-remove-count').textContent = res.total;
    $('insp-remove-filtered-btn').disabled = res.total === 0;
    $('insp-track-table-wrap').style.display = 'block';
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    $('insp-loading-state').style.display = 'none';
  }
}

function renderInspectorList(tracks) {
  const container = $('insp-track-list');
  if (!tracks.length) {
    container.innerHTML = '<p class="muted center p-4">Keine Songs entsprechen den aktuellen Filtern.</p>';
    return;
  }
  container.innerHTML = tracks.map((t, idx) => {
    const w = artistWeights[t.artist_id] ?? t.artist_weight ?? 1.0;
    const isBanned = w === 0.0;
    const isSoft = w > 0 && w < 0.5;
    const isBoosted = w > 1.0;
    return `
    <div class="track-item inspector-row" data-id="${t.id}" data-uri="${t.uri}">
      <span class="track-num">${idx + 1}</span>
      ${t.album_image ? `<img class="track-cover" src="${t.album_image}" alt="" />` : '<div class="track-cover-placeholder">🎵</div>'}
      <div class="track-info">
        <div class="track-name" title="${escHtml(t.name)}">${escHtml(t.name)}</div>
        <div class="track-artist">${escHtml(t.artist_name)}</div>
        ${t.vibe_score ? `<span class="vibe-tag">Vibe: ${t.vibe_score.toFixed(1)}/10</span>` : ''}
      </div>
      <span class="track-year">${t.release_year || '–'}</span>
      <div class="track-meta">
        <div class="popularity-bar"><div class="popularity-fill" style="width:${t.popularity}%"></div></div>
        <span class="track-score">${t.popularity} pop</span>
      </div>
      <div class="artist-quick-btns">
        <button class="quick-btn ${isBanned ? 'active-ban' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 0.0)" title="Hard-Ban">⛔ 0</button>
        <button class="quick-btn ${isSoft ? 'active-soft' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 0.3)" title="Soft-Ban">⚠️ Soft</button>
        <button class="quick-btn ${w === 1.0 ? 'active-normal' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 1.0)" title="Normal">1.0</button>
        <button class="quick-btn ${isBoosted ? 'active-boost' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 1.8)" title="Boost">⭐ 1.8</button>
      </div>
      <div>
        ${t.spotify_url ? `<a href="${t.spotify_url}" target="_blank" class="btn-icon" title="In Spotify öffnen">↗</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

async function onCheckDuplicates() {
  if (!inspectorCurrentPlaylistId) { toast('Wähle zuerst eine Playlist', 'error'); return; }
  const btn = $('insp-check-dupes-btn');
  btn.disabled = true;
  btn.textContent = 'Suche Duplikate...';

  try {
    const res = await API.inspectDuplicates(inspectorCurrentPlaylistId, false);
    if (res.duplicate_count === 0) {
      toast('Keine Duplikate gefunden! Alles sauber. 🎉', 'success');
    } else {
      if (confirm(`${res.duplicate_count} Duplikate gefunden! Sollen diese jetzt automatisch aus der Playlist auf Spotify entfernt werden?`)) {
        await API.inspectDuplicates(inspectorCurrentPlaylistId, true);
        toast(`${res.duplicate_count} Duplikate entfernt! ✅`, 'success');
        runInspectFilter(false);
      }
    }
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Duplikate finden';
  }
}

async function onReorderSpotify() {
  if (!inspectorCurrentPlaylistId) return;
  if (!confirm(`Soll die Playlist auf Spotify gemäß der aktuellen Sortierung ("${$('insp-sort-by').value}") dauerhaft neu geordnet werden?`)) return;

  const btn = $('insp-apply-reorder-btn');
  btn.disabled = true;
  btn.textContent = 'Speichere Reihenfolge...';

  try {
    const uris = inspectorTracks.map(t => t.uri);
    const res = await API.inspectReorder(inspectorCurrentPlaylistId, uris, $('insp-sort-by').value);
    if (res.success) {
      toast('Reihenfolge auf Spotify erfolgreich aktualisiert! ✅', 'success');
    } else {
      toast('Reihenfolge konnte nicht gespeichert werden.', 'error');
    }
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 Reihenfolge auf Spotify speichern';
  }
}

async function onBulkRemoveFiltered() {
  if (!inspectorCurrentPlaylistId || !inspectorTracks.length) return;
  if (!confirm(`Möchtest du diese ${inspectorTracks.length} gefilterten Songs wirklich dauerhaft aus deiner Spotify-Playlist LÖSCHEN?`)) return;

  const uris = inspectorTracks.map(t => t.uri);
  try {
    await API.inspectBulkRemove(inspectorCurrentPlaylistId, uris);
    toast(`${uris.length} Songs aus Playlist entfernt! 🗑️`, 'success');
    runInspectFilter(false);
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

function openSubPlaylistModal() {
  if (!inspectorTracks.length) { toast('Keine Songs gefiltert', 'error'); return; }
  $('modal-song-count').textContent = inspectorTracks.length;
  $('modal-playlist-name').value = `Sub: ${$('insp-playlist-select').selectedOptions[0]?.text.split('(')[0].trim() || 'Selection'}`;
  $('subplaylist-modal').style.display = 'flex';
}

async function onConfirmSaveAsNew() {
  const name = $('modal-playlist-name').value.trim();
  if (!name) { toast('Name erforderlich', 'error'); return; }

  const btn = $('modal-confirm-btn');
  btn.disabled = true;
  btn.textContent = 'Erstelle...';

  try {
    const res = await API.inspectSaveAsNew({
      source_playlist_id: inspectorCurrentPlaylistId,
      track_ids: inspectorTracks.map(t => t.id),
      new_playlist_name: name,
      description: $('modal-playlist-desc').value.trim(),
    });
    $('subplaylist-modal').style.display = 'none';
    toast(`Sub-Playlist "${res.name}" erstellt! ✅`, 'success');
    window.open(res.url, '_blank');
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'In Spotify anlegen';
  }
}

// ─────────────────────────────────────────────
// Shared Track List Renderer
// ─────────────────────────────────────────────
function renderTrackList(container, tracks) {
  if (!tracks.length) {
    container.innerHTML = '<p class="muted center">Keine Songs vorhanden.</p>';
    return;
  }
  container.innerHTML = tracks.map((t, idx) => {
    const w = artistWeights[t.artist_id] ?? t.artist_weight ?? 1.0;
    const badgeClass = w === 0 ? ' banned' : w < 0.5 ? ' soft' : w > 1 ? ' boosted' : '';
    return `
    <div class="track-item" data-id="${t.id}" data-artist-id="${t.artist_id}">
      <span class="track-num">${idx + 1}</span>
      ${t.album_image ? `<img class="track-cover" src="${t.album_image}" alt="" />` : '<div class="track-cover-placeholder">🎵</div>'}
      <div class="track-info">
        <div class="track-name" title="${escHtml(t.name)}">${escHtml(t.name)}</div>
        <div class="track-artist">${escHtml(t.artist_name)}</div>
        ${t.vibe_score ? `<span class="vibe-tag">Vibe: ${t.vibe_score.toFixed(1)}/10</span>` : ''}
      </div>
      <div class="track-meta">
        <div class="popularity-bar"><div class="popularity-fill" style="width:${t.popularity}%"></div></div>
        <span class="track-score">${t.popularity} pop · Score: ${Math.round(t.final_score ?? t.popularity)}</span>
      </div>
      <div class="artist-quick-btns">
        <span class="mini-badge${badgeClass}">${w.toFixed(1)}</span>
        <button class="quick-btn ${w === 0 ? 'active-ban' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 0.0)" title="Hard-Ban">⛔</button>
        <button class="quick-btn ${w > 0 && w < 0.5 ? 'active-soft' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 0.3)" title="Soft-Ban">⚠️</button>
        <button class="quick-btn ${w === 1.0 ? 'active-normal' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 1.0)" title="Normal">1.0</button>
        <button class="quick-btn ${w > 1.0 ? 'active-boost' : ''}" onclick="quickSetArtistWeight('${t.artist_id}', '${escHtml(t.artist_name)}', 1.8)" title="Boost">⭐</button>
        ${t.spotify_url ? `<a href="${t.spotify_url}" target="_blank" class="btn-icon" style="padding:2px 6px;margin-left:4px" title="In Spotify öffnen">↗</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ─────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = $('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
