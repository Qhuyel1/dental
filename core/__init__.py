# Fallback: dùng pymysql thay cho mysqlclient nếu chưa cài
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
