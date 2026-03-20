"""
predictor.py — Feature mapping + ML prediction logic.

Fully decoupled from Flask: can be imported and tested independently.

Score adjustments (from scores.md, applied after ML prediction):
  PEB   A=+4.5%  B=+3.5%  C=+1.75%  D=0%  E=-1.75%  F=-3.5%  G=-4.5%
  Avis  A=+7.5%  B=+5%    C=+2.5%   D=0%  E=-2.5%   F=-5%    G=-7.5%

PEB is NOT a model feature — only used for the post-prediction score multiplier.
Avis is a new quality rating field — only used for the post-prediction score multiplier.
Commune (optional) is geocoded via a static Belgian centroid table to improve lat/lon accuracy.

Commercial models (commercial_sale_model.pkl / commercial_rent_model.pkl):
  Additional post-prediction adjusters (not in model features):
  - hauteur_plafond > 6m  (warehouse/industrial only): +10%
  - quai_chargement True  (warehouse/industrial only): +8%
  - vitrine True          (shop/horeca only):          +5%
  - Clamp: total_adj clamped to [0.80, 1.30]
"""

import json
import logging
import math
import os
import joblib
import pandas as pd

_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Model loading (singleton)
# --------------------------------------------------------------------------- #

_MODEL = None
_FEATURE_NAMES: list[str] | None = None

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "model.pkl")
_FEAT_PATH  = os.path.join(os.path.dirname(__file__), "models", "model_metadata.json")

# Rental model (separate)
_RENTAL_MODEL = None
_RENTAL_FEATURE_NAMES: list[str] | None = None

_RENTAL_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "rental_model.pkl")
_RENTAL_FEAT_PATH  = os.path.join(os.path.dirname(__file__), "models", "rental_model_metadata.json")

# Commercial models (sale + rent)
_COMM_SALE_MODEL = None
_COMM_SALE_FEATURE_NAMES: list[str] | None = None
_COMM_RENT_MODEL = None
_COMM_RENT_FEATURE_NAMES: list[str] | None = None

_COMM_SALE_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "commercial_sale_model.pkl")
_COMM_SALE_FEAT_PATH  = os.path.join(os.path.dirname(__file__), "models", "commercial_sale_metadata.json")
_COMM_RENT_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "commercial_rent_model.pkl")
_COMM_RENT_FEAT_PATH  = os.path.join(os.path.dirname(__file__), "models", "commercial_rent_metadata.json")


def get_model():
    global _MODEL
    if _MODEL is None:
        _logger.info("Loading model from %s", _MODEL_PATH)
        _MODEL = joblib.load(_MODEL_PATH)
        _logger.info("Model loaded: %s", type(_MODEL).__name__)
    return _MODEL


def get_feature_names() -> list[str]:
    global _FEATURE_NAMES
    if _FEATURE_NAMES is None:
        if os.path.exists(_FEAT_PATH):
            with open(_FEAT_PATH) as f:
                meta = json.load(f)
            _FEATURE_NAMES = meta.get("features", [])
        else:
            m = get_model()
            _FEATURE_NAMES = list(getattr(m, "feature_names_in_", []))
    return _FEATURE_NAMES


def get_metadata() -> dict:
    if os.path.exists(_FEAT_PATH):
        with open(_FEAT_PATH) as f:
            return json.load(f)
    return {}


# ── Rental model helpers ─────────────────────────────────────────────────────

def get_rental_model():
    global _RENTAL_MODEL
    if _RENTAL_MODEL is None:
        _logger.info("Loading rental model from %s", _RENTAL_MODEL_PATH)
        _RENTAL_MODEL = joblib.load(_RENTAL_MODEL_PATH)
        _logger.info("Rental model loaded: %s", type(_RENTAL_MODEL).__name__)
    return _RENTAL_MODEL


def get_rental_feature_names() -> list[str]:
    global _RENTAL_FEATURE_NAMES
    if _RENTAL_FEATURE_NAMES is None:
        if os.path.exists(_RENTAL_FEAT_PATH):
            with open(_RENTAL_FEAT_PATH) as f:
                meta = json.load(f)
            _RENTAL_FEATURE_NAMES = meta.get("features", [])
        else:
            m = get_rental_model()
            _RENTAL_FEATURE_NAMES = list(getattr(m, "feature_names_in_", []))
    return _RENTAL_FEATURE_NAMES


def get_rental_metadata() -> dict:
    if os.path.exists(_RENTAL_FEAT_PATH):
        with open(_RENTAL_FEAT_PATH) as f:
            return json.load(f)
    return {}


# ── Commercial model helpers ──────────────────────────────────────────────────

def _get_commercial_sale_model():
    global _COMM_SALE_MODEL
    if _COMM_SALE_MODEL is None:
        _logger.info("Loading commercial sale model from %s", _COMM_SALE_MODEL_PATH)
        _COMM_SALE_MODEL = joblib.load(_COMM_SALE_MODEL_PATH)
    return _COMM_SALE_MODEL


def _get_commercial_sale_feature_names() -> list[str]:
    global _COMM_SALE_FEATURE_NAMES
    if _COMM_SALE_FEATURE_NAMES is None:
        if os.path.exists(_COMM_SALE_FEAT_PATH):
            with open(_COMM_SALE_FEAT_PATH) as f:
                _COMM_SALE_FEATURE_NAMES = json.load(f).get("features", [])
        else:
            _COMM_SALE_FEATURE_NAMES = list(
                getattr(_get_commercial_sale_model(), "feature_names_in_", [])
            )
    return _COMM_SALE_FEATURE_NAMES


