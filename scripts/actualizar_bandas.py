"""
Actualiza data/bandas.csv con los límites oficiales del régimen de bandas cambiarias
que publica el BCRA en su API de estadísticas (v4.0):

    1187 = Límite inferior (piso)
    1188 = Límite superior (techo)

El BCRA publica los valores por adelantado (hasta fin del mes siguiente), sólo días
hábiles. Como la serie es chica, se reescribe completa en cada corrida.

Uso:
    python scripts/actualizar_bandas.py
"""
import sys
from pathlib import Path

import pandas as pd
import requests

API_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{id}"
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "bandas.csv"
SERIES = {"piso": 1187, "techo": 1188}
DESDE = "2025-04-01"  # el régimen arrancó el 14/04/2025
HASTA = "2030-12-31"


def traer_serie(id_variable: int) -> pd.Series:
    r = requests.get(
        API_URL.format(id=id_variable),
        params={"desde": DESDE, "hasta": HASTA, "limit": 3000},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    resultados = r.json().get("results") or []
    detalle = resultados[0]["detalle"] if resultados else []
    if not detalle:
        raise RuntimeError(f"El BCRA no devolvió datos para la serie {id_variable}")
    s = pd.DataFrame(detalle).set_index("fecha")["valor"].astype(float)
    return s


def main() -> int:
    df = pd.DataFrame({col: traer_serie(i) for col, i in SERIES.items()})
    df = df.dropna().sort_index()
    df.index.name = "fecha"

    if len(df) < 100 or (df["piso"] >= df["techo"]).any():
        raise RuntimeError("Los datos del BCRA no pasan el control básico; no se actualiza.")

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH)
    print(
        f"{len(df)} filas ({df.index.min()} a {df.index.max()}). "
        f"Último: piso {df['piso'].iloc[-1]} / techo {df['techo'].iloc[-1]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
