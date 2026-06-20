import networkx as nx
from geopy.geocoders import Nominatim
from .util import shortest_path
class RouteManager:
    def __init__(self,city_graph):
        self.graph=city_graph

    def recomend_path(self,source,destination,user=None):
        if user and user.priority_score > 0.7:
            return shortest_path(self.graph,source,destination)

        #default recomended path
        return shortest_path(self.graph,source,destination)
    
    def shortest_path(self,source,destination):
        return shortest_path(self.graph,source,destination)
    
    def get_city(lat, lon):
        geolocator = Nominatim(user_agent="traffic_app")

        location = geolocator.reverse((lat, lon), exactly_one=True)

        address = location.raw.get("address", {})

        return (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
        )
        

            
            
            
