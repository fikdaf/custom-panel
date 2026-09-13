from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import secrets
import psutil
import shutil
import re
import subprocess
import time
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import pymysql

app = Flask(__name__)

SECRET_KEY_FILE = Path("/opt/custom-panel/.panel_secret_key")

if SECRET_KEY_FILE.exists():
    app.secret_key = SECRET_KEY_FILE.read_text().strip()
elif os.environ.get("PANEL_SECRET_KEY"):
    app.secret_key = os.environ["PANEL_SECRET_KEY"]
else:
    raise RuntimeError(
        "PANEL_SECRET_KEY tidak tersedia dan file secret key tidak ditemukan."
    )

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
login_attempts = {}

def get_csrf_token():
    token = session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token

    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


@app.before_request
def csrf_protect():
    if request.method != "POST":
        return

    token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")

    if (
        not token
        or not session_token
        or not secrets.compare_digest(token, session_token)
    ):
        return "CSRF token tidak valid.", 400


DATABASE = "panel.db"
def process_running(name):
    try:
        result = subprocess.run(
            ["pgrep", "-x", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        return result.returncode == 0

    except Exception:
        return False

WEB_ROOT = Path("/var/www/html")

PORT_START = 8080
PORT_END = 8999


MARIADB_SOCKET = "/run/mysqld/mysqld.sock"
MARIADB_USER = "jayantara_panel"
MARIADB_PASSWORD_FILE = Path("/opt/custom-panel/.mariadb_panel_password")

DATABASE_PREFIX = "jayantara_"

SYSTEM_DATABASES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
}


def get_mariadb_connection(database=None):
    if not MARIADB_PASSWORD_FILE.exists():
        raise RuntimeError(
            "Password MariaDB panel tidak ditemukan."
        )

    password = MARIADB_PASSWORD_FILE.read_text().strip()

    if not password:
        raise RuntimeError(
            "Password MariaDB panel kosong."
        )

    kwargs = {
        "unix_socket": MARIADB_SOCKET,
        "user": MARIADB_USER,
        "password": password,
        "charset": "utf8mb4",
        "autocommit": True,
    }

    if database:
        kwargs["database"] = database

    return pymysql.connect(**kwargs)


def valid_database_name(name):
    return re.fullmatch(
        r"jayantara_[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}",
        name
    ) is not None


def quote_mysql_identifier(identifier):
    return "`" + identifier.replace("`", "``") + "`"


def valid_table_name(name):
    return re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}",
        name
    ) is not None


def validate_table_value(column_type, value):
    """Validate a VALUE-mode database value against supported column types."""
    if not isinstance(value, str):
        raise ValueError("Nilai harus berupa teks form.")

    normalized_type = column_type.lower().strip()

    if normalized_type == "varchar(255)":
        if len(value) > 255:
            raise ValueError("VARCHAR(255) maksimal 255 karakter.")
        return

    if normalized_type == "text":
        return

    if normalized_type.startswith("int"):
        unsigned = "unsigned" in normalized_type
        try:
            number = int(value)
        except ValueError:
            raise ValueError("INT harus berupa bilangan bulat.")

        minimum = 0 if unsigned else -2147483648
        maximum = 4294967295 if unsigned else 2147483647

        if not minimum <= number <= maximum:
            raise ValueError("Nilai INT berada di luar range.")
        return

    if normalized_type.startswith("bigint"):
        unsigned = "unsigned" in normalized_type
        try:
            number = int(value)
        except ValueError:
            raise ValueError("BIGINT harus berupa bilangan bulat.")

        minimum = 0 if unsigned else -9223372036854775808
        maximum = (
            18446744073709551615
            if unsigned
            else 9223372036854775807
        )

        if not minimum <= number <= maximum:
            raise ValueError("Nilai BIGINT berada di luar range.")
        return

    if normalized_type == "decimal(10,2)":
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("DECIMAL(10,2) harus berupa angka valid.")

        if not number.is_finite():
            raise ValueError("DECIMAL(10,2) harus berupa angka hingga.")

        sign, digits, exponent = number.as_tuple()
        fractional_digits = -exponent if exponent < 0 else 0

        if fractional_digits > 2:
            raise ValueError("DECIMAL(10,2) maksimal 2 angka desimal.")

        integer_digits = max(len(digits) - fractional_digits, 0)

        if integer_digits > 8:
            raise ValueError(
                "DECIMAL(10,2) maksimal 8 digit sebelum desimal."
            )
        return

    if normalized_type == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("DATE harus berformat YYYY-MM-DD.")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Tanggal DATE tidak valid.")
        return

    if normalized_type == "datetime":
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
            value,
        ):
            raise ValueError(
                "DATETIME harus berformat YYYY-MM-DD HH:MM:SS."
            )
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("Nilai DATETIME tidak valid.")
        return

    if normalized_type in {"boolean", "tinyint(1)"}:
        if value not in {"0", "1"}:
            raise ValueError("BOOLEAN hanya menerima 0 atau 1.")
        return

    raise ValueError(f"Tipe data '{column_type}' tidak didukung.")


