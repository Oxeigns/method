"""Native MTProto owner commands and announcement transport; Bot API fallback for uncached peers."""
from telethon import TelegramClient,events,functions,errors
from telethon.sessions import StringSession
from .security import owner_command
from .http import RateLimited,RecipientUnavailable
from .retry import retry
class TelethonSender:
    def __init__(self,client,fallback):self.client,self.fallback=client,fallback
    async def send(self,uid,text):
        try:
            try:peer=await self.client.get_input_entity(uid)
            except ValueError:return await self.fallback.send(uid,text)
            return await self.client(functions.messages.SendMessageRequest(peer=peer,message=text,noforwards=True))
        except errors.FloodWaitError as exc:raise RateLimited(exc.seconds) from None
        except (errors.UserIsBlockedError,errors.ChatWriteForbiddenError):raise RecipientUnavailable() from None

async def start(cfg,store,cipher,transport):
    saved=await store.setting('telethon_session')
    session=StringSession(cipher.decrypt(0,saved) if saved else '')
    client=TelegramClient(session,cfg.api_id,cfg.api_hash,auto_reconnect=True,connection_retries=5,
                          retry_delay=1,request_retries=0,flood_sleep_threshold=0)
    await retry(lambda:client.start(bot_token=cfg.token),(ConnectionError,OSError,TimeoutError))
    await store.set_setting('telethon_session',cipher.encrypt(0,client.session.save()))
    @client.on(events.NewMessage(pattern=r'^/systemstatus(?:@\w+)?$'))
    @owner_command(cfg)
    async def status(event):
        await store.pool.fetchval('SELECT 1')
        await client(functions.messages.SendMessageRequest(peer=event.chat_id,message='Database connected. Use dashboard analytics for queue status.',noforwards=True))
    return client,TelethonSender(client,transport)
