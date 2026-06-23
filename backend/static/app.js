let pollingTimer = null;
const state = {
  queue: null,
  favorites: [],
  offlineStatuses: {},
  offlineData: [],
  downloadTasks: [],
  searchQuery: '',
  searchResults: null,
  historyData: null,
  currentView: 'search',
  currentTab: 'results',
};
const $ = id => document.getElementById(id);

function showToast(msg) {
  let el = $('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._hide);
  el._hide = setTimeout(() => el.classList.remove('show'), 2000);
}

// ── Navigation ─────────────────────────────────────────────────────────────

function showView(name) {
  state.currentView = name;

  // Update nav
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const navItem = document.querySelector(`.nav-item[data-view="${name}"]`);
  if (navItem) navItem.classList.add('active');

  const header = $('search-header');
  const tabs = $('panel-tabs');
  const queueFull = $('queue-full');

  // Hide everything, then show what's needed
  if (queueFull) queueFull.style.display = 'none';
  document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));

  if (name === 'search') {
    header.style.display = 'flex';
    tabs.style.display = 'flex';
    switchCenterTab(state.currentTab);
  } else if (name === 'favorites') {
    header.style.display = 'flex';
    tabs.style.display = 'flex';
    const tab = document.querySelector('.tab[data-tab="favorites"]');
    if (tab) tab.classList.add('active');
    const tc = $('tab-favorites');
    if (tc) tc.classList.add('active');
    fetchFavorites();
    renderCenterFavorites();
    startPolling();
  } else if (name === 'queue') {
    header.style.display = 'none';
    tabs.style.display = 'none';
    renderQueueFull();
    startPolling();
  } else if (name === 'downloads') {
    header.style.display = 'none';
    tabs.style.display = 'none';
    renderDownloadManager();
    fetchDownloadTasks();
  }

  closePanels();
  startPolling();
}

function switchCenterTab(name) {
  state.currentTab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.classList.add('active');
  const tc = $(`tab-${name}`);
  if (tc) tc.classList.add('active');

  if (name === 'results') {
    renderSearchResults();
  } else if (name === 'favorites') {
    fetchFavorites();
    renderCenterFavorites();
  } else if (name === 'reciente') {
    fetchHistory(1);
  }
}

function toggleSidebar() {
  $('sidebar-left').classList.toggle('show');
  $('overlay').classList.toggle('show');
}

function toggleQueuePanel() {
  $('sidebar-right').classList.toggle('show');
  $('overlay').classList.toggle('show');
}

function closePanels() {
  $('sidebar-left').classList.remove('show');
  $('sidebar-right').classList.remove('show');
  $('overlay').classList.remove('show');
}

function refreshAll() {
  fetchQueue();
  fetchFavorites();
  showToast('Actualizado');
}

// ── Polling ─────────────────────────────────────────────────────────────────

function startPolling() {
  stopPolling();
  pollingTimer = setInterval(() => {
    fetchQueue();
    fetchDownloadTasks();
  }, 3000);
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

// ── API helpers ─────────────────────────────────────────────────────────────

async function api(url, opts = {}) {
  try {
    const res = await fetch(url, opts);
    if (res.status === 401) {
      window.location.href = '/app-music/login';
      return null;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('API error:', url, e);
    return null;
  }
}

async function fetchQueue() {
  const data = await api('/app-music/api/queue');
  if (data) {
    state.queue = data;
    renderBottomBar();
    renderQueueSidebar();
  }
}

async function fetchFavorites() {
  const data = await api('/app-music/api/favorites');
  if (data) state.favorites = data;
}

async function fetchHistory(page) {
  const data = await api(`/app-music/api/history?page=${page || 1}&page_size=50`);
  if (data) {
    state.historyData = data;
    await fetchOfflineStatuses();
    renderReciente();
  }
}

async function searchSongs(query) {
  if (!query.trim()) return;
  state.searchQuery = query;
  const el = $('tab-results');
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  const data = await api(`/app-music/api/search?q=${encodeURIComponent(query)}`);
  state.searchResults = data || [];
  renderSearchResults();
  fetchOfflineStatuses();
}

async function enqueueSong(song) {
  const data = await api('/app-music/api/queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(song),
  });
  if (data) {
    showToast('Encolado');
    fetchQueue();
  } else {
    showToast('Error al encolar');
  }
}

async function toggleFavorite(song) {
  const check = await api(`/app-music/api/favorites/check/${song.video_id}`);
  if (check && check.favorite) {
    await api(`/app-music/api/favorites/${song.video_id}`, { method: 'DELETE' });
    showToast('Quitado de favoritos');
  } else {
    await api('/app-music/api/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(song),
    });
    showToast('Agregado a favoritos');
  }
  fetchFavorites();
  renderCenterFavorites();
  renderSearchResults();
}

