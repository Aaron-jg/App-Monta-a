-- Tablas de usuarios para Supabase: perfiles, consentimientos, ascensiones y tracks.
--
-- Cómo usarlo (después de catalogo_cimas.sql):
--   1. SQL Editor > New query > pegar este archivo > Run.
--   2. Settings > API > Exposed schemas: añadir "app" (además de "catalogo").
--   3. Opcional: Database > Extensions > activar pg_cron y ejecutar el bloque del final
--      para borrar cada noche los tracks caducados.
--
-- Principios (ver docs/RGPD.md):
--   - Esquema "app" separado del catálogo: aquí solo se guarda cima_id, nunca columnas de OSM.
--   - Row Level Security en todas las tablas: cada usuario solo ve y toca lo suyo.
--   - Minimización: al registrar una cima con GPS se guarda la distancia a la cumbre, no la
--     posición. Los tracks solo con consentimiento expreso, recortados al principio y al
--     final (para no revelar el domicilio) y con fecha de caducidad.
--   - Derechos: app.exportar_mis_datos() (portabilidad) y app.borrar_mi_cuenta() (supresión).

create extension if not exists postgis;

create schema if not exists app;

-- ---------------------------------------------------------------------------
-- Ajustes
-- ---------------------------------------------------------------------------

-- Distancia máxima a la cumbre para dar una ascensión por verificada con GPS
create or replace function app.radio_verificacion_m() returns integer
language sql immutable as $$ select 100 $$;

-- Conservación de los tracks
create or replace function app.conservacion_tracks() returns interval
language sql immutable as $$ select interval '2 years' $$;

create or replace function app.tocar_actualizado_en() returns trigger
language plpgsql as $$
begin
  new.actualizado_en := now();
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- Perfiles: lo mínimo para mostrar al usuario en la app. Sin nombre real ni fecha de
-- nacimiento. El correo ya está en auth.users y no se duplica.
-- ---------------------------------------------------------------------------

create table if not exists app.perfiles (
  id                    uuid primary key references auth.users (id) on delete cascade,
  alias                 text not null unique check (alias ~ '^[A-Za-z0-9_.-]{3,30}$'),
  avatar_url            text,
  perfil_publico        boolean not null default false,   -- privado por defecto
  idioma                text not null default 'es' check (idioma in ('es', 'ca', 'eu', 'gl', 'en')),
  recorte_privacidad_m  integer not null default 200 check (recorte_privacidad_m between 0 and 2000),
  creado_en             timestamptz not null default now(),
  actualizado_en        timestamptz not null default now()
);

drop trigger if exists perfiles_actualizado_en on app.perfiles;
create trigger perfiles_actualizado_en before update on app.perfiles
  for each row execute function app.tocar_actualizado_en();

-- Al darse de alta en Supabase Auth se crea su perfil con un alias provisional
create or replace function app.crear_perfil() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into app.perfiles (id, alias)
  values (new.id, 'cimero_' || left(replace(new.id::text, '-', ''), 12))
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists crear_perfil_al_registrarse on auth.users;
create trigger crear_perfil_al_registrarse after insert on auth.users
  for each row execute function app.crear_perfil();

-- ---------------------------------------------------------------------------
-- Consentimientos: registro de solo añadir. Retirar un consentimiento es añadir una
-- fila con aceptado = false. Sirve como prueba ante la AEPD.
-- ---------------------------------------------------------------------------

create table if not exists app.consentimientos (
  id             bigint generated always as identity primary key,
  usuario_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  tipo           text not null check (tipo in ('terminos', 'privacidad', 'ubicacion', 'tracks', 'comunicaciones')),
  version_texto  text not null,           -- versión del texto legal que vio, p. ej. '2026-10'
  aceptado       boolean not null,
  registrado_en  timestamptz not null default now()
);

create index if not exists consentimientos_usuario_idx
  on app.consentimientos (usuario_id, tipo, registrado_en desc);

-- ¿Tiene el usuario actual este consentimiento en vigor? (el último registro manda)
create or replace function app.tiene_consentimiento(p_tipo text) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce((
    select c.aceptado from app.consentimientos c
    where c.usuario_id = auth.uid() and c.tipo = p_tipo
    order by c.registrado_en desc, c.id desc
    limit 1), false)
$$;

-- ---------------------------------------------------------------------------
-- Ascensiones: qué cima subió el usuario y cuándo.
-- ---------------------------------------------------------------------------

