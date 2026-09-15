# Jayantara Custom Panel

**Jayantara Custom Panel** adalah panel administrasi web berbasis Flask yang dikembangkan untuk mengelola server dan website milik Jayantara secara mandiri.

Panel ini dirancang untuk berjalan pada lingkungan **Ubuntu Linux**, termasuk Ubuntu yang berjalan melalui **Termux/PRoot pada perangkat Android**, dengan fokus pada pengelolaan website, Nginx, database, file, dan operasi server yang diperlukan.

Repository ini berisi source code utama Custom Panel.

---

## Tujuan Proyek

Custom Panel dibuat untuk menyediakan satu antarmuka administrasi untuk:

* Mengelola website yang berjalan di server.
* Mengelola konfigurasi Nginx.
* Mengelola file website.
* Mengelola database MariaDB.
* Membuat dan mengelola tabel database.
* Melihat dan mengelola struktur tabel.
* Melihat, menambah, mengubah, dan menghapus data tabel.
* Menyediakan fondasi untuk pengelolaan server Jayantara secara terintegrasi.
* Mengurangi ketergantungan terhadap konfigurasi manual melalui terminal.

Panel ditujukan untuk penggunaan internal/admin dan bukan sebagai shared-hosting panel publik.

---

# Arsitektur Saat Ini

```text
                         Android
                            │
                         Termux
                            │
                     Ubuntu / PRoot
                            │
              ┌─────────────┴─────────────┐
              │                           │
           Nginx                      MariaDB
          :9000                     Unix Socket
              │
              ▼
         Gunicorn :5000
              │
              ▼
          Flask Panel
       /opt/custom-panel
              │
      ┌───────┼────────┐
      │       │        │
   SQLite   MariaDB  /var/www/html
   Panel DB   DBs       Websites
```

### Komponen utama

| Komponen | Fungsi                               |
| -------- | ------------------------------------ |
| Flask    | Backend aplikasi panel               |
| Gunicorn | Application server                   |
| Nginx    | Reverse proxy dan web server         |
| SQLite   | Database internal panel              |
| MariaDB  | Database yang dikelola melalui panel |
| Jinja2   | Template antarmuka                   |
| Werkzeug | Password hashing                     |
| PyMySQL  | Koneksi Flask ke MariaDB             |
| psutil   | Informasi resource sistem            |

---

# Fitur

## 1. Authentication

* Login administrator.
* Password disimpan menggunakan password hashing.
* Session menggunakan secret key persisten.
* HTTPOnly session cookie.
* SameSite cookie protection.
* CSRF protection untuk request POST.
* Login rate limiting.
* Change password dengan validasi password lama.
* Password baru memiliki persyaratan minimum.

---

## 2. Website Manager

Panel dapat mengelola website pada:

```text
/var/www/html/
```

Website mendapatkan port HTTP pada range:

```text
8080 - 8999
```

Fungsi yang tersedia meliputi:

* Membuat website.
* Menentukan document root.
* Alokasi port.
* Membuat konfigurasi Nginx.
* Validasi konfigurasi Nginx.
* Reload Nginx.
* Rollback apabila konfigurasi gagal.

Website yang saat ini digunakan untuk pengujian:

```text
jayantara  → 8080
testsite   → 8081
demo8082   → 8082
Test8082   → 8083
demo8084   → 8084
autotest8085 → 8085
```

---

## 3. File Manager

Panel menyediakan pengelolaan file website dengan validasi path untuk mencegah akses keluar dari document root.

Fitur yang telah tersedia:

* Melihat file.
* Membuka file.
* Mengedit file.
* Validasi safe path.

---

# 4. Database Manager

Database Manager menggunakan MariaDB.

Database yang dikelola oleh panel menggunakan prefix:

```text
jayantara_
```

Contoh:

```text
jayantara_dbmanager_test
```

Database sistem seperti:

```text
information_schema
mysql
performance_schema
sys
```

tidak dapat dikelola melalui panel.