async function removeFavorite(videoId) {
  const res = await api(`/app-music/api/favorites/${videoId}`, { method: 'DELETE' });
  if (res && res.ok) {
    showToast('Quitado de favoritos');
    fetchFavorites();
    renderCenterFavorites();
  }
}

async function fetchDownloadTasks() {
  const data = await api('/app-music/api/offline/tasks');
  if (data) {
    state.downloadTasks = data;
    if (state.currentView === 'downloads') renderDownloadManager();
  }
}

async function fetchOfflineStatuses() {
  if (!state.searchResults || state.searchResults.length === 0) return;
  const ids = state.searchResults.map(s => s.video_id).join(',');
  const data = await api(`/app-music/api/offline/statuses?ids=${encodeURIComponent(ids)}`);
  if (data) {
    state.offlineStatuses = data;
    renderSearchResults();
  }
}

async function deleteOffline(videoId) {
  if (!confirm('Eliminar descarga offline?')) return;
  const res = await api(`/app-music/api/offline/${videoId}`, { method: 'DELETE' });
  if (res && res.ok) {
    showToast('Eliminado');
    fetchDownloadTasks();
  }
}

async function markForDownload(song) {
  const res = await api('/app-music/api/offline/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(song),
  });
  if (res && res.ok) {
    showToast('Agregado a descargas');
    fetchDownloadTasks();
    fetchOfflineStatuses();
  } else {
    showToast('Error al agregar');
  }
}

async function downloadAllQueue() {
  if (!state.queue || !state.queue.queue) {
    showToast('Cola vacia');
    return;
  }
  for (const s of state.queue.queue) {
    await api('/app-music/api/offline/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: s.video_id, title: s.title, artist: s.artist, thumbnail: s.thumbnail || '' }),
    });
  }
  showToast('Agregadas a descargas');
  fetchDownloadTasks();
  await resumeDownloader();
}

async function resumeDownloader() {
  const res = await api('/app-music/api/offline/downloader/resume', { method: 'POST' });
  if (res && res.ok) {
    showToast('Descargando pendientes...');
    fetchDownloadTasks();
  }
}

async function clearQueue() {
  if (!confirm('Limpiar toda la cola?')) return;
  const res = await api('/app-music/api/queue/clear', { method: 'POST' });
  if (res && res.ok) {
    showToast('Cola limpiada');
    fetchQueue();
  }
}

// ── Bottom Bar ──────────────────────────────────────────────────────────────

function renderBottomBar() {
  const q = state.queue;
  const ttl = $('track-title');
  const art = $('track-artist');
  const thumb = $('track-thumb');
  const fill = $('progress-fill');
  const cur = $('progress-current');
  const tot = $('progress-total');
  const playBtn = $('play-btn');

  if (!q || !q.current) {
    ttl.textContent = 'Sin reproduccion';
    art.textContent = '-';
    thumb.innerHTML = '<i class="fas fa-music"></i>';
    fill.style.width = '0%';
    cur.textContent = '0:00';
    tot.textContent = '0:00';
    playBtn.innerHTML = '<i class="fas fa-play"></i>';
    return;
  }

  const s = q.current;
  ttl.textContent = s.title || 'Desconocido';
  art.textContent = s.artist || '';
  thumb.innerHTML = s.thumbnail
    ? `<img src="${escAttr(s.thumbnail)}">`
    : '<i class="fas fa-music"></i>';
  playBtn.innerHTML = '<i class="fas fa-play"></i>';
}

