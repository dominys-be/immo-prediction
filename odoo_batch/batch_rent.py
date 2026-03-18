"""
batch_rent.py — Odoo SaaS rental estimation batch script.

Runs on OVH VPS (cron every 5 minutes).
Flow:
  1. Authenticate to Odoo SaaS via XML-RPC
  2. Fetch rental records where x_studio_x_predicted_rent = 0 (not yet estimated)
  3. Call /predict-rent for each record
  4. Write the monthly rent estimate back to Odoo (x_studio_x_predicted_rent field)

Configuration: same .env as batch.py — uses ODOO_RENT_MODEL for the Odoo model name.

Usage:
  python batch_rent.py             # normal run
  python batch_rent.py --dry-run   # fetch + predict, skip Odoo write
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

ODOO_URL        = os.getenv("ODOO_URL")
ODOO_DB         = os.getenv("ODOO_DB")
ODOO_USER       = os.getenv("ODOO_USER")
ODOO_PASS       = os.getenv("ODOO_APIKEY")
ODOO_RENT_MODEL = os.getenv("ODOO_RENT_MODEL", "x_immobilier_loyer")
API_BASE        = os.getenv("API_URL", "http://localhost:5000").rstrip("/predict").rstrip("/")
API_URL         = API_BASE + "/predict-rent"

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("odoo_batch_rent")

# ── Odoo field mapping ────────────────────────────────────────────────────────

FIELD_MAP = {
    "x_studio_x_living_area":        "living_area",
    "x_studio_x_bedroom_count":      "bedroom_count",
    "x_studio_x_room_count":         "room_count",
    "x_studio_x_facades":            "number_of_facades",
    "x_studio_x_street":             "street",
    "x_studio_x_commune":            "commune",
    "x_studio_x_state_of_building":  "state_of_building",
    "x_studio_x_type_of_property":   "type_of_property",
    "x_studio_x_postal_code":        "postal_code",
    "x_studio_x_region":             "region",
    "x_studio_x_floor_number":       "floor_number",
    "x_studio_x_construction_year":  "construction_year",
    "x_studio_x_furnished":          "furnished",
    "x_studio_x_terrace":            "terrace",
    "x_studio_x_garden":             "garden",
    "x_studio_x_garage":             "garage",
    "x_studio_x_lift":               "lift",
    "x_studio_x_monthly_charges":    "monthly_charges",
    "x_studio_x_heating_type":       "heating_type",
    "x_studio_x_peb":                "peb",
    "x_studio_x_avis":               "avis",
}

ODOO_FIELDS = list(FIELD_MAP.keys()) + ["id", "x_studio_x_predicted_rent"]

REQUIRED_PREDICT = {"room_count", "living_area", "number_of_facades", "bedroom_count"}


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
    logger.info("Odoo authenticated (uid=%s, model=%s)", uid, ODOO_RENT_MODEL)
    return uid, models


def fetch_pending(uid, models):
    domain = [
        "&",
        ("x_transaction_type", "=", "location"),
        "|", ("x_studio_x_predicted_rent", "=", 0), ("x_studio_x_predicted_rent", "=", False),
    ]
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_RENT_MODEL, "search_read",
        [domain],
        {"fields": ODOO_FIELDS, "limit": 200},
    )
    logger.info("Found %d pending rental record(s)", len(records))
    return records


def build_payload(record):
    payload = {}
    for odoo_field, predict_field in FIELD_MAP.items():
        val = record.get(odoo_field)
        if val not in (None, False, ""):
            payload[predict_field] = val
    if payload.get("commune") == "":
        del payload["commune"]
    return payload


def call_predict_rent(payload):
    try:
        resp = requests.post(API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["predicted_rent"])
    except requests.RequestException as exc:
        logger.error("API call failed: %s", exc)
        return None
    except (KeyError, ValueError) as exc:
        logger.error("Unexpected API response: %s", exc)
        return None


def write_rent(uid, models, record_id, rent):
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        ODOO_RENT_MODEL, "write",
        [[record_id], {"x_studio_x_predicted_rent": rent}],
    )


def run(dry_run=False):
    start = datetime.now()
    logger.info("=== Rental batch start (dry_run=%s) ===", dry_run)

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

        rent = call_predict_rent(payload)
        if rent is None:
            error += 1
            continue

        if dry_run:
            logger.info("[DRY-RUN] Record %d -> €%.0f/month (not written)", rec_id, rent)
        else:
            write_rent(uid, models, rec_id, rent)
            logger.info("Record %d -> €%.0f/month written", rec_id, rent)

        ok += 1

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "=== Rental batch done in %.1fs — ok=%d  skipped=%d  errors=%d ===",
        elapsed, ok, skip, error,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ImmoApp rental batch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + predict, do not write to Odoo")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
