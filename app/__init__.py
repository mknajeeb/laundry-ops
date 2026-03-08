from flask import Flask
from flask_cors import CORS
from app.routes import api

def create_app():

    app = Flask(__name__)

    # allow all frontend origins
    CORS(app, resources={r"/*": {"origins": "*"}})

    app.register_blueprint(api)

    return app