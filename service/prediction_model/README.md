# Traffic Prediction Model Service

Complete, production-ready traffic prediction and dispatch planning service. Combines ML-based congestion prediction with LLM-powered incident analysis.

## 📊 Architecture

```
prediction_model/
├── __init__.py                 # Package initialization & exports
├── model_loader.py             # Singleton ML model manager
├── llm_agent.py                # Gemini LLM for incident parsing
├── prediction_service.py       # Dispatch planning & predictions
├── models/                     # Pre-trained ML models
│   ├── ngboost_traffic_model.pkl      # NGBoost regression model
│   ├── label_encoder_cause.pkl        # Incident cause encoder
│   └── label_encoder_priority.pkl     # Priority level encoder
└── data/
    └── processed_astram_with_graph_AND_history.csv  # City graph & history
```

## 🚀 Quick Start

### 1. Initialize Models (Once at Startup)

```python
from prediction_model import TrafficModelLoader

# Load all models into memory
TrafficModelLoader.load_models()
```

### 2. Make Predictions

```python
from prediction_model import predict_traffic_impact

result = predict_traffic_impact(
    latitude=13.0827,
    longitude=80.2707,
    event_cause="accident",
    priority="high",
    description="Two vehicles collided at junction near Metro Station"
)

print(result)
```

### 3. Response Format

```json
{
    "status": "success",
    "event_id": "EVT_20260619_143022",
    "timestamp": "2026-06-19T14:30:22.123456",
    "location": {
        "latitude": 13.0827,
        "longitude": 80.2707,
        "closest_node": {
            "distance_meters": 45.2,
            "node_id": "node_12345"
        }
    },
    "event_details": {
        "cause": "accident",
        "priority": "high",
        "description": "Two vehicles collided at junction near Metro Station",
        "llm_analysis": {
            "severity_multiplier": 2.5,
            "hazards_present": ["accident_site", "debris", "blocked_lane"],
            "special_assets_needed": ["ambulance", "tow_vehicle", "standard_patrol"]
        }
    },
    "traffic_prediction": {
        "predicted_congestion_level": 75.43,
        "congestion_category": "critical",
        "severity_multiplier": 2.5
    },
    "routing": {
        "status": "success",
        "detour_distance_km": 2.34,
        "detour_duration_mins": 8.5,
        "route_coordinates": [[13.0827, 80.2707], ...]
    },
    "resource_allocation": {
        "constables_needed": 5,
        "barricades_needed": 2,
        "available_resources": {
            "total_constables": 150,
            "available_constables": 150,
            "total_barricades": 40,
            "available_barricades": 40
        }
    }
}
```

## 🔧 Components

### TrafficModelLoader (model_loader.py)
**Singleton pattern for ML model management**

```python
from prediction_model import TrafficModelLoader

# Load models
loader = TrafficModelLoader.load_models()

# Access loaded components
print(loader.ai_model)           # NGBoost regression model
print(loader.encoder_cause)      # Cause label encoder
print(loader.encoder_priority)   # Priority label encoder
print(loader.spatial_tree)       # KDTree for spatial queries
print(loader.df_nodes)           # DataFrame with city nodes
print(loader.avg_embeddings)     # Average spatial embeddings

# Check readiness
if TrafficModelLoader.is_ready():
    print("Models loaded and ready!")
```

**Features:**
- Lazy loading: Models loaded once and reused
- Error handling: Detailed error messages for missing files
- Logging: Comprehensive logging for debugging
- Validation: Checks for required columns and file existence

### LLM Agent (llm_agent.py)
**Google Gemini-powered incident description parsing**

```python
from prediction_model import parse_traffic_description

# Parse incident with LLM
result = parse_traffic_description(
    "ಊರ್ವಶಿ ಜಂಕ್ಷನ್ ನಲ್ಲಿ ಬಸ್ ವಾಹನ ಸ್ಥಮನ ಆಯ್ತೆ"  # Kannada
)

# Or English
result = parse_traffic_description(
    "Fire reported at downtown junction with 3 vehicles affected"
)

print(result)
# Output:
# {
#     "severity_multiplier": 2.5,
#     "hazards_present": ["fire", "blocked_lane", "collision_debris"],
#     "special_assets_needed": ["fire_engine", "ambulance", "tow_vehicle"]
# }
```

**Features:**
- Multi-language support (English, Kannada, etc.)
- Graceful fallback: Uses heuristic parsing if API unavailable
- Timeout protection: 10-second API call timeout
- Error resilience: Returns safe defaults on failure

### Dispatch Planner (prediction_service.py)
**Integrated traffic prediction and dispatch planning**

```python
from prediction_model import DispatchPlanner

# Direct dispatch planning
plan = DispatchPlanner.dispatch_plan(
    latitude=13.0827,
    longitude=80.2707,
    event_cause="construction",
    priority="medium",
    description="Road maintenance at junction"
)

# Calculate alternative routes
detour = DispatchPlanner.calculate_detour(13.0827, 80.2707)
print(detour)
# {
#     "status": "success",
#     "detour_distance_km": 2.34,
#     "detour_duration_mins": 8.5,
#     "route_coordinates": [...]
# }
```

