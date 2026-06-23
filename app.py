import os
import sys
import time
import threading
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# Load environment variables
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, "backend", ".env"))

FRONTEND_FOLDER = os.path.join(ROOT_DIR, "frontend")
DATA_BASE_DIR = os.path.join(ROOT_DIR, "database")

PORT = os.getenv("PORT", "8000")
FASTAPI_URL = f"http://127.0.0.1:{PORT}"

import sys

# 1. Capture absolute paths for the backend package and root workspace directory
backend_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.dirname(backend_dir)
# Path to the backend folder containing model.py
backend_pkg_dir = os.path.join(backend_dir, "backend")

# 2. Append them explicitly into runtime path trackers to prevent execution module isolation
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
# Ensure the actual `backend` subfolder is on the import path so `import model` succeeds
if backend_pkg_dir not in sys.path:
    sys.path.insert(0, backend_pkg_dir)

# Unused model imports removed to enable lazy loading optimization

# Import handlers safely
from service.db.db_handler import TrafficReportManager, NewsReportManager
from service.route_recomend.route_management import RouteManager
from service.traffic_assignment.traffic_assignment import TrafficAssignmentManager
from service.db.util import load_city_traffic_stations
from service.route_recomend.util import create_city_graph




def news_sync_worker(news_manager):
    """Background task loop that runs continuously every 24 hours."""
    print("[Thread System]: News Synchronization Background Worker Started.")
    while True:
        try:
            # Executes data cleanup and fetches incoming news
            news_manager.insert_news()
        except Exception as e:
            print(f"[Thread System Worker Exception Error]: {e}")

        # Sleep for exactly 24 hours (86400 seconds) before performing next check
        time.sleep(86400)


def create_app(data_base_dir, frontend_dir):
    app = Flask(
        __name__,
        template_folder=frontend_dir,
        static_folder=frontend_dir,
        static_url_path="",
    )
    CORS(app)

    app.traffic_report_manager = TrafficReportManager(data_base_dir)
    app.news_report_manager = NewsReportManager(data_base_dir)

    # Set placeholder for lazy loading RouteManager to optimize memory footprint
    app.route_manager = None
    app.route_manager_loaded = False

    # Start the daemonized background loop thread
    sync_thread = threading.Thread(
        target=news_sync_worker, args=(app.news_report_manager,), daemon=True
    )
    sync_thread.start()

    return app


app = create_app(DATA_BASE_DIR, FRONTEND_FOLDER)


route_manager_lock = threading.Lock()

def get_route_manager():
    """Lazy loads and returns the RouteManager instance to save startup memory."""
    global route_manager_lock
    if not getattr(app, "route_manager_loaded", False):
        with route_manager_lock:
            if not getattr(app, "route_manager_loaded", False):
                # Check if running in a memory-limited environment like Render
                limit_ram = os.getenv("RENDER") is not None or os.getenv("LIMIT_RAM", "false").lower() == "true"
                city_graph = None
                
                if limit_ram:
                    print("[Lazy Ingestion]: ⚠️ RAM limit detected (Render environment). Skipping heavy map graph loading to prevent 502/OOM crashes.")
                else:
                    print("[Lazy Ingestion]: Loading Bangalore city graph on demand...")
                    try:
                        city_graph = create_city_graph(
                            os.path.join(ROOT_DIR, "map_cache"), city_name="Bangalore"
                        )
                    except Exception as e:
                        print(f"[Lazy Ingestion Error]: Failed to create city graph: {e}")
                
                # Always initialize RouteManager (with None if limited) so assignments endpoint doesn't fail
                app.route_manager = RouteManager(city_graph)
                if city_graph:
                    print("[Lazy Ingestion]: ✓ Route manager initialized with city graph")
                else:
                    print("[Lazy Ingestion]: ⚠ Route manager initialized without city graph (fallback routing active)")
                app.route_manager_loaded = True
    return app.route_manager



@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/officer-dashboard")
def officer_dashboard():
    return render_template("main.html")


@app.route("/get_reports")
def get_reports():
    reports = app.traffic_report_manager.get_active_incidents()
    print(f"------------/get reports : {reports}-----------------")
    return jsonify({"active_reports": reports}), 200


@app.route("/get_news")
def get_news():
    news = app.news_report_manager.get_news()
    return jsonify({"active_news": news}), 200


