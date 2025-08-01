import json
from channels.generic.websocket import WebsocketConsumer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# ===================================================================
# == CONSUMER PARA EL PANEL DE ALERTAS DE LA TIENDA (EXISTENTE) ==
# ===================================================================
class PedidoNotificationConsumer(WebsocketConsumer):
    def connect(self):
        self.room_group_name = 'pedidos_new_orders' # Canal para la tienda
        self.channel_layer = get_channel_layer()

        print(f"TIENDA CONSUMER CONNECT: Conectando y uniendo al grupo: {self.room_group_name}")
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )
        self.accept()

    def disconnect(self, close_code):
        print(f"TIENDA CONSUMER DISCONNECT: Desconectando del grupo: {self.room_group_name}")
        if hasattr(self, 'channel_layer'): 
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name,
                self.channel_name
            )

    # Este método es llamado por la vista ver_carrito
    def send_order_notification(self, event):
        print(f"TIENDA CONSUMER: Mensaje recibido: {event}")

        message = event.get('message')
        order_id = event.get('order_id')
        order_data = event.get('order_data')

        if message and order_id and order_data:
            self.send(text_data=json.dumps({
                'message': message,
                'order_id': order_id,
                'order_data': order_data
            }))
            print(f"TIENDA CONSUMER: Notificación de pedido #{order_id} enviada al frontend.")

# ===============================================================
# == CONSUMER PARA EL PANEL DE LOS CADETES (NUEVO) ==
# ===============================================================
class CadeteNotificationConsumer(WebsocketConsumer):
    def connect(self):
        self.user = self.scope['user']

        # --- VERIFICACIÓN DE AUTENTICACIÓN ---
        # Si el usuario no está logueado o no tiene un perfil de cadete, se rechaza la conexión.
        if not self.user.is_authenticated or not hasattr(self.user, 'cadeteprofile'):
            self.close()
            return

        self.room_group_name = 'cadetes_disponibles' # Canal para los cadetes
        self.channel_layer = get_channel_layer()

        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )
        self.accept()
        print(f"CADETE CONSUMER: El cadete {self.user.username} se ha conectado al canal.")

    def disconnect(self, close_code):
        if hasattr(self, 'channel_layer'):
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name,
                self.channel_name
            )
        print(f"CADETE CONSUMER: El cadete {self.scope.get('user', 'Usuario anónimo')} se ha desconectado.")

    # Este método será llamado por la vista confirmar_pedido
    def send_cadete_notification(self, event):
        # Simplemente reenvía todo el evento (que contendrá los datos del pedido)
        # al WebSocket del cadete.
        self.send(text_data=json.dumps(event))
        print(f"CADETE CONSUMER: Notificación enviada a {self.user.username}.")