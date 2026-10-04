"""Fase 3: calcula la prominencia de cada pico y compara umbrales (30, 50 y 100 m).

Uso:
    python scripts/fase3_prominencia.py --region ES-VC             # con el MDT25
    python scripts/fase3_prominencia.py --region ES-VC --mdt MDT05

Necesita la salida de la fase 1 (data/salida/fase1/picos_osm_<region>.csv). El MDT se
descarga (o se reutiliza si ya está en data/mdt/) igual que en la fase 2.

Salidas en data/salida/fase3/:
    prominencia_<region>.csv        una fila por pico de OSM con su prominencia y su collado
    umbrales_<region>.csv           cuántas cimas superan cada umbral, en total y por provincia
    prominencia_<region>.json       cifras resumen
    prominencia_<region>.md         informe legible
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cimas.mdt import obtener_modelo, preparar_mosaico  # noqa: E402
from cimas.prominencia import (  # noqa: E402
    UMBRALES, calcular_prominencias, prominencia_picos, tabla_umbrales,
)
from cimas.regiones import obtener_region  # noqa: E402

# Cimas conocidas para comprobar a ojo que los resultados tienen sentido
CIMAS_REFERENCIA = ("Penyagolosa", "Aitana", "Montgó", "Calderón", "Puig Campana", "Benicadell",
                    "Mondúver", "Garbí", "Caroig", "Maigmó", "Bèrnia", "Rápita", "Montcabrer")


def _fmt(v, dec=0):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    return f"{v:.{dec}f}" if isinstance(v, float) else str(v)


def _fila_cima(p) -> str:
    nombre = p["nombre"] if isinstance(p["nombre"], str) else "(sin nombre)"
    minima = " (mín.)" if p["prominencia_es_minima"] else ""
    return (f"| {nombre} | {p['provincia'] if isinstance(p['provincia'], str) else '-'} | "
            f"{_fmt(p['altitud_mdt'])} | {_fmt(p['prominencia'])}{minima} | "
            f"{_fmt(p['altitud_collado'])} |")


def informe_md(region_nombre: str, modelo: str, tabla: pd.DataFrame, prom: pd.DataFrame,
               r: dict, fecha: str) -> str:
    total = tabla[tabla["ambito"] == "Total"].iloc[0]
    lineas = [
        f"# Prominencia de las cimas — {region_nombre}",
        "",
        f"Picos: © colaboradores de OpenStreetMap (ODbL 1.0). Terreno: {modelo} © Instituto "
        f"Geográfico Nacional (CNIG), CC BY 4.0 (descarga {fecha}).",
        "",
        "Prominencia = altitud de la cima − altitud del collado más alto por el que hay que bajar "
        "para llegar a un terreno más alto. Calculada sobre el MDT, con la cima del MDT más alta "
        f"a menos de {r['radio_busqueda_m']:.0f} m de cada pico de OSM (si esa cima es solo una "
        "irregularidad de menos de 10 m junto a la cumbre, se toma la cumbre).",
        "",
        "## Cuántas cimas salen con cada umbral",
        "",
        f"Cimas distintas de partida: **{int(total['cimas'])}** "
        f"({r['picos_osm']} picos de OSM; {r['picos_comparten_cima']} comparten cima en el MDT "
        "y cuentan una sola vez).",
        "",
        "| Umbral | Cimas | Con nombre | % del total | Dudosas* |",
        "|---|---|---|---|---|",
    ]
    for u in UMBRALES:
        lineas.append(
            f"| ≥ {u} m | **{total[f'prom_{u}m']}** | {total[f'prom_{u}m_con_nombre']} | "
            f"{100 * total[f'prom_{u}m'] / total['cimas']:.1f} % | {total[f'prom_{u}m_dudosas']} |"
        )
    lineas += [
        "",
        "\\* Dudosas: su montaña toca el borde del terreno descargado antes de llegar al collado, "
        "así que solo se conoce un mínimo que no llega al umbral, pero el máximo posible sí.",
        "",
        "### Por provincia",
        "",
        "| Provincia | Cimas | ≥ 30 m | ≥ 50 m | ≥ 100 m |",
        "|---|---|---|---|---|",
    ]
    for _, t in tabla[tabla["ambito"] != "Total"].iterrows():
        lineas.append(f"| {t['ambito']} | {t['cimas']} | {t['prom_30m']} | {t['prom_50m']} | "
                      f"{t['prom_100m']} |")
    lineas += [
        "",
        "## Reparto de prominencias",
        "",
        "| Prominencia | Picos de OSM |",
        "|---|---|",
    ]
    for tramo, n in r["reparto"].items():
        lineas.append(f"| {tramo} | {n} |")
    lineas += [
        "",
        "## Calidad",
        "",
        "| Dato | Valor |",
        "|---|---|",
        f"| Picos de OSM sin cima propia en el MDT (hombros o resaltes; prominencia 0) | "
        f"{r['sin_cima_en_mdt']} |",
        f"| Picos de OSM que caen en la misma cima del MDT que otro | {r['picos_comparten_cima']} |",
        f"| Picos con prominencia acotada por el borde del recorte (mín.) | {r['prominencia_minima']} |",
        f"| Distancia mediana del nodo de OSM a la cima del MDT | {r['distancia_mediana_m']} m |",
        f"| Tiempo de cálculo | {r['segundos_calculo']} s |",
        "",
        "## Cimas más prominentes",
        "",
        "| Cima | Provincia | Altitud MDT (m) | Prominencia (m) | Collado (m) |",
        "|---|---|---|---|---|",
    ]
    top = prom[~prom["comparte_cima_mdt"] | prom["nombre"].notna()]
    for _, p in top.sort_values("prominencia", ascending=False).head(15).iterrows():
        lineas.append(_fila_cima(p))
    lineas += [
        "",
        "## Comprobación con cimas conocidas",
        "",
        "| Cima | Provincia | Altitud MDT (m) | Prominencia (m) | Collado (m) |",
        "|---|---|---|---|---|",
    ]
    nombres = prom["nombre"].fillna("")
    for ref in CIMAS_REFERENCIA:
        candidatas = prom[nombres.str.contains(ref, case=False, regex=False)]
        if len(candidatas):
            lineas.append(_fila_cima(candidatas.sort_values("altitud_mdt", ascending=False).iloc[0]))
    return "\n".join(lineas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="ES-VC")
    ap.add_argument("--mdt", default="MDT25")
    ap.add_argument("--radio-m", type=float, default=75.0,
                    help="Radio de búsqueda de la cima del MDT alrededor de cada pico de OSM")
    args = ap.parse_args()

    import rasterio

    region = obtener_region(args.region)
    modelo = obtener_modelo(args.mdt)
    epsg = region.epsg_utm
    picos = pd.read_csv(RAIZ / "data" / "salida" / "fase1" / f"picos_osm_{region.iso}.csv")

    print(region.nombre)
    ruta_mdt, info = preparar_mosaico(picos, epsg, modelo, region.iso, RAIZ / "data" / "mdt")

    print("Calculando prominencias sobre todo el terreno...")
    with rasterio.open(ruta_mdt) as src:
        z = src.read(1, masked=True).astype("float32").filled(np.nan)
        transform = src.transform
    t0 = time.time()
    res = calcular_prominencias(z)
    segundos = round(time.time() - t0)
    print(f"  hecho en {segundos} s")

    prom = prominencia_picos(picos, z, transform, epsg, res, args.radio_m)
    tabla = tabla_umbrales(prom)

    tramos = pd.cut(prom["prominencia"], [-0.1, 10, 30, 50, 100, 300, 1e5], right=False,
                    labels=["< 10 m", "10–30 m", "30–50 m", "50–100 m", "100–300 m", "≥ 300 m"])
    r = {
        "region": region.iso, "mdt": modelo.nombre, "radio_busqueda_m": args.radio_m,
        "picos_osm": int(len(prom)),
        "sin_cima_en_mdt": int(prom["sin_cima_en_mdt"].sum()),
        "picos_comparten_cima": int(prom["comparte_cima_mdt"].sum()),
        "prominencia_minima": int(prom["prominencia_es_minima"].sum()),
        "distancia_mediana_m": round(float(prom["distancia_a_cima_mdt_m"].median()), 1),
        "reparto": {str(k): int(v) for k, v in tramos.value_counts(sort=False).items()},
        "umbrales": tabla.to_dict(orient="records"),
        "segundos_calculo": segundos,
        "mdt_fecha_descarga": info["fecha_descarga"],
    }

    salida = RAIZ / "data" / "salida" / "fase3"
    salida.mkdir(parents=True, exist_ok=True)
    prom.assign(fuente_prominencia=f"Calculada sobre {modelo.nombre} © IGN (CC BY 4.0)") \
        .drop(columns="cima_mdt").to_csv(salida / f"prominencia_{region.iso}.csv", index=False)
    tabla.to_csv(salida / f"umbrales_{region.iso}.csv", index=False)
    (salida / f"prominencia_{region.iso}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    md = informe_md(region.nombre, modelo.nombre, tabla, prom, r, info["fecha_descarga"])
    (salida / f"prominencia_{region.iso}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
