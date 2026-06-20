"""
Traffic Prediction and Dispatch Service
Provides high-level API for traffic prediction and emergency dispatch
"""

import os
import sys
import requests
import polyline
import numpy as np
from datetime import datetime
from .model_loader import TrafficModelLoader
from .llm_agent import parse_traffic_description

import logging
logger = logging.getLogger(__name__)

class DispatchPlanner:
    """Handles traffic event analysis and dispatch planning"""
    
    CITY_INVENTORY = {
        "total_constables": 150,
        "available_constables": 150,
        "total_barricades": 40,
        "available_barricades": 40
    }
    
    @staticmethod
    def calculate_detour(incident_lat, incident_lon):
        """
        Calculate alternative route around incident using routing APIs.
        Attempts Mappls first, falls back to OSRM.
        
        Args:
            incident_lat: Latitude of incident
            incident_lon: Longitude of incident
            
        Returns:
            dict: Route information with coordinates, distance, duration
        """
        try:
            mappls_key = os.getenv("MAPPLS_API_KEY")
            
            # Simulate a route bypassing the incident
            start_lon, start_lat = incident_lon - 0.015, incident_lat - 0.015
            end_lon, end_lat = incident_lon + 0.015, incident_lat + 0.015
            
            if mappls_key:
                print("[Routing] Using Mappls Enterprise Routing...")
                url = f"https://apis.mappls.com/advancedmaps/v1/{mappls_key}/route_adv/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full"
            else:
                print("[Routing] Using OSRM fallback...")
                url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full"

            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                encoded_polyline = data['routes'][0]['geometry']
                detour_coords = polyline.decode(encoded_polyline)
                
                return {
                    "status": "success",
                    "detour_distance_km": round(data['routes'][0]['distance'] / 1000, 2),
                    "detour_duration_mins": round(data['routes'][0]['duration'] / 60, 1),
                    "route_coordinates": detour_coords 
                }
            return {
                "status": f"route_api_error_{response.status_code}",
                "route_coordinates": []
            }
        except Exception as e:
            print(f"[Routing] Error: {e}")
            return {
                "status": f"routing_failed",
                "error": str(e),
                "route_coordinates": []
            }
    
    @staticmethod
    def dispatch_plan(latitude, longitude, event_cause, priority, description):
        """
        Generate comprehensive dispatch plan for traffic event.
        
        Args:
            latitude: Event latitude
            longitude: Event longitude
            event_cause: Type of incident (accident, construction, etc.)
            priority: Priority level (low, medium, high, critical)
            description: Event description for LLM parsing
            
        Returns:
            dict: Complete dispatch plan with predictions and recommendations
        """
        loader = TrafficModelLoader.get_models()
        
        if not loader.is_ready():
            return {
                "status": "error",
                "message": "Models not loaded. Call TrafficModelLoader.load_models() first."
            }
        
        # Phase 1: Find nearest node in graph
        try:
            distance_degrees, index = loader.spatial_tree.query(
                [latitude, longitude], k=1
            )
            distance_meters = distance_degrees * 111000
            closest_node = loader.df_nodes.iloc[index]
        except Exception as e:
            logger.error(f"Spatial query failed: {e}")
            return {
                "status": "error",
                "message": f"Spatial query failed: {e}"
            }
        
        # Phase 2: Parse description with LLM for enriched context
        try:
            llm_insights = parse_traffic_description(description)
        except Exception as e:
            logger.error(f"LLM parsing failed: {e}")
            llm_insights = {"severity_multiplier": 1.0, "hazards_present": ["unknown"], "special_assets_needed": ["standard_patrol"]}
        
        # Phase 3: Prepare features for ML model prediction
        try:
            severity = llm_insights.get("severity_multiplier", 1.0)
            
            # Encode categorical features
            cause_encoded = loader.encoder_cause.transform([event_cause])[0] if event_cause in loader.encoder_cause.classes_ else 0
            priority_encoded = loader.encoder_priority.transform([priority])[0] if priority in loader.encoder_priority.classes_ else 1
            
            # Get spatial embeddings (use average if missing)
            spatial_emb_cols = [col for col in loader.df_nodes.columns if 'spatial_emb' in col]
            node_embeddings = closest_node[spatial_emb_cols].values if len(spatial_emb_cols) > 0 else list(loader.avg_embeddings.values())
            node_embeddings = np.array(node_embeddings, dtype=float)
            
            # Prepare prediction features
            # Assuming model expects: [cause_encoded, priority_encoded, severity, ...spatial_embeddings, distance, hour]
            hour = datetime.now().hour
            features = np.concatenate([
                [cause_encoded, priority_encoded, severity, distance_meters/1000, hour],
                node_embeddings
            ]).reshape(1, -1)
            
            # Phase 3.5: Get model prediction
            try:
                traffic_pred = loader.ai_model.predict(features)[0]
                traffic_pred = max(0, min(100, float(traffic_pred)))  # Clamp to 0-100
            except Exception as e:
                logger.warning(f"Model prediction failed: {e}, using default")
                traffic_pred = 50 + severity * 10
                
        except Exception as e:
            logger.error(f"Feature preparation failed: {e}")
            traffic_pred = 50
        
        # Phase 4: Calculate routing and detour
        detour_info = DispatchPlanner.calculate_detour(latitude, longitude)
        
        # Phase 5: Compile dispatch plan
        dispatch_plan = {
            "status": "success",
            "event_id": f"EVT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "closest_node": {
                    "distance_meters": round(distance_meters, 1),
                    "node_id": str(closest_node.name) if hasattr(closest_node, 'name') else 'unknown'
                }
            },
            "event_details": {
                "cause": event_cause,
                "priority": priority,
                "description": description,
                "llm_analysis": llm_insights
            },
            "traffic_prediction": {
                "predicted_congestion_level": round(traffic_pred, 2),
                "congestion_category": DispatchPlanner._categorize_congestion(traffic_pred),
                "severity_multiplier": severity
            },
            "routing": detour_info,
            "resource_allocation": {
                "constables_needed": max(1, int(llm_insights.get("severity_multiplier", 1.0) * 2)),
                "barricades_needed": max(0, int(llm_insights.get("severity_multiplier", 1.0) * 1)),
                "available_resources": DispatchPlanner.CITY_INVENTORY
            }
        }
        
        return dispatch_plan
    
    @staticmethod
    def _categorize_congestion(pred_value):
        """Categorize traffic congestion level"""
        if pred_value < 20:
            return "light"
        elif pred_value < 40:
            return "moderate"
        elif pred_value < 70:
            return "heavy"
        else:
            return "critical"


def predict_traffic_impact(latitude, longitude, event_cause, priority, description):
    """
    Main prediction function - simplified interface for traffic impact analysis.
    
    Args:
        latitude: Event latitude
        longitude: Event longitude  
        event_cause: Type of incident
        priority: Priority level
        description: Event description
        
    Returns:
        dict: Dispatch plan with predictions
    """
    try:
        return DispatchPlanner.dispatch_plan(latitude, longitude, event_cause, priority, description)
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
