import os
import sys
import asyncio
from datetime import datetime

# Ensure backend directory is in sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from schemas import IncidentInput
from database import SessionLocal
from routers.predict import run_prediction

def process_single_news_item(news_item: dict) -> dict:
    """
    Process a single news item by preparing IncidentInput,
    running the ML prediction pipeline, and returning the result dictionary.
    """
    # 1. Extract and map inputs safely
    lat = news_item.get("lat") or news_item.get("latitude") or 12.9716
    lng = news_item.get("lng") or news_item.get("longitude") or 77.5946
    
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        lat = 12.9716
        
    try:
        lng = float(lng)
    except (TypeError, ValueError):
        lng = 77.5946
        
    event_cause = news_item.get("event_cause") or news_item.get("issue_type") or "others"
    priority = news_item.get("priority") or "Low"
    description = news_item.get("description") or news_item.get("llm_analysis") or ""
    
    # 2. Get hour of day from news timestamp or default to current hour
    hour_of_day = datetime.now().hour
    timestamp_str = news_item.get("timestamp")
    if timestamp_str:
        try:
            # Try parsing ISO timestamp
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            hour_of_day = dt.hour
        except Exception:
            pass
            
    # 3. Build IncidentInput Pydantic model
    incident = IncidentInput(
        event_cause=event_cause,
        priority=priority,
        hour_of_day=hour_of_day,
        description=description,
        latitude=lat,
        longitude=lng,
        address=news_item.get("address") or news_item.get("location_name") or "",
        junction=news_item.get("junction") or "",
        zone=news_item.get("zone") or "",
        corridor=news_item.get("corridor") or ""
    )
    
    # 4. Initialize DB session and run the async prediction pipeline synchronously
    db = SessionLocal()
    try:
        # Create or use existing event loop to execute the prediction
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            
        prediction_output = loop.run_until_complete(run_prediction(incident, db))
        
        # Serialize the Pydantic output model to dict for Flask response rendering
        result = prediction_output.model_dump()
        
        # Keep backward-compatibility keys for flask merge
        result["priority"] = prediction_output.priority
        result["event_cause"] = prediction_output.event_cause
        result["description"] = prediction_output.address
        
        return result
    except Exception as e:
        print(f"[backend.query] News item prediction failed: {e}")
        return {}
    finally:
        db.close()
