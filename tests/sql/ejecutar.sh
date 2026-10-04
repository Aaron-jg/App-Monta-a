#!/usr/bin/env bash
# Prueba los scripts de supabase/ en una base de datos PostgreSQL + PostGIS vacía.
# Uso: tests/sql/ejecutar.sh  (variables PG* estándar para la conexión)
set -euo pipefail
cd "$(dirname "$0")/../.."
BD="${BD_PRUEBAS:-prueba_cimas}"
psql -q -v ON_ERROR_STOP=1 -d postgres -c "drop database if exists $BD" -c "create database $BD"
for f in tests/sql/supabase_simulado.sql supabase/catalogo_cimas.sql supabase/app_usuarios.sql \
         supabase/app_usuarios.sql supabase/vistas_public.sql supabase/vistas_public.sql; do
  # app_usuarios.sql y vistas_public.sql se aplican dos veces: deben poder re-ejecutarse
  psql -q -v ON_ERROR_STOP=1 -d "$BD" -f "$f" > /dev/null
done
psql -q -v ON_ERROR_STOP=1 -d "$BD" -f tests/sql/prueba_app_usuarios.sql
psql -q -v ON_ERROR_STOP=1 -d "$BD" -f tests/sql/prueba_vistas_public.sql
