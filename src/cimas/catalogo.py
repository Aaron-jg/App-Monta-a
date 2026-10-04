"""Construcción del catálogo final de cimas a partir de las fases 1 a 3.

Reglas:
- Entra toda cima con prominencia ≥ umbral (mínimo garantizado), más las de la lista
  manual de emblemáticas.
- Si varios picos de OSM caen en la misma cima del MDT, queda uno (con nombre, con nombre
  en valenciano, con altitud... por ese orden de preferencia).
- Altitud: la de OSM si coincide con el MDT a ±10 m (suele venir de vértices geodésicos y
  mapas del IGN, con más precisión que la malla de 25 m); si no, la del MDT.
- Cada cima tiene un identificador propio (UUID) que se conserva entre ejecuciones:
  se guarda en data/catalogo/ids_cimas_<region>.csv y se reasigna por osm_id o, si el nodo
  de OSM ha cambiado, por cercanía (≤ 100 m).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .mdt import a_utm
from .regiones import Region

TOLERANCIA_ALTITUD_M = 10
RADIO_REASIGNAR_ID_M = 100

COLUMNAS = [
    "id", "osm_id", "nombre", "nombre_es", "nombre_ca", "nombre_eu", "nombre_gl",
    "altitud_m", "altitud_fuente", "prominencia_m", "prominencia_es_minima", "altitud_collado_m",
    "categoria", "latitud", "longitud",
    "ccaa_ine", "ccaa", "provincia_ine", "provincia", "comarca", "municipio_ine", "municipio",
    "fuente", "fuente_prominencia", "osm_version", "osm_fecha_edicion", "fecha_catalogo",
]


def quitar_duplicados(prom: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Deja un único pico de OSM por cada cima del MDT."""
    d = prom.copy()
    orden = pd.DataFrame({"a": d["nombre"].isna(), "b": d["nombre_ca"].isna(),
                          "c": d["altitud_osm"].isna(), "d": d["distancia_a_cima_mdt_m"].fillna(1e9)})
    comparten = d[d["comparte_cima_mdt"]]
    # Una cima del MDT queda identificada por su altitud y su collado
    clave = ["altitud_mdt", "altitud_collado", "collado_lat", "collado_lon"]
    preferidos = orden.loc[comparten.index].sort_values(["a", "b", "c", "d"], kind="stable").index
    elegidos = comparten.loc[preferidos].drop_duplicates(subset=clave)
    resultado = pd.concat([d[~d["comparte_cima_mdt"]], elegidos]).sort_index()
    return resultado, len(d) - len(resultado)


def elegir_altitud(osm: float, mdt: float) -> tuple[float, str]:
    if pd.notna(osm) and pd.notna(mdt) and abs(osm - mdt) <= TOLERANCIA_ALTITUD_M:
        return float(osm), "OpenStreetMap (coincide con MDT a ±10 m)"
    if pd.notna(mdt):
        return float(mdt), "MDT IGN"
    return (float(osm), "OpenStreetMap") if pd.notna(osm) else (np.nan, "")


def asignar_ids(cat: pd.DataFrame, ruta_ids: Path, epsg: int) -> pd.DataFrame:
    """Reutiliza los identificadores ya asignados y crea los nuevos."""
    previos = pd.read_csv(ruta_ids, dtype=str) if ruta_ids.exists() else \
        pd.DataFrame(columns=["id", "osm_id", "latitud", "longitud", "fecha_alta"])
    ids = pd.Series([None] * len(cat), index=cat.index, dtype=object)
    usados: set[str] = set()

    por_osm = dict(zip(previos["osm_id"], previos["id"]))
    for i, osm_id in cat["osm_id"].items():
        if osm_id in por_osm and por_osm[osm_id] not in usados:
            ids[i] = por_osm[osm_id]
            usados.add(ids[i])

    libres = previos[~previos["id"].isin(usados)]
    pendientes = ids[ids.isna()].index
    if len(libres) and len(pendientes):
        xl, yl = a_utm(libres["latitud"].astype(float), libres["longitud"].astype(float), epsg)
        arbol = cKDTree(np.column_stack([xl, yl]))
        xp, yp = a_utm(cat.loc[pendientes, "latitud"], cat.loc[pendientes, "longitud"], epsg)
        dist, idx = arbol.query(np.column_stack([xp, yp]), distance_upper_bound=RADIO_REASIGNAR_ID_M)
        for i, d_, j in zip(pendientes, dist, idx):
            if np.isfinite(d_) and libres.iloc[j]["id"] not in usados:
                ids[i] = libres.iloc[j]["id"]
                usados.add(ids[i])

    hoy = date.today().isoformat()
    nuevos = ids.isna()
    ids[nuevos] = [str(uuid.uuid4()) for _ in range(int(nuevos.sum()))]
    cat = cat.assign(id=ids)

    # Registro de identificadores: se conservan también los de cimas que hayan salido
    actuales = cat[["id", "osm_id", "latitud", "longitud"]].astype(str)
    fechas = dict(zip(previos["id"], previos["fecha_alta"]))
    actuales["fecha_alta"] = [fechas.get(i, hoy) for i in actuales["id"]]
    registro = pd.concat([actuales, previos[~previos["id"].isin(actuales["id"])]])
    ruta_ids.parent.mkdir(parents=True, exist_ok=True)
    registro.to_csv(ruta_ids, index=False)
    return cat