function prevTrack() { showToast('Usa "Alexa, anterior"'); }
function nextTrack() { showToast('Usa "Alexa, siguiente"'); }
function togglePlay() { showToast('Usa "Alexa, pausa/reanudar"'); }

// ── Queue Sidebar (Right) ──────────────────────────────────────────────────

function renderQueueSidebar() {
  const el = $('queue-list');
  if (!el) return;
  const q = state.queue;
  if (!q || !q.queue || q.queue.length === 0) {
    el.innerHTML = '<div class="queue-empty"><i class="fas fa-list"></i><p>Cola vacia</p></div>';
    return;
  }

  el.innerHTML = q.queue.map((s, i) => {
    const isCurrent = i === q.current_index;
    const isFaved = state.favorites.some(f => f.video_id === s.video_id);
    return `<div class="queue-item${isCurrent ? ' current' : ''}">
      ${renderThumb(s.thumbnail, 36)}
      <div class="info">
        <div class="title">${esc(s.title)}</div>
        <div class="artist">${esc(s.artist)}</div>
      </div>
      <button class="qfav-btn" onclick="event.stopPropagation();markForDownload({
        video_id:'${escAttr(s.video_id)}',
        title:'${escAttr(s.title)}',
        artist:'${escAttr(s.artist)}',
        thumbnail:'${escAttr(s.thumbnail||'')}'
      })" title="Descargar"><i class="fas fa-download"></i></button>
      <button class="qfav-btn ${isFaved?'active':''}"
        onclick="event.stopPropagation();toggleFavorite({
          video_id:'${escAttr(s.video_id)}',
          title:'${escAttr(s.title)}',
          artist:'${escAttr(s.artist)}',
          thumbnail:'${escAttr(s.thumbnail||'')}'
        })" title="${isFaved?'Quitar de':'Agregar a'} favoritos"><i class="fas fa-heart"></i></button>
      ${isCurrent ? '<span class="badge">Ahora</span>' : ''}
    </div>`;
  }).join('');
}

function renderQueueFull() {
  const el = $('queue-full') || (() => {
    const div = document.createElement('div');
    div.id = 'queue-full';
    $('panel-content').appendChild(div);
    return div;
  })();

  el.style.display = 'block';
  const q = state.queue;

  if (!q || !q.queue || q.queue.length === 0) {
    el.innerHTML = '<div class="empty-state"><i class="fas fa-list"></i><p>Cola vacia</p></div>';
    return;
  }

  el.innerHTML = `<p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">
      ${q.total} canciones${q.looping ? ' &middot; Bucle activado' : ''}</p>
    ${q.queue.map((s, i) => {
      const isCurrent = i === q.current_index;
      const isFaved = state.favorites.some(f => f.video_id === s.video_id);
      return `<div class="song-row" style="${isCurrent ? 'background:#e8f5e9;' : ''}">
        ${renderThumb(s.thumbnail, 40)}
        <div class="info">
          <div class="title">${esc(s.title)} ${isCurrent ? '<span style="color:var(--primary);font-size:11px;">Ahora</span>' : ''}</div>
          <div class="artist">${esc(s.artist)}</div>
        </div>
        <div class="actions">
          <button class="action-btn" onclick="markForDownload({
            video_id:'${escAttr(s.video_id)}',
            title:'${escAttr(s.title)}',
            artist:'${escAttr(s.artist)}',
            thumbnail:'${escAttr(s.thumbnail||'')}'
          })" title="Descargar"><i class="fas fa-download"></i></button>
          <button class="action-btn ${isFaved?'active':''}"
            onclick="toggleFavorite({
              video_id:'${escAttr(s.video_id)}',
              title:'${escAttr(s.title)}',
              artist:'${escAttr(s.artist)}',
              thumbnail:'${escAttr(s.thumbnail||'')}'
            })" title="Favorito"><i class="fas fa-heart"></i></button>
        </div>
      </div>`;
    }).join('')}`;
}

