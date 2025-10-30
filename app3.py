import os
import json
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -------------------------------
# CONFIG
# -------------------------------
API_URL = "https://api.mae.com.ar/MarketData/v1/mercado/cotizaciones/forex"

# API key: primero busca en secrets de Streamlit, si no en variable de entorno
API_KEY = st.secrets.get("API_KEY", os.getenv("MAE_API_KEY"))
HEADERS = {"x-api-key": API_KEY} if API_KEY else {}

# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=300)
def traer_precio_api():
    """Trae el último precio del dólar mayorista desde la API del MAE.
       Detecta bloqueos de Incapsula y evita romper el app."""
    if not API_KEY:
        st.warning("Falta API_KEY (secrets['API_KEY'] o MAE_API_KEY).")
        return None

    # Headers más 'humanos' para evitar heurísticas de bot
    headers = {
        "x-api-key": API_KEY,
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.mae.com.ar",
        "Referer": "https://www.mae.com.ar/",
        "Connection": "keep-alive",
    }

    try:
        resp = requests.get(API_URL, headers=headers, timeout=10, allow_redirects=False)

        # Si no es 200, lo mostramos y salimos
        if resp.status_code != 200:
            st.warning(f"API devolvió status {resp.status_code}")
            st.text_area("Respuesta API", resp.text[:1000], height=150)
            return None

        # Si el content-type no es JSON o contiene HTML, probablemente es Incapsula
        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype.lower() or "<html" in resp.text.lower():
            st.warning("La respuesta no parece JSON (posible bloqueo de Incapsula).")
            st.text_area("Respuesta API", resp.text[:1000], height=150)
            return None

        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict) and "data" in data:
            cotizaciones = data["data"]
        elif isinstance(data, list):
            cotizaciones = data
        else:
            cotizaciones = []

        usd_mayorista = next(
            (item.get("precioUltimo")
             for item in cotizaciones
             if isinstance(item, dict)
             and item.get("ticker") == "UST$T"
             and item.get("plazo") == "000"),
            None
        )
        return usd_mayorista

    except Exception as e:
        st.error(f"Error al consultar API: {e}")
        return None



def cargar_historico_desde_xlsx(carpeta="."):
    """
    Carga histórico desde el primer .xlsx/.xls encontrado en 'carpeta'.
    Normaliza columnas (Fecha, Volumen, Precio) y devuelve solo ['fecha','precio'].
    Filtra a fechas con año >= 2025.
    """
    xls = [p for p in Path(carpeta).glob("*.xls*") if not p.name.startswith("~$")]
    if not xls:
        raise FileNotFoundError("No se encontró ningún archivo .xlsx en la carpeta actual.")
    if len(xls) > 1:
        st.warning(f"Se encontraron varios Excel, se usará: {xls[0].name}")

    df = pd.read_excel(xls[0], engine="openpyxl")

    # Normalizar nombres de columnas
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

    # Parseo robusto de fecha (prioriza día/mes/año, tolera mezclas)
    df["fecha"] = pd.to_datetime(df["fecha"], format="mixed", dayfirst=True, errors="coerce")
    df = df.dropna(subset=["fecha"])

    # Filtrar a año >= 2025
    df = df[df["fecha"].dt.year >= 2025]

    # Quedarse solo con lo necesario
    df = df[["fecha", "precio"]].sort_values("fecha").reset_index(drop=True)
    return df


def cargar_bandas_desde_csv(path="bandas.csv"):
    """Carga bandas desde CSV y asegura columnas fecha, piso, techo, promedio."""
    bandas = pd.read_csv(path)
    bandas.columns = [c.strip().lower() for c in bandas.columns]

    requeridas = {"fecha", "piso", "techo", "promedio"}
    if not requeridas.issubset(set(bandas.columns)):
        faltan = requeridas - set(bandas.columns)
        raise ValueError(f"Columnas faltantes en bandas.csv: {', '.join(sorted(faltan))}")

    bandas["fecha"] = pd.to_datetime(bandas["fecha"], dayfirst=True, errors="coerce")
    bandas = bandas.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)
    return bandas


# -------------------------------
# APP STREAMLIT
# -------------------------------
st.set_page_config(page_title="Bandas Cambiarias", layout="wide")
st.title("Dólar Mayorista vs Bandas Cambiarias")

# Cargar bandas
try:
    bandas = cargar_bandas_desde_csv("bandas.csv")
except Exception as e:
    st.error(f"No se pudieron cargar las bandas: {e}")
    st.stop()

# Traer valor actual desde API (cacheado 5 min)
usd_mayorista = traer_precio_api()



# Cargar histórico desde el único Excel y, si hay API, anexar spot en memoria
try:
    historico = cargar_historico_desde_xlsx(".")
except Exception as e:
    st.error(f"No se pudo cargar el histórico desde Excel: {e}")
    historico = pd.DataFrame(columns=["fecha", "precio"])

ahora = datetime.now().replace(second=0, microsecond=0)

if usd_mayorista is not None:
    fila_actual = pd.DataFrame([{"fecha": ahora, "precio": usd_mayorista}])
    historico = (
        pd.concat([historico, fila_actual], ignore_index=True)
        .drop_duplicates(subset=["fecha"], keep="last")
        .sort_values("fecha")
        .reset_index(drop=True)
    )
else:
    st.warning("No se pudo obtener el valor del dólar mayorista en tiempo real; se grafica solo el histórico del Excel.")

# -------------------------------
# GRÁFICO
# -------------------------------
fig = go.Figure()

# Histórico
if not historico.empty:
    fig.add_trace(go.Scatter(
        x=historico["fecha"],
        y=historico["precio"],
        mode="lines",
        name="USD Mayorista",
        line=dict(color="black")
    ))

# Bandas
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["piso"],
    mode="lines", name="Piso Banda",
    line=dict(color="red", dash="dash")
))
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["techo"],
    mode="lines", name="Techo Banda",
    line=dict(color="green", dash="dash")
))
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["promedio"],
    mode="lines", name="Promedio Banda",
    line=dict(color="blue", dash="dot")
))

# Punto spot actual
if usd_mayorista is not None:
    fig.add_trace(go.Scatter(
        x=[ahora], y=[usd_mayorista],
        mode="markers+text",
        name="USD Actual",
        marker=dict(size=8),
        text=[f"${usd_mayorista}"],
        textposition="top right"
    ))

fig.update_layout(
    title=f"Dólar Mayorista vs Bandas Cambiarias"
          f"<br><sup>Última actualización: {ahora.strftime('%Y-%m-%d %H:%M:%S')}</sup>",
    xaxis_title="Fecha",
    yaxis_title="Precio",
    template="plotly_white",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="black"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
)

st.plotly_chart(fig, use_container_width=True)