@app.route("/save_news", methods=["POST"])
def save_news():
    data = request.get_json()
    if not data or not data.get("issue_type") or not data.get("description"):
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    lat_val = data.get("lat")
    lng_val = data.get("lng")
    try:
        lat_val = float(lat_val) if (lat_val is not None and str(lat_val).strip() != "") else None
    except (ValueError, TypeError):
        lat_val = None

    try:
        lng_val = float(lng_val) if (lng_val is not None and str(lng_val).strip() != "") else None
    except (ValueError, TypeError):
        lng_val = None

    success, message = app.news_report_manager.insert_external_news(
        issue_type=data.get("issue_type"),
        description=data.get("description"),
        location_name=data.get("location_name"),
        lat=lat_val,
        lng=lng_val,
        priority=data.get("priority", "LOW"),
        timestamp=data.get("timestamp"),
    )

    if success:
        return jsonify({"success": True, "message": message}), 200
    return jsonify({"success": False, "error": message}), 500


# Assuming this route is added inside your main app file or a blueprint
@app.route("/api/police_stations", methods=["GET"])
def get_all_police_stations():
    """
    API endpoint to retrieve the complete inventory profile,
    names, and geographical coordinates for all traffic police stations in a city.
    """
    # Fallback to 'Bangalore' if no query parameter is provided
    city_name = request.args.get("city", "Bangalore")

    try:
        # Resolve path directory from your app configuration state or report manager
        db_dir = app.traffic_report_manager.get_db_dir()

        # Load the raw profiles out of your target JSON schema infrastructure
        stations_list = load_city_traffic_stations(db_dir, city=city_name)

        if not stations_list:
            return jsonify(
                {
                    "status": "empty",
                    "city": city_name,
                    "message": f"No police station logs or asset profiles found for region: '{city_name}'",
                    "police_stations": [],
                }
            ), 200

        return jsonify(
            {
                "status": "success",
                "city": city_name,
                "total_stations": len(stations_list),
                "police_stations": stations_list,
            }
        ), 200

    except AttributeError:
        # Error handling if app.traffic_report_manager or the db path configuration context is missing
        return jsonify(
            {
                "status": "error",
                "message": "Server database path context manager is uninitialized.",
            }
        ), 500
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "message": f"Unexpected runtime validation error occurred: {str(e)}",
            }
        ), 500


@app.route("/get_police_stations", methods=["GET"])
def get_police_stations():
    """Legacy alias for older frontend clients."""
    return get_all_police_stations()


@app.route("/save_reports", methods=["GET"])
def save_report():
    location_name = request.args.get("location")
    event_cause = request.args.get("event_type")
    description = request.args.get("description", "")
    lat = request.args.get("lat")
    lng = request.args.get("long")
    priority = request.args.get("priority", "MEDIUM")

    if not location_name or not event_cause:
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    try:
        lat_val = float(lat) if (lat and lat.strip()) else 0.0
    except (ValueError, TypeError):
        lat_val = 0.0

    try:
        lng_val = float(lng) if (lng and lng.strip()) else 0.0
    except (ValueError, TypeError):
        lng_val = 0.0

    if lat_val == 0.0 or lng_val == 0.0:
        import random
        # Bangalore center default with small random offset
        lat_val = 12.9716 + random.uniform(-0.03, 0.03)
        lng_val = 77.5946 + random.uniform(-0.03, 0.03)

    success, message = app.traffic_report_manager.insert_traffic_report(
        issue_type=event_cause,
        lat=lat_val,
        lng=lng_val,
        location_name=location_name,
        description=description,
        priority=priority,
    )

    if success:
        return jsonify({"success": True, "message": message}), 200
    else:
        return jsonify({"success": False, "error": message}), 500


@app.route("/api/assignments")
def get_assignments():
    """API endpoint providing dispatch routes and localized station inventory counts."""
    city = request.args.get("city", "Bangalore")

    route_mgr = get_route_manager()
    if not route_mgr:
        return jsonify({"error": "Route manager not initialized"}), 500

    assignment_mgr = TrafficAssignmentManager(
        report_manager=app.traffic_report_manager,
        news_manager=app.news_report_manager,
        route_manager=route_mgr,
    )

    active_assignments = assignment_mgr.assign_reports(city_name=city)
    return jsonify({"assignments": active_assignments})