// ── Search ──────────────────────────────────────────────────────────────────

function doSearch() {
  const input = $('search-input');
  if (input && input.value.trim()) {
    switchCenterTab('results');
    searchSongs(input.value.trim());
  }
}

function renderSearchResults() {
  const el = $('tab-results');
  if (!el) return;
  const results = state.searchResults;

  if (!results || results.length === 0) {
    el.innerHTML = state.searchQuery
      ? '<div class="empty-state"><i class="fas fa-search"></i><p>Sin resultados</p></div>'
      : '<div class="empty-state"><i class="fas fa-music"></i><p>Escribe para buscar canciones</p></div>';
    return;
  }

  el.innerHTML = `<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">${results.length} resultado(s)</p>
    ${results.map(s => {
      const isFaved = state.favorites.some(f => f.video_id === s.video_id);
      const offlineStatus = state.offlineStatuses[s.video_id];
      const offlineBadge = offlineStatus === 'complete' ? '<span class="badge-offline" title="Disponible sin conexion"><i class="fas fa-check-circle"></i></span>' : '';
      return `<div class="song-row">
        ${renderThumb(s.thumbnail, 40)}
        <div class="info">
          <div class="title">${esc(s.title)} ${offlineBadge}</div>
          <div class="artist">${esc(s.artist)}</div>
        </div>
        <div class="actions">
          <button class="action-btn" onclick="enqueueSong({
            video_id:'${escAttr(s.video_id)}',
            title:'${escAttr(s.title)}',
            artist:'${escAttr(s.artist)}',
            thumbnail:'${escAttr(s.thumbnail||'')}'
          })" title="Encolar"><i class="fas fa-plus"></i></button>
          <button class="action-btn" onclick="markForDownload({
            video_id:'${escAttr(s.video_id)}',
            title:'${escAttr(s.title)}',
            artist:'${escAttr(s.artist)}',
            thumbnail:'${escAttr(s.thumbnail||'')}'
          })" title="Descargar"><i class="fas fa-download"></i></button>
          <button class="action-btn ${isFaved?'active':''}"
            onclick="toggleFavorite({
              video_id:'${escAttr(s.video_id)}',
              title:'${escAttr(s.title)}',
              artist:'${escAttr(s.artist)}',
              thumbnail:'${escAttr(s.thumbnail||'')}'
            })" title="Favorito"><i class="fas fa-heart"></i></button>
        </div>
      </div>`;
    }).join('')}`;
}

// ── Center Favorites ────────────────────────────────────────────────────────

function renderCenterFavorites() {
  const el = $('tab-favorites');
  if (!el) return;
  const favs = state.favorites;
  if (!favs || favs.length === 0) {
    el.innerHTML = '<div class="empty-state"><i class="fas fa-heart"></i><p>Sin favoritos</p></div>';
    return;
  }

  el.innerHTML = `<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">${favs.length} favorito(s)</p>
    ${favs.map(s => {
      return `<div class="song-row">
        ${renderThumb(s.thumbnail, 40)}
        <div class="info">
          <div class="title">${esc(s.title)}</div>
          <div class="artist">${esc(s.artist)}</div>
        </div>
        <div class="actions">
          <button class="action-btn" onclick="enqueueSong({
            video_id:'${escAttr(s.video_id)}',
            title:'${escAttr(s.title)}',
            artist:'${escAttr(s.artist)}',
            thumbnail:'${escAttr(s.thumbnail||'')}'
          })" title="Encolar"><i class="fas fa-plus"></i></button>
          <button class="action-btn" onclick="markForDownload({
            video_id:'${escAttr(s.video_id)}',
            title:'${escAttr(s.title)}',
            artist:'${escAttr(s.artist)}',
            thumbnail:'${escAttr(s.thumbnail||'')}'
          })" title="Descargar"><i class="fas fa-download"></i></button>
          <button class="action-btn danger" onclick="removeFavorite('${escAttr(s.video_id)}')"
            title="Quitar"><i class="fas fa-trash"></i></button>
        </div>
      </div>`;
    }).join('')}`;
}

