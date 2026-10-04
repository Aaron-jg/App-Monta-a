"""Métricas de calidad de la lista de picos: nombres, altitudes, duplicados y provincias."""

from __future__ import annotations

import unicodedata

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree


def normalizar_nombre(nombre: str | None) -> str | None:
    """Minúsculas, sin tildes y sin prefijos genéricos, para comparar nombres."""
    if not nombre or not isinstance(nombre, str):
        return None
    t = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    for prefijo in ("pico ", "pic ", "alto ", "alt ", "cerro ", "tossal ", "mola ", "penya ", "pena "):
        if t.startswith(prefijo):
            t = t[len(prefijo):]
    return " ".join(t.replace("'", " ").replace("-", " ").split()) or None


def coordenadas_metricas(df: pd.DataFrame, epsg: int) -> np.ndarray:
    """Pasa lat/lon a coordenadas UTM en metros para poder medir distancias."""
    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    x, y = tr.transform(df["lon"].to_numpy(), df["lat"].to_numpy())
    return np.column_stack([x, y])


def posibles_duplicados(
    df: pd.DataFrame, epsg: int, radio_cercania: float = 50, radio_mismo_nombre: float = 500
) -> pd.DataFrame:
    """Parejas de picos sospechosos de ser la misma cima.

    - "cercania": dos picos a menos de `radio_cercania` metros.
    - "mismo_nombre": mismo nombre normalizado a menos de `radio_mismo_nombre` metros.
    """
    if len(df) < 2:
        return pd.DataFrame()
    xy = coordenadas_metricas(df, epsg)
    arbol = cKDTree(xy)
    nombres = df["nombre"].map(normalizar_nombre).to_numpy()
    filas = []
    for i, j in sorted(arbol.query_pairs(radio_mismo_nombre)):
        dist = float(np.hypot(*(xy[i] - xy[j])))
        mismo = nombres[i] is not None and nombres[i] == nombres[j]
        if dist <= radio_cercania or mismo:
            a, b = df.iloc[i], df.iloc[j]
            filas.append({
                "motivo": "mismo_nombre" if mismo else "cercania",
                "distancia_m": round(dist, 1),
                "osm_id_a": a["osm_id"], "nombre_a": a["nombre"], "altitud_a": a["altitud_osm"],
                "osm_id_b": b["osm_id"], "nombre_b": b["nombre"], "altitud_b": b["altitud_osm"],
            })
    return pd.DataFrame(filas)


def resumen(df: pd.DataFrame, duplicados: pd.DataFrame) -> dict:
    total = len(df)
    con_nombre = df["nombre"].notna()
    con_alt = df["altitud_osm"].notna()
    pct = lambda n: round(100 * n / total, 1) if total else 0.0  # noqa: E731

    por_prov = (
        df.assign(provincia=df["provincia"].fillna("Sin provincia única"))
        .groupby("provincia")
        .agg(picos=("osm_id", "size"),
             con_nombre=("nombre", lambda s: s.notna().sum()),
             con_altitud=("altitud_osm", lambda s: s.notna().sum()),
             altitud_max=("altitud_osm", "max"))
        .reset_index()
    )
    return {
        "total_picos": total,
        "nodos": int((df["osm_id"].str.startswith("node/")).sum()),
        "vias": int((df["osm_id"].str.startswith("way/")).sum()),
        "con_nombre": int(con_nombre.sum()), "con_nombre_pct": pct(con_nombre.sum()),
        "con_nombre_ca": int(df["nombre_ca"].notna().sum()),
        "con_altitud": int(con_alt.sum()), "con_altitud_pct": pct(con_alt.sum()),
        "ele_no_interpretable": int((df["ele_texto"].notna() & ~con_alt).sum()),
        "con_nombre_y_altitud": int((con_nombre & con_alt).sum()),
        "ids_repetidos": int(df["osm_id"].duplicated().sum()),
        "parejas_cercania": int((duplicados.get("motivo") == "cercania").sum()) if len(duplicados) else 0,
        "parejas_mismo_nombre": int((duplicados.get("motivo") == "mismo_nombre").sum()) if len(duplicados) else 0,
        "por_provincia": por_prov.to_dict(orient="records"),
    }
