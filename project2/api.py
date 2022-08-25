from project2.models import Vehicle, Route, Parameters, Analysis, Distance, Loops, Speeding, Stops, Liveness
from project2 import db
from haversine import haversine
from datetime import datetime
import gpxpy
import gpxpy.gpx

class Point():
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon

class Polygon():
    def __init__(self, top_left_pt, bottom_right_pt):
        self.top_left_pt = top_left_pt
        self.bottom_right_pt = bottom_right_pt

    def contains(self, point):
        if self.top_left_pt.lat >= point.lat and self.top_left_pt.lon <= point.lon and self.bottom_right_pt.lat < point.lat and self.bottom_right_pt.lon > point.lon:
            return True
        else:
            return False

def list_to_string(list):
    return ','.join(str(element) for element in list)

def string_to_list(string):
    return [int(element) for element in string.split(',')]

def is_gpx_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'gpx'

def is_csv_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'csv'

def create_geojson_feature(gps_data):
    geojson = {
        "type": "MultiPoint",
        "coordinates": []
    }

    for location in gps_data:
        point = [location['longitude'], location['latitude']]
        geojson["coordinates"].append(point)
        
    return geojson

def generate_corner_pts(gps_data, buffer=0.1):
    greatest_lat = gps_data[0].get('latitude')
    least_lat = gps_data[0].get('latitude')
    greatest_long = gps_data[0].get('longitude')
    least_long = gps_data[0].get('longitude')

    for point in gps_data:
        point_lat = point.get('latitude')
        point_long = point.get('longitude')

        if point_lat > greatest_lat:
            greatest_lat = point_lat 
        elif point_lat < least_lat:
            least_lat = point_lat
        
        if point_long > greatest_long:
            greatest_long = point_long
        elif point_long < least_long:
            least_long = point_long

    # 1km * buffer, buffer by default is 0.1 (100m), buffer is set to cell_size
    greatest_lat += 0.009 * buffer
    least_long -= 0.009 * buffer
    least_lat -= 0.009 * buffer
    greatest_long += 0.009 * buffer

    return Point(greatest_lat, least_long), Point(least_lat, greatest_long)

def csv_to_gpx_stops(stop_file):
    stops = []

    stop_file.readline()
    list_of_lines = stop_file.readlines()

    for line in list_of_lines:
        line = line.decode("utf-8").split(',')
        stop = {}

        stop['lat1'] = line[1]
        stop['long1'] = line[2]
        stop['lat2'] = line[3]
        stop['long2'] = line[4].strip()

        stops.append(stop)

    gpx = gpxpy.gpx.GPX()

    for stop in stops:
        gpx.waypoints.append(gpxpy.gpx.GPXTrackPoint(float(stop['lat1']), float(stop['long1'])))
        gpx.waypoints.append(gpxpy.gpx.GPXTrackPoint(float(stop['lat2']), float(stop['long2'])))

    return gpx 

def parse_gpx_file(gpx_file_location):
    """
    Parses GPX file to output array of objects
    """
    points = []
    gpx = gpxpy.parse(gpx_file_location)
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append({
                    'latitude': point.latitude,
                    'longitude': point.longitude,
                    'elevation': point.elevation,
                    'time': point.time,
                    'speed': point.speed
                })
    unique_points = list({point['time']:point for point in points}.values())

    return unique_points

def parse_gpx_waypoints(gpx_file):
    waypoints = []
    gpx = gpxpy.parse(gpx_file)

    for waypoint in gpx.waypoints:
        waypoints.append({'latitude': waypoint.latitude, 'longitude': waypoint.longitude})

    return waypoints

def compute_distance_travelled(gps_data):
    """
    Calculates total distance travelled in km
    """
    distance_travelled = 0.0
    for i in range(len(gps_data) - 1):
        distance_travelled += haversine((gps_data[i].get('latitude'), gps_data[i].get('longitude')), 
            (gps_data[i+1].get('latitude'), gps_data[i+1].get('longitude')))
    
    return '%.2f'%(distance_travelled)

def sec_to_minute(seconds):
    return seconds / 60.0

def sec_to_hour(seconds):
    return seconds / 3600.0

