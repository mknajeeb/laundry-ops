import mysql.connector
from app.config import Config


def get_db_connection():

    conn = mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=3306
    )

    return conn