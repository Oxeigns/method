#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
# Run in a current Termux installation. Android background restrictions still apply.
pkg install -y python clang rust openssl libffi git
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-local.txt
if [ ! -f .env ]; then cp .env.example .env; fi
printf '%s\n' 'Set BOT_TOKEN and ADMIN_ID in .env, then run: . .venv/bin/activate && python main.py' 'Keep DATA_DIR on persistent internal storage; export backups. Use TELETHON_ENABLED=false for token-only local use.'
