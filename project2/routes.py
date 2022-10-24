import os
import jwt
import json
import numpy as np
import boto3
from requests import post
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, date
from flask import request, jsonify, send_file, current_app
from flask_cors import CORS
from project2 import app, db
from project2.models import User, Vehicle, Route, Parameters, Analysis, Distance, Loops, Speeding, Stops, Liveness, GPSCutoffTime
from project2.api import parse_gpx_file, compute_distance_travelled, compute_speed_violation, compute_stop_violation, compute_liveness, generate_grid_fence, generate_path, route_check, is_gpx_file, is_csv_file, create_geojson_feature, csv_to_gpx_stops, generate_corner_pts, parse_gpx_waypoints, Point, compute_vehicle_info

PER_PAGE = 8
QUERY_LIMIT = 7
CONFIG_FILE_PATH = 'project2/config.py'

AWS_ACCESS_KEY = app.config['AWS_ACCESS_KEY']
AWS_SECRET_KEY = app.config['AWS_SECRET_KEY']
REGION_NAME = app.config['AWS_REGION_NAME']
VEHICLE_BUCKET = app.config['AWS_VEHICLE_BUCKET']
ROUTE_BUCKET = app.config['AWS_ROUTE_BUCKET']

s3 = boto3.client('s3', 
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=REGION_NAME
)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    file_path = os.path.join(app.static_folder, path)
    if os.path.isfile(file_path):
        return send_file(file_path)
    index_path = os.path.join(app.static_folder, 'index.html')
    return send_file(index_path)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'X-Access-Token' in request.headers:
            token = request.headers['X-Access-Token']
        
        if not token:
            return jsonify({'error': 'Access Token is missing'}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            curr_user = User.query.filter_by(username=data['username']).first()
            if not curr_user:
                raise

        except:
            return jsonify({'error': 'Access Token is invalid'}), 401

        return f(curr_user, *args, **kwargs)

    return decorated

def admin_only(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if args[0].admin:
            return f(*args, **kwargs)

        return jsonify({'error': 'unauthorized user'}), 403

    return decorated

@app.route('/api/login', methods=['POST'])
def login():
    username = request.get_json()['username']
    password = request.get_json()['password']

    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'Incorrect credentials'}), 422

    if check_password_hash(user.password, password):
        token = jwt.encode(
            {
                'username': user.username, 
                'exp': datetime.utcnow() + timedelta(hours=4),
                'admin': user.admin
            },
            app.config['SECRET_KEY']
        )
        return jsonify({'token': token, 'username': user.username, 'admin': user.admin}), 200
    else:
        return jsonify({'error': 'Incorrect credentials'}), 422

@app.route('/api/route', methods=['POST'])
@token_required
@admin_only
def create_route(curr_user):
    name = request.get_json()['name']

    route = Route.query.filter_by(name=name).first()

    if not route:
        route = Route(name)
        db.session.add(route)
        db.session.commit()

        data = {
            'id': route.id,
            'route_name': route.name,
            'ref_filename': json.dumps(None),
            'stop_filename': json.dumps(None),
            'date_uploaded': json.dumps(None)
        }
        
        return jsonify(data), 201

    return jsonify({'error': 'route entry creation failed'}), 400

@app.route('/api/parameter', methods=['POST'])
@token_required
@admin_only
def create_parameters(curr_user):
    name = request.get_json()['name']

    parameters = Parameters.query.filter_by(name=name).first()
    route = Route.query.filter_by(name=name).first()
    if not parameters and route:
        parameters = Parameters(name, route.id)
        db.session.add(parameters)
        db.session.commit()

        data = {
            'id': parameters.id,
            'route_name': parameters.name,
            'cell_size': json.dumps(None),
            'stop_min_time': json.dumps(None),
            'stop_max_time': json.dumps(None),
            'speeding_time_limit': json.dumps(None),
            'speeding_speed_limit': json.dumps(None),
            'liveness_time_limit': json.dumps(None),
            'route_id': parameters.route_id
        }

        return jsonify(data), 201
    
    return jsonify({'error': 'parameters entry creation failed'}), 400

