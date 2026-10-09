from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from db import get_db_connection
from schema import initialize_database
from routes.video_routes import video_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(video_bp)


@app.get("/api/health")
def health():
    result = {
        "status": "ok",
        "service": "inx-backend",
        "database": "disconnected",
    }

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        connection.close()
        result["database"] = "connected"
    except Exception as exc:
        result["status"] = "degraded"
        result["error"] = str(exc)

    return jsonify(result)


if __name__ == "__main__":
    initialize_database()
    app.run(
        host=Config.FLASK_HOST,
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG,
    )
