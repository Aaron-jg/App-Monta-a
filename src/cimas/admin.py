"""Municipio y comarca de cada cima a partir de los límites administrativos de OSM.

Se pregunta a Overpass en qué áreas administrativas cae cada punto (`is_in`). De cada
municipio se toma su código INE (etiqueta `ine:municipio`, o los 5 primeros dígitos de
`ref:ine`). Las comarcas no tienen código INE: se guarda su nombre.

Datos © colaboradores de OpenStreetMap, licencia ODbL 1.0.
"""

from __future__ import annotations

import time

import pandas as pd

from .osm import ejecutar_overpass

NIVEL_MUNICIPIO = "8"
NIVEL_COMARCA = "7"


def consulta_ubicaciones(puntos: list[tuple[float, float]], desplazamiento: int = 0) -> str:
    """Consulta Overpass QL con un bloque is_in por punto, separados por un marcador."""
    bloques = []
    for k, (lat, lon) in enumerate(puntos, desplazamiento):
        bloques.append(
            f'is_in({lat:.7f},{lon:.7f})->.a;\n'
            f'area.a["boundary"~"^(administrative|political)$"]["admin_level"];\n'
            f'out tags;\n'
            f'make marcador indice="{k}";\nout;'
        )
    return "[out:json][timeout:600];\n" + "\n".join(bloques)


def parsear_ubicaciones(respuesta: dict) -> dict[int, list[dict]]:
    """Agrupa las áreas devueltas por punto: {índice: [etiquetas de cada área]}."""
    resultado: dict[int, list[dict]] = {}
    pendientes: list[dict] = []
    for e in respuesta.get("elements", []):
        if e.get("type") == "marcador":
            resultado[int(e["tags"]["indice"])] = pendientes
            pendientes = []
        elif e.get("type") == "area":
            pendientes.append(e.get("tags", {}))
    return resultado


def _codigo_municipio(tags: dict) -> str | None:
    codigo = tags.get("ine:municipio") or (tags.get("ref:ine") or "")[:5]
    codigo = "".join(ch for ch in str(codigo) if ch.isdigit())
    return codigo.zfill(5) if 1 <= len(codigo) <= 5 else None


def elegir_unidades(areas: list[dict]) -> dict:
    """De las áreas que contienen un punto, extrae municipio y comarca."""
    municipio = next((a for a in areas if a.get("admin_level") == NIVEL_MUNICIPIO
                      and a.get("boundary") == "administrative"), None)
    comarca = next((a for a in areas if a.get("admin_level") == NIVEL_COMARCA), None)
    return {
        "municipio": municipio.get("name") if municipio else None,
        "municipio_ine": _codigo_municipio(municipio) if municipio else None,
        "comarca": comarca.get("name") if comarca else None,
    }


def ubicar_puntos(df: pd.DataFrame, lote: int = 150) -> pd.DataFrame:
    """Municipio y comarca de cada fila de df (columnas lat, lon). Mismo orden que df."""
    puntos = list(zip(df["lat"], df["lon"]))
    areas: dict[int, list[dict]] = {}
    for inicio in range(0, len(puntos), lote):
        consulta = consulta_ubicaciones(puntos[inicio:inicio + lote], inicio)
        areas.update(parsear_ubicaciones(ejecutar_overpass(consulta)))
        print(f"  ubicados {min(inicio + lote, len(puntos))}/{len(puntos)}")
        time.sleep(2)
    # Qué tipos de área han aparecido (para revisar el resultado en el registro)
    tipos = pd.Series([(a.get("boundary"), a.get("admin_level")) for lista in areas.values() for a in lista])
    print("  áreas encontradas (boundary, admin_level):", tipos.value_counts().to_dict())
    filas = [elegir_unidades(areas.get(k, [])) for k in range(len(puntos))]
    return pd.DataFrame(filas, index=df.index)
