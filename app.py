import os
from flask import Flask, render_template,request,jsonify
from flask_cors import CORS

# 1. Get the directory containing app.py (traffic-project/backend)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# 3. Explicitly join ROOT_DIR with the frontend folder
FRONTEND_FOLDER = os.path.join(ROOT_DIR, "frontend")
DATA_BASE_DIR=os.path.join(ROOT_DIR,"database")

from service.db.db_handler import TrafficReportManager,NewsReportManager


def create_app(data_base_dir,frontend_dir):
    app = Flask(__name__, template_folder=frontend_dir)
    CORS(app)
    app.traffic_report_manager=TrafficReportManager(data_base_dir)
    app.news_report_manager=NewsReportManager(data_base_dir)
    return app

app = create_app(DATA_BASE_DIR,FRONTEND_FOLDER)

@app.route("/")
def home():
    # Now Flask will look inside traffic-project/frontend/ for your HTML files
    return render_template("dashboard.html") 

@app.route("/officer-dashboard")
def officer_dashboard():
    return render_template("index.html")

@app.route("/get_reports")
def get_reports():
    reports=app.traffic_report_manager.get_active_incidents()
    return jsonify({"active_reports": reports}), 200

@app.route("/get_news")
def get_news():
    news=app.news_report_manager.get_news()
    return jsonify({"active_news": news}), 200


@app.route("/save_reports", methods=["GET"])
def save_report():
    # 1. Retrieve query parameters
    location_name = request.args.get("location")       # Expected format: "latitude,longitude" (e.g., "37.7749,-122.4194")
    event_cause = request.args.get("event_type")  # Maps to issue_type
    description = request.args.get("description","")
    lat=request.args.get("lat")
    lng=request.args.get("long")

    # Optional field in your current query but not used in insert_traffic_report
    priority = request.args.get("priority", "MEDIUM") 

    # 2. Validate mandatory inputs
    if not location_name or not event_cause:
        return jsonify({"success": False, "error": "Missing required fields: 'location' and 'event_type' are mandatory."}), 400


    
    # 4. Invoke the manager with the correct parameters
    success, message = app.traffic_report_manager.insert_traffic_report(
        issue_type=event_cause,
        lat=lat,
        lng=lng,
        location_name=location_name,
        description=description,
        priority=priority
    )

    # 5. Return appropriate JSON response
    if success:
        return jsonify({"success": True, "message": message}), 200
    else:
        return jsonify({"success": False, "error": message}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)