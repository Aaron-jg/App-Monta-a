"""Cálculo de la prominencia topográfica sobre un modelo digital de elevaciones.

Prominencia de una cima = su altitud menos la del collado más alto por el que hay que
bajar para llegar a un terreno más alto (el "collado clave").

Método ("inundación" de arriba abajo): se recorren todos los píxeles del MDT del más alto
al más bajo, como si el agua bajara de nivel en vez de subir. Cada píxel se une a los
vecinos ya visitados. Cuando dos montañas se juntan en un píxel, ese píxel es el collado
entre ambas: la de cima más baja termina ahí y su prominencia es su cima menos ese collado.

Bordes: más allá del terreno descargado no sabemos qué hay. Si una montaña toca el borde
del recorte antes de llegar a su collado clave, puede que fuera haya un camino hacia
terreno más alto por un collado más alto. En ese caso la prominencia real está entre un
mínimo (cima − nivel al que tocó el borde) y un máximo (cima − collado encontrado dentro),
y se marca en la columna `prominencia_es_minima`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit


@njit(cache=True)
def _raiz(padre, i):
    while padre[i] != i:
        padre[i] = padre[padre[i]]
        i = padre[i]
    return i


@njit(cache=True)
def _unir(padre, cima_de, cota_borde, z, a, b, p,
          prom, prom_min, collado, cima_padre, es_minima, es_cima):
    ra = _raiz(padre, a)
    rb = _raiz(padre, b)
    if ra == rb:
        return
    # Gana la montaña de cima más alta; en empate, la que ya existía (ra)
    if z[cima_de[ra]] >= z[cima_de[rb]]:
        ganadora, perdedora = ra, rb
    else:
        ganadora, perdedora = rb, ra
    s = cima_de[perdedora]
    prom[s] = z[s] - z[p]
    collado[s] = p
    cima_padre[s] = cima_de[ganadora]
    es_cima[s] = z[s] > z[p]
    if cota_borde[perdedora] > -np.inf:      # tocó el borde antes de llegar a este collado
        es_minima[s] = True
        prom_min[s] = z[s] - cota_borde[perdedora]
    else:
        prom_min[s] = prom[s]
    cota_borde[ganadora] = max(cota_borde[ganadora], cota_borde[perdedora])
    padre[perdedora] = ganadora


@njit(cache=True)
def _inundar(z, valido, orden, alto, ancho):
    n = z.size
    padre = np.full(n, -1, dtype=np.int32)
    cima_de = np.full(n, -1, dtype=np.int32)
    cota_borde = np.full(n, -np.inf, dtype=np.float32)
    prom = np.full(n, np.nan, dtype=np.float32)
    prom_min = np.full(n, np.nan, dtype=np.float32)
    collado = np.full(n, -1, dtype=np.int32)
    cima_padre = np.full(n, -1, dtype=np.int32)
    es_minima = np.zeros(n, dtype=np.bool_)
    es_cima = np.zeros(n, dtype=np.bool_)

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
                    _unir(padre, cima_de, cota_borde, z, p, q, p,
                          prom, prom_min, collado, cima_padre, es_minima, es_cima)
        if en_borde:
            r = _raiz(padre, p)
            cota_borde[r] = max(cota_borde[r], z[p])

    # Montañas que nunca se unieron a otra más alta: la más alta de cada zona conectada.
    # Su collado está fuera del recorte: solo se conoce un mínimo.
    for k in range(orden.size):
        p = orden[k]
        if padre[p] == p:
            s = cima_de[p]
            es_cima[s] = True
            es_minima[s] = True
            base = cota_borde[p] if cota_borde[p] > -np.inf else z[orden[orden.size - 1]]
            prom_min[s] = z[s] - base
    return prom, prom_min, collado, cima_padre, es_minima, es_cima


def calcular_prominencias(z2d: np.ndarray) -> dict:
    """Prominencia de todas las cimas (máximos locales) de un MDT.

    z2d: matriz de altitudes con NaN donde no hay dato.
    Devuelve arrays planos del tamaño del MDT (solo tienen sentido en las cimas):
      es_cima      True en los píxeles que son cima (máximo local)
      prominencia  cima − collado clave encontrado dentro del recorte (máximo posible);
                   NaN si no hay ningún terreno más alto dentro del recorte
      prominencia_minima  mínimo garantizado (igual a la anterior si no es dudosa)
      es_minima    True si la prominencia real puede ser menor por el efecto del borde
      collado      índice del píxel del collado clave
      cima_padre   índice de la cima más alta con la que se une en el collado
    """
    alto, ancho = z2d.shape
    z = np.ascontiguousarray(z2d, dtype=np.float32).ravel()
    valido = np.isfinite(z)
    clave = np.where(valido, -z, np.inf)
    orden = np.argsort(clave, kind="stable")[: int(valido.sum())].astype(np.int32)
    del clave
    prom, prom_min, collado, cima_padre, es_minima, es_cima = _inundar(z, valido, orden, alto, ancho)
    return {"prominencia": prom, "prominencia_minima": prom_min, "collado": collado,
            "cima_padre": cima_padre, "es_minima": es_minima, "es_cima": es_cima,
            "alto": alto, "ancho": ancho}


def prominencia_picos(df: pd.DataFrame, z2d: np.ndarray, transform, epsg: int, res: dict,
                      radio_m: float = 75.0, radio_cumbre_m: float = 150.0,
                      prom_ruido_m: float = 10.0) -> pd.DataFrame:
    """Asigna a cada pico de OSM su cima en el MDT y la prominencia de esa cima.

    1. Se toma la cima del MDT más alta a menos de `radio_m` del nodo de OSM.
    2. Si esa cima es solo una irregularidad (menos de `prom_ruido_m` de prominencia) y la
       cima más alta con la que se une está a menos de `radio_cumbre_m` del nodo, se pasa a
       esa: es la misma cumbre y el nodo de OSM está algo desplazado.
    3. Si no hay ninguna cima del MDT cerca (el pico de OSM es un hombro o un resalte que a
       25 m de resolución no se distingue), la prominencia es 0 y se marca `sin_cima_en_mdt`.
    """
    import rasterio
    from pyproj import Transformer

    from .mdt import a_utm

    alto, ancho = res["alto"], res["ancho"]
    z = z2d.ravel()
    prom, prom_min = res["prominencia"], res["prominencia_minima"]
    collado, cima_padre = res["collado"], res["cima_padre"]
    es_minima, es_cima = res["es_minima"], res["es_cima"]
    x, y = a_utm(df["lat"], df["lon"], epsg)
    filas, cols = rasterio.transform.rowcol(transform, x, y)
    res_m = transform.a
    r_px = max(1, int(round(radio_m / res_m)))
    a_geo = Transformer.from_crs(epsg, 4326, always_xy=True)

    def centro(idx):
        f, c = divmod(int(idx), ancho)
        xx, yy = rasterio.transform.xy(transform, f, c)
        lon, lat = a_geo.transform(xx, yy)
        return xx, yy, lat, lon

    salida = []
    for k, (f, c) in enumerate(zip(filas, cols)):
        reg = {"cima_mdt": -1, "altitud_mdt": np.nan, "prominencia": np.nan,
               "prominencia_maxima": np.nan, "prominencia_es_minima": False,
               "sin_cima_en_mdt": False, "altitud_collado": np.nan,
               "collado_lat": np.nan, "collado_lon": np.nan, "distancia_a_cima_mdt_m": np.nan}
        if 0 <= f < alto and 0 <= c < ancho:
            mejor, mejor_z, max_z = -1, -np.inf, -np.inf
            for ff in range(max(0, f - r_px), min(alto, f + r_px + 1)):
                for cc in range(max(0, c - r_px), min(ancho, c + r_px + 1)):
                    if (ff - f) ** 2 + (cc - c) ** 2 > r_px ** 2:
                        continue
                    q = ff * ancho + cc
                    if np.isfinite(z[q]):
                        max_z = max(max_z, z[q])
                        if es_cima[q] and z[q] > mejor_z:
                            mejor, mejor_z = q, z[q]
            # Subir a la cumbre principal si la cima encontrada es solo una irregularidad
            while mejor >= 0 and prom_min[mejor] < prom_ruido_m and cima_padre[mejor] >= 0:
                fp, cp = divmod(int(cima_padre[mejor]), ancho)
                if np.hypot(fp - f, cp - c) * res_m > radio_cumbre_m:
                    break
                mejor = int(cima_padre[mejor])
            if np.isfinite(max_z):
                reg["altitud_mdt"] = float(max_z)
                if mejor >= 0:
                    xs, ys, _, _ = centro(mejor)
                    reg.update({
                        "cima_mdt": int(mejor), "altitud_mdt": float(z[mejor]),
                        "prominencia": float(prom_min[mejor]),
                        "prominencia_maxima": float(prom[mejor]),
                        "prominencia_es_minima": bool(es_minima[mejor]),
                        "distancia_a_cima_mdt_m": round(float(np.hypot(xs - x[k], ys - y[k])), 1),
                    })
                    if collado[mejor] >= 0:
                        _, _, lat_c, lon_c = centro(collado[mejor])
                        reg.update({"altitud_collado": float(z[collado[mejor]]),
                                    "collado_lat": round(lat_c, 6), "collado_lon": round(lon_c, 6)})
                else:
                    reg.update({"prominencia": 0.0, "prominencia_maxima": 0.0, "sin_cima_en_mdt": True})
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

    Cuenta como segura una cima cuya prominencia mínima garantizada llega al umbral.
    Se cuenta aparte como "dudosa" la que no llega con el mínimo pero podría llegar
    con el máximo (efecto del borde del terreno descargado).
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
            podria = g["prominencia_maxima"].isna() | (g["prominencia_maxima"] >= u)
            dudoso = (~seguro) & g["prominencia_es_minima"] & podria
            fila[f"prom_{u}m"] = int(seguro.sum())
            fila[f"prom_{u}m_con_nombre"] = int((seguro & g["nombre"].notna()).sum())
            fila[f"prom_{u}m_dudosas"] = int(dudoso.sum())
        filas.append(fila)
    return pd.DataFrame(filas)
