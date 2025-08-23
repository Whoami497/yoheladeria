/* eslint-disable no-restricted-globals */
// Service Worker para push

self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data.json(); }
  catch (e) {
    data = { title: 'Yo Heladerías', body: event.data && event.data.text() };
  }

  const title = data.title || 'Yo Heladerías';
  const options = {
  body: data.body || 'Tocá para abrir',
  tag: 'order-alert',        // agrupa notis del mismo tipo
  renotify: true,            // vuelve a vibrar si llega otra del mismo tag
  vibrate: [100, 50, 100],
  requireInteraction: true,  // queda visible hasta que el usuario interactúe
  data: { url: data.url || '/cadete/panel/' }
};


self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/cadete/panel/';
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      try {
        if (client.url && client.url.startsWith(self.location.origin)) {
          await client.focus();
          await client.navigate(target);
          return;
        }
      } catch (_) {}
    }
    await clients.openWindow(target);
  })());
});
