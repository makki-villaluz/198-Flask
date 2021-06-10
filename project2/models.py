import datetime
from project2 import db

class GPXVehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), unique=True, nullable=False)
    date_uploaded = db.Column(db.Date, default=datetime.date.today(), nullable=False)
    route_id = db.Column(db.Integer, nullable=False)
    stops_id = db.Column(db.Integer, nullable=False)

class GPXRoute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), unique=True, nullable=False)
    date_uploaded = db.Column(db.Date, default=datetime.date.today(), nullable=False)
    cell_size = db.Column(db.Float, nullable=False)

class GPXStop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    date_uploaded = db.Column(db.Date, default=datetime.date.today(), nullable=False)
    min_time = db.Column(db.Float, nullable=False)
    max_time = db.Column(db.Float, nullable=False)