def _get_commercial_rent_model():
    global _COMM_RENT_MODEL
    if _COMM_RENT_MODEL is None:
        _logger.info("Loading commercial rental model from %s", _COMM_RENT_MODEL_PATH)
        _COMM_RENT_MODEL = joblib.load(_COMM_RENT_MODEL_PATH)
    return _COMM_RENT_MODEL


def _get_commercial_rent_feature_names() -> list[str]:
    global _COMM_RENT_FEATURE_NAMES
    if _COMM_RENT_FEATURE_NAMES is None:
        if os.path.exists(_COMM_RENT_FEAT_PATH):
            with open(_COMM_RENT_FEAT_PATH) as f:
                _COMM_RENT_FEATURE_NAMES = json.load(f).get("features", [])
        else:
            _COMM_RENT_FEATURE_NAMES = list(
                getattr(_get_commercial_rent_model(), "feature_names_in_", [])
            )
    return _COMM_RENT_FEATURE_NAMES


def get_commercial_metadata() -> dict:
    """Return metadata for both commercial models (sale + rent)."""
    meta: dict = {}
    for path, key in (
        (_COMM_SALE_FEAT_PATH, "sale"),
        (_COMM_RENT_FEAT_PATH, "rent"),
    ):
        if os.path.exists(path):
            with open(path) as f:
                meta[key] = json.load(f)
    return meta


# --------------------------------------------------------------------------- #
# Score multiplier tables (boss-defined, scores.md)
# PEB and Avis are applied AFTER the ML prediction — they are NOT model features.
# --------------------------------------------------------------------------- #

PEB_SCORES = {
    "A": 0.045, "B": 0.035, "C": 0.0175,
    "D": 0.0,   "E": -0.0175, "F": -0.035, "G": -0.045,
}

AVIS_SCORES = {
    "A": 0.075, "B": 0.05,  "C": 0.025,
    "D": 0.0,   "E": -0.025, "F": -0.05,  "G": -0.075,
}

# --------------------------------------------------------------------------- #
# Categorical mappings
# --------------------------------------------------------------------------- #

STATE_MAP = {
    "AS_NEW": 0, "GOOD": 1, "TO_BE_DONE_UP": 2,
    "TO_RENOVATE": 3, "TO_RESTORE": 4,
    "New": 0, "Good": 1, "Fair": 2, "Poor": 3, "Needs Renovation": 4,
}
TYPE_MAP = {
    "HOUSE": 0, "APARTMENT": 1, "VILLA": 2, "STUDIO": 3,
    "House": 0, "Apartment": 1, "Villa": 2, "Studio": 3,
}
REGION_MAP = {
    "Flanders": 0, "Wallonia": 1, "Brussels": 2,
    "Flemish Region": 0, "Walloon Region": 1, "Brussels-Capital Region": 2,
}
HEATING_MAP = {
    "GAS": 0, "FUEL_OIL": 1, "ELECTRIC": 2,
    "HEAT_PUMP": 3, "PELLET": 4, "WOOD": 5, "SOLAR": 6,
    "Gas": 0, "Electric": 2, "Heat pump": 3,
}
COMMERCIAL_TYPE_MAP = {
    # English (Immoweb API values)
    "COMMERCIAL": 0, "RETAIL": 0, "SHOP": 0,
    "OFFICE": 1, "OFFICES": 1,
    "WAREHOUSE": 2, "STORAGE": 2,
    "INDUSTRIAL": 3, "INDUSTRY": 3,
    "HORECA": 4, "RESTAURANT": 4, "HOTEL": 4,
    # French (Odoo display values)
    "Commerce": 0, "Dükkan": 0,
    "Bureau": 1, "Ofis": 1,
    "Entrepôt": 2, "Entrepot": 2, "Depo": 2,
    "Industrie": 3, "Sanayi": 3,
    "Horeca": 4,
}

FLOODING_ZONE_COLS = [
    "FZ_CIRCUMSCRIBED_FLOOD_ZONE",
    "FZ_CIRCUMSCRIBED_WATERSIDE_ZONE",
    "FZ_NON_FLOOD_ZONE",
    "FZ_POSSIBLE_FLOOD_ZONE",
    "FZ_POSSIBLE_N_CIRCUMSCRIBED_FLOOD_ZONE",
    "FZ_POSSIBLE_N_CIRCUMSCRIBED_WATERSIDE_ZONE",
    "FZ_RECOGNIZED_FLOOD_ZONE",
    "FZ_RECOGNIZED_N_CIRCUMSCRIBED_FLOOD_ZONE",
    "FZ_RECOGNIZED_N_CIRCUMSCRIBED_WATERSIDE_FLOOD_ZONE",
]
FLOODING_ZONE_MAP = {v.replace("FZ_", ""): i for i, v in enumerate(FLOODING_ZONE_COLS)}

SALE_COLS = [
    "Sale_annuity_lump_sum",
    "Sale_annuity_monthly_amount",
    "Sale_annuity_without_lump_sum",
    "Sale_homes_to_build",
    "Sale_residential_monthly_rent",
    "Sale_residential_sale",
]
SALE_MAP = {v.replace("Sale_", ""): i for i, v in enumerate(SALE_COLS)}

