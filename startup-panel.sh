#!/bin/bash

set -e

echo "=== Starting MariaDB ==="

if /opt/custom-panel/venv/bin/python - <<'PYTHON' >/dev/null 2>&1
import pymysql
from pathlib import Path

password_file = Path("/opt/custom-panel/.mariadb_panel_password")
if not password_file.exists():
    raise SystemExit(1)

password = password_file.read_text().strip()
if not password:
    raise SystemExit(1)

conn = pymysql.connect(
    unix_socket="/run/mysqld/mysqld.sock",
    user="jayantara_panel",
    password=password,
    charset="utf8mb4",
    autocommit=True,
    connect_timeout=3,
)

with conn.cursor() as cur:
    cur.execute("SELECT 1")

conn.close()
PYTHON
then
    echo "MariaDB sudah berjalan dan dapat diakses panel."
else
    service mariadb start
    echo "MariaDB berhasil dijalankan."
fi

echo
echo "=== Starting PHP-FPM ==="

if service php8.5-fpm status >/dev/null 2>&1; then
    echo "PHP-FPM sudah berjalan."
else
    service php8.5-fpm start
    echo "PHP-FPM berhasil dijalankan."
fi

echo
echo "=== Starting Nginx ==="

if pgrep -x nginx >/dev/null 2>&1; then
    echo "Nginx sudah berjalan."
else
    nginx
    echo "Nginx berhasil dijalankan."
fi

echo
echo "=== Starting Gunicorn ==="
/opt/custom-panel/panelctl.sh start

echo
echo "=== Service Status ==="

echo "MariaDB:"
if /opt/custom-panel/venv/bin/python - <<'PYTHON' >/dev/null 2>&1
import pymysql
from pathlib import Path

password_file = Path("/opt/custom-panel/.mariadb_panel_password")
if not password_file.exists():
    raise SystemExit(1)

password = password_file.read_text().strip()
if not password:
    raise SystemExit(1)

conn = pymysql.connect(
    unix_socket="/run/mysqld/mysqld.sock",
    user="jayantara_panel",
    password=password,
    charset="utf8mb4",
    autocommit=True,
    connect_timeout=3,
)

with conn.cursor() as cur:
    cur.execute("SELECT 1")

conn.close()
PYTHON
then
    echo "RUNNING — dapat diakses panel"
else
    echo "UNAVAILABLE — tidak dapat diakses panel"
fi

echo
echo "PHP-FPM:"
service php8.5-fpm status || true

echo
echo "Nginx:"
if pgrep -x nginx >/dev/null 2>&1; then
    echo "RUNNING"
else
    echo "STOPPED"
fi

echo
echo "Gunicorn:"
/opt/custom-panel/panelctl.sh status || true

echo
echo "=== Health Check ==="

PANEL_HTTP=$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:5000/login || true)
NGINX_HTTP=$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:9000/login || true)

echo "Panel: HTTP $PANEL_HTTP"
echo "Nginx Panel: HTTP $NGINX_HTTP"

if [ "$PANEL_HTTP" != "200" ]; then
    echo "ERROR: Panel health check gagal."
    exit 1
fi

if [ "$NGINX_HTTP" != "200" ]; then
    echo "ERROR: Nginx Panel health check gagal."
    exit 1
fi

echo
echo "=== All services started successfully ==="
