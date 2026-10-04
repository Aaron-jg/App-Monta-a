import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cimas.admin import tabla_limites, ubicar_en_limites  # noqa: E402
from cimas.catalogo import (  # noqa: E402
    COLUMNAS, a_geojson, asignar_ids, completar_provincia, construir_catalogo, elegir_altitud,
)
from cimas.regiones import obtener_region  # noqa: E402

REGION = obtener_region("ES-VC")


def _rel(nombre, nivel, exterior, interior=None, **tags):
    def via(coords, rol):
        return {"type": "way", "role": rol, "geometry": [{"lon": x, "lat": y} for x, y in coords]}
    # El anillo exterior partido en dos vías, como suele venir en OSM
    miembros = [via(exterior[:3], "outer"), via(exterior[2:] + exterior[:1], "outer")]
    if interior:
        miembros.append(via(interior + interior[:1], "inner"))
    return {"type": "relation", "members": miembros,
            "tags": {"boundary": "administrative", "admin_level": nivel, "name": nombre, **tags}}


def test_limites_y_ubicacion():
    cuadrado = [(0, 0), (2, 0), (2, 2), (0, 2)]
    hueco = [(0.5, 0.5), (1, 0.5), (1, 1), (0.5, 1)]
    datos = {"elements": [
        _rel("Municipio A", "8", cuadrado, hueco, **{"ine:municipio": "12133"}),
        _rel("Enclave B", "8", hueco, **{"ref:ine": "12999000000"}),
        _rel("Comarca C", "7", [(-1, -1), (3, -1), (3, 3), (-1, 3)]),
    ]}
    limites = tabla_limites(datos)
    assert sorted(limites["tipo"]) == ["comarca", "municipio", "municipio"]
    puntos = pd.DataFrame({"lat": [1.5, 0.75, 5.0], "lon": [1.5, 0.75, 5.0]})
    r = ubicar_en_limites(puntos, limites)
    assert r.loc[0].tolist() == ["Municipio A", "12133", "Comarca C"]
    assert r.loc[1].tolist() == ["Enclave B", "12999", "Comarca C"]     # dentro del hueco
    assert r.loc[2].isna().all()


def test_elegir_altitud():
    assert elegir_altitud(1813.0, 1812.0) == (1813.0, "OpenStreetMap (coincide con MDT a ±10 m)")
    assert elegir_altitud(239.0, 334.0) == (334.0, "MDT IGN")
    assert elegir_altitud(np.nan, 500.0) == (500.0, "MDT IGN")


def _entradas():
    picos = pd.DataFrame({
        "osm_id": ["node/1", "node/2", "node/3", "node/4", "node/5"],
        "nombre_ca": ["Penyagolosa", None, None, None, None],
        "nombre_es": [None] * 5, "osm_version": [3] * 5, "osm_fecha_edicion": ["2024-01-01"] * 5,
    })
    base = {"provincia": "Castellón/Castelló", "prominencia_maxima": np.nan, "prominencia_es_minima": False,
            "sin_cima_en_mdt": False, "collado_lat": 40.0, "collado_lon": -0.3, "distancia_a_cima_mdt_m": 10.0,
            "comparte_cima_mdt": False}
    prom = pd.DataFrame([
        {**base, "osm_id": "node/1", "nombre": "Penyagolosa", "altitud_osm": 1815.0, "lat": 40.2228, "lon": -0.3497,
         "altitud_mdt": 1812.0, "prominencia": 438.0, "altitud_collado": 1374.0, "comparte_cima_mdt": True},
        {**base, "osm_id": "node/2", "nombre": None, "altitud_osm": 1812.0, "lat": 40.2229, "lon": -0.3498,
         "altitud_mdt": 1812.0, "prominencia": 438.0, "altitud_collado": 1374.0, "comparte_cima_mdt": True},
        {**base, "osm_id": "node/3", "nombre": "Tossal", "altitud_osm": 900.0, "lat": 40.1, "lon": -0.2,
         "altitud_mdt": 899.0, "prominencia": 45.0, "altitud_collado": 854.0},
        {**base, "osm_id": "node/4", "nombre": "Loma", "altitud_osm": 700.0, "lat": 40.0, "lon": -0.1,
         "altitud_mdt": 700.0, "prominencia": 12.0, "altitud_collado": 688.0},
        {**base, "osm_id": "node/5", "nombre": "Hombro", "altitud_osm": 650.0, "lat": 40.05, "lon": -0.15,
         "altitud_mdt": 650.0, "prominencia": 0.0, "altitud_collado": np.nan, "sin_cima_en_mdt": True},
    ])
    return picos, prom


def test_construir_catalogo_y_ids(tmp_path):
    picos, prom = _entradas()
    emblematicas = pd.DataFrame({"osm_id": ["node/4"], "motivo": ["Cima muy visitada"]})
    cat, cifras = construir_catalogo(picos, prom, REGION, 30, emblematicas, "MDT25")
    assert list(cat["osm_id"]) == ["node/1", "node/3", "node/4"]      # duplicado fuera, hombro fuera
    assert cifras == {"duplicados_quitados": 1, "por_umbral": 2, "emblematicas_anadidas": 1}
    assert list(cat["categoria"]) == ["principal", "secundaria", "emblematica"]
    assert cat.loc[0, "nombre_ca"] == "Penyagolosa" and cat.loc[0, "altitud_m"] == 1815

    cat["municipio"] = ["Vistabella del Maestrat", None, None]
    cat["municipio_ine"] = ["12133", None, None]
    cat["comarca"] = ["l'Alcalatén", None, None]
    cat = completar_provincia(cat, REGION)
    assert list(cat["provincia_ine"]) == ["12", "12", "12"]

    ruta = tmp_path / "ids.csv"
    con_ids = asignar_ids(cat, ruta, REGION.epsg_utm)
    assert con_ids["id"].nunique() == 3
    # Segunda ejecución: el nodo de Penyagolosa cambia de id en OSM y se mueve 20 m -> mismo id
    cat2 = cat.copy()
    cat2.loc[0, "osm_id"] = "node/99"
    cat2.loc[0, "latitud"] += 0.00018
    con_ids2 = asignar_ids(cat2, ruta, REGION.epsg_utm)
    assert list(con_ids2["id"]) == list(con_ids["id"])

    ruta_geo = tmp_path / "c.geojson"
    a_geojson(con_ids2[COLUMNAS], ruta_geo, "© OSM")
    geo = json.loads(ruta_geo.read_text(encoding="utf-8"))
    assert len(geo["features"]) == 3
    assert geo["features"][0]["geometry"]["coordinates"] == [-0.3497, 40.2228 + 0.00018]
    assert geo["features"][1]["properties"]["municipio"] is None
