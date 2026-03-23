"""
batch_commercial.py — Odoo SaaS commercial real estate estimation batch script.

Flow:
  1. Authenticate to Odoo SaaS via XML-RPC
  2. Fetch records where bien_type = "Commercial" AND prediction = 0
  3. Call /predict-commercial for each record
  4. Write the result back to Odoo
     - À vendre → x_studio_x_predicted_price_commercial
     - À louer  → x_studio_x_predicted_rent_commercial

Configuration: same .env as batch.py / batch_rent.py

Usage:
  python batch_commercial.py           # normal run
  python batch_commercial.py --dry-run # fetch + predict, skip Odoo write
"""

import argparse
import logging
import os
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Configuration ─────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

ODOO_URL   = os.getenv("ODOO_URL")
ODOO_DB    = os.getenv("ODOO_DB")
ODOO_USER  = os.getenv("ODOO_USER")
ODOO_PASS  = os.getenv("ODOO_APIKEY")
ODOO_MODEL = os.getenv("ODOO_MODEL", "x_estimation")
API_BASE   = os.getenv("API_URL", "http://localhost:8080").rstrip("/predict").rstrip("/")
API_URL    = API_BASE + "/predict-commercial"

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("odoo_batch_commercial")

# ── Odoo field mapping ────────────────────────────────────────────────────────

FIELD_MAP = {
    # Shared location / building fields (same as residential)
    "x_studio_x_region":             "region",
    "x_studio_x_commune":            "commune",
    "x_studio_x_postal_code":        "postal_code",
    "x_studio_x_street":             "street",
    "x_studio_x_state_of_building":  "state_of_building",
    "x_studio_x_construction_year":  "construction_year",
    "x_studio_x_heating_type":       "heating_type",
    "x_studio_x_peb":                "peb",
    "x_studio_x_lift":               "has_lift",
    # Commercial-specific fields (actual Odoo Studio technical names)
    "x_studio_type_de_local":           "commercial_type",
    "x_studio_x_surface_totale":        "surface_totale",
    "x_studio_hauteur_sous_plafond_m":  "hauteur_plafond",
    "x_studio_quai_de_chargement":      "quai_chargement",
    "x_studio_x_vitrine":               "vitrine",
    # Routing fields
    "x_studio_x_transaction_type":      "transaction_type",
    "x_studio_x_bien_type":             "bien_type",
}

ODOO_FIELDS = list(FIELD_MAP.keys()) + [
    "id",
    "x_studio_prix_estime_commercial_",
    "x_studio_loyer_estime_commercial_mois",
]

REQUIRED_PREDICT = {"commercial_type", "surface_totale", "transaction_type"}


# ── Odoo helpers ──────────────────────────────────────────────────────────────

def odoo_connect():
    if not all([ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASS]):
        raise ValueError(
            "Missing Odoo credentials. Check ODOO_URL / ODOO_DB / ODOO_USER / ODOO_APIKEY in .env"
        )
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
    if not uid:
        raise PermissionError("Odoo authentication failed — check credentials in .env")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
    logger.info("Odoo authenticated (uid=%s, model=%s)", uid, ODOO_MODEL)
    return uid, models


def fetch_pending(uid, models):
    """Fetch commercial records (bien_type = Commercial) where prediction is still 0/False."""
    domain = [
        "&",
        ("x_studio_x_bien_type", "=", "Commercial"),
        "|",
        "|",
        ("x_studio_prix_estime_commercial_", "=", 0),
        ("x_studio_prix_estime_commercial_", "=", False),
        "|",
        ("x_studio_loyer_estime_commercial_mois", "=", 0),
        ("x_studio_loyer_estime_commercial_mois", "=", False),
    ]
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_MODEL, "search_read",
        [domain],
        {"fields": ODOO_FIELDS, "limit": 200},
    )
    logger.info("Found %d pending commercial record(s)", len(records))
    return records


def build_payload(record):
    payload = {}
    for odoo_field, predict_field in FIELD_MAP.items():
        val = record.get(odoo_field)
        if val not in (None, False, ""):
            payload[predict_field] = val
    return payload


def call_predict_commercial(payload):
    try:
        resp = requests.post(API_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # API returns either predicted_price_commercial or predicted_rent_commercial
        if "predicted_price_commercial" in data:
            return float(data["predicted_price_commercial"]), "sale"
        if "predicted_rent_commercial" in data:
            return float(data["predicted_rent_commercial"]), "rent"
        logger.error("Unexpected API response keys: %s", list(data.keys()))
        return None, None
    except requests.RequestException as exc:
        logger.error("API call failed: %s", exc)
        return None, None
    except (KeyError, ValueError) as exc:
        logger.error("Unexpected API response: %s", exc)
        return None, None


def write_result(uid, models, record_id, value, result_type):
    field = (
        "x_studio_prix_estime_commercial_"
        if result_type == "sale"
        else "x_studio_loyer_estime_commercial_mois"
    )
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_MODEL, "write",
        [[record_id], {field: value, "x_studio_value": value}],
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run=False):
    start = datetime.now()
    logger.info("=== Commercial batch start (dry_run=%s) ===", dry_run)

    uid, models = odoo_connect()
    records = fetch_pending(uid, models)

    ok = skip = error = 0

    for rec in records:
        rec_id = rec["id"]
        payload = build_payload(rec)

        missing = REQUIRED_PREDICT - set(payload.keys())
        if missing:
            logger.warning("Record %d skipped — missing fields: %s", rec_id, missing)
            skip += 1
            continue

        value, result_type = call_predict_commercial(payload)
        if value is None:
            error += 1
            continue

        unit = "€" if result_type == "sale" else "€/month"
        if dry_run:
            logger.info("[DRY-RUN] Record %d (%s) → %s%.0f (not written)", rec_id, result_type, "€", value)
        else:
            write_result(uid, models, rec_id, value, result_type)
            logger.info("Record %d (%s) → %.0f %s written", rec_id, result_type, value, unit)

        ok += 1

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "=== Commercial batch done in %.1fs — ok=%d  skipped=%d  errors=%d ===",
        elapsed, ok, skip, error,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ImmoApp commercial batch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + predict, do not write to Odoo")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