def speed_between_points(lon1, lat1, time1, lon2, lat2, time2):
    """
    Given 2 GPS points, calculate the speed between them
    """
    d_time = sec_to_hour(time2.timestamp() - time1.timestamp())
    d_distance = haversine((lat1, lon1), (lat2, lon2))
    return d_distance / d_time

def compute_speed_violation(gps_data, type, speed_limit, time):
    """
    Determines if a speed violation of {speed_limit}
    occured for {time} minutes, given {type} of analysis.
    Input:
        type = "Explicit" or "Location"
        speed_limit in km/hr
        time in seconds
    """
    time_elapsed = 0
    first_point = True
    list_violations = []
    for i in range(len(gps_data) - 1):
        time0 = gps_data[i-1].get("time")
        lon1 = gps_data[i].get("longitude")
        lat1 = gps_data[i].get("latitude")
        time1 = gps_data[i].get("time")
        lon2 = gps_data[i+1].get("longitude")
        lat2 = gps_data[i+1].get("latitude")
        time2 = gps_data[i+1].get("time")

        if type == "Explicit":
            if(gps_data[i].get("speed") is None):
                speed = speed_between_points(lon1, lat1, time1, lon2, lat2, time2)
            else:
                speed = gps_data[i].get("speed")
        elif type == "Location":
            speed = speed_between_points(lon1, lat1, time1, lon2, lat2, time2)

        if speed >= speed_limit: 
            if first_point == True:
                starting_point = gps_data[i]
                first_point = False
            else: 
                time_elapsed += time1.timestamp() - time0.timestamp() 
        else:
            if time_elapsed >= time:
                violation = {
                    'duration': time_elapsed, 
                    'lat1': starting_point['latitude'],
                    'long1': starting_point['longitude'],
                    'time1': starting_point['time'],
                    'lat2': gps_data[i-1]['latitude'],
                    'long2': gps_data[i-1]['longitude'],
                    'time2': gps_data[i-1]['time']
                }

                list_violations.append(violation)
            time_elapsed = 0
            first_point = True

    return list_violations

def stop_violation(gps_data, min_time, max_time, point1, point2):
    fence = Polygon(point1, point2)
    index_start = -1
    results = []

    for i in range(len(gps_data)):
        pt = Point(gps_data[i].get('latitude'), gps_data[i].get('longitude'))

        if fence.contains(pt):
            if index_start == -1:
                index_start = i
        else:
            if index_start != -1:
                timer_start = gps_data[index_start].get('time').timestamp()
                timer_end = gps_data[i-1].get('time').timestamp()
                fence_time = timer_end - timer_start

                if fence_time < min_time or fence_time > max_time:
                    center_lat = (point1.lat + point2.lat) / 2
                    center_long = (point1.lon + point2.lon) / 2

                    violation = {
                        'duration': fence_time,
                        'time1': gps_data[index_start].get('time'),
                        'time2': gps_data[i-1].get('time'),
                        'center_lat': center_lat,
                        'center_long': center_long
                    }

                    if fence_time < min_time:
                        violation['violation'] = 'below limit'
                    elif fence_time > max_time:
                        violation['violation'] = 'above limit'

                    results.append(violation)
                
                index_start = -1

    return results

def compute_stop_violation(stops, gps_data_vehicle, min_time, max_time):
    stop_violations = []
    for i in range(len(stops)):
        if i % 2 == 0:
            point1 = Point(stops[i]['latitude'], stops[i]['longitude'])
            point2 = Point(stops[i+1]['latitude'], stops[i+1]['longitude'])
            stop_violations += stop_violation(gps_data_vehicle, min_time, max_time, point1, point2)

    return stop_violations

def compute_liveness(gps_data, time_limit):
    """
    Determines total "aliveness" time of a vehicle. The
    vehicle is considered "alive" if the gaps between
    GPS readings are less than given {time_limit}.
    Input:  gps_data (array of dictionaries)
            time_limit (in seconds)
    Output: total_liveness (in seconds)
            results (array of dictionaries)
    """
    results = []
    total_liveness = 0
    start_index = 0

    for i in range(len(gps_data) - 1):
        time0 = gps_data[i].get("time")
        time1 = gps_data[i+1].get("time")
        time_diff = time1.timestamp() - time0.timestamp()

        if time_diff >= time_limit:
            segment_liveness = time0.timestamp() - gps_data[start_index].get("time").timestamp()
            results.append({
                "liveness": segment_liveness,
                "time1": gps_data[start_index].get("time"),
                "time2": gps_data[i].get("time")
            })
            start_index = i + 1
            total_liveness += segment_liveness
    
    time0 = gps_data[start_index].get("time")
    time1 = gps_data[-1].get("time")
    segment_liveness = time1.timestamp() - time0.timestamp()
    results.append({
        "liveness": segment_liveness,
        "time1": time0,
        "time2": time1
    })
    total_liveness += segment_liveness
    results = {'total_liveness': total_liveness, 'segments': results}

    return results

