import os
import osmnx as ox
import pickle

def load_city_graph(city):
    # Get database directory from environment or use default
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA_BASE_DIR = os.path.join(base_dir, 'database')
    
    # 1. Correctly format the file name without overwriting the 'city' variable
    file_name = f"{city}_graph.pkl"
    file_path = os.path.join(DATA_BASE_DIR, file_name)

    # 2. If cached file exists, load it using binary read mode ('rb')
    if os.path.exists(file_path):
        print(f"Loading {city} graph from cache...")
        with open(file_path, 'rb') as f:
            G = pickle.load(f)
        return G 

    # 3. If not cached, fetch it from OpenStreetMap using osmnx
    print(f"Fetching {city} graph from OpenStreetMap (this may take a moment)...")
    G = ox.graph_from_place(
        city,
        network_type="drive"
    )

    # 4. Save it to cache using binary write mode ('wb')
    with open(file_path, 'wb') as f:
        pickle.dump(G, f)
        
    return G

    