def get_managed_databases():
    conn = get_mariadb_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            rows = cursor.fetchall()

        databases = []

        for row in rows:
            name = row[0]

            if (
                name.startswith(DATABASE_PREFIX)
                and name not in SYSTEM_DATABASES
            ):
                databases.append(name)

        return sorted(databases, key=str.lower)

    finally:
        conn.close()


def get_used_ports():
    conn = get_db()

    rows = conn.execute(
        "SELECT port FROM websites WHERE port IS NOT NULL"
    ).fetchall()

    conn.close()

    return {
        row["port"]
        for row in rows
        if row["port"] is not None
    }


def get_next_available_port():
    used_ports = get_used_ports()

    for port in range(PORT_START, PORT_END + 1):
        if port not in used_ports:
            return port

    raise RuntimeError(
        "Tidak ada port tersedia."
    )


def valid_website_name(name):
    return re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}",
        name
    ) is not None


def safe_path(base, relative_path=""):
    base = Path(base).resolve()

    target = (base / relative_path).resolve()

    if target != base and base not in target.parents:
        raise ValueError("Path tidak diizinkan.")

    return target



def get_server_status():

    memory = psutil.virtual_memory()

    disk = shutil.disk_usage("/")

    return {
        "nginx": process_running("nginx"),
        "php": process_running("php-fpm8.5"),
        "mariadb": process_running("mariadbd"),

        "cpu": psutil.cpu_percent(interval=0.5),

        "ram": memory.percent,

        "disk": round(
            disk.used / disk.total * 100,
            1
        )
    }


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS websites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            path TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            port INTEGER
        )
    """)

    user = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if user is None:
        initial_password = os.environ.get("PANEL_INITIAL_ADMIN_PASSWORD")

        if not initial_password:
            conn.close()
            raise RuntimeError(
                "PANEL_INITIAL_ADMIN_PASSWORD wajib diset "
                "saat user admin belum ada."
            )

        if len(initial_password) < 12:
            conn.close()
            raise RuntimeError(
                "PANEL_INITIAL_ADMIN_PASSWORD minimal 12 karakter."
            )

        password_hash = generate_password_hash(initial_password)

        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("admin", password_hash)
        )
    website = conn.execute(
        "SELECT * FROM websites WHERE name = ?",
        ("jayantara",)
    ).fetchone()

    if website is None:
        conn.execute(
            """
            INSERT INTO websites
            (name, path, status)
            VALUES (?, ?, ?)
            """,
            (
                "jayantara",
                "/var/www/html/jayantara",
                "active"
            )
        )

    conn.commit()
    conn.close()


@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    return redirect("/dashboard")


@app.route("/login", methods=["GET", "POST"])
def login():

    error = None

    if request.method == "POST":

        client_ip = request.remote_addr or "unknown"
        now = time.time()

        attempts = login_attempts.get(client_ip, [])

        attempts = [
            timestamp
            for timestamp in attempts
            if now - timestamp < LOGIN_WINDOW_SECONDS
        ]

        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            error = "Terlalu banyak percobaan login. Coba lagi dalam 5 menit."
            login_attempts[client_ip] = attempts

            return render_template(
                "login.html",
                error=error
            ), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):
            login_attempts.pop(client_ip, None)

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect("/dashboard")

        attempts.append(now)
        login_attempts[client_ip] = attempts

        error = "Username atau password salah."

    return render_template(
        "login.html",
        error=error
    )


@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    status = get_server_status()

    return render_template(
        "dashboard.html",
        username=session["username"],
        status=status
    )


@app.route("/change-password", methods=["GET", "POST"])
def change_password():

    if "user_id" not in session:
        return redirect("/login")

    error = None
    success = None

    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        conn = get_db()

        try:
            user = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()

            if user is None:
                session.clear()
                return redirect("/login")

            if not check_password_hash(
                user["password"],
                current_password
            ):
                error = "Password saat ini salah."

            elif len(new_password) < 12:
                error = "Password baru minimal 12 karakter."

            elif new_password != confirm_password:
                error = "Konfirmasi password tidak cocok."

            elif check_password_hash(
                user["password"],
                new_password
            ):
                error = "Password baru harus berbeda dari password lama."

            else:
                password_hash = generate_password_hash(
                    new_password
                )

                conn.execute(
                    """
                    UPDATE users
                    SET password = ?
                    WHERE id = ?
                    """,
                    (
                        password_hash,
                        session["user_id"]
                    )
                )

                conn.commit()

                success = "Password berhasil diubah."

        finally:
            conn.close()

    return render_template(
        "change_password.html",
        error=error,
        success=success
    )


@app.route("/websites/<int:website_id>/files")
def website_files(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    current_path = request.args.get("path", "").strip("/")

    try:
        website_root = safe_path(website["path"])
        current_dir = safe_path(
            website_root,
            current_path
        )

    except ValueError:
        return "Path tidak diizinkan", 403

    if not current_dir.exists():
        return "Folder tidak ditemukan", 404

    if not current_dir.is_dir():
        return "Bukan folder", 400

    items = []

    for item in sorted(
        current_dir.iterdir(),
        key=lambda x: (not x.is_dir(), x.name.lower())
    ):

        items.append({
            "name": item.name,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size
            if item.is_file()
            else None
        })

    return render_template(
        "files.html",
        website=website,
        current_path=current_path,
        items=items
    )

@app.route(
    "/websites/<int:website_id>/files/mkdir",
    methods=["POST"]
)
def create_folder(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    current_path = request.form.get(
        "path",
        ""
    ).strip("/")

    folder_name = request.form.get(
        "name",
        ""
    ).strip()

    if not folder_name:
        return "Nama folder wajib diisi", 400

    try:

        current_dir = safe_path(
            website["path"],
            current_path
        )

        new_folder = safe_path(
            current_dir,
            folder_name
        )

        new_folder.mkdir(
            parents=False,
            exist_ok=False
        )

    except FileExistsError:
        return "Folder sudah ada", 409

    except ValueError:
        return "Path tidak diizinkan", 403

    return redirect(
        f"/websites/{website_id}/files"
        f"?path={current_path}"
    )


@app.route(
    "/websites/<int:website_id>/files/create",
    methods=["POST"]
)
def create_file(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    current_path = request.form.get(
        "path",
        ""
    ).strip("/")

    file_name = request.form.get(
        "name",
        ""
    ).strip()

    if not file_name:
        return "Nama file wajib diisi", 400

    try:

        current_dir = safe_path(
            website["path"],
            current_path
        )

        new_file = safe_path(
            current_dir,
            file_name
        )

        new_file.touch(
            exist_ok=False
        )

    except FileExistsError:
        return "File sudah ada", 409

    except ValueError:
        return "Path tidak diizinkan", 403

    return redirect(
        f"/websites/{website_id}/files"
        f"?path={current_path}"
    )

@app.route(
    "/websites/<int:website_id>/files/rename",
    methods=["POST"]
)
def rename_file(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    current_path = request.form.get(
        "path",
        ""
    ).strip("/")

    old_name = request.form.get(
        "old_name",
        ""
    ).strip()

    new_name = request.form.get(
        "new_name",
        ""
    ).strip()

    if not old_name or not new_name:
        return "Nama file wajib diisi", 400

    if "/" in new_name or "\\" in new_name:
        return "Nama tidak boleh mengandung path", 400

    try:

        current_dir = safe_path(
            website["path"],
            current_path
        )

        old_path = safe_path(
            current_dir,
            old_name
        )

        new_path = safe_path(
            current_dir,
            new_name
        )

        if not old_path.exists():
            return "File/folder tidak ditemukan", 404

        if new_path.exists():
            return "Nama tujuan sudah digunakan", 409

        old_path.rename(new_path)

    except ValueError:
        return "Path tidak diizinkan", 403

    return redirect(
        f"/websites/{website_id}/files?path={current_path}"
    )

@app.route(
    "/websites/<int:website_id>/files/delete",
    methods=["POST"]
)
def delete_file(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    current_path = request.form.get(
        "path",
        ""
    ).strip("/")

    name = request.form.get(
        "name",
        ""
    ).strip()

    if not name:
        return "Nama tidak ditemukan", 400

    try:

        current_dir = safe_path(
            website["path"],
            current_path
        )

        target = safe_path(
            current_dir,
            name
        )

        if not target.exists():
            return "File/folder tidak ditemukan", 404

        # Jangan izinkan document root dihapus
        if target.resolve() == Path(
            website["path"]
        ).resolve():
            return "Document root tidak boleh dihapus", 403

        if target.is_dir():

            # Hanya hapus folder kosong
            target.rmdir()

        else:

            target.unlink()

    except OSError:
        return (
            "Folder tidak kosong atau tidak dapat dihapus",
            400
        )

    except ValueError:
        return "Path tidak diizinkan", 403

    return redirect(
        f"/websites/{website_id}/files?path={current_path}"
    )

@app.route(
    "/websites/<int:website_id>/files/edit",
    methods=["GET", "POST"]
)
def edit_file(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    relative_path = request.args.get(
        "path",
        ""
    ).strip("/")

    if not relative_path:
        return "File tidak ditentukan", 400

    try:

        file_path = safe_path(
            website["path"],
            relative_path
        )

    except ValueError:

        return "Path tidak diizinkan", 403

    if not file_path.exists():
        return "File tidak ditemukan", 404

    if not file_path.is_file():
        return "Bukan file", 400

    if request.method == "POST":

        content = request.form.get(
            "content",
            ""
        )

        try:

            file_path.write_text(
                content,
                encoding="utf-8"
            )

        except Exception as e:

            return render_template(
                "edit_file.html",
                website=website,
                path=relative_path,
                content=content,
                error=str(e)
            )

        return redirect(
            "/websites/"
            + str(website_id)
            + "/files?path="
            + relative_path.rsplit("/", 1)[0]
            if "/" in relative_path
            else
            "/websites/"
            + str(website_id)
            + "/files"
        )

    try:

        content = file_path.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError:

        return "File bukan text/UTF-8", 400

    return render_template(
        "edit_file.html",
        website=website,
        path=relative_path,
        content=content,
        error=None
    )

@app.route("/websites")
def websites():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    websites = conn.execute(
        "SELECT * FROM websites ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template(
        "websites.html",
        websites=websites
    )

@app.route("/websites/add", methods=["GET", "POST"])
def add_website():

    if "user_id" not in session:
        return redirect("/login")

    error = None

    if request.method == "POST":

        name = request.form.get("name", "").strip()

        if not valid_website_name(name):
            error = "Nama website tidak valid."

            return render_template(
                "add_website.html",
                error=error
            )

        website_path = WEB_ROOT / name

        if website_path.exists():
            error = "Website tersebut sudah ada."

            return render_template(
                "add_website.html",
                error=error
            )

        config_path = Path(
            f"/etc/nginx/sites-enabled/{name}"
        )

        if config_path.exists():
            error = "Konfigurasi Nginx website tersebut sudah ada."

            return render_template(
                "add_website.html",
                error=error
            )

        website_created = False
        nginx_created = False
        db_saved = False
        port = None

        try:

            # Ambil port kosong
            port = get_next_available_port()

            # Buat directory website
            website_path.mkdir(
                parents=True,
                exist_ok=False
            )

            website_created = True

            # Buat halaman awal
            index_file = website_path / "index.html"

            index_file.write_text(
                f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{name}</title>
</head>
<body>

<h1>{name}</h1>

<p>
Website berhasil dibuat oleh Jayantara Panel.
</p>

<p>
Port: {port}
</p>

</body>
</html>
""",
                encoding="utf-8"
            )

            # Konfigurasi Nginx
            nginx_config = f"""server {{
    listen {port};
    listen [::]:{port};

    server_name {name};

    root {website_path};
    index index.html;

    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""

            config_path.write_text(
                nginx_config,
                encoding="utf-8"
            )

            nginx_created = True

            # Test konfigurasi Nginx
            test = subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True
            )

            if test.returncode != 0:
                raise RuntimeError(
                    "Konfigurasi Nginx gagal:\n"
                    + test.stderr
                )

            # Reload Nginx
            reload_result = subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True
            )

            if reload_result.returncode != 0:
                raise RuntimeError(
                    "Nginx gagal reload:\n"
                    + reload_result.stderr
                )

            # Simpan ke database
            conn = get_db()

            try:
                conn.execute(
                    """
                    INSERT INTO websites
                    (name, path, status, port)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        name,
                        str(website_path),
                        "active",
                        port
                    )
                )

                conn.commit()
                db_saved = True

            finally:
                conn.close()

            return redirect("/websites")

        except Exception as e:

            # Rollback database tidak diperlukan jika
            # commit belum berhasil.

            if nginx_created:
                config_path.unlink(
                    missing_ok=True
                )

                # Jika Nginx sebelumnya sudah berhasil reload,
                # reload kembali agar konfigurasi website baru
                # tidak terus aktif.
                subprocess.run(
                    ["nginx", "-s", "reload"],
                    capture_output=True,
                    text=True
                )

            if website_created and website_path.exists():

                for item in website_path.iterdir():

                    if item.is_file() or item.is_symlink():
                        item.unlink(
                            missing_ok=True
                        )

                    elif item.is_dir():
                        import shutil
                        shutil.rmtree(item)

                website_path.rmdir()

            error = str(e)

    return render_template(
        "add_website.html",
        error=error
    )


