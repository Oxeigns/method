"""Only token and owner ID required; database and encryption key are local."""
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from cryptography.fernet import Fernet

@dataclass(frozen=True)
class Config:
    token:str
    admin_id:int
    data_dir:Path
    keys:tuple[str,...]
    payment_mode:str
    support:str

    @classmethod
    def load(cls):
        load_dotenv()
        os.umask(0o077)
        token=os.getenv('BOT_TOKEN','')
        admin=int(os.getenv('ADMIN_ID','0'))
        if not token or admin<=0:raise ValueError('Set BOT_TOKEN and your numeric ADMIN_ID in .env.')
        mode=os.getenv('PAYMENT_MODE','stars')
        if mode not in {'stars','upi'}:raise ValueError('Unknown PAYMENT_MODE')
        if mode=='upi' and os.getenv('ACKNOWLEDGE_UPI_PLATFORM_RESTRICTION')!='true':
            raise ValueError('Keep Stars for digital goods. See README for UPI restrictions.')
        folder=Path(os.getenv('DATA_DIR','./data')).resolve()
        folder.mkdir(parents=True,exist_ok=True)
        keyfile=folder/'master.key'
        if not keyfile.exists():
            if (folder/'research.sqlite3').exists():
                raise ValueError('Database exists but master.key is missing. Restore the original key; refusing to replace it.')
            try:
                fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f:f.write(Fernet.generate_key().decode())
            except FileExistsError:pass
        keys=tuple(keyfile.read_text().strip().split(','))
        for key in keys:Fernet(key.encode())
        return cls(token,admin,folder,keys,mode,os.getenv('SUPPORT_USERNAME',''))
