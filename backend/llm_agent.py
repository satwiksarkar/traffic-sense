import os
import json
from google import genai
from google.genai import types
from pydantic import BaseModel 
from dotenv import load_dotenv

# Find the absolute path to backend/.env and root .env relative to this file's location
base_dir = os.path.dirname(os.path.abspath(__file__))
root_env_path = os.path.join(os.path.dirname(base_dir), ".env")
env_path = os.path.join(base_dir, ".env")

# Force load from the correct directory paths
if os.path.exists(root_env_path):
    load_dotenv(dotenv_path=root_env_path)
load_dotenv(dotenv_path=env_path)

GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not GOOGLE_API_KEY:
    print("[LLM Warning] GEMINI_API_KEY not found in environment. LLM features will use fallback.")
    client = None
else:
    # ✅ NEW: Initialize the central GenAI client
    client = genai.Client(api_key=GOOGLE_API_KEY)


class TrafficIntelligence(BaseModel): # Inherit from Pydantic's BaseModel
    severity_multiplier: float
    hazards_present: list[str]
    special_assets_needed: list[str]


def parse_traffic_description(description_text: str) -> dict:
    """Sends incident description to Gemini and returns structured severity data.

    Handles both English and Kannada text.

    Returns:
        {
            "severity_multiplier": float (1.0 - 3.0),
            "hazards_present": list[str],
            "special_assets_needed": list[str]
        }
    """
    # Return safe defaults for empty/null descriptions
    if (
        not description_text
        or str(description_text).strip() == ""
        or str(description_text).lower() == "nan"
    ):
        return {
            "severity_multiplier": 1.0,
            "hazards_present": ["none"],
            "special_assets_needed": ["standard_patrol"],
        }

    if not client:
        return {
            "severity_multiplier": 1.0,
            "hazards_present": ["no_api_key"],
            "special_assets_needed": ["standard_patrol"],
        }

    prompt = f"""
    You are an elite Traffic Command AI for the Bengaluru Traffic Police.
    Read the following field officer incident report (it may contain English or Kannada).
    
    Incident Report: "{description_text}"
    
    Your task is to extract operational intelligence and return it strictly following the requested JSON schema.
    
    Severity guidance:
    - 1.0 = minor/standard
    - 1.5 = heavy vehicle/bus/tree fall
    - 2.0 = major blockage/accident
    - 3.0 = fire/flooding/complete road closure
    """

    try:
        # ✅ NEW: Use client.models.generate_content with structured outputs
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TrafficIntelligence,  # Forces compliance with Pydantic class
                temperature=0.1,  # Low temp ensures strict, deterministic adherence to facts
            ),
        )

        # ✅ NEW: The SDK handles parsing automatically via response.parsed
        # If response.parsed isn't populated, we fallback to loading text safely
        if response.parsed:
            result = response.parsed.model_dump()
        else:
            result = json.loads(response.text)

        # Validate and clamp severity_multiplier to safe range
        result["severity_multiplier"] = max(
            1.0, min(3.0, float(result.get("severity_multiplier", 1.0)))
        )
        result.setdefault("hazards_present", ["unknown"])
        result.setdefault("special_assets_needed", ["standard_patrol"])

        return result

    except Exception as e:
        print(f"[LLM] Gemini API error: {e}")
        return {
            "severity_multiplier": 1.0,
            "hazards_present": ["api_error"],
            "special_assets_needed": ["standard_patrol"],
        }