---

## Database Manager Phase 1

Fitur dasar:

* Melihat daftar database.
* Membuat database.
* Melihat detail database.
* Menghapus database.

Panel menggunakan dedicated MariaDB account:

```text
jayantara_panel@localhost
```

Akun tersebut tidak menggunakan `GRANT OPTION` dan hak akses dibatasi sesuai kebutuhan panel.

---

# Database Manager Phase 2

Phase 2 berfokus pada pengelolaan tabel dan data.

### Table Management

* Membuat tabel.
* Menghapus tabel.
* Melihat struktur tabel.

Tabel baru menggunakan struktur awal dengan:

```sql
id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY
```

---

## Column Management

Fitur:

* Menambahkan column.
* Menghapus column.
* Melihat tipe column.
* Melihat nullable status.
* Melihat key.
* Melihat default.
* Melihat extra information.

Tipe column yang saat ini diperbolehkan melalui UI:

```text
VARCHAR(255)
TEXT
INT
BIGINT
DECIMAL(10,2)
DATE
DATETIME
BOOLEAN
```

Primary key dan column `AUTO_INCREMENT` dilindungi dari penghapusan melalui panel.

---

## Table Data Management

Fitur:

* Browse data.
* Insert data.
* Edit data.
* Delete data.

Browse dibatasi sampai:

```text
100 rows
```

untuk mencegah halaman panel memuat dataset yang terlalu besar sekaligus.

---

# Security Principles

Custom Panel menggunakan beberapa prinsip keamanan dasar:

### Authentication

Semua operasi administratif membutuhkan session login.

### CSRF Protection

Request POST membutuhkan CSRF token.

### Password Security

Password tidak disimpan dalam bentuk plaintext.

### SQL Injection Protection

Value SQL menggunakan parameterized query.

Identifier database, table, dan column divalidasi sebelum digunakan.

Identifier SQL yang telah divalidasi juga di-quote menggunakan helper khusus.

### Path Traversal Protection

File manager menggunakan validasi safe path agar operasi file tetap berada di dalam area yang diizinkan.

### Privilege Separation

Panel menggunakan account MariaDB khusus dan tidak menggunakan root database account untuk operasi normal.

---

# Runtime

Current development environment:

```text
OS: Ubuntu Linux under Termux/PRoot
Architecture: aarch64 / ARM64
Python: 3.14.x
Flask: application framework
Gunicorn: application server
Nginx: reverse proxy
MariaDB: 11.8.x
PyMySQL: MariaDB client library
```

Current panel flow:

```text
Client
  │
  ▼
Nginx :9000
  │
  ▼
Gunicorn :5000
  │
  ▼
Flask
```

Panel dapat diakses melalui LAN menggunakan alamat server, misalnya:

```text
http://SERVER_IP:9000/login
```

---

# Project Structure

```text
/opt/custom-panel/
│
├── app.py
├── panelctl.sh
├── start-panel.sh
├── startup-panel.sh
├── panel.db
├── .panel_secret_key
├── .mariadb_panel_password
├── venv/
│
└── templates/
    ├── add_website.html
    ├── change_password.html
    ├── dashboard.html
    ├── database_detail.html
    ├── databases.html
    ├── edit_file.html
    ├── files.html
    ├── login.html
    ├── nginx_manager.html
    ├── table_browse.html
    ├── table_edit.html
    ├── table_insert.html
    ├── table_structure.html
    ├── website_detail.html
    └── websites.html
```

> File secret, database runtime, virtual environment, log, dan backup tidak boleh dimasukkan ke repository Git.

---

# Git Branch Strategy

Development database manager saat ini berada pada:

```text
feature/database-manager-phase2
```

Branch tersebut digunakan sebagai checkpoint pengembangan sebelum perubahan siap masuk ke branch release.

---

# Milestone

## Milestone 0 — Project Foundation

**Status: DONE**

