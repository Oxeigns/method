"""Authenticated encryption; bind every ciphertext to its service to reject row swaps."""
import argparse
import json
from cryptography.fernet import Fernet, MultiFernet, InvalidToken

class VaultCipher:
    def __init__(self, keys):
        self.cipher = MultiFernet([Fernet(k.strip().encode()) for k in keys])

    def encrypt(self, service_id: int, text: str) -> str:
        if not text or len(text.encode('utf-8')) > 100_000:
            raise ValueError('Research must contain 1 to 100000 UTF-8 bytes.')
        body = json.dumps({'v': 1, 'service_id': service_id, 'text': text}, ensure_ascii=False)
        return self.cipher.encrypt(body.encode()).decode()

    def decrypt(self, service_id: int, token: str) -> str:
        obj = json.loads(self.cipher.decrypt(token.encode()))
        if obj.get('v') != 1 or obj.get('service_id') != service_id or not isinstance(obj.get('text'), str):
            raise InvalidToken('Ciphertext context mismatch')
        return obj['text']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate-key', action='store_true', required=True)
    parser.parse_args()
    print(Fernet.generate_key().decode())