create table if not exists app.ascensiones (
  id                  uuid primary key default gen_random_uuid(),
  usuario_id          uuid not null default auth.uid() references auth.users (id) on delete cascade,
  cima_id             uuid not null references catalogo.cimas (id) on delete restrict,
  fecha               date not null default current_date
                      check (fecha between date '1900-01-01' and current_date + 1),
  verificada_gps      boolean not null default false,
  distancia_a_cima_m  integer check (distancia_a_cima_m >= 0),
  visibilidad         text not null default 'privada' check (visibilidad in ('privada', 'publica')),
  nota                text check (char_length(nota) <= 500),
  creado_en           timestamptz not null default now(),
  actualizado_en      timestamptz not null default now(),
  unique (usuario_id, cima_id, fecha)
);

create index if not exists ascensiones_usuario_idx on app.ascensiones (usuario_id, fecha desc);
create index if not exists ascensiones_cima_idx on app.ascensiones (cima_id);

drop trigger if exists ascensiones_actualizado_en on app.ascensiones;
create trigger ascensiones_actualizado_en before update on app.ascensiones
  for each row execute function app.tocar_actualizado_en();

-- Registrar una ascensión. Si se pasa la posición GPS (con consentimiento de ubicación),
-- se calcula la distancia a la cumbre y se marca como verificada si está a menos de
-- app.radio_verificacion_m(). La posición NO se guarda.
create or replace function app.registrar_ascension(
  p_cima_id     uuid,
  p_fecha       date default current_date,
  p_lat         double precision default null,
  p_lon         double precision default null,
  p_visibilidad text default 'privada',
  p_nota        text default null
) returns app.ascensiones
language plpgsql security definer set search_path = public, extensions as $$
declare
  v_usuario  uuid := auth.uid();
  v_dist     double precision;
  v_fila     app.ascensiones;
begin
  if v_usuario is null then
    raise exception 'Hay que iniciar sesión' using errcode = '42501';
  end if;
  if not exists (select 1 from catalogo.cimas where id = p_cima_id) then
    raise exception 'La cima % no existe en el catálogo', p_cima_id using errcode = '23503';
  end if;
  if p_lat is not null and p_lon is not null then
    if not app.tiene_consentimiento('ubicacion') then
      raise exception 'Falta el consentimiento de ubicación' using errcode = '42501';
    end if;
    select st_distance(c.geom, st_setsrid(st_makepoint(p_lon, p_lat), 4326)::geography)
      into v_dist
      from catalogo.cimas c where c.id = p_cima_id;
  end if;

  insert into app.ascensiones as a
    (usuario_id, cima_id, fecha, verificada_gps, distancia_a_cima_m, visibilidad, nota)
  values
    (v_usuario, p_cima_id, p_fecha, coalesce(v_dist <= app.radio_verificacion_m(), false),
     round(v_dist)::integer, p_visibilidad, p_nota)
  on conflict (usuario_id, cima_id, fecha) do update set
    -- Repetir el registro el mismo día solo puede mejorar la verificación
    verificada_gps     = a.verificada_gps or excluded.verificada_gps,
    distancia_a_cima_m = least(a.distancia_a_cima_m, excluded.distancia_a_cima_m),
    visibilidad        = excluded.visibilidad,
    nota               = coalesce(excluded.nota, a.nota)
  returning a.* into v_fila;
  return v_fila;
end $$;

-- ---------------------------------------------------------------------------
-- Tracks: recorrido GPS. Dato muy sensible: solo con consentimiento 'tracks',
-- recortado en los extremos y con caducidad.
-- ---------------------------------------------------------------------------

create table if not exists app.tracks (
  id              uuid primary key default gen_random_uuid(),
  usuario_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  ascension_id    uuid references app.ascensiones (id) on delete set null,
  recorrido       geography(LineString, 4326) not null,
  fecha           date not null default current_date,
  caduca_en       date not null default (current_date + app.conservacion_tracks())::date,
  creado_en       timestamptz not null default now()
);

create index if not exists tracks_usuario_idx on app.tracks (usuario_id, fecha desc);
create index if not exists tracks_caduca_idx on app.tracks (caduca_en);

-- Quita los primeros y últimos metros del recorrido (donde suele estar el domicilio
-- o el coche). Si el track es más corto que dos recortes, se rechaza.
create or replace function app.recortar_track() returns trigger
language plpgsql security definer set search_path = public, extensions as $$
declare
  v_recorte  integer;
  v_longitud double precision;
  v_frac     double precision;