def generate_grid_fence(point1, point2, side_length):
    grid_fence = []

    side_interval = side_length * 0.009

    latitude = point1.lat
    longitude = point1.lon

    while latitude > point2.lat:
        row = []

        while longitude < point2.lon:
            top_left_pt = Point(latitude, longitude)
            bottom_right_pt = Point(latitude - side_interval, longitude + side_interval)

            geofence = Polygon(top_left_pt, bottom_right_pt)
            row.append(geofence)

            longitude += side_interval

        longitude = point1.lon
        latitude -= side_interval

        grid_fence.append(row)

    return grid_fence

def generate_path(gps_data, grid_fence):
    path = []
    current_fence = -1

    if isinstance(grid_fence[0], list):
        for point in gps_data:
            pt = Point(point.get('latitude'), point.get('longitude'))
            for i in range(len(grid_fence)):
                for j in range(len(grid_fence[0])):
                    if grid_fence[i][j].contains(pt):
                        fence_number = i * len(grid_fence[0]) + j
                        if current_fence != fence_number:
                            current_fence = fence_number
                            path.append(fence_number)
                            break
                else:
                    continue
                break
    else:
        for point in gps_data:
            pt = Point(point.get('latitude'), point.get('longitude'))
            for i in range(len(grid_fence)):
                if grid_fence[i].contains(pt):
                    if current_fence != i:
                        current_fence = i 
                        path.append(i)
                        break

    return path

def route_check(set_route, vehicle_route):
    set_route = "".join([str(x) for x in set_route])
    vehicle_route = "".join([str(x) for x in vehicle_route])

    loops = 0
    start = 0 
    while start < len(vehicle_route):
        pos = vehicle_route.find(set_route, start)

        if pos != -1:
            start = pos + 1
            loops += 1
        else:
            break

    return loops

def compute_loops(route, traj, grid_cells):
    errors = 0
    loops = 0
    r = 0
    i = 0
    while i < len(traj):
        if traj[i] == route[r]:
            r += 1
        else:
            ind = find_current_index(traj[i], route)
            # "Local" Errors
            if ind != -1:
                if ind > r:
                    r = ind + 1
                elif ind < r:
                    if traj[ind] == route[0]:
                        if traj[i - 1] == route[1]:
                            r = ind + 1
                        else: 
                            r = len(route) 
                    else:
                        r = ind + 1
            # "Foreign" Errors
            elif ind == -1:
                i, r, detour, missed_route = detour_info(i, r, route, traj)
                errors += check_neighbors(detour, missed_route, grid_cells)
        if r == len(route):
            r = r % len(route)
            if errors == 0:
                loops += 1
            else:
                errors = 0
        i += 1
    return loops

def detour_info(i, r, route, traj):
    detour = []
    missed_route = []
    sub_traj = traj[i:]
    _i = i
    
    # Find Detour List
    for j in range(len(sub_traj)):
        if find_current_index(sub_traj[j], route) == -1:
            detour.append(sub_traj[j])
            i += 1
        else:
            break

    # Find Missing Route
    if _i == 0:
        if find_current_index(traj[i], route) == 0:
            missed_route = [route[0]]
        else:
            end_index = find_current_index(traj[i], route) + 1
            missed_route = route[0:end_index]
        r = find_current_index(traj[i], route) + 1
    elif _i != 0:
        start_index = find_current_index(traj[_i-1], route)
        if i == len(traj):
            missed_route = route[start_index:len(route)]
            r = len(route) # arbitrary, traj has already ended
        else:
            end_index = find_current_index(traj[i], route) + 1
            if end_index < start_index:
                missed_route = route[start_index:len(route)]
                missed_route.append(end_index)
            else:
                missed_route = route[start_index:end_index]
            r = find_current_index(traj[i], route) + 1
    return i, r, detour, missed_route