def construir_catalogo(picos: pd.DataFrame, prom: pd.DataFrame, region: Region, umbral: float,
                       emblematicas: pd.DataFrame, modelo: str) -> tuple[pd.DataFrame, dict]:
    """Une picos (fase 1) y prominencia (fase 3), filtra por umbral y deja las columnas finales.

    Devuelve el catálogo (sin id ni municipio/comarca todavía) y cifras del proceso.
    """
    extra = picos[["osm_id", "nombre_ca", "nombre_es", "osm_version", "osm_fecha_edicion"]]
    d = prom.merge(extra, on="osm_id", how="left")
    d = d[~d["sin_cima_en_mdt"]]
    d, duplicados = quitar_duplicados(d)

    manual = set(emblematicas["osm_id"]) if len(emblematicas) else set()
    supera = d["prominencia"] >= umbral
    es_manual = d["osm_id"].isin(manual)
    d = d[supera | es_manual].copy()

    alt = [elegir_altitud(o, m) for o, m in zip(d["altitud_osm"], d["altitud_mdt"])]
    d["altitud_m"] = [a for a, _ in alt]
    d["altitud_fuente"] = [f for _, f in alt]
    d["categoria"] = np.select(
        [d["prominencia"] >= 100, d["prominencia"] >= umbral],
        ["principal", "secundaria"], default="emblematica")
    d = d.rename(columns={"lat": "latitud", "lon": "longitud", "prominencia": "prominencia_m",
                          "altitud_collado": "altitud_collado_m"})
    d["nombre_eu"] = None
    d["nombre_gl"] = None
    d["ccaa_ine"] = region.ine
    d["ccaa"] = region.nombre
    d["fuente"] = "OpenStreetMap (ODbL 1.0)"
    d["fuente_prominencia"] = f"Calculada sobre {modelo} © IGN (CC BY 4.0)"
    d["fecha_catalogo"] = date.today().isoformat()
    cifras = {"duplicados_quitados": int(duplicados), "por_umbral": int(supera.sum()),
              "emblematicas_anadidas": int((es_manual & ~supera).sum())}
    return d.reset_index(drop=True), cifras


def completar_provincia(cat: pd.DataFrame, region: Region) -> pd.DataFrame:
    """Provincia a partir del código INE del municipio (sus 2 primeros dígitos)."""
    nombres = {p.ine: p.nombre for p in region.provincias}
    prov_ine = cat["municipio_ine"].str[:2]
    por_nombre = {p.nombre: p.ine for p in region.provincias}
    prov_ine = prov_ine.fillna(cat["provincia"].map(por_nombre))
    return cat.assign(provincia_ine=prov_ine,
                      provincia=prov_ine.map(nombres).fillna(cat["provincia"]))


def a_geojson(cat: pd.DataFrame, ruta: Path, atribucion: str) -> None:
    def limpio(v):
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating, float)):
            return None if np.isnan(v) else float(v)
        if isinstance(v, np.bool_):
            return bool(v)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v

    features = [{
        "type": "Feature",
        "id": fila["id"],
        "geometry": {"type": "Point", "coordinates": [round(fila["longitud"], 7), round(fila["latitud"], 7)]},
        "properties": {k: limpio(fila[k]) for k in COLUMNAS if k not in ("latitud", "longitud")},
    } for _, fila in cat.iterrows()]
    ruta.write_text(json.dumps({"type": "FeatureCollection", "attribution": atribucion,
                                "features": features}, ensure_ascii=False), encoding="utf-8")
