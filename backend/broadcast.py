"""Durable per-recipient leases, bounded concurrency, global rate pacing and retries."""
import asyncio,logging,time,uuid
from .http import RateLimited,RecipientUnavailable

class Pacer:
    def __init__(self,rate):self.interval=1/rate;self.next=0.;self.blocked=0.;self.lock=asyncio.Lock()
    async def wait(self):
        async with self.lock:
            while True:
                delay=max(self.next,self.blocked)-time.monotonic()
                if delay<=0:break
                await asyncio.sleep(delay)
            self.next=time.monotonic()+self.interval
    def pause(self,seconds):self.blocked=max(self.blocked,time.monotonic()+seconds)

async def prepare(store):
    db=store.pool
    async with db.acquire() as c,c.transaction():
        suffix=' FOR UPDATE SKIP LOCKED' if getattr(db,'dialect','sqlite')=='postgres' else ''
        b=await c.fetchrow('SELECT * FROM broadcasts WHERE prepared=0 AND done=0 ORDER BY broadcast_id LIMIT 1'+suffix)
        if not b:return
        await c.execute('''INSERT INTO broadcast_targets(broadcast_id,user_id)
        SELECT $1,user_id FROM users WHERE is_banned=0 ON CONFLICT(broadcast_id,user_id) DO NOTHING''',b['broadcast_id'])
        await c.execute('UPDATE broadcasts SET prepared=1 WHERE broadcast_id=$1',b['broadcast_id'])

async def claim(store):
    db=store.pool
    async with db.acquire() as c,c.transaction():
        suffix=' FOR UPDATE SKIP LOCKED' if getattr(db,'dialect','sqlite')=='postgres' else ''
        t=await c.fetchrow("SELECT * FROM broadcast_targets WHERE (status='queued' AND available_at<=now()) OR (status='leased' AND lease_until<now()) ORDER BY target_id LIMIT 1"+suffix)
        if not t:return None
        token=uuid.uuid4().hex
        await c.execute("UPDATE broadcast_targets SET status='leased',lease_until=now()+120,lease_token=$2,attempts=attempts+1 WHERE target_id=$1",t['target_id'],token)
        t['lease_token']=token;t['attempts']+=1
        return t

async def process(store,cipher,sender,pacer,target):
    tid,token=target['target_id'],target['lease_token']
    try:
        # A recipient may have been banned after the audience snapshot was created.
        if await store.pool.fetchval('SELECT is_banned FROM users WHERE user_id=$1',target['user_id']):raise RecipientUnavailable()
        raw=await store.pool.fetchval('SELECT encrypted_text FROM broadcasts WHERE broadcast_id=$1',target['broadcast_id'])
        await asyncio.wait_for(sender.send(target['user_id'],cipher.decrypt(0,raw)),timeout=30)
    except RateLimited as exc:
        pacer.pause(exc.seconds)
        await store.pool.execute("UPDATE broadcast_targets SET status='queued',available_at=now()+$3,last_error='rate_limit' WHERE target_id=$1 AND lease_token=$2",tid,token,float(exc.seconds))
    except RecipientUnavailable:
        await store.pool.execute("UPDATE broadcast_targets SET status='failed',last_error='recipient_unavailable' WHERE target_id=$1 AND lease_token=$2",tid,token)
    except Exception as exc:
        delay=float(min(3600,2**min(target['attempts'],11)))
        status='failed' if target['attempts']>=8 else 'queued'
        await store.pool.execute('UPDATE broadcast_targets SET status=$3,available_at=now()+$4,last_error=$5 WHERE target_id=$1 AND lease_token=$2',tid,token,status,delay,type(exc).__name__)
        logging.warning('broadcast_retry target=%s type=%s',tid,type(exc).__name__)
    else:
        await store.pool.execute("UPDATE broadcast_targets SET status='sent',last_error=NULL WHERE target_id=$1 AND lease_token=$2",tid,token)

async def loop(store,cipher,sender,rate):
    pacer=Pacer(rate)
    async def consumer():
        while True:
            try:
                await pacer.wait()
                target=await claim(store)
                if target:await process(store,cipher,sender,pacer,target)
                else:await asyncio.sleep(1)
            except Exception as exc:
                logging.error('broadcast_worker_failure type=%s',type(exc).__name__);await asyncio.sleep(3)
    async def coordinator():
        while True:
            try:
                await prepare(store)
                await store.pool.execute("UPDATE broadcasts SET done=1 WHERE prepared=1 AND done=0 AND NOT EXISTS(SELECT 1 FROM broadcast_targets t WHERE t.broadcast_id=broadcasts.broadcast_id AND t.status IN ('queued','leased'))")
            except Exception as exc:logging.error('broadcast_prepare_failure type=%s',type(exc).__name__)
            await asyncio.sleep(2)
    tasks=[asyncio.create_task(consumer()) for _ in range(4)]+[asyncio.create_task(coordinator())]
    try:await asyncio.gather(*tasks)
    finally:
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
