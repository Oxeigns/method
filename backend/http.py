"""Bounded aiohttp Telegram transport; no automatic retry of ambiguous sends."""
import aiohttp
from .retry import retry
class RateLimited(Exception):
    def __init__(self,seconds):self.seconds=max(1,min(int(seconds),86400))
class RecipientUnavailable(Exception):pass
class TelegramTransport:
    def __init__(self,token,session):self.token,self.session=token,session
    async def call(self,method,payload):
        async with self.session.post(f'https://api.telegram.org/bot{self.token}/{method}',json=payload) as r:
            if r.content_length and r.content_length>2_000_000:raise RuntimeError('Oversized upstream response')
            body=await r.content.read(2_000_001)
            if len(body)>2_000_000:raise RuntimeError('Oversized upstream response')
            import json
            data=json.loads(body)
            if r.status==429 or data.get('error_code')==429:raise RateLimited(data.get('parameters',{}).get('retry_after',5))
            if r.status==403 or data.get('error_code')==403:raise RecipientUnavailable()
            if r.status>=500:raise aiohttp.ClientConnectionError('Upstream unavailable')
            if not data.get('ok'):raise RuntimeError('Telegram request failed')
            return data['result']
    async def send(self,uid,text):
        return await self.call('sendMessage',{'chat_id':uid,'text':text,'protect_content':True})
    async def metadata(self):
        return await retry(lambda:self.call('getMe',{}),(aiohttp.ClientError,TimeoutError))
