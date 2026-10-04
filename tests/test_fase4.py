import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cimas.admin import consulta_ubicaciones, elegir_unidades, parsear_ubicaciones  # noqa: E402
from cimas.catalogo import (  # noqa: E402
    COLUMNAS, a_geojson, asignar_ids, completar_provincia, construir_catalogo, elegir_altitud,
)
from cimas.regiones import obtener_region  # noqa: E402

REGION = obtener_region("ES-VC")


def test_consulta_y_parseo_ubicaciones():
    q = consulta_ubicaciones([(40.22, -0.35), (38.5, -0.63)], desplazamiento=10)
    assert q.count("is_in(") == 2 and 'indice="11"' in q
    respuesta = {"elements": [
        {"type": "area", "tags": {"boundary": "administrative", "admin_level": "4", "name": "Comunitat Valenciana"}},
        {"type": "area", "tags": {"boundary": "administrative", "admin_level": "7", "name": "l'Alcalatén"}},
        {"type": "area", "tags": {"boundary": "administrative", "admin_level": "8", "name": "Vistabella del Maestrat",
                                  "ine:municipio": "12133"}},
        {"type": "marcador", "tags": {"indice": "10"}},
        {"type": "marcador", "tags": {"indice": "11"}},      # punto sin áreas (en el mar)
    ]}
    areas = parsear_ubicaciones(respuesta)
    assert elegir_unidades(areas[10]) == {"municipio": "Vistabella del Maestrat",
                                          "municipio_ine": "12133", "comarca": "l'Alcalatén"}
    assert elegir_unidades(areas[11])["municipio"] is None
    # Código desde ref:ine (11 dígitos) si falta ine:municipio
    assert elegir_unidades([{"boundary": "administrative", "admin_level": "8", "name": "X",
                             "ref:ine": "46250000000"}])["municipio_ine"] == "46250"


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