begin
  select p.recorte_privacidad_m into v_recorte from app.perfiles p where p.id = new.usuario_id;
  v_recorte := coalesce(v_recorte, 200);
  if v_recorte = 0 then
    return new;
  end if;
  v_longitud := st_length(new.recorrido);
  if v_longitud <= 2 * v_recorte then
    raise exception 'Track demasiado corto para recortar % m en cada extremo', v_recorte
      using errcode = '22023';
  end if;
  v_frac := v_recorte / v_longitud;
  new.recorrido := st_linesubstring(new.recorrido::geometry, v_frac, 1 - v_frac)::geography;
  return new;
end $$;

drop trigger if exists tracks_recortar on app.tracks;
create trigger tracks_recortar before insert on app.tracks
  for each row execute function app.recortar_track();

-- Si el usuario retira el consentimiento de tracks, se borran sus tracks
create or replace function app.aplicar_retirada_consentimiento() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.tipo = 'tracks' and not new.aceptado then
    delete from app.tracks where usuario_id = new.usuario_id;
  end if;
  return new;
end $$;

drop trigger if exists consentimientos_retirada on app.consentimientos;
create trigger consentimientos_retirada after insert on app.consentimientos
  for each row execute function app.aplicar_retirada_consentimiento();

-- Borrado de tracks caducados (llamar a diario con pg_cron, ver el final)
create or replace function app.purgar_tracks_caducados() returns integer
language plpgsql security definer set search_path = '' as $$
declare v_n integer;
begin
  delete from app.tracks where caduca_en < current_date;
  get diagnostics v_n = row_count;
  return v_n;
end $$;

-- ---------------------------------------------------------------------------
-- Vistas para la app
-- ---------------------------------------------------------------------------

-- Estadísticas del usuario actual
create or replace view app.mis_estadisticas with (security_invoker = true) as
select
  count(distinct a.cima_id)                                          as cimas_distintas,
  count(*)                                                           as ascensiones,
  count(distinct a.cima_id) filter (where c.categoria = 'principal') as cimas_principales,
  count(distinct a.cima_id) filter (where a.verificada_gps)          as cimas_verificadas,
  max(c.altitud_m)                                                   as altitud_maxima_m,
  max(a.fecha)                                                       as ultima_ascension
from app.ascensiones a
join catalogo.cimas c on c.id = a.cima_id
where a.usuario_id = auth.uid();

-- Clasificación pública: solo usuarios con perfil público y ascensiones públicas
create or replace view app.ranking_publico with (security_invoker = true) as
select p.alias, p.avatar_url,
       count(distinct a.cima_id) as cimas_distintas,
       count(distinct a.cima_id) filter (where a.verificada_gps) as cimas_verificadas
from app.ascensiones a
join app.perfiles p on p.id = a.usuario_id
where p.perfil_publico and a.visibilidad = 'publica'
group by p.alias, p.avatar_url;

-- ---------------------------------------------------------------------------
-- Derechos RGPD
-- ---------------------------------------------------------------------------

-- Portabilidad / acceso: todos los datos del usuario en un JSON
-- (security definer porque los usuarios no pueden leer auth.users; todo va filtrado por auth.uid())
create or replace function app.exportar_mis_datos() returns jsonb
language sql stable security definer set search_path = public, extensions as $$
  select jsonb_build_object(
    'generado_en', now(),
    'cuenta', (select jsonb_build_object('id', u.id, 'email', u.email)
               from auth.users u where u.id = auth.uid()),
    'perfil', (select to_jsonb(p) from app.perfiles p where p.id = auth.uid()),
    'consentimientos', coalesce((select jsonb_agg(to_jsonb(c) order by c.registrado_en)
                                 from app.consentimientos c where c.usuario_id = auth.uid()), '[]'),
    'ascensiones', coalesce((select jsonb_agg(to_jsonb(a) || jsonb_build_object('cima', ci.nombre)
                                              order by a.fecha)
                             from app.ascensiones a join catalogo.cimas ci on ci.id = a.cima_id
                             where a.usuario_id = auth.uid()), '[]'),
    'tracks', coalesce((select jsonb_agg(jsonb_build_object(
                          'id', t.id, 'fecha', t.fecha, 'caduca_en', t.caduca_en,
                          'recorrido', st_asgeojson(t.recorrido)::jsonb) order by t.fecha)
                        from app.tracks t where t.usuario_id = auth.uid()), '[]')
  )
$$;

-- Supresión: borra la cuenta y, en cascada, todos sus datos de este esquema.
-- (Las fotos de Supabase Storage, si se añaden, hay que borrarlas aparte.)
create or replace function app.borrar_mi_cuenta() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then
    raise exception 'Hay que iniciar sesión' using errcode = '42501';
  end if;
  delete from auth.users where id = auth.uid();
