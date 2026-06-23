"""LLM Agent for parsing traffic incident descriptions
Uses Google Gemini API to extract operational intelligence from incident reports
"""

import os
import json
import logging

try:
    import google.generativeai as genai
except ImportError:
    raise ImportError("google-generativeai not installed. Install with: pip install google-generativeai")

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Find the absolute path to backend/.env relative to this file's location
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(base_dir, "backend", ".env")

# Force load from the correct directory path
load_dotenv(dotenv_path=env_path)
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not GOOGLE_API_KEY:
    logger.warning("GEMINI_API_KEY not found in .env file - LLM parsing will use fallback")
    model = None
else:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("Gemini API configured successfully")
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}")
        model = None

def parse_traffic_description(description_text):
    """
    Sends the raw text to the LLM and forces it to return a structured JSON.
    Falls back to heuristic parsing if LLM is unavailable.
    
    Args:
        description_text: Raw incident description (may contain English or Kannada)
        
    Returns:
        dict: Structured incident intelligence with keys:
            - severity_multiplier (float 1.0-3.0)
            - hazards_present (list of strings)
            - special_assets_needed (list of strings)
    """
    # Handle empty/null descriptions
    if not description_text or str(description_text).strip() == "" or str(description_text).lower() == "nan":
        logger.debug("Empty description provided, returning defaults")
        return {
            "severity_multiplier": 1.0,
            "hazards_present": ["none"],
            "special_assets_needed": ["standard_patrol"]
        }

    # If model not configured, use heuristic parsing
    if model is None:
        logger.info("Gemini API not configured, using heuristic parsing")
        return _heuristic_parse(description_text)
    
    prompt = f"""
    You are an elite Traffic Command AI for the Bengaluru Traffic Police.
    Read the following field officer incident report (it may contain English or Kannada).
    
    Incident Report: "{description_text}"
    
    Your task is to extract operational intelligence and return it strictly as a JSON object.
    Do not include any markdown formatting, backticks, or extra text. ONLY return valid JSON.
    
    JSON Schema Requirements:
    - "severity_multiplier": A float from 1.0 to 3.0. (1.0 = standard, 1.5 = heavy vehicle/bus/tree, 2.0+ = fire/flooding/major blockage).
    - "hazards_present": A list of strings describing hazards (e.g., "waterlogging", "debris", "blocked_lane").
    - "special_assets_needed": A list of strings for required equipment (e.g., "heavy_crane", "fire_engine", "chainsaw", "ambulance"). Default to ["standard_patrol"] if nothing special is needed.
    
    Always return valid JSON only.
    """
    
    try:
        response = model.generate_content(prompt, timeout=10)
        # Clean markdown if the LLM adds it
        cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(cleaned_text)
        logger.debug(f"LLM parsing succeeded: {parsed}")
        return parsed
        
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}")
        return _heuristic_parse(description_text)
    except Exception as e:
        logger.error(f"LLM Parsing Error: {e}")
        return _heuristic_parse(description_text)


def _heuristic_parse(description_text):
    """
    Fallback heuristic parsing when LLM is unavailable.
    Uses keyword matching to determine severity and required assets.
    
    Args:
        description_text: Raw incident description
        
    Returns:
        dict: Parsed incident intelligence
    """
    logger.debug(f"Using heuristic parsing for: {description_text[:50]}...")
    text_lower = str(description_text).lower()
    
    # Determine severity based on keywords
    critical_keywords = ['fire', 'flooding', 'flood', 'accident', 'collision', 'major']
    high_keywords = ['vehicle', 'bus', 'truck', 'tree', 'blockage', 'blocked']
    medium_keywords = ['waterlogging', 'debris', 'construction', 'cement']
    
    severity = 1.0
    if any(kw in text_lower for kw in critical_keywords):
        severity = 2.5
    elif any(kw in text_lower for kw in high_keywords):
        severity = 1.5
    elif any(kw in text_lower for kw in medium_keywords):
        severity = 1.2
    
    # Determine required assets
    assets = ["standard_patrol"]
    if 'fire' in text_lower:
        assets.append("fire_engine")
    if 'flood' in text_lower or 'waterlogging' in text_lower:
        assets.append("pump")
    if 'tree' in text_lower or 'debris' in text_lower:
        assets.append("chainsaw")
    if 'accident' in text_lower or 'collision' in text_lower:
        assets.append("ambulance")
    if 'heavy' in text_lower or 'truck' in text_lower:
        assets.append("tow_vehicle")
    
    hazards = []
    if 'water' in text_lower:
        hazards.append("waterlogging")
    if 'debris' in text_lower:
        hazards.append("debris")
    if 'block' in text_lower:
        hazards.append("blocked_lane")
    if 'accident' in text_lower:
        hazards.append("accident_site")
    
    if not hazards:
        hazards = ["unknown"]
    
    result = {
        "severity_multiplier": min(3.0, round(severity, 1)),
        "hazards_present": hazards,
        "special_assets_needed": list(set(assets))  # Remove duplicates
    }
    logger.debug(f"Heuristic parsing result: {result}")
    return result
    print("🚨 STARTING LOCAL LLM TEST 🚨\n")
    
    test_text = "ಊರ್ವಶಿ ಜಂಕ್ಷನ್ ನಲ್ಲಿ ಒಳಚರಂಡಿ ಚೇಂಬರ್ ಗೆ ಹೊಸದಾಗಿ ಸಿಮೆಂಟ್ ಹಾಕಿದ್ದು ಟ್ರಾಫಿಕ್ ಮೂವ್ಮೆಂಟ್ ಸ್ವಲ್ಪ ನಿಧಾನಗತಿಯಲ್ಲಿ ಇರುತ್ತದೆ ಸರ್🙏"
    print(f"RAW INPUT: '{test_text}'")
    
    result = parse_traffic_description(test_text)
    
    print("\nAI PARSED OUTPUT:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
