#!/bin/bash

set -e

cd /opt/custom-panel
source /opt/custom-panel/venv/bin/activate

exec gunicorn \
  --bind 127.0.0.1:5000 \
  --workers 2 \
  --access-logfile /opt/custom-panel/gunicorn-access.log \
  --error-logfile /opt/custom-panel/gunicorn-error.log \
  app:app
