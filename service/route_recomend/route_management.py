import os
import json
import math
from .util import shortest_path

class RouteManager:
    def __init__(self, city_graph):
        self.graph = city_graph
        # Dynamically locate the JSON dataset relative to this file path
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.stations_json_path = os.path.join(base_dir, "database", "traffic_police_station.json")
        self._assign_cache = {}

    def _calculate_haversine(self, lat1, lon1, lat2, lon2):
        """Calculates straight line distance in kilometers between two points."""
        R = 6371.0  # Earth radius in kilometers
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def load_stations_by_city(self, city_name="Bangalore"):
        """Loads police stations from local database JSON file based on city key."""
        if not os.path.exists(self.stations_json_path):
            print(f"[RouteManager Error]: Missing file {self.stations_json_path}")
            return []
        try:
            with open(self.stations_json_path, "r") as f:
                data = json.load(f)
                return data.get(city_name, [])
        except Exception as e:
            print(f"[RouteManager JSON Read Error]: {e}")
            return []

    def assign_station_to_incident(self, incident_lat, incident_lon, city_name="Bangalore"):
        """
        Estimates closest police station to incident, resolves the path,
        and returns a payload optimized for frontend rendering.
        """
        cache_key = (float(incident_lat), float(incident_lon), city_name)
        if cache_key in self._assign_cache:
            return self._assign_cache[cache_key]

        stations = self.load_stations_by_city(city_name)
        if not stations:
            return {"error": f"No stations found for city: {city_name}"}

        closest_station = None
        min_distance = float('inf')

        # 1. Use Haversine loop to find the nearest base station
        for station in stations:
            dist = self._calculate_haversine(
                float(incident_lat), float(incident_lon), 
                station["lat"], station["lon"]
            )
            if dist < min_distance:
                min_distance = dist
                closest_station = station

        # 2. Extract structural nodes for shortest path routing using your util
        # Maps coordinates to nearest graph intersection/nodes
        station_coords = (closest_station["lat"], closest_station["lon"])
        incident_coords = (float(incident_lat), float(incident_lon))
        
        try:
            # We assume your shortest_path function takes node coordinates or IDs
            route_path = shortest_path(self.graph, station_coords, incident_coords)
        except Exception as e:
            print(f"[Route Generation Error]: Could not map graph route path: {e}")
            route_path = [station_coords, incident_coords] # Fallback to direct vector

        result = {
            "assigned_station": closest_station["station_name"],
            "station_location": {"lat": closest_station["lat"], "lng": closest_station["lon"]},
            "distance_km": round(min_distance, 2),
            "route": route_path  # List of coordinates/nodes for frontend line strings
        }
        self._assign_cache[cache_key] = result
        return result

    def recomend_path(self, source, destination, user=None):
        if user and user.priority_score > 0.7:
            return shortest_path(self.graph, source, destination)
        return shortest_path(self.graph, source, destination)
    
    def shortest_path(self, source, destination):
        return shortest_path(self.graph, source, destination)
    
    @staticmethod
    def get_city(lat, lon):
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="traffic_app")
        location = geolocator.reverse((lat, lon), exactly_one=True)
        address = location.raw.get("address", {})
        return (
            address.get("city") or 
            address.get("town") or 
            address.get("village") or 
            address.get("municipality")
        )