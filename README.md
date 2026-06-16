# Dental Management

Huong dan setup nhanh project Django voi MySQL.

Project nay chi dung MySQL, khong dung database SQLite `db.sqlite3`.

## 1. Chuan bi

Can cai san:

- Python 3.10+
- MySQL Server
- MySQL Workbench neu muon xem database bang giao dien

## 2. Tao moi truong Python

```bash
cd /Users/hoang/dental_management
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Tao database MySQL

Mo MySQL Workbench bang tai khoan `root`, chay file:

```text
setup_mysql_user.sql
```

File nay se tao database `medica` va user `dental_user`. Kiem tra password trong file SQL va dung cung password do cho `DB_PASSWORD` trong `.env`.

Neu muon tu chay SQL nhanh:

```sql
CREATE DATABASE IF NOT EXISTS medica CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'dental_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON medica.* TO 'dental_user'@'localhost';
GRANT ALL PRIVILEGES ON test_medica.* TO 'dental_user'@'localhost';
FLUSH PRIVILEGES;
```

## 4. Cau hinh `.env`

Tao file `.env` o thu muc goc project:

```env
DB_ENGINE=mysql
DB_NAME=medica
DB_USER=dental_user
DB_PASSWORD=your_password
DB_HOST=127.0.0.1
DB_PORT=3306
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@dental.local
MOMO_PARTNER_CODE=
MOMO_ACCESS_KEY=
MOMO_SECRET_KEY=
MOMO_PARTNER_NAME=Dental Management
MOMO_STORE_NAME=Dental Management
MOMO_STORE_ID=DENTAL
MOMO_CREATE_ENDPOINT=https://test-payment.momo.vn/v2/gateway/api/create
MOMO_QUERY_ENDPOINT=https://test-payment.momo.vn/v2/gateway/api/query
```

`DB_PASSWORD` phai trung voi password cua user MySQL vua tao.

Neu muon gui email that, thay `EMAIL_BACKEND` bang SMTP backend va khai bao them:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your_email@example.com
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_USE_TLS=true
```

Mau san cho che do `MoMo sandbox + Gmail SMTP`:

```bash
cp .env.momo-gmail.example .env
```

Sau do sua 5 gia tri that trong `.env`:

- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `MOMO_PARTNER_CODE`
- `MOMO_ACCESS_KEY`
- `MOMO_SECRET_KEY`

## 5. Tao bang va tai khoan admin

```bash
python3 manage.py migrate
python3 manage.py createsuperuser
```

## 6. Chay web

```bash
python3 manage.py runserver
```

Mo trinh duyet:

```text
http://127.0.0.1:8000/
```

Trang quan ly he thong:

```text
http://127.0.0.1:8000/system/
```

Trang bac si / nhan vien:

```text
http://127.0.0.1:8000/portal/login/
```

## 7. Chay test

Tai khoan MySQL can co quyen tao/xoa database test `test_medica`. Neu gap loi `Access denied ... test_medica`, hay chay lai `setup_mysql_user.sql` bang tai khoan `root`.

```bash
python3 manage.py test
```

## 8. Tao du lieu mau de test giao dien

Lenh nay tao/cap nhat tai khoan mau, benh nhan, nhan su, dich vu, bang gia, ca truc va lich hen trong database `medica`.

```bash
python manage.py seed_demo_data
```

Tai khoan dang nhap mau:

```text
demo_admin / Demo@12345
```

## 9. Kiem tra app dang dung database nao

```bash
python check_db.py
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default'])"
```

Ket qua dung phai la MySQL database `medica`.

## 10. Loi hay gap

Neu web khong thay du lieu trong MySQL Workbench:

```bash
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'], settings.DATABASES['default']['NAME'])"
```

Neu khong hien `django.db.backends.mysql medica`, hay kiem tra lai file `.env` va restart server.

Neu sua `.env`, dung server bang `Ctrl+C`, sau do chay lai:

```bash
python manage.py runserver
```
