import os
import sys
import networkx as nx
import osmnx as ox

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass


def _prune_graph(G):
    """Prunes unused attributes from the graph to dramatically reduce RAM usage."""
    if G is None:
        return G
    print("🧹 Pruning unused map attributes to optimize memory...")
    edges_pruned = 0
    nodes_pruned = 0
    # Keep only these attributes on edges to perform routing calculations
    edge_keys_to_keep = {'geometry', 'length', 'speed_kph', 'travel_time'}
    for u, v, k, data in G.edges(keys=True, data=True):
        for key in list(data.keys()):
            if key not in edge_keys_to_keep:
                del data[key]
                edges_pruned += 1
    # Keep only these attributes on nodes
    node_keys_to_keep = {'x', 'y'}
    for n, data in G.nodes(data=True):
        for key in list(data.keys()):
            if key not in node_keys_to_keep:
                del data[key]
                nodes_pruned += 1
    print(f"🧹 Pruned {edges_pruned} edge attributes and {nodes_pruned} node attributes.")
    import gc
    gc.collect()
    return G


def create_city_graph(DATA_BASE_DIR, city_name="Bangalore", network_type="drive"):
    """
    Checks for a locally saved Pickle (.pkl) file first for instant loading.
    If not found, falls back to GraphML, unprojects, caches it to Pickle, and returns.
    """
    import joblib

    # Sanitize name for file system storage
    base_name = f"{city_name.lower().replace(' ', '_')}_{network_type}"
    pkl_name = f"{base_name}.pkl"
    file_name = f"{base_name}.graphml"
    
    pkl_path = os.path.join(DATA_BASE_DIR, pkl_name)
    file_path = os.path.join(DATA_BASE_DIR, file_name)

    # 1. Check Pickle Cache First (Loads in ~2 seconds)
    if os.path.exists(pkl_path):
        print(f"📂 Found cached pickle map network at: {pkl_path}")
        print(f"🚀 Loading {city_name} topological matrix directly from Pickle...")
        try:
            G_projected = joblib.load(pkl_path)
            print(f"✅ Loaded from pickle successfully! Nodes: {len(G_projected.nodes)} | Edges: {len(G_projected.edges)}")
            return _prune_graph(G_projected)
        except Exception as e:
            print(f"⚠️ Error loading cached pickle: {e}, falling back to GraphML...")

    # 2. Direct Load Strategy from GraphML
    if os.path.exists(file_path):
        print(f"📂 Found cached GraphML map network at: {file_path}")
        print(f"🚀 Loading {city_name} topological matrix directly from GraphML...")
        try:
            G_projected = ox.load_graphml(file_path)
            
            # Unproject once upon loading to avoid expensive runtime projection conversion
            from pyproj import CRS
            crs = G_projected.graph.get("crs")
            if crs and CRS.from_user_input(crs).is_projected:
                print("🔄 Unprojecting loaded graph to GPS decimal degrees (lat/lng)...")
                G_projected = ox.project_graph(G_projected, to_latlong=True)
                
            # Cache the unprojected graph to Pickle for future instant loads
            try:
                print(f"💾 Caching unprojected graph to Pickle at: {pkl_path}")
                joblib.dump(G_projected, pkl_path)
                print("✅ Cached to Pickle successfully!")
            except Exception as ex:
                print(f"⚠️ Failed to cache pickle: {ex}")
                
            print(f"✅ Loaded successfully! Nodes: {len(G_projected.nodes)} | Edges: {len(G_projected.edges)}")
            return _prune_graph(G_projected)
        except Exception as e:
            print(f"⚠️ Error loading cached GraphML, falling back to download: {e}")

    # 3. Download Strategy: Runs if cache doesn't exist
    print(f"🌐 Cache miss. Querying OpenStreetMap geospatial bounds for: {city_name}...")
    try:
        # Ensure target database directory directory exists
        os.makedirs(DATA_BASE_DIR, exist_ok=True)

        query = f"{city_name}, India" if "india" not in city_name.lower() else city_name
        
        # Download raw topology
        G = ox.graph_from_place(query, network_type=network_type, retain_all=False)
        
        # Project coordinates to local UTM meters for accurate tracking
        G_projected = ox.project_graph(G)
        
        # Hydrate vectors with traffic attributes
        G_projected = ox.add_edge_speeds(G_projected)
        G_projected = ox.add_edge_travel_times(G_projected)
        
        # Store to Database Dir: Cache the GraphML graph
        print(f"💾 Caching processed graph to GraphML at: {file_path}")
        ox.save_graphml(G_projected, filepath=file_path)
        
        # Unproject to return standard GPS lat/lng decimal degree graph
        G_projected = ox.project_graph(G_projected, to_latlong=True)
        
        # Cache the unprojected graph to Pickle
        try:
            print(f"💾 Caching unprojected graph to Pickle at: {pkl_path}")
            joblib.dump(G_projected, pkl_path)
            print("✅ Cached to Pickle successfully!")
        except Exception as ex:
            print(f"⚠️ Failed to cache pickle: {ex}")
            
        print(f"✅ Setup complete. Nodes: {len(G_projected.nodes)} | Edges: {len(G_projected.edges)}")
        return _prune_graph(G_projected)

    except Exception as e:
        print(f"❌ Failed to build or store network matrix for '{city_name}': {str(e)}")
        return None

