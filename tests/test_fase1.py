import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cimas.diagnostico import normalizar_nombre, posibles_duplicados, resumen  # noqa: E402
from cimas.osm import a_tabla, parsear_altitud  # noqa: E402
from cimas.regiones import obtener_region  # noqa: E402


@pytest.mark.parametrize("texto,esperado", [
    ("1558", 1558.0),
    ("1558 m", 1558.0),
    ("1558,4", 1558.4),
    ("1.558", 1558.0),
    ("1558;1560", 1558.0),
    ("5000", None),
    ("1200 ft", None),
    ("", None),
    (None, None),
    ("desconocida", None),
])
def test_parsear_altitud(texto, esperado):
    assert parsear_altitud(texto) == esperado


def test_normalizar_nombre():
    assert normalizar_nombre("Penyagolosa") == "penyagolosa"
    assert normalizar_nombre("Pico del Águila") == "del aguila"
    assert normalizar_nombre("Tossal d'Alcoi") == "d alcoi"
    assert normalizar_nombre(None) is None


def _datos_ejemplo():
    elementos = [
        # Penyagolosa y un duplicado a ~20 m
        {"type": "node", "id": 1, "lat": 40.2222, "lon": -0.3508,
         "tags": {"natural": "peak", "name": "Penyagolosa", "ele": "1813"}},
        {"type": "node", "id": 2, "lat": 40.2224, "lon": -0.3507,
         "tags": {"natural": "peak", "ele": "1814"}},
        # Mismo nombre a ~300 m
        {"type": "node", "id": 3, "lat": 38.7000, "lon": -0.4000,
         "tags": {"natural": "peak", "name": "Montcabrer"}},
        {"type": "node", "id": 4, "lat": 38.7027, "lon": -0.4000,
         "tags": {"natural": "peak", "name": "Pic Montcabrer", "ele": "1389"}},
        # Pico aislado en una vía, sin provincia asignada
        {"type": "way", "id": 5, "center": {"lat": 39.5, "lon": -0.9},
         "tags": {"natural": "peak", "name": "Caroig", "name:ca": "Caroig", "ele": "1126 m"}},
    ]
    return {
        "fecha_descarga": "2026-10-04T00:00:00+00:00",
        "picos": {"elements": elementos},
        "ids_por_provincia": {"ES-CS": ["node/1", "node/2"], "ES-A": ["node/3", "node/4"], "ES-V": []},
    }


def test_diagnostico_completo():
    region = obtener_region("ES-VC")
    df = a_tabla(_datos_ejemplo(), region)
    dups = posibles_duplicados(df, region.epsg_utm)
    r = resumen(df, dups)

    assert r["total_picos"] == 5
    assert r["vias"] == 1
    assert r["con_nombre"] == 4
    assert r["con_altitud"] == 4
    assert r["con_nombre_ca"] == 1
    assert r["parejas_cercania"] == 1
    assert r["parejas_mismo_nombre"] == 1
    provs = {p["provincia"]: p["picos"] for p in r["por_provincia"]}
    assert provs == {"Castellón/Castelló": 2, "Alicante/Alacant": 2, "Sin provincia única": 1}
