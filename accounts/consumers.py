import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .realtime import (
    build_profile_live_payload,
    get_profile_group_name,
)


class ProfileAuctionStateConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not getattr(user, 'is_authenticated', False):
            await self.close()
            return

        self.user_id = str(user.pk)
        self.group_name = get_profile_group_name(self.user_id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        payload = await database_sync_to_async(build_profile_live_payload)(user)
        await self.send(
            text_data=json.dumps(
                {
                    'type': 'initial_state',
                    'payload': payload,
                }
            )
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def profile_auction_update(self, event):
        payload = await database_sync_to_async(build_profile_live_payload)(
            self.scope.get('user')
        )
        await self.send(
            text_data=json.dumps(
                {
                    'type': 'profile_update',
                    'payload': payload,
                }
            )
        )
