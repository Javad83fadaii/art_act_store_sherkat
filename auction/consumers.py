import json
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .realtime import build_bid_live_payload, get_auction_product_group_name


class AuctionProductBidConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.product_pk = int(self.scope['url_route']['kwargs']['product_pk'])
        self.group_name = get_auction_product_group_name(self.product_pk)
        query_params = parse_qs((self.scope.get('query_string') or b'').decode())
        self.include_user_history = query_params.get('compact', ['0'])[0] != '1'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        try:
            # دریافت داده‌ها ممکن است کمی زمان ببرد
            payload = await database_sync_to_async(build_bid_live_payload)(
                self.product_pk,
                self.scope.get('user'),
                include_user_history=self.include_user_history,
            )
            # تلاش برای ارسال داده به کلاینت
            await self.send(
                text_data=json.dumps(
                    {
                        'type': 'initial_state',
                        'payload': payload,
                    }
                )
            )
        except Exception:
            # اگر کلاینت قبل از رسیدن به این خط اتصال را قطع کرده باشد،
            # به جای نمایش خطای Autobahn، اتصال به صورت امن بسته می‌شود
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def auction_bid_update(self, event):
        try:
            payload = await database_sync_to_async(build_bid_live_payload)(
                self.product_pk,
                self.scope.get('user'),
                include_user_history=self.include_user_history,
            )
            await self.send(
                text_data=json.dumps(
                    {
                        'type': 'bid_update',
                        'payload': payload,
                    }
                )
            )
        except Exception:
            # مدیریت خطای مشابه در زمان آپدیت‌های گروهی (Broadcasting)
            pass
