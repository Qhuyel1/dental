import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


def check_db_connection():
    engine = os.getenv('DB_ENGINE', 'mysql')
    print(f"Current DB_ENGINE in .env: {engine}")

    if engine != 'mysql':
        print("ERROR: Project nay chi cau hinh MySQL. Hay dat DB_ENGINE=mysql trong file .env.")
        return

    try:
        conn = pymysql.connect(
            host=os.getenv('DB_HOST', '127.0.0.1'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'medica'),
            port=int(os.getenv('DB_PORT', 3306)),
        )
        print("Connected to MySQL database successfully.")
        conn.close()
    except Exception as e:
        print(f"Failed to connect to MySQL: {e}")


if __name__ == "__main__":
    check_db_connection()
