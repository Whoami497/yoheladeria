// sw.js — Service Worker de notificaciones para cadetes
// Cambiá la versión para forzar actualización del SW
const SW_VERSION = 'v3-2025-09-15';

// ————————————————————————————————————————————————
// Ciclo de vida
// ————————————————————————————————————————————————
self.addEventListener('install', (event) => {
  // console.log('[SW] install', SW_VERSION);
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // console.log('[SW] activate', SW_VERSION);
  event.waitUntil(self.clients.claim());
});

// ————————————————————————————————————————————————
// PUSH: mostrar notificación incluso con la app cerrada
// Espera recibir desde el backend: { title, body, url, ...opcionales }
// ————————————————————————————————————————————————
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    try { data = JSON.parse(event.data.text()); } catch (_) { data = {}; }
  }

  const title = data.title || data.head || 'Yo Heladerías';
  const body  = data.body  || 'Nuevo pedido disponible';
  const url   = data.url   || '/cadete/panel/';

  const options = {
    body,
    data: { url, v: SW_VERSION },
    icon:  data.icon  || '/static/pedidos/icons/notification-192.png',
    badge: data.badge || '/static/pedidos/icons/badge-72.png',
    tag:   data.tag   || 'yoheladeria-new-order', // agrupa notificaciones
    renotify: true,
    vibrate: data.vibrate || [200, 100, 200],
    requireInteraction: !!data.requireInteraction,
    silent: false,
    actions: [
      { action: 'open', title: 'Abrir panel' },
    ],
  };

  event.waitUntil((async () => {
    // Opcional: cerrar previas del mismo tag para que no queden duplicadas visibles
    const existing = await self.registration.getNotifications({ tag: options.tag });
    existing.forEach(n => n.close());

    await self.registration.showNotification(title, options);
  })());
});

// ————————————————————————————————————————————————
// CLICK en la notificación: enfocar o abrir el panel del cadete
// Si hay una pestaña de la app, la enfoca y navega al panel si hace falta.
// Si no hay, abre una nueva ventana a /cadete/panel/.
// ————————————————————————————————————————————————
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  // Respetar la acción (por si en el futuro agregás más)
  const action = event.action || 'open';

  // Normalizar URL al mismo origen del SW (evita abrir dominios externos desde el SW)
  const rawUrl = (event.notification.data && event.notification.data.url) || '/cadete/panel/';
  const targetUrl = new URL(rawUrl, self.location.origin).href;

  event.waitUntil((async () => {
    const clientsArr = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });

    // Si ya existe una pestaña de la app:
    for (const c of clientsArr) {
      try {
        // Si ya está en el panel, solo enfocar
        if (c.url.includes('/cadete/panel')) {
          if ('focus' in c) await c.focus();
          return;
        }
        // Está en la app pero en otra ruta -> enfocar + navegar (mismo origen)
        if ('focus' in c) await c.focus();
        if ('navigate' in c) {
          await c.navigate(targetUrl);
          return;
        }
      } catch (_) {}
    }

    // Si no hay pestañas de la app, abrir una nueva
    if (action === 'open') {
      return self.clients.openWindow(targetUrl);
    }
  })());
});

// ————————————————————————————————————————————————
// Algunos navegadores vencen la suscripción: avisar al usuario
// ————————————————————————————————————————————————
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

// ————————————————————————————————————————————————
// Canal simple de mensajes para diagnósticos (p.ej. versión de SW)
// ————————————————————————————————————————————————
self.addEventListener('message', (event) => {
  if (event.data === 'SW_VERSION?') {
    event.ports && event.ports[0] && event.ports[0].postMessage({ version: SW_VERSION });
  }
});

/*
NOTA:
- Asegurate de registrar este SW con un scope que incluya "/cadete/panel/".
- Si lo servís desde una ruta no raíz, en la vista de Django podés agregar:
    resp["Service-Worker-Allowed"] = "/"
  para permitir scope en "/".
*/
