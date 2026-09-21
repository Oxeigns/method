"""Small in-memory abuse limiter; business state lives in SQLite."""
import time
class RateLimiter:
    def __init__(self):self.values={}
    async def incr(self,key):
        now=time.monotonic()
        count,deadline=self.values.get(key,(0,now+3))
        if deadline<=now:count,deadline=0,now+3
        self.values[key]=(count+1,deadline)
        if len(self.values)>10000:
            self.values={k:v for k,v in self.values.items() if v[1]>now}
        return count+1
    async def expire(self,key,seconds):pass