def shortest_path(G, source, destination, active_incidents=None):
    # Unproject the graph if it is in UTM/meters projection to ensure decimal degree computations
    from pyproj import CRS
    crs = G.graph.get("crs")
    is_proj = CRS.from_user_input(crs).is_projected if crs else False

    if is_proj:
        G_gps = ox.project_graph(G, to_latlong=True)
    else:
        G_gps = G

    # Copy graph to apply temporary penalties
    G_temp = G_gps.copy() if active_incidents else G_gps
    
    if active_incidents:
        import math
        # Apply heavy penalties to edges near other active incidents/traffic jams
        for incident in active_incidents:
            lat = incident.get("lat") or incident.get("mean_lat")
            lng = incident.get("lng") or incident.get("mean_lng") or incident.get("long")
            if lat is None or lng is None:
                continue
            
            try:
                lat_val = float(lat)
                lng_val = float(lng)
            except (ValueError, TypeError):
                continue
                
            # Iterate through edges and penalize those within ~400 meters (approx 0.004 degrees lat/lng)
            is_barricaded = incident.get("barricaded") == 1 or incident.get("barricaded") is True
            penalty = 5000.0 if is_barricaded else 20.0
            
            for u, v, k, data in G_temp.edges(keys=True, data=True):
                node_u = G_temp.nodes[u]
                edge_lat = node_u.get('y')
                edge_lng = node_u.get('x')
                if edge_lat and edge_lng:
                    dist = math.sqrt((edge_lat - lat_val)**2 + (edge_lng - lng_val)**2)
                    if dist < 0.004:
                        # Apply dynamic weight penalty based on barricade status
                        data["length"] = data.get("length", 1.0) * penalty

    # 2. Get nearest nodes (OSMnx expects longitude X first, then latitude Y)
    start_node = ox.distance.nearest_nodes(G_temp, source[1], source[0])
    end_node = ox.distance.nearest_nodes(G_temp, destination[1], destination[0])

    # 3. Calculate shortest path node IDs
    route = nx.shortest_path(G_temp, source=start_node, target=end_node, weight="length")

    # 4. Extract the actual [Lat, Lng] coordinates from the node IDs for Leaflet
    route_coords = []
    for node in route:
        node_data = G_temp.nodes[node]
        # OSMnx nodes store 'y' as Latitude and 'x' as Longitude
        route_coords.append([node_data['y'], node_data['x']])

    return route_coords


