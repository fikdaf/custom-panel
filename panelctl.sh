#!/bin/bash

APP_DIR="/opt/custom-panel"
GUNICORN="$APP_DIR/venv/bin/gunicorn"
PIDFILE="$APP_DIR/gunicorn.pid"
ACCESS_LOG="$APP_DIR/gunicorn-access.log"
ERROR_LOG="$APP_DIR/gunicorn-error.log"
PORT="5000"

start() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")

        if kill -0 "$PID" 2>/dev/null; then
            echo "Gunicorn sudah berjalan. PID: $PID"
            return 0
        fi

        rm -f "$PIDFILE"
    fi

    if curl -s --max-time 2 http://127.0.0.1:$PORT/login >/dev/null 2>&1; then
        echo "Port $PORT sedang digunakan."
        echo "Batalkan start untuk mencegah Gunicorn ganda."
        return 1
    fi

    cd "$APP_DIR"

    nohup "$GUNICORN" \
        --bind 127.0.0.1:$PORT \
        --workers 2 \
        --pid "$PIDFILE" \
        --access-logfile "$ACCESS_LOG" \
        --error-logfile "$ERROR_LOG" \
        app:app >/dev/null 2>&1 &

    sleep 2

    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")

        if kill -0 "$PID" 2>/dev/null; then
            echo "Gunicorn berhasil dijalankan. PID: $PID"
            return 0
        fi
    fi

    echo "Gagal menjalankan Gunicorn."
    tail -20 "$ERROR_LOG" 2>/dev/null || true
    return 1
}

stop() {
    if [ ! -f "$PIDFILE" ]; then
        echo "Gunicorn tidak berjalan."
        return 0
    fi

    PID=$(cat "$PIDFILE")

    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Gunicorn dihentikan. PID: $PID"

        for i in 1 2 3 4 5; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
    else
        echo "PID tidak aktif."
    fi

    rm -f "$PIDFILE"
}

status() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")

        if kill -0 "$PID" 2>/dev/null; then
            echo "Gunicorn: RUNNING"
            echo "PID: $PID"
            return 0
        fi
    fi

    echo "Gunicorn: STOPPED"
    return 1
}

restart() {
    stop
    sleep 1
    start
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
