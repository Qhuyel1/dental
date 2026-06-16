-- Chạy trong MySQL Workbench (root connection)

-- 1. Tạo database nếu chưa có
CREATE DATABASE IF NOT EXISTS medica CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS test_medica CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 2. Xóa user cũ nếu tồn tại
DROP USER IF EXISTS 'dental_user'@'localhost';
DROP USER IF EXISTS 'dental_user'@'%';
DROP USER IF EXISTS 'dental_user'@'127.0.0.1';

-- 3. Tạo lại user (MySQL 8.4+ không cần chỉ plugin)
CREATE USER 'dental_user'@'localhost' IDENTIFIED BY 'Meo@2004';
CREATE USER 'dental_user'@'%' IDENTIFIED BY 'Meo@2004';
CREATE USER 'dental_user'@'127.0.0.1' IDENTIFIED BY 'Meo@2004';

-- 4. Cấp toàn bộ quyền
GRANT ALL PRIVILEGES ON medica.* TO 'dental_user'@'localhost';
GRANT ALL PRIVILEGES ON medica.* TO 'dental_user'@'%';
GRANT ALL PRIVILEGES ON medica.* TO 'dental_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON test_medica.* TO 'dental_user'@'localhost';
GRANT ALL PRIVILEGES ON test_medica.* TO 'dental_user'@'%';
GRANT ALL PRIVILEGES ON test_medica.* TO 'dental_user'@'127.0.0.1';

-- Django test runner can create/drop the test database.
GRANT CREATE, DROP ON *.* TO 'dental_user'@'localhost';
GRANT CREATE, DROP ON *.* TO 'dental_user'@'%';
GRANT CREATE, DROP ON *.* TO 'dental_user'@'127.0.0.1';

-- 5. Áp dụng thay đổi
FLUSH PRIVILEGES;

-- 6. Kiểm tra kết quả
SELECT User, Host FROM mysql.user WHERE User = 'dental_user';
SHOW DATABASES LIKE 'medica';
SHOW DATABASES LIKE 'test_medica';
SHOW GRANTS FOR 'dental_user'@'localhost';