@app.route("/api/mappls_route")
def mappls_route():
    """Proxy endpoint to resolve Mappls advanced routing without browser CORS restrictions."""
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    
    api_key = os.getenv("MAPPLS_API_KEY")
    if not api_key:
        return jsonify({"error": "MAPPLS_API_KEY environment variable is not set."}), 500
        
    url = f"https://apis.mappls.com/advancedmaps/v1/{api_key}/route_adv/driving/{origin};{destination}?geometries=geojson&steps=true"
    
    try:
        response = requests.get(url, timeout=5)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/toggle_barricade", methods=["POST"])
def toggle_barricade():
    """Toggles barricade status for an incident in the SQLite database."""
    try:
        data = request.get_json()
        if not data or "id" not in data:
            return jsonify({"success": False, "error": "Missing incident 'id' parameter"}), 400
        
        report_id = data["id"]
        status = int(data.get("status", 0)) # 1 for placed, 0 for cleared
        
        success, msg = app.traffic_report_manager.toggle_barricade(report_id, status)
        if success:
            return jsonify({"success": True, "message": msg})
        else:
            return jsonify({"success": False, "error": msg}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/reports/resolve/<report_id>", methods=["POST"])
def resolve_report(report_id):
    """Resolves an incident report by deleting it from Flask database and notifying FastAPI."""
    try:
        success, msg = app.traffic_report_manager.delete_report(report_id)
        if success:
            # Also try to resolve it from the FastAPI backend if it exists there
            try:
                requests.post(f"{FASTAPI_URL}/incidents/resolve/{report_id}", timeout=2)
            except Exception as e:
                print(f"[Backend Sync Warning]: Failed to resolve on FastAPI: {e}")
                
            return jsonify({"success": True, "message": msg})
        else:
            return jsonify({"success": False, "error": msg}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/route_diversion")
def route_diversion():
    """Calculates a dynamic diversion route avoiding other active incidents using OSMnx."""
    origin_lat = request.args.get("origin_lat")
    origin_lng = request.args.get("origin_lng")
    dest_lat = request.args.get("dest_lat")
    dest_lng = request.args.get("dest_lng")
    report_id = request.args.get("report_id")
    barricaded = request.args.get("barricaded") == "true"
    
    route_mgr = get_route_manager()
    if not route_mgr:
        return jsonify({"error": "Route manager not initialized"}), 500
        
    try:
        origin = (float(origin_lat), float(origin_lng))
        destination = (float(dest_lat), float(dest_lng))
        
        if not route_mgr.graph:
            print("[Diversion Route Warning]: Graph not loaded (RAM limited). Returning direct path fallback.")
            return jsonify({"success": True, "route": [origin, destination]})
        
        # Fetch other active reports to penalize
        all_incidents = app.traffic_report_manager.get_active_incidents()
        
        if barricaded:
            other_incidents = all_incidents
        else:
            other_incidents = [inc for inc in all_incidents if inc.get("id") != report_id]
        
        from service.route_recomend.util import shortest_path as sp_with_penalties
        route_coords = sp_with_penalties(
            route_mgr.graph, 
            origin, 
            destination, 
            active_incidents=other_incidents
        )
        
        return jsonify({"success": True, "route": route_coords})
    except Exception as e:
        print(f"[Diversion Route Error]: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/route_planner")
def route_planner():
    """Calculates a detailed route with traffic segment color coding avoiding active blockages."""
    origin_lat = request.args.get("origin_lat")
    origin_lng = request.args.get("origin_lng")
    dest_lat = request.args.get("dest_lat")
    dest_lng = request.args.get("dest_lng")

    route_mgr = get_route_manager()
    if not route_mgr:
        return jsonify({"error": "Route manager not initialized"}), 500

    try:
        origin = (float(origin_lat), float(origin_lng))
        destination = (float(dest_lat), float(dest_lng))

        if not route_mgr.graph:
            print("[Route Planner Warning]: Graph not loaded (RAM limited). Returning direct path fallback.")
            import math
            lat1, lon1 = origin
            lat2, lon2 = destination
            # Simple haversine calculation
            R = 6371000.0  # Earth radius in meters
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            c = 2 * math.asin(math.sqrt(a))
            dist_m = R * c
            duration_s = dist_m / (40.0 / 3.6) # assume 40 km/h speed
            
            fallback_result = {
                "segments": [
                    {
                        "coords": [[lat1, lon1], [lat2, lon2]],
                        "color": "#136327",
                        "weight": 4,
                        "speed": 40.0,
                        "status": "Free Flow (Fallback)",
                        "length_m": round(dist_m, 1),
                        "duration_s": round(duration_s, 1)
                    }
                ],
                "total_distance_km": round(dist_m / 1000.0, 2),
                "total_duration_min": round(duration_s / 60.0, 1)
            }
            return jsonify({"success": True, "result": fallback_result})

        # Fetch all active incidents to penalize
        active_incidents = app.traffic_report_manager.get_active_incidents()

        from service.route_recomend.util import shortest_path_with_traffic
        result = shortest_path_with_traffic(
            route_mgr.graph,
            origin,
            destination,
            active_incidents=active_incidents
        )

        return jsonify({"success": True, "result": result})
    except Exception as e:
        print(f"[Route Planner API Error]: {e}")
        return jsonify({"error": str(e)}), 500



@app.route("/get_route_status", methods=["GET"])
def get_route_status():
    """Returns route status with full polylines for active incidents."""
    city = request.args.get("city", "Bangalore")

    route_mgr = get_route_manager()
    if not route_mgr:
        return jsonify({"error": "Route manager not initialized", "incidents": []}), 200

    active_incidents = app.traffic_report_manager.get_active_incidents()
    results = []

    for inc in active_incidents:
        lat = inc.get("lat") or inc.get("mean_lat")
        lng = inc.get("lng") or inc.get("lng") or inc.get("mean_lng")

        # Skip incidents with invalid coordinates
        try:
            lat_f = float(lat) if lat else None
            lng_f = float(lng) if lng else None
            if lat_f is None or lng_f is None:
                continue
        except (TypeError, ValueError):
            continue

        # Get route from route manager
        try:
            assignment = route_mgr.assign_station_to_incident(
                incident_lat=lat_f, incident_lon=lng_f, city_name=city
            )

            results.append(
                {
                    "report_id": inc.get("id"),
                    "issue_type": inc.get("issue_type"),
                    "priority": inc.get("priority", "MEDIUM"),
                    "location_name": inc.get("location_name") or "Dropped pin",
                    "description": inc.get("description") or "",
                    "coordinates": {"lat": lat_f, "lng": lng_f},
                    "assigned_station": assignment.get("assigned_station"),
                    "station_coordinates": assignment.get("station_location"),
                    "distance_km": assignment.get("distance_km"),
                    "route_polyline": assignment.get("route", [[lat_f, lng_f]]),
                }
            )
        except Exception as e:
            print(
                f"[Route Status Error]: Failed to get route for incident {inc.get('id')}: {e}"
            )
            continue

    return jsonify({"incidents": results})


import random

from flask import jsonify, request



from flask import jsonify, request
import json


@app.route("/api/forcast-result", methods=["POST"])
def forecast_result():
    try:
        news_item = request.get_json()
        if not news_item:
            return jsonify({"error": "No news data provided"}), 400

        # Run your ML & Gemini processing pipelines
        try:
            from backend.query import process_single_news_item

            result = process_single_news_item(news_item)
        except Exception as e:
            print(f"[Backend Warning] Fallback to raw object handling: {e}")
            result = {}

        # Merge object data ensuring no parameters drop off the pipeline map
        response_data = {
            "id": news_item.get("id") or "UNKNOWN",
            "predicted_priority": news_item.get("priority")
            or result.get("priority")
            or "LOW",
            "predicted_cause": news_item.get("event_cause")
            or result.get("event_cause")
            or "Unspecified",
            # Spatial Metrics
            "zone": news_item.get("zone") or "General Area",
            "corridor": news_item.get("corridor") or "Main Corridor",
            "junction": news_item.get("junction") or "General Intersection",
            # Operational Tactical Computations
            "clearance_duration_mins": news_item.get("duration_mins")
            or result.get("predicted_duration_mins")
            or 0,
            "jam_length_km": news_item.get("jam_length_km")
            or result.get("jam_length_km")
            or 0.0,
            "severity_score": news_item.get("severity_score")
            or result.get("severity_score")
            or 0.0,
            "severity_multiplier": news_item.get("severity_multiplier")
            or result.get("severity_multiplier")
            or 1.0,
            "officers_needed": news_item.get("officers_needed")
            or result.get("officers_needed")
            or 0,
            "barricades_needed": news_item.get("barricades_needed")
            or news_item.get("barricade_points")
            or result.get("barricade_points")
            or 0,
            # Historical Analytics
            "historical_count": news_item.get("historical_count") or 0,
            "historical_median_mins": news_item.get("historical_median_mins") or 0,
            # Confidence & Uncertainty Bounds Boundaries
            "severity_lower": result.get("severity_lower")
            or result.get("lower_bound")
            or max(0, int(news_item.get("duration_mins", 0) * 0.85)),
            "severity_upper": result.get("severity_upper")
            or result.get("upper_bound")
            or int(news_item.get("duration_mins", 0) * 1.2),
            "confidence": result.get("confidence") or 0.85,
            # Narrative Analyses (Safeguard raw object's 'llm_analysis' or backend's summaries)
            "llm_summary": news_item.get("llm_analysis")
            or result.get("description")
            or result.get("llm_summary")
            or "No explicit summary.",
            "llm_recommendation": result.get("llm_recommendation")
            or "Deploy units to establish visual confirmation markers.",
            # Structural Lists & Arrays
            "hazards_present": result.get("hazards_present") or [],
            "suggested_diversions": news_item.get("suggested_diversions") or [],
            "timeline": news_item.get("timeline")
            or {"start": "--:--", "modified": "--:--", "resolved": "Pending"},
        }

        return jsonify(response_data)

    except Exception as e:
        print(f"[Backend Error] Evaluation Node pipeline exception: {e}")
        return jsonify({"error": "Inference pipeline failure", "details": str(e)}), 500


@app.route("/api/analysis", methods=["GET"])
def get_traffic_analytics():
    """
    USE CASE: Requests aggregated analytics metrics from FastAPI.
    Fetches complex analytical chart points (like peak congestion periods and distribution lists)
    intended to be displayed on the officer dashboard.

    EXPECTED RETURN JSON SIGNATURE:
    {
      "total_incidents_month": int,
      "avg_predicted_duration": float,
      "most_affected_junction": "string",
      "peak_hour": int,
      "total_resolved": int,
      "total_active": int,
      "avg_severity_multiplier": float,
      "total_officers_deployed": int
    }
    OR (on error):
    {
      "error": "string"
    }
    """
    # Use localhost connection to avoid issues with host proxy on Render
    port = os.getenv("PORT", "8000")
    FASTAPI_URL = f"http://127.0.0.1:{port}"

    try:
        fastapi_response = requests.get(f"{FASTAPI_URL}/analytics/summary", timeout=5)
        if fastapi_response.status_code == 200:
            return jsonify(fastapi_response.json()), 200
        return jsonify(
            {"error": "Failed to fetch analytical metrics"}
        ), fastapi_response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Analytics engine unreachable: {str(e)}"}), 503


@app.route("/api/deployment-analysis", methods=["GET"])
def get_predictive_predictions_history():
    """
    USE CASE: Fetches historical predictions logs stored inside FastAPI database infrastructure.

    EXPECTED RETURN JSON SIGNATURE:
    {
      "locations": [
        {
          "name": "string",
          "lat": float,
          "lng": float
        }
      ],
      "count": int
    }
    OR (on error):
    {
      "error": "string"
    }
    """
    # Use localhost connection to avoid issues with host proxy on Render
    port = os.getenv("PORT", "8000")
    FASTAPI_URL = f"http://127.0.0.1:{port}"

    try:
        fastapi_response = requests.get(f"{FASTAPI_URL}/api/locations", timeout=5)
        if fastapi_response.status_code == 200:
            return jsonify(fastapi_response.json()), 200
        return jsonify(
            {"error": "Failed to load historical database array"}
        ), fastapi_response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Database pipeline communication gap: {str(e)}"}), 503


@app.route("/api/hotspots", methods=["GET"])
def get_hotspots():
    import json

    try:
        path = os.path.join(ROOT_DIR, "backend", "data", "hotspots.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data), 200
        return jsonify([]), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk_table", methods=["GET"])
def get_risk_table():
    import json

    try:
        path = os.path.join(ROOT_DIR, "backend", "data", "risk_table.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data), 200
        return jsonify({}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
