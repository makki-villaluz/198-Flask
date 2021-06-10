import os 
from flask import request, jsonify, send_file
from flask_cors import CORS
from project2 import app, db
from project2.api import parse_gpx_file, distance_travelled, speed_violation, stop_violation, check_liveness, generate_grid_fence, generate_path, route_check, allowed_file, list_to_string, string_to_list, create_geojson_feature, generate_corner_pts, create_stops_gpx, parse_gpx_waypoints, Point
from project2.models import GPXVehicle, GPXRoute, GPXStop

@app.route('/api/vehicle/<int:gpx_vehicle_id>', methods=['GET'])
def get_vehicle(gpx_vehicle_id):
    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)
    gpx_route = GPXRoute.query.get(gpx_vehicle.route_id)
    gpx_stop = GPXStop.query.get(gpx_vehicle.stops_id)

    if gpx_vehicle:
        with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
            gps_data = parse_gpx_file(gpx_file)
            geojson = create_geojson_feature(gps_data)

        data = {
            'id': gpx_vehicle.id,
            'filename': gpx_vehicle.filename,
            'name': gpx_vehicle.name,
            'date_uploaded': gpx_vehicle.date_uploaded.strftime("%b %d, %Y"),
            'route_id': gpx_route.id,
            'route_name': gpx_route.name,
            'stops_id': gpx_stop.id,
            'stops_name': gpx_stop.name,
            'geojson': geojson
        }

        return jsonify(data)
    
    return jsonify({'error': 'record does not exist'}), 400

@app.route('/api/route/<int:gpx_route_id>', methods=['GET'])
def get_route(gpx_route_id):
    gpx_route = GPXRoute.query.get(gpx_route_id)

    if gpx_route:
        with open(os.path.join(app.config['GPX_ROUTE_FOLDER'], gpx_route.filename)) as gpx_file:
            gps_data = parse_gpx_file(gpx_file)
            geojson = create_geojson_feature(gps_data)

        data = {
            'id': gpx_route.id,
            'filename': gpx_route.filename,
            'name': gpx_route.name,
            'date_uploaded': gpx_route.date_uploaded.strftime("%b %d, %Y"),
            'cell_size': gpx_route.cell_size,
            'geojson': geojson
        }

        return jsonify(data)
    
    return jsonify({'error': 'record does not exist'}), 400

@app.route('/api/stop/<int:gpx_stop_id>', methods=['GET'])
def get_stop(gpx_stop_id):
    gpx_stop = GPXStop.query.get(gpx_stop_id)

    if gpx_stop:
        with open(os.path.join(app.config['GPX_STOP_FOLDER'], gpx_stop.filename)) as gpx_file:
            gps_data = parse_gpx_waypoints(gpx_file)
            geojson = create_geojson_feature(gps_data)

        data = {
            'id': gpx_stop.id,
            'filename': gpx_stop.filename,
            'name': gpx_stop.name,
            'date_uploaded': gpx_stop.date_uploaded.strftime("%b %d, %Y"),
            'min_time': gpx_stop.min_time,
            'max_time': gpx_stop.max_time,
            'geojson': geojson
        }

        return jsonify(data)

    return jsonify({'error': 'record does not exist'}), 400

@app.route('/api/vehicle', methods=['GET'])
def get_all_vehicles():
    all_gpx_vehicles = GPXVehicle.query.all()

    data = []

    for vehicle in all_gpx_vehicles:
        gpx_route = GPXRoute.query.get(vehicle.route_id)
        gpx_stop = GPXStop.query.get(vehicle.stops_id)

        data.append({
            'id': vehicle.id,
            'filename': vehicle.filename,
            'name': vehicle.name,
            'route_id': gpx_route.id,
            'route_name': gpx_route.name,
            'stops_id': gpx_stop.id,
            'stops_name': gpx_stop.name,
            'date_uploaded': vehicle.date_uploaded.strftime("%b %d, %Y")
        })

    return jsonify(data)

@app.route('/api/route', methods=['GET'])
def get_all_routes():
    all_gpx_routes = GPXRoute.query.all()

    data = []

    for route in all_gpx_routes:
        data.append({
            'id': route.id,
            'filename': route.filename,
            'name': route.name,
            'date_uploaded': route.date_uploaded.strftime("%b %d, %Y"),
            'cell_size': route.cell_size
        })

    return jsonify(data)

@app.route('/api/stop', methods=['GET'])
def get_all_stops():
    all_gpx_stops = GPXStop.query.all()

    data = []

    for stop in all_gpx_stops:
        data.append({
            'id': stop.id,
            'filename': stop.filename,
            'name': stop.name,
            'date_uploaded': stop.date_uploaded.strftime("%b %d, %Y"),
            'min_time': stop.min_time,
            'max_time': stop.max_time
        })

    return jsonify(data)

