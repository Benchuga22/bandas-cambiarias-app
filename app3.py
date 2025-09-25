import os
import json
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- Archivos ---
archivo_historico = "historico_mayorista.csv"
archivo_bandas = "bandas.csv"

# --- Leer bandas ---
bandas = pd.read_csv(archivo_bandas, decimal=",")  # soporta decimales con coma
bandas["fecha"] = pd.to_datetime(bandas["fecha"], errors="coerce")
bandas["piso"] = pd.to_numeric(bandas["piso"], errors="coerce")
bandas["techo"] = pd.to_numeric(bandas["techo"], errors="coerce")
bandas["promedio"] = pd.to_numeric(bandas["promedio"], errors="coerce")

# --- API MAE ---
url = "https://api.mae.com.ar/MarketData/v1/mercado/cotizaciones/forex"
headers = {"x-api-key": "REMOVIDO"}  # 👈 reemplazar con tu API Key real

usd_mayorista = None
try:
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()

    if isinstance(data, str):
        data = json.loads(data)

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
except Exception as e:
    print("No se pudo traer la cotización en tiempo real:", e)

# --- Actualizar histórico ---
if usd_mayorista:
    ahora = datetime.now()
    nuevo = pd.DataFrame([{
        "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "precio": usd_mayorista
    }])

    if os.path.exists(archivo_historico):
        historico = pd.read_csv(archivo_historico)
        historico = pd.concat([historico, nuevo], ignore_index=True)
    else:
        historico = nuevo

    historico.to_csv(archivo_historico, index=False)
else:
    if os.path.exists(archivo_historico):
        historico = pd.read_csv(archivo_historico)
    else:
        historico = pd.DataFrame(columns=["fecha", "precio"])

historico["fecha"] = pd.to_datetime(historico["fecha"], errors="coerce")

# --- Gráfico ---
fig = go.Figure()

# Histórico
fig.add_trace(go.Scatter(
    x=historico["fecha"], y=historico["precio"],
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
if usd_mayorista:
    ahora = datetime.now()
    fig.add_trace(go.Scatter(
        x=[ahora], y=[usd_mayorista],
        mode="markers+text",
        name="USD Actual",
        marker=dict(color="orange", size=9),
        text=[f"${usd_mayorista}"],
        textposition="top right"
    ))

    fig.update_layout(
        title=f"Dólar Mayorista vs Bandas Cambiarias<br><sup>Última actualización: {ahora.strftime('%Y-%m-%d %H:%M:%S')}</sup>",
        xaxis_title="Fecha",
        yaxis_title="Precio ($ARS)",
        template="plotly_white"
    )

fig.show()
