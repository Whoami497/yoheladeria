// sw.js — Service Worker de notificaciones para cadetes
// Versión para forzar actualización de SW (cambiar cuando hagas cambios)
const SW_VERSION = 'v2-2025-09-09';

// Instalar y tomar control inmediatamente
self.addEventListener('install', (event) => {
  // útil para debugging/ver que cargó la versión nueva
  // console.log('[SW] install', SW_VERSION);
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  // console.log('[SW] activate', SW_VERSION);
  event.waitUntil(self.clients.claim());
});

// === PUSH: mostrar notificación incluso con pestaña cerrada ===
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    try { data = JSON.parse(event.data.text()); } catch (_) { data = {}; }
  }

  // El backend envía "title", "body" y "url"
  const title = data.title || data.head || 'Yo Heladerías';
  const body  = data.body  || 'Nuevo pedido disponible';
  const url   = data.url   || '/cadete/panel/';

  // Opciones de la notificación (iconos opcionales si existen en static/)
  const options = {
    body,
    data: { url, v: SW_VERSION },
    icon:  data.icon  || '/static/pedidos/icons/notification-192.png',
    badge: data.badge || '/static/pedidos/icons/badge-72.png',
    tag:   data.tag   || 'yoheladeria-new-order', // agrupa
    renotify: true,
    vibrate: data.vibrate || [200, 100, 200],
    requireInteraction: !!data.requireInteraction, // en mobile puede ignorarse
    silent: false, // intenta que el SO no silencie (algunos lo ignoran)
    actions: [
      { action: 'open', title: 'Abrir panel' },
    ],
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// === CLICK en la notificación: enfocar/abrir el panel del cadete ===
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl =
    (event.notification.data && event.notification.data.url) || '/cadete/panel/';

  const go = async () => {
    const clientsArr = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Si ya hay una pestaña de la app, enfocarla (y navegar si no es el panel)
    for (const c of clientsArr) {
      try {
        if (c.url.includes('/cadete/panel')) return c.focus();
      } catch(_) {}
    }
    return self.clients.openWindow(targetUrl);
  };

  event.waitUntil(go());
});

// === (Opcional) pushsubscriptionchange: algunos navegadores vencen la suscripción ===
// No podemos re-suscribir desde el SW (CSRF/login), así que avisamos al usuario para reactivarla.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    self.registration.showNotification('Actualizá tus notificaciones', {
      body: 'Tocá para reactivar las notificaciones del cadete.',
      data: { url: '/cadete/panel/?renew_push=1', v: SW_VERSION },
      tag: 'yoheladeria-push-renew',
      renotify: true,
      badge: '/static/pedidos/icons/badge-72.png',
      icon: '/static/pedidos/icons/notification-192.png',
      vibrate: [120, 80, 120],
    })
  );
});

// (Opcional) canal de mensajes para diagnósticos simples desde la página
self.addEventListener('message', (event) => {
  if (event.data === 'SW_VERSION?') {
    event.ports && event.ports[0] && event.ports[0].postMessage({ version: SW_VERSION });
  }
});
