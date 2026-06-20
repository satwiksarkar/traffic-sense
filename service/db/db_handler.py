import os
import sqlite3
from .util import compute_spatial_clusters

class TrafficReportManager:
    def __init__(self, DATA_BASE_DIR, consolidation_threshold=10):
        os.makedirs(DATA_BASE_DIR, exist_ok=True)
        self.report_db_path = os.path.join(DATA_BASE_DIR, 'traffic_system.db')
        self.threshold = consolidation_threshold
        self._init_db()

    def _init_db(self):
        """Creates the local database schemas if they don't already exist."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS traffic_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        issue_type TEXT NOT NULL,
                        lat REAL NOT NULL,
                        lng REAL NOT NULL,
                        location_name TEXT,
                        description TEXT,
                        priority TEXT DEFAULT 'MEDIUM',
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS active_incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        issue_type TEXT NOT NULL,
                        mean_lat REAL NOT NULL,
                        mean_lng REAL NOT NULL,
                        report_count INTEGER,
                        location_name TEXT,
                        description TEXT,
                        priority TEXT DEFAULT 'MEDIUM',
                        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Perform safe ALTER commands to support existing database migrations
                try:
                    cursor.execute("ALTER TABLE traffic_reports ADD COLUMN priority TEXT DEFAULT 'MEDIUM'")
                except sqlite3.OperationalError:
                    pass

                for col in [("location_name", "TEXT"), ("description", "TEXT"), ("priority", "TEXT DEFAULT 'MEDIUM'")]:
                    try:
                        cursor.execute(f"ALTER TABLE active_incidents ADD COLUMN {col[0]} {col[1]}")
                    except sqlite3.OperationalError:
                        pass

                conn.commit()
        except sqlite3.Error as e:
            print(f"[Offline DB Init Error]: {e}")

    def insert_traffic_report(self, issue_type: str, lat: float, lng: float, location_name: str, description: str, priority: str = "MEDIUM"):
        """Inserts a new raw log and checks if counter limits are reached."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO traffic_reports (issue_type, lat, lng, location_name, description, priority)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (issue_type, lat, lng, location_name, description, priority))
                conn.commit()
                print("report saved to db from insert_traffic_report")
            
            self._check_and_consolidate()
            return True, "Report successfully saved locally"
        except sqlite3.Error as e:
            return False, f"Offline Storage Error: {str(e)}"

    def get_active_incidents(self):
        """Returns all active incidents, combining consolidated clusters and raw individual reports."""
        import math
        from datetime import datetime

        def get_minutes_ago(timestamp_str):
            try:
                # Parse SQLite default CURRENT_TIMESTAMP format
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                diff = datetime.utcnow() - dt
                return max(0, int(diff.total_seconds() / 60))
            except Exception:
                return 0

        def get_distance_km(lat1, lng1):
            try:
                # Bangalore center coordinates
                lat2, lng2 = 12.9716, 77.5946
                R = 6371.0
                dlat = math.radians(lat2 - lat1)
                dlng = math.radians(lng2 - lng1)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                return round(R * c, 1)
            except Exception:
                return 0.0

        def get_officers_count(priority, count=1):
            if count > 1:
                return count * 2
            p = (priority or 'MEDIUM').upper()
            if p == 'HIGH':
                return 5
            if p == 'LOW':
                return 1
            return 3

        combined_reports = []
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 1. Fetch consolidated active incidents
                cursor.execute('''
                    SELECT id, issue_type, mean_lat, mean_lng, report_count, location_name, description, priority, last_updated
                    FROM active_incidents
                    ORDER BY last_updated DESC
                ''')
                cluster_rows = cursor.fetchall()
                for row in cluster_rows:
                    lat = row['mean_lat']
                    lng = row['mean_lng']
                    priority = row['priority'] or 'MEDIUM'
                    minutes_ago = get_minutes_ago(row['last_updated'])
                    distance_km = get_distance_km(lat, lng)
                    officers = get_officers_count(priority, row['report_count'])
                    
                    combined_reports.append({
                        "id": f"cluster_{row['id']}",
                        "issue_type": row['issue_type'],
                        "lat": lat,
                        "lng": lng,
                        "location_name": row['location_name'] or f"Consolidated {row['issue_type']}",
                        "description": row['description'] or "",
                        "priority": priority,
                        "report_count": row['report_count'],
                        "minutes_ago": minutes_ago,
                        "distance_km": distance_km,
                        "officers": officers,
                        "last_updated": row['last_updated']
                    })

                # 2. Fetch raw unclustered reports
                cursor.execute('''
                    SELECT id, issue_type, lat, lng, location_name, description, priority, timestamp
                    FROM traffic_reports
                    ORDER BY timestamp DESC
                ''')
                raw_rows = cursor.fetchall()
                for row in raw_rows:
                    lat = row['lat']
                    lng = row['lng']
                    priority = row['priority'] or 'MEDIUM'
                    minutes_ago = get_minutes_ago(row['timestamp'])
                    distance_km = get_distance_km(lat, lng)
                    officers = get_officers_count(priority, 1)
                    
                    combined_reports.append({
                        "id": f"raw_{row['id']}",
                        "issue_type": row['issue_type'],
                        "lat": lat,
                        "lng": lng,
                        "location_name": row['location_name'] or "Dropped pin",
                        "description": row['description'] or "",
                        "priority": priority,
                        "report_count": 1,
                        "minutes_ago": minutes_ago,
                        "distance_km": distance_km,
                        "officers": officers,
                        "last_updated": row['timestamp']
                    })
        except sqlite3.Error as e:
            print(f"[DB Read Error]: {e}")

        # Sort combined reports by last_updated DESC
        combined_reports.sort(key=lambda x: x['last_updated'], reverse=True)
        return combined_reports

    def resolve_incident(self, incident_id: int):
        """Removes a resolved incident cluster from active tracking."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM active_incidents WHERE id = ?', (incident_id,))
                conn.commit()
                if cursor.rowcount:
                    return True, "Incident resolved successfully."
                return False, "Incident not found."
        except sqlite3.Error as e:
            return False, f"Database update error: {e}"

    def _get_raw_report_count(self):
        with sqlite3.connect(self.report_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM traffic_reports")
            return cursor.fetchone()[0]

    def _check_and_consolidate(self):
        if self._get_raw_report_count() >= self.threshold:
            print(f"[System Log]: Counter hit threshold ({self.threshold}). Invoking automated sweep...")
            self.consolidate_and_replace()

    def consolidate_and_replace(self):
        """Fetches active rows, passes them to the util module, and handles structural table updates."""
        with sqlite3.connect(self.report_db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, issue_type, lat, lng, location_name, description, priority FROM traffic_reports")
            reports = [dict(row) for row in cursor.fetchall()]

        if not reports:
            return

        # Core Clustering Separation Call
        consolidated_clusters, processed_raw_ids = compute_spatial_clusters(reports, radius_km=0.5)

        # Write clean data and flush processed individual raw tracks out under a safe transaction
        if consolidated_clusters:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("BEGIN TRANSACTION")

                    for cluster in consolidated_clusters:
                        cursor.execute('''
                            INSERT INTO active_incidents (issue_type, mean_lat, mean_lng, report_count, location_name, description, priority)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (cluster['issue_type'], cluster['mean_lat'], cluster['mean_lng'], cluster['count'], cluster['location_name'], cluster['description'], cluster['priority']))

                    if processed_raw_ids:
                        placeholders = ', '.join('?' for _ in processed_raw_ids)
                        cursor.execute(f"DELETE FROM traffic_reports WHERE id IN ({placeholders})", processed_raw_ids)

                    conn.commit()
                    print("[System Log]: Swap executed. Cluster nodes calculated successfully.")
                except sqlite3.Error as e:
                    conn.rollback()
                    print(f"[System Transaction Error]: Processing aborted and rolled back: {e}")


from datetime import datetime, timezone
from service.news_handler.collect_news import process_news  # Assuming process_news is the entry point

class NewsReportManager:
    def __init__(self, DATA_BASE_DIR, consolidation_threshold=10):
        os.makedirs(DATA_BASE_DIR, exist_ok=True)
        self.report_db_path = os.path.join(DATA_BASE_DIR, 'news.db')
        self.threshold = consolidation_threshold
        self._init_db()

    def _init_db(self):
        """Creates the local database schemas if they don't already exist."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS traffic_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        issue_type TEXT NOT NULL,
                        lat REAL NOT NULL,
                        lng REAL NOT NULL,
                        location_name TEXT,
                        description TEXT,
                        priority TEXT DEFAULT 'MEDIUM',
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS active_incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        issue_type TEXT NOT NULL,
                        mean_lat REAL NOT NULL,
                        mean_lng REAL NOT NULL,
                        report_count INTEGER,
                        location_name TEXT,
                        description TEXT,
                        priority TEXT DEFAULT 'MEDIUM',
                        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Perform safe ALTER commands to support existing database migrations
                try:
                    cursor.execute("ALTER TABLE traffic_reports ADD COLUMN priority TEXT DEFAULT 'MEDIUM'")
                except sqlite3.OperationalError:
                    pass

                for col in [("location_name", "TEXT"), ("description", "TEXT"), ("priority", "TEXT DEFAULT 'MEDIUM'")]:
                    try:
                        cursor.execute(f"ALTER TABLE active_incidents ADD COLUMN {col[0]} {col[1]}")
                    except sqlite3.OperationalError:
                        pass

                conn.commit()
        except sqlite3.Error as e:
            print(f"[Offline DB Init Error]: {e}")

    def _geocode_location(self, location_name):
        """
        Placeholder method to convert a location name string into coordinates.
        Replace this with an actual geocoding service (like geopy or an internal lookup dictionary).
        """
        # Return mock coordinates for India center region as a fallback
        return 20.5937, 78.9629

    def insert_news(self):
        """Fetches the latest news using the news handler and saves relevant records to the DB."""
        print("[News Handler]: Fetching fresh traffic stories...")
        fetched_events = process_news()
        
        if not fetched_events:
            print("[News Handler]: No traffic events found today.")
            return

        inserted_count = 0
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                
                for event in fetched_events:
                    # Resolve a location name if found, otherwise use a generic fallback
                    loc_name = event["locations"][0] if event["locations"] else "India (General)"
                    lat, lng = self._geocode_location(loc_name)
                    
                    cursor.execute('''
                        INSERT INTO traffic_reports (
                            issue_type, lat, lng, location_name, description, priority, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        event["event_type"],
                        lat,
                        lng,
                        loc_name,
                        event["title"],
                        event["severity"],
                        event.get("published", datetime.now(timezone.utc).isoformat())
                    ))
                    inserted_count += 1
                
                conn.commit()
                print(f"[News Handler]: Successfully stored {inserted_count} reports in database.")
        except sqlite3.Error as e:
            print(f"[News Handler DB Insert Error]: {e}")

    def get_news(self, limit=50):
        """Retrieves collected traffic reports from the database sorted by newest first."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                conn.row_factory = sqlite3.Row  # Returns results as dictionary-accessible items
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, issue_type, lat, lng, location_name, description, priority, timestamp 
                    FROM traffic_reports 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            print(f"[News Handler DB Fetch Error]: {e}")
            return []

# ==========================================================
# EXECUTION EXAMPLE
# ==========================================================
if __name__ == "__main__":
    # Setup manager instance pointing to a local directory
    manager = NewsReportManager(DATA_BASE_DIR="./data")
    
    # 1. Fetch live RSS items and record them into your local sqlite file
    manager.insert_news()
    
    # 2. Extract and inspect whatever was saved inside the db file
    saved_reports = manager.get_news(limit=5)
    print("\n--- RECENT STORED ENTRIES ---")
    for report in saved_reports:
        print(f"[{report['priority']}] {report['issue_type']} at {report['location_name']}: {report['description']}")