@app.route("/websites/<int:website_id>")
def website_detail(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    return render_template(
        "website_detail.html",
        website=website
    )

@app.route("/databases")
def databases():
    if "user_id" not in session:
        return redirect("/login")

    error = None
    database_list = []

    try:
        database_list = get_managed_databases()
    except Exception as exc:
        error = f"Gagal membaca database: {exc}"

    return render_template(
        "databases.html",
        databases=database_list,
        error=error
    )


@app.route("/databases/create", methods=["POST"])
def create_database():
    if "user_id" not in session:
        return redirect("/login")

    name = request.form.get("name", "").strip()

    if not valid_database_name(name):
        return render_template(
            "databases.html",
            databases=get_managed_databases(),
            error=(
                "Nama database tidak valid. Gunakan format "
                "jayantara_nama dengan huruf, angka, underscore "
                "atau tanda minus."
            )
        ), 400

    if name in SYSTEM_DATABASES:
        return "Database sistem tidak boleh dibuat melalui panel.", 400

    conn = None

    try:
        conn = get_mariadb_connection()

        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE {quote_mysql_identifier(name)} "
                "CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )

    except pymysql.err.OperationalError as exc:
        return render_template(
            "databases.html",
            databases=get_managed_databases(),
            error=f"Gagal membuat database: {exc}"
        ), 400

    except Exception as exc:
        return render_template(
            "databases.html",
            databases=get_managed_databases(),
            error=f"Gagal membuat database: {exc}"
        ), 500

    finally:
        if conn:
            conn.close()

    return redirect("/databases")


@app.route("/databases/<database_name>")
def database_detail(database_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    try:
        conn = get_mariadb_connection()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT SCHEMA_NAME
                FROM information_schema.SCHEMATA
                WHERE SCHEMA_NAME = %s
                """,
                (database_name,)
            )

            exists = cursor.fetchone()

            if not exists:
                return "Database tidak ditemukan.", 404

            cursor.execute(
                """
                SELECT
                    TABLE_NAME,
                    TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
                """,
                (database_name,)
            )

            tables = cursor.fetchall()

        return render_template(
            "database_detail.html",
            database=database_name,
            tables=tables
        )

    except Exception as exc:
        return f"Gagal membaca database: {exc}", 500

    finally:
        if "conn" in locals() and conn:
            conn.close()

@app.route(
    "/databases/<database_name>/tables/create",
    methods=["POST"]
)
def create_table(database_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    table_name = request.form.get("table_name", "").strip()

    if not valid_table_name(table_name):
        return (
            "Nama table tidak valid. Gunakan huruf, angka, "
            "underscore atau tanda minus.",
            400
        )

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE {quote_mysql_identifier(table_name)} (
                    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB
                """
            )

    except pymysql.err.OperationalError as exc:
        return f"Gagal membuat table: {exc}", 400

    except Exception as exc:
        return f"Gagal membuat table: {exc}", 500

    finally:
        if conn:
            conn.close()

    return redirect(f"/databases/{database_name}")

@app.route(
    "/databases/<database_name>/tables/<table_name>/delete",
    methods=["POST"]
)
def delete_table(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                """,
                (database_name, table_name)
            )

            if cursor.fetchone() is None:
                return "Table tidak ditemukan.", 404

            cursor.execute(
                f"DROP TABLE {quote_mysql_identifier(table_name)}"
            )

    except pymysql.err.IntegrityError as exc:
        return f"Gagal menghapus table: {exc}", 400

    except pymysql.err.OperationalError as exc:
        return f"Gagal menghapus table: {exc}", 400

    except Exception as exc:
        return f"Gagal menghapus table: {exc}", 500

    finally:
        if conn:
            conn.close()

    return redirect(f"/databases/{database_name}")

@app.route(
    "/databases/<database_name>/tables/<table_name>/structure"
)
def table_structure(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COLUMN_NAME,
                    COLUMN_TYPE,
                    IS_NULLABLE,
                    COLUMN_KEY,
                    COLUMN_DEFAULT,
                    EXTRA
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (database_name, table_name)
            )

            columns = cursor.fetchall()

            if not columns:
                return "Table tidak ditemukan atau tidak memiliki kolom.", 404

        return render_template(
            "table_structure.html",
            database=database_name,
            table=table_name,
            columns=columns
        )

    except Exception as exc:
        return f"Gagal membaca struktur table: {exc}", 500

    finally:
        if conn:
            conn.close()

@app.route(
    "/databases/<database_name>/tables/<table_name>/columns/add",
    methods=["POST"]
)
def add_table_column(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    column_name = request.form.get("column_name", "").strip()
    column_type = request.form.get("column_type", "").strip().upper()

    if not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_]{0,63}",
        column_name
    ):
        return "Nama column tidak valid.", 400

    allowed_types = {
        "VARCHAR(255)",
        "TEXT",
        "INT",
        "BIGINT",
        "DECIMAL(10,2)",
        "DATE",
        "DATETIME",
        "BOOLEAN",
    }

    if column_type not in allowed_types:
        return "Tipe data tidak diizinkan.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                """,
                (database_name, table_name)
            )

            if cursor.fetchone() is None:
                return "Table tidak ditemukan.", 404

            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
                """,
                (database_name, table_name, column_name)
            )

            if cursor.fetchone() is not None:
                return "Column sudah ada.", 400

            cursor.execute(
                f"""
                ALTER TABLE {quote_mysql_identifier(table_name)}
                ADD COLUMN {quote_mysql_identifier(column_name)}
                {column_type}
                NULL
                """
            )

    except pymysql.err.OperationalError as exc:
        return f"Gagal menambah column: {exc}", 400

    except Exception as exc:
        return f"Gagal menambah column: {exc}", 500

    finally:
        if conn:
            conn.close()

    return redirect(
        f"/databases/{database_name}/tables/{table_name}/structure"
    )

@app.route(
    "/databases/<database_name>/tables/<table_name>/columns/delete",
    methods=["POST"]
)
def delete_table_column(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    column_name = request.form.get("column_name", "").strip()

    if not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_]{0,63}",
        column_name
    ):
        return "Nama column tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COLUMN_NAME,
                    COLUMN_KEY,
                    EXTRA
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
                """,
                (database_name, table_name, column_name)
            )

            column = cursor.fetchone()

            if column is None:
                return "Column tidak ditemukan.", 404

            if column[1] == "PRI":
                return "Primary key tidak dapat dihapus.", 400

            if "auto_increment" in column[2].lower():
                return "Column AUTO_INCREMENT tidak dapat dihapus.", 400

            cursor.execute(
                f"""
                ALTER TABLE {quote_mysql_identifier(table_name)}
                DROP COLUMN {quote_mysql_identifier(column_name)}
                """
            )

    except pymysql.err.OperationalError as exc:
        return f"Gagal menghapus column: {exc}", 400

    except Exception as exc:
        return f"Gagal menghapus column: {exc}", 500

    finally:
        if conn:
            conn.close()

    return redirect(
        f"/databases/{database_name}/tables/{table_name}/structure"
    )


