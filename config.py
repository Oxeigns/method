"""Central fail-fast settings shared by bot, Flask, migrations and workers."""
import os
import fcntl
import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from dotenv import load_dotenv

def integer(name,default,lo,hi):
    try:value=int(os.getenv(name) or str(default))
    except ValueError:raise ValueError(f'{name} must be an integer.') from None
    if not lo<=value<=hi:raise ValueError(f'{name} must be between {lo} and {hi}.')
    return value

def boolean(name,default=False):
    raw=os.getenv(name,str(default)).lower()
    if raw not in {'true','false'}:raise ValueError(f'{name} must be true or false.')
    return raw=='true'

@dataclass(frozen=True)
class Config:
    token:str
    admin_id:int
    data_dir:Path
    keys:tuple[str,...]
    payment_mode:str
    support:str
    database_url:str=''
    production:bool=False
    api_id:int=0
    api_hash:str=''
    telethon_enabled:bool=False
    origin:str='http://localhost:8000'
    secret_key:str=''
    password_hash:str=''
    pool_max:int=5
    broadcast_rate:int=8
    trust_proxy:bool=False

    @classmethod
    def load(cls,component='bot'):
        load_dotenv();os.umask(0o077)
        production=os.getenv('APP_ENV','local')=='production'
        if os.getenv('APP_ENV','local') not in {'local','production'}:raise ValueError('Invalid APP_ENV.')
        token=os.getenv('BOT_TOKEN','');admin=integer('ADMIN_ID',0,1,2**63-1)
        if not token:raise ValueError('Missing BOT_TOKEN.')
        database=os.getenv('DATABASE_URL','')
        if database and urlparse(database).scheme not in {'postgres','postgresql'}:raise ValueError('DATABASE_URL must be PostgreSQL.')
        if (production or os.getenv('DYNO')) and not database:raise ValueError('Production/Heroku requires persistent PostgreSQL; local SQLite is refused.')
        mode=os.getenv('PAYMENT_MODE','stars')
        if mode not in {'stars','upi'}:raise ValueError('Invalid PAYMENT_MODE.')
        if mode=='upi' and not boolean('ACKNOWLEDGE_UPI_PLATFORM_RESTRICTION'):raise ValueError('Read the UPI platform restriction.')
        folder=Path(os.getenv('DATA_DIR','./data')).resolve();folder.mkdir(parents=True,exist_ok=True)
        raw_keys=os.getenv('MASTER_ENCRYPTION_KEYS','')
        seed=os.getenv('MASTER_KEY_SEED','')
        if not raw_keys and seed:
            if len(seed)<32:raise ValueError('MASTER_KEY_SEED must contain at least 32 random characters.')
            raw_keys=base64.urlsafe_b64encode(hashlib.sha256(b'method-vault-v1\0'+seed.encode()).digest()).decode()
        if not raw_keys:
            if database:raise ValueError('PostgreSQL requires MASTER_ENCRYPTION_KEYS, shared by web and worker.')
            keyfile=folder/'master.key'
            # Web and bot can start together; serialize first-key creation and reads.
            with open(folder/'key-init.lock','a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                if not keyfile.exists():
                    if (folder/'research.sqlite3').exists():raise ValueError('Restore missing original master.key; refusing to replace it.')
                    fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'w') as f:
                        f.write(Fernet.generate_key().decode());f.flush();os.fsync(f.fileno())
                raw_keys=keyfile.read_text().strip()
        keys=tuple(k.strip() for k in raw_keys.split(','))
        for k in keys:Fernet(k.encode())
        enabled=boolean('TELETHON_ENABLED',production)
        api_id=integer('API_ID',0,1 if enabled else 0,2**31-1)
        api_hash=os.getenv('API_HASH','')
        if enabled and (len(api_hash)!=32 or any(c not in '0123456789abcdefABCDEF' for c in api_hash)):
            raise ValueError('Telethon requires a 32-character API_HASH from my.telegram.org.')
        origin=os.getenv('PUBLIC_ORIGIN', '' if production else 'http://localhost:8000').rstrip('/')
        parts=urlparse(origin)
        if origin and (parts.scheme not in {'http','https'} or not parts.netloc or parts.path or parts.query or parts.fragment):
            raise ValueError('PUBLIC_ORIGIN must be an origin without a path.')
        if production and origin and parts.scheme!='https':raise ValueError('Production requires HTTPS PUBLIC_ORIGIN.')
        secret=os.getenv('SECRET_KEY','');password=os.getenv('DASHBOARD_PASSWORD_HASH','')
        if component=='web':
            if len(secret)<32:raise ValueError('Web requires SECRET_KEY of at least 32 characters.')
            if password and not password.startswith(('scrypt:','pbkdf2:')):raise ValueError('Set DASHBOARD_PASSWORD_HASH with scripts/generate_secrets.py.')
        return cls(token,admin,folder,keys,mode,os.getenv('SUPPORT_USERNAME',''),database,production,api_id,api_hash,enabled,
                   origin,secret,password,integer('DB_POOL_MAX',5,2,30),integer('BROADCAST_RATE',8,1,20),boolean('TRUST_PROXY'))
