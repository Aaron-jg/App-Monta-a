"""Regiones de trabajo.

La región es un parámetro: para ampliar a otra comunidad autónoma basta con añadir
una entrada a REGIONES con su código ISO 3166-2 y sus provincias.
Los códigos INE de provincia sirven para enlazar después con datos oficiales.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Provincia:
    iso: str        # código ISO 3166-2, el que usa OSM en la etiqueta "ISO3166-2"
    ine: str        # código INE de provincia (2 dígitos)
    nombre: str


@dataclass(frozen=True)
class Region:
    iso: str
    nombre: str
    provincias: tuple[Provincia, ...]
    epsg_utm: int   # sistema de coordenadas métrico (ETRS89 / UTM) para medir distancias


REGIONES: dict[str, Region] = {
    "ES-VC": Region(
        iso="ES-VC",
        nombre="Comunitat Valenciana",
        provincias=(
            Provincia("ES-A", "03", "Alicante/Alacant"),
            Provincia("ES-CS", "12", "Castellón/Castelló"),
            Provincia("ES-V", "46", "Valencia/València"),
        ),
        epsg_utm=25830,
    ),
}


def obtener_region(iso: str) -> Region:
    try:
        return REGIONES[iso]
    except KeyError:
        disponibles = ", ".join(sorted(REGIONES))
        raise ValueError(f"Región {iso!r} no definida. Disponibles: {disponibles}") from None
