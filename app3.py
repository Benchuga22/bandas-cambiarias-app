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

    # Parseo fechas con tolerancia (naive)
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

# 1) Intento con DolarAPI (venta)
venta_api, fecha_api_ar = traer_venta_dolarapi()

# 2) Si DolarAPI falla, intento proxy
usd_mayorista = None
fuente_actual = None

# Hora actual: con tz para mostrar y naive para graficar (coordenada X)
ahora_ar = datetime.now(TZ_AR).replace(second=0, microsecond=0)
ahora_naive = ahora_ar.replace(tzinfo=None)

if venta_api is not None:
    usd_mayorista = venta_api
    fuente_actual = f"DolarAPI (actualizado: {fecha_api_ar.strftime('%Y-%m-%d %H:%M:%S %Z') if isinstance(fecha_api_ar, datetime) else 's/d'})"
else:
    proxy_precio = traer_precio_api_via_proxy()
    if proxy_precio is not None:
        usd_mayorista = float(proxy_precio)
        fuente_actual = "Proxy MAE"
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

# Punto “actual” (solo desde API/proxy si hay)
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

st.plotly_chart(fig, use_container_width=True)

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

# Métrica rápida (deshabilitada)
# st.subheader("")
# col1, col2 = st.columns(2)
# with col1:
#     st.metric("USD Mayorista (venta)", f\"${usd_mayorista:.2f}\" if usd_mayorista is not None else "s/d")
# with col2:
#     st.caption("Visualización en AR; valores en $/USD.")
