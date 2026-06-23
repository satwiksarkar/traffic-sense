"""
NGBoost model loader and predictor.

Loads three artefacts from the models/ directory:
  - ngboost_traffic_model.pkl   → trained NGBoost regressor
  - label_encoder_cause.pkl     → sklearn LabelEncoder for incident cause
  - label_encoder_priority.pkl  → sklearn LabelEncoder for priority level

Exposes public functions for spatial embedding resolution and duration prediction.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from schemas import IncidentInput

# Suppress sklearn version warnings
warnings.filterwarnings('ignore')

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

def get_path(rel_path: str) -> str:
    # Try current working directory first
    if os.path.exists(rel_path):
        return rel_path
    # Try module directory
    alt_path = BASE_DIR / rel_path
    if alt_path.exists():
        return str(alt_path)
    return rel_path

# ── Load Encoders and Model from Shared Singleton (LAZY LOADED) ────────────────
_lazy_data = {}

def _get_lazy_data():
    if not _lazy_data:
        from service.prediction_model.model_loader import TrafficModelLoader
        loader = TrafficModelLoader.get_models()
        
        spatial_db = loader.df_nodes
        # Drop rows where latitude or longitude is 0 or NaN
        spatial_db = spatial_db.dropna(subset=['latitude', 'longitude'])
        spatial_db = spatial_db[(spatial_db['latitude'] != 0.0) & (spatial_db['longitude'] != 0.0)]
        spatial_db = spatial_db.reset_index(drop=True)
        
        spatial_cols = [f"spatial_emb_{i}" for i in range(16)]
        
        _lazy_data["ngboost_model"] = loader.ai_model
        _lazy_data["le_cause"] = loader.encoder_cause
        _lazy_data["le_priority"] = loader.encoder_priority
        _lazy_data["spatial_db"] = spatial_db
        _lazy_data["spatial_cols"] = spatial_cols
        _lazy_data["global_avg_embeddings"] = spatial_db[spatial_cols].mean().values
        _lazy_data["global_avg_hist_count"] = float(spatial_db['historical_incident_count'].mean())
        _lazy_data["global_avg_hist_duration"] = float(spatial_db['historical_median_duration'].mean())
        
    return _lazy_data


# ── PART 2 — HAVERSINE DISTANCE FUNCTION ──────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2) -> float:
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees) in metres.
    """
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371000.0 * c

