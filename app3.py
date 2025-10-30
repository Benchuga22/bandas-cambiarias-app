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
API_KEY = st.secrets.get("API_KEY", os.getenv("MAE_API_KEY"))
HEADERS = {"x-api-key": API_KEY} if API_KEY else {}

# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=300)  # cachea 5 minutos
def traer_precio_api():
    """
    Trae el último precio del dólar mayorista desde la API del MAE.
    Si la respuesta no es JSON (p.ej. HTML de Incapsula), devuelve None.
    """
    if not API_KEY:
        return None

    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=10)

        # 1) Si no es 200, no seguimos
        if resp.status_code != 200:
            return None

        # 2) Si parece HTML (bloqueo Incapsula), no seguimos
        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype.lower() or "<html" in resp.text.lower():
            return None

        # 3) Parseo JSON
        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)

        # Normalizar estructura
        if isinstance(data, dict) and "data" in data:
            cotizaciones = data["data"]
        elif isinstance(data, list):
            cotizaciones = data
        else:
            cotizaciones = []

        # Buscar ticker mayorista
        usd_mayorista = next(
            (item.get("precioUltimo")
             for item in cotizaciones
             if isinstance(item, dict)
             and item.get("ticker") == "UST$T"
             and item.get("plazo") == "000"),
            None
        )
        return usd_mayorista

    except Exception:
        return None


def cargar_historico_desde_xlsx(carpeta="."):
    """
    Carga histórico desde el primer .xlsx/.xls en 'carpeta'.
    Espera columnas: Fecha, Volumen, Precio (no todas se usan).
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
    # Renombrar si vienen variantes
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

    # Parseo fechas d/m/Y con tolerancia a mezclas
    df["fecha"] = pd.to_datetime(df["fecha"], format="mixed", dayfirst=True, errors="coerce")
    df = df.dropna(subset=["fecha"])

    # Filtro a 2025+
    df = df[df["fecha"].dt.year >= 2025]

    # Sólo lo necesario
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

# Bandas
try:
    bandas = cargar_bandas_desde_csv("bandas.csv")
except Exception as e:
    st.error(f"No se pudieron cargar las bandas: {e}")
    st.stop()

# Histórico desde Excel
try:
    historico = cargar_historico_desde_xlsx(".")
except Exception as e:
    st.error(f"No se pudo cargar el histórico desde Excel: {e}")
    historico = pd.DataFrame(columns=["fecha", "precio"])

# Intento de spot por API
usd_mayorista = traer_precio_api()
ahora = datetime.now().replace(second=0, microsecond=0)

# Fallback (B): si la API falla, usar último valor del histórico
if usd_mayorista is None:
    if not historico.empty:
        ultimo_hist = float(historico.sort_values("fecha").iloc[-1]["precio"])
        st.info("No se pudo leer el spot en tiempo real; se usa el último valor del histórico.")
        # Anexamos un punto 'actual' con el último histórico (en memoria)
        fila_aprox = pd.DataFrame([{"fecha": ahora, "precio": ultimo_hist}])
        historico = (
            pd.concat([historico, fila_aprox], ignore_index=True)
            .drop_duplicates(subset=["fecha"], keep="last")
            .sort_values("fecha")
            .reset_index(drop=True)
        )
    else:
        st.warning("No hay histórico disponible y la API falló. No se puede mostrar el spot actual.")

# Si la API funcionó, anexar punto real en memoria (sin tocar el Excel)
else:
    fila_actual = pd.DataFrame([{"fecha": ahora, "precio": usd_mayorista}])
    historico = (
        pd.concat([historico, fila_actual], ignore_index=True)
        .drop_duplicates(subset=["fecha"], keep="last")
        .sort_values("fecha")
        .reset_index(drop=True)
    )

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

# Punto “actual” (sea real por API o aproximación del histórico)
if not historico.empty:
    punto_actual = historico.iloc[-1]
    fig.add_trace(go.Scatter(
        x=[punto_actual["fecha"]], y=[punto_actual["precio"]],
        mode="markers+text",
        name="USD Actual",
        marker=dict(size=8),
        text=[f"${punto_actual['precio']:.2f}"],
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
