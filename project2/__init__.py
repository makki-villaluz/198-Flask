import os 
from flask import Flask
from project2.config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

app = Flask(__name__, static_folder='./../static')
cors = CORS(app)
app.config.from_object(Config)
db = SQLAlchemy(app)

from project2 import routes