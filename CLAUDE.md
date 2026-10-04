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
| Umbral de prominencia | **30 m** (decidido el 2026-10-04). Categoría "principal" si ≥ 100 m |
| Cimas emblemáticas | Lista manual añadida después para las que no lleguen al umbral |
| Fuente base | OpenStreetMap (`natural=peak`) |
| Validación de nombres y altitudes | IGN/CNIG e Institut Cartogràfic Valencià (ICV) |
| Cálculo de prominencia | MDT25 del IGN/CNIG (LiDAR), descargado por el servicio WCS de la IDEE; MDT05 reservado para afinar casos concretos |
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
| 1 | **Hecha** (2026-10-04, vía GitHub Actions) | 3.616 picos; 87,6 % con nombre; 99,5 % con altitud; 16 parejas de posibles duplicados. Resultados en `data/salida/fase1/` |
| 2 | **Hecha** (2026-10-04, vía GitHub Actions) | MDT25, 455 teselas de 10 km. Altitud OSM vs MDT: mediana 1 m de diferencia, 98,1 % a ±10 m, 5 picos con más de 50 m. Informe en `data/salida/fase2/`; mosaico como archivo descargable de la ejecución |
| 3 | **Hecha** (2026-10-04, vía GitHub Actions) | Prominencia sobre MDT25 (inundación descendente con unión de regiones). Cimas distintas: 3.583. Con ≥30 m: 1.570; ≥50 m: 967; ≥100 m: 396. Solo 2 con prominencia acotada por el borde (ambas >100 m). Resultados en `data/salida/fase3/` |
| 4 | **Hecha** (2026-10-04, vía GitHub Actions) | 1.570 cimas (396 principales). 94 % con nombre, 100 % con municipio (INE) y comarca. Catálogo en `data/salida/fase4/`; esquema en `supabase/catalogo_cimas.sql` |

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
src/cimas/mdt.py          Descarga del MDT del IGN por teselas (WCS) y comparación con OSM
src/cimas/prominencia.py  Cálculo de la prominencia y tabla de umbrales
src/cimas/admin.py        Municipio y comarca de cada cima (límites de OSM)
src/cimas/catalogo.py     Catálogo final: filtro, duplicados, altitud, ids estables, GeoJSON
scripts/fase1_osm.py      Ejecuta la fase 1 y genera el informe
scripts/fase2_mdt.py      Ejecuta la fase 2 y genera el informe
scripts/fase3_prominencia.py  Ejecuta la fase 3 y genera el informe
scripts/fase4_catalogo.py Ejecuta la fase 4 y genera el catálogo
supabase/catalogo_cimas.sql   Tabla catalogo.cimas (PostGIS, RLS de lectura pública)
data/manual/cimas_emblematicas.csv  Cimas que entran aunque no lleguen al umbral
data/catalogo/            Registro de identificadores de cima (no borrar: da estabilidad a los id)
.github/workflows/        Ejecución de cada fase en GitHub Actions
tests/                    Pruebas automáticas (sin red)
data/raw/                 Descargas originales (no se versionan)
data/mdt/                 Teselas y mosaico del MDT (no se versionan)
data/salida/              Resultados generados
```

## Cómo ejecutar

```bash
pip install -r requirements.txt
python scripts/fase1_osm.py --region ES-VC   # descarga + diagnóstico
python scripts/fase2_mdt.py --region ES-VC   # MDT25 + comparación con OSM
python scripts/fase3_prominencia.py --region ES-VC   # prominencia + umbrales
python scripts/fase4_catalogo.py --region ES-VC --umbral 30   # catálogo final
python -m pytest tests                        # pruebas
```

## Entorno

- En la sesión en la nube actual, la red solo permite gestores de paquetes (pypi, npm…).
  `overpass-api.de`, `download.geofabrik.de` y `centrodedescargas.cnig.es` están
  bloqueados. Para ejecutar las fases hay que añadir esos dominios en
  *Network access* del entorno, o ejecutar los scripts en un ordenador local.
- Aunque se autoricen esos dominios, la conexión se corta antes de recibir respuesta
  (comprobado el 2026-10-04). Alternativa sin instalar nada: el flujo de GitHub Actions
  `.github/workflows/fase1_osm.yml` ejecuta la fase 1 en los servidores de GitHub y sube
  los resultados de `data/salida/fase1/` a la rama. Igual con `fase2_mdt.yml`.
- El centro de descargas del CNIG tampoco responde desde GitHub; el MDT se obtiene por el
  servicio WCS `https://servicios.idee.es/wcs-inspire/mdt` (coberturas `Elevacion25830_25`,
  `Elevacion25830_5`...; para Canarias, `Elevacion4083_*`). Devuelve metros enteros (int16).

## Pendiente tras la fase 4

- Rellenar `data/manual/cimas_emblematicas.csv` con las cimas conocidas por debajo de 30 m.
- Completar `nombre_ca` (solo el 30 % tiene `name:ca` en OSM) con la toponimia del ICV.
- Revisar las 25 cimas cuya altitud de OSM no cuadra con el MDT (se usa la del MDT).
- Al ampliar a otras comunidades: extraer también `name:eu` y `name:gl` en `osm.a_tabla`
  y comprobar el nivel administrativo de las comarcas en OSM (aquí `admin_level=7`).

## Convenciones

- Código y comentarios en español; nombres de funciones en español sin tildes.
- Las descargas brutas se guardan en `data/raw/` con fecha, para poder reproducir resultados.
- No incluir identificadores de modelo de IA en commits ni en archivos del repositorio.
