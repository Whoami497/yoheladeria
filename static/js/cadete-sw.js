// /static/js/cadete-sw.js

// (opcional) ajustá la URL del panel del cadete si fuera distinta
const FALLBACK_URL = "/cadete/panel/";

// Install/activate simples para asegurar control del SW
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => self.clients.claim());

// Recibir el push y mostrar la notificación
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}

  const title = data.title || "Nuevo pedido disponible";
  const body  = data.body  || "Tenés un pedido para aceptar o seguir.";
  const url   = data.url   || FALLBACK_URL;

  const options = {
    body,
    // icon: "/static/images/push-icon.png",   // opcional: si tenés icono
    // badge: "/static/images/push-badge.png", // opcional: si tenés badge
    data: { url },
    actions: [{ action: "open", title: "Abrir" }],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Abrir/enfocar el panel al tocar la notificación
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || FALLBACK_URL;

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientsArr) => {
      for (const c of clientsArr) {
        // si ya hay una pestaña al panel, enfocarla
        if (c.url.includes("/cadete/panel") && "focus" in c) return c.focus();
      }
      // si no hay, abrir una nueva
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
