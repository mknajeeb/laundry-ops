import os

from backend.app import app

if __name__ == "__main__":
    # FLASK_DEBUG=0 speeds up local API (no reloader / debugger overhead).
    _dbg = os.getenv("FLASK_DEBUG", "1").strip().lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=8000, debug=_dbg)