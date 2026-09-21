import asyncio,random
async def retry(operation,errors,attempts=5,base=.5,cap=20):
    """Only wrap idempotent operations. Cancellation always propagates."""
    for n in range(attempts):
        try:return await operation()
        except errors:
            if n==attempts-1:raise
            await asyncio.sleep(min(cap,base*2**n)*random.uniform(.7,1.3))
