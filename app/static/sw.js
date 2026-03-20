/* ============================================================
   SESA Service Worker
   Strategy:
     - Static assets (css/js/images/fonts): cache-first
     - Navigation / HTML pages:             network-first with cache fallback
     - API / POST requests:                 network-only (never cache)
   ============================================================ */

const CACHE_VERSION = 'sesa-v4'; // bump this every deployment to force cache refresh
const STATIC_ASSETS = [
  '/static/css/main.css',
  '/static/js/main.js',
  '/static/manifest.json',
  '/static/images/Pofa_pwa.png',
  '/static/images/Pofa_pwa-192.png',
  '/static/images/Pofa.png',  // keep only one logo variant
  '/offline',
];

// ── Install: pre-cache static assets ────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
      .catch(err => console.warn('[SW] Pre-cache failed:', err))
  );
});

// ── Activate: remove old caches ─────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(
        names.filter(n => n !== CACHE_VERSION).map(n => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and cross-origin requests
  if (request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  // Network-only: API endpoints and all pages that show health data
  const NEVER_CACHE = [
    '/test/api/',
    '/test/result/',
    '/home',
    '/results',
    '/counsellor/',
    '/admin/',
    '/school/',
  ];
  if (NEVER_CACHE.some(p => url.pathname.startsWith(p))) return;

  // Static assets: cache-first
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname === '/static/manifest.json'
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // HTML navigation: network-first with offline fallback
  if (request.mode === 'navigate' || request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstWithOfflineFallback(request));
    return;
  }
});

// ── Strategies ───────────────────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Asset unavailable offline.', { status: 503 });
  }
}

async function networkFirstWithOfflineFallback(request) {
  try {
    const response = await fetch(request);
    // Update cache with fresh page on success
    if (response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Try cache, then dedicated offline page
    const cached = await caches.match(request);
    if (cached) return cached;
    const offline = await caches.match('/offline');
    return offline || new Response(
      '<h1>You are offline</h1><p>Please reconnect and try again.</p>',
      { status: 503, headers: { 'Content-Type': 'text/html' } }
    );
  }
}
