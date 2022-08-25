import datetime
from project2 import db
from werkzeug.security import generate_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    admin = db.Column(db.Boolean, nullable=False)
    routes = db.Column(db.String(1000))

    def __init__(self, username, password, admin=False, routes=""):
        self.username = username
        self.password = generate_password_hash(password, method='sha256')
        self.admin = admin
        self.routes = routes

    def __repr__(self):
        return f"User('{self.id}','{self.username}','{self.admin}','{self.routes}')"

class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    ref_filename = db.Column(db.String(60), default=None, nullable=True, unique=True)
    stop_filename = db.Column(db.String(60), default=None, nullable=True, unique=True)
    date_uploaded = db.Column(db.Date, default=None)
    vehicles = db.relationship('Vehicle', backref='route')
    parameters = db.relationship('Parameters', backref='route', lazy='select', uselist=False)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Route('{self.id}','{self.name}','{self.ref_filename}','{self.stop_filename}','{self.date_uploaded}')"

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    filename = db.Column(db.String(60), unique=True, nullable=False)
    date_uploaded = db.Column(db.Date, default=datetime.date.today(), nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'))
    route_name = db.Column(db.String(60), nullable=False)
    analysis = db.relationship('Analysis', backref='vehicle', lazy='select', uselist=False)

    def __init__(self, filename, name, route_id, route_name):
        self.filename = filename
        self.name = name
        self.route_id = route_id
        self.route_name = route_name

    def __repr__(self):
        return f"Vehicle('{self.id}','{self.name}','{self.filename}','{self.date_uploaded}','{self.route_id}','{self.route_name}')"

class Parameters(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    cell_size = db.Column(db.Float, default=None, nullable=True)
    stop_min_time = db.Column(db.Integer, default=None, nullable=True)
    stop_max_time = db.Column(db.Integer, default=None, nullable=True)
    speeding_time_limit = db.Column(db.Integer, default=None, nullable=True)
    speeding_speed_limit = db.Column(db.Integer, default=None, nullable=True)
    liveness_time_limit = db.Column(db.Integer, default=None, nullable=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'))

    def __init__(self, name, route_id):
        self.name = name
        self.route_id = route_id

    def __repr__(self):
        return f"Parameters('{self.id}','{self.name}','{self.cell_size}','{self.stop_min_time}','{self.stop_max_time}','{self.speeding_time_limit}','{self.speeding_speed_limit}','{self.liveness_time_limit}')"

class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    distance = db.relationship('Distance', backref='analysis', uselist=False)
    loops = db.relationship('Loops', backref='analysis', uselist=False)
    speeding = db.relationship('Speeding', backref='analysis')
    stops = db.relationship('Stops', backref='analysis')
    total_liveness = db.Column(db.Integer, default=None, nullable=True)
    cell_size = db.Column(db.Float, default=None, nullable=True)
    stop_min_time = db.Column(db.Integer, default=None, nullable=True)
    stop_max_time = db.Column(db.Integer, default=None, nullable=True)
    speeding_time_limit = db.Column(db.Integer, default=None, nullable=True)
    speeding_speed_limit = db.Column(db.Integer, default=None, nullable=True)
    liveness_time_limit = db.Column(db.Integer, default=None, nullable=True)
    liveness_segments = db.relationship('Liveness', backref='analysis', lazy='select')

    def __init__(self, vehicle_id):
        self.vehicle_id = vehicle_id

    def __repr__(self):
        return f"Analysis('{self.id}', '{self.vehicle_id}', '{self.distance}', '{self.loops}', '{self.speeding}', '{self.stops}', '{self.total_liveness}', '{self.liveness_segments}')"

class Distance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    distance = db.Column(db.Float, default=None)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analysis.id'))

    def __init__(self, distance, analysis_id):
        self.distance = distance
        self.analysis_id = analysis_id

    def __repr__(self):
        return f"Distance('{self.id}', '{self.distance}', '{self.analysis_id}')"

class Loops(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loops = db.Column(db.Integer, default=None)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analysis.id'))

    def __init__(self, loops, analysis_id):
        self.loops = loops
        self.analysis_id = analysis_id

    def __repr__(self):
        return f"Loops('{self.id}', '{self.loops}', '{self.analysis_id}')"

class Speeding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    duration = db.Column(db.Integer, default=None)
    time1 = db.Column(db.DateTime, default=None)
    time2 = db.Column(db.DateTime, default=None)
    lat1 = db.Column(db.Float, default=None)
    long1 = db.Column(db.Float, default=None)
    lat2 = db.Column(db.Float, default=None)
    long2 = db.Column(db.Float, default=None)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analysis.id'))

    def __init__(self, duration, time1, time2, lat1, long1, lat2, long2, analysis_id):
        self.duration = duration
        self.time1 = time1
        self.time2 = time2
        self.lat1 = lat1
        self.long1 = long1
        self.lat2 = lat2
        self.long2 = long2
        self.analysis_id = analysis_id

    def __repr__(self):
        return f"Speeding('{self.id}', '{self.duration}', '{self.time1}', '{self.time2}', '{self.lat1}', '{self.long1}', '{self.lat2}', '{self.long2}', '{self.analysis_id}')"
    
class Stops(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    violation = db.Column(db.String(60), default=None)
    duration = db.Column(db.Integer, default=None)
    time1 = db.Column(db.DateTime, default=None)
    time2 = db.Column(db.DateTime, default=None)
    center_lat = db.Column(db.Float, default=None)
    center_long = db.Column(db.Float, default=None)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analysis.id'))

    def __init__(self, violation, duration, time1, time2, center_lat, center_long, analysis_id):
        self.violation = violation
        self.duration = duration
        self.time1 = time1
        self.time2 = time2
        self.center_lat = center_lat
        self.center_long = center_long
        self.analysis_id = analysis_id

    def __repr__(self):
        return f"Stops('{self.id}', '{self.violation}', '{self.duration}', '{self.time1}', '{self.time2}', '{self.center_lat}', '{self.center_long}', '{self.analysis_id}')"
    
class Liveness(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    liveness = db.Column(db.Integer, default=None)
    time1 = db.Column(db.DateTime, default=None)
    time2 = db.Column(db.DateTime, default=None)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analysis.id'))

    def __init__(self, liveness, time1, time2, analysis_id):
        self.liveness = liveness
        self.time1 = time1
        self.time2 = time2
        self.analysis_id = analysis_id

    def __repr__(self):
        return f"Liveness('{self.id}', '{self.liveness}', '{self.time1}', '{self.time2}', '{self.analysis_id}')"

class GPSCutoffTime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time = db.Column(db.Time, default=None)

    def __init__(self, time):
        self.time = time

    def __repr__(self):
        return f"GPSCutofTime('{self.id}', {self.time})"