@app.route('/api/vehicle', methods=['POST'])
@token_required
@admin_only
def create_vehicle(curr_user):
    vehicle_name = request.form['vehicle_name']
    route_name = request.form['route_name']
    date = request.form['date']
    gpx_file = request.files['gpx_file']
    filename = gpx_file.filename
    date = datetime.strptime(date, "%Y-%m-%d").date()

    # check and add route, parameter if it doesn't exist
    route = Route.query.filter_by(name=route_name).first()
    if not route:
        route = Route(route_name)
        db.session.add(route)
        db.session.commit()

        parameters = Parameters(route_name, route.id)
        db.session.add(parameters)
        db.session.commit()

    # check if gpx_file is valid and add vehicle, analysis
    if gpx_file and is_gpx_file(filename):
        res = s3.put_object(Body=gpx_file.read(), Bucket=VEHICLE_BUCKET, Key=filename)

        vehicle = Vehicle(filename, vehicle_name, date, route.id, route_name)
        db.session.add(vehicle)
        db.session.commit()

        analysis = Analysis(vehicle.id)
        db.session.add(analysis)
        db.session.commit()

        gpx_file = s3.get_object(Bucket=VEHICLE_BUCKET, Key=vehicle.filename)['Body'].read()
        gps_data_vehicle = parse_gpx_file(gpx_file)

        # compute distance
        distance = compute_distance_travelled(gps_data_vehicle)
        distance_record = Distance(distance, vehicle.analysis.id)
        db.session.add(distance_record)
        db.session.commit()

        # check and analyze vehicle if ref_file, stop_file, and parameter data are available
        if route.parameters.cell_size and route.ref_filename:
            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.ref_filename)['Body'].read()
            gps_data_route = parse_gpx_file(gpx_file)

            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.stop_filename)['Body'].read()
            stops = parse_gpx_waypoints(gpx_file)

            compute_vehicle_info(vehicle, route, gps_data_vehicle, gps_data_route, stops)

        data = {
            'id': vehicle.id,
            'vehicle_name': vehicle.name,
            'filename': vehicle.filename,
            'date_uploaded': vehicle.date_uploaded,
            'route_id': vehicle.route_id,
            'route_name': vehicle.route_name
        }

        return jsonify(data), 201

    return jsonify({'error': 'vehicle entry creation failed'}), 400

@app.route('/api/route/<int:route_id>', methods=['PUT'])
@token_required
@admin_only
def update_route(curr_user, route_id):
    ref_file = request.files['ref_file']
    ref_filename = secure_filename(ref_file.filename)

    stop_file = request.files['stop_file']
    stop_filename = secure_filename(stop_file.filename).rsplit('.')[0] + '.gpx'

    if ref_file and is_gpx_file(ref_filename) and stop_file and is_csv_file(stop_file.filename):
        route = Route.query.get(route_id)

        route_with_ref_file = Route.query.filter_by(ref_filename=ref_filename).first()
        if not route_with_ref_file:
            res = s3.put_object(Body=ref_file.read(), Bucket=ROUTE_BUCKET, Key=ref_filename)

        route.ref_filename = ref_filename

        route_with_stop_file = Route.query.filter_by(stop_filename=stop_filename).first()
        if not route_with_stop_file:
            gpx = csv_to_gpx_stops(stop_file)
            res = s3.put_object(Body=gpx.to_xml(), Bucket=ROUTE_BUCKET, Key=stop_filename)

        route.stop_filename = stop_filename

        route.date_uploaded = date.today()
        
        db.session.commit()

        data = {
            'id': route.id,
            'route_name': route.name,
            'ref_filename': route.ref_filename,
            'stop_filename': route.stop_filename,
            'date_uploaded': route.date_uploaded.strftime("%b %d, %Y")
        }

        return jsonify(data), 201

    return jsonify({'error': 'route file upload failed'}), 400

@app.route('/api/parameter/<int:parameters_id>', methods=['PUT'])
@token_required
@admin_only
def update_parameters(curr_user, parameters_id):
    cell_size = request.get_json()['cell_size']
    stop_min_time = request.get_json()['stop_min_time']
    stop_max_time = request.get_json()['stop_max_time']
    speeding_time_limit = request.get_json()['speeding_time_limit']
    speeding_speed_limit = request.get_json()['speeding_speed_limit']
    liveness_time_limit = request.get_json()['liveness_time_limit']

    parameters = Parameters.query.get(parameters_id)

    if parameters:
        parameters.cell_size = cell_size
        parameters.stop_min_time = stop_min_time
        parameters.stop_max_time = stop_max_time
        parameters.speeding_time_limit = speeding_time_limit
        parameters.speeding_speed_limit = speeding_speed_limit
        parameters.liveness_time_limit = liveness_time_limit

        db.session.commit()

        data = {
            'id': parameters.id,
            'route_name': parameters.name,
            'cell_size': parameters.cell_size,
            'stop_min_time': parameters.stop_min_time,
            'stop_max_time': parameters.stop_max_time,
            'speeding_time_limit': parameters.speeding_time_limit,
            'speeding_speed_limit': parameters.speeding_speed_limit,
            'liveness_time_limit': parameters.liveness_time_limit,
            'route_id': parameters.route_id
        }

        return jsonify(data), 201

    return jsonify({'error': 'parameters entry failed to update'}), 400

@app.route('/api/route/<int:route_id>', methods=['GET'])
@token_required
@admin_only
def get_route(curr_user, route_id):
    route = Route.query.get(route_id)

    if route: 
        data = {
            'id': route.id,
            'route_name': route.name,
            'geojson': json.dumps(None),
            'polygon': json.dumps(None),
            'ref_filename': json.dumps(None),
            'stop_filename': json.dumps(None),
            'date_uploaded': route.date_uploaded.strftime("%b %d, %Y") if route.date_uploaded else json.dumps(None),
            'parameters_id': route.parameters.id if route.parameters else json.dumps(None)
        }

        if route.ref_filename:
            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.ref_filename)['Body'].read()
            gps_data = parse_gpx_file(gpx_file)
            data['geojson'] = create_geojson_feature(gps_data)
            data['ref_filename'] = route.ref_filename

        if route.stop_filename:
            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.stop_filename)['Body'].read()
            gps_data = parse_gpx_waypoints(gpx_file)
            data['polygon'] = create_geojson_feature(gps_data)
            data['stop_filename'] = route.stop_filename

        return jsonify(data), 200

    return jsonify({'error': 'route does not exist'}), 400

@app.route('/api/route/paged/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def get_paged_routes(curr_user, page_no):
    sort_by = request.get_json()['sortBy']
    sort_desc = request.get_json()['sortDesc']

    if sort_by == 'route_name':
        if sort_desc == False:
            paged_routes = Route.query.order_by(Route.name.asc())
        else:
            paged_routes = Route.query.order_by(Route.name.desc())
    elif sort_by == 'complete_files':
        if sort_desc == False:
            paged_routes = Route.query.order_by(Route.ref_filename.asc().nullsfirst())
        else:
            paged_routes = Route.query.order_by(Route.ref_filename.desc().nullslast())
    elif sort_by == 'date_uploaded':
        if sort_desc == False:
            paged_routes = Route.query.order_by(Route.date_uploaded.asc())
        else: 
            paged_routes = Route.query.order_by(Route.date_uploaded.desc())
    else:
        paged_routes = Route.query.order_by(Route.name.asc())

    paged_routes = paged_routes.paginate(page=page_no, per_page=PER_PAGE)

    if paged_routes:
        data = []

        for route in paged_routes.items:
            route_data = {
                'id': route.id,
                'route_name': route.name,
                'ref_filename': route.ref_filename if route.ref_filename else json.dumps(None),
                'stop_filename': route.stop_filename if route.stop_filename else json.dumps(None),
                'date_uploaded': route.date_uploaded.strftime("%b %d, %Y") if route.date_uploaded else json.dumps(None)
            }

            data.append(route_data)

        return jsonify({
            'routes': data, 
            'total_rows': paged_routes.total, 
            'per_page': paged_routes.per_page, 
            'curr_page': paged_routes.page
        }), 200
    
    return jsonify({'error': 'paged routes cannot be found'}), 400

@app.route('/api/vehicle/<int:vehicle_id>', methods=['GET'])
@token_required
def get_vehicle(curr_user, vehicle_id):
    vehicle = Vehicle.query.get(vehicle_id)

    if vehicle:            
        gpx_file = s3.get_object(Bucket=VEHICLE_BUCKET, Key=vehicle.filename)['Body'].read()
        gps_data = parse_gpx_file(gpx_file)
        geojson = create_geojson_feature(gps_data)

        data = {
            'id': vehicle.id,
            'vehicle_name': vehicle.name,
            'filename': vehicle.filename,
            'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y"),
            'route_id': vehicle.route_id,
            'route_name': vehicle.route_name,
            'analysis_id': vehicle.analysis.id if vehicle.analysis else json.dumps(None),
            'geojson': geojson
        }

        return jsonify(data), 200

    return jsonify({'error': 'vehicle does not exist'}), 400

@app.route('/api/vehicle/paged/<int:page_no>', methods=['POST'])
@token_required
def get_paged_vehicles(curr_user, page_no):
    sort_by = request.get_json()['sortBy']
    sort_desc = request.get_json()['sortDesc']

    if sort_by == 'vehicle_name':
        if sort_desc == False:
            paged_vehicles = Vehicle.query.order_by(Vehicle.name.asc())
        else:
            paged_vehicles = Vehicle.query.order_by(Vehicle.name.desc())
    elif sort_by == 'route_name':
        if sort_desc == False:
            paged_vehicles = Vehicle.query.order_by(Vehicle.route_name.asc())
        else:
            paged_vehicles = Vehicle.query.order_by(Vehicle.route_name.desc())
    elif sort_by == 'date_uploaded':
        if sort_desc == False:
            paged_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.asc())
        else:
            paged_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.desc())
    else:
        paged_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.desc())

    if curr_user.admin:
        paged_vehicles = paged_vehicles.paginate(page=page_no, per_page=PER_PAGE)
    else:
        paged_vehicles = paged_vehicles.filter(Vehicle.route_name.in_(curr_user.routes.split(', '))).paginate(page=page_no, per_page=PER_PAGE)

    if paged_vehicles:
        data = []

        for vehicle in paged_vehicles.items:
            vehicle_data = {
                'id': vehicle.id,
                'vehicle_name': vehicle.name,
                'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y"),
                'route_name': vehicle.route_name
            }

            data.append(vehicle_data)

        return jsonify({
            'vehicles': data, 
            'total_rows': paged_vehicles.total, 
            'per_page': paged_vehicles.per_page, 
            'curr_page': paged_vehicles.page
        }), 200
    
    return jsonify({'error': 'paged vehicles cannot be found'}), 400

@app.route('/api/parameter/<int:parameter_id>', methods=['GET'])
@token_required
@admin_only
def get_parameter(curr_user, parameter_id):
    parameter = Parameters.query.get(parameter_id)

    if parameter:
        route = Route.query.get(parameter.route_id)

        data = {
            'id': parameter.id,
            'route_name': parameter.name,
            'cell_size': parameter.cell_size if parameter.cell_size else json.dumps(None),
            'stop_min_time': parameter.stop_min_time if parameter.stop_min_time else json.dumps(None),
            'stop_max_time': parameter.stop_max_time if parameter.stop_max_time else json.dumps(None),
            'speeding_time_limit': parameter.speeding_time_limit if parameter.speeding_time_limit else json.dumps(None),
            'speeding_speed_limit': parameter.speeding_speed_limit if parameter.speeding_speed_limit else json.dumps(None),
            'liveness_time_limit': parameter.liveness_time_limit if parameter.liveness_time_limit else json.dumps(None),
            'geojson': json.dumps(None),
            'polygon': json.dumps(None),
            'ref_filename': json.dumps(None),
            'stop_filename': json.dumps(None),
            'route_id': parameter.route_id
        }

        if route.ref_filename:
            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.ref_filename)['Body'].read()
            gps_data = parse_gpx_file(gpx_file)
            data['geojson'] = create_geojson_feature(gps_data)
            data['ref_filename'] = route.ref_filename

        if route.stop_filename:
            gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.stop_filename)['Body'].read()
            gps_data = parse_gpx_waypoints(gpx_file)
            data['polygon'] = create_geojson_feature(gps_data)
            data['stop_filename'] = route.stop_filename

        return jsonify(data), 200

    return jsonify({'error': 'parameter does not exist'}), 400

@app.route('/api/parameter/paged/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def get_paged_parameters(curr_user, page_no):
    sort_by = request.get_json()['sortBy']
    sort_desc = request.get_json()['sortDesc']

    if sort_by == 'route_name':
        if sort_desc == False:
            paged_parameters = Parameters.query.order_by(Parameters.name.asc())
        else:
            paged_parameters = Parameters.query.order_by(Parameters.name.desc())
    elif sort_by == 'cell_size':
        if sort_desc == False:
            paged_parameters = Parameters.query.order_by(Parameters.cell_size.asc().nullsfirst())
        else:
            paged_parameters = Parameters.query.order_by(Parameters.cell_size.desc().nullslast())
    else:
        paged_parameters = Parameters.query.order_by(Parameters.name.asc())

    paged_parameters = paged_parameters.paginate(page=page_no, per_page=PER_PAGE)

    if paged_parameters:
        data = []

        for parameter in paged_parameters.items:
            parameter_data = {
                'id': parameter.id,
                'route_name': parameter.name,
                'cell_size': parameter.cell_size if parameter.cell_size else json.dumps(None),
                'stop_min_time': parameter.stop_min_time if parameter.stop_min_time else json.dumps(None),
                'stop_max_time': parameter.stop_max_time if parameter.stop_max_time else json.dumps(None),
                'speeding_time_limit': parameter.speeding_time_limit if parameter.speeding_time_limit else json.dumps(None),
                'speeding_speed_limit': parameter.speeding_speed_limit if parameter.speeding_speed_limit else json.dumps(None),
                'liveness_time_limit': parameter.liveness_time_limit if parameter.liveness_time_limit else json.dumps(None)
            }

            data.append(parameter_data)
        
        return jsonify({
            'parameters': data,
            'total_rows': paged_parameters.total,
            'per_page': paged_parameters.per_page,
            'curr_page': paged_parameters.page
        })
    
    return jsonify({'error': 'paged parameters cannot be found'}), 400

@app.route('/api/vehicle/search/<int:page_no>', methods=['POST'])
@token_required
def search_vehicles(curr_user, page_no):
    vehicle_name = request.get_json()['vehicle_name']
    route_name = request.get_json()['route_name']
    date = request.get_json()['date']
    sort_by = request.get_json()['sortBy']
    sort_desc = request.get_json()['sortDesc']

    search_vehicles = []
    route = None

    if route_name:
        route = Route.query.filter_by(name=route_name).first()

        if route == None:
            return jsonify({
                'vehicles': [], 
                'total_rows': 0, 
                'per_page': PER_PAGE, 
                'curr_page': 1
            }), 200

    if sort_by == 'vehicle_name':
        if sort_desc == False:
            search_vehicles = Vehicle.query.order_by(Vehicle.name.asc())
        else:
            search_vehicles = Vehicle.query.order_by(Vehicle.name.desc())
    elif sort_by == 'route_name':
        if sort_desc == False:
            search_vehicles = Vehicle.query.order_by(Vehicle.route_name.asc())
        else:
            search_vehicles = Vehicle.query.order_by(Vehicle.route_name.desc())
    elif sort_by == 'date_uploaded':
        if sort_desc == False:
            search_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.asc())
        else:
            search_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.desc())
    else:
        search_vehicles = Vehicle.query.order_by(Vehicle.date_uploaded.desc())

    columns = {
        "name": vehicle_name,
        "route_id" : route.id if route else "", 
        "date_uploaded": date
    }

    filters = {k:v for k,v in columns.items() if v != ""}
    search_vehicles = search_vehicles.filter_by(**filters).paginate(page=page_no, per_page=PER_PAGE)

    if search_vehicles:
        data = []

        for vehicle in search_vehicles.items:
            if not route_name:
                route = Route.query.filter_by(id=vehicle.route_id).first()

            vehicle_data = {
                'id': vehicle.id,
                'vehicle_name': vehicle.name,
                'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y"),
                'route_name': route.name
            }

            data.append(vehicle_data)

        return jsonify({
            'vehicles': data, 
            'total_rows': search_vehicles.total, 
            'per_page': search_vehicles.per_page, 
            'curr_page': search_vehicles.page
        }), 200

    return jsonify({'error': 'searched vehicles cannot be found'}), 400

@app.route('/api/route/search/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def search_routes(curr_user, page_no):
    route_name = request.get_json()['route_name']

    route = Route.query.filter_by(name=route_name).first()
    
    if route:
        data = {
            'id': route.id,
            'route_name': route.name,
            'ref_filename': route.ref_filename if route.ref_filename else json.dumps(None),
            'stop_filename': route.stop_filename if route.stop_filename else json.dumps(None),
            'date_uploaded': route.date_uploaded.strftime("%b %d, %Y") if route.date_uploaded else json.dumps(None)
        }

        return jsonify({
            'routes': [data],
            'total_rows': 0,
            'per_page': PER_PAGE,
            'curr_page': 1
        }), 200

    elif route == None:
        return jsonify({
            'routes': [], 
            'total_rows': 0, 
            'per_page': PER_PAGE, 
            'curr_page': 1
        }), 200

    return jsonify({'error': 'searched routes cannot be found'}), 400

@app.route('/api/parameter/search/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def search_parameters(curr_user, page_no):
    parameter_name = request.get_json()['parameter_name']

    parameter = Parameters.query.filter_by(name=parameter_name).first()

    if parameter:
        data = {
            'id': parameter.id,
            'route_name': parameter.name,
            'cell_size': parameter.cell_size if parameter.cell_size else json.dumps(None),
            'stop_min_time': parameter.stop_min_time if parameter.stop_min_time else json.dumps(None),
            'stop_max_time': parameter.stop_max_time if parameter.stop_max_time else json.dumps(None),
            'speeding_time_limit': parameter.speeding_time_limit if parameter.speeding_time_limit else json.dumps(None),
            'speeding_speed_limit': parameter.speeding_speed_limit if parameter.speeding_speed_limit else json.dumps(None),
            'liveness_time_limit': parameter.liveness_time_limit if parameter.liveness_time_limit else json.dumps(None)
        }
        
        return jsonify({
            'parameters': [data],
            'total_rows': 0,
            'per_page': PER_PAGE,
            'curr_page': 1
        })
    
    elif parameter == None:
        return jsonify({
            'parameters': [],
            'total_rows': 0,
            'per_page': PER_PAGE,
            'curr_page': 1
        })
    
    return jsonify({'error': 'paged parameters cannot be found'}), 400

@app.route('/api/auto-complete/vehicle', methods=['POST'])
@token_required
def auto_complete_vehicle(curr_user):
    vehicle_name = request.get_json()['vehicle_name']

    if curr_user.admin:
        search_vehicles = Vehicle.query.filter(Vehicle.name.ilike(f"%{vehicle_name}%")).with_entities(Vehicle.name).distinct().limit(QUERY_LIMIT).all()
    else:
        search_vehicles = Vehicle.query.filter(Vehicle.route_name.in_(curr_user.routes.split(', '))).filter(Vehicle.name.ilike(f"%{vehicle_name}%")).with_entities(Vehicle.name).distinct().limit(QUERY_LIMIT).all()

    if len(search_vehicles):
        search_vehicles = np.squeeze(np.array(search_vehicles), axis=1)
    
        return jsonify({
            'vehicles': search_vehicles.tolist()
        }), 200

    elif len(search_vehicles) == 0:
        return jsonify({
            'vehicles': []
        }), 200

    return jsonify({'error': 'searched vehicles cannot be found'}), 400

@app.route('/api/auto-complete/route', methods=['POST'])
@token_required
def auto_complete_route(curr_user):
    route_name = request.get_json()['route_name']

    if curr_user.admin:
        search_routes = Route.query.filter(Route.name.ilike(f"%{route_name}%")).limit(QUERY_LIMIT).all()
    else:
        search_routes = Route.query.filter(Route.name.in_(curr_user.routes.split(', '))).filter(Route.name.ilike(f"%{route_name}%")).limit(QUERY_LIMIT).all()

    if search_routes:
        data = []

        for route in search_routes:
            data.append(route.name)

        return jsonify({
            'routes': data
        }), 200

    elif len(search_routes) == 0:
        return jsonify({
            'routes': []
        }), 200

    return jsonify({'error': 'searched routes cannot be found'}), 400

@app.route('/api/vehicle/analyze/distance/<int:id>', methods=['GET'])
@token_required
def get_distance_travelled(curr_user, id):
    distance = Distance.query.filter_by(analysis_id=id).first()

    if distance:
        data = {
            'distance': distance.distance
        }

        return jsonify(data), 200

    return jsonify({'error': 'distance does not exist'}), 400

@app.route('/api/vehicle/analyze/loop/<int:id>', methods=['GET'])
@token_required
def get_loops(curr_user, id):
    loops = Loops.query.filter_by(analysis_id=id).first()

    if loops:
        data = {
            'loops': loops.loops
        }

        return jsonify(data), 200

    return jsonify({'error': 'loops does not exist'}), 400

@app.route('/api/vehicle/analyze/speeding/<int:id>', methods=['GET'])
@token_required
def get_speeding_violations(curr_user, id):
    violations = Speeding.query.filter_by(analysis_id=id).all()

    if violations:
        vehicle = Vehicle.query.get(id)

        data = {
            'time_limit': vehicle.analysis.speeding_time_limit,
            'speed_limit': vehicle.analysis.speeding_speed_limit,
            'violations': []
        }

        for violation in violations:
            temp = {
                'duration': violation.duration,
                'lat1': violation.lat1,
                'long1': violation.long1,
                'lat2': violation.lat2,
                'long2': violation.long2,
                'time1': violation.time1.strftime("%I:%M %p, %m/%d/%Y"),
                'time2': violation.time2.strftime("%I:%M %p, %m/%d/%Y"),
            }
            data['violations'].append(temp)

        return jsonify(data), 200

    return jsonify({'error': 'speeding does not exist'}), 400

@app.route('/api/vehicle/analyze/stop/<int:id>', methods=['GET'])
@token_required
def get_stop_violations(curr_user, id):
    violations = Stops.query.filter_by(analysis_id=id).all()

    if violations:
        vehicle = Vehicle.query.get(id)

        data = {
            'min_time': vehicle.analysis.stop_min_time,
            'max_time': vehicle.analysis.stop_max_time,
            'violations': []
        }

        for violation in violations:
            temp = {
                'duration': violation.duration,
                'violation': violation.violation,
                'time1': violation.time1.strftime("%I:%M %p, %m/%d/%Y"),
                'time2': violation.time2.strftime("%I:%M %p, %m/%d/%Y"),
                'center_lat': violation.center_lat,
                'center_long': violation.center_long,
            }

            data['violations'].append(temp)

        return jsonify(data), 200

    return jsonify({'error': 'stops does not exist'}), 400

@app.route('/api/vehicle/analyze/liveness/<int:id>', methods=['GET'])
@token_required
def get_liveness(curr_user, id):
    liveness_segments = Liveness.query.filter_by(analysis_id=id).all()

    if liveness_segments:
        vehicle = Vehicle.query.get(id)

        data = {
            'total_liveness': vehicle.analysis.total_liveness,
            'time_limit': vehicle.analysis.liveness_time_limit,
            'segments': []
        }

        for segment in liveness_segments:
            temp = {
                'liveness': segment.liveness,
                'time1': segment.time1.strftime("%I:%M %p, %m/%d/%Y"),
                'time2': segment.time2.strftime("%I:%M %p, %m/%d/%Y")
            }

            data['segments'].append(temp)

        return jsonify(data), 200

    return jsonify({'error': 'liveness does not exist'}), 400

@app.route('/api/admin/cutofftime', methods=['GET'])
@token_required
@admin_only
def get_cutofftime(curr_user):
    cut_off_time = GPSCutoffTime.query.first()

    if cut_off_time:
        data = {
            'cut_off_time': cut_off_time.time.strftime("%H:%M")
        }

        return jsonify(data), 200

    return jsonify({'error': 'cut off time not set'}), 400

@app.route('/api/admin/cutofftime', methods=['PUT'])
@token_required
@admin_only
def set_cutofftime(curr_user):
    time = request.get_json()['cut_off_time']
    cut_off_time = GPSCutoffTime.query.first()

    time = datetime.strptime(time, '%H:%M:%S').time()

    if cut_off_time:
        cut_off_time.time = time
    else:
        cut_off_time = GPSCutoffTime(time)
        db.session.add(cut_off_time)

    db.session.commit()

    data = {
        'cut_off_time': cut_off_time.time.strftime('%H:%M')
    }

    return jsonify(data), 200

@app.route('/api/admin/northboundkey', methods=['GET'])
@token_required
@admin_only
def get_northbound_key(curr_user):
    config_file = open(CONFIG_FILE_PATH, 'r')
    lines = config_file.readlines()

    northbound_url = ''
    northbound_username = ''
    northbound_password = ''

    for line in lines:
        if 'NORTHBOUND_URL' in line[1:15]:
            northbound_url = line[19:-2]
        elif 'NORTHBOUND_USERNAME' in line[1:21]:
            northbound_username = line[24:-2]
        elif 'NORTHBOUND_PASSWORD' in line[1:21]:
            northbound_password = line[24:-2]

    config_file.close()

    return jsonify({'northbound_url': northbound_url, 'northbound_username': northbound_username, 'northbound_password': northbound_password}), 200

@app.route('/api/admin/northboundkey', methods=['PUT'])
@token_required
@admin_only
def set_northbound_key(curr_user):
    new_url = request.get_json()['url']
    new_username = request.get_json()['username']
    new_password = request.get_json()['password']

    file = open(CONFIG_FILE_PATH, 'r')
    lines = file.readlines()
    file.close()

    config_file = open(CONFIG_FILE_PATH, 'w')

    for line in lines:
        if 'NORTHBOUND_URL' in line[1:15]:
            new_line = line[0:19] + new_url + line[-2:]
            config_file.write(new_line)
        elif 'NORTHBOUND_USERNAME' in line[1:21]:
            new_line = line[0:24] + new_username + line[-2:]
            config_file.write(new_line)
        elif 'NORTHBOUND_PASSWORD' in line[1:21]:
            new_line = line[0:24] + new_password + line[-2:]
            config_file.write(new_line)
        else:
            config_file.write(line)

    config_file.close()

    return jsonify({'new_url': new_url, 'new_username': new_username, 'new_password': new_password}), 200

@app.route('/api/northbound/token', methods=['GET'])
@token_required
@admin_only
def northbound_connect(curr_user):
    config_file = open(CONFIG_FILE_PATH, 'r')
    lines = config_file.readlines()

    northbound_url = ''
    northbound_username = ''
    northbound_password = ''

    for line in lines:
        if 'NORTHBOUND_URL' in line[1:15]:
            northbound_url = line[19:-2]
        elif 'NORTHBOUND_USERNAME' in line[1:21]:
            northbound_username = line[24:-2]
        elif 'NORTHBOUND_PASSWORD' in line[1:21]:
            northbound_password = line[24:-2]

    access_token = post(northbound_url + '/login', auth=(northbound_username, northbound_password)).json()['access_token']

    if access_token:
        return jsonify({'northbound_url': northbound_url, 'access_token': access_token}), 200

    return jsonify({'error': 'Cannot login to Northbound API'})

@app.route('/api/route/refresh', methods=['PUT'])
@token_required
@admin_only
def route_refresh(curr_user):
    list_of_routes = request.get_json()['routes']
    
    for route in list_of_routes:
        stored_route = Route.query.filter_by(name=route['route_id']).first()

        if not stored_route:
            new_route = Route(route['route_id'])

            db.session.add(new_route)
            db.session.commit()

            new_parameter = Parameters(route['route_id'], new_route.id)
            db.session.add(new_parameter)
            db.session.commit()

    paged_routes = Route.query.order_by(Route.name.asc()).paginate(page=1, per_page=PER_PAGE)

    if paged_routes:
        data = []

        for route in paged_routes.items:
            route_data = {
                'id': route.id,
                'route_name': route.name,
                'ref_filename': route.ref_filename if route.ref_filename else json.dumps(None),
                'stop_filename': route.stop_filename if route.stop_filename else json.dumps(None),
                'date_uploaded': route.date_uploaded.strftime("%b %d, %Y") if route.date_uploaded else json.dumps(None)
            }

            data.append(route_data)

        return jsonify({
            'routes': data,
            'total_rows': paged_routes.total,
            'per_page': paged_routes.per_page,
            'curr_page': paged_routes.page
        }), 200

    return jsonify({'error': 'paged routes cannot be found'}), 200

@app.route('/api/parameter/refresh', methods=['PUT'])
@token_required
@admin_only
def parameter_refresh(curr_user):
    list_of_routes = request.get_json()['routes']

    for route in list_of_routes:
        stored_route = Route.query.filter_by(name=route['route_id']).first()

        if not stored_route:
            new_route = Route(route['route_id'])

            db.session.add(new_route)
            db.session.commit()

            new_parameter = Parameters(route['route_id'], new_route.id)
            db.session.add(new_parameter)
            db.session.commit()

    paged_parameters = Parameters.query.order_by(Parameters.name.asc()).paginate(page=1, per_page=PER_PAGE)

    if paged_parameters:
        data = []

        for parameter in paged_parameters.items:
            route = Route.query.get(parameter.route_id)
            
            parameter_data = {
                'id': parameter.id,
                'route_name': route.name,
                'cell_size': parameter.cell_size if parameter.cell_size else json.dumps(None),
                'stop_min_time': parameter.stop_min_time if parameter.stop_min_time else json.dumps(None),
                'stop_max_time': parameter.stop_max_time if parameter.stop_max_time else json.dumps(None),
                'speeding_time_limit': parameter.speeding_time_limit if parameter.speeding_time_limit else json.dumps(None),
                'speeding_speed_limit': parameter.speeding_speed_limit if parameter.speeding_speed_limit else json.dumps(None),
                'liveness_time_limit': parameter.liveness_time_limit if parameter.liveness_time_limit else json.dumps(None)
            }

            data.append(parameter_data)
        
        return jsonify({
            'parameters': data,
            'total_rows': paged_parameters.total,
            'per_page': paged_parameters.per_page,
            'curr_page': paged_parameters.page
        }), 200
    
    return jsonify({'error': 'paged parameters cannot be found'}), 400

@app.route('/api/admin/account', methods=['POST'])
@token_required
@admin_only
def create_account(curr_user):
    username = request.get_json()['username']
    password = request.get_json()['password']
    routes = request.get_json()['routes']

    account = User.query.filter_by(username=username).first()

    if not account:
        account = User(username, password, False, routes)
        db.session.add(account)
        db.session.commit()

        paged_accounts = User.query.filter_by(admin=False).paginate(page=1, per_page=PER_PAGE)
        data = []

        for account in paged_accounts.items:
            account_data = {
                'id': account.id,
                'username': account.username,
                'routes': account.routes.split(', ')
            }

            data.append(account_data)

        return jsonify({
            'accounts': data,
            'total_rows': paged_accounts.total,
            'per_page': paged_accounts.per_page,
            'curr_page': paged_accounts.page
        }), 200

    return jsonify({'error': 'user entry creation failed'}), 400

@app.route('/api/admin/account/paged/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def get_paged_accounts(curr_user, page_no):
    sort_by = request.get_json()['sortBy']
    sort_desc = request.get_json()['sortDesc']

    if sort_by == 'username':
        if sort_desc == False:
            paged_accounts = User.query.order_by(User.username.asc())
        else:
            paged_accounts = User.query.order_by(User.username.desc())
    else:
        paged_accounts = User.query.order_by(User.username.asc())    

    paged_accounts = paged_accounts.filter_by(admin=False).paginate(page=page_no, per_page=PER_PAGE)

    if paged_accounts:
        data = []

        for account in paged_accounts.items:
            account_data = {
                'id': account.id,
                'username': account.username,
                'routes': account.routes.split(', ')
            }

            data.append(account_data)

        return jsonify({
            'accounts': data,
            'total_rows': paged_accounts.total,
            'per_page': paged_accounts.per_page,
            'curr_page': paged_accounts.page
        }), 200
    
    return jsonify({'error': 'paged accounts cannot be found'}), 400

@app.route('/api/admin/account/<int:account_id>', methods=['PUT'])
@token_required
@admin_only
def update_account(curr_user, account_id):
    routes = request.get_json()['routes']

    account = User.query.get(account_id)

    if account:
        account.routes = routes

        db.session.commit()

        paged_accounts = User.query.filter_by(admin=False).paginate(page=1, per_page=PER_PAGE)
        data = []

        for account in paged_accounts.items:
            account_data = {
                'id': account.id,
                'username': account.username,
                'routes': account.routes.split(', ')
            }

            data.append(account_data)

        return jsonify({
            'accounts': data,
            'total_rows': paged_accounts.total,
            'per_page': paged_accounts.per_page,
            'curr_page': paged_accounts.page
        }), 200

    return jsonify({'error': 'user does not exist'}), 400

@app.route('/api/admin/account/search/<int:page_no>', methods=['POST'])
@token_required
@admin_only
def search_account(curr_user, page_no):
    username = request.get_json()['username']

    account = User.query.filter_by(username=username).first()

    if account:
        data = {
            'id': account.id,
            'username': account.username,
            'routes': account.routes.split(', ')
        }

        return jsonify({
            'accounts': [data],
            'total_rows': 0,
            'per_page': PER_PAGE,
            'curr_page': 1
        }), 200

    elif route == None:
        return jsonify({
            'accounts': [], 
            'total_rows': 0, 
            'per_page': PER_PAGE, 
            'curr_page': 1
        }), 200

    return jsonify({'error': 'searched accounts cannot be found'}), 400

@app.route('/api/auto-complete/account', methods=['POST'])
@token_required
@admin_only
def auto_complete_account(curr_user):
    username= request.get_json()['username']

    search_accounts = User.query.filter_by(admin=False).filter(User.username.ilike(f"%{username}%")).with_entities(User.username).distinct().limit(QUERY_LIMIT).all()

    if len(search_accounts):
        search_accounts = np.squeeze(np.array(search_accounts), axis=1)

        return jsonify({
            'accounts': search_accounts.tolist()
        }), 200

    elif len(search_accounts) == 0:
        return jsonify({
            'accounts': []
        }), 200

    return jsonify({'error': 'searched accounts cannot be found'}), 400