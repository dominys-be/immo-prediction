"""
train_demo_model.py — Trains a demo GradientBoostingRegressor with realistic
Belgian real estate data distributions. Run once to produce model.pkl.

Usage:
    python train_demo_model.py
"""

import json, os, random
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error

random.seed(42)
np.random.seed(42)

N = 6000

# ---- Simulate realistic Belgian real estate distributions ----

# Region: Flanders 60%, Wallonia 30%, Brussels 10%
region_num = np.random.choice([0, 1, 2], size=N, p=[0.60, 0.30, 0.10])

# Property type: House 60%, Apartment 40%
type_num = np.random.choice([0, 1], size=N, p=[0.60, 0.40])

# LivingArea: houses bigger
living_area = np.where(
    type_num == 0,
    np.random.normal(160, 50, N).clip(50, 500),   # house
    np.random.normal(90, 30, N).clip(30, 250),     # apartment
)

bedroom_count = np.where(type_num == 0, np.random.randint(2, 6, N), np.random.randint(1, 4, N))
room_count = bedroom_count + np.random.randint(1, 4, N)
bathroom_count = np.random.randint(1, 3, N)
shower_count = np.random.randint(0, 3, N)
toilet_count = np.random.randint(1, 4, N)
facades = np.where(type_num == 0, np.random.randint(2, 5, N), np.random.randint(1, 3, N))

construction_year = np.random.randint(1900, 2024, N)
house_age = 2025 - construction_year

state_num = np.random.choice([0,1,2,3,4], size=N, p=[0.10,0.40,0.20,0.20,0.10])

# Latitude/Longitude — random Belgian coordinates
# Belgium bounding box: lat 49.5–51.5, lon 2.5–6.4
latitude  = np.random.uniform(49.5, 51.5, N)
longitude = np.random.uniform(2.5,  6.4,  N)

# DistanceToBrussels computed from lat/lon (Haversine approximation)
_lat_bxl, _lon_bxl = 50.8503, 4.3517
distance_to_brussels = np.sqrt(
    ((latitude - _lat_bxl) * 111.0) ** 2
    + ((longitude - _lon_bxl) * 111.0 * np.cos(np.radians(50.85))) ** 2
)

fireplace = (np.random.rand(N) < 0.3).astype(int)
garden = (np.random.rand(N) < np.where(type_num == 0, 0.75, 0.25)).astype(int)
garden_area = np.where(garden == 1, np.random.exponential(200, N).clip(10, 3000), 0)
terrace = (np.random.rand(N) < 0.45).astype(int)
swimming_pool = (np.random.rand(N) < 0.08).astype(int)
furnished = (np.random.rand(N) < 0.15).astype(int)
garage = (np.random.rand(N) < 0.45).astype(int)
surface_of_plot = np.where(type_num == 0, np.random.normal(400, 200, N).clip(80, 3000), 0)
monthly_charges = np.where(type_num == 1, np.random.normal(200, 80, N).clip(0, 800), 0)
kitchen = np.random.randint(0, 6, N)  # 0=none, 5=luxury

# Postal code — rough price zones
postal_code = np.random.choice([
    1000, 1050, 1180, 2000, 2018, 2600, 3000, 8000, 9000, 9700,
    4000, 4020, 5000, 6000, 7000,
    1300, 1400, 1500,
], size=N)

# FloodingZone one-hot (mostly NON_FLOOD_ZONE)
fz_idx = np.random.choice(range(9), size=N, p=[0.01,0.01,0.80,0.08,0.03,0.02,0.02,0.02,0.01])
fz_cols = [
    "FZ_CIRCUMSCRIBED_FLOOD_ZONE", "FZ_CIRCUMSCRIBED_WATERSIDE_ZONE",
    "FZ_NON_FLOOD_ZONE", "FZ_POSSIBLE_FLOOD_ZONE",
    "FZ_POSSIBLE_N_CIRCUMSCRIBED_FLOOD_ZONE", "FZ_POSSIBLE_N_CIRCUMSCRIBED_WATERSIDE_ZONE",
    "FZ_RECOGNIZED_FLOOD_ZONE", "FZ_RECOGNIZED_N_CIRCUMSCRIBED_FLOOD_ZONE",
    "FZ_RECOGNIZED_N_CIRCUMSCRIBED_WATERSIDE_FLOOD_ZONE",
]
fz_data = np.zeros((N, 9), dtype=int)
for i, idx in enumerate(fz_idx):
    fz_data[i, idx] = 1

