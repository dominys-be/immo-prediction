"""
app.py — Flask REST API for ImmoApp price prediction.

Endpoints
---------
GET  /health    → model status + metrics
POST /predict   → predicted price in EUR
GET  /features  → full feature list with allowed values (for Odoo Studio)
"""

import logging
import os
import threading
import xmlrpc.client
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderRateLimited
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from predictor import predict, get_metadata, get_feature_names, predict_rent, get_rental_metadata

# Odoo credentials for webhook write-back
_ODOO_URL   = os.getenv("ODOO_URL", "")
_ODOO_DB    = os.getenv("ODOO_DB", "")
_ODOO_USER  = os.getenv("ODOO_USER", "")
_ODOO_KEY   = os.getenv("ODOO_APIKEY", "")
_ODOO_MODEL = os.getenv("ODOO_MODEL", "x_estimation")

# Odoo Studio field name → predict() parameter name
_WEBHOOK_FIELD_MAP = {
    "x_studio_x_living_area":       "living_area",
    "x_studio_x_bedroom_count":     "bedroom_count",
    "x_studio_x_room_count":        "room_count",
    "x_studio_x_facades":           "number_of_facades",
    "x_studio_x_peb":               "peb",
    "x_studio_x_avis":              "avis",
    "x_studio_x_street":            "street",
    "x_studio_x_commune":           "commune",
    "x_studio_x_state_of_building": "state_of_building",
    "x_studio_x_type_of_property":  "type_of_property",
    "x_studio_x_region":            "region",
    "x_studio_x_postal_code":       "postal_code",
    "x_studio_x_construction_year": "construction_year",
    "x_studio_x_heating_type":      "heating_type",
    "x_studio_x_garage":            "garage",
    "x_studio_x_garden":            "garden",
    "x_studio_x_garden_area":       "garden_area",
    "x_studio_x_swimming_pool":     "swimming_pool",
    "x_studio_x_terrace":           "terrace",
    "x_studio_x_fireplace":         "fireplace",
    "x_studio_x_lift":              "lift",
    "x_studio_x_solar_panels":      "has_solar_panels",
    "x_studio_x_transaction_type":  "transaction_type",
}

_geolocator = Nominatim(user_agent="immoapp-price-predictor")

def _geocode(street: str, number: str, postal_code) -> tuple | None:
    query = f"{street} {number}, {postal_code}, Belgium".strip(", ")
    try:
        loc = _geolocator.geocode(query, timeout=5)
        if loc:
            return loc.latitude, loc.longitude
    except (GeocoderTimedOut, GeocoderUnavailable, GeocoderRateLimited):
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


@app.post("/predict-rent")
def predict_rent_price():
    """
    Predict Belgian monthly rental price.

    Same input schema as /predict — required: room_count, living_area,
    number_of_facades, bedroom_count.
    PEB / Avis multipliers ARE applied as post-prediction score multipliers (same as sale model).
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    required = ["room_count", "living_area", "number_of_facades", "bedroom_count"]
    missing = [f for f in required if f not in body]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    errors = []
    if not (10 <= float(body.get("living_area", 50)) <= 1000):
        errors.append("living_area must be 10–1000 m²")
    if not (1 <= int(body.get("number_of_facades", 1)) <= 4):
        errors.append("number_of_facades must be 1–4")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    # Street-level geocoding (optional)
    street = body.get("street", "").strip()
    if street:
        coords = _geocode(street, str(body.get("house_number", "")), body.get("postal_code", 1000))
        if coords:
            body = dict(body, latitude=coords[0], longitude=coords[1])

    try:
        rent = predict_rent(body)
    except Exception as e:
        _logger.exception("Rental prediction failed")
        return jsonify({"error": f"Prediction failed: {str(e)}"}), 500

    return jsonify({
        "predicted_rent": round(rent, 2),
        "currency": "EUR",
        "unit": "per month",
    })


@app.get("/health-rent")
def health_rent():
    """Rental model liveness + info endpoint."""
    try:
        meta = get_rental_metadata()
        return jsonify({
            "status": "ok",
            "model_name":    meta.get("model_name", "unknown"),
            "r2":            meta.get("r2"),
            "mae":           meta.get("mae"),
            "trained_at":    meta.get("trained_at"),
            "feature_count": meta.get("feature_count"),
            "rent_range_eur": meta.get("rent_range_eur"),
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503


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
# Odoo Webhook endpoint
# --------------------------------------------------------------------------- #

def _process_webhook(body):
    record_id = body.get("id")
    payload = {}
    for odoo_field, pred_field in _WEBHOOK_FIELD_MAP.items():
        val = body.get(odoo_field)
        if val not in (None, False, ""):
            payload[pred_field] = val

    transaction_type = payload.pop("transaction_type", "") or ""

    street = payload.get("street", "").strip()
    if street:
        coords = _geocode(street, "", payload.get("postal_code", 1000))
        if coords:
            payload["latitude"], payload["longitude"] = coords

    is_rental = transaction_type.lower() in ("location", "à louer", "a louer", "louer")
    try:
        if is_rental:
            result_value = predict_rent(payload)
            write_field = "x_studio_x_predicted_rent"
        else:
            result_value = predict(payload)
            write_field = "x_studio_x_predicted_price"
    except Exception:
        _logger.exception("Webhook prediction failed for record %s", record_id)
        return

    try:
        common = xmlrpc.client.ServerProxy(f"{_ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(_ODOO_DB, _ODOO_USER, _ODOO_KEY, {})
        models = xmlrpc.client.ServerProxy(f"{_ODOO_URL}/xmlrpc/2/object")
        models.execute_kw(
            _ODOO_DB, uid, _ODOO_KEY,
            _ODOO_MODEL, "write",
            [[record_id], {write_field: round(result_value, 2)}],
        )
        _logger.info("Webhook: record %s → %s = %.2f", record_id, write_field, result_value)
    except Exception:
        _logger.exception("Odoo write-back failed for record %s", record_id)


@app.post("/odoo-webhook")
def odoo_webhook():
    """
    Receives Odoo 'Envoyer une notification webhook' POST.
    Maps Odoo Studio fields → predict() / predict_rent() → writes result back via XML-RPC.
    Returns 200 immediately; processing runs in a background thread.
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Empty body"}), 400

    record_id = body.get("id")
    if not record_id:
        return jsonify({"error": "Missing record id"}), 400

    threading.Thread(target=_process_webhook, args=(body,), daemon=True).start()
    return jsonify({"status": "accepted", "record_id": record_id}), 200


# --------------------------------------------------------------------------- #
# Dev server
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app.run(debug=True, port=5000)
