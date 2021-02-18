from haversine import haversine
import gpxpy
import gpxpy.gpx
from shapely.geometry import Point, Polygon

def list_to_string(list):
    return ','.join(str(element) for element in list)

def string_to_list(string):
    return [int(element) for element in string.split(',')]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'gpx'

def create_geojson_feature(gps_data):
    geojson = {
        "type": "MultiPoint",
        "coordinates": []
    }

    for location in gps_data:
        point = [location['longitude'], location['latitude']]
        geojson["coordinates"].append(point)
        
    return geojson

def generate_corner_pts(gps_data):
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

    # 100 meters 
    greatest_lat += 0.0009
    least_long -= 0.0009
    least_lat -= 0.0009
    greatest_long += 0.0009

    return (greatest_lat, least_long), (least_lat, greatest_long)

def create_stops_gpx(stops):
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

def distance_travelled(gps_data):
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

def speed_violation(gps_data, type, speed_limit, time):
    """
    Determines if a speed violation of {speed_limit}
    occured for {time} minutes, given {type} of analysis.
    Input:
        type = "Explicit" or "Location"
        speed_limit in km/hr
        time in minutes
    """
    time_elapsed = -1
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

        if(speed >= speed_limit):
            speeding = True
            time_elapsed += time1.timestamp() - time0.timestamp()

            if (first_point == True):
                starting_point = gps_data[i]
                first_point = False

        else:
            speeding = False

            if (sec_to_minute(time_elapsed) >= time): 
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
                # list_violations.append(({'duration': time_elapsed}, starting_point, gps_data[i-1]))

            time_elapsed = -1
            first_point = True

    return list_violations

def stop_violation(gps_data, min_time, max_time, point1, point2):
    fence = Polygon([point1, (point1[0], point2[1]), point2, (point2[0], point1[1])])
    index_start = -1
    results = []

    for i in range(len(gps_data)):
        pt = Point(gps_data[i].get('latitude'), gps_data[i].get('longitude'))

        if fence.intersects(pt):
            if index_start == -1:
                index_start = i
        else:
            if index_start != -1:
                timer_start = gps_data[index_start].get('time').timestamp()
                timer_end = gps_data[i-1].get('time').timestamp()
                fence_time = timer_end - timer_start

                if fence_time < min_time or fence_time > max_time:
                    center_lat = (point1[0] + point2[0]) / 2
                    center_long = (point1[1] + point2[1]) / 2

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

def check_liveness(gps_data, time_limit):
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

    latitude = point1[0]
    longitude = point1[1]

    while latitude > point2[0]:
        while longitude < point2[1]:
            top_left_pt = (latitude, longitude)
            top_right_pt = (latitude, longitude + side_interval)
            bottom_left_pt = (latitude - side_interval, longitude)
            bottom_right_pt = (latitude - side_interval, longitude + side_interval)

            geofence = Polygon([top_left_pt, top_right_pt, bottom_right_pt, bottom_left_pt])
            grid_fence.append(geofence)

            longitude += side_interval

        longitude = point1[1]
        latitude -= side_interval

    return grid_fence

def generate_path(gps_data, grid_fence):
    path = []
    current_fence = -1

    for point in gps_data:
        pt = Point(point.get('latitude'), point.get('longitude'))
        for i in range(len(grid_fence)):
            if grid_fence[i].intersects(pt):
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