end $$;

-- ---------------------------------------------------------------------------
-- Seguridad: Row Level Security y permisos
-- ---------------------------------------------------------------------------

alter table app.perfiles        enable row level security;
alter table app.consentimientos enable row level security;
alter table app.ascensiones     enable row level security;
alter table app.tracks          enable row level security;

-- Perfiles: ver el propio y los públicos; editar solo el propio
drop policy if exists perfiles_ver on app.perfiles;
create policy perfiles_ver on app.perfiles for select to authenticated
  using (id = auth.uid() or perfil_publico);
drop policy if exists perfiles_editar on app.perfiles;
create policy perfiles_editar on app.perfiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

-- Consentimientos: ver y añadir los propios; nunca modificar ni borrar
drop policy if exists consentimientos_ver on app.consentimientos;
create policy consentimientos_ver on app.consentimientos for select to authenticated
  using (usuario_id = auth.uid());
drop policy if exists consentimientos_anadir on app.consentimientos;
create policy consentimientos_anadir on app.consentimientos for insert to authenticated
  with check (usuario_id = auth.uid());

-- Ascensiones: las propias siempre; las de otros solo si son públicas y su perfil también
drop policy if exists ascensiones_ver on app.ascensiones;
create policy ascensiones_ver on app.ascensiones for select to authenticated
  using (usuario_id = auth.uid()
         or (visibilidad = 'publica'
             and exists (select 1 from app.perfiles p where p.id = usuario_id and p.perfil_publico)));
drop policy if exists ascensiones_anadir on app.ascensiones;
create policy ascensiones_anadir on app.ascensiones for insert to authenticated
  with check (usuario_id = auth.uid());
drop policy if exists ascensiones_editar on app.ascensiones;
create policy ascensiones_editar on app.ascensiones for update to authenticated
  using (usuario_id = auth.uid()) with check (usuario_id = auth.uid());
drop policy if exists ascensiones_borrar on app.ascensiones;
create policy ascensiones_borrar on app.ascensiones for delete to authenticated
  using (usuario_id = auth.uid());

-- Tracks: solo los propios, y para añadir hace falta el consentimiento en vigor
drop policy if exists tracks_ver on app.tracks;
create policy tracks_ver on app.tracks for select to authenticated
  using (usuario_id = auth.uid());
drop policy if exists tracks_anadir on app.tracks;
create policy tracks_anadir on app.tracks for insert to authenticated
  with check (usuario_id = auth.uid() and app.tiene_consentimiento('tracks'));
drop policy if exists tracks_borrar on app.tracks;
create policy tracks_borrar on app.tracks for delete to authenticated
  using (usuario_id = auth.uid());

-- Permisos: nada para visitantes sin sesión (anon). Para usuarios con sesión, solo las
-- columnas que tiene sentido que escriban (la verificación GPS solo la pone el servidor).
revoke all on all tables in schema app from anon, authenticated;
revoke all on all functions in schema app from public, anon, authenticated;
grant usage on schema app to authenticated;

grant select on app.perfiles to authenticated;
grant update (alias, avatar_url, perfil_publico, idioma, recorte_privacidad_m) on app.perfiles to authenticated;

grant select on app.consentimientos to authenticated;
grant insert (tipo, version_texto, aceptado) on app.consentimientos to authenticated;

grant select, delete on app.ascensiones to authenticated;
grant insert (cima_id, fecha, visibilidad, nota) on app.ascensiones to authenticated;
grant update (fecha, visibilidad, nota) on app.ascensiones to authenticated;

grant select, delete on app.tracks to authenticated;
grant insert (ascension_id, recorrido, fecha) on app.tracks to authenticated;

grant select on app.mis_estadisticas, app.ranking_publico to authenticated;

grant execute on function app.tiene_consentimiento(text) to authenticated;
grant execute on function app.registrar_ascension(uuid, date, double precision, double precision, text, text) to authenticated;
grant execute on function app.exportar_mis_datos() to authenticated;
grant execute on function app.borrar_mi_cuenta() to authenticated;
grant execute on function app.radio_verificacion_m(), app.conservacion_tracks() to authenticated;

-- ---------------------------------------------------------------------------
-- Opcional: borrado nocturno de tracks caducados (requiere la extensión pg_cron)
-- ---------------------------------------------------------------------------
-- select cron.schedule('purgar-tracks-caducados', '15 3 * * *',
--                      $$ select app.purgar_tracks_caducados() $$);