// ── Reciente (History) ──────────────────────────────────────────────────────

function renderReciente() {
  const el = $('tab-reciente');
  if (!el) return;
  const data = state.historyData;
  if (!data || !data.items || data.items.length === 0) {
    el.innerHTML = '<div class="empty-state"><i class="fas fa-clock"></i><p>Sin historial</p></div>';
    return;
  }

  let html = `<div class="history-toolbar">
      <button class="toolbar-btn" onclick="dedupHistory()"><i class="fas fa-broom"></i> Limpiar duplicados</button>
      <button class="toolbar-btn" onclick="downloadHistory()"><i class="fas fa-download"></i> Descargar historial</button>
    </div>`;

  html += `<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
    ${data.total} canciones &middot; Pagina ${data.page} de ${data.total_pages}</p>`;

  const offlineStatuses = state.offlineStatuses || {};

  data.items.forEach(s => {
    const played = s.played === 1;
    const isOffline = offlineStatuses[s.video_id] === 'complete';
    const badge = isOffline
      ? '<i class="fas fa-check-circle" style="color:var(--primary);font-size:14px;" title="Descargada"></i>'
      : `<button class="action-btn" onclick="downloadSongFromHistory('${escAttr(s.video_id)}','${escAttr(s.title)}','${escAttr(s.artist)}')" title="Descargar"><i class="fas fa-download"></i></button>`;
    html += `<div class="song-row">
        <div class="info">
          <div class="title">${esc(s.title)}</div>
          <div class="artist">${esc(s.artist)}</div>
        </div>
        <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${played?'#e8f5e9':'#f5f5f5'};color:${played?'var(--primary)':'var(--text-muted)'};font-weight:500;">${played?'Reproducida':'En cola'}</span>
        ${badge}
      </div>`;
  });

  html += '<div class="pagination">';
  if (data.page > 1) {
    html += `<button onclick="fetchHistory(${data.page-1})">Anterior</button>`;
  } else {
    html += '<button disabled>Anterior</button>';
  }
  if (data.page < data.total_pages) {
    html += `<button onclick="fetchHistory(${data.page+1})">Siguiente</button>`;
  } else {
    html += '<button disabled>Siguiente</button>';
  }
  html += '</div>';
  el.innerHTML = html;
}

// ── Download Manager View ──────────────────────────────────────────────────

async function retryDownload(videoId) {
  const res = await api(`/app-music/api/offline/${videoId}/retry`, { method: 'POST' });
  if (res && res.ok) {
    showToast('Reintentando descarga');
    fetchDownloadTasks();
  }
}

async function clearCompleted() {
  const res = await api('/app-music/api/offline/clear-completed', { method: 'POST' });
  if (res && res.ok) {
    showToast(res.removed + ' descargas eliminadas');
    fetchDownloadTasks();
  }
}

async function cancelDownload() {
  const res = await api('/app-music/api/offline/cancel', { method: 'POST' });
  if (res && res.ok) {
    showToast('Descarga cancelada');
  } else {
    showToast('Error al cancelar');
  }
}

async function downloadHistory() {
  const data = state.historyData;
  if (!data || !data.items || data.items.length === 0) {
    showToast('Historial vacio');
    return;
  }
  const ids = data.items.map(s => s.video_id).filter(Boolean);
  if (ids.length === 0) return;
  const statuses = await api('/app-music/api/offline/statuses?ids=' + ids.join(','));
  let count = 0;
  for (const s of data.items) {
    if (!s.video_id) continue;
    if (statuses && statuses[s.video_id] === 'complete') continue;
    await api('/app-music/api/offline/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: s.video_id, title: s.title, artist: s.artist, thumbnail: '' }),
    });
    count++;
  }
  showToast(count + ' canciones agregadas a descargas');
  fetchDownloadTasks();
  await resumeDownloader();
}

