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
# URL de tu proxy FastAPI (poner en Streamlit Secrets o variable de entorno)
PROXY_URL = st.secrets.get("PROXY_URL", os.getenv("PROXY_URL"))

# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=300)
def traer_precio_api_via_proxy():
    """
    Llama al proxy (FastAPI) que consulta el MAE y devuelve {precio: ...}.
    Devuelve None si falla.
    """
    if not PROXY_URL:
        return None
    try:
        r = requests.get(f"{PROXY_URL.rstrip('/')}/mae/latest", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        # Por si el proxy alguna vez respondiera string JSON
        if isinstance(data, str):
            data = json.loads(data)
        return data.get("precio")
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

    # requiere openpyxl en requirements.txt
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

# Cargar bandas
try:
    bandas = cargar_bandas_desde_csv("bandas.csv")
except Exception as e:
    st.error(f"No se pudieron cargar las bandas: {e}")
    st.stop()

# Cargar histórico desde el único Excel
try:
    historico = cargar_historico_desde_xlsx(".")
except Exception as e:
    st.error(f"No se pudo cargar el histórico desde Excel: {e}")
    historico = pd.DataFrame(columns=["fecha", "precio"])

# Traer spot via proxy
usd_mayorista = traer_precio_api_via_proxy()
ahora = datetime.now().replace(second=0, microsecond=0)

# Fallback: si el proxy falla, usar último valor del histórico como punto “actual”
if usd_mayorista is None:
    if not historico.empty:
        ultimo_hist = float(historico.sort_values("fecha").iloc[-1]["precio"])
        st.info("No se pudo leer el spot en tiempo real (proxy/API). Se usa el último valor del histórico.")
        fila_aprox = pd.DataFrame([{"fecha": ahora, "precio": ultimo_hist}])
        historico = (
            pd.concat([historico, fila_aprox], ignore_index=True)
            .drop_duplicates(subset=["fecha"], keep="last")
            .sort_values("fecha")
            .reset_index(drop=True)
        )
else:
    # Si el proxy devuelve precio, anexamos el punto real en memoria
    fila_actual = pd.DataFrame([{"fecha": ahora, "precio": float(usd_mayorista)}])
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

# Punto “actual” (real por proxy o aproximación)
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
