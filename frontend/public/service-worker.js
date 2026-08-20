// Bump when fetch strategy changes so clients pick up new worker.
const CACHE_NAME = "laundry-ops-shell-v11-veewash-icons";
const APP_SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icons/veewash-icon-192-v1.png",
  "/icons/veewash-icon-512-v1.png",
  "/icons/veewash-apple-touch-180-v1.png",
  "/washpro-mark.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

function isPinPublicPath(pathname) {
  const p = String(pathname || "");
  return (
    p === "/pin" ||
    p.startsWith("/pin/") ||
    p === "/attendance" ||
    p.startsWith("/attendance/") ||
    p === "/kiosk" ||
    p.startsWith("/kiosk/")
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return;

  let url;
  try {
    url = new URL(request.url);
    if (url.protocol !== "http:" && url.protocol !== "https:") return;
  } catch {
    return;
  }

  // Never cache-first PIN / attendance / kiosk shells — stale start_url installs break iOS A2HS.
  if (request.mode === "navigate" && isPinPublicPath(url.pathname)) {
    event.respondWith(fetch(request).catch(() => caches.match("/index.html")));
    return;
  }

  if (/\.webmanifest$/i.test(url.pathname)) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached || caches.match("/index.html");
        })
    );
    return;
  }

  if (url.origin !== self.location.origin) {
    return;
  }

  // Live operational APIs must never be served from cache.
  if (url.pathname.startsWith("/rinse/") || url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(request));
    return;
  }

  // Never cache-first JS/CSS bundles (PWA would keep stale i18n / UI after deploy).
  if (url.pathname.startsWith("/assets/") || /\.(?:js|css)(?:\?|$)/i.test(url.pathname)) {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;

      return fetch(request).then((response) => {
        if (!response || response.status !== 200 || response.type !== "basic") {
          return response;
        }

        const cloned = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
        return response;
      });
    })
  );
});
