/* Veille virale : service worker — notifications push et ouverture de l'application. Pas de cache : toujours la dernière version. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {texte: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.titre || "Veille virale", {
    body: d.texte || "", icon: "/static/icones/icone-192.png", badge: "/static/icones/icone-192.png", data: {url: d.url || "/app"}, lang: "fr"
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/app";
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(l => {
    const w = l.find(c => new URL(c.url).pathname.startsWith("/app") || new URL(c.url).pathname === "/");
    return w ? w.focus().then(c => c.navigate ? c.navigate(url) : c) : self.clients.openWindow(url);
  }));
});
