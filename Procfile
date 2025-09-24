web: gunicorn run:app -b 0.0.0.0:$PORT --workers=3 --worker-class=gthread --threads=2 --preload --max-requests=1000 --max-requests-jitter=100 --keep-alive=5 --timeout=120 --log-level=info --access-logfile=- --error-logfile=-
cron: python3 path/to/your/task.py
