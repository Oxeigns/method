release: python -m backend.migrate
web: gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 40 --max-requests 2000 --max-requests-jitter 200
worker: python main.py
