"""Fase 2: descarga el modelo de elevaciones (MDT) del IGN y lo valida con los picos de OSM.

Uso:
    python scripts/fase2_mdt.py --region ES-VC                # MDT25 (por defecto)
    python scripts/fase2_mdt.py --region ES-VC --mdt MDT05

Necesita la salida de la fase 1 (data/salida/fase1/picos_osm_<region>.csv).

Salidas:
    data/mdt/teselas/...                       teselas descargadas (no se versionan)
    data/mdt/<MDT>_<region>.tif                mosaico de la región (no se versiona)
    data/salida/fase2/comparacion_altitud_<region>.csv   altitud OSM frente a MDT por pico
    data/salida/fase2/mdt_<region>.json        cifras resumen
    data/salida/fase2/mdt_<region>.md          informe legible
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cimas.mdt import (  # noqa: E402
    WCS_URL, a_utm, descargar_teselas, muestrear_picos, obtener_modelo,
    resumen_comparacion, teselas_necesarias, unir_teselas,
)
from cimas.regiones import obtener_region  # noqa: E402


def informe_md(region_nombre: str, modelo, info: dict, comp: dict, peores: pd.DataFrame,
               por_prov: pd.DataFrame, fecha: str) -> str:
    lineas = [
        f"# Modelo de elevaciones — {region_nombre}",
        "",
        f"Fuente: {modelo.nombre} © Instituto Geográfico Nacional (CNIG), CC BY 4.0. "
        f"Servicio WCS {WCS_URL}. Descarga: {fecha}.",
        "",
        "## Terreno descargado",
        "",
        "| Dato | Valor |",
        "|---|---|",
        f"| Modelo | {modelo.nombre} ({modelo.descripcion}) |",
        f"| Teselas de {info['lado_tesela_km']} km | {info['teselas']} |",
        f"| Tamaño del mosaico | {info['ancho_px']} × {info['alto_px']} píxeles, {info['tamano_mb']} MB |",
        f"| Tipo de dato original | {info['tipo_dato_original']} |",
        f"| Superficie sin dato (mar o fuera de cobertura) | {info['pct_sin_dato']} % |",
        f"| Altitud mínima / máxima | {info['altitud_min']} m / {info['altitud_max']} m |",
        "",
        "## Comparación con la altitud de OSM",
        "",
        "Altitud del MDT = la máxima en un radio de 50 m alrededor del pico de OSM.",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Picos comparados (con altitud en OSM) | {comp['picos_comparados']} |",
        f"| Picos sin dato en el MDT | {comp['picos_sin_dato_mdt']} |",
        f"| Diferencia mediana (OSM − MDT) | {comp['diferencia_mediana_m']} m |",
        f"| Diferencia absoluta mediana | {comp['diferencia_abs_mediana_m']} m |",
        f"| Coinciden a ±5 m | {comp['pct_dentro_5m']} % |",
        f"| Coinciden a ±10 m | {comp['pct_dentro_10m']} % |",
        f"| Coinciden a ±25 m | {comp['pct_dentro_25m']} % |",
        f"| Diferencia mayor de 50 m | {comp['picos_mas_50m']} picos |",
        "",
        "### Por provincia (diferencia absoluta mediana)",
        "",
        "| Provincia | Picos | Mediana (m) | ±10 m (%) |",
        "|---|---|---|---|",
    ]
    for _, p in por_prov.iterrows():
        lineas.append(f"| {p['provincia']} | {p['picos']} | {p['mediana']} | {p['pct_10m']} |")
    lineas += [
        "",
        "### Mayores diferencias (revisar: altitud mal puesta en OSM o pico mal situado)",
        "",
        "| OSM | Nombre | Altitud OSM | Altitud MDT | Diferencia |",
        "|---|---|---|---|---|",
    ]
    for _, p in peores.iterrows():
        lineas.append(
            f"| {p['osm_id']} | {p['nombre'] if isinstance(p['nombre'], str) else '-'} | "
            f"{p['altitud_osm']} | {p['altitud_mdt_max_50m']} | {p['diferencia_osm_mdt']} |"
        )
    return "\n".join(lineas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="ES-VC")
    ap.add_argument("--mdt", default="MDT25", help="MDT25 (por defecto), MDT05 o MDT200")
    ap.add_argument("--lado-km", type=int, default=10, help="Lado de cada tesela de descarga")
    ap.add_argument("--margen-km", type=int, default=15, help="Margen alrededor de cada pico")
    args = ap.parse_args()

    region = obtener_region(args.region)
    modelo = obtener_modelo(args.mdt)
    epsg = region.epsg_utm
    picos = pd.read_csv(RAIZ / "data" / "salida" / "fase1" / f"picos_osm_{region.iso}.csv")

    x, y = a_utm(picos["lat"], picos["lon"], epsg)
    lado = args.lado_km * 1000
    teselas = teselas_necesarias(x, y, lado, args.margen_km * 1000)
    print(f"{region.nombre}: {len(picos)} picos -> {len(teselas)} teselas de {args.lado_km} km "
          f"del {modelo.nombre} ({modelo.cobertura(epsg)})")

    fecha = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dir_teselas = RAIZ / "data" / "mdt" / "teselas" / f"{modelo.nombre}_{epsg}"
    rutas = descargar_teselas(modelo, epsg, teselas, lado, dir_teselas)

    ruta_mdt = RAIZ / "data" / "mdt" / f"{modelo.nombre}_{region.iso}.tif"
    print("Uniendo teselas...")
    info = unir_teselas(rutas, ruta_mdt)
    info.update({"modelo": modelo.nombre, "cobertura_wcs": modelo.cobertura(epsg), "epsg": epsg,
                 "teselas": len(teselas), "lado_tesela_km": args.lado_km,
                 "margen_km": args.margen_km, "fecha_descarga": fecha})

    print("Comparando con las altitudes de OSM...")
    comp = muestrear_picos(picos, ruta_mdt, epsg)
    r = resumen_comparacion(comp)
    validos = comp.dropna(subset=["diferencia_osm_mdt"]).assign(abs=lambda d: d["diferencia_osm_mdt"].abs())
    por_prov = (validos.fillna({"provincia": "Sin provincia única"}).groupby("provincia")
                .agg(picos=("abs", "size"), mediana=("abs", "median"),
                     pct_10m=("abs", lambda s: round(100 * (s <= 10).mean(), 1)))
                .reset_index())
    por_prov["mediana"] = por_prov["mediana"].round(1)
    peores = validos.sort_values("abs", ascending=False).head(15)

    salida = RAIZ / "data" / "salida" / "fase2"
    salida.mkdir(parents=True, exist_ok=True)
    comp.to_csv(salida / f"comparacion_altitud_{region.iso}.csv", index=False)
    info_publica = {k: v for k, v in info.items() if k != "archivo"}
    (salida / f"mdt_{region.iso}.json").write_text(
        json.dumps({"mdt": info_publica, "comparacion_osm": r}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = informe_md(region.nombre, modelo, info, r, peores, por_prov, fecha)
    (salida / f"mdt_{region.iso}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
