import feedparser
import spacy
import json
import re
import urllib.parse
from datetime import datetime, timezone

# ==========================================================
# CONFIG
# ==========================================================

RSS_QUERY = (
    "India traffic OR rally OR protest OR road closure "
    "OR procession OR crowd OR accident OR stadium OR festival"
)

KEYWORDS = [
    "rally",
    "protest",
    "crowd",
    "traffic",
    "road closure",
    "closed road",
    "diversion",
    "accident",
    "procession",
    "march",
    "festival",
    "stadium",
    "match",
    "congestion",
    "demonstration",
    "gathering",
    "collision",
    "crash"
]

EVENT_TYPES = {
    "RALLY": ["rally", "protest", "march", "demonstration"],
    "SPORTS": ["match", "stadium", "tournament", "league", "football", "cricket"],
    "FESTIVAL": ["festival", "puja", "celebration"],
    "CONCERT": ["concert", "music show", "performance", "show"],
    "ACCIDENT": ["accident", "collision", "crash"]
}

# ==========================================================
# NLP MODEL & FALLBACK SETUP
# ==========================================================

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("[System Log]: spaCy 'en_core_web_sm' model not found. Attempting download...")
    from spacy.cli import download
    try:
        download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")
    except Exception as e:
        print(f"[System Log]: Failed to download 'en_core_web_sm': {e}")
        print("[System Log]: Utilizing fallback rule-based location/entity detector.")
        
        class FallbackNLP:
            def __call__(self, text):
                class Entity:
                    def __init__(self, t, label):
                        self.text = t
                        self.label_ = label
                class Doc:
                    def __init__(self, txt):
                        self.ents = []
                        words = txt.split()
                        ignored = {"India", "Google", "News", "The", "Today", "And", "For", "With", "Traffic", "Road"}
                        for w in words:
                            w_clean = w.strip(".,()\"';:-")
                            if w_clean and w_clean[0].isupper() and len(w_clean) > 2:
                                if w_clean not in ignored:
                                    self.ents.append(Entity(w_clean, "GPE"))
                return Doc(text)
        
        nlp = FallbackNLP()

# ==========================================================
# FETCH NEWS
# ==========================================================

def fetch_today_news():
    encoded_query = urllib.parse.quote(RSS_QUERY)
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={encoded_query}"
        "&hl=en-IN&gl=IN&ceid=IN:en"  # <-- Added missing opening quote here
    )
    feed = feedparser.parse(rss_url)
    return feed.entries

# ==========================================================
# FILTER ARTICLES
# ==========================================================

def is_traffic_related(text):
    text = text.lower()
    return any(keyword in text for keyword in KEYWORDS)

# ==========================================================
# EVENT TYPE DETECTION
# ==========================================================

def detect_event_type(text):
    text = text.lower()
    for event_type, words in EVENT_TYPES.items():
        for word in words:
            if word in text:
                return event_type
    return "UNKNOWN"

# ==========================================================
# EXTRACT ENTITIES (LOCATIONS, DATES, TIMES)
# ==========================================================

def extract_event_info(text):
    doc = nlp(text)
    
    locations = set()
    dates = set()
    times = set()

    for ent in doc.ents:
        if ent.label_ in ["GPE", "LOC"]:
            locations.add(ent.text)
        elif ent.label_ == "DATE":
            dates.add(ent.text)
        elif ent.label_ == "TIME":
            times.add(ent.text)

    # Regex fallback date extraction
    date_matches = re.findall(
        r"\b\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
        text,
        flags=re.IGNORECASE
    )
    dates.update(date_matches)

    # Regex fallback time extraction
    time_matches = re.findall(
        r"\b\d{1,2}(?::\d{2})?\s?(?:AM|PM|am|pm)\b",
        text
    )
    times.update(time_matches)

    return {
        "locations": list(locations),
        "dates": list(dates),
        "times": list(times)
    }

# ==========================================================
# ESTIMATE SEVERITY
# ==========================================================

def estimate_severity(text):
    text = text.lower()
    
    high_words = [
        "road closure",
        "blocked",
        "massive rally",
        "heavy congestion",
        "major protest"
    ]
    
    medium_words = [
        "rally",
        "crowd",
        "protest",
        "diversion",
        "procession",
        "festival"
    ]

    for word in high_words:
        if word in text:
            return "HIGH"

    for word in medium_words:
        if word in text:
            return "MEDIUM"

    return "LOW"

# ==========================================================
# CHECK TODAY
# ==========================================================

def is_today(entry):
    try:
        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        today = datetime.now(timezone.utc).date()
        return published.date() == today
    except Exception:
        return True

# ==========================================================
# PROCESS ARTICLES
# ==========================================================

def process_news():
    entries = fetch_today_news()
    results = []

    for article in entries:
        title = article.get("title", "")
        summary = article.get("summary", "")
        text = f"{title}\n{summary}"

        if not is_today(article):
            continue

        if not is_traffic_related(text):
            continue

        info = extract_event_info(text)

        event = {
            "title": title,
            "event_type": detect_event_type(text),
            "severity": estimate_severity(text),
            "locations": info["locations"],
            "dates": info["dates"],
            "times": info["times"],
            "published": article.get("published", ""),
            "source": article.get("source", {}).get("title", "Google News"),
            "link": article.get("link", "")
        }

        results.append(event)

    return results

# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":
    events = process_news()
    
    print("\n===== TODAY'S TRAFFIC IMPACT NEWS =====\n")
    print(json.dumps(events, indent=4, ensure_ascii=False))