# ── PART 3 — SPATIAL RESOLVER FUNCTION ────────────────────────────────────────
def resolve_spatial_embeddings(lat: float, lng: float) -> dict:
    """
    Calculates distances from (lat, lng) to every row in SPATIAL_DB
    using vectorised numpy operations (not a Python loop).
    """
    data = _get_lazy_data()
    spatial_db = data["spatial_db"]
    spatial_cols = data["spatial_cols"]
    global_avg_embeddings = data["global_avg_embeddings"]
    global_avg_hist_count = data["global_avg_hist_count"]
    global_avg_hist_duration = data["global_avg_hist_duration"]

    # Step 1: Compute distance from input point to all rows in SPATIAL_DB
    dlat = np.radians(spatial_db['latitude'] - lat)
    dlon = np.radians(spatial_db['longitude'] - lng)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat)) * np.cos(np.radians(spatial_db['latitude'])) * np.sin(dlon/2)**2
    distances = 6371000.0 * 2.0 * np.arcsin(np.sqrt(a))
    
    # Step 2: Find the nearest row and its distance
    nearest_idx = distances.idxmin()
    nearest_distance = float(distances[nearest_idx])
    nearest_row = spatial_db.loc[nearest_idx]
    nearest_junction_name = str(nearest_row['junction']) if pd.notna(nearest_row['junction']) else ""

    # Step 3: EXACT MATCH — if nearest_distance <= 500 metres:
    if nearest_distance <= 500.0:
        embeddings = nearest_row[spatial_cols].values.astype(float)
        hist_count = float(nearest_row['historical_incident_count'])
        hist_duration = float(nearest_row['historical_median_duration'])
        
        # If NaN, fallback to global averages
        if np.isnan(embeddings).any():
            nan_mask = np.isnan(embeddings)
            embeddings[nan_mask] = global_avg_embeddings[nan_mask]
        if np.isnan(hist_count):
            hist_count = global_avg_hist_count
        if np.isnan(hist_duration):
            hist_duration = global_avg_hist_duration

        return {
            "embeddings": embeddings,
            "historical_incident_count": hist_count,
            "historical_median_duration": hist_duration,
            "method": "exact_match",
            "nearest_junction": nearest_junction_name,
            "distance_m": nearest_distance
        }
    
    # Step 4: PROXIMITY AVERAGE — if nearest_distance > 500m:
    else:
        # Find all rows within 1000 metres (1km).
        nearby_mask = distances <= 1000.0
        nearby = spatial_db[nearby_mask]
        
        if len(nearby) >= 1:
            embeddings = nearby[spatial_cols].mean().values.astype(float)
            hist_count = float(nearby['historical_incident_count'].mean())
            hist_duration = float(nearby['historical_median_duration'].mean())
            
            # If NaN, fallback to global averages
            if np.isnan(embeddings).any():
                nan_mask = np.isnan(embeddings)
                embeddings[nan_mask] = global_avg_embeddings[nan_mask]
            if np.isnan(hist_count):
                hist_count = global_avg_hist_count
            if np.isnan(hist_duration):
                hist_duration = global_avg_hist_duration

            return {
                "embeddings": embeddings,
                "historical_incident_count": hist_count,
                "historical_median_duration": hist_duration,
                "method": "proximity_average",
                "nearest_junction": nearest_junction_name,
                "distance_m": nearest_distance
            }
        else:
            # If nearby is empty (truly isolated location):
            return {
                "embeddings": global_avg_embeddings.astype(float),
                "historical_incident_count": global_avg_hist_count,
                "historical_median_duration": global_avg_hist_duration,
                "method": "global_average",
                "nearest_junction": "global_average",
                "distance_m": nearest_distance
            }

# ── PART 4 — FEATURE ASSEMBLY FUNCTION ────────────────────────────────────────
def build_feature_vector(incident: IncidentInput) -> tuple[np.ndarray, dict]:
    """
    Assemble the feature vector in exact order (21 features) and resolve embeddings if needed.
    """
    data = _get_lazy_data()
    le_cause = data["le_cause"]
    le_priority = data["le_priority"]
    global_avg_hist_count = data["global_avg_hist_count"]
    global_avg_hist_duration = data["global_avg_hist_duration"]

    # Check if spatial embeddings are provided in the incident input.
    # A value is "provided" if spatial_emb_0 is not None.
    if incident.spatial_emb_0 is not None:
        spatial_emb_list = [
            incident.spatial_emb_0, incident.spatial_emb_1, incident.spatial_emb_2, incident.spatial_emb_3,
            incident.spatial_emb_4, incident.spatial_emb_5, incident.spatial_emb_6, incident.spatial_emb_7,
            incident.spatial_emb_8, incident.spatial_emb_9, incident.spatial_emb_10, incident.spatial_emb_11,
            incident.spatial_emb_12, incident.spatial_emb_13, incident.spatial_emb_14, incident.spatial_emb_15
        ]
        emb = np.array(spatial_emb_list, dtype=float)
        
        spatial_info = {
            "method": "exact_match",
            "nearest_junction": incident.junction or "provided_by_client",
            "distance_m": 0.0
        }
        hist_count = incident.historical_incident_count if incident.historical_incident_count is not None else global_avg_hist_count
        hist_duration = incident.historical_median_duration if incident.historical_median_duration is not None else global_avg_hist_duration
    else:
        resolved = resolve_spatial_embeddings(incident.latitude, incident.longitude)
        emb = resolved["embeddings"]
        hist_count = resolved["historical_incident_count"]
        hist_duration = resolved["historical_median_duration"]
        spatial_info = {
            "method": resolved["method"],
            "nearest_junction": resolved["nearest_junction"],
            "distance_m": resolved["distance_m"]
        }
        
    # Encode categorical features:
    # cause_enc = le_cause.transform([incident.event_cause])[0]
    #   (if unknown cause, default to le_cause.transform(['others'])[0])
    if incident.event_cause in le_cause.classes_:
        cause_enc = le_cause.transform([incident.event_cause])[0]
    else:
        cause_enc = le_cause.transform(['others'])[0]
        
    # priority_enc = le_priority.transform([incident.priority])[0]
    #   (if unknown priority, default to le_priority.transform(['Low'])[0])
    if incident.priority in le_priority.classes_:
        priority_enc = le_priority.transform([incident.priority])[0]
    else:
        priority_enc = le_priority.transform(['Low'])[0]
        
    # Assemble feature vector in EXACT ORDER (21 features):
    feature_vector = np.array([
        cause_enc,
        priority_enc,
        incident.hour_of_day,
        emb[0], emb[1], emb[2], emb[3], emb[4], emb[5], emb[6], emb[7],
        emb[8], emb[9], emb[10], emb[11], emb[12], emb[13], emb[14], emb[15],
        hist_count,
        hist_duration
    ], dtype=float).reshape(1, 21)
    
    return feature_vector, spatial_info

