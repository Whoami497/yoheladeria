# pedidos/consumers/notifications.py

import json
from channels.generic.websocket import WebsocketConsumer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync # <-- ¡Asegúrate de importar esto!

class PedidoNotificationConsumer(WebsocketConsumer):
    def connect(self):
        self.room_group_name = 'pedidos_new_orders' # Nombre del grupo hardcodeado

        self.channel_layer = get_channel_layer()

        print(f"DEBUG CONSUMER CONNECT: Conectando y uniendo al grupo: {self.room_group_name}")
        # Envuelve las operaciones de grupo en async_to_sync
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )
        self.accept()

        # --- CÓDIGO TEMPORAL DE DIAGNÓSTICO: ENVÍA UN MENSAJE DE PRUEBA DESDE EL MISMO CONSUMER ---
        # Esto verificará si la comunicación interna del Channel Layer funciona
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                "type": "send_order_notification", # Usamos el mismo tipo que envía la vista
                "message": "TEST: Mensaje enviado por el propio consumidor al conectarse.",
                "order_id": "TEST_ID",
                "order_data": {"source": "consumer_connect_test"}
            }
        )
        print("DEBUG CONSUMER: Enviado un mensaje de prueba desde connect() a su propio grupo.")
        # --- FIN CÓDIGO TEMPORAL DE DIAGNÓSTICO ---

    def disconnect(self, close_code):
        print(f"DEBUG CONSUMER DISCONNECT: Desconectando del grupo: {self.room_group_name}")
        if hasattr(self, 'channel_layer'): 
            # Envuelve también la operación de desconexión
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name,
                self.channel_name
            )

    def send_order_notification(self, event):
        # ESTE PRINT ES EL MÁS IMPORTANTE. SI ESTO NO APARECE, EL MENSAJE NO ESTÁ LLEGANDO AL CONSUMER.
        print(f"DEBUG CONSUMER: ¡MENSAJE RECIBIDO EN CONSUMER! Tipo: {event.get('type')}, Evento Completo: {event}")

        if event.get('type') == 'send_order_notification':
            message = event.get('message')
            order_id = event.get('order_id')
            order_data = event.get('order_data')

            if message and order_id and order_data:
                self.send(text_data=json.dumps({
                    'message': message,
                    'order_id': order_id,
                    'order_data': order_data
                }))
                print(f"DEBUG CONSUMER: Notificación de pedido #{order_id} ENVIADA al frontend.")
            else:
                print(f"DEBUG CONSUMER: Datos incompletos en el evento: {event}")
        else:
            print(f"DEBUG CONSUMER: Mensaje de tipo desconocido recibido: {event.get('type')}. Evento: {event}")