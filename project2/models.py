from project2 import db

class GPXVehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), unique=True, nullable=False)

class GPXRoute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), unique=True, nullable=False)
    # route = db.Column(db.String(500), nullable=False)
    lat1 = db.Column(db.Float, nullable=False)
    long1 = db.Column(db.Float, nullable=False)
    lat2 = db.Column(db.Float, nullable=False)
    long2 = db.Column(db.Float, nullable=False)
    cell_size = db.Column(db.Float, nullable=False)

class GPXStop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    min_time = db.Column(db.Float, nullable=False)
    max_time = db.Column(db.Float, nullable=False)