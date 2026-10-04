-- Pruebas de supabase/app_usuarios.sql. Cada bloque falla con un error si algo no cuadra.
\set ON_ERROR_STOP on
\set QUIET on

-- Dos cimas de ejemplo (como administrador)
insert into catalogo.cimas (id, osm_id, nombre, altitud_m, altitud_fuente, prominencia_m, categoria,
                            latitud, longitud, fuente, fecha_catalogo)
values ('11111111-1111-1111-1111-111111111111', 'node/276913145', 'Penyagolosa', 1813, 'prueba', 438,
        'principal', 40.22276, -0.349742, 'prueba', current_date),
       ('22222222-2222-2222-2222-222222222222', 'node/26864619', 'el Maigmó', 1296, 'prueba', 557,
        'principal', 38.5018761, -0.6312948, 'prueba', current_date);

-- Dos usuarios: Ana y Blas. El trigger debe crearles el perfil.
insert into auth.users (id, email) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'ana@example.com'),
  ('bbbbbbbb-0000-0000-0000-000000000002', 'blas@example.com');

do $$ begin
  assert (select count(*) from app.perfiles) = 2, 'no se crearon los perfiles';
  assert not (select bool_or(perfil_publico) from app.perfiles), 'los perfiles deben ser privados por defecto';
end $$;

-- ---------- Como Ana ----------
set role authenticated;
set request.jwt.claim.sub = 'aaaaaaaa-0000-0000-0000-000000000001';

-- Sin consentimiento de ubicación no se puede usar el GPS
do $$ begin
  perform app.registrar_ascension('11111111-1111-1111-1111-111111111111', current_date, 40.2228, -0.3497);
  raise exception 'debía fallar sin consentimiento';
exception when insufficient_privilege then null;
end $$;

insert into app.consentimientos (tipo, version_texto, aceptado) values
  ('terminos', '2026-10', true), ('privacidad', '2026-10', true), ('ubicacion', '2026-10', true);

-- Registro con GPS a ~20 m de la cumbre: verificada, y no se guarda la posición
do $$
declare a app.ascensiones;
begin
  a := app.registrar_ascension('11111111-1111-1111-1111-111111111111', current_date, 40.22294, -0.349742);
  assert a.verificada_gps, 'debía quedar verificada';
  assert a.distancia_a_cima_m between 15 and 25, 'distancia inesperada: ' || a.distancia_a_cima_m;
end $$;

-- Registro con GPS a 2 km: queda sin verificar
do $$
declare a app.ascensiones;
begin
  a := app.registrar_ascension('22222222-2222-2222-2222-222222222222', current_date - 3, 38.52, -0.6313);
  assert not a.verificada_gps, 'no debía verificarse a 2 km';
end $$;

-- Repetir el mismo día con mejor GPS mejora la verificación, sin duplicar
do $$
declare a app.ascensiones;
begin
  a := app.registrar_ascension('22222222-2222-2222-2222-222222222222', current_date - 3, 38.50190, -0.63129);
  assert a.verificada_gps, 'el segundo registro debía verificar';
  assert (select count(*) from app.ascensiones) = 2, 'no debía duplicar';
end $$;

-- No se puede marcar a mano una ascensión como verificada
do $$ begin
  update app.ascensiones set verificada_gps = true;
  raise exception 'debía fallar';
exception when insufficient_privilege then null;
end $$;

-- Inserción directa (sin GPS): permitida, queda sin verificar
insert into app.ascensiones (cima_id, fecha) values ('11111111-1111-1111-1111-111111111111', current_date - 30);

-- Ni hacerse pasar por otro usuario
do $$ begin
  insert into app.ascensiones (cima_id, fecha, usuario_id)
  values ('11111111-1111-1111-1111-111111111111', current_date - 1, 'bbbbbbbb-0000-0000-0000-000000000002');
  raise exception 'debía fallar';
exception when insufficient_privilege then null;
end $$;

-- Tracks: sin consentimiento 'tracks', prohibido
do $$ begin
  insert into app.tracks (recorrido) values ('LINESTRING(-0.36 40.20, -0.35 40.21, -0.3497 40.2228)');
  raise exception 'debía fallar sin consentimiento de tracks';
exception when insufficient_privilege then null;
end $$;

insert into app.consentimientos (tipo, version_texto, aceptado) values ('tracks', '2026-10', true);
insert into app.tracks (recorrido) values ('LINESTRING(-0.36 40.20, -0.35 40.21, -0.3497 40.2228)');

