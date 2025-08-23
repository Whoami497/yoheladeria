self.addEventListener('push', event => {
  let data = {};
  try { data = event.data.json(); } catch(e){ data = {title:'Nuevo aviso', body:'Tienes una notificación'}; }
  const title = data.title || 'Yo Heladerías';
  const body  = data.body  || '';
  const url   = data.url   || '/cadete/panel/';

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '/static/images/logo_yo_heladeria_blanco.png',
      badge: '/static/images/logo_yo_heladeria_blanco.png',
      data: { url }
    })
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/cadete/panel/';
  event.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(clientList=>{
    for (const client of clientList) {
      if (client.url.includes(url) && 'focus' in client) return client.focus();
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
