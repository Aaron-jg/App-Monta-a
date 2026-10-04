import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cimas.mdt import (  # noqa: E402
    limites_tesela, muestrear_picos, obtener_modelo, resumen_comparacion,
    teselas_necesarias, unir_teselas,
)

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402


def test_modelo_y_cobertura():
    m = obtener_modelo("mdt25")
    assert m.cobertura(25830) == "Elevacion25830_25"
    with pytest.raises(ValueError):
        obtener_modelo("MDT99")


def test_limites_alineados_con_pixeles_ign():
    # El MDT25 del IGN tiene los bordes de píxel en múltiplos de 25 m + 12,5 m
    xmin, ymin, xmax, ymax = limites_tesela(70, 428, 10_000, obtener_modelo("MDT25"))
    assert (xmin, ymin, xmax, ymax) == (700_012.5, 4_280_012.5, 710_012.5, 4_290_012.5)


def test_teselas_con_margen():
    # Un punto en el centro de una tesela con margen menor que media tesela: solo esa
    assert teselas_necesarias([705_000], [4_285_000], 10_000, 4_000) == [(70, 428)]
    # Con 15 km de margen: 4 x 4 teselas
    assert len(teselas_necesarias([705_000], [4_285_000], 10_000, 15_000)) == 16


def _tesela(ruta: Path, x0: float, y0: float, valores: np.ndarray, res: float = 25.0):
    perfil = {"driver": "GTiff", "height": valores.shape[0], "width": valores.shape[1], "count": 1,
              "dtype": "int16", "crs": "EPSG:25830", "transform": from_origin(x0, y0, res, res)}
    with rasterio.open(ruta, "w", **perfil) as dst:
        dst.write(valores.astype("int16"), 1)
    return ruta


def test_unir_y_muestrear(tmp_path):
    # Dos teselas contiguas de 1 km; un "pico" de 900 m a 25 m del punto de OSM
    a = np.full((40, 40), 500)
    b = np.full((40, 40), 600)
    a[20, 21] = 900
    b[0, 0] = -9999                       # relleno sin etiqueta nodata
    rutas = [_tesela(tmp_path / "a.tif", 700_000, 4_290_000, a),
             _tesela(tmp_path / "b.tif", 701_000, 4_290_000, b)]
    info = unir_teselas(rutas, tmp_path / "m.tif")
    assert (info["ancho_px"], info["alto_px"]) == (80, 40)
    assert info["altitud_max"] == 900 and info["altitud_min"] == 500

    from cimas.mdt import a_utm
    from pyproj import Transformer
    # Punto en el centro del píxel (20, 20) -> el máximo en 50 m es el píxel vecino de 900 m
    x, y = 700_000 + 20 * 25 + 12.5, 4_290_000 - 20 * 25 - 12.5
    lon, lat = Transformer.from_crs(25830, 4326, always_xy=True).transform(x, y)
    df = pd.DataFrame({"osm_id": ["node/1", "node/2"], "nombre": ["Test", None],
                       "altitud_osm": [905.0, None], "lat": [lat, 0.0], "lon": [lon, 0.0],
                       "provincia": ["Valencia/València", None]})
    comp = muestrear_picos(df, tmp_path / "m.tif", 25830)
    assert comp.loc[0, "altitud_mdt_punto"] == 500
    assert comp.loc[0, "altitud_mdt_max_50m"] == 900
    assert comp.loc[0, "diferencia_osm_mdt"] == 5
    assert np.isnan(comp.loc[1, "altitud_mdt_max_50m"])   # fuera del mosaico
    r = resumen_comparacion(comp)
    assert r["picos_comparados"] == 1 and r["pct_dentro_5m"] == 100.0
    assert a_utm([lat], [lon], 25830)[0][0] == pytest.approx(x, abs=0.01)