-- El track se guarda recortado ~200 m por cada extremo
do $$
declare l double precision;
begin
  select extensions_len into l from (select st_length(recorrido) as extensions_len from app.tracks) t;
  assert abs(l - (st_length('LINESTRING(-0.36 40.20, -0.35 40.21, -0.3497 40.2228)'::geography) - 400)) < 30,
         'recorte inesperado: ' || l;
  assert (select caduca_en from app.tracks) = (current_date + interval '2 years')::date, 'caducidad';
end $$;

do $$
declare e record;
begin
  select * into e from app.mis_estadisticas;
  assert e.cimas_distintas = 2 and e.ascensiones = 3 and e.cimas_verificadas = 2, 'estadísticas';
  assert e.altitud_maxima_m = 1813, 'altitud máxima';
end $$;

-- Exportación con todos sus datos
do $$
declare j jsonb := app.exportar_mis_datos();
begin
  assert j->'cuenta'->>'email' = 'ana@example.com', 'export: cuenta';
  assert jsonb_array_length(j->'ascensiones') = 3, 'export: ascensiones';
  assert jsonb_array_length(j->'tracks') = 1, 'export: tracks';
  assert jsonb_array_length(j->'consentimientos') = 4, 'export: consentimientos';
end $$;

-- Los consentimientos no se pueden reescribir
do $$ begin
  update app.consentimientos set aceptado = true where tipo = 'tracks';
  raise exception 'debía fallar';
exception when insufficient_privilege then null;
end $$;

-- ---------- Como Blas ----------
set request.jwt.claim.sub = 'bbbbbbbb-0000-0000-0000-000000000002';
do $$ begin
  assert (select count(*) from app.ascensiones) = 0, 'Blas no debe ver las ascensiones privadas de Ana';
  assert (select count(*) from app.tracks) = 0, 'Blas no debe ver tracks ajenos';
  assert (select count(*) from app.perfiles) = 1, 'Blas solo debe ver su perfil';
  assert (select count(*) from app.consentimientos) = 0, 'Blas no debe ver consentimientos ajenos';
end $$;

-- ---------- Ana hace público su perfil y una ascensión ----------
set request.jwt.claim.sub = 'aaaaaaaa-0000-0000-0000-000000000001';
update app.perfiles set perfil_publico = true, alias = 'ana_monte';
update app.ascensiones set visibilidad = 'publica' where cima_id = '22222222-2222-2222-2222-222222222222';

set request.jwt.claim.sub = 'bbbbbbbb-0000-0000-0000-000000000002';
do $$ begin
  assert (select count(*) from app.ascensiones) = 1, 'Blas debe ver solo la ascensión pública de Ana';
  assert (select cimas_distintas from app.ranking_publico where alias = 'ana_monte') = 1, 'ranking';
  -- Blas no puede editar el perfil de Ana (la política lo filtra: 0 filas)
  update app.perfiles set alias = 'pirata' where alias = 'ana_monte';
  assert exists (select 1 from app.perfiles where alias = 'ana_monte'), 'Blas modificó el perfil de Ana';
end $$;

-- Visitante sin sesión: sin acceso a nada de app
reset role;
set role anon;
do $$ begin
  perform 1 from app.ascensiones;
  raise exception 'anon no debía poder leer';
exception when insufficient_privilege then null;
end $$;

-- ---------- Ana retira el consentimiento de tracks y luego borra su cuenta ----------
reset role;
set role authenticated;
set request.jwt.claim.sub = 'aaaaaaaa-0000-0000-0000-000000000001';
insert into app.consentimientos (tipo, version_texto, aceptado) values ('tracks', '2026-10', false);
do $$ begin
  assert (select count(*) from app.tracks) = 0, 'al retirar el consentimiento se debían borrar los tracks';
end $$;

select app.borrar_mi_cuenta();
reset role;
do $$ begin
  assert not exists (select 1 from auth.users where email = 'ana@example.com'), 'cuenta no borrada';
  assert not exists (select 1 from app.ascensiones where usuario_id = 'aaaaaaaa-0000-0000-0000-000000000001'),
         'ascensiones no borradas';
  assert not exists (select 1 from app.consentimientos where usuario_id = 'aaaaaaaa-0000-0000-0000-000000000001'),
         'consentimientos no borrados';
  assert (select count(*) from catalogo.cimas) = 2, 'el catálogo no debe verse afectado';
end $$;

-- Purga de tracks caducados
insert into app.tracks (usuario_id, recorrido, caduca_en)
values ('bbbbbbbb-0000-0000-0000-000000000002', 'LINESTRING(-0.36 40.20, -0.35 40.21, -0.3497 40.2228)',
        current_date - 1);
do $$ begin
  assert app.purgar_tracks_caducados() = 1, 'purga';
end $$;

\echo 'Todas las pruebas SQL han pasado'
