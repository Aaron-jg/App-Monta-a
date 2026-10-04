"""Municipio y comarca de cada cima a partir de los límites administrativos de OSM.

Se descargan de una vez los límites de municipios (admin_level 8) y comarcas (admin_level 7)
de la región con Overpass, se reconstruyen sus polígonos y se mira en cuál cae cada cima.
Es una sola consulta, en lugar de una por cima.

De cada municipio se toma su código INE (etiqueta `ine:municipio`, o los 5 primeros dígitos
de `ref:ine`). Las comarcas no tienen código INE: se guarda su nombre.

Datos © colaboradores de OpenStreetMap, licencia ODbL 1.0.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

from .osm import ejecutar_overpass

NIVEL_MUNICIPIO = "8"
NIVEL_COMARCA = "7"


def consulta_limites(iso_area: str) -> str:
    return f"""
[out:json][timeout:600];
area["ISO3166-2"="{iso_area}"]->.zona;
rel(area.zona)["boundary"~"^(administrative|political)$"]["admin_level"~"^({NIVEL_COMARCA}|{NIVEL_MUNICIPIO})$"];
out geom;
""".strip()


def poligono_relacion(rel: dict):
    """Polígono de una relación de OSM: anillos exteriores menos anillos interiores."""
    def anillos(rol_buscado: str):
        lineas = []
        for m in rel.get("members", []):
            rol = m.get("role") or "outer"
            if m.get("type") == "way" and m.get("geometry") and rol == rol_buscado:
                coords = [(p["lon"], p["lat"]) for p in m["geometry"]]
                if len(coords) >= 2:
                    lineas.append(LineString(coords))
        return unary_union(list(polygonize(unary_union(lineas)))) if lineas else None

    exterior = anillos("outer")
    if exterior is None or exterior.is_empty:
        return None
    interior = anillos("inner")
    return exterior.difference(interior) if interior is not None and not interior.is_empty else exterior


def _codigo_municipio(tags: dict) -> str | None:
    codigo = tags.get("ine:municipio") or (tags.get("ref:ine") or "")[:5]
    codigo = "".join(ch for ch in str(codigo) if ch.isdigit())
    return codigo.zfill(5) if 1 <= len(codigo) <= 5 else None


def descargar_limites(region_iso: str, dir_raw: Path) -> dict:
    datos = ejecutar_overpass(consulta_limites(region_iso))
    dir_raw.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now(timezone.utc).date().isoformat()
    (dir_raw / f"osm_limites_{region_iso}_{fecha}.json").write_text(json.dumps(datos), encoding="utf-8")
    return datos


def tabla_limites(datos: dict) -> pd.DataFrame:
    """Una fila por municipio o comarca con su polígono."""
    filas = []
    for rel in datos.get("elements", []):
        if rel.get("type") != "relation":
            continue
        tags = rel.get("tags", {})
        nivel = tags.get("admin_level")
        if nivel == NIVEL_MUNICIPIO and tags.get("boundary") != "administrative":
            continue
        geom = poligono_relacion(rel)
        if geom is None:
            continue
        filas.append({"tipo": "municipio" if nivel == NIVEL_MUNICIPIO else "comarca",
                      "nombre": tags.get("name"), "codigo_ine": _codigo_municipio(tags)
                      if nivel == NIVEL_MUNICIPIO else None, "geom": geom})
    return pd.DataFrame(filas, columns=["tipo", "nombre", "codigo_ine", "geom"])


def ubicar_en_limites(df: pd.DataFrame, limites: pd.DataFrame) -> pd.DataFrame:
    """Municipio y comarca de cada fila de df (columnas lat, lon). Mismo índice que df."""
    resultado = pd.DataFrame({"municipio": None, "municipio_ine": None, "comarca": None},
                             index=df.index, dtype=object)
    puntos = [Point(lon, lat) for lat, lon in zip(df["lat"], df["lon"])]
    for tipo in ("municipio", "comarca"):
        capa = limites[limites["tipo"] == tipo].reset_index(drop=True)
        if capa.empty:
            continue
        arbol = STRtree(list(capa["geom"]))
        idx_puntos, idx_geoms = arbol.query(puntos, predicate="intersects")
        for ip, ig in zip(idx_puntos, idx_geoms):
            fila = df.index[ip]
            if resultado.at[fila, tipo] is not None:      # en una línea límite: el primero
                continue
            resultado.at[fila, tipo] = capa.at[ig, "nombre"]
            if tipo == "municipio":
                resultado.at[fila, "municipio_ine"] = capa.at[ig, "codigo_ine"]
    return resultado


def ubicar_puntos(df: pd.DataFrame, region_iso: str, dir_raw: Path) -> pd.DataFrame:
    print("  descargando límites de municipios y comarcas...")
    limites = tabla_limites(descargar_limites(region_iso, dir_raw))
    print(f"  {int((limites['tipo'] == 'municipio').sum())} municipios, "
          f"{int((limites['tipo'] == 'comarca').sum())} comarcas")
    return ubicar_en_limites(df, limites)