@app.route('/api/vehicle', methods=['POST'])
def upload_vehicle():
    gpx_file = request.files['gpx_file']
    name = request.form['name']
    route_id = request.form['route_id']
    stops_id = request.form['stops_id']
    filename = gpx_file.filename

    if gpx_file and allowed_file(filename):
        gpx_vehicle = GPXVehicle.query.filter_by(filename=filename).first()

        if not gpx_vehicle:
            gpx_file.save(os.path.join(app.config['GPX_VEHICLE_FOLDER'], filename))

            gpx_vehicle = GPXVehicle(filename=filename, name=name, route_id=route_id, stops_id=stops_id)
            gpx_route = GPXRoute.query.get(route_id)
            gpx_stop = GPXStop.query.get(stops_id)
            db.session.add(gpx_vehicle)
            db.session.commit()

            data = {
                'id': gpx_vehicle.id,
                'filename': gpx_vehicle.filename,
                'name': gpx_vehicle.name,
                'date_uploaded': gpx_vehicle.date_uploaded.strftime("%b %d, %Y"),
                'route_id': gpx_vehicle.route_id,
                'route_name': gpx_route.name,
                'stops_id': gpx_vehicle.stops_id,
                'stops_name': gpx_stop.name
            }

            return jsonify(data)

    return jsonify({'error': 'file error'}), 400

@app.route('/api/route', methods=['POST'])
def upload_route():
    gpx_file = request.files['gpx_file']
    name = request.form['name']
    cell_size = float(request.form['cell_size'])

    filename = gpx_file.filename

    if gpx_file and allowed_file(filename):
        gpx_route = GPXRoute.query.filter_by(filename=filename).first()

        if not gpx_route:
            gpx_file.save(os.path.join(app.config['GPX_ROUTE_FOLDER'], filename))

            with open(os.path.join(app.config['GPX_ROUTE_FOLDER'], filename)) as gpx_file:
                gps_data = parse_gpx_file(gpx_file)

            gpx_route = GPXRoute(
                filename=filename,
                name=name,
                cell_size=cell_size
            )

            db.session.add(gpx_route)
            db.session.commit()

            data = {
                'id': gpx_route.id,
                'filename': gpx_route.filename,
                'name': gpx_route.name,
                'date_uploaded': gpx_route.date_uploaded.strftime("%b %d, %Y"),
                'cell_size': gpx_route.cell_size
            }
            
            return jsonify(data)

    return jsonify({'error': 'file error'}), 400

@app.route('/api/stop', methods=['POST'])
def upload_stop():
    min_time = float(request.get_json(force=True)['min_time'])
    max_time = float(request.get_json(force=True)['max_time'])
    name = request.get_json(force=True)['name']
    filename = request.get_json(force=True)['filename']
    stops = request.get_json(force=True)['stops']

    gpx = create_stops_gpx(stops)
    with open(os.path.join(app.config['GPX_STOP_FOLDER'], filename ), 'w') as gpx_file:
        gpx_file.write(gpx.to_xml())

    gpx_stop = GPXStop(filename=filename, name=name, min_time=min_time, max_time=max_time)
    db.session.add(gpx_stop)
    db.session.commit()

    data = {
        'id': gpx_stop.id,
        'filename': gpx_stop.filename,
        'name': gpx_stop.name,
        'date_uploaded': gpx_stop.date_uploaded.strftime("%b %d, %Y"),
        'min_time': gpx_stop.min_time,
        'max_time': gpx_stop.max_time
    }

    return jsonify(data)

@app.route('/api/vehicle/<int:gpx_vehicle_id>', methods=['PUT'])
def update_vehicle(gpx_vehicle_id):
    new_name = request.form['name']
    new_route_id = request.form['route_id']
    new_stops_id = request.form['stops_id']

    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)
    gpx_route = GPXRoute.query.get(new_route_id)
    gpx_stop = GPXStop.query.get(new_stops_id)

    if gpx_vehicle:
        gpx_vehicle.name = new_name
        gpx_vehicle.route_id = new_route_id
        gpx_vehicle.stops_id = new_stops_id

        db.session.commit()

        data = {
            'id': gpx_vehicle.id,
            'filename': gpx_vehicle.filename,
            'name': new_name,
            'route_id': new_route_id,
            'route_name': gpx_route.name,
            'stops_id': new_stops_id,
            'stops_name': gpx_stop.name
        }

        return jsonify(data)

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/route/<int:gpx_route_id>', methods=['PUT'])
def update_route(gpx_route_id):
    new_name = request.form['name']
    new_cell_size = float(request.form['cell_size'])

    gpx_route = GPXRoute.query.get(gpx_route_id)

    if gpx_route:
        with open(os.path.join(app.config['GPX_ROUTE_FOLDER'], gpx_route.filename)) as gpx_file:
            gps_data = parse_gpx_file(gpx_file)

        gpx_route.name = new_name
        gpx_route.cell_size = new_cell_size

        db.session.commit()

        data = {
            'id': gpx_route.id,
            'filename': gpx_route.filename,
            'name': new_name,
            'cell_size': gpx_route.cell_size
        }

        return jsonify(data)

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/stop/<int:gpx_stop_id>', methods=['PUT'])
def update_stop(gpx_stop_id):
    new_name = request.form['name']
    new_min_time = float(request.form['min_time'])
    new_max_time = float(request.form['max_time'])

    gpx_stop = GPXStop.query.get(gpx_stop_id)

    if gpx_stop:
        gpx_stop.name = new_name
        gpx_stop.min_time = new_min_time
        gpx_stop.max_time = new_max_time

        db.session.commit()

        data = {
            'id': gpx_stop_id,
            'filename': gpx_stop.filename,
            'name': gpx_stop.name,
            'min_time': gpx_stop.min_time,
            'max_time': gpx_stop.max_time
        }

        return jsonify(data)

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/vehicle/<int:gpx_vehicle_id>', methods=['DELETE'])
def delete_vehicle(gpx_vehicle_id):
    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)
    
    if gpx_vehicle:
        filename = gpx_vehicle.filename
        os.remove(os.path.join(app.config['GPX_VEHICLE_FOLDER'], filename))

        db.session.delete(gpx_vehicle)
        db.session.commit()

        return jsonify({'id': gpx_vehicle_id})

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/route/<int:gpx_route_id>', methods=['DELETE'])
def delete_route(gpx_route_id):
    gpx_route = GPXRoute.query.get(gpx_route_id)
    
    if gpx_route:
        filename = gpx_route.filename
        os.remove(os.path.join(app.config['GPX_ROUTE_FOLDER'], filename))

        db.session.delete(gpx_route)
        db.session.commit()

        return jsonify({'id': gpx_route_id})

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/stop/<int:gpx_stop_id>', methods=['DELETE'])
def delete_stop(gpx_stop_id):
    gpx_stop = GPXStop.query.get(gpx_stop_id)

    if gpx_stop:
        filename = gpx_stop.filename
        os.remove(os.path.join(app.config['GPX_STOP_FOLDER'], filename))

        db.session.delete(gpx_stop)
        db.session.commit()

        return jsonify({'id': gpx_stop_id})

    return jsonify({'error': 'file does not exist'}), 400

