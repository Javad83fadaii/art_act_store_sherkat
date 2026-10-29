#!/bin/sh
set -eu

cd /app

echo "Starting Daphne..."
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