async function downloadSongFromHistory(videoId, title, artist) {
  await api('/app-music/api/offline/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_id: videoId, title: title, artist: artist, thumbnail: '' }),
  });
  showToast('Agregada a descargas');
  fetchDownloadTasks();
}

async function fetchOfflineStatuses() {
  const data = state.historyData;
  if (!data || !data.items || data.items.length === 0) return;
  const ids = data.items.map(s => s.video_id).filter(Boolean);
  if (ids.length === 0) return;
  const statuses = await api('/app-music/api/offline/statuses?ids=' + ids.join(','));
  state.offlineStatuses = statuses || {};
}

async function dedupHistory() {
  const res = await api('/app-music/api/history/dedup', { method: 'POST' });
  if (res && res.ok) {
    showToast(res.removed + ' duplicados eliminados');
    fetchHistory(1);
  }
}

function toggleSection(btn) {
  const section = btn.closest('.dl-section');
  section.classList.toggle('collapsed');
  if (!state.sectionState) state.sectionState = {};
  const label = btn.textContent.trim().split(' (')[0];
  state.sectionState[label] = section.classList.contains('collapsed');
}

function getSectionState(label) {
  if (!state.sectionState) state.sectionState = {};
  if (state.sectionState[label] === undefined) state.sectionState[label] = false;
  return state.sectionState[label] ? 'collapsed' : '';
}

function renderDownloadManager() {
  const el = $('queue-full') || (() => {
    const div = document.createElement('div');
    div.id = 'queue-full';
    $('panel-content').appendChild(div);
    return div;
  })();

  el.style.display = 'block';
  const tasks = state.downloadTasks;

  if (!tasks || tasks.length === 0) {
    el.innerHTML = '<div class="empty-state"><i class="fas fa-download"></i><p>Sin descargas</p><p style="font-size:12px;color:var(--text-muted);margin-top:8px;">Agrega canciones con el boton de descarga o usa "Descargar pendientes"</p></div>';
    return;
  }

  const downloading = tasks.filter(t => t.status === 'downloading');
  const pending = tasks.filter(t => t.status === 'pending');
  const completed = tasks.filter(t => t.status === 'complete');
  const failed = tasks.filter(t => t.status === 'failed');

  let html = '<div class="dl-toolbar">';
  html += '<button class="btn-sync" onclick="resumeDownloader()"><i class="fas fa-download"></i> Descargar pendientes</button>';
  if (completed.length > 0) {
    html += '<button class="btn-sync" onclick="clearCompleted()" style="margin-left:6px;"><i class="fas fa-trash"></i> Limpiar completadas</button>';
  }
  html += '</div>';

  if (downloading.length > 0) {
    html += `<div class="dl-section ${getSectionState('Descargando')}"><h3 class="dl-section-title" onclick="toggleSection(this)"><i class="fas fa-circle-notch fa-spin dl-icon"></i> Descargando (${downloading.length}) <span class="collapse-icon"></span></h3><div class="dl-body">`;
    html += downloading.map(t => renderDlTask(t)).join('');
    html += `</div></div>`;
  }

  if (pending.length > 0) {
    html += `<div class="dl-section ${getSectionState('Pendientes')}"><h3 class="dl-section-title" onclick="toggleSection(this)"><i class="fas fa-clock dl-icon"></i> Pendientes (${pending.length}) <span class="collapse-icon"></span></h3><div class="dl-body">`;
    html += pending.map(t => renderDlTask(t)).join('');
    html += `</div></div>`;
  }

  if (completed.length > 0) {
    html += `<div class="dl-section ${getSectionState('Completadas')}"><h3 class="dl-section-title" onclick="toggleSection(this)"><i class="fas fa-check-circle dl-icon" style="color:var(--primary)"></i> Completadas (${completed.length}) <span class="collapse-icon"></span></h3><div class="dl-body">`;
    html += completed.map(t => renderDlTask(t)).join('');
    html += `</div></div>`;
  }

  if (failed.length > 0) {
    html += `<div class="dl-section ${getSectionState('Fallidas')}"><h3 class="dl-section-title" onclick="toggleSection(this)"><i class="fas fa-exclamation-circle dl-icon" style="color:var(--danger)"></i> Fallidas (${failed.length}) <span class="collapse-icon"></span></h3><div class="dl-body">`;
    html += failed.map(t => renderDlTask(t)).join('');
    html += `</div></div>`;
  }

  el.innerHTML = html;
}

