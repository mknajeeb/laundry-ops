from app.db import get_db_connection

def get_time():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT NOW()")
    result = cursor.fetchone()
    conn.close()
    return result