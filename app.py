import os
import time
import threading
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_FOLDER = os.path.join(ROOT_DIR, "frontend")
DATA_BASE_DIR = os.path.join(ROOT_DIR, "database")

FASTAPI_URL = "http://127.0.0.1:8000"

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

# ── NOW RUN YOUR ORIGINAL IMPORTS WITHOUT ANY ALTERATIONS ──
from model import resolve_spatial_embeddings, predict_duration
# From here down, the rest of your original imports...

# ── NOW YOUR ORIGINAL IMPORTS WILL WORK CLEANLY ──
# From here down, your existing imports continue...

# Import handlers safely
from service.db.db_handler import TrafficReportManager, NewsReportManager
from service.route_recomend.route_management import RouteManager
from service.traffic_assignment.traffic_assignment import TrafficAssignmentManager
from service.db.util import load_city_traffic_stations
from service.route_recomend.util import create_city_graph

from backend.query import process_single_news_item


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

    # Initialize city graph once at app startup for route calculations
    print("[App Initialization]: Loading Bangalore city graph...")
    city_graph = create_city_graph(
        os.path.join(ROOT_DIR, "map_cache"), city_name="Bangalore"
    )
    if city_graph:
        app.route_manager = RouteManager(city_graph)
        print("[App Initialization]: ✓ Route manager initialized with city graph")
    else:
        print(
            "[App Initialization]: ⚠ Failed to load city graph - routing will be limited"
        )
        app.route_manager = None

    # Start the daemonized background loop thread
    sync_thread = threading.Thread(
        target=news_sync_worker, args=(app.news_report_manager,), daemon=True
    )
    sync_thread.start()

    return app


app = create_app(DATA_BASE_DIR, FRONTEND_FOLDER)


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

    success, message = app.news_report_manager.insert_external_news(
        issue_type=data.get("issue_type"),
        description=data.get("description"),
        location_name=data.get("location_name"),
        lat=data.get("lat"),
        lng=data.get("lng"),
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

    success, message = app.traffic_report_manager.insert_traffic_report(
        issue_type=event_cause,
        lat=lat,
        lng=lng,
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

    # Use the pre-initialized route manager from app context
    if not app.route_manager:
        return jsonify({"error": "Route manager not initialized"}), 500

    assignment_mgr = TrafficAssignmentManager(
        report_manager=app.traffic_report_manager,
        news_manager=app.news_report_manager,
        route_manager=app.route_manager,
    )

    active_assignments = assignment_mgr.assign_reports(city_name=city)
    return jsonify({"assignments": active_assignments})


@app.route("/get_route_status", methods=["GET"])
def get_route_status():
    """Returns route status with full polylines for active incidents."""
    city = request.args.get("city", "Bangalore")

    if not app.route_manager:
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
            assignment = app.route_manager.assign_station_to_incident(
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
from backend.query import process_single_news_item


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
    # Extract just the hostname (minus the port)
    host_header = request.headers.get("Host") or "127.0.0.1"
    hostname = host_header.split(":")[0]

    # Reconstruct it to force port 8000
    FASTAPI_URL = f"http://{hostname}:8000"

    try:
        fastapi_response = requests.get(f"{FASTAPI_URL}/analytics", timeout=5)
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
    # Extract just the hostname (minus the port)
    host_header = request.headers.get("Host") or "127.0.0.1"
    hostname = host_header.split(":")[0]

    # Reconstruct it to force port 8000
    FASTAPI_URL = f"http://{hostname}:8000"

    try:
        fastapi_response = requests.get(f"{FASTAPI_URL}/api", timeout=5)
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
