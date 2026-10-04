# CLAUDE.md — App Montaña: catálogo de cimas

Contexto del proyecto para Claude y para cualquier persona que trabaje en el repositorio.
Actualizar este archivo al cerrar cada fase.

## Qué es el proyecto

App móvil (iOS y Android) para que senderistas, corredores de trail y montañeros
registren las cimas que han subido.

- Mercado final: España. Piloto: Comunitat Valenciana (ISO 3166-2 `ES-VC`).
- El responsable del proyecto es estudiante de Digital Business, no programador:
  explicar las cosas de forma aplicada, sin jerga innecesaria y en español de España.
- El proyecto puede convertirse en negocio: las decisiones técnicas deben pensar en
  uso comercial y en escalar a toda España.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| App | FlutterFlow (no-code), iOS y Android |
| Base de datos | Supabase (PostgreSQL + PostGIS), proyecto alojado en región UE |
| Criterio de "montaña" | Prominencia topográfica mínima, no altitud |
| Umbral de prominencia | Pendiente: se decidirá comparando cuántas cimas salen con 30, 50 y 100 m |
| Cimas emblemáticas | Lista manual añadida después para las que no lleguen al umbral |
| Fuente base | OpenStreetMap (`natural=peak`) |
| Validación de nombres y altitudes | IGN/CNIG e Institut Cartogràfic Valencià (ICV) |
| Cálculo de prominencia | Modelo digital de elevaciones del CNIG (LiDAR) |
| Lenguaje de los scripts | Python 3.11 |

## Plan de trabajo por fases

Ir fase a fase. Al terminar cada una, enseñar resultados y preguntar antes de seguir.

1. **Descarga y diagnóstico OSM** — picos `natural=peak` dentro de
   `area["ISO3166-2"="ES-VC"]` vía Overpass. Diagnóstico: total, con nombre,
   con altitud, duplicados, reparto por provincia.
2. **Modelo de elevaciones** — elegir MDT05, MDT25 u otro y obtenerlo. Si una descarga
   del CNIG no se puede automatizar, indicar qué archivos bajar a mano y dónde guardarlos.
3. **Prominencia** — calcularla para cada pico y tabla comparativa por umbrales (30/50/100 m).
4. **Catálogo final** — CSV y GeoJSON con: id, nombre, nombre en valenciano, altitud,
   prominencia, latitud, longitud, provincia, comarca, municipio. Importable en Supabase.

### Estado

| Fase | Estado | Notas |
|---|---|---|
| 1 | Código listo, **pendiente de ejecutar** | La red del entorno en la nube bloquea `overpass-api.de` (ver "Entorno") |
| 2 | No iniciada | |
| 3 | No iniciada | |
| 4 | No iniciada | |

## Criterios de calidad

- Datos verificables y con su fuente indicada (cada registro guarda su origen).
- Sin cimas duplicadas.
- Respetar licencias (ODbL en OSM, CC BY 4.0 en IGN/CNIG) y documentar la atribución
  (ver `docs/LICENCIAS.md`).
- Código organizado y reutilizable: la región es un parámetro, no algo fijo en el código,
  para ampliar después al resto de España.

## Contexto de negocio

### Licencias y atribución
- Detalle completo en `docs/LICENCIAS.md`. Resumen:
  - **OpenStreetMap — ODbL 1.0.** Atribución obligatoria "© colaboradores de OpenStreetMap".
    Una base de datos derivada que se distribuya o se use públicamente debe ofrecerse
    con la misma licencia ODbL (*share-alike*).
  - **IGN/CNIG — CC BY 4.0.** Atribución obligatoria, p. ej. "Contiene información
    derivada del MDT05 © Instituto Geográfico Nacional (CNIG)".
  - **ICV — CC BY 4.0.** Atribución "© Institut Cartogràfic Valencià, Generalitat".
- La atribución debe verse dentro de la app (pantalla "Acerca de / Fuentes de datos").

### Separación de datos OSM y datos propios
- Las tablas derivadas de OSM (catálogo de cimas) van en un **esquema separado**
  (p. ej. `catalogo`) de las tablas con datos de usuarios (p. ej. esquema `app`).
- Las tablas de usuarios **solo referencian** la cima por su identificador; no copian
  columnas de OSM. Así el catálogo es la "base de datos derivada" sujeta a ODbL y los
  datos de usuarios quedan como obra independiente (*collective database*).
- Los datos que añadamos nosotros a mano (lista de cimas emblemáticas, correcciones)
  se guardan con su propio campo `fuente` para saber siempre de dónde viene cada dato.

### Escalabilidad (toda España desde el principio)
- Identificador propio estable de cada cima (no depender solo del id de OSM, que puede
  cambiar si alguien borra y recrea el nodo); guardar `osm_id` como columna aparte.
- Columnas de comunidad autónoma, provincia, comarca y municipio con códigos oficiales
  (INE) además del nombre.
- Columnas de nombre multilingüe: `nombre`, `nombre_es`, `nombre_ca` (valenciano/catalán),
  `nombre_eu`, `nombre_gl`, para cubrir todas las lenguas cooficiales.
- Geometría en PostGIS como `geography(Point, 4326)` con índice espacial.
- Coordenadas de cálculo en ETRS89 (EPSG:4258/25830-25831) cuando se trabaje con el MDT.

### RGPD
- Proyecto Supabase en región de la UE (p. ej. Frankfurt `eu-central-1` o París).
- Las ubicaciones GPS, tracks y registros de cimas de un usuario son **datos personales**
  (revelan hábitos y domicilio aproximado): consentimiento explícito, minimización
  (guardar solo lo necesario), plazo de conservación, derecho de borrado y exportación.
- Row Level Security (RLS) en Supabase activada en todas las tablas de usuario.
- Nada de datos de usuarios en el repositorio ni en los archivos de `data/`.

## Estructura del repositorio

```
CLAUDE.md                 Este archivo
docs/LICENCIAS.md         Licencias y atribución de cada fuente
requirements.txt          Dependencias de Python
src/cimas/regiones.py     Definición de regiones (piloto ES-VC; ampliable a España)
src/cimas/osm.py          Descarga de picos vía Overpass y limpieza básica
src/cimas/diagnostico.py  Métricas de calidad (nombres, altitud, duplicados, provincias)
scripts/fase1_osm.py      Ejecuta la fase 1 y genera el informe
tests/                    Pruebas automáticas (sin red)
data/raw/                 Descargas originales (no se versionan)
data/salida/              Resultados generados
```

## Cómo ejecutar

```bash
pip install -r requirements.txt
python scripts/fase1_osm.py --region ES-VC   # descarga + diagnóstico
python -m pytest tests                        # pruebas
```

## Entorno

- En la sesión en la nube actual, la red solo permite gestores de paquetes (pypi, npm…).
  `overpass-api.de`, `download.geofabrik.de` y `centrodedescargas.cnig.es` están
  bloqueados. Para ejecutar las fases hay que añadir esos dominios en
  *Network access* del entorno, o ejecutar los scripts en un ordenador local.

## Convenciones

- Código y comentarios en español; nombres de funciones en español sin tildes.
- Las descargas brutas se guardan en `data/raw/` con fecha, para poder reproducir resultados.
- No incluir identificadores de modelo de IA en commits ni en archivos del repositorio.