# ── PART 5 — PREDICT FUNCTION ─────────────────────────────────────────────────
def predict_duration(incident: IncidentInput) -> dict:
    """
    Predict traffic incident duration using NGBoost model and spatial indexing features.
    """
    data = _get_lazy_data()
    ngboost_model = data["ngboost_model"]

    feature_vector, spatial_info = build_feature_vector(incident)
    predicted_mins = float(ngboost_model.predict(feature_vector)[0])
    
    return {
        "predicted_duration_mins": predicted_mins,
        "spatial_resolution_method": spatial_info["method"],
        "nearest_junction": spatial_info["nearest_junction"],
        "distance_to_nearest_m": spatial_info["distance_m"]
    }

# ── Legacy Prediction Request Support ──────────────────────────────────────────
# Keep this for backward compatibility with routers/predictions.py

_DAY_MAP = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}

_WEATHER_MAP = {
    "Clear": 0, "Cloudy": 1, "Fog": 2, "Rain": 3, "Heavy Rain": 4,
}

_ROAD_MAP = {
    "National Highway": 5, "Ring Road": 4, "Inner Ring Road": 3,
    "State Highway": 2, "Arterial Road": 1, "Local Road": 0,
}

def _mock_predict(req) -> dict:
    base = 3.0
    if req.is_peak_hour:           base += 2.0
    if req.weather.value == "Rain":        base += 1.5
    if req.weather.value == "Heavy Rain":  base += 3.0
    if req.weather.value == "Fog":         base += 1.0
    if req.road_works_active:      base += 1.5
    if req.accident_last_24h:      base += 1.0
    if req.is_holiday:             base -= 1.5

    severity = min(max(round(base, 2), 0.0), 10.0)

    # Derive priority
    if severity >= 8:   priority = "Critical"
    elif severity >= 6: priority = "High"
    elif severity >= 4: priority = "Medium"
    else:               priority = "Low"

    causes = ["Traffic Congestion", "Road Accident", "Road Works",
              "Waterlogging", "Signal Failure", "VIP Movement"]
    cause_idx = (req.hour + int(req.is_peak_hour) * 2) % len(causes)

    return {
        "predicted_cause":    causes[cause_idx],
        "predicted_priority": priority,
        "severity_score":     severity,
        "confidence":         0.72,
        "severity_lower":     max(0.0, severity - 1.5),
        "severity_upper":     min(10.0, severity + 1.5),
    }

def predict(req) -> dict:
    return _mock_predict(req)
