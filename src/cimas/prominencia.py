"""Cálculo de la prominencia topográfica sobre un modelo digital de elevaciones.

Prominencia de una cima = su altitud menos la del collado más alto por el que hay que
bajar para llegar a un terreno más alto (el "collado clave").

Método ("inundación" de arriba abajo): se recorren todos los píxeles del MDT del más alto
al más bajo, como si el agua bajara de nivel en vez de subir. Cada píxel se une a los
vecinos ya visitados. Cuando dos montañas se juntan en un píxel, ese píxel es el collado
entre ambas: la de cima más baja termina ahí y su prominencia es su cima menos ese collado.

Bordes: más allá del terreno descargado no sabemos qué hay. Se supone que fuera puede
haber terreno más alto, así que un pico cuyo collado clave cae fuera del recorte recibe
una prominencia que es un mínimo garantizado (columna `prominencia_es_minima`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

FUERA = -2   # identificador de la "cima" ficticia del exterior (infinitamente alta)


@njit(cache=True)
def _raiz(padre, i):
    while padre[i] != i:
        padre[i] = padre[padre[i]]
        i = padre[i]
    return i


@njit(cache=True)
def _altura_cima(z, cima):
    return np.inf if cima == FUERA else z[cima]


@njit(cache=True)
def _unir(padre, cima_de, z, a, b, p, prom, collado, es_minima):
    ra = _raiz(padre, a)
    rb = _raiz(padre, b)
    if ra == rb:
        return
    sa, sb = cima_de[ra], cima_de[rb]
    # Gana la montaña de cima más alta; en empate, la que ya existía (sa)
    if _altura_cima(z, sa) >= _altura_cima(z, sb):
        ganadora, perdedora = ra, rb
    else:
        ganadora, perdedora = rb, ra
    s = cima_de[perdedora]
    if s != FUERA:
        prom[s] = z[s] - z[p]
        collado[s] = p
        es_minima[s] = cima_de[ganadora] == FUERA
    padre[perdedora] = ganadora


@njit(cache=True)
def _inundar(z, valido, orden, alto, ancho):
    n = z.size
    exterior = n                       # nodo extra que representa el terreno no descargado
    padre = np.full(n + 1, -1, dtype=np.int32)
    cima_de = np.full(n + 1, -1, dtype=np.int32)
    padre[exterior] = exterior
    cima_de[exterior] = FUERA
    prom = np.full(n, np.nan, dtype=np.float32)
    collado = np.full(n, -1, dtype=np.int32)
    es_minima = np.zeros(n, dtype=np.bool_)

    for k in range(orden.size):
        p = orden[k]
        padre[p] = p
        cima_de[p] = p
        f, c = p // ancho, p % ancho
        en_borde = False
        for df in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if df == 0 and dc == 0:
                    continue
                ff, cc = f + df, c + dc
                if ff < 0 or ff >= alto or cc < 0 or cc >= ancho:
                    en_borde = True
                    continue
                q = ff * ancho + cc
                if not valido[q]:
                    en_borde = True
                elif padre[q] != -1:
                    _unir(padre, cima_de, z, p, q, p, prom, collado, es_minima)
        if en_borde:
            _unir(padre, cima_de, z, p, exterior, p, prom, collado, es_minima)
    return prom, collado, es_minima


def calcular_prominencias(z2d: np.ndarray) -> dict:
    """Prominencia de todas las cimas (máximos locales) de un MDT.

    z2d: matriz de altitudes con NaN donde no hay dato.
    Devuelve arrays planos del tamaño del MDT:
      prominencia  (NaN salvo en las cimas; 0 en píxeles que no son cima)
      collado      índice del píxel del collado clave de cada cima
      es_minima    True si la prominencia es solo un mínimo (collado fuera del recorte)
    """
    alto, ancho = z2d.shape
    z = np.ascontiguousarray(z2d, dtype=np.float32).ravel()
    valido = np.isfinite(z)
    clave = np.where(valido, -z, np.inf)
    orden = np.argsort(clave, kind="stable")[: int(valido.sum())].astype(np.int32)
    del clave
    prom, collado, es_minima = _inundar(z, valido, orden, alto, ancho)
    return {"prominencia": prom, "collado": collado, "es_minima": es_minima,
            "alto": alto, "ancho": ancho}


def prominencia_picos(df: pd.DataFrame, z2d: np.ndarray, transform, epsg: int,
                      res: dict, radio_m: float = 75.0) -> pd.DataFrame:
    """Asigna a cada pico de OSM la cima del MDT más alta dentro de un radio.

    Si dentro del radio no hay ninguna cima propia del MDT (el pico de OSM es un hombro o
    un resalte que a 25 m de resolución no se distingue), la prominencia se deja en 0 y se
    marca `sin_cima_en_mdt`.
    """
    import rasterio
    from pyproj import Transformer

    from .mdt import a_utm

    alto, ancho = res["alto"], res["ancho"]
    z = z2d.ravel()
    prom, collado, es_minima = res["prominencia"], res["collado"], res["es_minima"]
    x, y = a_utm(df["lat"], df["lon"], epsg)
    filas, cols = rasterio.transform.rowcol(transform, x, y)
    r_px = max(1, int(round(radio_m / transform.a)))
    a_geo = Transformer.from_crs(epsg, 4326, always_xy=True)

    def centro(idx):
        f, c = divmod(int(idx), ancho)
        xx, yy = rasterio.transform.xy(transform, f, c)
        lon, lat = a_geo.transform(xx, yy)
        return xx, yy, lat, lon

    salida = []
    for k, (f, c) in enumerate(zip(filas, cols)):
        reg = {"cima_mdt": -1, "altitud_mdt": np.nan, "prominencia": np.nan,
               "prominencia_es_minima": False, "sin_cima_en_mdt": False,
               "altitud_collado": np.nan, "collado_lat": np.nan, "collado_lon": np.nan,
               "distancia_a_cima_mdt_m": np.nan}
        if 0 <= f < alto and 0 <= c < ancho:
            mejor, mejor_z, max_z = -1, -np.inf, -np.inf
            for ff in range(max(0, f - r_px), min(alto, f + r_px + 1)):
                for cc in range(max(0, c - r_px), min(ancho, c + r_px + 1)):
                    if (ff - f) ** 2 + (cc - c) ** 2 > r_px ** 2:
                        continue
                    q = ff * ancho + cc
                    if np.isfinite(z[q]):
                        max_z = max(max_z, z[q])
                        # cima propia = píxel que no se unió a nada más alto al inundarse
                        if prom[q] > 0 and z[q] > mejor_z:
                            mejor, mejor_z = q, z[q]
            if np.isfinite(max_z):
                reg["altitud_mdt"] = float(max_z)
                if mejor >= 0:
                    xs, ys, _, _ = centro(mejor)
                    reg.update({
                        "cima_mdt": int(mejor), "altitud_mdt": float(mejor_z),
                        "prominencia": float(prom[mejor]),
                        "prominencia_es_minima": bool(es_minima[mejor]),
                        "distancia_a_cima_mdt_m": round(float(np.hypot(xs - x[k], ys - y[k])), 1),
                    })
                    if collado[mejor] >= 0:
                        _, _, lat_c, lon_c = centro(collado[mejor])
                        reg.update({"altitud_collado": float(z[collado[mejor]]),
                                    "collado_lat": round(lat_c, 6), "collado_lon": round(lon_c, 6)})
                else:
                    reg.update({"prominencia": 0.0, "sin_cima_en_mdt": True})
        salida.append(reg)

    out = pd.concat([df[["osm_id", "nombre", "provincia", "altitud_osm", "lat", "lon"]].reset_index(drop=True),
                     pd.DataFrame(salida)], axis=1)
    # Varios nodos de OSM que caen sobre la misma cima del MDT
    con_cima = out["cima_mdt"] >= 0
    out["comparte_cima_mdt"] = False
    out.loc[con_cima, "comparte_cima_mdt"] = out.loc[con_cima, "cima_mdt"].duplicated(keep=False)
    return out


UMBRALES = (30, 50, 100)


def tabla_umbrales(prom: pd.DataFrame, umbrales=UMBRALES) -> pd.DataFrame:
    """Cuántas cimas superan cada umbral, en total y por provincia.

    Una cima con prominencia mínima (collado fuera del recorte) que aún no llega al umbral
    se cuenta aparte como "dudosa": su prominencia real podría ser mayor.
    """
    filas = []
    datos = prom.fillna({"provincia": "Sin provincia única"})
    # Si varios nodos de OSM caen en la misma cima del MDT, cuenta una sola vez
    # (se queda el que tenga nombre)
    con_cima = datos["cima_mdt"] >= 0
    unicos = (datos[con_cima].assign(_sin_nombre=datos["nombre"].isna())
              .sort_values("_sin_nombre", kind="stable")
              .drop_duplicates(subset="cima_mdt").drop(columns="_sin_nombre"))
    datos = pd.concat([unicos, datos[~con_cima]]).sort_index()
    grupos = [("Total", datos)] + list(datos.groupby("provincia"))
    for nombre, g in grupos:
        fila = {"ambito": nombre, "cimas": len(g)}
        for u in umbrales:
            seguro = g["prominencia"] >= u
            dudoso = (~seguro) & g["prominencia_es_minima"]
            fila[f"prom_{u}m"] = int(seguro.sum())
            fila[f"prom_{u}m_con_nombre"] = int((seguro & g["nombre"].notna()).sum())
            fila[f"prom_{u}m_dudosas"] = int(dudoso.sum())
        filas.append(fila)
    return pd.DataFrame(filas)