@app.route(
    "/databases/<database_name>/tables/<table_name>/browse"
)
def browse_table(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                """,
                (database_name, table_name)
            )

            if cursor.fetchone() is None:
                return "Table tidak ditemukan.", 404

            cursor.execute(
                f"SELECT * FROM {quote_mysql_identifier(table_name)} LIMIT 100"
            )

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                  AND COLUMN_KEY = 'PRI'
                ORDER BY ORDINAL_POSITION
                """,
                (database_name, table_name)
            )

            primary_columns = [column[0] for column in cursor.fetchall()]
            primary_key_index = None

            if len(primary_columns) == 1:
                primary_key_index = columns.index(primary_columns[0])

        return render_template(
            "table_browse.html",
            database=database_name,
            table=table_name,
            columns=columns,
            rows=rows,
            primary_key_index=primary_key_index
        )

    except Exception as exc:
        return f"Gagal membaca data table: {exc}", 500

    finally:
        if conn:
            conn.close()

@app.route(
    "/databases/<database_name>/tables/<table_name>/insert",
    methods=["GET", "POST"]
)
def insert_table_row(database_name, table_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COLUMN_NAME,
                    COLUMN_TYPE,
                    IS_NULLABLE,
                    COLUMN_DEFAULT,
                    EXTRA
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (database_name, table_name)
            )

            columns = cursor.fetchall()

            if not columns:
                return "Table tidak ditemukan atau tidak memiliki kolom.", 404

            if request.method == "POST":
                values = []
                column_names = []

                for column in columns:
                    column_name = column[0]
                    column_type = column[1]
                    is_nullable = column[2]
                    column_default = column[3]
                    extra = column[4]

                    # AUTO_INCREMENT diisi otomatis oleh MariaDB.
                    if "auto_increment" in extra.lower():
                        continue

                    mode = request.form.get(f"{column_name}__mode", "")
                    if mode not in {"VALUE", "NULL", "DEFAULT"}:
                        return f"Mode kolom '{column_name}' tidak valid.", 400
                    if mode == "NULL":
                        if is_nullable != "YES":
                            return f"Kolom '{column_name}' tidak boleh NULL.", 400
                        values.append(None)
                        column_names.append(column_name)
                        continue
                    if mode == "DEFAULT":
                        if column_default is None and is_nullable != "YES":
                            return f"Kolom '{column_name}' tidak memiliki DEFAULT.", 400
                        continue
                    if (
                        column_name not in request.form
                        and is_nullable != "YES"
                        and column_default is None
                    ):
                        return f"Kolom '{column_name}' wajib diisi.", 400

                    value = request.form.get(column_name, "")

                    try:
                        validate_table_value(column_type, value)
                    except ValueError as exc:
                        return render_template(
                            "table_insert.html",
                            database=database_name,
                            table=table_name,
                            columns=columns,
                            form_data=request.form,
                            error=str(exc),
                        ), 400

                    values.append(value)
                    column_names.append(column_name)

                if not column_names:
                    cursor.execute(
                        f"INSERT INTO {quote_mysql_identifier(table_name)} () VALUES ()"
                    )
                else:
                    quoted_columns = ", ".join(
                        quote_mysql_identifier(name)
                        for name in column_names
                    )

                    placeholders = ", ".join(
                        ["%s"] * len(values)
                    )

                    cursor.execute(
                        f"""
                        INSERT INTO {quote_mysql_identifier(table_name)}
                        ({quoted_columns})
                        VALUES ({placeholders})
                        """,
                        values
                    )

                return redirect(
                    f"/databases/{database_name}/tables/{table_name}/browse"
                )

        return render_template(
            "table_insert.html",
            database=database_name,
            table=table_name,
            columns=columns
        )

    except pymysql.err.IntegrityError as exc:
        return f"Gagal memasukkan data: {exc}", 400

    except pymysql.err.OperationalError as exc:
        return f"Gagal memasukkan data: {exc}", 400

    except Exception as exc:
        return f"Gagal memasukkan data: {exc}", 500

    finally:
        if conn:
            conn.close()
