"""
batch.py — Odoo SaaS <-> ImmoApp prediction batch script.

Runs on OVH VPS (cron every 5 minutes).
Flow:
  1. Authenticate to Odoo SaaS via XML-RPC
  2. Fetch records where x_studio_x_predicted_price = 0 (not yet estimated)
  3. Call /predict for each record
  4. Write the result back to Odoo (x_studio_x_predicted_price field)

Configuration: copy .env.example to .env and fill in credentials.

Usage:
  python batch.py             # normal run
  python batch.py --dry-run   # fetch + predict, skip Odoo write
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

# ── Configuration ────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

ODOO_URL   = os.getenv("ODOO_URL")
ODOO_DB    = os.getenv("ODOO_DB")
ODOO_USER  = os.getenv("ODOO_USER")
ODOO_PASS  = os.getenv("ODOO_APIKEY")
ODOO_MODEL = os.getenv("ODOO_MODEL", "x_immobilier")
API_URL    = os.getenv("API_URL", "http://localhost:5000/predict")

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("odoo_batch")

# ── Odoo field mapping ────────────────────────────────────────────────────────
# Maps Odoo Studio field names -> /predict parameter names

FIELD_MAP = {
    "x_living_area":      "living_area",
    "x_bedroom_count":    "bedroom_count",
    "x_room_count":       "room_count",
    "x_facades":          "number_of_facades",
    "x_peb":              "peb",
    "x_avis":             "avis",
    "x_street":           "street",
    "x_commune":          "commune",
    "x_state_of_building":"state_of_building",
    "x_type_of_property": "type_of_property",
    "x_postal_code":      "postal_code",
    "x_region":           "region",
    "x_surface_of_plot":  "surface_of_plot",
    "x_bathroom_count":   "bathroom_count",
    "x_garden":           "garden",
    "x_terrace":          "terrace",
    "x_swimming_pool":    "swimming_pool",
}

ODOO_FIELDS = list(FIELD_MAP.keys()) + ["id", "x_studio_x_predicted_price"]

# Minimum required fields to call /predict
REQUIRED_PREDICT = {"room_count", "living_area", "number_of_facades", "bedroom_count"}


def odoo_connect():
    """Authenticate to Odoo and return (uid, models_proxy)."""
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
    """Return records where x_studio_x_predicted_price is 0 or not set."""
    domain = ["|", ("x_studio_x_predicted_price", "=", 0), ("x_studio_x_predicted_price", "=", False)]
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_MODEL, "search_read",
        [domain],
        {"fields": ODOO_FIELDS, "limit": 200},
    )
    logger.info("Found %d pending record(s)", len(records))
    return records


def build_payload(record):
    """Convert an Odoo record dict to a /predict payload."""
    payload = {}
    for odoo_field, predict_field in FIELD_MAP.items():
        val = record.get(odoo_field)
        if val not in (None, False, ""):
            payload[predict_field] = val

    # Remove commune if empty string
    if payload.get("commune") == "":
        del payload["commune"]

    return payload


def call_predict(payload):
    """Call the prediction API. Returns float price or None on error."""
    try:
        resp = requests.post(API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["predicted_price"])
    except requests.RequestException as exc:
        logger.error("API call failed: %s", exc)
        return None
    except (KeyError, ValueError) as exc:
        logger.error("Unexpected API response: %s", exc)
        return None


def write_price(uid, models, record_id, price):
    """Write x_studio_x_predicted_price back to Odoo."""
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_MODEL, "write",
        [[record_id], {"x_studio_x_predicted_price": price}],
    )


def run(dry_run=False):
    start = datetime.now()
    logger.info("=== Batch start (dry_run=%s) ===", dry_run)

    uid, models = odoo_connect()
    records = fetch_pending(uid, models)

    ok = skip = error = 0

    for rec in records:
        rec_id = rec["id"]
        payload = build_payload(rec)

        # Check minimum required fields
        missing = REQUIRED_PREDICT - set(payload.keys())
        if missing:
            logger.warning("Record %d skipped — missing fields: %s", rec_id, missing)
            skip += 1
            continue

        price = call_predict(payload)
        if price is None:
            error += 1
            continue

        if dry_run:
            logger.info("[DRY-RUN] Record %d -> €%.0f (not written)", rec_id, price)
        else:
            write_price(uid, models, rec_id, price)
            logger.info("Record %d -> €%.0f written", rec_id, price)

        ok += 1

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "=== Batch done in %.1fs — ok=%d  skipped=%d  errors=%d ===",
        elapsed, ok, skip, error,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ImmoApp Odoo batch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + predict, do not write to Odoo")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
