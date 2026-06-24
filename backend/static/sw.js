const CACHE = 'cancionero-v4';
const ASSETS = [
  '/app-music/',
  '/app-music/static/index.html',
  '/app-music/static/app.js',
  '/app-music/static/styles.css',
  '/app-music/static/manifest.json',
  '/app-music/static/icons/icon.svg',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((cache) => {
      return cache.addAll(ASSETS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  if (ASSETS.includes(url.pathname)) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }

  if (url.pathname.startsWith('/app-music/api/')) {
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request).then((cached) => cached || new Response('{"error":"offline"}', {
        status: 503, headers: { 'Content-Type': 'application/json' },
      })))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((cached) => {
      return cached || fetch(e.request).catch(() => new Response('Offline', { status: 503 }));
    })
  );
});
