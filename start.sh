#!/bin/sh
set -e

echo "==> [1/5] Starting embedded Redis server..."
redis-server --daemonize yes --protected-mode no --port 6379

echo "==> [2/5] Initializing database schema..."
cd /app
python -m flask init-db || true

echo "==> [3/5] Starting Celery background worker..."
celery -A app.workers.celery_app worker -l info --pool=threads --concurrency=2 &

echo "==> [4/5] Starting Gunicorn Flask API on 127.0.0.1:5000..."
gunicorn run:app --bind 127.0.0.1:5000 --workers 2 --worker-class gthread --threads 4 --timeout 600 &

echo "==> [5/5] Configuring Nginx on PORT ${PORT:-10000} and starting web server..."
export PORT="${PORT:-10000}"
export API_URL="http://127.0.0.1:5000"

mkdir -p /etc/nginx/conf.d
envsubst '${PORT} ${API_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Keep container running with Nginx in the foreground
exec nginx -g 'daemon off;'
