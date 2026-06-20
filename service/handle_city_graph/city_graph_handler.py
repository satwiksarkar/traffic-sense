import osmnx as ox
from .util import load_city_graph

class DynamicGraphManager:
    def __init__(self,location):
        self.graph=load_city_graph(location)

    def update_edge_weights(self,location,updated_weight):
        lon=location[1]
        lat=location[0]
        u, v, key = ox.distance.nearest_edges(self.graph,lon,lat)
        self.graph.edges[u,v,key]["travel_time"]=updated_weight
        print("Updated")

    def get_nearest_edge(self,location):
        lon=location[1]
        lat=location[0]
        u, v, key = ox.distance.nearest_edges(self.graph,lon,lat)
        return u, v, key    

    def display_graph(self):
        ox.plot_graph(self.graph)

    def get_graph(self):
        return self.graph

    