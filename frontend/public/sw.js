const CACHE_NAME = "shiftpilotai-shell-v1";
const SHELL_ROUTES = ["/", "/login", "/launch"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ROUTES))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((cacheNames) =>
        Promise.all(
          cacheNames
            .filter((cacheName) => cacheName !== CACHE_NAME)
            .map((cacheName) => caches.delete(cacheName)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(request).catch(() =>
      caches.match(request).then((cached) => cached || caches.match("/login")),
    ),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const navigationUrl = event.notification.data?.navigationUrl;
  if (!navigationUrl) return;

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if ("focus" in client) {
            client.focus();
            break;
          }
        }

        return self.clients.openWindow(navigationUrl);
      }),
  );
});

self.addEventListener("push", (event) => {
  const fallbackPayload = {
    title: "Travel reminder",
    body: "It is almost time to leave.",
    tag: "travel-reminder",
    navigationUrl: "/calendar",
  };
  const payload = event.data ? event.data.json() : fallbackPayload;

  event.waitUntil(
    self.registration.showNotification(payload.title || fallbackPayload.title, {
      body: payload.body || fallbackPayload.body,
      tag: payload.tag || fallbackPayload.tag,
      icon: "/images/icon/icon.png",
      badge: "/images/icon/icon.png",
      data: {
        navigationUrl: payload.navigationUrl || fallbackPayload.navigationUrl,
        reminderId: payload.reminderId,
      },
      actions: [
        {
          action: "navigate",
          title: "Start navigation",
        },
      ],
    }),
  );
});