@app.route(
    "/databases/<database_name>/tables/<table_name>/edit/<path:row_id>",
    methods=["GET", "POST"]
)
def edit_table_row(database_name, table_name, row_id):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COLUMN_NAME,
                    COLUMN_TYPE,
                    IS_NULLABLE,
                    COLUMN_DEFAULT,
                    EXTRA,
                    COLUMN_KEY
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (database_name, table_name)
            )

            columns = cursor.fetchall()

            if not columns:
                return "Table tidak ditemukan atau tidak memiliki kolom.", 404

            primary_columns = [
                column[0]
                for column in columns
                if column[5] == "PRI"
            ]

            if len(primary_columns) != 1:
                return (
                    "Edit sementara hanya mendukung table "
                    "dengan tepat satu primary key.",
                    400
                )

            primary_column = primary_columns[0]

            cursor.execute(
                f"""
                SELECT *
                FROM {quote_mysql_identifier(table_name)}
                WHERE {quote_mysql_identifier(primary_column)} = %s
                LIMIT 1
                """,
                (row_id,)
            )

            row = cursor.fetchone()

            if row is None:
                return "Data tidak ditemukan.", 404

            if request.method == "POST":
                assignments = []
                values = []

                for index, column in enumerate(columns):
                    column_name = column[0]
                    column_type = column[1]
                    is_nullable = column[2]
                    column_default = column[3]
                    extra = column[4]

                    if column_name == primary_column:
                        continue

                    if "auto_increment" in extra.lower():
                        continue

                    mode = request.form.get(f"{column_name}__mode", "")
                    if mode not in {"VALUE", "NULL", "DEFAULT"}:
                        return f"Mode kolom '{column_name}' tidak valid.", 400
                    if mode == "NULL":
                        if is_nullable != "YES":
                            return f"Kolom '{column_name}' tidak boleh NULL.", 400
                        assignments.append(
                            f"{quote_mysql_identifier(column_name)} = %s"
                        )
                        values.append(None)
                        continue
                    if mode == "DEFAULT":
                        if column_default is None and is_nullable != "YES":
                            return f"Kolom '{column_name}' tidak memiliki DEFAULT.", 400
                        assignments.append(
                            f"{quote_mysql_identifier(column_name)} = DEFAULT"
                        )
                        continue
                    if (
                        column_name not in request.form
                        and is_nullable != "YES"
                        and column_default is None
                    ):
                        return f"Kolom '{column_name}' wajib diisi.", 400

                    value = request.form.get(column_name, "")

                    try:
                        validate_table_value(column_type, value)
                    except ValueError as exc:
                        return render_template(
                            "table_edit.html",
                            database=database_name,
                            table=table_name,
                            columns=columns,
                            row=row,
                            primary_column=primary_column,
                            row_id=row_id,
                            form_data=request.form,
                            error=str(exc),
                        ), 400

                    assignments.append(
                        f"{quote_mysql_identifier(column_name)} = %s"
                    )
                    values.append(value)

                if assignments:
                    values.append(row_id)

                    cursor.execute(
                        f"""
                        UPDATE {quote_mysql_identifier(table_name)}
                        SET {", ".join(assignments)}
                        WHERE {quote_mysql_identifier(primary_column)} = %s
                        """,
                        values
                    )

                return redirect(
                    f"/databases/{database_name}/tables/{table_name}/browse"
                )

        return render_template(
            "table_edit.html",
            database=database_name,
            table=table_name,
            columns=columns,
            row=row,
            primary_column=primary_column,
            row_id=row_id
        )

    except pymysql.err.IntegrityError as exc:
        return f"Gagal mengubah data: {exc}", 400

    except pymysql.err.OperationalError as exc:
        return f"Gagal mengubah data: {exc}", 400

    except Exception as exc:
        return f"Gagal mengubah data: {exc}", 500

    finally:
        if conn:
            conn.close()