def shortest_path_with_traffic(G, source, destination, active_incidents=None):
    """
    Calculates the shortest/optimum path between source and destination using OSMnx,
    penalizing edges near active incidents and returning segments styled with traffic colors.
    """
    from pyproj import CRS
    crs = G.graph.get("crs")
    is_proj = CRS.from_user_input(crs).is_projected if crs else False

    if is_proj:
        G_gps = ox.project_graph(G, to_latlong=True)
    else:
        G_gps = G

    G_temp = G_gps.copy()
    
    # Track which edges are penalized
    penalized_edges = {}
    
    if active_incidents:
        import math
        for incident in active_incidents:
            lat = incident.get("lat") or incident.get("mean_lat")
            lng = incident.get("lng") or incident.get("mean_lng") or incident.get("long")
            if lat is None or lng is None:
                continue
            
            try:
                lat_val = float(lat)
                lng_val = float(lng)
            except (ValueError, TypeError):
                continue
                
            is_barricaded = incident.get("barricaded") == 1 or incident.get("barricaded") is True
            penalty = 5000.0 if is_barricaded else 20.0
            
            for u, v, k, data in G_temp.edges(keys=True, data=True):
                node_u = G_temp.nodes[u]
                edge_lat = node_u.get('y')
                edge_lng = node_u.get('x')
                if edge_lat and edge_lng:
                    dist = math.sqrt((edge_lat - lat_val)**2 + (edge_lng - lng_val)**2)
                    if dist < 0.004:  # ~400 meters
                        data["length"] = data.get("length", 1.0) * penalty
                        edge_key = (u, v, k)
                        if edge_key not in penalized_edges or penalty > penalized_edges[edge_key]:
                            penalized_edges[edge_key] = penalty

    start_node = ox.distance.nearest_nodes(G_temp, source[1], source[0])
    end_node = ox.distance.nearest_nodes(G_temp, destination[1], destination[0])

    try:
        route = nx.shortest_path(G_temp, source=start_node, target=end_node, weight="length")
    except nx.NetworkXNoPath:
        return {
            "segments": [],
            "total_distance_km": 0.0,
            "total_duration_min": 0.0
        }
    except Exception as e:
        print(f"[routing error]: {e}")
        return {
            "segments": [],
            "total_distance_km": 0.0,
            "total_duration_min": 0.0
        }

    segments = []
    total_distance_m = 0
    total_duration_s = 0

    for i in range(len(route) - 1):
        u = route[i]
        v = route[i+1]
        
        edge_data = G_temp[u][v]
        if isinstance(edge_data, dict):
            if 0 in edge_data:
                data = edge_data[0]
                k = 0
            else:
                k = list(edge_data.keys())[0]
                data = edge_data[k]
        else:
            data = edge_data
            k = 0

        segment_coords = []
        if "geometry" in data:
            coords_x_y = list(data["geometry"].coords)
            for x, y in coords_x_y:
                segment_coords.append([y, x])
        else:
            node_u = G_temp.nodes[u]
            node_v = G_temp.nodes[v]
            segment_coords = [[node_u['y'], node_u['x']], [node_v['y'], node_v['x']]]

        length = data.get("length", 100.0)
        
        speed_kph = data.get("speed_kph", 40.0)
        if isinstance(speed_kph, list):
            speed_kph = speed_kph[0]
        try:
            speed_kph = float(speed_kph)
        except (ValueError, TypeError):
            speed_kph = 40.0

        penalty = penalized_edges.get((u, v, k), 1.0)
        if penalty >= 5000.0:
            color = "#a81111"  # Dark Red
            weight = 6.5
            speed = 2.0
            status = "Road Blocked"
        elif penalty >= 20.0:
            color = "#cc8400"  # Dark Yellow/Orange
            weight = 5
            speed = 10.0
            status = "Heavy Traffic"
        else:
            color = "#136327"  # Dark Green
            weight = 4
            speed = speed_kph
            status = "Free Flow"

        original_length = length / penalty if penalty > 1.0 else length
        duration = original_length / (speed / 3.6)

        total_distance_m += original_length
        total_duration_s += duration

        segments.append({
            "coords": segment_coords,
            "color": color,
            "weight": weight,
            "speed": round(speed, 1),
            "status": status,
            "length_m": round(original_length, 1),
            "duration_s": round(duration, 1)
        })

    return {
        "segments": segments,
        "total_distance_km": round(total_distance_m / 1000.0, 2),
        "total_duration_min": round(total_duration_s / 60.0, 1)
    }




if __name__ == "__main__":
    # source and destination as (lat, lng)
    source = (12.9716, 77.5946)
    destination = (12.9900, 77.6000)
    
    coords = shortest_path("Bangalore, Karnataka, India", source, destination)
    print(f"Generated {len(coords)} coordinates for the path.")
    print("Sample:", coords[:3]) # Prints the first few coordinates