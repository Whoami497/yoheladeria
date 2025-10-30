# pedidos/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from pedidos.models import Pedido

class PedidoNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("TIENDA CONSUMER CONNECT: Conectando y uniendo al grupo: pedidos_new_orders")
        await self.channel_layer.group_add("pedidos_new_orders", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        print("TIENDA CONSUMER DISCONNECT")
        await self.channel_layer.group_discard("pedidos_new_orders", self.channel_name)

    async def receive(self, text_data):
        print("TIENDA CONSUMER: Mensaje recibido:", text_data)
        # No esperamos mensajes del frontend

    async def nuevo_pedido(self, event):
        print("TIENDA CONSUMER: Notificación de pedido #{} enviada al frontend.".format(event['order_id']))
        await self.send(text_data=json.dumps({
            'message': 'nuevo_pedido',
            'order_id': event['order_id'],
            'order_data': event['order_data']
        }))

    async def actualizacion_pedido(self, event):
        await self.send(text_data=json.dumps({
            'message': 'actualizacion_pedido',
            'order_id': event['order_id'],
            'order_data': event['order_data']
        }))

    async def tienda_estado(self, event):
        await self.send(text_data=json.dumps({
            'message': 'tienda_estado',
            'order_data': event['order_data']
        }))

# --- PARA CADETES (si lo usas) ---
class CadeteNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
    async def disconnect(self, close_code):
        pass