"""
Actualiza data/mayorista.csv con el histórico del dólar mayorista (UST$T, plazo 000,
segmento Mayorista) que publica A3 Mercados / MAE en marketdata.mae.com.ar.

Es el mismo dato que baja el botón de descarga de la página:
https://marketdata.mae.com.ar/titulos/FOR/UST$T?plazo=000&segmento=M&moneda=T

Uso:
    python scripts/actualizar_mayorista.py            # completa desde el último dato
    python scripts/actualizar_mayorista.py --desde 2025-01-01   # rehace desde esa fecha
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API_URL = "https://api.marketdata.mae.com.ar/api/mercado/datosgrafico"
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "mayorista.csv"
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
# Se vuelven a pedir los últimos días por si MAE corrige algún valor
DIAS_SOLAPE = 10

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Origin": "https://marketdata.mae.com.ar",
    "Referer": "https://marketdata.mae.com.ar/",
}


def traer_serie(desde: date, hasta: date) -> pd.DataFrame:
    """Pide la serie diaria a MAE y la devuelve como DataFrame [fecha, precio]."""
    params = {
        "codTitulo": "UST$T",
        "plazo": "000",
        "segmento": "M",
        "moneda": "T",
        "tipoFecha": "R",
        "fecha": desde.isoformat(),
        "fechaHasta": hasta.isoformat(),
    }
    r = requests.get(
        API_URL,
        params={"oTitulo": json.dumps(params, separators=(",", ":"))},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"MAE no devolvió JSON (status {r.status_code}); "
            f"posible bloqueo anti-bot. Inicio de la respuesta: {r.text[:200]!r}"
        )
    precios = r.json().get("precios") or []
    df = pd.DataFrame(precios, columns=["time", "value"])
    # 'time' es la medianoche UTC del día de la cotización
    df["fecha"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    df["precio"] = df["value"].astype(float)
    return df[["fecha", "precio"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="YYYY-MM-DD; por defecto, últimos días del CSV")
    args = ap.parse_args()

    hoy = datetime.now(TZ_AR).date()

    if CSV_PATH.exists():
        actual = pd.read_csv(CSV_PATH, dtype={"fecha": str})
    else:
        actual = pd.DataFrame(columns=["fecha", "precio"])

    if args.desde:
        desde = date.fromisoformat(args.desde)
    elif not actual.empty:
        desde = date.fromisoformat(actual["fecha"].max()) - timedelta(days=DIAS_SOLAPE)
    else:
        desde = date(2025, 1, 1)

    nuevo = traer_serie(desde, hoy)
    if nuevo.empty:
        print(f"MAE no devolvió datos entre {desde} y {hoy}.")
        return 0

    combinado = (
        pd.concat([actual, nuevo])
        .drop_duplicates(subset="fecha", keep="last")  # lo nuevo pisa a lo viejo
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    combinado.to_csv(CSV_PATH, index=False)
    agregadas = len(combinado) - len(actual)
    ultimo = combinado.iloc[-1]
    print(
        f"{len(nuevo)} filas recibidas ({desde} a {hoy}), {agregadas} nuevas. "
        f"Último dato: {ultimo['fecha']} = {ultimo['precio']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
