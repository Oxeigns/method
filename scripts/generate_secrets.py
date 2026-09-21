"""Run on your own terminal, never paste existing service secrets into chat."""
import argparse,getpass,secrets
from werkzeug.security import generate_password_hash
from cryptography.fernet import Fernet
p=argparse.ArgumentParser()
p.add_argument('--password-hash',action='store_true')
a=p.parse_args()
if a.password_hash:
    value=getpass.getpass('Choose dashboard password (at least 16 characters): ')
    if len(value)<16:raise SystemExit('Password too short.')
    if value!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords do not match.')
    print(generate_password_hash(value,method='scrypt'))
else:
    print('SECRET_KEY='+secrets.token_urlsafe(48))
    print('MASTER_ENCRYPTION_KEYS='+Fernet.generate_key().decode())
