// sw.js  — Service Worker de notificaciones para cadetes

// Aplicar la actualización del SW sin esperar
self.addEventListener('install', (event) => {
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Push -> mostrar notificación
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    try { data = JSON.parse(event.data.text()); } catch(_) {}
  }

  // El backend envía "title", "body" y "url"
  const title = data.title || data.head || 'Yo Heladerías';
  const body  = data.body  || 'Nuevo pedido disponible';
  const url   = data.url   || '/cadete/panel/';

  const options = {
    body,
    data: { url },
    // Estos iconos son opcionales; ponelos si existen en tu static/
    icon:  data.icon  || '/static/pedidos/icons/notification-192.png',
    badge: data.badge || '/static/pedidos/icons/badge-72.png',
    tag:   data.tag   || 'yoheladeria-new-order', // agrupa notifs
    renotify: true,
    vibrate: data.vibrate || [200, 100, 200],
    requireInteraction: !!data.requireInteraction, // en mobile puede ignorarse
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Click en la notificación -> enfocar/abrir el panel del cadete
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl =
    (event.notification.data && event.notification.data.url) || '/cadete/panel/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          // Si ya hay una pestaña, la enfocamos y navegamos al panel si hace falta
          if ('focus' in client) {
            if (!client.url.includes('/cadete/panel')) {
              client.navigate(targetUrl);
            }
            return client.focus();
          }
        }
        // Si no hay pestañas, abrir una nueva
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl);
        }
      })
  );
});
