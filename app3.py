import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -------------------------------
# CONFIG
# -------------------------------
DOLARAPI_URL = "https://dolarapi.com/v1/dolares/mayorista"
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BandasCambiarias/1.0 (+contacto@example.com)"
}

# -------------------------------
# FUNCIONES
# -------------------------------
@st.cache_data(ttl=120)
def traer_venta_dolarapi():
    """
    Llama a DolarAPI y devuelve (venta, fecha_actualizacion_en_AR) o (None, None).
    """
    try:
        r = requests.get(DOLARAPI_URL, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None, None
        data = r.json()
        if isinstance(data, str):
            data = json.loads(data)
        venta = data.get("venta")
        fecha_api = data.get("fechaActualizacion")
        api_dt = None
        if isinstance(fecha_api, str):
            # viene ISO UTC con 'Z' -> convertir a AR para mostrar
            api_dt = datetime.fromisoformat(fecha_api.replace("Z", "+00:00")).astimezone(TZ_AR)
        return (float(venta) if venta is not None else None), api_dt
    except Exception:
        return None, None


def cargar_historico(path="data/mayorista.csv"):
    """
    Carga el histórico del mayorista (UST$T MAE) que mantiene actualizado
    el workflow .github/workflows/actualizar_datos.yml.
    Devuelve DataFrame con ['fecha','precio'] filtrado a año >= 2025.
    """
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d")
    df = df[df["fecha"].dt.year >= 2025]
    return df[["fecha", "precio"]].sort_values("fecha").reset_index(drop=True)


def cargar_bandas(path="data/bandas.csv"):
    """
    Carga las bandas oficiales del BCRA (fecha, piso, techo) que mantiene actualizadas
    el workflow .github/workflows/actualizar_datos.yml, y calcula el promedio.
    """
    bandas = pd.read_csv(path)
    bandas["fecha"] = pd.to_datetime(bandas["fecha"], format="%Y-%m-%d")
    bandas["promedio"] = (bandas["piso"] + bandas["techo"]) / 2
    return bandas.sort_values("fecha").reset_index(drop=True)


# -------------------------------
# APP STREAMLIT
# -------------------------------
st.set_page_config(page_title="Bandas Cambiarias", layout="wide")
st.title("Dólar Mayorista vs Bandas Cambiarias")

# Cargar bandas
try:
    bandas = cargar_bandas()
except Exception as e:
    st.error(f"No se pudieron cargar las bandas: {e}")
    st.stop()

# Cargar histórico del mayorista
try:
    historico = cargar_historico()
except Exception as e:
    st.error(f"No se pudo cargar el histórico del mayorista: {e}")
    historico = pd.DataFrame(columns=["fecha", "precio"])

# Valor actual desde DolarAPI (si falla, se muestra sólo el histórico)
venta_api, fecha_api_ar = traer_venta_dolarapi()

usd_mayorista = None
fuente_actual = None

# Hora actual: con tz para mostrar y naive para graficar (coordenada X)
ahora_ar = datetime.now(TZ_AR).replace(second=0, microsecond=0)
ahora_naive = ahora_ar.replace(tzinfo=None)

if venta_api is not None:
    usd_mayorista = venta_api
    fuente_actual = f"DolarAPI (actualizado: {fecha_api_ar.strftime('%Y-%m-%d %H:%M:%S %Z') if isinstance(fecha_api_ar, datetime) else 's/d'})"
else:
    fuente_actual = "Histórico (fallback)"

# -------------------------------
# GRÁFICO (sin título)
# -------------------------------
fig = go.Figure()

# === Línea del USD Mayorista (histórico + último spot para conectar) ===
df_linea = historico.copy()
if (usd_mayorista is not None) and (not historico.empty):
    df_linea = pd.concat(
        [df_linea, pd.DataFrame([{"fecha": ahora_naive, "precio": float(usd_mayorista)}])],
        ignore_index=True
    ).sort_values("fecha")

if not df_linea.empty:
    fig.add_trace(go.Scatter(
        x=df_linea["fecha"],
        y=df_linea["precio"],
        mode="lines",
        name="USD Mayorista",
        line=dict(color="black"),
        connectgaps=True
    ))

# Bandas (Piso = rojo, Techo = verde para coincidir con la leyenda de tus capturas)
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["piso"],
    mode="lines", name="Piso Banda",
    line=dict(color="green", dash="dash")
))
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["techo"],
    mode="lines", name="Techo Banda",
    line=dict(color="red", dash="dash")
))
fig.add_trace(go.Scatter(
    x=bandas["fecha"], y=bandas["promedio"],
    mode="lines", name="Promedio Banda",
    line=dict(color="blue", dash="dot")
))

# Punto “actual” (sólo si DolarAPI respondió)
if usd_mayorista is not None:
    fig.add_trace(go.Scatter(
        x=[ahora_naive], y=[float(usd_mayorista)],
        mode="markers+text",
        name="USD Actual",
        marker=dict(size=8),
        text=[f"${float(usd_mayorista):,.0f}"],
        textposition="top right"
    ))

fig.update_layout(
    title_text="",
    xaxis_title="Fecha",
    yaxis_title="Precio",
    template="plotly_white",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="black"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(t=10)
)

# === Marca de inicio del régimen y sombreado hacia adelante ===
inicio_regimen = pd.to_datetime(bandas["fecha"].min())

# incluir el spot en el límite derecho si existe
x_max = pd.to_datetime(
    max(
        bandas["fecha"].max() if not bandas.empty else inicio_regimen,
        historico["fecha"].max() if not historico.empty else inicio_regimen,
        pd.to_datetime(ahora_naive) if usd_mayorista is not None else inicio_regimen
    )
)

fig.add_vline(
    x=inicio_regimen,
    line_width=1,
    line_dash="dot",
    line_color="gray",
    opacity=0.9,
)

fig.add_annotation(
    x=inicio_regimen,
    yref="paper",
    y=0.93,
    xanchor="left",
    showarrow=False,
    text="Inicio régimen monetario de bandas cambiarias",
    font=dict(size=12, color="black")
)

fig.add_shape(
    type="rect",
    xref="x", yref="paper",
    x0=inicio_regimen, x1=x_max,
    y0=0, y1=1,
    fillcolor="lightgrey",
    opacity=0.12,
    line_width=0,
    layer="below"
)

st.plotly_chart(fig, width="stretch")

# Caption con hora local AR y fuente
subtitulo_fuente = f"Fuente: {fuente_actual} • Última actualización (AR): {ahora_ar.strftime('%Y-%m-%d %H:%M:%S')}"
st.caption(subtitulo_fuente)

# Footer de contacto
st.markdown(
    "<div style='text-align:center; color:#6b7280; font-size:12px; margin-top:8px;'>"
    "Consultas o feedback: <a href='mailto:benjamingomezalonso@gmail.com'>benjamingomezalonso@gmail.com</a>"
    "</div>",
    unsafe_allow_html=True
)