DEFAULT_VALUES = {
    "BathroomCount": 0,
    "ShowerCount": 0,
    "ToiletCount": 1,
    "GarageCount": 0,
    "GardenArea": 0,
    "SurfaceOfPlot": 0,
    "MonthlyCharges": 0,
    "NumberOfFacades": 2,
    "EPCkWh": 200,
    "FloorNumber": 0,
    "TotalFloors": 1,
    "DistanceToBrussels": 80,
    "MunicipalityAvgPricePerM2": 2500,
    "PostalCode": 1000,
    "Locality": 0,
    "Fireplace": 0,
    "Furnished": 0,
    "Garden": 0,
    "SwimmingPool": 0,
    "Terrace": 0,
    "Kitchen": 0,
    "Garage": 0,
    "Basement": 0,
    "Attic": 0,
    "Lift": 0,
    "HasSolarPanels": 0,
    "DoubleGlazing": 0,
    "BedroomRatio": 0.4,
    "HouseAge": 40,
    "RenovationRecency": 40,
    "StateOfBuilding_Num": 1,
    "TypeOfProperty_Num": 0,
    "Region_Num": 0,
    "HeatingType_Num": 0,
    # Default to Brussels centre — overridden when commune is supplied
    "Latitude": 50.8503,
    "Longitude": 4.3517,
    # Statbel municipal socio-economics (Belgian medians)
    "MedianIncome": 25000,
    "PopulationDensity": 400,
}

# --------------------------------------------------------------------------- #
# Belgian commune centroid lookup (static table, no external API)
# Keys: lowercase commune name — both French and Dutch forms accepted
# --------------------------------------------------------------------------- #

_BRUSSELS_COORDS = (50.8503, 4.3517)

