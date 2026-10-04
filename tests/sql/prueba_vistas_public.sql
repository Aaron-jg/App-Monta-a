-- Pruebas de supabase/vistas_public.sql (se ejecutan tras prueba_app_usuarios.sql)
\set ON_ERROR_STOP on
\set QUIET on

insert into auth.users (id, email) values ('cccccccc-0000-0000-0000-000000000003', 'carla@example.com');

set role authenticated;
set request.jwt.claim.sub = 'cccccccc-0000-0000-0000-000000000003';

select public.dar_consentimiento('ubicacion', '2026-10', true);
select public.registrar_ascension('11111111-1111-1111-1111-111111111111', current_date, 40.22294, -0.349742);
update public.mi_perfil set alias = 'carla_cumbres';

do $$ begin
  assert (select count(*) from public.cimas) = 2, 'vista de cimas';
  assert (select count(*) from public.mis_ascensiones) = 1, 'Carla debe ver solo su ascensión';
  assert (select cima_nombre from public.mis_ascensiones) = 'Penyagolosa', 'nombre de la cima';
  assert (select alias from public.mi_perfil) = 'carla_cumbres', 'editar perfil por la vista';
  assert (select cimas_verificadas from public.mis_estadisticas) = 1, 'estadísticas por la vista';
end $$;

-- Por la vista tampoco se puede falsear la verificación
do $$ begin
  update public.mis_ascensiones set verificada_gps = true;
  raise exception 'debía fallar';
exception when insufficient_privilege or object_not_in_prerequisite_state or feature_not_supported then null;
end $$;

reset role;
set role anon;
do $$ begin
  assert (select count(*) from public.cimas) = 2, 'el catálogo es público';
  perform 1 from public.mis_ascensiones;
  raise exception 'anon no debía poder leer ascensiones';
exception when insufficient_privilege then null;
end $$;

\echo 'Pruebas de las vistas públicas: correctas'
