"""JSON logs explicitly exclude update bodies, credentials, URLs and research."""
import json,logging,time
class JSONFormatter(logging.Formatter):
    def format(self,record):
        return json.dumps({'time':time.time(),'level':record.levelname,'logger':record.name,
                           'event':record.getMessage()},ensure_ascii=False)
def configure():
    handler=logging.StreamHandler();handler.setFormatter(JSONFormatter())
    root=logging.getLogger();root.handlers=[handler];root.setLevel(logging.INFO)
    for name in ['aiogram','telethon','httpx','werkzeug']:logging.getLogger(name).setLevel(logging.WARNING)