# TypeOfSale one-hot (mostly residential_sale)
sale_idx = np.random.choice(range(6), size=N, p=[0.01,0.01,0.01,0.03,0.02,0.92])
sale_cols = [
    "Sale_annuity_lump_sum", "Sale_annuity_monthly_amount",
    "Sale_annuity_without_lump_sum", "Sale_homes_to_build",
    "Sale_residential_monthly_rent", "Sale_residential_sale",
]
sale_data = np.zeros((N, 6), dtype=int)
for i, idx in enumerate(sale_idx):
    sale_data[i, idx] = 1

bedroom_ratio = bedroom_count / room_count.clip(1)
renovation_recency = house_age.copy()  # assume no renovation

# ---- Build price (target) with realistic relationships ----
base_price = (
    80_000
    + living_area * 1_800
    + bedroom_count * 8_000
    + room_count * 5_000
    - house_age * 500
    + fireplace * 6_000
    + garden * 8_000
    + garden_area * 15
    + terrace * 4_000
    + swimming_pool * 25_000
    + garage * 12_000
    - state_num * 20_000      # better state = lower num = higher price
    + surface_of_plot * 80
    - monthly_charges * 20
    + kitchen * 4_000
    # Location effect: Brussels centre premium, distance penalty
    - distance_to_brussels * 1_200
)

# Region multiplier
region_mult = np.where(region_num == 0, 1.0, np.where(region_num == 1, 0.75, 1.35))
base_price *= region_mult

# Type adjustment
base_price *= np.where(type_num == 0, 1.0, 0.85)

# Facades bonus (detached = 4 facades = most valuable)
base_price += (facades - 2) * 15_000

# Add noise (~8%)
noise = np.random.normal(0, base_price * 0.08)
price = (base_price + noise).clip(50_000, 3_000_000)

# ---- Assemble DataFrame ----
df = pd.DataFrame({
    "RoomCount":           room_count,
    "LivingArea":          living_area.astype(int),
    "NumberOfFacades":     facades,
    "BedroomCount":        bedroom_count,
    "BathroomCount":       bathroom_count,
    "ShowerCount":         shower_count,
    "ToiletCount":         toilet_count,
    "ConstructionYear":    construction_year,
    "PostalCode":          postal_code,
    "Fireplace":           fireplace,
    "Furnished":           furnished,
    "Garden":              garden,
    "GardenArea":          garden_area.astype(int),
    "SwimmingPool":        swimming_pool,
    "Terrace":             terrace,
    "Kitchen":             kitchen,
    "Garage":              garage,
    "MonthlyCharges":      monthly_charges.astype(int),
    "SurfaceOfPlot":       surface_of_plot.astype(int),
    "Latitude":            latitude.round(6),
    "Longitude":           longitude.round(6),
    "DistanceToBrussels":  distance_to_brussels.round(2),
    "StateOfBuilding_Num": state_num,
    "TypeOfProperty_Num":  type_num,
    "Region_Num":          region_num,
    "HouseAge":            house_age,
    "RenovationRecency":   renovation_recency,
    "BedroomRatio":        bedroom_ratio.round(4),
})

# Add one-hot columns
for j, col in enumerate(fz_cols):
    df[col] = fz_data[:, j]
for j, col in enumerate(sale_cols):
    df[col] = sale_data[:, j]

feature_cols = list(df.columns)
X = df[feature_cols]
y = price

# ---- Train ----
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = GradientBoostingRegressor(
    n_estimators=200,
    learning_rate=0.08,
    max_depth=5,
    min_samples_leaf=10,
    subsample=0.8,
    random_state=42,
)
model.fit(X_train, y_train)

preds = model.predict(X_test)
r2  = r2_score(y_test, preds)
mae = mean_absolute_error(y_test, preds)
print(f"R²:  {r2:.4f}")
print(f"MAE: {mae:,.0f} EUR")

# ---- Save ----
out_dir = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(out_dir, exist_ok=True)

model_path = os.path.join(out_dir, "model.pkl")
meta_path  = os.path.join(out_dir, "model_metadata.json")

joblib.dump(model, model_path)
print(f"Model saved → {model_path}")

meta = {
    "model_type": "GradientBoostingRegressor",
    "n_estimators": 200,
    "r2": round(r2, 4),
    "mae": round(mae, 2),
    "train_rows": len(X_train),
    "features": feature_cols,
    "note": "Demo model v2 — PEB removed from features (now a post-prediction multiplier). Retrain with real Immoweb data for production.",
}
with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)
print(f"Metadata saved → {meta_path}")
