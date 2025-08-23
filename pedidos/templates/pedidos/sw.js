// templates/pedidos/sw.js

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Recibir push
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'Nuevo pedido', body: event.data ? event.data.text() : '' };
  }

  const title = data.title || 'Yo Heladerías';
  const options = {
    body: data.body || 'Nuevo pedido disponible. Tocá para abrir el panel.',
    icon: data.icon || '/static/images/push-icon.png',
    badge: data.badge || '/static/images/push-badge.png',
    data: { url: data.url || '/cadete/panel/' },
    tag: data.tag || 'yoheladerias-pedidos',
    renotify: true,
    vibrate: [120, 40, 120],
    actions: [{ action: 'open', title: 'Abrir panel' }]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Click en la notificación
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/cadete/panel/';
  event.waitUntil(
    (async () => {
      const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of allClients) {
        if ('focus' in client && client.url.includes('/cadete/panel')) {
          client.focus();
          return;
        }
      }
      await clients.openWindow(url);
    })()
  );
});
