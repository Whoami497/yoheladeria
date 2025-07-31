// Este console.log nos ayuda a saber que el service worker se está cargando
console.log('Service Worker - Cargado y listo para recibir notificaciones.');

// 1. Escuchar el evento 'push' (cuando llega una notificación del servidor)
self.addEventListener('push', function(event) {
    console.log('[Service Worker] Notificación Push Recibida.');
    
    // El servidor nos envía los datos como texto, los convertimos a JSON
    const data = event.data.json();
    console.log('[Service Worker] Datos de la notificación:', data);

    const title = data.head || "Notificación de Yo Heladerías";
    const options = {
        body: data.body || 'Tienes un nuevo mensaje.',
        icon: data.icon || '/static/images/logo_yo_heladeria_blanco.png', // Un ícono por defecto
        badge: data.icon || '/static/images/logo_yo_heladeria_blanco.png', // Ícono para la barra de notificaciones en Android
        data: {
            url: data.url || '/' // La URL a la que se irá al hacer clic
        }
    };

    // Usamos event.waitUntil para asegurar que el navegador no cierre el service worker
    // antes de que la notificación se haya mostrado.
    event.waitUntil(self.registration.showNotification(title, options));
});

// 2. Escuchar el evento 'notificationclick' (cuando el usuario hace clic en la notificación)
self.addEventListener('notificationclick', function(event) {
    console.log('[Service Worker] Clic en la notificación recibido.');

    // Cerramos la notificación
    event.notification.close();

    // Abrimos la URL que pasamos en los datos de la notificación
    event.waitUntil(
        clients.openWindow(event.notification.data.url)
    );
});