const CACHE_NAME = 'au-daily-cache-v8';
const urlsToCache = [
    '/static/style.css',
    '/static/AUlogo.jpg',
    '/offline.html'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(cacheNames => Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                    return null;
                })
            ))
            .then(() => self.clients.claim())
    );
});

function isNavigationRequest(request) {
    const accept = request.headers.get('accept') || '';
    return request.mode === 'navigate' || accept.includes('text/html');
}

function isSafeStaticAsset(request) {
    const url = new URL(request.url);
    return request.method === 'GET'
        && url.origin === self.location.origin
        && (url.pathname.startsWith('/static/') || url.pathname === '/offline.html');
}

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') {
        return;
    }

    if (isNavigationRequest(event.request)) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match('/offline.html'))
        );
        return;
    }

    if (!isSafeStaticAsset(event.request)) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then(cachedResponse => {
            if (cachedResponse) {
                return cachedResponse;
            }

            return fetch(event.request).then(response => {
                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseToCache));
                return response;
            });
        })
    );
});
