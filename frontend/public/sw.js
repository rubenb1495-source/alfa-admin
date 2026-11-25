const CACHE_NAME = "alfa-admin-shell-v1";
const STATIC_ASSETS = [
  "/manifest.json",
  "/alfa-favicon.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Nunca cachear llamadas a la API ni métodos que no sean GET
  if (
    event.request.method !== "GET" ||
    url.pathname.startsWith("/api/") ||
    url.origin !== self.location.origin
  ) {
    return;
  }

  // Solo cachear íconos y manifest estático; el resto siempre red primero
  if (
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.json" ||
    url.pathname === "/alfa-favicon.png"
  ) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
