import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_db():
    """MySQL connection using environment variables (see .env.example)."""
    # Support MYSQL_* (Flask / Azure) or DB_* (legacy .env) — same values, one set is enough.
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "mkncentralussrv1.mysql.database.azure.com"
    user = os.getenv("MYSQL_USER") or os.getenv("DB_USER") or "kamsee"
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME") or "laundryapp"
    port = int(os.getenv("MYSQL_PORT") or os.getenv("DB_PORT") or "3306")

    if not password:
        raise RuntimeError(
            "Set MYSQL_PASSWORD or DB_PASSWORD in a .env file in the project root."
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
