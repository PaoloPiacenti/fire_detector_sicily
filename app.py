# streamlit_app.py  –  FIRMS Sicilia “Fogos-style”
import os
from datetime import datetime, timezone
from io import StringIO

import numpy as np
import pandas as pd
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

# ─────────────────────────── PARAMETRI BASE ───────────────────────────
BBOX   = (11.8, 35.4, 15.7, 39.0)        # west, south, east, north (Sicilia)
SOURCE = "VIIRS_NOAA20_NRT"              # satellite & product
MAP_KEY = MAP_KEY = st.secrets.get("MAP_KEY", os.getenv("FIRMS_MAP_KEY"))
CACHE_HOURS = 0.5                        # refresh ogni 30 min
DAYS = 3
# ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Incendi FIRMS – Sicilia", layout="wide")
st.title("🔥 Incendi FIRMS in Sicilia")

# ───── slider giorni & spiegazione dataset ───────────────────────────

with st.expander("ℹ️ Che cosa stai vedendo?"):
    st.markdown("""
**Fonte dati:** NASA **FIRMS** (VIIRS NOAA-20, Near-Real-Time)
Ogni pin indica un *hotspot* (fuoco o forte sorgente di calore).

* **Colore pin** → freschezza (≤ 6 h rosso scuro, ≤ 12 h rosso, ≤ 36 h arancio, > 36 h nero)
* **Icona pin** → 🔥 dato ≤12 h, ☁️ ≤36 h, 🌳 più vecchio
* Clicca un pin per i dettagli (appaiono a destra).
""")

# ───── sessione & cache ───────────────────────────────────────────────
st.session_state.setdefault("api_calls", 0)

@st.cache_data(ttl=CACHE_HOURS * 3600, show_spinner="⏳ Scarico dati FIRMS…")
def get_firms_df(bbox, days, api_key, source):
    w, s, e, n = bbox
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{source}/{w},{s},{e},{n}/{days}"
    r = requests.get(url, timeout=60); r.raise_for_status()
    st.session_state.api_calls += 1
    df = pd.read_csv(StringIO(r.text))
    if df.empty or {"acq_date", "acq_time"} - set(df.columns):
        return pd.DataFrame(), url
    df["acq_datetime_utc"] = pd.to_datetime(
        df["acq_date"] + " " + df["acq_time"].astype(str).str.zfill(4),
        format="%Y-%m-%d %H%M",
    ).dt.tz_localize("UTC")
    df["acq_datetime_local"] = df["acq_datetime_utc"].dt.tz_convert("Europe/Rome")
    return df, url

# if st.button("🔄 Aggiorna ora"):
#     st.cache_data.clear()

df, url_used = get_firms_df(BBOX, DAYS, MAP_KEY, SOURCE)
# st.caption(f"URL usato: `{url_used}`")

if df.empty:
    st.warning("Nessun hotspot o MAP_KEY errata – amplia l'intervallo o verifica la chiave.")
    st.stop()

# st.sidebar.write(f"Chiamate API effettive: **{st.session_state.api_calls}**")

# ───── funzioni colore & raggio ───────────────────────────────────────
def color_by_age(ts):
    hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if hrs <= 6:   return "darkred"
    if hrs <= 12:  return "red"
    if hrs <= 36:  return "orange"
    return "black"

def icon_by_age(ts):
    """Return a Font Awesome icon name based on the age in hours."""
    hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if hrs <= 12:
        return "fire"         # dato più recente di 12h
    if hrs <= 36:
        return "smog"        # tra 12h e 36h → fumo
    return "fire-extinguisher"             # oltre 36h → estintore

def icon_size_by_scan_track(scan, track):
    """Return (width, height) for the marker based on scan/track."""
    avg = (scan + track) / 2
    if avg >= 0.006:
        return (35, 35)      # grande
    if avg >= 0.003:
        return (25, 25)      # medio
    return (15, 15)          # piccolo

def radius_by_intensity(row):
    b_norm  = np.clip((row["bright_ti4"] - 300) / 100, 0, 1)       # 300-400 K
    frp_norm= np.clip(row["frp"] / 50, 0, 1)                       # 0-50 MW
    fp_norm = np.clip(((row["scan"] + row["track"]) / 2) / 0.005, 0, 1)
    score   = (b_norm + frp_norm + fp_norm) / 3
    return 6 + score * 14   # raggio 6-20 px

