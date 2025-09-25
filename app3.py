import os
import json
import requests
import pandas as pd
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go

# -------------------------------
# CONFIG
# -------------------------------
ARCHIVO_HISTORICO = "historico_mayorista.csv"
API_URL = "https://api.mae.com.ar/MarketData/v1/mercado/cotizaciones/forex"
API_KEY = "REMOVIDO"   # 👈 reemplazá con tu API Key
HEADERS = {"x-api-key": API_KEY}


# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=300)  # cachea el resultado por 5 minutos
def traer_precio_api():
    """Trae el último precio del dólar mayorista desde la API del MAE"""
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=10)
        data = response.json()

        # Caso 1: si viene como string con JSON adentro
        if isinstance(data, str):
            data = json.loads(data)

        # Caso 2: si viene como {"data": [...]} o ya como lista
        if isinstance(data, dict) and "data" in data:
            cotizaciones = data["data"]
        elif isinstance(data, list):
            cotizaciones = data
        else:
            cotizaciones = []

        usd_mayorista = next(
            (item["precioUltimo"] for item in cotizaciones
             if isinstance(item, dict)
             and item.get("ticker") == "UST$T"
             and item.get("plazo") == "000"),
            None
        )
        return usd_mayorista
    except Exception as e:
        st.error(f"Error al consultar API: {e}")
        return None


def actualizar_historico(usd_mayorista):
    """Guarda el valor spot en el histórico asegurando fechas limpias"""
    ahora = datetime.now()

    # Nueva fila con valor de la API
    nuevo = pd.DataFrame([{
        "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),  # formato ISO siempre
        "precio": usd_mayorista
    }])

    # Cargar histórico existente o iniciar
    if os.path.exists(ARCHIVO_HISTORICO):
        historico = pd.read_csv(ARCHIVO_HISTORICO)
        historico = pd.concat([historico, nuevo], ignore_index=True)
    else:
        historico = nuevo

    # Convertir fechas a datetime y limpiar duplicados
    historico["fecha"] = pd.to_datetime(
        historico["fecha"], errors="coerce", format="%Y-%m-%d %H:%M:%S"
    )
    historico = historico.sort_values("fecha").drop_duplicates(subset=["fecha"], keep="last")

    # Guardar limpio
    historico.to_csv(ARCHIVO_HISTORICO, index=False)

    return historico


# -------------------------------
# APP STREAMLIT
# -------------------------------
st.set_page_config(page_title="Bandas Cambiarias", layout="wide")

st.title("📊 Dólar Mayorista vs Bandas Cambiarias")

# --- Bandas desde CSV ---
bandas = pd.read_csv("bandas.csv")
bandas["fecha"] = pd.to_datetime(bandas["fecha"], dayfirst=True, errors="coerce")

# --- Traer valor actual desde API (cacheado 5 min) ---
usd_mayorista = traer_precio_api()

# --- Actualizar histórico ---
if usd_mayorista:
    historico = actualizar_historico(usd_mayorista)
    ahora = datetime.now()
else:
    st.warning("No se pudo obtener el valor del dólar mayorista en tiempo real.")
    if os.path.exists(ARCHIVO_HISTORICO):
        historico = pd.read_csv(ARCHIVO_HISTORICO)
        historico["fecha"] = pd.to_datetime(historico["fecha"], errors="coerce")
    else:
        historico = pd.DataFrame(columns=["fecha", "precio"])
    ahora = datetime.now()

# --- Plotly ---
fig = go.Figure()

# Histórico
fig.add_trace(go.Scatter(
    x=historico["fecha"], y=historico["precio"],
    mode="lines",
    name="USD Mayorista",
    line=dict(color="black")
))

# Bandas
fig.add_trace(go.Scatter(x=bandas["fecha"], y=bandas["piso"], mode="lines", name="Piso Banda",
                         line=dict(color="red", dash="dash")))
fig.add_trace(go.Scatter(x=bandas["fecha"], y=bandas["techo"], mode="lines", name="Techo Banda",
                         line=dict(color="green", dash="dash")))
fig.add_trace(go.Scatter(x=bandas["fecha"], y=bandas["promedio"], mode="lines", name="Promedio Banda",
                         line=dict(color="blue", dash="dot")))

# Punto spot actual
if usd_mayorista:
    fig.add_trace(go.Scatter(
        x=[ahora], y=[usd_mayorista],
        mode="markers+text",
        name="USD Actual",
        marker=dict(color="orange", size=8),
        text=[f"${usd_mayorista}"],
        textposition="top right"
    ))

# Layout general
fig.update_layout(
    title=f"Dólar Mayorista vs Bandas Cambiarias<br><sup>Última actualización: {ahora.strftime('%Y-%m-%d %H:%M:%S')}</sup>",
    xaxis_title="Fecha",
    yaxis_title="Precio",
    template="plotly_white",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="black")
)

st.plotly_chart(fig, use_container_width=True)


