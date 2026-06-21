import sys
import os

# Python 3.14 protobuf compatibility patch
sys.modules['google._upb._message'] = None

# Ensure both backend/ and root directories are in sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.dirname(backend_dir)

if backend_dir not in sys.path:
    sys.path.append(backend_dir)
if base_dir not in sys.path:
    sys.path.append(base_dir)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.wsgi import WSGIMiddleware
from routers import predictions, predict, resources, incidents, analytics, routing
from database import engine, Base, SessionLocal
from db_models import seed_resources
from websocket_manager import manager
from app import app as flask_app


app = FastAPI(
    title="Bengaluru Traffic Incident Prediction API",
    description="AI-powered traffic incident prediction system for Bengaluru using NGBoost + Gemini LLM",
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow all origins so the standalone frontend (file:// or any dev server) can
# reach this API without CORS errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(predictions.router, prefix="/api", tags=["predictions"])
app.include_router(predict.router, prefix="/predict", tags=["predict"])
app.include_router(resources.router, prefix="/resources", tags=["resources"])
app.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(routing.router, prefix="/routing", tags=["routing"])



# ── Startup Event ─────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    # 1. Create tables if they do not exist
    Base.metadata.create_all(bind=engine)
    # 2. Seed default resources
    db = SessionLocal()
    try:
        seed_resources(db)
    finally:
        db.close()


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
def health_check():
    """Simple liveness probe used by the frontend to verify the backend is up."""
    return {"status": "ok"}


# Commented out root route to let the Flask frontend load at "/"
# @app.get("/", tags=["meta"])
# def root():
#     return {
#         "message": "Bengaluru Traffic Incident Prediction API",
#         "docs": "/docs",
#         "health": "/health",
#     }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    db = SessionLocal()
    try:
        from db_models import Incident
        from routers.incidents import format_incident
        active = db.query(Incident).filter(Incident.status == "active").order_by(Incident.reported_at.desc()).all()
        active_formatted = [format_incident(inc) for inc in active]
        
        # Serialize datetimes to ISO strings for JSON serialization
        active_serialized = []
        for inc in active_formatted:
            serialized = {**inc}
            if serialized["reported_at"]:
                serialized["reported_at"] = serialized["reported_at"].isoformat()
            if serialized["resolved_at"]:
                serialized["resolved_at"] = serialized["resolved_at"].isoformat()
            active_serialized.append(serialized)

        await websocket.send_json({
            "type": "INITIAL_STATE",
            "incidents": active_serialized
        })
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WS error: {e}")
        manager.disconnect(websocket)
    finally:
        db.close()


# Mount the Flask application at "/" as the fallback
app.mount("/", WSGIMiddleware(flask_app))
