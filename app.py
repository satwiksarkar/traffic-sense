import os
import time
import threading
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_FOLDER = os.path.join(ROOT_DIR, "frontend")
DATA_BASE_DIR = os.path.join(ROOT_DIR, "database")

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
    app = Flask(__name__, template_folder=frontend_dir, static_folder=frontend_dir, static_url_path="")
    CORS(app)
    
    app.traffic_report_manager = TrafficReportManager(data_base_dir)
    app.news_report_manager = NewsReportManager(data_base_dir)
    
    # Start the daemonized background loop thread
    sync_thread = threading.Thread(
        target=news_sync_worker, 
        args=(app.news_report_manager,), 
        daemon=True
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
    return render_template("index.html")

@app.route("/get_reports")
def get_reports():
    reports = app.traffic_report_manager.get_active_incidents()
    print(f"------------/get reports : {reports}-----------------")
    return jsonify({"active_reports": reports}), 200

@app.route("/get_news")
def get_news():
    news = app.news_report_manager.get_news()
    return jsonify({"active_news": news}), 200

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
            return jsonify({
                "status": "empty",
                "city": city_name,
                "message": f"No police station logs or asset profiles found for region: '{city_name}'",
                "police_stations": []
            }), 200
            
        return jsonify({
            "status": "success",
            "city": city_name,
            "total_stations": len(stations_list),
            "police_stations": stations_list
        }), 200
        
    except AttributeError:
        # Error handling if app.traffic_report_manager or the db path configuration context is missing
        return jsonify({
            "status": "error",
            "message": "Server database path context manager is uninitialized."
        }), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Unexpected runtime validation error occurred: {str(e)}"
        }), 500

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
        priority=priority
    )

    if success:
        return jsonify({"success": True, "message": message}), 200
    else:
        return jsonify({"success": False, "error": message}), 500

@app.route("/api/assignments")
def get_assignments():
    """API endpoint providing dispatch routes and localized station inventory counts."""
    city = request.args.get("city", "Bangalore")
    
    # Initialize your manager using your existing operational system instances
    assignment_mgr = TrafficAssignmentManager(
        report_manager=app.traffic_report_manager,
        news_manager=app.news_report_manager,
        route_manager=RouteManager(app.traffic_report_manager.get_db_dir())
    )
    
    active_assignments = assignment_mgr.assign_reports(city_name=city)
    return jsonify({"assignments": active_assignments})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)