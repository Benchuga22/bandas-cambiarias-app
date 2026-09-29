# Bandas Cambiarias

App de Streamlit que grafica el dólar mayorista contra las bandas cambiarias del BCRA
desde el inicio del régimen (14/04/2025).

## Datos

| Archivo | Qué tiene | Fuente |
|---|---|---|
| `data/mayorista.csv` | Cierre diario del dólar mayorista (`fecha, precio`) | [A3 Mercados / MAE](https://marketdata.mae.com.ar/titulos/FOR/UST$T?plazo=000&segmento=M&moneda=T) — UST$T, plazo 000, segmento mayorista |
| `data/bandas.csv` | Límites de la banda (`fecha, piso, techo`) | [API de estadísticas del BCRA](https://api.bcra.gob.ar/estadisticas/v4.0/monetarias) — series 1187 (piso) y 1188 (techo) |

El punto "USD Actual" del gráfico se toma en vivo de [DolarAPI](https://dolarapi.com/v1/dolares/mayorista)
cada vez que se abre la app. Si no responde, se muestra sólo el histórico.

## Actualización automática

El workflow [`actualizar-datos`](.github/workflows/actualizar_datos.yml) corre de lunes a viernes
a las 16:47 y a las 20:47 (hora Argentina), baja ambas series y commitea los CSV sólo si hubo cambios.
Si alguna fuente falla, guarda la otra y el workflow queda en rojo (GitHub avisa por mail).

Para correrlo a mano: pestaña **Actions → actualizar-datos → Run workflow**. El campo opcional
"desde" permite rehacer el histórico del mayorista desde una fecha (`YYYY-MM-DD`).

## Correr localmente

```bash
pip install -r requirements.txt
streamlit run app3.py

# actualizar los datos a mano
python scripts/actualizar_mayorista.py
python scripts/actualizar_bandas.py
```