## 📋 Data Requirements

### CSV Format (data/processed_astram_with_graph_AND_history.csv)

Required columns:
- `latitude` (float): Node latitude
- `longitude` (float): Node longitude

Optional but recommended:
- `spatial_emb_*`: Spatial embedding columns (e.g., `spatial_emb_0`, `spatial_emb_1`, ...)
- Any other node features for enrichment

### Model Files (models/)

All files must be present:
- `ngboost_traffic_model.pkl`: Trained NGBoost model for congestion prediction
- `label_encoder_cause.pkl`: Maps incident causes to numeric codes
- `label_encoder_priority.pkl`: Maps priority levels to numeric codes

## 🔑 Environment Variables

Create `.env` in the backend directory:

```bash
# Required for LLM-based description parsing
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: For advanced routing
MAPPLS_API_KEY=your_mappls_api_key_here
```

If `GEMINI_API_KEY` is missing, the system falls back to heuristic parsing.

## 📊 Congestion Levels

The model outputs congestion predictions categorized as:

- **Light** (0-20): Normal traffic flow
- **Moderate** (20-40): Some delays expected
- **Heavy** (40-70): Significant congestion, detours advised
- **Critical** (70-100): Major incident, immediate action required

## ⚠️ Error Handling

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| `FileNotFoundError: AI model not found` | Missing model files | Ensure `models/*.pkl` files exist |
| `FileNotFoundError: CSV data not found` | Missing geographic data | Ensure CSV file is in `data/` |
| `LLM Parsing Error` | API unavailable | System uses heuristic fallback |
| `Models not loaded` | `load_models()` not called | Call `TrafficModelLoader.load_models()` once at startup |

## 🎯 Integration with Flask

```python
from flask import Flask, request, jsonify
from prediction_model import predict_traffic_impact, TrafficModelLoader

app = Flask(__name__)

# Initialize models at startup
@app.before_first_request
def init():
    TrafficModelLoader.load_models()

@app.route('/api/traffic/predict', methods=['POST'])
def predict():
    data = request.json
    result = predict_traffic_impact(
        latitude=data['latitude'],
        longitude=data['longitude'],
        event_cause=data.get('cause', 'other'),
        priority=data.get('priority', 'low'),
        description=data.get('description', '')
    )
    return jsonify(result)

if __name__ == '__main__':
    app.run()
```

## 🧪 Testing

```python
from prediction_model import TrafficModelLoader, predict_traffic_impact

# Test model loading
try:
    TrafficModelLoader.load_models()
    print("✓ Models loaded successfully")
except Exception as e:
    print(f"✗ Model loading failed: {e}")

# Test prediction
if TrafficModelLoader.is_ready():
    result = predict_traffic_impact(
        latitude=13.0827,
        longitude=80.2707,
        event_cause="accident",
        priority="high",
        description="Test incident"
    )
    if result['status'] == 'success':
        print("✓ Prediction successful")
        print(f"  Congestion level: {result['traffic_prediction']['predicted_congestion_level']}")
        print(f"  Resources needed: {result['resource_allocation']}")
    else:
        print(f"✗ Prediction failed: {result['message']}")
```

## 📈 Performance

- **Model Loading**: ~2-5 seconds (one-time)
- **Prediction**: ~500-1000ms per request
- **Memory**: ~200-300MB for all loaded models
- **Concurrency**: Thread-safe singleton pattern supports concurrent predictions

## 🔄 Update Models

To update the trained models:

1. Replace files in `models/` directory:
   - `ngboost_traffic_model.pkl`
   - `label_encoder_cause.pkl`
   - `label_encoder_priority.pkl`

2. Optionally update geographic data:
   - Replace `data/processed_astram_with_graph_AND_history.csv`

3. Restart the application to reload models

## 📝 Logging

Enable detailed logging:

```python
import logging

# Set to DEBUG for verbose output
logging.getLogger('prediction_model').setLevel(logging.DEBUG)

# Now all module operations will be logged
from prediction_model import predict_traffic_impact
```

## ⚙️ Customization

### Change Model Directory

```python
TrafficModelLoader.load_models(
    model_dir='custom_models',
    data_dir='custom_data'
)
```

### Custom Resource Inventory

```python
from prediction_model import DispatchPlanner

DispatchPlanner.CITY_INVENTORY = {
    "total_constables": 200,
    "available_constables": 200,
    "total_barricades": 60,
    "available_barricades": 60
}
```

## 🐛 Debugging

Enable debug logging:

```python
import logging
import sys

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
```

## 📚 Dependencies

- `pandas`: Data processing
- `numpy`: Numerical computations
- `scikit-learn`: ML utilities
- `ngboost`: Gradient boosting regressor
- `scipy`: Spatial indexing (KDTree)
- `joblib`: Model serialization
- `google-generativeai`: Gemini LLM API
- `requests`: HTTP requests for routing APIs
- `polyline`: Route encoding/decoding
- `python-dotenv`: Environment variable management

## 📄 License

Part of Traffic Control System project.