COMMUNE_CENTROIDS: dict[str, tuple[float, float]] = {
    # Brussels Capital Region
    "bruxelles": _BRUSSELS_COORDS, "brussels": _BRUSSELS_COORDS, "brussel": _BRUSSELS_COORDS,
    "anderlecht": (50.8365, 4.3044),
    "molenbeek-saint-jean": (50.8569, 4.3312), "sint-jans-molenbeek": (50.8569, 4.3312),
    "molenbeek": (50.8569, 4.3312),
    "schaerbeek": (50.8680, 4.3818), "schaarbeek": (50.8680, 4.3818),
    "ixelles": (50.8272, 4.3736), "elsene": (50.8272, 4.3736),
    "forest": (50.8122, 4.3389), "vorst": (50.8122, 4.3389),
    "jette": (50.8804, 4.3236),
    "etterbeek": (50.8345, 4.3919),
    "woluwe-saint-lambert": (50.8428, 4.4279), "sint-lambrechts-woluwe": (50.8428, 4.4279),
    "woluwe-saint-pierre": (50.8253, 4.4407), "sint-pieters-woluwe": (50.8253, 4.4407),
    "uccle": (50.7976, 4.3609), "ukkel": (50.7976, 4.3609),
    "auderghem": (50.8147, 4.4305), "oudergem": (50.8147, 4.4305),
    "watermael-boitsfort": (50.8017, 4.4171), "watermaal-bosvoorde": (50.8017, 4.4171),
    "ganshoren": (50.8805, 4.3119),
    "berchem-sainte-agathe": (50.8737, 4.2977), "sint-agatha-berchem": (50.8737, 4.2977),
    "koekelberg": (50.8701, 4.3329),
    "saint-gilles": (50.8260, 4.3491), "sint-gillis": (50.8260, 4.3491),
    "evere": (50.8742, 4.4063),
    "saint-josse-ten-noode": (50.8556, 4.3706), "sint-joost-ten-node": (50.8556, 4.3706),

    # Flanders — major cities and communes
    "antwerpen": (51.2194, 4.4025), "antwerp": (51.2194, 4.4025),
    "gent": (51.0543, 3.7174), "ghent": (51.0543, 3.7174),
    "brugge": (51.2093, 3.2247), "bruges": (51.2093, 3.2247),
    "leuven": (50.8798, 4.7005), "louvain": (50.8798, 4.7005),
    "mechelen": (51.0282, 4.4777), "malines": (51.0282, 4.4777),
    "aalst": (50.9377, 4.0387), "alost": (50.9377, 4.0387),
    "sint-niklaas": (51.1608, 4.1427),
    "kortrijk": (50.8281, 3.2642), "courtrai": (50.8281, 3.2642),
    "hasselt": (50.9307, 5.3378),
    "genk": (50.9651, 5.5027),
    "turnhout": (51.3238, 4.9475),
    "roeselare": (50.9437, 3.1257), "roulers": (50.9437, 3.1257),
    "oostende": (51.2308, 2.9174), "ostend": (51.2308, 2.9174), "ostende": (51.2308, 2.9174),
    "sint-truiden": (50.8148, 5.1875), "saint-trond": (50.8148, 5.1875),
    "herentals": (51.1773, 4.8378),
    "mol": (51.1898, 5.1133),
    "lokeren": (51.1026, 3.9873),
    "beveren": (51.2101, 4.2565),
    "halle": (50.7314, 4.2317), "hal": (50.7314, 4.2317),
    "vilvoorde": (50.9305, 4.4269), "vilvorde": (50.9305, 4.4269),
    "dendermonde": (51.0275, 4.1008), "termonde": (51.0275, 4.1008),
    "ronse": (50.7432, 3.5967), "renaix": (50.7432, 3.5967),
    "oudenaarde": (50.8449, 3.6068), "audenarde": (50.8449, 3.6068),
    "ieper": (50.8500, 2.8803), "ypres": (50.8500, 2.8803),
    "waregem": (50.8850, 3.4267),
    "deinze": (50.9811, 3.5318),
    "eeklo": (51.1855, 3.5665),
    "zottegem": (50.8702, 3.8101),
    "ninove": (50.8420, 4.0133),
    "geraardsbergen": (50.7717, 3.8822), "grammont": (50.7717, 3.8822),
    "wetteren": (51.0032, 3.8837),
    "temse": (51.1249, 4.2099), "tamise": (51.1249, 4.2099),
    "willebroek": (51.0569, 4.3579),
    "boom": (51.0895, 4.3672),
    "kontich": (51.1271, 4.4512),
    "schoten": (51.2663, 4.4988),
    "kapellen": (51.3167, 4.4295),
    "brasschaat": (51.2970, 4.4893),
    "geel": (51.1613, 4.9916),
    "lier": (51.1316, 4.5664), "lierre": (51.1316, 4.5664),
    "heist-op-den-berg": (51.0793, 4.7183),
    "bornem": (51.0985, 4.2419),
    "diest": (50.9845, 5.0553),
    "tienen": (50.8020, 4.9426), "tirlemont": (50.8020, 4.9426),
    "tongeren": (50.7805, 5.4661), "tongres": (50.7805, 5.4661),
    "bilzen": (50.8694, 5.5208),
    "maasmechelen": (50.9718, 5.7065),
    "lanaken": (50.8887, 5.6474),
    "maaseik": (51.0955, 5.7883),
    "bree": (51.1403, 5.5953),
    "peer": (51.1320, 5.4571),
    "lommel": (51.2294, 5.3107),
    "houthalen-helchteren": (51.0330, 5.3773),
    "zonhoven": (50.9929, 5.3725),
    "diepenbeek": (50.9082, 5.4145),
    "beringen": (51.0524, 5.2271),
    "leopoldsburg": (51.1175, 5.2581),
    "torhout": (51.0697, 3.0997),
    "veurne": (51.0723, 2.6590), "furnes": (51.0723, 2.6590),
    "poperinge": (50.8600, 2.7264),
    "diksmuide": (51.0329, 2.8627), "dixmude": (51.0329, 2.8627),
    "tielt": (50.9996, 3.3270),
    "izegem": (50.9163, 3.2134),
    "menen": (50.7989, 3.1195), "menin": (50.7989, 3.1195),
    "wevelgem": (50.8036, 3.1804),
    "harelbeke": (50.8583, 3.3117),
    "zwevegem": (50.8043, 3.3374),

    # Wallonia — major cities and communes
    "liège": (50.6326, 5.5797), "luik": (50.6326, 5.5797), "liege": (50.6326, 5.5797),
    "namur": (50.4669, 4.8675), "namen": (50.4669, 4.8675),
    "charleroi": (50.4108, 4.4445),
    "mons": (50.4542, 3.9517), "bergen": (50.4542, 3.9517),
    "la louvière": (50.4806, 4.1886), "la-louvière": (50.4806, 4.1886),
    "la louviere": (50.4806, 4.1886), "la-louviere": (50.4806, 4.1886),
    "seraing": (50.5916, 5.5011),
    "verviers": (50.5886, 5.8636),
    "mouscron": (50.7441, 3.2065), "moeskroen": (50.7441, 3.2065),
    "tournai": (50.6049, 3.3888), "doornik": (50.6049, 3.3888),
    "herstal": (50.6671, 5.6351),
    "ans": (50.6599, 5.5284),
    "huy": (50.5196, 5.2361), "hoei": (50.5196, 5.2361),
    "waremme": (50.6979, 5.2562), "borgworm": (50.6979, 5.2562),
    "hannut": (50.6734, 5.0862), "hannuit": (50.6734, 5.0862),
    "gembloux": (50.5614, 4.6965),
    "fleurus": (50.4808, 4.5427),
    "châtelet": (50.4030, 4.5208), "chatelet": (50.4030, 4.5208),
    "binche": (50.4100, 4.1671),
    "soignies": (50.5752, 4.0715), "zinnik": (50.5752, 4.0715),
    "braine-le-comte": (50.6079, 4.1303),
    "tubize": (50.6941, 4.2026), "tubeke": (50.6941, 4.2026),
    "nivelles": (50.5983, 4.3307), "nijvel": (50.5983, 4.3307),
    "wavre": (50.7170, 4.6074), "waver": (50.7170, 4.6074),
    "jodoigne": (50.7226, 4.8637), "geldenaken": (50.7226, 4.8637),
    "braine-l'alleud": (50.6851, 4.3801), "braine-lalleud": (50.6851, 4.3801),
    "waterloo": (50.7147, 4.3985),
    "rixensart": (50.7188, 4.5354),
    "ottignies-louvain-la-neuve": (50.6698, 4.6073), "ottignies": (50.6698, 4.6073),
    "louvain-la-neuve": (50.6698, 4.6073),
    "genappe": (50.5899, 4.4483),
    "andenne": (50.4817, 5.0956),
    "sambreville": (50.4363, 4.5986),
    "dinant": (50.2614, 4.9120),
    "ciney": (50.2986, 5.1007),
    "rochefort": (50.1615, 5.2237),
    "marche-en-famenne": (50.2269, 5.3456), "marche": (50.2269, 5.3456),
    "bastogne": (50.0048, 5.7151),
    "arlon": (49.6852, 5.8164), "aarlen": (49.6852, 5.8164),
    "virton": (49.5669, 5.5312),
    "neufchâteau": (49.8445, 5.4356), "neufchateau": (49.8445, 5.4356),
    "libramont-chevigny": (49.9197, 5.3786), "libramont": (49.9197, 5.3786),
    "saint-hubert": (50.0257, 5.3783),
    "vielsalm": (50.2891, 5.9174),
    "malmedy": (50.4272, 6.0277),
    "spa": (50.4920, 5.8650),
    "theux": (50.5387, 5.8156),
    "pepinster": (50.5708, 5.8082),
    "eupen": (50.6278, 6.0328),
    "visé": (50.7367, 5.7089), "vise": (50.7367, 5.7089), "wezet": (50.7367, 5.7089),
    "flémalle": (50.5961, 5.4696), "flemalle": (50.5961, 5.4696),
    "grâce-hollogne": (50.6296, 5.4766), "grace-hollogne": (50.6296, 5.4766),
    "saint-nicolas": (50.6431, 5.5409),
    "nandrin": (50.4988, 5.4091),
    "amay": (50.5492, 5.3156),
    "wanze": (50.5331, 5.2023),
    "florenville": (49.6947, 5.3069),
    "bouillon": (49.7933, 5.0642),
    "bertrix": (49.8533, 5.2506),
    "aubange": (49.5815, 5.7997),
    "messancy": (49.5937, 5.8117),
    "habay": (49.7228, 5.6403),
    "étalle": (49.6726, 5.5966), "etalle": (49.6726, 5.5966),
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two lat/lon points (Haversine formula)."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def get_commune_latlon(commune: str) -> tuple[float, float] | None:
    """Return (lat, lon) centroid for a Belgian commune, or None if not found."""
    return COMMUNE_CENTROIDS.get(commune.strip().lower())


# --------------------------------------------------------------------------- #
# Core predict function
# --------------------------------------------------------------------------- #

def predict(inp: dict) -> float:
    """
    Map a user-supplied dict to the model's feature space and return a price.

    PEB and Avis are NOT passed to the ML model. They are applied as
    post-prediction percentage multipliers (scores.md).

    Parameters
    ----------
    inp : dict
        Keys match the API schema (snake_case or PascalCase both accepted).
        Required: room_count, living_area, number_of_facades, bedroom_count.
        Optional new: avis (A-G), commune (Belgian municipality name).

    Returns
    -------
    float — adjusted price in EUR
    """
    model = get_model()
    feature_names = get_feature_names()

    # Extract score inputs before building feature dict (NOT sent to model)
    peb_raw  = str(inp.get("peb",  "D")).strip().upper()
    avis_raw = str(inp.get("avis", "D")).strip().upper()

    # Start from defaults
    data: dict = dict(DEFAULT_VALUES)

    # --- Map incoming snake_case to PascalCase ---
    alias = {
        "room_count":           "RoomCount",
        "living_area":          "LivingArea",
        "number_of_facades":    "NumberOfFacades",
        "bedroom_count":        "BedroomCount",
        "bathroom_count":       "BathroomCount",
        "shower_count":         "ShowerCount",
        "toilet_count":         "ToiletCount",
        "garage_count":         "GarageCount",
        "construction_year":    "ConstructionYear",
        "renovation_year":      "RenovationYear",
        "monthly_charges":      "MonthlyCharges",
        "garden_area":          "GardenArea",
        "surface_of_plot":      "SurfaceOfPlot",
        "postal_code":          "PostalCode",
        "floor_number":         "FloorNumber",
        "total_floors":         "TotalFloors",
        "epc_kwh":              "EPCkWh",
        "distance_to_brussels": "DistanceToBrussels",
        "municipality_avg":     "MunicipalityAvgPricePerM2",
        "latitude":             "Latitude",
        "longitude":            "Longitude",
        "fireplace":            "Fireplace",
        "furnished":            "Furnished",
        "garden":               "Garden",
        "swimming_pool":        "SwimmingPool",
        "terrace":              "Terrace",
        "kitchen":              "Kitchen",
        "garage":               "Garage",
        "basement":             "Basement",
        "attic":                "Attic",
        "lift":                 "Lift",
        "has_solar_panels":     "HasSolarPanels",
        "double_glazing":       "DoubleGlazing",
        "state_of_building":    "_state",
        "type_of_property":     "_type",
        "region":               "_region",
        "heating_type":         "_heating",
        "flooding_zone":        "_flooding",
        "type_of_sale":         "_sale",
        "commune":              "_commune",
        # peb and avis are score multipliers only — excluded from model features
    }

    for k, v in inp.items():
        if k in ("peb", "avis"):
            continue  # handled as score multipliers below
        mapped = alias.get(k, k)
        if mapped.startswith("_"):
            data[mapped] = v
        else:
            data[mapped] = int(v) if isinstance(v, bool) else v

    # --- Commune → lat/lon (static Belgian centroid lookup) ---
    commune_raw = data.pop("_commune", None)
    if commune_raw:
        coords = get_commune_latlon(str(commune_raw))
        if coords:
            data["Latitude"], data["Longitude"] = coords
            data["DistanceToBrussels"] = _haversine(
                coords[0], coords[1],
                _BRUSSELS_COORDS[0], _BRUSSELS_COORDS[1],
            )

    # --- Encode categoricals ---
    if "_state" in data:
        raw = str(data.pop("_state")).strip()
        data["StateOfBuilding_Num"] = STATE_MAP.get(raw, STATE_MAP.get(raw.upper(), 1))

    if "_type" in data:
        raw = str(data.pop("_type")).strip()
        data["TypeOfProperty_Num"] = TYPE_MAP.get(raw, TYPE_MAP.get(raw.upper(), 0))

    if "_region" in data:
        raw = str(data.pop("_region")).strip()
        data["Region_Num"] = REGION_MAP.get(raw, 0)

    if "_heating" in data:
        raw = str(data.pop("_heating")).strip()
        data["HeatingType_Num"] = HEATING_MAP.get(raw, HEATING_MAP.get(raw.upper(), 0))

    # One-hot FloodingZone
    fz_raw = data.pop("_flooding", "NON_FLOOD_ZONE")
    fz_idx = FLOODING_ZONE_MAP.get(str(fz_raw), FLOODING_ZONE_MAP.get("NON_FLOOD_ZONE", 2))
    for i, col in enumerate(FLOODING_ZONE_COLS):
        data[col] = 1 if i == fz_idx else 0

    # One-hot TypeOfSale
    sale_raw = data.pop("_sale", "residential_sale")
    sale_idx = SALE_MAP.get(str(sale_raw), SALE_MAP.get("residential_sale", 5))
    for i, col in enumerate(SALE_COLS):
        data[col] = 1 if i == sale_idx else 0

    # Derived features
    construction_year = data.get("ConstructionYear", 2000 - data.get("HouseAge", 40))
    data["HouseAge"] = max(0, 2025 - int(construction_year))
    renovation_year = data.get("RenovationYear", None)
    data["RenovationRecency"] = (2025 - int(renovation_year)) if renovation_year else data["HouseAge"]
    room_count = max(data.get("RoomCount", 1), 1)
    bedroom_count = data.get("BedroomCount", 0)
    data["BedroomRatio"] = bedroom_count / room_count

    # Build DataFrame with model's expected feature order
    if feature_names:
        for feat in feature_names:
            if feat not in data:
                data[feat] = 0
        df_row = pd.DataFrame([data], columns=feature_names)
    else:
        df_row = pd.DataFrame([data])

    base_price = float(model.predict(df_row)[0])

    # --- Apply score multipliers (scores.md) ---
    peb_pct  = PEB_SCORES.get(peb_raw,  0.0)
    avis_pct = AVIS_SCORES.get(avis_raw, 0.0)
    return base_price * (1 + peb_pct) * (1 + avis_pct)


# --------------------------------------------------------------------------- #
# Rental prediction
# --------------------------------------------------------------------------- #

_RENTAL_DEFAULTS = {
    "BedroomCount": 1,
    "RoomCount": 3,
    "NumberOfFacades": 1,
    "StateOfBuilding_Num": 1,
    "TypeOfProperty_Num": 1,   # apartment default for rentals
    "Region_Num": 0,
    "HeatingType_Num": 0,
    "Furnished": 0,
    "Terrace": 0,
    "Garden": 0,
    "SwimmingPool": 0,
    "Fireplace": 0,
    "Lift": 0,
    "Kitchen": 0,
    "Garage": 0,
    "MonthlyCharges": 0,
    "HouseAge": 30,
    "BedroomRatio": 0.4,
    "Latitude": 50.8503,
    "Longitude": 4.3517,
    "DistanceToBrussels": 80,
    "PostalCode": 1000,
    "FloorNumber": 0,
    "EPCkWh": 200,
    "MedianIncome": 25000,
    "PopulationDensity": 400,
}

_RENTAL_ALIAS = {
    "living_area":          "LivingArea",
    "bedroom_count":        "BedroomCount",
    "room_count":           "RoomCount",
    "number_of_facades":    "NumberOfFacades",
    "furnished":            "Furnished",
    "terrace":              "Terrace",
    "garden":               "Garden",
    "swimming_pool":        "SwimmingPool",
    "fireplace":            "Fireplace",
    "lift":                 "Lift",
    "kitchen":              "Kitchen",
    "garage":               "Garage",
    "monthly_charges":      "MonthlyCharges",
    "construction_year":    "ConstructionYear",
    "floor_number":         "FloorNumber",
    "postal_code":          "PostalCode",
    "latitude":             "Latitude",
    "longitude":            "Longitude",
    "distance_to_brussels": "DistanceToBrussels",
    "epc_kwh":              "EPCkWh",
    "state_of_building":    "_state",
    "type_of_property":     "_type",
    "region":               "_region",
    "heating_type":         "_heating",
    "commune":              "_commune",
}


def predict_rent(inp: dict) -> float:
    """
    Predict monthly rental price (EUR/month) for a Belgian property.

    Uses the dedicated rental model (rental_model.pkl) trained on
    residential_monthly_rent listings from Immoweb.

    Parameters are identical to predict() — same snake_case keys accepted.
    PEB and Avis multipliers are applied as post-prediction score multipliers
    (same percentages as the sale model).

    Returns
    -------
    float — adjusted monthly rent in EUR
    """
    model         = get_rental_model()
    feature_names = get_rental_feature_names()

    # Extract PEB/Avis before building feature dict (NOT sent to model)
    peb_raw  = str(inp.get("peb",  "D")).strip().upper()
    avis_raw = str(inp.get("avis", "D")).strip().upper()

    data: dict = dict(_RENTAL_DEFAULTS)

    for k, v in inp.items():
        if k in ("peb", "avis"):
            continue
        mapped = _RENTAL_ALIAS.get(k, k)
        if mapped.startswith("_"):
            data[mapped] = v
        else:
            data[mapped] = int(v) if isinstance(v, bool) else v

    # Commune → lat/lon
    commune_raw = data.pop("_commune", None)
    if commune_raw:
        coords = get_commune_latlon(str(commune_raw))
        if coords:
            data["Latitude"], data["Longitude"] = coords
            data["DistanceToBrussels"] = _haversine(
                coords[0], coords[1],
                _BRUSSELS_COORDS[0], _BRUSSELS_COORDS[1],
            )

    # Encode categoricals
    if "_state" in data:
        raw = str(data.pop("_state")).strip()
        data["StateOfBuilding_Num"] = STATE_MAP.get(raw, STATE_MAP.get(raw.upper(), 1))
    if "_type" in data:
        raw = str(data.pop("_type")).strip()
        data["TypeOfProperty_Num"] = TYPE_MAP.get(raw, TYPE_MAP.get(raw.upper(), 1))
    if "_region" in data:
        raw = str(data.pop("_region")).strip()
        data["Region_Num"] = REGION_MAP.get(raw, 0)
    if "_heating" in data:
        raw = str(data.pop("_heating")).strip()
        data["HeatingType_Num"] = HEATING_MAP.get(raw, HEATING_MAP.get(raw.upper(), 0))

    # Derived
    construction_year = data.pop("ConstructionYear", None)
    if construction_year:
        data["HouseAge"] = max(0, 2025 - int(construction_year))
    room_count = max(data.get("RoomCount", 1), 1)
    data["BedroomRatio"] = data.get("BedroomCount", 1) / room_count

    if feature_names:
        for feat in feature_names:
            if feat not in data:
                data[feat] = 0
        df_row = pd.DataFrame([data], columns=feature_names)
    else:
        df_row = pd.DataFrame([data])

    base_rent = float(model.predict(df_row)[0])

    # Apply score multipliers (same as sale model — scores.md)
    peb_pct  = PEB_SCORES.get(peb_raw,  0.0)
    avis_pct = AVIS_SCORES.get(avis_raw, 0.0)
    return base_rent * (1 + peb_pct) * (1 + avis_pct)


# --------------------------------------------------------------------------- #
# Commercial prediction (sale + rent)
# --------------------------------------------------------------------------- #

_COMMERCIAL_DEFAULTS = {
    "TotalSurface":                      200.0,
    "CommercialType_Num":                0,       # retail
    "FloorCount":                        1,
    "FloorNumber":                       0,
    "PostalCode":                        1000,
    "Latitude":                          50.8503,
    "Longitude":                         4.3517,
    "DistanceToBrussels":                80.0,
    "MunicipalityAvgCommercialPricePerM2": 3000.0,
    "ConstructionYear":                  1985,
    "BuildingAge":                       40,
    "StateOfBuilding_Num":               1,
    "HeatingType_Num":                   0,
    "HasParking":                        0,
    "HasLift":                           0,
    "Region_Num":                        0,
    "MedianIncome":                      25000,
    "PopulationDensity":                 400,
}

_COMMERCIAL_ALIAS = {
    "surface_totale":        "TotalSurface",
    "total_surface":         "TotalSurface",
    "living_area":           "TotalSurface",   # fallback if residential field sent
    "commercial_type":       "_commercial_type",
    "floor_count":           "FloorCount",
    "floor_number":          "FloorNumber",
    "postal_code":           "PostalCode",
    "latitude":              "Latitude",
    "longitude":             "Longitude",
    "distance_to_brussels":  "DistanceToBrussels",
    "construction_year":     "ConstructionYear",
    "state_of_building":     "_state",
    "heating_type":          "_heating",
    "has_parking":           "HasParking",
    "parking":               "HasParking",
    "has_lift":              "HasLift",
    "lift":                  "HasLift",
    "region":                "_region",
    "commune":               "_commune",
}

# Commercial types for which warehouse-specific adjusters apply
_WAREHOUSE_TYPES = {"WAREHOUSE", "INDUSTRIAL", "Entrepôt", "Entrepot", "Depo", "Sanayi"}
# Commercial types for which shop-specific adjusters apply
_SHOP_TYPES = {"COMMERCIAL", "RETAIL", "SHOP", "HORECA", "Commerce", "Dükkan", "Horeca"}


def _build_commercial_features(inp: dict) -> tuple[dict, str]:
    """
    Map user input to the commercial model feature space.

    Returns (feature_dict, commercial_type_raw) where commercial_type_raw
    is the original string value for use in post-prediction adjusters.
    """
    data: dict = dict(_COMMERCIAL_DEFAULTS)
    commercial_type_raw = str(inp.get("commercial_type", "COMMERCIAL")).strip()

    for k, v in inp.items():
        if k in ("peb",):
            continue
        mapped = _COMMERCIAL_ALIAS.get(k, k)
        if mapped.startswith("_"):
            data[mapped] = v
        else:
            data[mapped] = int(v) if isinstance(v, bool) else v

    # Commune → lat/lon
    commune_raw = data.pop("_commune", None)
    if commune_raw:
        coords = get_commune_latlon(str(commune_raw))
        if coords:
            data["Latitude"], data["Longitude"] = coords
            data["DistanceToBrussels"] = _haversine(
                coords[0], coords[1],
                _BRUSSELS_COORDS[0], _BRUSSELS_COORDS[1],
            )

    # Commercial type encoding
    ct_raw = data.pop("_commercial_type", commercial_type_raw)
    commercial_type_raw = str(ct_raw).strip()
    data["CommercialType_Num"] = COMMERCIAL_TYPE_MAP.get(
        commercial_type_raw,
        COMMERCIAL_TYPE_MAP.get(commercial_type_raw.upper(), 0),
    )

    # State of building
    if "_state" in data:
        raw = str(data.pop("_state")).strip()
        data["StateOfBuilding_Num"] = STATE_MAP.get(raw, STATE_MAP.get(raw.upper(), 1))

    # Region
    if "_region" in data:
        raw = str(data.pop("_region")).strip()
        data["Region_Num"] = REGION_MAP.get(raw, 0)

    # Heating
    if "_heating" in data:
        raw = str(data.pop("_heating")).strip()
        data["HeatingType_Num"] = HEATING_MAP.get(raw, HEATING_MAP.get(raw.upper(), 0))

    # BuildingAge from ConstructionYear
    cy = data.get("ConstructionYear", 1985)
    data["BuildingAge"] = max(0, 2025 - int(cy))

    # LogSurface — model trained with this feature
    surface = float(data.get("TotalSurface", 1))
    data["LogSurface"] = math.log1p(max(surface, 0))

    return data, commercial_type_raw


def _apply_commercial_adjusters(base_price: float, inp: dict, commercial_type_raw: str) -> float:
    """Apply post-prediction adjusters (PEB + warehouse/shop-specific extras)."""
    peb_raw = str(inp.get("peb", "D")).strip().upper()
    peb_pct = PEB_SCORES.get(peb_raw, 0.0)

    extra = 0.0
    ct_upper = commercial_type_raw.upper()

    # Warehouse / industrial adjusters
    if ct_upper in {t.upper() for t in _WAREHOUSE_TYPES}:
        hauteur = float(inp.get("hauteur_plafond", 0) or 0)
        if hauteur > 6:
            extra += 0.10
        if inp.get("quai_chargement"):
            extra += 0.08

    # Shop / horeca adjusters
    if ct_upper in {t.upper() for t in _SHOP_TYPES}:
        if inp.get("vitrine"):
            extra += 0.05

    total_adj = (1 + peb_pct) * (1 + extra)
    # Safety clamp: prevent runaway values (max ±30%)
    total_adj = min(max(total_adj, 0.80), 1.30)
    return base_price * total_adj


def predict_commercial_sale(inp: dict) -> float:
    """
    Predict Belgian commercial real estate sale price (EUR).

    Required: commercial_type, surface_totale, region (or postal_code)
    Optional: construction_year, state_of_building, heating_type, has_parking,
              has_lift, floor_count, commune, peb,
              hauteur_plafond (warehouse/industrial: +10% if >6m),
              quai_chargement (warehouse/industrial: +8%),
              vitrine (shop/horeca: +5%)

    Returns: adjusted sale price in EUR
    """
    model         = _get_commercial_sale_model()
    feature_names = _get_commercial_sale_feature_names()

    data, commercial_type_raw = _build_commercial_features(inp)

    if feature_names:
        for feat in feature_names:
            if feat not in data:
                data[feat] = 0
        df_row = pd.DataFrame([data], columns=feature_names)
    else:
        df_row = pd.DataFrame([data])

    # Model trained on log1p(price) — convert back to original scale
    log_pred = float(model.predict(df_row)[0])
    base_price = math.expm1(log_pred) if log_pred > 1 else log_pred
    return _apply_commercial_adjusters(base_price, inp, commercial_type_raw)


def predict_commercial_rent(inp: dict) -> float:
    """
    Predict Belgian commercial real estate monthly rent (EUR/month).

    Same input schema as predict_commercial_sale().
    Returns: adjusted monthly rent in EUR
    """
    model         = _get_commercial_rent_model()
    feature_names = _get_commercial_rent_feature_names()

    data, commercial_type_raw = _build_commercial_features(inp)

    if feature_names:
        for feat in feature_names:
            if feat not in data:
                data[feat] = 0
        df_row = pd.DataFrame([data], columns=feature_names)
    else:
        df_row = pd.DataFrame([data])

    # Model trained on log1p(rent) — convert back to original scale
    log_pred = float(model.predict(df_row)[0])
    base_rent = math.expm1(log_pred) if log_pred > 1 else log_pred
    return _apply_commercial_adjusters(base_rent, inp, commercial_type_raw)
