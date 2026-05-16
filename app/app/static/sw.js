/**
 * knowly Service Worker
 *
 * Strategy:
 *  - App shell (CSS, JS, fonts, icons)  → Cache-First
 *  - HTML pages                          → Network-First (with offline fallback)
 *  - API endpoints (/api/*)              → Network-Only (always fresh)
 *  - Images                              → Stale-While-Revalidate
 *  - Everything else                     → Network-First
 */

const CACHE_VERSION   = 'v7';
const SHELL_CACHE     = `knowly-shell-${CACHE_VERSION}`;
const IMAGE_CACHE     = `knowly-images-${CACHE_VERSION}`;
const PAGE_CACHE      = `knowly-pages-${CACHE_VERSION}`;

const SHELL_ASSETS = [
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/images/icon-192x192.png',
  '/static/images/icon-512x512.png',
  '/static/fonts/nunito-v32-latin-700.woff2',
  '/static/fonts/nunito-v32-latin-800.woff2',
  '/static/fonts/nunito-v32-latin-900.woff2',
  '/static/fonts/dm-sans-v17-latin-300.woff2',
  '/static/fonts/dm-sans-v17-latin-regular.woff2',
  '/static/fonts/dm-sans-v17-latin-italic.woff2',
  '/static/fonts/dm-sans-v17-latin-500.woff2',
  '/static/fonts/dm-sans-v17-latin-600.woff2',
  '/static/fonts/dm-sans-v17-latin-700.woff2',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
];

const OFFLINE_PAGE = '/offline';

/* ═══════════════════════════════════════
   INSTALL — pre-cache shell + offline page
   Uses individual try/catch so one failure
   doesn't abort the whole install.
   ═══════════════════════════════════════ */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(async cache => {
      // Cache offline page first
      try {
        await cache.add(OFFLINE_PAGE);
        console.log('[SW] Cached offline page OK');
      } catch(e) {
        console.error('[SW] Failed to cache offline page:', e);
      }
      // Cache shell assets individually
      for (const url of SHELL_ASSETS) {
        try {
          await cache.add(url);
          console.log('[SW] Cached OK:', url);
        } catch(e) {
          console.error('[SW] Failed to cache:', url, e.message);
        }
      }
    })
  );
});

/* ═══════════════════════════════════════
   ACTIVATE — remove old caches
   ═══════════════════════════════════════ */
self.addEventListener('activate', event => {
  const keep = [SHELL_CACHE, IMAGE_CACHE, PAGE_CACHE];
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => !keep.includes(k)).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

/* ═══════════════════════════════════════
   FETCH — routing logic
   ═══════════════════════════════════════ */
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET, non-http(s), POST forms, and auth endpoints
  if (request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;
  if (url.pathname.startsWith('/auth/')) return;
  if (url.pathname.startsWith('/admin/')) return;

  // API — always go to network, never cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Payment flows — network only
  if (url.pathname.startsWith('/payments/') || url.pathname.startsWith('/checkout')) {
    event.respondWith(fetch(request));
    return;
  }

  // Shell assets (CSS/JS/fonts) — Cache-First
  if (isShellAsset(url)) {
    event.respondWith(networkFirst(request, SHELL_CACHE));
    return;
  }

  // Images — Stale-While-Revalidate
  if (isImage(url)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
    return;
  }

  // HTML navigation & Turbo — Network-Only (No Cache) with offline fallback
  if (request.mode === 'navigate' || request.headers.get('Turbo-Frame') || request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkOnlyPage(request));
    return;
  }

  // Default — Network-First
  event.respondWith(networkFirst(request, PAGE_CACHE));
});

/* ═══════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════ */

function isShellAsset(url) {
  if (url.pathname.startsWith('/static/css/') ||
      url.pathname.startsWith('/static/js/')  ||
      url.pathname === '/static/manifest.json') return true;
  // External CDN assets (Font Awesome, Google Fonts)
  if (url.hostname === 'cdnjs.cloudflare.com') return true;
  if (url.hostname === 'fonts.googleapis.com') return true;
  if (url.hostname === 'fonts.gstatic.com')    return true;
  return false;
}

