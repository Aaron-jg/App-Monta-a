-- Opcional: vistas en el esquema "public" para herramientas que solo leen "public"
-- (p. ej. FlutterFlow). Ejecutar después de catalogo_cimas.sql y app_usuarios.sql.
--
-- Son "ventanas" a las tablas reales: no copian datos y, al ser security_invoker, aplican
-- las mismas reglas de seguridad (RLS y permisos por columna) que las tablas de origen.
-- Las funciones (registrar_ascension, exportar_mis_datos, borrar_mi_cuenta) se llaman
-- igual a través de los envoltorios de abajo.

create or replace view public.cimas with (security_invoker = true) as
  select id, osm_id, nombre, nombre_es, nombre_ca, nombre_eu, nombre_gl, altitud_m,
         prominencia_m, categoria, latitud, longitud, provincia, comarca, municipio,
         municipio_ine, fuente
  from catalogo.cimas;

create or replace view public.mi_perfil with (security_invoker = true) as
  select * from app.perfiles where id = auth.uid();

create or replace view public.mis_ascensiones with (security_invoker = true) as
  select a.*, c.nombre as cima_nombre, c.altitud_m as cima_altitud_m, c.categoria as cima_categoria
  from app.ascensiones a join catalogo.cimas c on c.id = a.cima_id
  where a.usuario_id = auth.uid();

create or replace view public.mis_estadisticas with (security_invoker = true) as
  select * from app.mis_estadisticas;

create or replace view public.ranking_publico with (security_invoker = true) as
  select * from app.ranking_publico;

create or replace function public.registrar_ascension(
  p_cima_id uuid, p_fecha date default current_date,
  p_lat double precision default null, p_lon double precision default null,
  p_visibilidad text default 'privada', p_nota text default null
) returns app.ascensiones
language sql security invoker as $$
  select app.registrar_ascension(p_cima_id, p_fecha, p_lat, p_lon, p_visibilidad, p_nota)
$$;

create or replace function public.dar_consentimiento(p_tipo text, p_version text, p_aceptado boolean)
returns void language sql security invoker as $$
  insert into app.consentimientos (tipo, version_texto, aceptado) values (p_tipo, p_version, p_aceptado)
$$;

create or replace function public.exportar_mis_datos() returns jsonb
language sql security invoker as $$ select app.exportar_mis_datos() $$;

create or replace function public.borrar_mi_cuenta() returns void
language sql security invoker as $$ select app.borrar_mi_cuenta() $$;

revoke all on public.cimas, public.mi_perfil, public.mis_ascensiones, public.mis_estadisticas,
              public.ranking_publico from anon, authenticated;
grant select on public.cimas to anon, authenticated;
grant select on public.mi_perfil, public.mis_ascensiones, public.mis_estadisticas,
                public.ranking_publico to authenticated;
grant update (alias, avatar_url, perfil_publico, idioma, recorte_privacidad_m) on public.mi_perfil to authenticated;

revoke all on function public.registrar_ascension(uuid, date, double precision, double precision, text, text),
                       public.dar_consentimiento(text, text, boolean), public.exportar_mis_datos(),
                       public.borrar_mi_cuenta() from public, anon;
grant execute on function public.registrar_ascension(uuid, date, double precision, double precision, text, text),
                          public.dar_consentimiento(text, text, boolean), public.exportar_mis_datos(),
                          public.borrar_mi_cuenta() to authenticated;
