"""
Model Loader - Lazy loads ML models to avoid redundant file I/O
Handles NGBoost ML model, encoders, geographic data, and spatial indexing
"""
import os
import joblib
import pandas as pd
from scipy.spatial import KDTree
import logging

logger = logging.getLogger(__name__)

class TrafficModelLoader:
    """Singleton pattern for loading and caching traffic prediction models"""
    _instance = None
    _models_loaded = False
    _load_error = None
    
    ai_model = None
    encoder_cause = None
    encoder_priority = None
    spatial_tree = None
    df_nodes = None
    avg_embeddings = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TrafficModelLoader, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def load_models(cls, model_dir='models', data_dir='data'):
        """
        Load all required models once into memory.
        
        Args:
            model_dir: Directory containing trained model files (default: 'models')
            data_dir: Directory containing data files (default: 'data')
            
        Returns:
            TrafficModelLoader: Singleton instance with loaded models
            
        Raises:
            FileNotFoundError: If model or data files are missing
            Exception: If model loading fails
        """
        if cls._models_loaded:
            logger.info("Models already loaded, returning cached instance")
            return cls._instance
        
        if cls._load_error:
            logger.error(f"Previous load error detected: {cls._load_error}")
            raise RuntimeError(f"Models failed to load: {cls._load_error}")
        
        # Get the directory where this file is located
        base_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(base_dir, model_dir)
        data_path = os.path.join(base_dir, data_dir)
        
        logger.info(f"[Loading Models] Base directory: {base_dir}")
        logger.info(f"[Loading Models] Model path: {model_path}")
        logger.info(f"[Loading Models] Data path: {data_path}")
        
        try:
            # Validate directories exist
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Model directory not found: {model_path}")
            if not os.path.exists(data_path):
                raise FileNotFoundError(f"Data directory not found: {data_path}")
            
            # Load trained ML models
            ai_model_file = os.path.join(model_path, 'ngboost_traffic_model.pkl')
            if not os.path.exists(ai_model_file):
                raise FileNotFoundError(f"AI model not found: {ai_model_file}")
            logger.info(f"  1. Loading AI model from {ai_model_file}")
            cls.ai_model = joblib.load(ai_model_file)
            
            # Load label encoders
            encoder_cause_file = os.path.join(model_path, 'label_encoder_cause.pkl')
            encoder_priority_file = os.path.join(model_path, 'label_encoder_priority.pkl')
            
            if not os.path.exists(encoder_cause_file):
                raise FileNotFoundError(f"Cause encoder not found: {encoder_cause_file}")
            if not os.path.exists(encoder_priority_file):
                raise FileNotFoundError(f"Priority encoder not found: {encoder_priority_file}")
            
            logger.info(f"  2. Loading label encoders")
            cls.encoder_cause = joblib.load(encoder_cause_file)
            cls.encoder_priority = joblib.load(encoder_priority_file)
            
            # Load geographic data and build spatial index
            csv_file = os.path.join(data_path, 'processed_astram_with_graph_AND_history.csv')
            if not os.path.exists(csv_file):
                raise FileNotFoundError(f"CSV data not found: {csv_file}")
            
            logger.info(f"  3. Loading city geometry from {csv_file}")
            cls.df_nodes = pd.read_csv(csv_file)
            logger.info(f"     Loaded {len(cls.df_nodes)} node records")
            
            # Build spatial index
            if 'latitude' not in cls.df_nodes.columns or 'longitude' not in cls.df_nodes.columns:
                raise ValueError("CSV must contain 'latitude' and 'longitude' columns")
            
            known_coords = cls.df_nodes[['latitude', 'longitude']].dropna().values
            if len(known_coords) == 0:
                raise ValueError("No valid coordinates found in data")
            
            cls.spatial_tree = KDTree(known_coords)
            logger.info(f"     Built spatial index with {len(known_coords)} coordinates")
            
            # Extract and cache embedding columns for averaging
            embedding_cols = [col for col in cls.df_nodes.columns if 'spatial_emb' in col]
            if embedding_cols:
                cls.avg_embeddings = cls.df_nodes[embedding_cols].mean().to_dict()
                logger.info(f"     Computed average embeddings from {len(embedding_cols)} columns")
            else:
                logger.warning("     No embedding columns found in data")
                cls.avg_embeddings = {}
            
            cls._models_loaded = True
            logger.info("✓ All models loaded successfully!\n")
            
        except FileNotFoundError as e:
            cls._load_error = str(e)
            logger.error(f"✗ Model loading failed: {e}")
            logger.error(f"  Make sure model files are in '{model_dir}/' directory and CSV data is in '{data_dir}/'")
            raise
        except Exception as e:
            cls._load_error = str(e)
            logger.error(f"✗ Error during model loading: {e}")
            raise
        
        return cls._instance
    
    @classmethod
    def get_models(cls):
        """Get the loaded models instance"""
        if not cls._models_loaded:
            cls.load_models()
        return cls._instance
    
    @classmethod
    def is_ready(cls):
        """Check if models are loaded and ready"""
        return cls._models_loaded and cls.ai_model is not None
