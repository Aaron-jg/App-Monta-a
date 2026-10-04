"""Modelo digital de elevaciones (MDT) del IGN/CNIG vía su servicio WCS.

El servicio WCS INSPIRE de elevaciones de la IDEE (https://servicios.idee.es/wcs-inspire/mdt)
permite descargar recortes del MDT de forma automática, sin pasar por el formulario
del centro de descargas del CNIG.

Datos © Instituto Geográfico Nacional (CNIG), licencia CC BY 4.0.

El terreno se descarga en teselas cuadradas (por defecto de 10 km de lado) alrededor de
los picos de la región. Cada tesela se guarda en su propio archivo: si una descarga se
corta se puede repetir sin volver a bajar lo ya descargado, y el mismo sistema sirve
para ampliar a otras regiones de España.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

WCS_URL = "https://servicios.idee.es/wcs-inspire/mdt"
USER_AGENT = "app-montana-catalogo-cimas/0.1 (proyecto académico)"


@dataclass(frozen=True)
class ModeloMDT:
    nombre: str
    resolucion_m: int
    descripcion: str

    def cobertura(self, epsg: int) -> str:
        """Identificador de la cobertura WCS, p. ej. Elevacion25830_25."""
        return f"Elevacion{epsg}_{self.resolucion_m}"

    def desfase(self) -> float:
        """Los bordes de píxel del IGN caen en múltiplos de la resolución + media celda."""
        return self.resolucion_m / 2


MODELOS: dict[str, ModeloMDT] = {
    "MDT05": ModeloMDT("MDT05", 5, "Malla de 5 m (LiDAR PNOA)"),
    "MDT25": ModeloMDT("MDT25", 25, "Malla de 25 m (LiDAR PNOA)"),
    "MDT200": ModeloMDT("MDT200", 200, "Malla de 200 m"),
}


def obtener_modelo(nombre: str) -> ModeloMDT:
    try:
        return MODELOS[nombre.upper()]
    except KeyError:
        raise ValueError(f"MDT {nombre!r} no definido. Disponibles: {', '.join(MODELOS)}") from None


def a_utm(lat, lon, epsg: int) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas geográficas (WGS84/ETRS89) a metros en ETRS89 / UTM."""
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    x, y = t.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.asarray(x), np.asarray(y)


