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

    kwargs = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port,
    }
    # Optional: path to CA PEM (Azure MySQL). If unset, connector uses its default TLS behavior.
    ssl_ca = os.getenv("MYSQL_SSL_CA")
    if ssl_ca:
        kwargs["ssl_ca"] = ssl_ca
        kwargs["ssl_disabled"] = False
    elif os.getenv("MYSQL_SSL_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
        kwargs["ssl_disabled"] = False

    return mysql.connector.connect(**kwargs)
