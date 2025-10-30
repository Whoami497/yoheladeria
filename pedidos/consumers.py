# pedidos/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

GROUP_PEDIDOS = "pedidos_new_orders"

class PedidoNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(GROUP_PEDIDOS, self.channel_name)
        await self.accept()
        # opcional: aviso de conexión
        await self.send(text_data=json.dumps({"message": "ws.connected"}))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP_PEDIDOS, self.channel_name)

    async def receive(self, text_data):
        # keep-alive opcional desde el frontend
        # (no esperamos mensajes del cliente)
        return

    # === HANDLERS QUE DEBEN COINCIDIR CON EL "type" DEL group_send ===

    # Compatibilidad con tu back actual (vista ver_carrito)
    async def send_order_notification(self, event):
        # event = {"type": "send_order_notification", "order_id": ..., "order_data": {...}, "message": "..."}
        await self.send(text_data=json.dumps({
            "message": event.get("message", "nuevo_pedido"),
            "order_id": event.get("order_id"),
            "order_data": event.get("order_data"),
        }))

    # Si más adelante querés usarlos, también quedan disponibles:
    async def nuevo_pedido(self, event):
        await self.send(text_data=json.dumps({
            "message": "nuevo_pedido",
            "order_id": event.get("order_id"),
            "order_data": event.get("order_data"),
        }))

    async def actualizacion_pedido(self, event):
        await self.send(text_data=json.dumps({
            "message": "actualizacion_pedido",
            "order_id": event.get("order_id"),
            "order_data": event.get("order_data"),
        }))

    async def tienda_estado(self, event):
        await self.send(text_data=json.dumps({
            "message": "tienda_estado",
            "order_data": event.get("order_data"),
        }))

# --- PARA CADETES (si lo usás) ---
class CadeteNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass
