import os
import jwt
import json
import numpy as np
import boto3
from requests import post
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from flask import request, jsonify, send_file, current_app
from flask_cors import CORS
from project2 import app, db
from project2.models import User, Vehicle, Route, Parameters, Analysis, Distance, Loops, Speeding, Stops, Liveness, GPSCutoffTime
from project2.api import parse_gpx_file, compute_distance_travelled, compute_speed_violation, compute_stop_violation, compute_liveness, generate_grid_fence, generate_path, route_check, is_gpx_file, is_csv_file, create_geojson_feature, csv_to_gpx_stops, generate_corner_pts, parse_gpx_waypoints, Point, compute_loops

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

@app.route('/api/route', methods=['POST'])
def create_route():
    name = request.get_json()['name']

    route = Route.query.filter_by(name=name).first()

    if not route:
        route = Route(name)
        db.session.add(route)
        db.session.commit()

        data = {
            'id': route.id,
            'name': route.name,
            'ref_filename': json.dumps(None),
            'stop_filename': json.dumps(None),
            'date_uploaded': json.dumps(None)
        }
        
        return jsonify(data), 201

    return jsonify({'error': 'route entry creation failed'}), 400

@app.route('/api/parameter', methods=['POST'])
def create_parameters():
    name = request.get_json()['name']

    parameters = Parameters.query.filter_by(name=name).first()
    route = Route.query.filter_by(name=name).first()
    if not parameters and route:
        parameters = Parameters(name, route.id)
        db.session.add(parameters)
        db.session.commit()

        data = {
            'id': parameters.id,
            'name': parameters.name,
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
def create_vehicle():
    vehicle_name = request.form['vehicle_name']
    route_name = request.form['route_name']
    gpx_file = request.files['gpx_file']
    filename = gpx_file.filename

    route = Route.query.filter_by(name=route_name).first()

    if gpx_file and route and is_gpx_file(filename):
        gpx_file.save(os.path.join(app.config['GPX_VEHICLE_FOLDER'], filename))

        vehicle = Vehicle(filename, vehicle_name, route.id)
        db.session.add(vehicle)
        db.session.commit()

        data = {
            'id': vehicle.id,
            'name': vehicle.name,
            'filename': vehicle.filename,
            'date_uploaded': vehicle.date_uploaded,
            'route_id': vehicle.route_id
        }

        return jsonify(data), 201

    return jsonify({'error': 'vehicle entry creation failed'}), 400

@app.route('/api/route/<int:route_id>', methods=['PUT'])
def update_route(route_id):
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
            'name': route.name,
            'ref_filename': route.ref_filename,
            'stop_filename': route.stop_filename,
            'date_uploaded': route.date_uploaded.strftime("%b %d, %Y")
        }

        return jsonify(data), 201

    return jsonify({'error': 'route file upload failed'}), 400

