import networkx as nx
import osmnx as ox

def shortest_path(G, source, destination):

    # 2. Get nearest nodes (OSMnx expects longitude X first, then latitude Y)
    start_node = ox.distance.nearest_nodes(G, source[1], source[0])
    end_node = ox.distance.nearest_nodes(G, destination[1], destination[0])

    # 3. Calculate shortest path node IDs
    route = nx.shortest_path(G, source=start_node, target=end_node, weight="length")

    # 4. Extract the actual [Lat, Lng] coordinates from the node IDs for Leaflet
    route_coords = []
    for node in route:
        node_data = G.nodes[node]
        # OSMnx nodes store 'y' as Latitude and 'x' as Longitude
        route_coords.append([node_data['y'], node_data['x']])

    return route_coords



if __name__ == "__main__":
    # source and destination as (lat, lng)
    source = (12.9716, 77.5946)
    destination = (12.9900, 77.6000)
    
    coords = shortest_path("Bangalore, Karnataka, India", source, destination)
    print(f"Generated {len(coords)} coordinates for the path.")
    print("Sample:", coords[:3]) # Prints the first few coordinates