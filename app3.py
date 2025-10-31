import os
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -------------------------------
# CONFIG
# -------------------------------
PROXY_URL = st.secrets.get("PROXY_URL", os.getenv("PROXY_URL"))
DOLARAPI_URL = "https://dolarapi.com/v1/dolares/mayorista"
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=120)
def traer_venta_dolarapi():
    """
    Llama a DolarAPI y devuelve (venta, fecha_actualizacion_en_AR) o (None, None).
    """
    try:
        r = requests.get(DOLARAPI_URL, timeout=10)
        if r.status_code != 200:
            return None, None
        data = r.json()
        if isinstance(data, str):
            data = json.loads(data)
        venta = data.get("venta")
        fecha_api = data.get("fechaActualizacion")
        api_dt = None
        if isinstance(fecha_api, str):
            # viene como ISO UTC (termina en Z): la pasamos a AR
            api_dt = datetime.fromisoformat(fecha_api.replace("Z", "+00:00")).astimezone(TZ_AR)
        return (float(venta) if venta is not None else None), api_dt
    except Exception:
        return None, None


@st.cache_data(ttl=300)
def traer_precio_api_via_proxy():
    """
    Llama al proxy (FastAPI) que consulta el MAE y devuelve {precio: ...}.
    Devuelve None si falla o no está configurado.
    """
    if not PROXY_URL:
        return None
    try:
        r = requests.get(f"{PROXY_URL.rstrip('/')}/mae/latest", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, str):
            data = json.loads(data)
        return data.get("precio")
    except Exception:
        return None


def cargar_historico_desde_xlsx(carpeta="."):
    """
    Carga histórico desde el primer .xlsx/.xls en 'carpeta'.
    Espera columnas: Fecha, Precio (no todas se usan).
    Devuelve DataFrame con ['fecha','precio'] filtrado a año >= 2025.
    """
    xls = [p for p in Path(carpeta).glob("*.xls*") if not p.name.startswith("~$")]
    if not xls:
        raise FileNotFoundError("No se encontró ningún archivo .xlsx en la carpeta actual.")
    if len(xls) > 1:
        st.warning(f"Se encontraron varios Excel, se usará: {xls[0].name}")

    df = pd.read_excel(xls[0], engine="openpyxl")

    # Normalizar columnas
    df.columns = [c.strip().lower() for c in df.columns]
    ren = {}
    if "fecha" not in df.columns:
        for c in df.columns:
            if c.lower().startswith("fecha"):
                ren[c] = "fecha"
    if "precio" not in df.columns:
        for c in df.columns:
            if c.lower().startswith("precio"):
                ren[c] = "precio"
    if ren:
        df = df.rename(columns=ren)

    if "fecha" not in df.columns or "precio" not in df.columns:
        raise ValueError("El Excel debe contener columnas 'Fecha' y 'Precio'.")

    # Parseo fechas con tole