@app.route(
    "/databases/<database_name>/tables/<table_name>/delete/<path:row_id>",
    methods=["POST"]
)
def delete_table_row(database_name, table_name, row_id):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak dapat dikelola.", 403

    if not valid_table_name(table_name):
        return "Nama table tidak valid.", 400

    conn = None

    try:
        conn = get_mariadb_connection(database_name)

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COLUMN_NAME,
                    COLUMN_KEY
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (database_name, table_name)
            )

            columns = cursor.fetchall()

            if not columns:
                return "Table tidak ditemukan atau tidak memiliki kolom.", 404

            primary_columns = [
                column[0]
                for column in columns
                if column[1] == "PRI"
            ]

            if len(primary_columns) != 1:
                return (
                    "Delete sementara hanya mendukung table "
                    "dengan tepat satu primary key.",
                    400
                )

            primary_column = primary_columns[0]

            cursor.execute(
                f"""
                SELECT 1
                FROM {quote_mysql_identifier(table_name)}
                WHERE {quote_mysql_identifier(primary_column)} = %s
                LIMIT 1
                """,
                (row_id,)
            )

            if cursor.fetchone() is None:
                return "Data tidak ditemukan.", 404

            cursor.execute(
                f"""
                DELETE FROM {quote_mysql_identifier(table_name)}
                WHERE {quote_mysql_identifier(primary_column)} = %s
                LIMIT 1
                """,
                (row_id,)
            )

        return redirect(
            f"/databases/{database_name}/tables/{table_name}/browse"
        )

    except pymysql.err.IntegrityError as exc:
        return f"Gagal menghapus data: {exc}", 400

    except pymysql.err.OperationalError as exc:
        return f"Gagal menghapus data: {exc}", 400

    except Exception as exc:
        return f"Gagal menghapus data: {exc}", 500

    finally:
        if conn:
            conn.close()

