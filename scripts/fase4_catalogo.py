"""Fase 4: catálogo final de cimas (CSV y GeoJSON) importable en Supabase.

Uso:
    python scripts/fase4_catalogo.py --region ES-VC --umbral 30

Necesita las salidas de la fase 1 (picos) y la fase 3 (prominencia). Descarga de Overpass
los límites de municipios y comarcas para ubicar cada cima.

Entradas manuales:
    data/manual/cimas_emblematicas.csv   osm_id,motivo  (cimas que entran aunque no
                                         lleguen al umbral)
Salidas:
    data/salida/fase4/cimas_<region>.csv       catálogo (una fila por cima)
    data/salida/fase4/cimas_<region>.geojson   el mismo catálogo como mapa
    data/salida/fase4/catalogo_<region>.md     informe
    data/catalogo/ids_cimas_<region>.csv       registro de identificadores (no borrar)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cimas.admin import ubicar_puntos  # noqa: E402
from cimas.catalogo import (  # noqa: E402
    COLUMNAS, a_geojson, asignar_ids, completar_provincia, construir_catalogo,
)
from cimas.regiones import obtener_region  # noqa: E402

ATRIBUCION = ("© colaboradores de OpenStreetMap (ODbL 1.0); contiene información derivada "
              "del {mdt} © Instituto Geográfico Nacional (CNIG), CC BY 4.0")


def pct(n, total):
    return f"{n} ({100 * n / total:.1f} %)" if total else "0"


def informe_md(region_nombre: str, cat: pd.DataFrame, cifras: dict, umbral: float, atribucion: str) -> str:
    n = len(cat)
    lineas = [
        f"# Catálogo de cimas — {region_nombre}",
        "",
        f"Fuentes: {atribucion}.",
        "",
        f"Criterio: prominencia ≥ {umbral:g} m, más la lista manual de cimas emblemáticas.",
        "",
        "| Dato | Valor |",
        "|---|---|",
        f"| Cimas en el catálogo | **{n}** |",
        f"| Por prominencia ≥ {umbral:g} m | {cifras['por_umbral']} |",
        f"| Añadidas a mano (emblemáticas) | {cifras['emblematicas_anadidas']} |",
        f"| Duplicados de OSM fusionados | {cifras['duplicados_quitados']} |",
        f"| Con nombre | {pct(int(cat['nombre'].notna().sum()), n)} |",
        f"| Con nombre en valenciano (`name:ca`) | {pct(int(cat['nombre_ca'].notna().sum()), n)} |",
        f"| Con municipio (código INE) | {pct(int(cat['municipio_ine'].notna().sum()), n)} |",
        f"| Con comarca | {pct(int(cat['comarca'].notna().sum()), n)} |",
        f"| Altitud tomada de OSM (coincide con el MDT a ±10 m) | "
        f"{pct(int(cat['altitud_fuente'].str.startswith('OpenStreetMap').sum()), n)} |",
        f"| Altitud tomada del MDT | {pct(int((cat['altitud_fuente'] == 'MDT IGN').sum()), n)} |",
        "",
        "## Por categoría",
        "",
        "| Categoría | Criterio | Cimas |",
        "|---|---|---|",
        f"| principal | prominencia ≥ 100 m | {int((cat['categoria'] == 'principal').sum())} |",
        f"| secundaria | prominencia {umbral:g}–100 m | {int((cat['categoria'] == 'secundaria').sum())} |",
        f"| emblematica | añadida a mano | {int((cat['categoria'] == 'emblematica').sum())} |",
        "",
        "## Por provincia",
        "",
        "| Provincia | Cimas | Principales | Altitud máx. (m) |",
        "|---|---|---|---|",
    ]
    for prov, g in cat.groupby(cat["provincia"].fillna("(sin dato)")):
        lineas.append(f"| {prov} | {len(g)} | {int((g['categoria'] == 'principal').sum())} | "
                      f"{g['altitud_m'].max():.0f} |")
    lineas += ["", "## Comarcas con más cimas", "", "| Comarca | Cimas |", "|---|---|"]
    for com, k in cat["comarca"].value_counts().head(15).items():
        lineas.append(f"| {com} | {k} |")
    lineas += ["", "## Municipios con más cimas", "", "| Municipio | Cimas |", "|---|---|"]
    for mun, k in cat["municipio"].value_counts().head(10).items():
        lineas.append(f"| {mun} | {k} |")
    return "\n".join(lineas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="ES-VC")
    ap.add_argument("--umbral", type=float, default=30.0, help="Prominencia mínima en metros")
    ap.add_argument("--mdt", default="MDT25", help="MDT con el que se calculó la prominencia")
    args = ap.parse_args()

    region = obtener_region(args.region)
    salida1 = RAIZ / "data" / "salida"
    picos = pd.read_csv(salida1 / "fase1" / f"picos_osm_{region.iso}.csv")
    prom = pd.read_csv(salida1 / "fase3" / f"prominencia_{region.iso}.csv")
    emblematicas = pd.read_csv(RAIZ / "data" / "manual" / "cimas_emblematicas.csv", dtype=str)

    cat, cifras = construir_catalogo(picos, prom, region, args.umbral, emblematicas, args.mdt)
    print(f"{region.nombre}: {len(cat)} cimas con prominencia ≥ {args.umbral:g} m o emblemáticas")

    print("Buscando municipio y comarca de cada cima en OSM...")
    cat = pd.concat([cat.drop(columns=["municipio", "municipio_ine", "comarca"], errors="ignore"),
                     ubicar_puntos(cat.rename(columns={"latitud": "lat", "longitud": "lon"}),
                                   region.iso, RAIZ / "data" / "raw")], axis=1)
    cat = completar_provincia(cat, region)
    cat = asignar_ids(cat, RAIZ / "data" / "catalogo" / f"ids_cimas_{region.iso}.csv", region.epsg_utm)
    cat = cat.sort_values(["provincia_ine", "altitud_m"], ascending=[True, False])[COLUMNAS]

    atribucion = ATRIBUCION.format(mdt=args.mdt)
    salida = salida1 / "fase4"
    salida.mkdir(parents=True, exist_ok=True)
    cat.to_csv(salida / f"cimas_{region.iso}.csv", index=False)
    a_geojson(cat, salida / f"cimas_{region.iso}.geojson", atribucion)
    md = informe_md(region.nombre, cat, cifras, args.umbral, atribucion)
    (salida / f"catalogo_{region.iso}.md").write_text(md, encoding="utf-8")
    (salida / f"catalogo_{region.iso}.json").write_text(
        json.dumps({"umbral_m": args.umbral, "cimas": len(cat), **cifras}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