function isImage(url) {
  return /\.(png|jpg|jpeg|webp|gif|svg|ico)(\?.*)?$/i.test(url.pathname) ||
    url.hostname === 'res.cloudinary.com';
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache  = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  return cached || await fetchPromise || new Response('', { status: 503 });
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response('Offline', { status: 503 });
  }
}

async function networkOnlyPage(request) {
  try {
    return await fetch(request);
  } catch {
    // Fall back to the offline page (cached during install)
    const offlinePage = await caches.match(OFFLINE_PAGE);
    if (offlinePage) return offlinePage;
    
    // Last resort — minimal offline response
    return new Response(
      `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline – knowly</title>
<style>
  body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;
       min-height:100vh;margin:0;background:#f8fafc;color:#0f172a;text-align:center;padding:2rem}
  .card{background:#fff;border-radius:20px;padding:2.5rem 2rem;max-width:360px;
        box-shadow:0 4px 24px rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.15)}
  .icon{font-size:3.5rem;margin-bottom:1rem}
  h1{font-size:1.5rem;font-weight:800;margin-bottom:.5rem;color:#6366f1}
  p{color:#64748b;line-height:1.6;margin-bottom:1.5rem}
  button{background:#6366f1;color:#fff;border:none;padding:.75rem 1.5rem;border-radius:10px;
         font-size:1rem;font-weight:600;cursor:pointer}
  button:hover{background:#4f46e5}
</style></head>
<body><div class="card">
  <div class="icon">📚</div>
  <h1>You're offline</h1>
  <p>Connect to the internet to keep studying with knowly.</p>
  <button onclick="location.reload()">Try again</button>
</div></body></html>`,
      { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(PAGE_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Try the cache
    const cached = await caches.match(request);
    if (cached) return cached;

    // Fall back to the offline page (cached during install if available)
    const offlinePage = await caches.match(OFFLINE_PAGE);
    if (offlinePage) return offlinePage;

    // Last resort — minimal offline response
    return new Response(
      `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline – knowly</title>
<style>
  body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;
       min-height:100vh;margin:0;background:#f8fafc;color:#0f172a;text-align:center;padding:2rem}
  .card{background:#fff;border-radius:20px;padding:2.5rem 2rem;max-width:360px;
        box-shadow:0 4px 24px rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.15)}
  .icon{font-size:3.5rem;margin-bottom:1rem}
  h1{font-size:1.5rem;font-weight:800;margin-bottom:.5rem;color:#6366f1}
  p{color:#64748b;line-height:1.6;margin-bottom:1.5rem}
  button{background:#6366f1;color:#fff;border:none;padding:.75rem 1.5rem;border-radius:10px;
         font-size:1rem;font-weight:600;cursor:pointer}
  button:hover{background:#4f46e5}
</style></head>
<body><div class="card">
  <div class="icon">📚</div>
  <h1>You're offline</h1>
  <p>Connect to the internet to keep studying with knowly.</p>
  <button onclick="location.reload()">Try again</button>
</div></body></html>`,
      { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

/* ═══════════════════════════════════════
   BACKGROUND SYNC (optional)
   Retries failed POST requests when back online
   ═══════════════════════════════════════ */
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    // Placeholder — expand for offline like/bookmark queue
    event.waitUntil(Promise.resolve());
  }
});

/* ═══════════════════════════════════════
   PUSH NOTIFICATIONS (optional scaffold)
   ═══════════════════════════════════════ */
self.addEventListener('push', event => {
  if (!event.data) return;
  const data = event.data.json().catch(() => ({ title: 'knowly', body: event.data.text() }));
  event.waitUntil(
    data.then(payload =>
      self.registration.showNotification(payload.title || 'knowly', {
        body:    payload.body    || '',
        icon:    '/static/images/icon-192x192.png',
        badge:   '/static/images/icon-96x96.png',
        data:    { url: payload.url || '/' },
        vibrate: [200, 100, 200],
      })
    )
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const existing = list.find(c => c.url === url && 'focus' in c);
      return existing ? existing.focus() : clients.openWindow(url);
    })
  );
});

/* ═══════════════════════════════════════
   MESSAGE — allow pages to trigger SW update
   Send { type: 'SKIP_WAITING' } to activate
   a waiting SW immediately.
   ═══════════════════════════════════════ */
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});