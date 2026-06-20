"""
Prediction Model Service
Handles traffic prediction, LLM parsing, and dispatch planning.

Main Components:
- TrafficModelLoader: Manages ML model and data loading
- parse_traffic_description: LLM-based incident description parsing
- predict_traffic_impact: Main prediction function

Usage:
    from prediction_model import predict_traffic_impact, TrafficModelLoader
    
    # Initialize models (call once at startup)
    TrafficModelLoader.load_models()
    
    # Make predictions
    result = predict_traffic_impact(
        latitude=13.0827,
        longitude=80.2707,
        event_cause="accident",
        priority="high",
        description="Two vehicles collided at junction"
    )
"""

import logging

# Configure logging for the module
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s: %(message)s'
)

from .llm_agent import parse_traffic_description
from .model_loader import TrafficModelLoader
from .prediction_service import predict_traffic_impact, DispatchPlanner

__version__ = '1.0.0'
__all__ = [
    'predict_traffic_impact',
    'parse_traffic_description',
    'TrafficModelLoader',
    'DispatchPlanner'
]
