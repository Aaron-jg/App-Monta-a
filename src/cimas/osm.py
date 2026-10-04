"""Descarga de picos de OpenStreetMap mediante la API de Overpass.

Datos © colaboradores de OpenStreetMap, licencia ODbL 1.0.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from .regiones import Region

SERVIDORES_OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "app-montana-catalogo-cimas/0.1 (proyecto académico)"


def consulta_picos(iso_area: str, solo_ids: bool = False) -> str:
    """Consulta Overpass QL: todos los natural=peak (nodos y vías) dentro de un área ISO."""
    salida = "out ids;" if solo_ids else "out center tags meta;"
    return f"""
[out:json][timeout:300];
area["ISO3166-2"="{iso_area}"]->.zona;
(
  node["natural"="peak"](area.zona);
  way["natural"="peak"](area.zona);
);
{salida}
""".strip()


def ejecutar_overpass(consulta: str, reintentos: int = 4) -> dict:
    """Envía la consulta probando varios servidores, con esperas crecientes si fallan."""
    ultimo_error: Exception | None = None
    for intento in range(reintentos):
        for url in SERVIDORES_OVERPASS:
            try:
                r = requests.post(
                    url, data={"data": consulta},
                    headers={"User-Agent": USER_AGENT}, timeout=360,
                )
                if r.status_code == 200:
                    return r.json()
                ultimo_error = RuntimeError(f"{url} respondió {r.status_code}: {r.text[:200]}")
            except requests.RequestException as e:
                ultimo_error = e
        time.sleep(2 ** (intento + 1))
    raise RuntimeError(f"No se pudo consultar Overpass: {ultimo_error}")


def descargar_region(region: Region, dir_raw: Path) -> dict:
    """Descarga los picos de la región y los ids por provincia. Guarda el JSON bruto."""
    datos = {
        "region": region.iso,
        "fecha_descarga": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "OpenStreetMap vía Overpass API (ODbL 1.0)",
        "picos": ejecutar_overpass(consulta_picos(region.iso)),
        "ids_por_provincia": {},
    }
    for prov in region.provincias:
        resp = ejecutar_overpass(consulta_picos(prov.iso, solo_ids=True))
        datos["ids_por_provincia"][prov.iso] = [
            f"{e['type']}/{e['id']}" for e in resp["elements"]
        ]
    dir_raw.mkdir(parents=True, exist_ok=True)
    fecha = datos["fecha_descarga"][:10]
    (dir_raw / f"osm_picos_{region.iso}_{fecha}.json").write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8"
    )
    return datos


_NUMERO = re.compile(r"-?\d+(?:[.,]\d+)?")


def parsear_altitud(valor: str | None) -> float | None:
    """Convierte la etiqueta ele de OSM a metros.

    Admite formatos habituales: "1234", "1234 m", "1234.5", "1234,5", "1234;1240"
    (se toma el primero). Devuelve None si no es interpretable o está fuera de rango
    plausible para España (por debajo de -10 m o por encima de 3.800 m).
    """
    if not valor:
        return None
    texto = valor.strip().lower()
    if "ft" in texto or "'" in texto:   # en pies: no se acepta sin revisar
        return None
    m = _NUMERO.search(texto)
    if not m:
        return None
    numero = m.group(0)
    # "1.234" con punto de miles (4 dígitos sin decimales reales)
    if re.fullmatch(r"\d\.\d{3}", numero):
        numero = numero.replace(".", "")
    alt = float(numero.replace(",", "."))
    if not -10 <= alt <= 3800:
        return None
    return alt


def a_tabla(datos: dict, region: Region) -> pd.DataFrame:
    """Convierte la respuesta de Overpass en una tabla con una fila por pico."""
    provincia_de: dict[str, list[str]] = {}
    for iso, ids in datos["ids_por_provincia"].items():
        for osm_id in ids:
            provincia_de.setdefault(osm_id, []).append(iso)
    nombres_prov = {p.iso: p.nombre for p in region.provincias}

    filas = []
    for e in datos["picos"]["elements"]:
        tags = e.get("tags", {})
        if e["type"] == "node":
            lat, lon = e["lat"], e["lon"]
        else:
            lat, lon = e["center"]["lat"], e["center"]["lon"]
        osm_id = f"{e['type']}/{e['id']}"
        provs = provincia_de.get(osm_id, [])
        filas.append({
            "osm_id": osm_id,
            "nombre": tags.get("name"),
            "nombre_ca": tags.get("name:ca"),
            "nombre_es": tags.get("name:es"),
            "ele_texto": tags.get("ele"),
            "altitud_osm": parsear_altitud(tags.get("ele")),
            "lat": lat,
            "lon": lon,
            "provincia_iso": provs[0] if len(provs) == 1 else None,
            "provincia": nombres_prov.get(provs[0]) if len(provs) == 1 else None,
            "n_provincias": len(provs),
            "osm_version": e.get("version"),
            "osm_fecha_edicion": e.get("timestamp"),
            "fuente": "OpenStreetMap (ODbL)",
        })
    return pd.DataFrame(filas)