@app.route("/databases/<database_name>/delete", methods=["POST"])
def delete_database(database_name):
    if "user_id" not in session:
        return redirect("/login")

    if not valid_database_name(database_name):
        return "Nama database tidak valid.", 400

    if database_name in SYSTEM_DATABASES:
        return "Database sistem tidak boleh dihapus.", 403

    if not database_name.startswith(DATABASE_PREFIX):
        return "Database di luar scope panel.", 403

    conn = None

    try:
        conn = get_mariadb_connection()

        with conn.cursor() as cursor:
            cursor.execute(
                f"DROP DATABASE {quote_mysql_identifier(database_name)}"
            )

    except pymysql.err.OperationalError as exc:
        return f"Gagal menghapus database: {exc}", 400

    except Exception as exc:
        return f"Gagal menghapus database: {exc}", 500

    finally:
        if conn:
            conn.close()

    return redirect("/databases")


@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")



@app.route("/websites/<int:website_id>/nginx")
def nginx_manager(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    nginx_file = (
        Path("/etc/nginx/sites-enabled")
        / website["name"]
    )

    config = ""

    if nginx_file.exists():
        config = nginx_file.read_text(
            encoding="utf-8"
        )

    return render_template(
        "nginx_manager.html",
        website=website,
        config=config,
        nginx_file=str(nginx_file),
        message=None,
        error=None
    )

@app.route(
    "/websites/<int:website_id>/nginx/save",
    methods=["POST"]
)
def nginx_save(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    config = request.form.get(
        "config",
        ""
    )

    if not config.strip():
        return "Konfigurasi kosong", 400

    nginx_file = (
        Path("/etc/nginx/sites-enabled")
        / website["name"]
    )

    if not nginx_file.exists():
        return "Konfigurasi Nginx belum dibuat.", 400

    old_config = nginx_file.read_text(
        encoding="utf-8"
    )

    try:

        # Simpan konfigurasi lama di memory.
        # Jangan menghapusnya sebelum konfigurasi baru
        # terbukti valid.

        nginx_file.write_text(
            config,
            encoding="utf-8"
        )

        test = subprocess.run(
            ["nginx", "-t"],
            capture_output=True,
            text=True
        )

        if test.returncode != 0:

            # Restore konfigurasi lama
            nginx_file.write_text(
                old_config,
                encoding="utf-8"
            )

            return render_template(
                "nginx_manager.html",
                website=website,
                config=old_config,
                nginx_file=str(nginx_file),
                message=None,
                error=(
                    "Konfigurasi baru ditolak. "
                    "Konfigurasi lama telah dipulihkan.\n\n"
                    "nginx -t gagal:\n\n"
                    + test.stderr
                )
            )

        # Konfigurasi valid.
        # Sekarang reload Nginx.

        reload_result = subprocess.run(
            ["nginx", "-s", "reload"],
            capture_output=True,
            text=True
        )

        if reload_result.returncode != 0:

            # Reload gagal → restore konfigurasi lama
            nginx_file.write_text(
                old_config,
                encoding="utf-8"
            )

            # Pastikan Nginx kembali memakai konfigurasi lama
            subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True
            )

            subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True
            )

            return render_template(
                "nginx_manager.html",
                website=website,
                config=old_config,
                nginx_file=str(nginx_file),
                message=None,
                error=(
                    "Nginx gagal reload. "
                    "Konfigurasi lama telah dipulihkan.\n\n"
                    + reload_result.stderr
                )
            )

        return render_template(
            "nginx_manager.html",
            website=website,
            config=config,
            nginx_file=str(nginx_file),
            message=(
                "Konfigurasi berhasil disimpan, "
                "valid, dan Nginx berhasil reload."
            ),
            error=None
        )

    except Exception as e:

        # Jika terjadi exception, selalu coba restore
        try:
            nginx_file.write_text(
                old_config,
                encoding="utf-8"
            )

            subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True
            )

            subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True
            )

        except Exception:
            pass

        return render_template(
            "nginx_manager.html",
            website=website,
            config=old_config,
            nginx_file=str(nginx_file),
            message=None,
            error=(
                "Terjadi kesalahan. "
                "Konfigurasi lama telah dicoba dipulihkan.\n\n"
                + str(e)
            )
        )

