import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_db():
    """MySQL connection using environment variables (see .env.example)."""
    host = os.getenv("MYSQL_HOST", "mkncentralussrv1.mysql.database.azure.com")
    user = os.getenv("MYSQL_USER", "kamsee")
    password = os.getenv("MYSQL_PASSWORD")
    database = os.getenv("MYSQL_DATABASE", "laundryapp")
    port = int(os.getenv("MYSQL_PORT", "3306"))

    if not password:
        raise RuntimeError(
            "MYSQL_PASSWORD is not set. Add it to a .env file in the project root."
        )

    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
    )
