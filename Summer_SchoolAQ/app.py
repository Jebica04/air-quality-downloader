from flask import Flask, render_template, request, jsonify, send_file
import requests
import pandas as pd
import json
from datetime import datetime, timedelta
import io
import os
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from math import radians, cos, sin, asin, sqrt
from collections import defaultdict


app = Flask(__name__)

# Configuration
API_BASE_URL = "http://airview.cs.upt.ro"

# Global variable to track scanning status
scanning_status = {
    'in_progress': False,
    'progress': 0,
    'total': 0,
    'active_found': 0,
    'current_mac': '',
    'results': []
}

class ActiveMACExtractor:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.timeout = 10
    
    def test_single_mac(self, mac):
        """Test if a single MAC address is active"""
        try:
            url = f"{self.base_url}/api/v1/data-intake/{quote(mac)}"
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    # Check for essential air quality fields
                    essential_fields = ['mac', 'timestamp', 't', 'pm25', 'pm10', 'iaq']
                    found_fields = [field for field in essential_fields if field in data and data[field] is not None]
                    
                    if len(found_fields) >= 2:  # At least 2 essential fields present
                        return {
                            'mac': mac,
                            'status': 'active',
                            'last_update': data.get('timestamp'),
                            'available_fields': list(data.keys()),
                            'essential_fields_found': found_fields,
                            'location': {
                                'lat': data.get('lat') or data.get('latitude'),
                                'lng': data.get('lng') or data.get('longitude')
                            },
                            'data_quality': 'good' if len(found_fields) >= 4 else 'limited',
                            'sample_data': {
                                't': data.get('t'),
                                'pm25': data.get('pm25'),
                                'pm10': data.get('pm10'),
                                'iaq': data.get('iaq')
                            }
                        }
                    else:
                        return {
                            'mac': mac,
                            'status': 'inactive',
                            'reason': 'insufficient_data',
                            'available_fields': list(data.keys()) if data else []
                        }
                else:
                    return {'mac': mac, 'status': 'inactive', 'reason': 'no_data'}
            elif response.status_code == 404:
                return {'mac': mac, 'status': 'not_found', 'reason': 'device_not_found'}
            else:
                return {'mac': mac, 'status': 'error', 'reason': f'http_{response.status_code}'}
                
        except requests.exceptions.Timeout:
            return {'mac': mac, 'status': 'timeout', 'reason': 'connection_timeout'}
        except requests.exceptions.ConnectionError:
            return {'mac': mac, 'status': 'connection_error', 'reason': 'cannot_connect'}
        except Exception as e:
            return {'mac': mac, 'status': 'error', 'reason': str(e)}
    
    def scan_mac_range(self, base_mac, range_size=100, callback=None):
        """Scan a range around a known working MAC address"""
        try:
            # Parse the base MAC
            mac_parts = base_mac.split(":")
            if len(mac_parts) != 6:
                raise ValueError("Invalid MAC format")
            
            # Convert last two parts to integers for range scanning
            base_fourth = int(mac_parts[4], 16)
            base_fifth = int(mac_parts[5], 16)
            
            mac_list = []
            prefix = ":".join(mac_parts[:4])
            
            # Generate range around the base MAC
            for i in range(max(0, base_fourth - range_size//2), min(256, base_fourth + range_size//2)):
                for j in range(max(0, base_fifth - range_size//2), min(256, base_fifth + range_size//2)):
                    mac = f"{prefix}:{i:02X}:{j:02X}"
                    mac_list.append(mac)
            
            return self.extract_active_macs_parallel(mac_list, max_workers=15, callback=callback)
            
        except Exception as e:
            print(f"Error in range scan: {e}")
            return []
    
    def extract_active_macs_parallel(self, mac_list, max_workers=15, callback=None):
        """Extract active MACs using parallel processing"""
        global scanning_status
        
        active_macs = []
        total = len(mac_list)
        
        scanning_status.update({
            'in_progress': True,
            'progress': 0,
            'total': total,
            'active_found': 0,
            'results': []
        })
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_mac = {executor.submit(self.test_single_mac, mac): mac for mac in mac_list}
            
            # Process completed tasks
            completed = 0
            for future in as_completed(future_to_mac):
                result = future.result()
                completed += 1
                
                scanning_status['progress'] = completed
                scanning_status['current_mac'] = result['mac']
                
                if result['status'] == 'active':
                    active_macs.append(result)
                    scanning_status['active_found'] = len(active_macs)
                    print(f"✅ ACTIVE: {result['mac']} ({completed}/{total})")
                
                if callback:
                    callback(result, completed, total)
        
        scanning_status['in_progress'] = False
        scanning_status['results'] = active_macs
        return active_macs


class AirQualityAPI:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.devices_file = 'saved_devices.json'
    
    def get_saved_devices(self):
        """Get list of saved devices from local file"""
        try:
            if os.path.exists(self.devices_file):
                with open(self.devices_file, 'r') as f:
                    return json.load(f)
            return []
        except Exception as e:
            print(f"Error loading saved devices: {e}")
            return []
    
    def save_device(self, mac, name=None):
        """Save a working device to the local file"""
        try:
            saved_devices = self.get_saved_devices()
            
            # Check if device already exists
            for device in saved_devices:
                if device['mac'].lower() == mac.lower():
                    # Update existing device
                    device['name'] = name or device.get('name', f"Device {mac}")
                    device['last_tested'] = datetime.now().isoformat()
                    break
            else:
                # Add new device
                new_device = {
                    'mac': mac,
                    'name': name or f"Device {mac}",
                    'added_date': datetime.now().isoformat(),
                    'last_tested': datetime.now().isoformat()
                }
                saved_devices.append(new_device)
            
            # Save to file
            with open(self.devices_file, 'w') as f:
                json.dump(saved_devices, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving device: {e}")
            return False
    
    def remove_device(self, mac):
        """Remove a device from saved list"""
        try:
            saved_devices = self.get_saved_devices()
            original_count = len(saved_devices)
            
            saved_devices = [d for d in saved_devices if d['mac'].lower() != mac.lower()]
            
            if len(saved_devices) < original_count:
                with open(self.devices_file, 'w') as f:
                    json.dump(saved_devices, f, indent=2)
                return True
            return False
        except Exception as e:
            print(f"Error removing device: {e}")
            return False
    
    def test_device(self, mac):
        """Test if a device MAC address works"""
        try:
            url = f"{self.base_url}/api/v1/data-intake/{mac}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    # Look for air quality data fields
                    air_quality_fields = [
                        'mac', 'timestamp', 't', 'pm25', 'pm10', 'co', 'no2', 'iaq'
                    ]
                    found_fields = [field for field in air_quality_fields if field in data]
                    
                    if len(found_fields) >= 2:
                        return True, f"Device working - found: {', '.join(found_fields[:3])}"
                    else:
                        return False, "Response doesn't contain expected air quality data"
                else:
                    return False, "No data available"
            elif response.status_code == 404:
                return False, "Device not found"
            else:
                return False, f"HTTP {response.status_code}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    def get_aqi_level(self, aqi_value):
        """Convert AQI numeric value to descriptive level"""
        if aqi_value is None or aqi_value < 0:
            return "No Data"
        elif aqi_value <= 50:
            return "Good"
        elif aqi_value <= 100:
            return "Moderate"
        elif aqi_value <= 150:
            return "Unhealthy for Sensitive Groups"
        elif aqi_value <= 200:
            return "Unhealthy"
        elif aqi_value <= 300:
            return "Very Unhealthy"
        else:
            return "Hazardous"
    
    def get_location_from_coords(self, lat, lng):
        """Get location name from coordinates using reverse geocoding"""
        try:
            if lat and lng and lat != 0 and lng != 0:
                # Try to get location from a free geocoding service
                url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lng}&localityLanguage=en"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    location_data = response.json()
                    
                    # Build location string from components
                    location_parts = []
                    
                    if 'locality' in location_data and location_data['locality']:
                        location_parts.append(location_data['locality'])
                    elif 'city' in location_data and location_data['city']:
                        location_parts.append(location_data['city'])
                    
                    if 'principalSubdivision' in location_data and location_data['principalSubdivision']:
                        location_parts.append(location_data['principalSubdivision'])
                    
                    if 'countryName' in location_data and location_data['countryName']:
                        location_parts.append(location_data['countryName'])
                    
                    if location_parts:
                        return ', '.join(location_parts)
                
            # Fallback to coordinates
            return f"Coordinates: {lat}, {lng}"
            
        except Exception as e:
            print(f"Error getting location from coords: {e}")
            return f"Coordinates: {lat}, {lng}"
    
    def get_device_coordinates(self, mac):
        """Get device coordinates from the latest data"""
        try:
            url = f"{self.base_url}/api/v1/data-intake/{quote(mac)}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    lat = data.get('lat') or data.get('latitude')
                    lng = data.get('lng') or data.get('longitude') 
                    
                    if lat and lng:
                        return float(lat), float(lng)
            
            # Fallback coordinates for Timișoara area if device doesn't provide them
            return 45.7613, 21.2513
            
        except Exception as e:
            print(f"Error getting device coordinates: {e}")
            return 45.7613, 21.2513
    
    def get_hourly_data(self, mac, hours_from, hours_to):
        """Get hourly data using the 24h endpoint with proper data processing"""
        print(f"Requesting hourly data for MAC {mac} from hour {hours_from} to {hours_to}")
        
        # Get device coordinates first
        lat, lng = self.get_device_coordinates(mac)
        location = self.get_location_from_coords(lat, lng)
        print(f"Device location: {location} ({lat}, {lng})")
        
        try:
            # Get enough hours to ensure we have data for the requested time range
            hours_needed = max(48, hours_to - hours_from + 48)  # Get enough data with buffer
            
            # Use the 24h endpoint that actually works
            url = f"{self.base_url}/api/v1/data-intake-24h/{quote(mac)}/{hours_needed}"
            print(f"Trying 24h endpoint: {url}")
            
            response = requests.get(url, timeout=30)
            print(f"24h endpoint response: Status {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"24h endpoint returned: {type(data)} with {len(data) if isinstance(data, list) else 'N/A'} items")
                    
                    if isinstance(data, list) and len(data) > 0:
                        print(f"✅ SUCCESS! Found {len(data)} hourly values")
                        
                        # Count valid readings for debugging
                        valid_readings = [x for x in data if x != -1]
                        print(f"Valid readings: {len(valid_readings)} out of {len(data)}")
                        
                        # Process the hourly data array
                        enhanced_data = []
                        now = datetime.now()
                        
                        for i, aqi_value in enumerate(data):
                            if aqi_value != -1:  # Only include valid readings
                                # Calculate the timestamp (going backwards from now)
                                hours_ago = len(data) - 1 - i
                                timestamp = now - timedelta(hours=hours_ago)
                                hour = timestamp.hour
                                
                                # Check if this hour is in our requested range
                                if hours_from <= hour <= hours_to:
                                    reading = {
                                        'mac': mac,
                                        'timestamp': timestamp.isoformat() + 'Z',
                                        'date': timestamp.strftime('%Y-%m-%d'),
                                        'time': timestamp.strftime('%H:%M:%S'),
                                        'hour': hour,
                                        'day_of_week': timestamp.strftime('%A'),
                                        'aqi': aqi_value,
                                        'calculatedAqi': aqi_value,
                                        'aqi_level': self.get_aqi_level(aqi_value),
                                        'measurement_type': 'hourly_aqi',
                                        'data_source': '24h_endpoint_real',
                                        'location': location,
                                        'latitude': lat,
                                        'longitude': lng,
                                        'hours_ago': hours_ago,
                                        'real_timestamp': True,
                                        'note': f'Real hourly AQI reading from {timestamp.strftime("%Y-%m-%d %H:00")}'
                                    }
                                    enhanced_data.append(reading)
                        
                        if enhanced_data:
                            # Sort by timestamp (oldest first)
                            enhanced_data.sort(key=lambda x: x['timestamp'])
                            print(f"Processed {len(enhanced_data)} valid readings for hours {hours_from}-{hours_to}")
                            return enhanced_data
                        else:
                            print(f"No valid readings found for hours {hours_from}-{hours_to} in the last {hours_needed} hours")
                            return []
                            
                except Exception as json_error:
                    print(f"Error parsing 24h response: {json_error}")
                    return []
                    
            elif response.status_code == 400:
                print(f"Bad request (400): {response.text[:200]}")
                return []
            elif response.status_code == 404:
                print("24h endpoint not found (404)")
                return []
            else:
                print(f"Error {response.status_code}: {response.text[:100]}")
                return []
                
        except Exception as e:
            print(f"Exception with 24h endpoint: {e}")
            return []
    
    def get_date_range_data(self, mac, start_date, end_date, start_hour=0, end_hour=23):
        """Get data for specific date range using available endpoints"""
        print(f"Requesting date range data from {start_date} to {end_date}, hours {start_hour}-{end_hour}")
        
        # Get device coordinates first
        lat, lng = self.get_device_coordinates(mac)
        location = self.get_location_from_coords(lat, lng)
        print(f"Device location: {location} ({lat}, {lng})")
        
        try:
            # Calculate how many hours we need to go back to cover the date range
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            now = datetime.now()
            
            # Calculate hours from now to the start of our date range
            time_diff = now - start_dt
            hours_to_fetch = int(time_diff.total_seconds() / 3600) + 48  # Add buffer
            
            # Cap at reasonable limit
            hours_to_fetch = min(hours_to_fetch, 168)  # Max 7 days
            
            print(f"Fetching {hours_to_fetch} hours of data to cover date range")
            
            # Use the 24h endpoint to get historical data
            url = f"{self.base_url}/api/v1/data-intake-24h/{quote(mac)}/{hours_to_fetch}"
            print(f"Trying 24h endpoint for date range: {url}")
            
            response = requests.get(url, timeout=30)
            print(f"24h endpoint response: Status {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Got {len(data)} hourly values")
                
                if isinstance(data, list) and len(data) > 0:
                    enhanced_data = []
                    
                    for i, aqi_value in enumerate(data):
                        if aqi_value != -1:  # Only process valid readings
                            # Calculate the timestamp (going backwards from now)
                            hours_ago = len(data) - 1 - i
                            timestamp = now - timedelta(hours=hours_ago)
                            
                            # Check if this timestamp falls within our date range and hour range
                            record_date = timestamp.strftime('%Y-%m-%d')
                            record_hour = timestamp.hour
                            
                            if (start_date <= record_date <= end_date and 
                                start_hour <= record_hour <= end_hour):
                                
                                reading = {
                                    'mac': mac,
                                    'timestamp': timestamp.isoformat() + 'Z',
                                    'date': record_date,
                                    'time': timestamp.strftime('%H:%M:%S'),
                                    'hour': record_hour,
                                    'day_of_week': timestamp.strftime('%A'),
                                    'aqi': aqi_value,
                                    'calculatedAqi': aqi_value,
                                    'aqi_level': self.get_aqi_level(aqi_value),
                                    'measurement_type': 'historical_aqi',
                                    'data_source': '24h_endpoint_historical',
                                    'location': location,
                                    'latitude': lat,
                                    'longitude': lng,
                                    'hours_ago': hours_ago,
                                    'real_timestamp': True,
                                    'note': f'Historical AQI reading from {timestamp.strftime("%Y-%m-%d %H:00")}'
                                }
                                enhanced_data.append(reading)
                    
                    if enhanced_data:
                        # Sort by timestamp (oldest first)
                        enhanced_data.sort(key=lambda x: x['timestamp'])
                        print(f"✅ Found {len(enhanced_data)} real historical readings for date range {start_date} to {end_date}")
                        return enhanced_data
                    else:
                        print(f"No data found in the specified date range {start_date} to {end_date}")
                        return []
                else:
                    print("No valid data in response")
                    return []
            else:
                print(f"Error {response.status_code}: {response.text[:100]}")
                return []
                
        except Exception as e:
            print(f"Error getting date range data: {e}")
            return []
    
    def get_device_data(self, mac):
        """Get latest data for a specific device"""
        try:
            url = f"{self.base_url}/api/v1/data-intake/{quote(mac)}"
            print(f"Requesting latest data: {url}")
            response = requests.get(url, timeout=10)
            print(f"Latest data response: Status {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Latest data received: {type(data)}")
                
                if isinstance(data, dict):
                    # Get coordinates from the data
                    lat = data.get('lat') or data.get('latitude') or 45.7613
                    lng = data.get('lng') or data.get('longitude') or 21.2513
                    
                    # Get location from coordinates
                    location = self.get_location_from_coords(lat, lng)
                    
                    # Enhance the data
                    data['location'] = location
                    data['latitude'] = lat
                    data['longitude'] = lng
                    data['data_source'] = 'latest_reading'
                    
                    # Add current date/time info if timestamp is missing
                    if 'timestamp' not in data or not data['timestamp']:
                        current_time = datetime.now()
                        data['timestamp'] = current_time.isoformat() + 'Z'
                        data['date'] = current_time.strftime('%Y-%m-%d')
                        data['time'] = current_time.strftime('%H:%M:%S')
                    
                    # Add AQI level
                    if 'calculatedAqi' in data and data['calculatedAqi'] and data['calculatedAqi'] > 0:
                        data['aqi_level'] = self.get_aqi_level(data['calculatedAqi'])
                    elif 'dustAqi' in data and data['dustAqi'] and data['dustAqi'] > 0:
                        data['aqi_level'] = self.get_aqi_level(data['dustAqi'])
                    elif 'iaq' in data and data['iaq'] and data['iaq'] > 0:
                        data['aqi_level'] = self.get_aqi_level(data['iaq'])
                    
                    return [data]
                elif isinstance(data, list):
                    return data
                else:
                    return []
            else:
                print(f"Error response: {response.text}")
                return []
        except Exception as e:
            print(f"Error fetching device data: {e}")
            return []

# Initialize API client and MAC scanner
api_client = AirQualityAPI(API_BASE_URL)
mac_scanner = ActiveMACExtractor(API_BASE_URL)

def flatten_nested_dict(d, parent_key='', sep='_'):
    """Recursively flatten nested dictionaries"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_nested_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Convert list to string representation
            items.append((new_key, str(v)))
        else:
            items.append((new_key, v))
    return dict(items)

def convert_to_csv(data):
    """Convert JSON data to CSV format"""
    if not data:
        return None
    
    # Ensure data is a list
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        return None
    
    # If empty list
    if len(data) == 0:
        return None
    
    try:
        # Flatten nested objects for CSV
        flattened_data = []
        for item in data:
            if isinstance(item, dict):
                flattened_item = flatten_nested_dict(item)
                flattened_data.append(flattened_item)
            else:
                # Skip non-dict items
                print(f"Skipping non-dict item: {type(item)}")
                continue
        
        if not flattened_data:
            return None
        
        # Create DataFrame
        df = pd.DataFrame(flattened_data)
        
        # Handle datetime columns
        for col in df.columns:
            if 'timestamp' in col.lower() or 'time' in col.lower():
                try:
                    df[col] = pd.to_datetime(df[col], errors='ignore')
                except:
                    pass
        
        return df.to_csv(index=False)
    
    except Exception as e:
        print(f"Error converting to CSV: {e}")
        return None

def scan_macs_background(base_mac, range_size):
    """Background function to scan MACs"""
    try:
        results = mac_scanner.scan_mac_range(base_mac, range_size)
        print(f"Background scan completed: {len(results)} active MACs found")
        
        # Save results to file
        scan_data = {
            'scan_timestamp': datetime.now().isoformat(),
            'base_mac': base_mac,
            'range_size': range_size,
            'total_active': len(results),
            'results': results
        }
        
        with open('mac_scan_results.json', 'w') as f:
            json.dump(scan_data, f, indent=2)
            
    except Exception as e:
        print(f"Error in background scan: {e}")
        global scanning_status
        scanning_status['in_progress'] = False

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points in meters."""
    R = 6371000  # Earth radius in meters
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def compute_movement_by_mac(data):
    from collections import defaultdict

    mac_locations = defaultdict(list)

    # Group and collect by MAC
    for entry in data:
        mac = entry.get("mac")
        location = entry.get("location")
        timestamp = entry.get("last_update") or entry.get("timestamp")

        if mac and location and timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                lat = location.get("lat")
                lng = location.get("lng")
                if lat is not None and lng is not None:
                    mac_locations[mac].append((dt, lat, lng))
            except Exception:
                continue

    # Determine mobility
    result = {}
    for mac, points in mac_locations.items():
        # Sort points by time
        points.sort(key=lambda x: x[0])
        is_mobile = False

        for i in range(len(points)):
            t1, lat1, lon1 = points[i]
            for j in range(i+1, len(points)):
                t2, lat2, lon2 = points[j]
                time_diff = abs((t2 - t1).total_seconds()) / 3600.0  # hours
                if time_diff > 6:
                    break  # Only compare within 6h
                dist = haversine(lat1, lon1, lat2, lon2)
                if dist > 100:
                    is_mobile = True
                    break
            if is_mobile:
                break

        result[mac] = "mobile" if is_mobile else "static"
    return result

def load_mac_scan_data(filepath):
    """Load and normalize MAC scan result data from JSON file."""
    with open(filepath, 'r') as f:
        raw_data = f.read()

    try:
        parsed = json.loads(raw_data)
        # Case 1: Wrapped in a "results" key
        if isinstance(parsed, dict) and "results" in parsed:
            return parsed["results"]
        # Case 2: Directly a list
        elif isinstance(parsed, list):
            return parsed
        # Case 3: List as a string
        elif isinstance(parsed, str):
            inner_parsed = json.loads(parsed)
            if isinstance(inner_parsed, list):
                return inner_parsed
        raise ValueError("Unexpected JSON structure")
    except Exception as e:
        raise ValueError(f"Failed to parse MAC scan JSON: {e}")


# ============= NEW MAC SCANNER ROUTES =============

@app.route('/api/scan_macs/start', methods=['POST'])
def start_mac_scan():
    """Start scanning for active MAC addresses"""
    global scanning_status
    
    if scanning_status['in_progress']:
        return jsonify({'error': 'Scan already in progress'}), 400
    
    try:
        base_mac = request.form.get('base_mac', '00:A0:50:D3:74:F7')
        range_size = int(request.form.get('range_size', 100))
        
        if range_size > 500:
            return jsonify({'error': 'Range size too large (max 500)'}), 400
        
        # Start background thread
        thread = threading.Thread(
            target=scan_macs_background, 
            args=(base_mac, range_size)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'MAC scan started for range {range_size} around {base_mac}',
            'estimated_time': f'{range_size // 10} seconds'
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan_macs/status')
def get_scan_status():
    """Get current scanning status"""
    global scanning_status
    return jsonify(scanning_status)

@app.route('/api/scan_macs/results')
def get_scan_results():
    try:
        if not os.path.exists('mac_scan_results.json'):
            return jsonify({'error': 'No scan results found'}), 404

        try:
            results = load_mac_scan_data('mac_scan_results.json')
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 500

        # Clean up and classify
        cleaned_results = []
        for entry in results:
            if isinstance(entry, dict):
                cleaned_entry = {k: v for k, v in entry.items() if k != "available_fields"}
                cleaned_results.append(cleaned_entry)

       # Compute mobility classification using "100m in 6h" rule
        movement_map = compute_movement_by_mac(cleaned_results)

        for entry in cleaned_results:
            mac = entry.get("mac")
            movement_status = movement_map.get(mac, "unknown")
            entry["movement"] = movement_status

        return jsonify({"results": cleaned_results})

    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/api/scan_macs/test_single', methods=['POST'])
def test_single_mac():
    """Test a single MAC address"""
    try:
        mac = request.form.get('mac')
        if not mac:
            return jsonify({'error': 'MAC address required'}), 400
        
        result = mac_scanner.test_single_mac(mac)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan_macs/save_active', methods=['POST'])
def save_active_macs():
    """Save all active MACs from scan results to saved devices"""
    try:
        if not os.path.exists('mac_scan_results.json'):
            return jsonify({'error': 'No scan results found'}), 404
        
        with open('mac_scan_results.json', 'r') as f:
            scan_data = json.load(f)
        
        active_macs = scan_data.get('results', [])
        saved_count = 0
        
        for mac_info in active_macs:
            if mac_info.get('status') == 'active':
                mac = mac_info['mac']
                # Generate a name based on data quality and fields
                fields_count = len(mac_info.get('available_fields', []))
                name = f"Discovered_{mac.replace(':', '')}_{fields_count}fields"
                
                if api_client.save_device(mac, name):
                    saved_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Saved {saved_count} active devices',
            'saved_count': saved_count,
            'total_active_found': len(active_macs)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/mac_results')
def show_mac_results():
    try:
        with open('mac_scan_results.json', 'r') as f:
            data = json.load(f)
        results = data.get("results", [])
        # Remove 'available_fields' from each entry (just in case)
        cleaned_results = [
            {k: v for k, v in entry.items() if k != "available_fields"}
            for entry in results
        ]
        return render_template("mac_results.html", results=cleaned_results)
    except Exception as e:
        return f"Error loading MAC scan results: {e}", 500


# ============= EXISTING ROUTES (unchanged) =============

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/devices')
def get_devices_api():
    """Get saved devices"""
    devices = api_client.get_saved_devices()
    return jsonify(devices)

@app.route('/api/devices/test', methods=['POST'])
def test_device():
    """Test if a device MAC address works"""
    try:
        mac = request.form.get('mac')
        if not mac:
            return jsonify({'error': 'MAC address is required'}), 400
        
        works, message = api_client.test_device(mac)
        return jsonify({
            'works': works,
            'message': message,
            'mac': mac
        })
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/devices/save', methods=['POST'])
def save_device():
    """Save a working device"""
    try:
        mac = request.form.get('mac')
        name = request.form.get('name')
        
        if not mac:
            return jsonify({'error': 'MAC address is required'}), 400
        
        # Test if the device works
        works, message = api_client.test_device(mac)
        if not works:
            return jsonify({'error': f'Device test failed: {message}'}), 400
        
        # Save the device
        success = api_client.save_device(mac, name)
        if success:
            return jsonify({
                'success': True,
                'message': f'Device {mac} saved successfully'
            })
        else:
            return jsonify({'error': 'Failed to save device'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/devices/remove', methods=['POST'])
def remove_device():
    """Remove a device from saved list"""
    try:
        mac = request.form.get('mac')
        if not mac:
            return jsonify({'error': 'MAC address is required'}), 400
        
        success = api_client.remove_device(mac)
        if success:
            return jsonify({'success': True, 'message': f'Device {mac} removed'})
        else:
            return jsonify({'error': 'Device not found'}), 404
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/download_data', methods=['POST'])
def download_data():
    """Download data as CSV"""
    try:
        mac = request.form.get('device_mac')
        data_type = request.form.get('data_type')
        
        if not mac:
            return jsonify({'error': 'Device MAC is required'}), 400
        
        data = None
        filename = f"air_quality_data_{mac}.csv"
        
        if data_type == 'time_range' or data_type == 'date_range':
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            start_hour = request.form.get('start_hour', '0')
            end_hour = request.form.get('end_hour', '23')
            
            if not start_date or not end_date:
                return jsonify({'error': 'Start date and end date are required'}), 400
            
            try:
                # Validate date format
                datetime.strptime(start_date, '%Y-%m-%d')
                datetime.strptime(end_date, '%Y-%m-%d')
                start_hour = int(start_hour)
                end_hour = int(end_hour)
                
                if start_hour < 0 or start_hour > 23 or end_hour < 0 or end_hour > 23:
                    return jsonify({'error': 'Hours must be between 0 and 23'}), 400
                
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
            data = api_client.get_date_range_data(mac, start_date, end_date, start_hour, end_hour)
            filename = f"date_range_data_{mac}_{start_date}_to_{end_date}.csv"
            
            if len(data) == 0:
                return jsonify({'error': f'No data found for dates {start_date} to {end_date}. Try different dates.'}), 404
        
        elif data_type == 'hourly':
            hours_from = request.form.get('hours_from')
            hours_to = request.form.get('hours_to')
            
            if not hours_from or not hours_to:
                return jsonify({'error': 'Hours from and to are required'}), 400
            
            try:
                hours_from = int(hours_from)
                hours_to = int(hours_to)
                
                if hours_from < 0 or hours_from > 23 or hours_to < 0 or hours_to > 23:
                    return jsonify({'error': 'Hours must be between 0 and 23'}), 400
                
                if hours_from >= hours_to:
                    return jsonify({'error': 'Start hour must be less than end hour'}), 400
                
            except ValueError:
                return jsonify({'error': 'Hours must be integers'}), 400
            
            data = api_client.get_hourly_data(mac, hours_from, hours_to)
            filename = f"hourly_data_{mac}_{hours_from}h_to_{hours_to}h.csv"
            
            if len(data) == 0:
                return jsonify({'error': f'No data found for hours {hours_from} to {hours_to}. Try a different time range.'}), 404
        
        elif data_type == 'latest':
            data = api_client.get_device_data(mac)
            filename = f"latest_data_{mac}.csv"
            
            if not data or len(data) == 0:
                return jsonify({'error': 'No latest data found'}), 404
        
        else:
            return jsonify({'error': 'Invalid data type'}), 400
        
        # Convert to CSV
        csv_data = convert_to_csv(data)
        if not csv_data:
            return jsonify({'error': 'Failed to convert data to CSV or no valid data found'}), 500
        
        # Create file buffer
        csv_buffer = io.StringIO(csv_data)
        csv_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8'))
        
        return send_file(
            csv_bytes,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        print(f"Download error: {e}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/preview_data', methods=['POST'])
def preview_data():
    """Preview data without downloading"""
    try:
        mac = request.form.get('device_mac')
        data_type = request.form.get('data_type')
        
        if not mac:
            return jsonify({'error': 'Device MAC is required'}), 400
        
        data = None
        
        if data_type == 'time_range' or data_type == 'date_range':
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            start_hour = request.form.get('start_hour', '0')
            end_hour = request.form.get('end_hour', '23')
            
            if not start_date or not end_date:
                return jsonify({'error': 'Start date and end date are required'}), 400
            
            try:
                # Validate date format
                datetime.strptime(start_date, '%Y-%m-%d')
                datetime.strptime(end_date, '%Y-%m-%d')
                start_hour = int(start_hour)
                end_hour = int(end_hour)
                
                if start_hour < 0 or start_hour > 23 or end_hour < 0 or end_hour > 23:
                    return jsonify({'error': 'Hours must be between 0 and 23'}), 400
                
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
            data = api_client.get_date_range_data(mac, start_date, end_date, start_hour, end_hour)
            
            if len(data) == 0:
                return jsonify({'error': f'No data found for dates {start_date} to {end_date}. Try different dates.'}), 404
        
        elif data_type == 'hourly':
            hours_from = request.form.get('hours_from')
            hours_to = request.form.get('hours_to')
            
            if not hours_from or not hours_to:
                return jsonify({'error': 'Hours from and to are required'}), 400
            
            try:
                hours_from = int(hours_from)
                hours_to = int(hours_to)
                
                if hours_from < 0 or hours_from > 23 or hours_to < 0 or hours_to > 23:
                    return jsonify({'error': 'Hours must be between 0 and 23'}), 400
                
                if hours_from >= hours_to:
                    return jsonify({'error': 'Start hour must be less than end hour'}), 400
                
            except ValueError:
                return jsonify({'error': 'Hours must be integers'}), 400
            
            data = api_client.get_hourly_data(mac, hours_from, hours_to)
            
            if len(data) == 0:
                return jsonify({'error': f'No data found for hours {hours_from} to {hours_to}. Try a different time range.'}), 404
        
        elif data_type == 'latest':
            data = api_client.get_device_data(mac)
            
            if not data or len(data) == 0:
                return jsonify({'error': 'No latest data found'}), 404
        
        else:
            return jsonify({'error': 'Invalid data type'}), 400
        
        # Return all data for preview
        preview_data = data if isinstance(data, list) else [data]
        total_records = len(data) if isinstance(data, list) else 1
        
        return jsonify({
            'success': True,
            'data': preview_data,
            'total_records': total_records
        })
    
    except Exception as e:
        print(f"Preview error: {e}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

if __name__ == '__main__':
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    if not os.path.exists('static'):
        os.makedirs('static')
        os.makedirs('static/js')
    
    # Get port from environment variable (for cloud hosting)
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV', 'production') == 'development'
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)