@app.route(
    "/websites/<int:website_id>/nginx/reload",
    methods=["POST"]
)
def nginx_reload(website_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    website = conn.execute(
        "SELECT * FROM websites WHERE id = ?",
        (website_id,)
    ).fetchone()

    conn.close()

    if website is None:
        return "Website tidak ditemukan", 404

    nginx_file = (
        Path("/etc/nginx/sites-enabled")
        / website["name"]
    )

    if not nginx_file.exists():
        return "Konfigurasi Nginx belum dibuat.", 400

    try:

        test = subprocess.run(
            ["nginx", "-t"],
            capture_output=True,
            text=True
        )

        if test.returncode != 0:

            return render_template(
                "nginx_manager.html",
                website=website,
                config=nginx_file.read_text(
                    encoding="utf-8"
                ),
                nginx_file=str(nginx_file),
                message=None,
                error=(
                    "Nginx reload dibatalkan.\n\n"
                    "nginx -t gagal:\n\n"
                    + test.stderr
                )
            )

        reload_result = subprocess.run(
            ["nginx", "-s", "reload"],
            capture_output=True,
            text=True
        )

        if reload_result.returncode != 0:

            return render_template(
                "nginx_manager.html",
                website=website,
                config=nginx_file.read_text(
                    encoding="utf-8"
                ),
                nginx_file=str(nginx_file),
                message=None,
                error=(
                    "nginx -t berhasil, tetapi "
                    "reload gagal:\n\n"
                    + reload_result.stderr
                )
            )

        return render_template(
            "nginx_manager.html",
            website=website,
            config=nginx_file.read_text(
                encoding="utf-8"
            ),
            nginx_file=str(nginx_file),
            message="Nginx berhasil di-test dan di-reload.",
            error=None
        )

    except Exception as e:

        return render_template(
            "nginx_manager.html",
            website=website,
            config=nginx_file.read_text(
                encoding="utf-8"
            ),
            nginx_file=str(nginx_file),
            message=None,
            error=str(e)
        )

if __name__ == "__main__":
    init_db()

    app.run(
        host="0.0.0.0",
        port=5000
    )
