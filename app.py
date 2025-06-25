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

from streamlit.components.v1 import html


# ─────────────────────────── PARAMETRI BASE ───────────────────────────
BBOX   = (11.8, 35.4, 15.7, 39.0)        # west, south, east, north (Sicilia)
SOURCE = "VIIRS_NOAA20_NRT"              # satellite & product
MAP_KEY = MAP_KEY = st.secrets.get("MAP_KEY", os.getenv("FIRMS_MAP_KEY"))
CACHE_HOURS = 0.5                        # refresh ogni 30 min
DAYS = 1                          # dati degli ultimi 24 ore
# ──────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sicilia in Fiamme - NASA FIRMS VIIRS NOAA-20, Near-Real-Time",
    page_icon="🔥",
    layout="centered",
)

# Nasconde logo Streamlit e pulsanti GitHub nell'interfaccia
st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header [data-testid="stToolbar"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🔥 Sicilia in Fiamme")
st.subheader("Mappa interattiva degli hotspot di calore rilevati nelle ultime 24 dai satelliti NASA FIRMS (VIIRS-SNPP)")

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

df, url_used = get_firms_df(BBOX, DAYS, MAP_KEY, SOURCE)

if df.empty:
    st.warning("Nessun hotspot o MAP_KEY errata – amplia l'intervallo o verifica la chiave.")
    st.stop()


# ───── funzioni colore & raggio ───────────────────────────────────────
def color_by_age(ts):
    hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if hrs <= 6:
        return "red"
    elif hrs <= 12:
        return "orange"
    elif hrs <= 36:
        return "yellow"
    else:
        return "gray"

def icon_by_stage(frp, brightness):
    """Return Font Awesome icon name based on FRP and brightness."""
    if frp >= 50 or brightness >= 367:
        return "fire"  # fiamma viva
    elif frp >= 10:
        return "triangle-exclamation"  # materiale rovente
    elif frp > 0 or brightness >= 330:
        return "temperature-high"  # calore residuo
    else:
        return None  # nessuna icona

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

# ───── MAPPA Folium migliorata ----------------------------------------

import branca.colormap as cm

center = [(BBOX[1]+BBOX[3])/2, (BBOX[0]+BBOX[2])/2]
m = folium.Map(location=center, zoom_start=7, tiles="CartoDB Positron")

# Colormap continua per FRP
colormap = cm.linear.YlOrRd_09.scale(0, 100)
colormap.caption = "FRP – Fire Radiative Power (MW)"

# Funzione colore bordo = età
def stroke_by_age(ts):
    hrs = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    return "red" if hrs <= 6 else "orange" if hrs <= 12 else "gray"

# Funzione raggio
def radius_by_intensity(row):
    base = np.clip(row["frp"] / 10, 0.5, 10)
    return base + 5  # range: 5–15 px

for _, r in df.iterrows():
    folium.CircleMarker(
        location=[r["latitude"], r["longitude"]],
        radius=radius_by_intensity(r),
        color=stroke_by_age(r['acq_datetime_utc']),
        fill=True,
        fill_color=colormap(r['frp']),
        fill_opacity=0.8,
        weight=1,
        tooltip=f"FRP {r['frp']:.1f} MW • {r['acq_datetime_local']:%H:%M}",
        popup=folium.Popup(f"""
        <b>🔥 Intensità:</b> {r['frp']:.1f} MW<br>
        <b>🌡 Temperatura:</b> {r['bright_ti4']} K<br>
        <b>🛰 Satellite:</b> {r['satellite']}<br>
        <b>🕓 Rilevato:</b> {r['acq_datetime_local']:%d/%m %H:%M}<br>
        <b>🎯 Confidenza:</b> {r['confidence']}
        """, max_width=250)
    ).add_to(m)

# ───── slider giorni & spiegazione dataset ───────────────────────────

with st.expander("ℹ️ Come funziona – Dati e Mappa"):
    st.markdown("""
Questa mappa mostra in **tempo quasi reale** gli hotspot di calore rilevati dai satelliti NASA nell’area della Sicilia.

I dati provengono da **FIRMS (Fire Information for Resource Management System)**, un sistema della NASA che rileva automaticamente gli incendi attivi grazie ai satelliti VIIRS (NOAA-20 e SNPP), aggiornati ogni ora.

Ogni punto sulla mappa rappresenta un'area in cui è stato rilevato **calore anomalo**. A seconda dell’intensità, l’algoritmo classifica automaticamente ogni hotspot in:

- 🔥 **Incendio attivo** – fiamme intense o fronti estesi (FRP ≥ 50 MW)
- 🔥 **Fuoco** – combustione moderata (FRP 10–50 MW)
- ⚠️ **Alta temperatura** – sorgenti calde deboli (FRP < 10 MW o bright_ti4 elevato)

📌 **Il colore** indica l’intensità (FRP), mentre **il bordo** mostra l’età dell’evento:
- **Rosso** = ultimi 6h
- **Arancio** = 6–12h
- **Grigio** = oltre 12h

Clicca su un punto per vedere i dettagli tecnici dell’osservazione (FRP, temperatura, ora locale, ecc.).

""")

    st.markdown("#### Legenda intensità (FRP)")
    html(colormap._repr_html_(), height=100)

    st.markdown(
        """
        <div style='margin-top:10px'>
        <a href="https://firms.modaps.eosdis.nasa.gov/" target="_blank"
           style="text-decoration:none;background:#004080;color:white;
                  padding:8px 14px;border-radius:4px;font-weight:bold;
                  display:inline-block">
            🔗 Scopri di più su FIRMS (NASA)
        </a>
        </div>

        <div style='margin-top:20px;font-size:13px;color:#555'>
            ♥ Creato con amore per la propria terra da <a href="https://www.linkedin.com/in/paolopiacenti/" target="_blank" style="color:#004080;font-weight:bold;">Paolo Piacenti</a>
        </div>

        <br>
        """,
        unsafe_allow_html=True,
    )

# ───── controllo click & dettagli (uguale) ----------------------------
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

# ───── controllo click & tabella dettagli ----------------------------
# map_state = st_folium(m, use_container_width=True, key="map")
# clicked = map_state.get("last_object_clicked")
# if clicked:
#     lat_c, lon_c = round(clicked["lat"], 5), round(clicked["lng"], 5)
#     sel = df[(df["latitude"].round(5)==lat_c) & (df["longitude"].round(5)==lon_c)]
#     if not sel.empty:
#         r = sel.iloc[0]
#         details = pd.DataFrame({
#             "Campo": ["FRP (MW)", "Brightness (K)", "Scan °", "Track °",
#                       "Satellite", "Confidenza", "UTC", "Locale"],
#             "Valore": [f"{r['frp']:.1f}", r["bright_ti4"],
#                        f"{r['scan']:.4f}", f"{r['track']:.4f}",
#                        r["satellite"], r["confidence"],
#                        r["acq_datetime_utc"].strftime("%Y-%m-%d %H:%M"),
#                        r["acq_datetime_local"].strftime("%d/%m %H:%M")]
#         })
#         st.sidebar.subheader("Dettagli hotspot selezionato")
#         st.sidebar.table(details)
