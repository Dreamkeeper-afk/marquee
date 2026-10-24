// Marquee service worker: lets the app be installed, and shows its notifications. Everything else is live.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: "Marquee", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Marquee",
    { body: d.body || "", icon: "/static/icon-192.png", badge: "/static/icon-192.png", tag: "marquee-" + (d.page || "news"),
      data: { page: d.page || "home" } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const page = (e.notification.data && e.notification.data.page) || "home";
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((list) => {
    if (list.length) { list[0].postMessage({ page }); return list[0].focus(); }
    return self.clients.openWindow("/#" + page);
  }));
});
