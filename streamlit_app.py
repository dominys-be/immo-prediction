"""
ImmoApp - Streamlit Price Prediction Interface
Usage: streamlit run streamlit_app.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from immo_api.predictor import predict, predict_rent, PEB_SCORES, AVIS_SCORES, get_metadata, get_rental_metadata

_geolocator = Nominatim(user_agent="immoapp-price-predictor")

def _geocode(street: str, number: str, postal_code: int) -> tuple | None:
    query = f"{street} {number}, {postal_code}, Belgium".strip(", ")
    try:
        loc = _geolocator.geocode(query, timeout=5)
        if loc:
            return loc.latitude, loc.longitude
    except (GeocoderTimedOut, GeocoderUnavailable):
        pass
    return None

st.set_page_config(
    page_title="ImmoApp - Price Prediction",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 ImmoApp — Belgian Real Estate Price Prediction")
st.divider()

tab_sale, tab_rent = st.tabs(["🏠 À vendre — Estimation de prix", "🔑 À louer — Estimation de loyer"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SALE PRICE PREDICTION
# ═══════════════════════════════════════════════════════════════════════════════

with tab_sale:

    # Model info bar
    meta = get_metadata()
    if meta:
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Model", meta.get("model_name", "—"))
        col_m2.metric("R²", f"{meta.get('r2', 0):.4f}")
        col_m3.metric("MAE", f"€{meta.get('mae', 0):,.0f}")
        col_m4.metric("Training records", f"{meta.get('dataset_size', 0):,}")

    st.divider()

    with st.form("predict_form"):

        # ── Property basics ───────────────────────────────────────────────────
        st.subheader("Property Details")

        c1, c2, c3, c4 = st.columns(4)
        living_area       = c1.number_input("Living area (m²)", min_value=15, max_value=2000, value=120, step=5)
        surface_of_plot   = c2.number_input("Plot area (m²)", min_value=0, max_value=10000, value=0, step=10)
        bedroom_count     = c3.number_input("Bedrooms", min_value=0, max_value=20, value=3)
        number_of_facades = c4.number_input("Facades", min_value=1, max_value=4, value=2)

        c5, c6, c7, c8 = st.columns(4)
        bathroom_count = c5.number_input("Bathrooms", min_value=0, max_value=10, value=1)
        shower_count   = c6.number_input("Showers", min_value=0, max_value=10, value=0)
        toilet_count   = c7.number_input("Toilets", min_value=0, max_value=10, value=1)
        garage_count   = c8.number_input("Garage capacity", min_value=0, max_value=10, value=0)

        # ── Location ──────────────────────────────────────────────────────────
        st.subheader("Location")

        c9, c10, c11 = st.columns(3)
        commune     = c9.text_input("Commune / Municipality", placeholder="e.g. Gent, bruxelles, Liege")
        postal_code = c10.number_input("Postal code", min_value=1000, max_value=9999, value=1000)
        region      = c11.selectbox("Region", ["Flanders", "Wallonia", "Brussels"])

        cs1, cs2 = st.columns([3, 1])
        street       = cs1.text_input("Street", placeholder="e.g. Kortrijksesteenweg  (optional — improves accuracy)")
        house_number = cs2.text_input("Number", placeholder="e.g. 48")

        # ── Building characteristics ───────────────────────────────────────────
        st.subheader("Building Characteristics")

        c12, c13, c14, c15 = st.columns(4)
        type_of_property  = c12.selectbox("Property type", ["House", "Apartment", "Villa", "Studio"])
        state_of_building = c13.selectbox(
            "Building condition",
            ["Good", "New", "Fair", "Poor", "Needs Renovation"],
        )
        heating_type = c14.selectbox(
            "Heating",
            ["Gas", "Electric", "Heat pump", "Fuel Oil", "Pellet", "Wood", "Solar"],
        )
        construction_year = c15.number_input("Construction year", min_value=1800, max_value=2025, value=1985)

        c16, c17 = st.columns(2)
        floor_number = c16.number_input("Floor number", min_value=0, max_value=50, value=0)
        total_floors = c17.number_input("Total floors", min_value=1, max_value=50, value=3)

        # ── Amenities ──────────────────────────────────────────────────────────
        st.subheader("Amenities")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.markdown("**Outdoor**")
            garden        = st.checkbox("Garden")
            garden_area   = st.number_input("Garden area (m²)", min_value=0, max_value=5000, value=0, step=10, disabled=not garden)
            terrace       = st.checkbox("Terrace")
            swimming_pool = st.checkbox("Swimming pool")

        with col_b:
            st.markdown("**Indoor**")
            fireplace = st.checkbox("Fireplace")
            furnished = st.checkbox("Furnished")
            kitchen   = st.checkbox("Equipped kitchen")
            garage    = st.checkbox("Garage")
            basement  = st.checkbox("Basement")
            attic     = st.checkbox("Attic")
            lift      = st.checkbox("Lift / Elevator")

        with col_c:
            st.markdown("**Technical**")
            has_solar_panels = st.checkbox("Solar panels")
            double_glazing   = st.checkbox("Double glazing")
            monthly_charges  = st.number_input("Monthly charges (EUR)", min_value=0, max_value=5000, value=0, step=10)

        # ── PEB & Avis ────────────────────────────────────────────────────────
        st.subheader("Energy & Quality Rating")

        peb_options = ["A", "B", "C", "D", "E", "F", "G"]
        peb_labels  = {
            "A": "A (+4.5%)", "B": "B (+3.5%)", "C": "C (+1.75%)", "D": "D (0%)",
            "E": "E (-1.75%)", "F": "F (-3.5%)", "G": "G (-4.5%)",
        }
        avis_labels = {
            "A": "A (+7.5%)", "B": "B (+5.0%)", "C": "C (+2.5%)", "D": "D (0%)",
            "E": "E (-2.5%)", "F": "F (-5.0%)", "G": "G (-7.5%)",
        }

        cp1, cp2 = st.columns(2)
        peb  = cp1.select_slider("PEB (Energy Performance)", options=peb_options,
                                  value="D", format_func=lambda x: peb_labels[x])
        avis = cp2.select_slider("Avis (Quality Rating)", options=peb_options,
                                  value="D", format_func=lambda x: avis_labels[x])

        submitted = st.form_submit_button("🔍 Predict Sale Price", use_container_width=True, type="primary")

    # ── Result ────────────────────────────────────────────────────────────────
    if submitted:
        heating_map_input = {
            "Gas": "GAS", "Electric": "ELECTRIC", "Heat pump": "HEAT_PUMP",
            "Fuel Oil": "FUEL_OIL", "Pellet": "PELLET", "Wood": "WOOD", "Solar": "SOLAR",
        }

        inp = dict(
            living_area       = living_area,
            bedroom_count     = bedroom_count,
            room_count        = bedroom_count + 2,
            number_of_facades = number_of_facades,
            bathroom_count    = bathroom_count,
            shower_count      = shower_count,
            toilet_count      = toilet_count,
            garage_count      = garage_count,
            surface_of_plot   = surface_of_plot,
            garden            = int(garden),
            garden_area       = garden_area if garden else 0,
            terrace           = int(terrace),
            swimming_pool     = int(swimming_pool),
            fireplace         = int(fireplace),
            furnished         = int(furnished),
            kitchen           = int(kitchen),
            garage            = int(garage),
            basement          = int(basement),
            attic             = int(attic),
            lift              = int(lift),
            has_solar_panels  = int(has_solar_panels),
            double_glazing    = int(double_glazing),
            monthly_charges   = monthly_charges,
            construction_year = construction_year,
            floor_number      = floor_number,
            total_floors      = total_floors,
            postal_code       = postal_code,
            region            = region,
            type_of_property  = type_of_property.upper(),
            state_of_building = state_of_building.upper().replace(" ", "_"),
            heating_type      = heating_map_input.get(heating_type, "GAS"),
            commune           = commune.strip() if commune.strip() else None,
            peb               = peb,
            avis              = avis,
        )
        if not inp["commune"]:
            del inp["commune"]

        try:
            if street.strip():
                coords = _geocode(street.strip(), house_number.strip(), postal_code)
                if coords:
                    inp["latitude"]  = coords[0]
                    inp["longitude"] = coords[1]
                    st.info(f"📍 Geocoded: lat={coords[0]:.5f}  lon={coords[1]:.5f}")
                else:
                    st.warning("Street not found via geocoding — using commune centroid instead.")

            price    = predict(inp)
            peb_pct  = PEB_SCORES.get(peb,  0.0)
            avis_pct = AVIS_SCORES.get(avis, 0.0)
            base     = price / ((1 + peb_pct) * (1 + avis_pct))
            peb_eur  = base * peb_pct
            avis_eur = price - base * (1 + peb_pct)

            st.divider()
            st.subheader("Prediction Result")

            res1, res2, res3, res4 = st.columns(4)
            res1.metric("Base price (model)", f"€{base:,.0f}")
            res2.metric(f"PEB {peb} adjustment ({peb_pct*100:+.2f}%)",
                        f"€{peb_eur:+,.0f}",
                        delta_color="normal" if peb_eur >= 0 else "inverse")
            res3.metric(f"Avis {avis} adjustment ({avis_pct*100:+.2f}%)",
                        f"€{avis_eur:+,.0f}",
                        delta_color="normal" if avis_eur >= 0 else "inverse")
            res4.metric("PREDICTED PRICE", f"€{price:,.0f}")

            st.progress(
                min(price / 1_500_000, 1.0),
                text=f"€{price:,.0f} / €1,500,000 reference ceiling"
            )

            with st.expander("PEB × Avis combination table"):
                import pandas as pd
                rows = []
                for p in ["A", "B", "C", "D", "E", "F", "G"]:
                    row = {"PEB \\ Avis": p}
                    for a in ["A", "B", "C", "D", "E", "F", "G"]:
                        row[a] = f"€{base * (1 + PEB_SCORES[p]) * (1 + AVIS_SCORES[a]):,.0f}"
                    rows.append(row)
                df_table = pd.DataFrame(rows).set_index("PEB \\ Avis")
                st.dataframe(df_table, use_container_width=True)

        except Exception as e:
            st.error(f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RENTAL PRICE PREDICTION
# ═══════════════════════════════════════════════════════════════════════════════

with tab_rent:

    # Rental model info bar
    meta_rent = get_rental_metadata()
    if meta_rent:
        col_r1, col_r2, col_r3, col_r4 = st.columns(4)
        col_r1.metric("Model", meta_rent.get("model_name", "—"))
        col_r2.metric("R²", f"{meta_rent.get('r2', 0):.4f}")
        col_r3.metric("MAE", f"€{meta_rent.get('mae', 0):,.0f}/month")
        rent_range = meta_rent.get("rent_range_eur", {})
        col_r4.metric("Median rent", f"€{rent_range.get('median', 0):,}/month")

    st.divider()

    with st.form("rent_form"):

        # ── Property basics ───────────────────────────────────────────────────
        st.subheader("Property Details")

        r1, r2, r3, r4 = st.columns(4)
        r_living_area       = r1.number_input("Living area (m²)", min_value=15, max_value=1000, value=80, step=5, key="r_living")
        r_bedroom_count     = r2.number_input("Bedrooms", min_value=0, max_value=10, value=2, key="r_bed")
        r_number_of_facades = r3.number_input("Facades", min_value=1, max_value=4, value=1, key="r_fac")
        r_floor_number      = r4.number_input("Floor number", min_value=0, max_value=50, value=0, key="r_floor")

        # ── Location ──────────────────────────────────────────────────────────
        st.subheader("Location")

        rc1, rc2, rc3 = st.columns(3)
        r_commune     = rc1.text_input("Commune / Municipality", placeholder="e.g. Bruxelles, Gent, Liège", key="r_commune")
        r_postal_code = rc2.number_input("Postal code", min_value=1000, max_value=9999, value=1000, key="r_postal")
        r_region      = rc3.selectbox("Region", ["Flanders", "Wallonia", "Brussels"], key="r_region")

        rcs1, rcs2 = st.columns([3, 1])
        r_street       = rcs1.text_input("Street", placeholder="e.g. Avenue Louise  (optional)", key="r_street")
        r_house_number = rcs2.text_input("Number", placeholder="e.g. 12", key="r_number")

        # ── Building characteristics ───────────────────────────────────────────
        st.subheader("Building Characteristics")

        rc4, rc5, rc6, rc7 = st.columns(4)
        r_type_of_property  = rc4.selectbox("Property type", ["Apartment", "House", "Villa", "Studio"], key="r_type")
        r_state_of_building = rc5.selectbox(
            "Building condition",
            ["Good", "New", "Fair", "Poor", "Needs Renovation"],
            key="r_state",
        )
        r_heating_type = rc6.selectbox(
            "Heating",
            ["Gas", "Electric", "Heat pump", "Fuel Oil", "Pellet", "Wood"],
            key="r_heat",
        )
        r_construction_year = rc7.number_input("Construction year", min_value=1800, max_value=2025, value=1990, key="r_year")

        # ── Amenities ──────────────────────────────────────────────────────────
        st.subheader("Amenities")

        ra, rb, rc = st.columns(3)

        with ra:
            st.markdown("**Outdoor**")
            r_garden  = st.checkbox("Garden", key="r_garden")
            r_terrace = st.checkbox("Terrace", key="r_terrace")

        with rb:
            st.markdown("**Indoor**")
            r_furnished = st.checkbox("Furnished", key="r_furnished")
            r_garage    = st.checkbox("Garage", key="r_garage")
            r_lift      = st.checkbox("Lift / Elevator", key="r_lift")
            r_kitchen   = st.checkbox("Equipped kitchen", key="r_kitchen")

        with rc:
            st.markdown("**Charges**")
            r_monthly_charges = st.number_input(
                "Monthly charges (EUR)", min_value=0, max_value=2000, value=0, step=10, key="r_charges"
            )

        # ── PEB & Avis ────────────────────────────────────────────────────────
        st.subheader("Energy & Quality Rating")

        peb_options = ["A", "B", "C", "D", "E", "F", "G"]
        peb_labels  = {
            "A": "A (+4.5%)", "B": "B (+3.5%)", "C": "C (+1.75%)", "D": "D (0%)",
            "E": "E (-1.75%)", "F": "F (-3.5%)", "G": "G (-4.5%)",
        }
        avis_labels = {
            "A": "A (+7.5%)", "B": "B (+5.0%)", "C": "C (+2.5%)", "D": "D (0%)",
            "E": "E (-2.5%)", "F": "F (-5.0%)", "G": "G (-7.5%)",
        }

        rp1, rp2 = st.columns(2)
        r_peb  = rp1.select_slider("PEB (Energy Performance)", options=peb_options,
                                    value="D", format_func=lambda x: peb_labels[x], key="r_peb")
        r_avis = rp2.select_slider("Avis (Quality Rating)", options=peb_options,
                                    value="D", format_func=lambda x: avis_labels[x], key="r_avis")

        rent_submitted = st.form_submit_button(
            "🔍 Predict Monthly Rent", use_container_width=True, type="primary"
        )

    # ── Rental Result ─────────────────────────────────────────────────────────
    if rent_submitted:
        heating_map_input = {
            "Gas": "GAS", "Electric": "ELECTRIC", "Heat pump": "HEAT_PUMP",
            "Fuel Oil": "FUEL_OIL", "Pellet": "PELLET", "Wood": "WOOD",
        }

        r_inp = dict(
            living_area       = r_living_area,
            bedroom_count     = r_bedroom_count,
            room_count        = r_bedroom_count + 2,
            number_of_facades = r_number_of_facades,
            floor_number      = r_floor_number,
            furnished         = int(r_furnished),
            garden            = int(r_garden),
            terrace           = int(r_terrace),
            garage            = int(r_garage),
            lift              = int(r_lift),
            kitchen           = int(r_kitchen),
            monthly_charges   = r_monthly_charges,
            construction_year = r_construction_year,
            postal_code       = r_postal_code,
            region            = r_region,
            type_of_property  = r_type_of_property.upper(),
            state_of_building = r_state_of_building.upper().replace(" ", "_"),
            heating_type      = heating_map_input.get(r_heating_type, "GAS"),
            commune           = r_commune.strip() if r_commune.strip() else None,
        )
        if not r_inp["commune"]:
            del r_inp["commune"]

        try:
            if r_street.strip():
                coords = _geocode(r_street.strip(), r_house_number.strip(), r_postal_code)
                if coords:
                    r_inp["latitude"]  = coords[0]
                    r_inp["longitude"] = coords[1]
                    st.info(f"📍 Geocoded: lat={coords[0]:.5f}  lon={coords[1]:.5f}")
                else:
                    st.warning("Street not found via geocoding — using commune centroid instead.")

            rent_base = predict_rent(r_inp)
            peb_pct   = PEB_SCORES.get(r_peb,  0.0)
            avis_pct  = AVIS_SCORES.get(r_avis, 0.0)
            rent      = rent_base * (1 + peb_pct) * (1 + avis_pct)
            peb_eur   = rent_base * peb_pct
            avis_eur  = rent_base * (1 + peb_pct) * avis_pct

            st.divider()
            st.subheader("Rental Estimation Result")

            rres1, rres2, rres3, rres4 = st.columns(4)
            rres1.metric("Base rent (model)", f"€{rent_base:,.0f}/month")
            rres2.metric(f"PEB {r_peb} ({peb_pct*100:+.2f}%)",
                         f"€{peb_eur:+,.0f}",
                         delta_color="normal" if peb_eur >= 0 else "inverse")
            rres3.metric(f"Avis {r_avis} ({avis_pct*100:+.2f}%)",
                         f"€{avis_eur:+,.0f}",
                         delta_color="normal" if avis_eur >= 0 else "inverse")
            rres4.metric("ESTIMATED RENT", f"€{rent:,.0f}/month")

            st.progress(
                min(rent / 5000, 1.0),
                text=f"€{rent:,.0f}/month / €5,000 reference ceiling"
            )

            with st.expander("PEB × Avis combination table"):
                import pandas as pd
                rows = []
                for p in ["A", "B", "C", "D", "E", "F", "G"]:
                    row = {"PEB \\ Avis": p}
                    for a in ["A", "B", "C", "D", "E", "F", "G"]:
                        row[a] = f"€{rent_base * (1 + PEB_SCORES[p]) * (1 + AVIS_SCORES[a]):,.0f}"
                    rows.append(row)
                df_table = pd.DataFrame(rows).set_index("PEB \\ Avis")
                st.dataframe(df_table, use_container_width=True)

        except Exception as e:
            st.error(f"Error: {e}")
