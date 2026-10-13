#!/bin/bash
set -e

# Wait until the db container is ready to accept connections
until pg_isready -h db -p 5432 -U postgres > /dev/null 2>&1; do
    echo "Waiting for Postgres to start..."
    sleep 1
done

# Run Django migrations
python manage.py migrate --noinput

# Start Django
exec python manage.py runserver 0.0.0.0:8090