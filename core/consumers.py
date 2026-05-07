import json

try:
    from channels.generic.websocket import AsyncWebsocketConsumer
except ImportError:
    class AsyncWebsocketConsumer:
        async def close(self, code=None):
            return None


class AdminNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not getattr(user, 'is_staff', False):
            await self.close()
            return

        await self.channel_layer.group_add('admin_notifications', self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard('admin_notifications', self.channel_name)

    async def notification(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    'type': event['notification_type'],
                    'title': event['title'],
                    'message': event['message'],
                    'data': event['data'],
                    'timestamp': event['timestamp'],
                },
                default=str,
            )
        )