# ───── MAPPA Folium ---------------------------------------------------
center = [(BBOX[1]+BBOX[3])/2, (BBOX[0]+BBOX[2])/2]
m = folium.Map(location=center, zoom_start=7, tiles="OpenStreetMap")

for _, r in df.iterrows():
    age_min = int((datetime.now(timezone.utc) - r['acq_datetime_utc']).total_seconds() / 60)

    icon = folium.Icon(
        icon=icon_by_age(r['acq_datetime_utc']),
        prefix='fa',
        color=color_by_age(r['acq_datetime_utc']),
        icon_size=icon_size_by_scan_track(r['scan'], r['track'])
    )

    folium.Marker(
        [r["latitude"], r["longitude"]],
        icon=icon,
        tooltip=f"{age_min} min • FRP {r['frp']:.1f}",
        popup=(
            f"<table style='font-size:13px'>"
            f"<tr><td><b>FRP</b></td><td>{r['frp']:.1f} MW</td></tr>"
            f"<tr><td><b>Brightness</b></td><td>{r['bright_ti4']} K</td></tr>"
            f"<tr><td><b>Scan/Track</b></td><td>{r['scan']:.4f} / {r['track']:.4f}°</td></tr>"
            f"<tr><td><b>Satellite</b></td><td>{r['satellite']}</td></tr>"
            f"<tr><td><b>Confidenza</b></td><td>{r['confidence']}</td></tr>"
            f"<tr><td><b>UTC</b></td><td>{r['acq_datetime_utc']:%Y-%m-%d %H:%M}</td></tr>"
            f"<tr><td><b>Locale</b></td><td>{r['acq_datetime_local']:%d/%m %H:%M}</td></tr>"
            f"</table>"
        ),
    ).add_to(m)

# ───── legenda colori -------------------------------------------------
legend = """
<div style='position: fixed; bottom:25px; right:25px; z-index:9999;
            background:rgba(255,255,255,0.9); padding:8px 10px;
            border:1px solid #ccc; border-radius:4px; font-size:13px'>
<b>Età hotspot</b><br>
<span style="display:inline-block;width:12px;height:12px;background:#8B0000"></span>&nbsp;≤ 6 h<br>
<span style="display:inline-block;width:12px;height:12px;background:#FF0000"></span>&nbsp;≤ 12 h<br>
<span style="display:inline-block;width:12px;height:12px;background:#FFA500"></span>&nbsp;≤ 36 h<br>
<span style="display:inline-block;width:12px;height:12px;background:#000000"></span>&nbsp;&gt; 36 h<br>
<hr style='margin:4px 0;'>
<b>Dimensione pin</b><br>
<span style="font-size:18px">📍</span>&nbsp;grande ≥0.006°<br>
<span style="font-size:14px">📍</span>&nbsp;medio ≥0.003°<br>
<span style="font-size:10px">📍</span>&nbsp;piccolo &lt;0.003°
</div>
"""
m.get_root().html.add_child(folium.Element(legend))

# ───── controllo click & tabella dettagli ----------------------------
map_state = st_folium(m, use_container_width=True, key="map")
clicked = map_state.get("last_object_clicked")
if clicked:
    lat_c, lon_c = round(clicked["lat"], 5), round(clicked["lng"], 5)
    sel = df[(df["latitude"].round(5)==lat_c) & (df["longitude"].round(5)==lon_c)]
    if not sel.empty:
        r = sel.iloc[0]
        details = pd.DataFrame({
            "Campo": ["FRP (MW)", "Brightness (K)", "Scan °", "Track °",
                      "Satellite", "Confidenza", "UTC", "Locale"],
            "Valore": [f"{r['frp']:.1f}", r["bright_ti4"],
                       f"{r['scan']:.4f}", f"{r['track']:.4f}",
                       r["satellite"], r["confidence"],
                       r["acq_datetime_utc"].strftime("%Y-%m-%d %H:%M"),
                       r["acq_datetime_local"].strftime("%d/%m %H:%M")]
        })
        st.sidebar.subheader("Dettagli hotspot selezionato")
        st.sidebar.table(details)