@app.route('/api/parameter/<int:parameters_id>', methods=['PUT'])
def update_parameters(parameters_id):
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
            'name': parameters.name,
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
def get_route(route_id):
    route = Route.query.get(route_id)

    if route: 
        data = {
            'id': route.id,
            'name': route.name,
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

@app.route('/api/route/paged/<int:page_no>', methods=['GET'])
def get_paged_routes(page_no):
    paged_routes = Route.query.paginate(page=page_no, per_page=PER_PAGE)

    if paged_routes:
        data = []

        for route in paged_routes.items:
            route_data = {
                'id': route.id,
                'name': route.name,
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
def get_vehicle(vehicle_id):
    vehicle = Vehicle.query.get(vehicle_id)

    if vehicle:            
        gpx_file = s3.get_object(Bucket=VEHICLE_BUCKET, Key=vehicle.filename)['Body'].read()
        gps_data = parse_gpx_file(gpx_file)
        geojson = create_geojson_feature(gps_data)

        data = {
            'id': vehicle.id,
            'name': vehicle.name,
            'filename': vehicle.filename,
            'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y"),
            'route_id': vehicle.route_id,
            'analysis_id': vehicle.analysis.id if vehicle.analysis else json.dumps(None),
            'geojson': geojson
        }

        return jsonify(data), 200

    return jsonify({'error': 'vehicle does not exist'}), 400

@app.route('/api/vehicle/paged/<int:page_no>', methods=['GET'])
def get_paged_vehicles(page_no):
    paged_vehicles = Vehicle.query.paginate(page=page_no, per_page=PER_PAGE)

    if paged_vehicles:
        data = []

        for vehicle in paged_vehicles.items:
            route = Route.query.get(vehicle.route_id)

            vehicle_data = {
                'id': vehicle.id,
                'name': vehicle.name,
                'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y"),
                'route_name': route.name
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
def get_parameter(parameter_id):
    parameter = Parameters.query.get(parameter_id)

    if parameter:
        route = Route.query.get(parameter.route_id)

        data = {
            'id': parameter.id,
            'name': parameter.name,
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

@app.route('/api/parameter/paged/<int:page_no>', methods=['GET'])
def get_paged_parameters(page_no):
    paged_parameters = Parameters.query.paginate(page=page_no, per_page=PER_PAGE)

    if paged_parameters:
        data = []

        for parameter in paged_parameters.items:
            parameter_data = {
                'id': parameter.id,
                'name': parameter.name,
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
def search_vehicles(page_no):
    vehicle_name = request.get_json()['vehicle_name']
    route_name = request.get_json()['route_name']
    date = request.get_json()['date']

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

    columns = {
        "name": vehicle_name,
        "route_id" : route.id if route else "", 
        "date_uploaded": date
    }

    filters = {k:v for k,v in columns.items() if v != ""}
    search_vehicles = Vehicle.query.filter_by(**filters).paginate(page=page_no, per_page=PER_PAGE)

    if search_vehicles:
        data = []

        for vehicle in search_vehicles.items:
            if not route_name:
                route = Route.query.filter_by(id=vehicle.route_id).first()

            vehicle_data = {
                'id': vehicle.id,
                'name': vehicle.name,
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
def search_routes(page_no):
    route_name = request.get_json()['route_name']

    route = Route.query.filter_by(name=route_name).first()
    
    if route:
        data = {
            'id': route.id,
            'name': route.name,
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
def search_parameters(page_no):
    parameter_name = request.get_json()['parameter_name']

    parameter = Parameters.query.filter_by(name=parameter_name).first()

    if parameter:
        data = {
            'id': parameter.id,
            'name': parameter.name,
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
    
    elif route == None:
        return jsonify({
            'parameters': [],
            'total_rows': 0,
            'per_page': PER_PAGE,
            'curr_page': 1
        })
    
    return jsonify({'error': 'paged parameters cannot be found'}), 400

@app.route('/api/auto-complete/vehicle', methods=['POST'])
def auto_complete_vehicle():
    vehicle_name = request.get_json()['vehicle_name']

    search_vehicles = Vehicle.query.filter(Vehicle.name.ilike(f"%{vehicle_name}%")).with_entities(Vehicle.name).distinct().limit(QUERY_LIMIT).all()

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
def auto_complete_route():
    route_name = request.get_json()['route_name']

    search_routes = Route.query.filter(Route.name.ilike(f"%{route_name}%")).limit(QUERY_LIMIT).all()

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

@app.route('/api/vehicle/analyze/<int:vehicle_id>', methods=['GET'])
def analyze_vehicle(vehicle_id):
    # query tables from db
    vehicle = Vehicle.query.get(vehicle_id)
    route = Route.query.get(vehicle.route_id)

    if vehicle.analysis == None:
        analysis = Analysis(vehicle.id)

        db.session.add(analysis)
        db.session.commit()        

    # read gpx files from file system
    gpx_file = s3.get_object(Bucket=VEHICLE_BUCKET, Key=vehicle.filename)['Body'].read()
    gps_data_vehicle = parse_gpx_file(gpx_file)

    gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.ref_filename)['Body'].read()
    gps_data_route = parse_gpx_file(gpx_file)

    gpx_file = s3.get_object(Bucket=ROUTE_BUCKET, Key=route.stop_filename)['Body'].read()
    stops = parse_gpx_waypoints(gpx_file)

    # compute distance
    distance = compute_distance_travelled(gps_data_vehicle)

    if vehicle.analysis.distance:
        vehicle.analysis.distance.distance = distance
    else:
        distance_record = Distance(distance, vehicle.analysis.id)
        db.session.add(distance_record)

    db.session.commit()

    # compute loops
    point1, point2 = generate_corner_pts(gps_data_vehicle, route.parameters.cell_size)
    grid_fence = generate_grid_fence(point1, point2, route.parameters.cell_size)
    vehicle_path = generate_path(gps_data_vehicle, grid_fence)
    route_path = generate_path(gps_data_route, grid_fence)
    loops = compute_loops(route_path, vehicle_path, grid_fence)

    if vehicle.analysis.loops:
        vehicle.analysis.loops.loops = loops
    else:
        loops_record = Loops(loops, vehicle.analysis.id)
        db.session.add(loops_record)

    db.session.commit()

    # compute speeding
    speeding_violations = compute_speed_violation(gps_data_vehicle, "Explicit", route.parameters.speeding_speed_limit, route.parameters.speeding_time_limit)

    if vehicle.analysis.speeding:
        Speeding.query.filter_by(analysis_id=vehicle.analysis.id).delete()
    
    for violation in speeding_violations:
        speeding = Speeding(violation['duration'], violation['time1'], violation['time2'], violation['lat1'], violation['long1'], violation['lat2'], violation['long2'], vehicle.analysis.id)
        db.session.add(speeding)
        
    db.session.commit()

    # compute stop
    stop_violations = compute_stop_violation(stops, gps_data_vehicle, route.parameters.stop_min_time, route.parameters.stop_max_time)

    if vehicle.analysis.stops:
        Stops.query.filter_by(analysis_id=vehicle.analysis.id).delete()

    for violation in stop_violations:
        stop = Stops(violation['violation'], violation['duration'], violation['time1'], violation['time2'], violation['center_lat'], violation['center_long'], vehicle.analysis.id)
        db.session.add(stop)

    db.session.commit()

    # compute liveness
    liveness = compute_liveness(gps_data_vehicle, route.parameters.liveness_time_limit)

    if vehicle.analysis.liveness_segments:
        Liveness.query.filter_by(analysis_id=vehicle.analysis.id).delete()

    vehicle.analysis.total_liveness = liveness['total_liveness']
    for segment in liveness['segments']:
        liveness_segment = Liveness(segment['liveness'], segment['time1'], segment['time2'], vehicle.analysis.id)
        db.session.add(liveness_segment)

    db.session.commit()

    return jsonify({'msg': 'success'}), 200

@app.route('/api/vehicle/analyze/distance/<int:id>', methods=['GET'])
def get_distance_travelled(id):
    distance = Distance.query.filter_by(analysis_id=id).first()

    if distance:
        data = {
            'distance': distance.distance
        }

        return jsonify(data), 200

    return jsonify({'error': 'distance does not exist'}), 400

@app.route('/api/vehicle/analyze/loop/<int:id>', methods=['GET'])
def get_loops(id):
    loops = Loops.query.filter_by(analysis_id=id).first()

    if loops:
        data = {
            'loops': loops.loops
        }

        return jsonify(data), 200

    return jsonify({'error': 'loops does not exist'}), 400

@app.route('/api/vehicle/analyze/speeding/<int:id>', methods=['GET'])
def get_speeding_violations(id):
    violations = Speeding.query.filter_by(analysis_id=id).all()

    if violations:
        analysis = Analysis.query.get(id)
        vehicle = Vehicle.query.get(analysis.vehicle_id)
        route = Route.query.get(vehicle.route_id)

        data = {
            'time_limit': route.parameters.speeding_time_limit,
            'speed_limit': route.parameters.speeding_speed_limit,
            'violations': []
        }

        for violation in violations:
            temp = {
                'duration': violation.duration,
                'lat1': violation.lat1,
                'long1': violation.long1,
                'lat2': violation.lat2,
                'long2': violation.long2,
                'time1': violation.time1,
                'time2': violation.time2,
            }
            data['violations'].append(temp)

        
        return jsonify(data), 200

    return jsonify({'error': 'speeding does not exist'}), 400

@app.route('/api/vehicle/analyze/stop/<int:id>', methods=['GET'])
def get_stop_violations(id):
    violations = Stops.query.filter_by(analysis_id=id).all()

    if violations:
        analysis = Analysis.query.get(id)
        vehicle = Vehicle.query.get(analysis.vehicle_id)
        route = Route.query.get(vehicle.route_id)

        data = {
            'min_time': route.parameters.stop_min_time,
            'max_time': route.parameters.stop_max_time,
            'violations': []
        }

        for violation in violations:
            temp = {
                'duration': violation.duration,
                'violation': violation.violation,
                'time1': violation.time1,
                'time2': violation.time2,
                'center_lat': violation.center_lat,
                'center_long': violation.center_long,
            }

            data['violations'].append(temp)

        return jsonify(data), 200

    return jsonify({'error': 'stops does not exist'}), 400

@app.route('/api/vehicle/analyze/liveness/<int:id>', methods=['GET'])
def get_liveness(id):
    analysis = Analysis.query.get(id)

    if analysis:
        vehicle = Vehicle.query.get(analysis.vehicle_id)
        route = Route.query.get(vehicle.route_id)

        if analysis.liveness_segments:
            data = {
                'total_liveness': analysis.total_liveness,
                'time_limit': route.parameters.liveness_time_limit,
                'segments': []
            }

            for segment in analysis.liveness_segments:
                temp = {
                    'liveness': segment.liveness,
                    'time1': segment.time1,
                    'time2': segment.time2
                }

                data['segments'].append(temp)

            return jsonify(data), 200

    return jsonify({'error': 'liveness does not exist'}), 400

@app.route('/api/admin/cutofftime', methods=['GET'])
def get_cutofftime():
    cut_off_time = GPSCutoffTime.query.first()

    if cut_off_time:
        data = {
            'cut_off_time': cut_off_time.time.strftime("%H:%M")
        }

        return jsonify(data), 200

    return jsonify({'error': 'cut off time not set'}), 400

@app.route('/api/admin/cutofftime', methods=['PUT'])
def set_cutofftime():
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
def get_northbound_key():
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
def set_northbound_key():
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
def northbound_connect():
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
def route_refresh():
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

    paged_routes = Route.query.paginate(page=1, per_page=PER_PAGE)

    if paged_routes:
        data = []

        for route in paged_routes.items:
            route_data = {
                'id': route.id,
                'name': route.name,
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
def parameter_refresh():
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

    paged_parameters = Parameters.query.paginate(page=1, per_page=PER_PAGE)

    if paged_parameters:
        data = []

        for parameter in paged_parameters.items:
            route = Route.query.get(parameter.route_id)
            
            parameter_data = {
                'id': parameter.id,
                'name': route.name,
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