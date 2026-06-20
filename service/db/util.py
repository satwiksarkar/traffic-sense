import numpy as np
from sklearn.cluster import DBSCAN

def get_max_priority(reports):
    priorities = [r.get('priority', 'MEDIUM') for r in reports if r.get('priority')]
    if 'HIGH' in priorities:
        return 'HIGH'
    if 'MEDIUM' in priorities or not priorities:
        return 'MEDIUM'
    return 'LOW'

def compute_spatial_clusters(reports_list, radius_km=0.5):
    """
    Processes a list of raw reports, runs DBSCAN spatial clustering, 
    and calculates the mathematical centroid (mean) for each dense cluster.
    
    :param reports_list: List of dicts containing [{'id': 1, 'issue_type': 'accident', 'lat': 22.5, 'lng': 88.3}, ...]
    :param radius_km: The grouping radius threshold in kilometers
    :return: (consolidated_clusters, processed_raw_ids)
    """
    if not reports_list:
        return [], []

    # Group records by category so different incident types don't merge together
    issue_types = set(r['issue_type'] for r in reports_list)
    consolidated_clusters = []
    processed_raw_ids = []

    for item_type in issue_types:
        type_reports = [r for r in reports_list if r['issue_type'] == item_type]
        if len(type_reports) < 2:
            continue  # Needs at least 2 reports to find density pairs

    # Extract coordinates into an array
        coords = np.array([[r['lat'], r['lng']] for r in type_reports])
        
        # Earth's approximate radius is 6371 km; convert distance parameter to radians
        kms_per_radian = 6371.0
        epsilon = radius_km / kms_per_radian

        # Run spatial clustering using Great-Circle (haversine) metric
        db = DBSCAN(eps=epsilon, min_samples=2, metric='haversine').fit(np.radians(coords))
        labels = db.labels_

        for cluster_id in set(labels):
            if cluster_id == -1:
                continue  # Skip anomalies/noise; leave them as raw entries for now

            cluster_indices = np.where(labels == cluster_id)[0]
            matched_reports = [type_reports[idx] for idx in cluster_indices]
            
            # Compute the geometric mean center (centroid) of the cluster
            cluster_coords = coords[cluster_indices]
            mean_lat, mean_lng = np.mean(cluster_coords, axis=0)

            # Aggregate description, location_name, priority
            location_names = [r.get('location_name') for r in matched_reports if r.get('location_name')]
            loc_name = location_names[0] if location_names else 'Consolidated Area'
            
            descriptions = [r.get('description') for r in matched_reports if r.get('description')]
            desc = "; ".join(filter(None, descriptions))
            
            prio = get_max_priority(matched_reports)

            consolidated_clusters.append({
                "issue_type": item_type,
                "mean_lat": float(mean_lat),
                "mean_lng": float(mean_lng),
                "count": len(matched_reports),
                "location_name": loc_name,
                "description": desc,
                "priority": prio
            })

            # Track which row IDs are packed into this cluster mean
            processed_raw_ids.extend([r['id'] for r in matched_reports])

    return consolidated_clusters, processed_raw_ids