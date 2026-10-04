-- Catálogo de cimas para Supabase (PostgreSQL + PostGIS).
--
-- Cómo usarlo:
--   1. En Supabase: SQL Editor > New query > pegar este archivo > Run.
--   2. Table Editor > esquema "catalogo" > tabla "cimas" > Insert > Import data from CSV >
--      elegir data/salida/fase4/cimas_ES-VC.csv.
--   3. Settings > API > Exposed schemas: añadir "catalogo" para que la app pueda leerla.
--
-- Licencia: el contenido de esta tabla es una base de datos derivada de OpenStreetMap
-- (ODbL 1.0) con datos del IGN (CC BY 4.0). Ver docs/LICENCIAS.md.
-- Los datos de usuarios van en otro esquema (p. ej. "app") y solo guardan cima_id.

create extension if not exists postgis;

create schema if not exists catalogo;

create table if not exists catalogo.cimas (
  id                    uuid primary key,             -- identificador propio y estable
  osm_id                text unique,                  -- nodo de OSM de origen (puede cambiar)
  nombre                text,
  nombre_es             text,
  nombre_ca             text,                          -- valenciano / catalán
  nombre_eu             text,
  nombre_gl             text,
  altitud_m             numeric(6, 1) not null,
  altitud_fuente        text not null,
  prominencia_m         numeric(6, 1) not null,
  prominencia_es_minima boolean not null default false,
  altitud_collado_m     numeric(6, 1),
  categoria             text not null check (categoria in ('principal', 'secundaria', 'emblematica')),
  latitud               double precision not null,
  longitud              double precision not null,
  ccaa_ine              text,
  ccaa                  text,
  provincia_ine         text,
  provincia             text,
  comarca               text,
  municipio_ine         text,
  municipio             text,
  fuente                text not null,
  fuente_prominencia    text,
  osm_version           integer,
  osm_fecha_edicion     timestamptz,
  fecha_catalogo        date not null,
  -- Punto para búsquedas por distancia ("cimas a menos de 10 km de mí")
  geom geography(Point, 4326)
    generated always as (st_setsrid(st_makepoint(longitud, latitud), 4326)::geography) stored
);

create index if not exists cimas_geom_idx on catalogo.cimas using gist (geom);
create index if not exists cimas_provincia_idx on catalogo.cimas (provincia_ine);
create index if not exists cimas_municipio_idx on catalogo.cimas (municipio_ine);

-- Lectura pública, sin escritura desde la app
alter table catalogo.cimas enable row level security;
drop policy if exists "Catálogo de lectura pública" on catalogo.cimas;
create policy "Catálogo de lectura pública" on catalogo.cimas
  for select to anon, authenticated using (true);

grant usage on schema catalogo to anon, authenticated;
grant select on catalogo.cimas to anon, authenticated;

-- Ejemplo: cimas a menos de 10 km de un punto
-- select nombre, altitud_m, prominencia_m,
--        round(st_distance(geom, st_makepoint(-0.35, 40.22)::geography)) as metros
-- from catalogo.cimas
-- where st_dwithin(geom, st_makepoint(-0.35, 40.22)::geography, 10000)
-- order by metros;