function renderDlTask(t) {
  const statusIcon = t.status === 'downloading' ? '<i class="fas fa-circle-notch fa-spin" style="color:var(--primary)"></i>'
    : t.status === 'pending' ? '<i class="fas fa-clock" style="color:var(--text-muted)"></i>'
    : t.status === 'complete' ? '<i class="fas fa-check-circle" style="color:var(--primary)"></i>'
    : '<i class="fas fa-exclamation-circle" style="color:var(--danger)"></i>';

  const actions = t.status === 'failed' || t.status === 'downloading'
    ? `<button class="action-btn" onclick="retryDownload('${escAttr(t.video_id)}')" title="Reintentar"><i class="fas fa-redo"></i></button>`
    : t.status === 'complete'
    ? `<button class="action-btn danger" onclick="deleteOffline('${escAttr(t.video_id)}')" title="Eliminar"><i class="fas fa-trash"></i></button>`
    : '';

  const subtitle = t.status === 'failed' && t.error
    ? `<div class="dl-error">${esc(t.error)}</div>`
    : '';

  let dlInfo = '';
  if (t.status === 'downloading') {
    const total = t.total_mb > 0 ? (t.total_mb >= 1000 ? (t.total_mb/1024).toFixed(1)+' GB' : Math.round(t.total_mb)+' MB') : '';
    const speed = t.speed_mb_s > 0 ? t.speed_mb_s.toFixed(2)+' MB/s' : '';
    const eta = t.eta ? t.eta : '';
    const parts = [total, speed, eta ? 'ETA '+eta : ''].filter(Boolean);
    dlInfo = '<div class="dl-info">'+parts.join(' &middot; ')+'</div>';
  }
  const progressPct = t.status === 'downloading' ? Math.min(Math.max(t.progress, 0), 100) : 0;
  const progressHtml = t.status === 'downloading'
    ? `<div class="progress-bar-dl"><div class="progress-fill-dl" style="width:${progressPct}%"></div><button class="cancel-dl-btn" onclick="cancelDownload()" title="Cancelar descarga"><i class="fas fa-times-circle"></i></button></div><span class="dl-pct">${Math.round(progressPct)}%</span>${dlInfo}`
    : '';

  return `<div class="song-row">
    <div class="info">
      <div class="title"><span class="dl-status-icon">${statusIcon}</span> ${esc(t.actual_title || t.title)}</div>
      <div class="artist">${esc(t.actual_artist || t.artist)}${t.status === 'pending' ? ' <span class="dl-meta">' + (t.created_at || '') + '</span>' : ''}</div>
      ${progressHtml}
      ${subtitle}
    </div>
    <div class="actions">${actions}</div>
  </div>`;
}

// ── Utils ──────────────────────────────────────────────────────────────────

function renderThumb(url, size) {
  if (!url) return `<div class="thumb" style="width:${size}px;height:${size}px;"><i class="fas fa-music"></i></div>`;
  return `<img class="thumb" src="${escAttr(url)}" style="width:${size}px;height:${size}px;"
    onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
    <div class="thumb" style="width:${size}px;height:${size}px;display:none;"><i class="fas fa-music"></i></div>`;
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return (s || '').replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  fetchQueue();
  fetchFavorites();
  showView('search');
  switchCenterTab('results');
});
