"""Offline disaster recovery. Stop the bot first; requires the original master.key."""
import argparse
import fcntl
import os
import sqlite3
import tempfile
from pathlib import Path
from bot.crypto import VaultCipher

def restore(backup,keyfile,folder):
    os.umask(0o077)
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    # Restoring only into an empty directory avoids accidentally discarding newer payments.
    if (folder/'research.sqlite3').exists() or (folder/'master.key').exists():
        raise ValueError('Restore destination must be empty of database/key files. Keep the old data directory intact.')
    with open(folder/'process.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        keys=Path(keyfile).read_text().strip()
        cipher=VaultCipher(keys.split(','))
        payload=cipher.cipher.decrypt(Path(backup).read_bytes())
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            db=Path(temp)/'database.sqlite3';db.write_bytes(payload)
            with sqlite3.connect(db) as conn:
                # Restore as a single file: no pending WAL may be left behind on rename.
                conn.execute('PRAGMA journal_mode=DELETE')
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Damaged backup.')
                if conn.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('Unsupported schema version.')
                for (sid,token) in conn.execute('SELECT service_id,encrypted_payload FROM vault_data'):
                    cipher.decrypt(sid,token)
                # Do not replay old payment notices, broadcasts or content automatically.
                conn.execute('DELETE FROM fsm')
                conn.execute("UPDATE delivery_jobs SET status='blocked' WHERE status='pending'")
                conn.execute('UPDATE broadcasts SET done=1')
                tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'broadcast_targets' in tables:
                    conn.execute("UPDATE broadcast_targets SET status='failed',lease_token=NULL WHERE status IN ('queued','leased')")
                if 'web_sessions' in tables:
                    conn.execute('DELETE FROM web_sessions')
                conn.commit()
            (folder/'master.key').write_text(keys)
            os.replace(db,folder/'research.sqlite3')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backup',type=Path,required=True)
    p.add_argument('--key-file',type=Path,required=True)
    p.add_argument('--data-dir',type=Path,required=True)
    args=p.parse_args()
    restore(args.backup,args.key_file,args.data_dir)
    print('Restored. Reconcile transactions newer than the snapshot before restarting the bot.')