def teselas_necesarias(x, y, lado_m: int = 10_000, margen_m: int = 15_000) -> list[tuple[int, int]]:
    """Índices (i, j) de las teselas que cubren cada punto con un margen alrededor.

    El margen permite que, al calcular la prominencia, el collado de un pico situado
    cerca del límite de la región quede dentro del terreno descargado.
    """
    teselas: set[tuple[int, int]] = set()
    for a, b in zip(np.asarray(x), np.asarray(y)):
        for i in range(int((a - margen_m) // lado_m), int((a + margen_m) // lado_m) + 1):
            for j in range(int((b - margen_m) // lado_m), int((b + margen_m) // lado_m) + 1):
                teselas.add((i, j))
    return sorted(teselas)


def limites_tesela(i: int, j: int, lado_m: int, modelo: ModeloMDT) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) de la tesela, alineados con los píxeles del IGN."""
    d = modelo.desfase()
    return i * lado_m + d, j * lado_m + d, (i + 1) * lado_m + d, (j + 1) * lado_m + d


def descargar_tesela(modelo: ModeloMDT, epsg: int, i: int, j: int, lado_m: int,
                     directorio: Path, reintentos: int = 4) -> Path:
    """Descarga una tesela en GeoTIFF. Si ya existe, no la vuelve a pedir."""
    destino = directorio / f"{modelo.nombre}_{epsg}_{lado_m}_{i}_{j}.tif"
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    xmin, ymin, xmax, ymax = limites_tesela(i, j, lado_m, modelo)
    params = [
        ("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
        ("CoverageId", modelo.cobertura(epsg)),
        ("subset", f"x({xmin},{xmax})"), ("subset", f"y({ymin},{ymax})"),
        ("format", "image/tiff"),
    ]
    ultimo_error: Exception | None = None
    for intento in range(reintentos):
        try:
            r = requests.get(WCS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/tiff"):
                temporal = destino.with_suffix(".part")
                temporal.write_bytes(r.content)
                temporal.replace(destino)
                return destino
            ultimo_error = RuntimeError(f"WCS respondió {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            ultimo_error = e
        time.sleep(2 ** (intento + 1))
    raise RuntimeError(f"No se pudo descargar la tesela {i},{j}: {ultimo_error}")


def descargar_teselas(modelo: ModeloMDT, epsg: int, teselas: list[tuple[int, int]], lado_m: int,
                      directorio: Path, hilos: int = 4) -> list[Path]:
    directorio.mkdir(parents=True, exist_ok=True)
    total = len(teselas)
    rutas: list[Path] = []
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = [ex.submit(descargar_tesela, modelo, epsg, i, j, lado_m, directorio)
                   for i, j in teselas]
        for n, f in enumerate(futuros, 1):
            rutas.append(f.result())
            if n % 50 == 0 or n == total:
                print(f"  teselas descargadas: {n}/{total}")
    return rutas


def unir_teselas(rutas: list[Path], destino: Path, nodata: float = -9999.0) -> dict:
    """Une las teselas en un único GeoTIFF comprimido (float32, metros)."""
    import rasterio
    from rasterio.merge import merge

    fuentes = [rasterio.open(p) for p in rutas]
    try:
        tipo_original = fuentes[0].dtypes[0]
        nodata_original = fuentes[0].nodata
        relleno = nodata_original if nodata_original is not None else nodata
        mosaico, transform = merge(fuentes, nodata=relleno, dtype="float32")
        crs = fuentes[0].crs
    finally:
        for f in fuentes:
            f.close()
    datos = mosaico[0]
    invalido = ~np.isfinite(datos)
    invalido |= datos == relleno
    invalido |= datos < -100   # valores de relleno típicos (-9999, -32767...) sin etiqueta nodata
    datos = np.where(invalido, nodata, datos).astype("float32")

    destino.parent.mkdir(parents=True, exist_ok=True)
    perfil = {
        "driver": "GTiff", "height": datos.shape[0], "width": datos.shape[1], "count": 1,
        "dtype": "float32", "crs": crs, "transform": transform, "nodata": nodata,
        "compress": "deflate", "predictor": 3, "tiled": True, "blockxsize": 512, "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(destino, "w", **perfil) as dst:
        dst.write(datos, 1)
        dst.update_tags(fuente="MDT © Instituto Geográfico Nacional (CNIG), CC BY 4.0",
                        servicio=WCS_URL)
    validos = datos[~invalido]
    return {
        "archivo": str(destino),
        "ancho_px": int(datos.shape[1]), "alto_px": int(datos.shape[0]),
        "resolucion_m": float(transform.a),
        "tipo_dato_original": str(tipo_original),
        "nodata_original": None if nodata_original is None else float(nodata_original),
        "pct_sin_dato": round(100 * float(invalido.mean()), 1),
        "altitud_min": float(validos.min()) if validos.size else None,
        "altitud_max": float(validos.max()) if validos.size else None,
        "tamano_mb": round(destino.stat().st_size / 1e6, 1),
    }


def muestrear_picos(df: pd.DataFrame, ruta_mdt: Path, epsg: int, radio_m: float = 50.0) -> pd.DataFrame:
    """Altitud del MDT en cada pico: en el punto exacto y la máxima en un radio.

    Los nodos de OSM a menudo no están exactamente en el punto más alto, así que la
    máxima dentro de un radio pequeño (50 m) es la referencia más justa para comparar.
    """
    import rasterio

    x, y = a_utm(df["lat"], df["lon"], epsg)
    en_punto = np.full(len(df), np.nan)
    en_radio = np.full(len(df), np.nan)
    with rasterio.open(ruta_mdt) as src:
        datos = src.read(1, masked=True).filled(np.nan)
        res = src.transform.a
        r_px = max(1, int(round(radio_m / res)))
        filas, cols = rasterio.transform.rowcol(src.transform, x, y)
        alto, ancho = datos.shape
        for k, (f, c) in enumerate(zip(filas, cols)):
            if not (0 <= f < alto and 0 <= c < ancho):
                continue
            en_punto[k] = datos[f, c]
            ventana = datos[max(0, f - r_px):f + r_px + 1, max(0, c - r_px):c + r_px + 1]
            # solo los píxeles dentro del círculo
            ff, cc = np.ogrid[max(0, f - r_px) - f:min(alto, f + r_px + 1) - f,
                              max(0, c - r_px) - c:min(ancho, c + r_px + 1) - c]
            circulo = ff ** 2 + cc ** 2 <= r_px ** 2
            vals = ventana[circulo]
            if np.isfinite(vals).any():
                en_radio[k] = np.nanmax(vals)
    salida = df[["osm_id", "nombre", "altitud_osm", "lat", "lon", "provincia"]].copy()
    salida["altitud_mdt_punto"] = np.round(en_punto, 1)
    salida[f"altitud_mdt_max_{int(radio_m)}m"] = np.round(en_radio, 1)
    salida["diferencia_osm_mdt"] = np.round(salida["altitud_osm"] - en_radio, 1)
    return salida


def resumen_comparacion(comp: pd.DataFrame) -> dict:
    """Cifras de concordancia entre la altitud de OSM y la del MDT."""
    d = comp["diferencia_osm_mdt"].dropna()
    a = d.abs()
    return {
        "picos_comparados": int(d.size),
        "picos_sin_dato_mdt": int(comp.filter(like="altitud_mdt_max").iloc[:, 0].isna().sum()),
        "diferencia_mediana_m": round(float(d.median()), 1) if d.size else None,
        "diferencia_abs_mediana_m": round(float(a.median()), 1) if d.size else None,
        "pct_dentro_5m": round(100 * float((a <= 5).mean()), 1) if d.size else None,
        "pct_dentro_10m": round(100 * float((a <= 10).mean()), 1) if d.size else None,
        "pct_dentro_25m": round(100 * float((a <= 25).mean()), 1) if d.size else None,
        "picos_mas_50m": int((a > 50).sum()),
    }


def preparar_mosaico(picos: pd.DataFrame, epsg: int, modelo: ModeloMDT, region_iso: str,
                     dir_mdt: Path, lado_km: int = 10, margen_km: int = 15) -> tuple[Path, dict]:
    """Descarga (o reutiliza) las teselas alrededor de los picos y crea el mosaico."""
    from datetime import datetime, timezone

    x, y = a_utm(picos["lat"], picos["lon"], epsg)
    lado = lado_km * 1000
    teselas = teselas_necesarias(x, y, lado, margen_km * 1000)
    print(f"{len(picos)} picos -> {len(teselas)} teselas de {lado_km} km "
          f"del {modelo.nombre} ({modelo.cobertura(epsg)})")
    fecha = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rutas = descargar_teselas(modelo, epsg, teselas, lado,
                              dir_mdt / "teselas" / f"{modelo.nombre}_{epsg}")
    ruta = dir_mdt / f"{modelo.nombre}_{region_iso}.tif"
    print("Uniendo teselas...")
    info = unir_teselas(rutas, ruta)
    info.update({"modelo": modelo.nombre, "cobertura_wcs": modelo.cobertura(epsg), "epsg": epsg,
                 "teselas": len(teselas), "lado_tesela_km": lado_km, "margen_km": margen_km,
                 "fecha_descarga": fecha})
    return ruta, info
