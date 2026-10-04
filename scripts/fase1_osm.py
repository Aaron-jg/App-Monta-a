"""Fase 1: descarga los picos de OSM de una región y genera el diagnóstico.

Uso:
    python scripts/fase1_osm.py --region ES-VC
    python scripts/fase1_osm.py --region ES-VC --desde data/raw/osm_picos_ES-VC_2026-10-04.json

Salidas en data/salida/fase1/:
    picos_osm_<region>.csv          una fila por pico
    posibles_duplicados_<region>.csv
    diagnostico_<region>.json       cifras resumen
    diagnostico_<region>.md         informe legible
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cimas.diagnostico import posibles_duplicados, resumen  # noqa: E402
from cimas.osm import a_tabla, descargar_region  # noqa: E402
from cimas.regiones import obtener_region  # noqa: E402


def informe_md(region_nombre: str, r: dict, fecha: str) -> str:
    lineas = [
        f"# Diagnóstico de picos OSM — {region_nombre}",
        "",
        f"Fuente: © colaboradores de OpenStreetMap (ODbL 1.0). Descarga: {fecha}.",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Total de picos (`natural=peak`) | {r['total_picos']} |",
        f"| Con nombre | {r['con_nombre']} ({r['con_nombre_pct']} %) |",
        f"| Con nombre en valenciano (`name:ca`) | {r['con_nombre_ca']} |",
        f"| Con altitud válida | {r['con_altitud']} ({r['con_altitud_pct']} %) |",
        f"| Con `ele` no interpretable | {r['ele_no_interpretable']} |",
        f"| Con nombre y altitud | {r['con_nombre_y_altitud']} |",
        f"| Parejas a menos de 50 m | {r['parejas_cercania']} |",
        f"| Parejas con mismo nombre a menos de 500 m | {r['parejas_mismo_nombre']} |",
        "",
        "## Reparto por provincia",
        "",
        "| Provincia | Picos | Con nombre | Con altitud | Altitud máx. (m) |",
        "|---|---|---|---|---|",
    ]
    for p in r["por_provincia"]:
        lineas.append(
            f"| {p['provincia']} | {p['picos']} | {p['con_nombre']} | "
            f"{p['con_altitud']} | {p['altitud_max'] if p['altitud_max'] == p['altitud_max'] else '-'} |"
        )
    return "\n".join(lineas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="ES-VC")
    ap.add_argument("--desde", type=Path, help="Reutilizar un JSON ya descargado en vez de consultar Overpass")
    args = ap.parse_args()

    region = obtener_region(args.region)
    if args.desde:
        datos = json.loads(args.desde.read_text(encoding="utf-8"))
    else:
        print(f"Descargando picos de {region.nombre} desde Overpass...")
        datos = descargar_region(region, RAIZ / "data" / "raw")

    df = a_tabla(datos, region)
    dups = posibles_duplicados(df, region.epsg_utm)
    r = resumen(df, dups)

    salida = RAIZ / "data" / "salida" / "fase1"
    salida.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida / f"picos_osm_{region.iso}.csv", index=False)
    dups.to_csv(salida / f"posibles_duplicados_{region.iso}.csv", index=False)
    (salida / f"diagnostico_{region.iso}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )
    md = informe_md(region.nombre, r, datos["fecha_descarga"])
    (salida / f"diagnostico_{region.iso}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
