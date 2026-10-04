# Licencias y atribución de las fuentes de datos

Este documento recoge, para cada fuente, qué licencia tiene, qué obliga a hacer y qué
texto de atribución hay que mostrar. Revisarlo antes de publicar la app o de vender
cualquier producto basado en estos datos.

> Nota: esto es un resumen práctico, no asesoramiento jurídico. Antes de lanzar el
> negocio conviene que un abogado revise el uso de ODbL.

## Resumen

| Fuente | Qué usamos | Licencia | Atribución obligatoria | Share-alike |
|---|---|---|---|---|
| OpenStreetMap | Picos `natural=peak`, nombres, límites administrativos | ODbL 1.0 | Sí | **Sí**, para la base de datos derivada |
| IGN / CNIG | MDT05 / MDT25 (elevaciones), nomenclátor | CC BY 4.0 | Sí | No |
| Institut Cartogràfic Valencià | Toponimia y altitudes de validación | CC BY 4.0 | Sí | No |

## OpenStreetMap — ODbL 1.0

- Licencia: Open Database License 1.0 — https://opendatacommons.org/licenses/odbl/1-0/
- Guía oficial: https://osmfoundation.org/wiki/Licence/Attribution_Guidelines
- Texto de atribución: **"© colaboradores de OpenStreetMap"** con enlace a
  https://www.openstreetmap.org/copyright
- Qué implica para nosotros:
  - El catálogo de cimas es una **base de datos derivada** de OSM. Si se usa
    públicamente (y una app lo es), hay que ofrecer esa base de datos derivada con
    licencia ODbL a quien la pida (o publicarla).
  - Los datos de usuarios (cimas subidas, fechas, fotos, tracks) **no** se mezclan con
    el catálogo: viven en tablas aparte y solo apuntan al identificador de la cima.
    Así forman una base de datos independiente que no queda sujeta a ODbL.
  - Si añadimos correcciones a mano sobre datos de OSM, esas correcciones forman parte
    de la base derivada. Lo ideal es devolverlas a OSM.

## IGN / CNIG — CC BY 4.0

- Licencia: https://creativecommons.org/licenses/by/4.0/deed.es
- Condiciones del CNIG: https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf
- Texto de atribución (ejemplo): **"Contiene información derivada del MDT05
  © Instituto Geográfico Nacional"** (ajustar al producto usado: MDT05, MDT25, NGBE...).
- Uso comercial permitido. Solo obliga a citar la fuente e indicar si se ha modificado.

## Institut Cartogràfic Valencià — CC BY 4.0

- Licencia de los datos del ICV: CC BY 4.0.
- Texto de atribución: **"© Institut Cartogràfic Valencià. Generalitat"**.
- Uso comercial permitido con atribución.

## Dónde mostrar la atribución

- En la app: pantalla "Acerca de / Fuentes de datos" con los tres textos y sus enlaces.
- En los mapas: atribución visible de OSM (y del proveedor de teselas) en una esquina.
- En los archivos exportados (CSV/GeoJSON): campo `fuente` por registro y este documento
  junto al archivo.