@app.route('/api/distance/<int:gpx_vehicle_id>', methods=['GET'])
def distance(gpx_vehicle_id):
    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)

    with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
        gps_data = parse_gpx_file(gpx_file)

    distance = distance_travelled(gps_data)

    return jsonify({'distance': distance})

@app.route('/api/speeding/<int:gpx_vehicle_id>', methods=['POST'])
def speeding(gpx_vehicle_id):
    speed_type = request.form['speed_type']
    speed_limit = float(request.form['speed_limit'])
    time_limit = float(request.form['time_limit'])

    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)

    with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
        gps_data = parse_gpx_file(gpx_file)

    violations = speed_violation(gps_data, speed_type, speed_limit, time_limit)

    return jsonify(violations)

@app.route('/api/stop/<int:gpx_vehicle_id>/<int:gpx_stop_id>', methods=['GET'])
def stop(gpx_vehicle_id, gpx_stop_id):
    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)
    gpx_stop = GPXStop.query.get(gpx_stop_id)

    with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
        gps_data = parse_gpx_file(gpx_file)

    with open(os.path.join(app.config['GPX_STOP_FOLDER'], gpx_stop.filename)) as gpx_file:
        stops = parse_gpx_waypoints(gpx_file)

    violations = []
    for i in range(len(stops)):
        if i % 2 == 0:
            point1 = Point(stops[i]['latitude'], stops[i]['longitude'])
            point2 = Point(stops[i+1]['latitude'], stops[i+1]['longitude'])
            violations += stop_violation(gps_data, gpx_stop.min_time, gpx_stop.max_time, point1, point2)
        else:
            continue

    return jsonify(violations)

@app.route('/api/liveness/<int:gpx_vehicle_id>', methods=['POST'])
def liveness(gpx_vehicle_id):
    time_limit = int(request.form['time_limit'])

    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)

    with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
        gps_data = parse_gpx_file(gpx_file)

    results = check_liveness(gps_data, time_limit)

    return jsonify(results)

@app.route('/api/loop/<int:gpx_vehicle_id>/<int:gpx_route_id>', methods=['GET'])
def loop(gpx_vehicle_id, gpx_route_id):
    gpx_vehicle = GPXVehicle.query.get(gpx_vehicle_id)
    gpx_route = GPXRoute.query.get(gpx_route_id)

    with open(os.path.join(app.config['GPX_VEHICLE_FOLDER'], gpx_vehicle.filename)) as gpx_file:
        gps_data_vehicle = parse_gpx_file(gpx_file)

    with open(os.path.join(app.config['GPX_ROUTE_FOLDER'], gpx_route.filename)) as gpx_file:
        gps_data_route = parse_gpx_file(gpx_file)

    cell_size = gpx_route.cell_size

    point1, point2 = generate_corner_pts(gps_data_vehicle, cell_size)
    grid_fence = generate_grid_fence(point1, point2, cell_size)
    vehicle_path = generate_path(gps_data_vehicle, grid_fence)
    route_path = generate_path(gps_data_route, grid_fence)
    loops = loop_counting(route_path, vehicle_path, grid_fence)

    return jsonify({'loops': loops})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    file_path = os.path.join(app.static_folder, path)
    if os.path.isfile(file_path):
        return send_file(file_path)
    index_path = os.path.join(app.static_folder, 'index.html')
    return send_file(index_path)