* [x] Flask application.
* [x] Basic project structure.
* [x] Authentication.
* [x] Session management.
* [x] Password hashing.
* [x] CSRF protection.
* [x] Basic dashboard.
* [x] Git repository.

---

## Milestone 1 — Website Management

**Status: DONE**

* [x] Website creation.
* [x] Website listing.
* [x] Website detail.
* [x] Port allocation.
* [x] Nginx configuration generation.
* [x] Nginx configuration validation.
* [x] Nginx reload.
* [x] Rollback on configuration failure.
* [x] Website HTTP testing.

---

## Milestone 2 — File Management

**Status: DONE / BASELINE**

* [x] File listing.
* [x] File viewing.
* [x] File editing.
* [x] Safe path validation.

---

## Milestone 3 — Database Manager Phase 1

**Status: DONE**

* [x] Database listing.
* [x] Database creation.
* [x] Database detail.
* [x] Database deletion.
* [x] Dedicated MariaDB panel user.
* [x] Database name validation.
* [x] System database protection.

---

## Milestone 4 — Database Manager Phase 2

**Status: DONE**

### Table Management

* [x] Create table.
* [x] Delete table.
* [x] View table structure.

### Column Management

* [x] Add column.
* [x] Delete column.
* [x] Protect primary key.
* [x] Protect AUTO_INCREMENT column.

### Data Management

* [x] Browse table data.
* [x] Insert row.
* [x] Edit row.
* [x] Delete row.

### Validation

* [x] Comprehensive negative testing.
* [x] Foreign key behavior testing.
* [x] Multiple-column primary key handling.
* [x] Edge-case testing for unusual schemas.
* [x] Error handling review.
* [x] UI consistency review.
* [x] Security review of all database routes.
* [x] Regression testing.

---

## Milestone 5 — Production Hardening

**Status: DONE**

### Security Hardening

* [x] Full route audit.
* [x] Input validation audit.
* [x] CSRF audit.
* [x] Authentication/authorization audit.
* [x] Session security review.
* [x] Error handling review.
* [x] Logging review.
* [x] Remove debug/development behavior.
* [x] Database operation regression testing.
* [x] Transaction/error handling review.
* [x] Schema edge-case testing.
* [x] Permission boundary testing.
* [x] Destructive-operation safeguards.
* [x] Nginx configuration audit.
* [x] Invalid configuration rollback testing.
* [x] Port collision testing.
* [x] Reload/runtime failure testing.
* [x] File path traversal and permission review.

### Production Runtime

* [x] Gunicorn binding and worker configuration reviewed.
* [x] Nginx reverse proxy configuration reviewed.
* [x] Nginx → Gunicorn runtime verified.
* [x] Gunicorn logging reviewed.
* [x] Final regression smoke tests completed.
* [x] Release Candidate security audit completed.

### Notes

* Database exception details are no longer returned directly to users.
* Composite primary keys are safely rejected by the current Edit/Delete implementation.
* Password/session lifecycle was reviewed; no blocking authentication defect was identified.
* MariaDB panel access remains scoped to the `jayantara_%` database namespace.

---

## Milestone 6 — Operational Reliability

**Status: DONE**

* [x] Clean startup sequence.
* [x] Gunicorn process management verified.
* [x] Nginx startup verified.
* [x] MariaDB startup and panel connectivity verified.
* [x] PHP-FPM startup/recovery verified.
* [x] Restart/recovery testing.
* [x] Service health checks.
* [x] SQLite backup and restore procedure tested.
* [x] MariaDB backup and restore procedure tested.
* [x] Configuration consistency verified.
* [x] Git checkpoint procedure verified.
* [x] Log rotation configuration verified.
* [x] Startup idempotency verified.

### Notes

* Gunicorn, Nginx, PHP-FPM, and MariaDB recovery behavior was tested.
* MariaDB forced-stop simulation was limited by the PRoot runtime because the `mariadbd-safe` parent kept the daemon alive; application connectivity and startup/recovery behavior were nevertheless verified.
* SQLite and MariaDB backup/restore procedures were successfully tested.
* Gunicorn log rotation and log reopening via `SIGUSR1` were verified.

