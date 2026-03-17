"""
app.py — Flask REST API for ImmoApp price prediction.

Endpoints
---------
GET  /health    → model status + metrics
POST /predict   → predicted price in EUR
GET  /features  → full feature list with allowed values (for Odoo Studio)
"""

import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

from predictor import predict, get_metadata, get_feature_names

_geolocator = Nominatim(user_agent="immoapp-price-predictor")

def _geocode(street: str, number: str, postal_code) -> tuple | None:
    query = f"{street} {number}, {postal_code}, Belgium".strip(", ")
    try:
        loc = _geolocator.geocode(query, timeout=5)
        if loc:
            return loc.latitude, loc.longitude
    except (GeocoderTimedOut, GeocoderUnavailable):
        pass
    return None

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Allow all origins — required for Odoo Online calls


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    """Liveness + model info endpoint."""
    try:
        meta = get_metadata()
        return jsonify({
            "status": "ok",
            "model_name":    meta.get("model_name", "unknown"),
            "version":       meta.get("version", "unknown"),
            "r2":            meta.get("r2"),
            "mae":           meta.get("mae"),
            "trained_at":    meta.get("trained_at"),
            "feature_count": meta.get("feature_count"),
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503


@app.post("/predict")
def predict_price():
    """
    Predict Belgian real estate price.

    Required fields: room_count, living_area, number_of_facades, bedroom_count
    All other fields are optional (sensible defaults applied).
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    # Validate required fields
    required = ["room_count", "living_area", "number_of_facades", "bedroom_count"]
    missing = [f for f in required if f not in body]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # Basic type/range checks
    errors = []
    if not (1 <= int(body.get("room_count", 1)) <= 100):
        errors.append("room_count must be 1–100")
    if not (10 <= float(body.get("living_area", 50)) <= 5000):
        errors.append("living_area must be 10–5000 m²")
    if not (1 <= int(body.get("number_of_facades", 2)) <= 4):
        errors.append("number_of_facades must be 1–4")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    # Street-level geocoding (optional — overrides commune centroid)
    street = body.get("street", "").strip()
    if street:
        coords = _geocode(street, str(body.get("house_number", "")), body.get("postal_code", 1000))
        if coords:
            body = dict(body, latitude=coords[0], longitude=coords[1])

    try:
        price = predict(body)
    except Exception as e:
        _logger.exception("Prediction failed")
        return jsonify({"error": f"Prediction failed: {str(e)}"}), 500

    return jsonify({
        "predicted_price": round(price, 2),
        "currency": "EUR",
    })


@app.get("/features")
def features():
    """
    Return the feature list the model was trained on, plus allowed values
    for categorical fields. Used by Odoo Studio to build forms.
    """
    return jsonify({
        "feature_names": get_feature_names(),
        "categoricals": {
            "peb": ["A", "B", "C", "D", "E", "F", "G"],
            "avis": ["A", "B", "C", "D", "E", "F", "G"],
            "state_of_building": ["New", "Good", "Fair", "Poor", "Needs Renovation"],
            "type_of_property": ["House", "Apartment", "Villa", "Studio"],
            "region": ["Flanders", "Wallonia", "Brussels"],
            "heating_type": ["Gas", "Electric", "Heat pump", "FUEL_OIL", "PELLET", "WOOD"],
            "flooding_zone": [
                "NON_FLOOD_ZONE", "POSSIBLE_FLOOD_ZONE", "RECOGNIZED_FLOOD_ZONE",
                "CIRCUMSCRIBED_FLOOD_ZONE", "CIRCUMSCRIBED_WATERSIDE_ZONE",
            ],
            "type_of_sale": [
                "residential_sale", "residential_monthly_rent",
                "annuity_lump_sum", "annuity_monthly_amount",
                "annuity_without_lump_sum", "homes_to_build",
            ],
        },
        "optional_new": {
            "commune": "Belgian municipality name (e.g. 'Gent', 'Liège') — improves location accuracy",
            "street": "Street name (e.g. 'Kortrijksesteenweg') — enables street-level geocoding via OpenStreetMap",
            "house_number": "House number (e.g. '48') — used together with street for precise geocoding",
            "avis": "Quality rating A–G — post-prediction multiplier (scores.md)",
            "peb": "Energy class A–G — post-prediction multiplier (scores.md)",
        },
        "required": ["room_count", "living_area", "number_of_facades", "bedroom_count"],
    })


# --------------------------------------------------------------------------- #
# Dev server
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app.run(debug=True, port=5000)
