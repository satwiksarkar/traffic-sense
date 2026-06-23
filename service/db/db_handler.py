import os
import sqlite3
from .util import compute_spatial_clusters

class TrafficReportManager:
    def __init__(self, DATA_BASE_DIR, consolidation_threshold=10):
        os.makedirs(DATA_BASE_DIR, exist_ok=True)
        self.report_db_path = os.path.join(DATA_BASE_DIR, 'traffic_system.db')
        self.threshold = consolidation_threshold
        self._init_db()

    def get_db_dir(self):
        return os.path.dirname(self.report_db_path)
        
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

                try:
                    cursor.execute("ALTER TABLE traffic_reports ADD COLUMN barricaded INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute("ALTER TABLE active_incidents ADD COLUMN barricaded INTEGER DEFAULT 0")
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

    def delete_report(self, report_id):
        """
        Deletes a report from the database. Handles plain integers or prefixed string IDs 
        such as 'raw_12' or 'cluster_5' directly matching frontend combined lists.
        """
        try:
            string_id = str(report_id).strip()
            target_table = None
            clean_id = None

            # Determine targeting schema
            if string_id.startswith("cluster_"):
                target_table = "active_incidents"
                clean_id = string_id.replace("cluster_", "")
            elif string_id.startswith("raw_"):
                target_table = "traffic_reports"
                clean_id = string_id.replace("raw_", "")
            else:
                clean_id = string_id

            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                
                # If specific prefix was found, target only that table
                if target_table:
                    cursor.execute(f"DELETE FROM {target_table} WHERE id = ?", (clean_id,))
                else:
                    # Fallback structural attempt across both if no prefix matched
                    cursor.execute("DELETE FROM traffic_reports WHERE id = ?", (clean_id,))
                    raw_count = cursor.rowcount
                    cursor.execute("DELETE FROM active_incidents WHERE id = ?", (clean_id,))
                    cluster_count = cursor.rowcount
                    
                    if raw_count > 0 or cluster_count > 0:
                        conn.commit()
                        return True, f"Report ID {clean_id} dropped successfully."
                    return False, f"No report found matching ID {clean_id}."

                conn.commit()
                if cursor.rowcount > 0:
                    return True, f"Successfully deleted {string_id}."
                return False, f"Record {string_id} not found in database."

        except sqlite3.Error as e:
            return False, f"Database deletion transaction failed: {str(e)}"

    def get_active_incidents(self):
        """Returns all active incidents, combining consolidated clusters and raw individual reports."""
        import math
        from datetime import datetime

        def get_minutes_ago(timestamp_str):
            try:
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                diff = datetime.utcnow() - dt
                return max(0, int(diff.total_seconds() / 60))
            except Exception:
                return 0

        def get_distance_km(lat1, lng1):
            try:
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
                    SELECT id, issue_type, mean_lat, mean_lng, report_count, location_name, description, priority, last_updated, barricaded
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
                        "last_updated": row['last_updated'],
                        "barricaded": row['barricaded'] if 'barricaded' in row.keys() else 0
                    })

                # 2. Fetch raw unclustered reports
                cursor.execute('''
                    SELECT id, issue_type, lat, lng, location_name, description, priority, timestamp, barricaded
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
                        "last_updated": row['timestamp'],
                        "barricaded": row['barricaded'] if 'barricaded' in row.keys() else 0
                    })
        except sqlite3.Error as e:
            print(f"[DB Read Error]: {e}")

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

        consolidated_clusters, processed_raw_ids = compute_spatial_clusters(reports, radius_km=0.5)

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

    def toggle_barricade(self, report_id, status: int):
        """Updates the barricaded state of a report in the sqlite database."""
        try:
            string_id = str(report_id).strip()
            target_table = None
            clean_id = None

            if string_id.startswith("cluster_"):
                target_table = "active_incidents"
                clean_id = string_id.replace("cluster_", "")
            elif string_id.startswith("raw_"):
                target_table = "traffic_reports"
                clean_id = string_id.replace("raw_", "")
            else:
                clean_id = string_id

            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                if target_table:
                    cursor.execute(f"UPDATE {target_table} SET barricaded = ? WHERE id = ?", (status, clean_id))
                else:
                    cursor.execute("UPDATE traffic_reports SET barricaded = ? WHERE id = ?", (status, clean_id))
                    cursor.execute("UPDATE active_incidents SET barricaded = ? WHERE id = ?", (status, clean_id))
                conn.commit()
                return True, f"Barricade status updated to {status} for ID {string_id}."
        except sqlite3.Error as e:
            return False, f"Failed to update barricade status: {str(e)}"

from datetime import datetime, timezone
import os
import sqlite3
from service.news_handler.collect_news import process_news

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

    def purge_old_news(self):
        """Deletes any records from traffic_reports that are older than 24 hours."""
        try:
            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                # Targets rows older than 24 hours relative to modern UTC standards
                cursor.execute('''
                    DELETE FROM traffic_reports 
                    WHERE datetime(timestamp) < datetime('now', '-1 day')
                ''')
                deleted_rows = cursor.rowcount
                if deleted_rows > 0:
                    print(f"[Garbage Collector]: Purged {deleted_rows} expired news reports older than 24 hours.")
                conn.commit()
        except sqlite3.Error as e:
            print(f"[Garbage Collector Error]: Failed to clean old news data: {e}")

    def _geocode_location(self, location_name):
        """Placeholder method to convert a location name string into coordinates."""
        return 20.5937, 78.9629

    def insert_external_news(self, issue_type: str, description: str, location_name: str = None, lat: float = None, lng: float = None, priority: str = "LOW", timestamp: str = None):
        """
        Public endpoint function to manually insert an external singular news story into the database.
        Automatically resolves coordinates using geocoding if lat/lng are missing.
        """
        try:
            # Fallback to defaults or geocoding if coordinate metadata isn't provided
            loc_name = location_name if location_name else "India (General)"
            if lat is None or lng is None:
                lat, lng = self._geocode_location(loc_name)

            with sqlite3.connect(self.report_db_path) as conn:
                cursor = conn.cursor()
                
                if timestamp:
                    cursor.execute('''
                        INSERT INTO traffic_reports (
                            issue_type, lat, lng, location_name, description, priority, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (issue_type, lat, lng, loc_name, description, priority, timestamp))
                else:
                    cursor.execute('''
                        INSERT INTO traffic_reports (
                            issue_type, lat, lng, location_name, description, priority
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    ''', (issue_type, lat, lng, loc_name, description, priority))
                
                conn.commit()
            return True, "External news story saved successfully."
        except sqlite3.Error as e:
            return False, f"Database Write Error: {str(e)}"

    def insert_news(self):
        """Purges old records, then fetches and logs the latest news stories."""
        # Clean out yesterdays stories first
        self.purge_old_news()

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
                conn.row_factory = sqlite3.Row
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