#!/bin/bash

set -e

echo "=== Starting MariaDB ==="

if service mariadb status >/dev/null 2>&1; then
    echo "MariaDB sudah berjalan."
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
service mariadb status || true

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
