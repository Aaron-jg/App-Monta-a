import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("numba")
from cimas.prominencia import calcular_prominencias, prominencia_picos, tabla_umbrales  # noqa: E402


def _dos_montes():
    """Terreno de 21 x 41 píxeles: monte A (1000 m) y monte B (800 m) con un collado a 600 m."""
    z = np.full((21, 41), 100.0)
    z[8:13, 10:31] = 600.0                          # cresta que une los dos montes
    yy, xx = np.mgrid[0:21, 0:41]
    z = np.maximum(z, 1000 - 60 * np.hypot(yy - 10, xx - 10))   # A en (10, 10)
    z = np.maximum(z, 800 - 60 * np.hypot(yy - 10, xx - 30))    # B en (10, 30)
    return np.round(z)


def test_prominencia_dos_montes():
    z = _dos_montes()
    r = calcular_prominencias(z)
    ancho = z.shape[1]
    a, b = 10 * ancho + 10, 10 * ancho + 30
    # B: 800 - 600 (collado en la cresta) = 200 m, exacta
    assert r["prominencia"][b] == 200
    assert not r["es_minima"][b]
    assert z.ravel()[r["collado"][b]] == 600
    assert r["cima_padre"][b] == a
    # A es el más alto: su collado está fuera del recorte -> prominencia mínima garantizada
    assert r["es_minima"][a] and r["es_cima"][a]
    assert r["prominencia_minima"][a] == 1000 - 400   # el borde más alto que toca está a 400 m
    assert np.isnan(r["prominencia"][a])               # máximo desconocido
    # Un píxel de ladera no es cima
    assert not r["es_cima"][10 * ancho + 12]


def test_borde_no_contamina_otras_cimas():
    # Un monte alto que toca el borde no convierte en dudosa a la cima vecina:
    # B se une a A por un collado interior, así que su prominencia es exacta
    z = _dos_montes()
    z[10, 0:10] = 990       # cresta de A que llega al borde a mucha altura
    r = calcular_prominencias(z)
    b = 10 * z.shape[1] + 30
    assert r["prominencia"][b] == 200 and not r["es_minima"][b]


def test_irregularidad_junto_a_la_cumbre():
    from rasterio.transform import from_origin
    from pyproj import Transformer

    z = _dos_montes()
    z[10, 33] = z[10, 32] + 3        # bulto de 3 m a 75 m de la cima B
    t = from_origin(700_000, 4_290_000, 25, 25)
    r = calcular_prominencias(z)
    x, y = 700_000 + 33 * 25 + 12.5, 4_290_000 - 10 * 25 - 12.5
    lon, lat = Transformer.from_crs(25830, 4326, always_xy=True).transform(x, y)
    df = pd.DataFrame({"osm_id": ["node/1"], "nombre": ["B"], "provincia": ["V"],
                       "altitud_osm": [800.0], "lat": [lat], "lon": [lon]})
    p = prominencia_picos(df, z, t, 25830, r, radio_m=30)
    assert p.loc[0, "altitud_mdt"] == 800 and p.loc[0, "prominencia"] == 200


def test_nodata_es_borde():
    z = _dos_montes()
    z[:, 20] = np.nan        # sin dato justo en el collado: B pasa a tener prominencia mínima
    r = calcular_prominencias(z)
    b = 10 * z.shape[1] + 30
    assert r["es_minima"][b] and r["prominencia_minima"][b] == 200


def test_asignar_picos_y_umbrales():
    from pyproj import Transformer
    from rasterio.transform import from_origin

    z = _dos_montes()
    t = from_origin(700_000, 4_290_000, 25, 25)
    r = calcular_prominencias(z)
    a_geo = Transformer.from_crs(25830, 4326, always_xy=True)

    def punto(f, c):
        x, y = 700_000 + c * 25 + 12.5, 4_290_000 - f * 25 - 12.5
        lon, lat = a_geo.transform(x, y)
        return lat, lon

    lat_b, lon_b = punto(10, 31)     # nodo de OSM 25 m al lado de la cima B
    lat_b2, lon_b2 = punto(9, 30)    # nodo duplicado sobre la misma cima
    lat_h, lon_h = punto(2, 20)      # punto en terreno llano: no es cima
    df = pd.DataFrame({
        "osm_id": ["node/1", "node/2", "node/3"], "nombre": ["Monte B", None, "Llano"],
        "provincia": ["Valencia/València"] * 3, "altitud_osm": [800.0, None, 100.0],
        "lat": [lat_b, lat_b2, lat_h], "lon": [lon_b, lon_b2, lon_h],
    })
    p = prominencia_picos(df, z, t, 25830, r)
    assert p.loc[0, "prominencia"] == 200 and p.loc[0, "altitud_mdt"] == 800
    assert p.loc[0, "distancia_a_cima_mdt_m"] == 25
    assert p.loc[0, "altitud_collado"] == 600
    assert p.loc[0, "comparte_cima_mdt"] and p.loc[1, "comparte_cima_mdt"]
    assert p.loc[2, "sin_cima_en_mdt"] and p.loc[2, "prominencia"] == 0

    tabla = tabla_umbrales(p).set_index("ambito")
    assert tabla.loc["Total", "cimas"] == 2               # el duplicado cuenta una vez
    assert tabla.loc["Total", "prom_100m"] == 1
    assert tabla.loc["Total", "prom_100m_con_nombre"] == 1