def check_neighbors(detour, missed_route, grid_cells):
    # A detour cell must be adjacent to at least one missed_route cell
    err = 0
    width = len(grid_cells[0])
    length = len(grid_cells) * len(grid_cells[0])

    for d in detour:
        for r in missed_route:
            if d not in adjacent_cells(r, width, length):
                err = 1
                break
    return err

def adjacent_cells(d, w, l):
    # Top Left
    if d == 0:
        return [d+1, d+w, d+w+1]
    # Top Right
    elif d == w-1:
        return [d-1, d+w-1, d+w]
    # Bottom Left
    elif d == l-w:
        return [d-w, d-w+1, d+1]
    # Bottom Right
    elif d == l-1:
        return [d-w-1, d-w, d-1]
    # North
    elif d < w:
        return [d-1, d+1, d+w-1, d+w, d+w+1]
    # South
    elif (d < l) and (d >= l-w):
        return [d-w-1, d-w, d-w+1, d-1, d+1]
    # West
    elif d % w == 0:
        return [d-w, d-w+1, d+1, d+w, d+w+1]
    # East
    elif d % w == w - 1:
        return [d-w-1, d-w, d-1, d+w-1, d+w]
    # Middle
    else:
        return [d-w-1, d-w, d-w+1, d-1, d+1, d+w-1, d+w, d+w+1]

def find_current_index(cell, route_list):
    # Find what index in the route_list the trajectory cell exists in
    for i in range(len(route_list)):
        if route_list[i] == cell:
            return i
    return -1

def compute_vehicle_info(vehicle, route, gps_data_vehicle, gps_data_route, stops):
    # compute loops
    point1, point2 = generate_corner_pts(gps_data_vehicle, route.parameters.cell_size)
    grid_fence = generate_grid_fence(point1, point2, route.parameters.cell_size)
    vehicle_path = generate_path(gps_data_vehicle, grid_fence)
    route_path = generate_path(gps_data_route, grid_fence)
    loops = compute_loops(route_path, vehicle_path, grid_fence)

    loops_record = Loops(loops, vehicle.analysis.id)
    db.session.add(loops_record)
    vehicle.analysis.cell_size = route.parameters.cell_size

    # compute speeding
    speeding_violations = compute_speed_violation(gps_data_vehicle, "Explicit", route.parameters.speeding_speed_limit, route.parameters.speeding_time_limit)

    if not speeding_violations:
        speeding = Speeding(0, datetime.fromtimestamp(0), datetime.fromtimestamp(0), 0, 0, 0, 0, vehicle.analysis.id)
        db.session.add(speeding)
    else:
        for violation in speeding_violations:
            speeding = Speeding(violation['duration'], violation['time1'], violation['time2'], violation['lat1'], violation['long1'], violation['lat2'], violation['long2'], vehicle.analysis.id)
            db.session.add(speeding)
    vehicle.analysis.speeding_time_limit = route.parameters.speeding_time_limit
    vehicle.analysis.speeding_speed_limit = route.parameters.speeding_speed_limit

    # compute stop
    stop_violations = compute_stop_violation(stops, gps_data_vehicle, route.parameters.stop_min_time, route.parameters.stop_max_time)

    if not stop_violations:
        stop = Stops('no violation', 0, datetime.fromtimestamp(0), datetime.fromtimestamp(0), 0, 0, vehicle.analysis.id)
        db.session.add(stop)
    else:
        for violation in stop_violations:
            stop = Stops(violation['violation'], violation['duration'], violation['time1'], violation['time2'], violation['center_lat'], violation['center_long'], vehicle.analysis.id)
            db.session.add(stop)
    vehicle.analysis.stop_min_time = route.parameters.stop_min_time
    vehicle.analysis.stop_max_time = route.parameters.stop_max_time

    # compute liveness
    liveness = compute_liveness(gps_data_vehicle, route.parameters.liveness_time_limit)

    vehicle.analysis.total_liveness = liveness['total_liveness']
    for segment in liveness['segments']:
        liveness_segment = Liveness(segment['liveness'], segment['time1'], segment['time2'], vehicle.analysis.id)
        db.session.add(liveness_segment)
    vehicle.analysis.liveness_time_limit = route.parameters.liveness_time_limit

    db.session.commit()