---

## Milestone 7 — Release Candidate

**Status: CURRENT**

Custom Panel is in the Release Candidate audit phase.

### Release Candidate Checklist

* [x] Semua fitur utama selesai.
* [x] Security audit selesai.
* [x] Database Manager selesai.
* [x] Website Manager selesai.
* [x] File Manager baseline selesai.
* [x] Nginx Manager selesai.
* [x] Restart/recovery berhasil diuji.
* [x] Backup dan restore berhasil diuji.
* [x] Production configuration diverifikasi.
* [x] Repository bersih.
* [x] Dependency audit selesai.
* [x] Static application audit selesai.
* [x] HTTP endpoint dan authentication smoke test selesai.
* [x] CSRF enforcement test selesai.
* [x] Database CRUD regression test selesai.
* [x] Database/table management regression test selesai.
* [x] Nginx configuration audit selesai.
* [x] Permission and ownership audit selesai.
* [x] SQLite integrity and production data audit selesai.
* [x] Final runtime and service consistency audit selesai.
* [ ] Release Candidate checkpoint dibuat.

---

## Milestone 8 — Production Ready

**Status: NOT READY**

Custom Panel baru dianggap **siap digunakan** apabila seluruh checklist berikut terpenuhi:

```text
[ ] Feature complete
[ ] Security reviewed
[ ] No critical bugs
[ ] No high-priority unresolved bugs
[ ] Database operations tested
[ ] Website operations tested
[ ] File operations tested
[ ] Nginx operations tested
[ ] Startup tested
[ ] Restart tested
[ ] Failure recovery tested
[ ] Backup tested
[ ] Restore tested
[ ] Git repository clean
[ ] Production configuration verified
[ ] Release checkpoint created
---

# Development Rules

Perubahan besar sebaiknya dilakukan secara bertahap.

Sebelum melanjutkan ke fitur berikutnya:

1. Test fitur saat ini.
2. Periksa `git diff --check`.
3. Commit perubahan.
4. Push checkpoint ke GitHub.
5. Baru lanjut ke perubahan berikutnya.

Contoh:

```bash
git diff --check
git status
git add .
git commit -m "Descriptive commit message"
git push
```

---

# Backup and Recovery

Source code disimpan menggunakan Git.

Repository:

```text
fikdaf/custom-panel
```

Development branch:

```text
feature/database-manager-phase2
```

Checkpoint harus dibuat sebelum perubahan besar sehingga perubahan dapat dikembalikan apabila terjadi regresi.

**Secret dan credential tidak boleh di-commit.**

Contoh file yang harus tetap berada di luar Git:

```text
.panel_secret_key
.mariadb_panel_password
panel.db
venv/
logs/
backup files
```


---

# Current Development Status

Saat README ini dibuat, Custom Panel telah memiliki:

* Authentication.
* Website Manager.
* File Manager dasar.
* Nginx integration.
* MariaDB integration.
* Database Manager Phase 1.
* Database Manager Phase 2 untuk table, column, dan row management.

Fokus saat ini adalah menyelesaikan **Release Candidate audit**, memastikan tidak ada regression atau blocker yang tersisa, dan menyiapkan checkpoint release sebelum evaluasi Production Ready.

---

# Final Goal

Tujuan akhir proyek adalah menghasilkan panel administrasi internal Jayantara yang:

* Stabil.
* Aman.
* Dapat dipulihkan.
* Mudah digunakan.
* Tidak bergantung pada operasi manual untuk tugas administrasi umum.
* Memiliki backup dan checkpoint yang jelas.
* Siap dijalankan sebagai bagian dari infrastructure server Jayantara.

**Production Ready bukan hanya berarti semua fitur selesai, tetapi juga seluruh fitur telah diuji, error handling telah diverifikasi, keamanan telah diaudit, dan prosedur backup/restore telah terbukti berhasil.**
