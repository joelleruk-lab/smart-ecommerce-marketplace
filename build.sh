#!/usr/bin/env bash
# Build script used by Render / Railway / Fly.io.
set -o errexit
set -o pipefail

python -m pip install --upgrade pip
pip install -r requirements.txt

python manage.py migrate --noinput

if [ "${SEED_DEMO:-true}" = "true" ]; then
  python manage.py seed_demo || echo "Seed skipped or already present."
fi

# Collect after seeding so generated product art is included when a fresh
# database is provisioned.
python manage.py collectstatic --noinput
