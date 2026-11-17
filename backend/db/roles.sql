-- NotIA · Roles y permisos de PostgreSQL (privilegios mínimos, RS-19)
--
-- Crea dos roles:
--   notia_owner  dueño de la base y del esquema. Se usa solo para migraciones
--                y para el comando manual de purga de la bitácora.
--   notia_app    el que usa la aplicación. Puede leer y escribir filas, pero
--                no puede crear, alterar ni borrar objetos.
--
-- Cómo se ejecuta:
--   * En local lo ejecuta docker compose al crear la base por primera vez.
--   * En producción lo ejecuta una persona, una sola vez, con el usuario
--     administrador del servidor:  psql -h <servidor> -U <admin> -d postgres -f roles.sql
--
-- Las contraseñas NO están en este archivo: psql las toma de las variables de
-- entorno DB_OWNER_PASSWORD y DB_PASSWORD. El nombre de la base viene de DB_NAME.
-- Requiere psql 15 o superior (por \getenv). Se puede volver a ejecutar sin
-- problemas: actualiza las contraseñas y repone los permisos.
--
-- Necesita el archivo permisos/base_de_datos.sql, que está junto a este script.
--
-- Sin triggers ni jobs: aquí solo hay roles y permisos.

\set ON_ERROR_STOP on

\getenv nombre_bd DB_NAME
\getenv clave_owner DB_OWNER_PASSWORD
\getenv clave_app DB_PASSWORD

\if :{?nombre_bd}
\else
  \set nombre_bd ''
\endif
\if :{?clave_owner}
\else
  \set clave_owner ''
\endif
\if :{?clave_app}
\else
  \set clave_app ''
\endif

SELECT :'nombre_bd' = '' OR :'clave_owner' = '' OR :'clave_app' = '' AS faltan_variables \gset
\if :faltan_variables
  \echo 'roles.sql: define DB_NAME, DB_OWNER_PASSWORD y DB_PASSWORD antes de ejecutar.'
  DO $$ BEGIN RAISE EXCEPTION 'Faltan variables de entorno para crear los roles de NotIA'; END $$;
\endif

SELECT :'clave_owner' = :'clave_app' AS claves_iguales \gset
\if :claves_iguales
  \echo 'roles.sql: DB_OWNER_PASSWORD y DB_PASSWORD deben ser distintas.'
  DO $$ BEGIN RAISE EXCEPTION 'Los dos roles de NotIA no pueden compartir contraseña'; END $$;
\endif

-- ---------------------------------------------------------------------------
-- 1. Roles. Ninguno es superusuario ni puede crear bases u otros roles.
-- ---------------------------------------------------------------------------
SELECT 'CREATE ROLE notia_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notia_owner') \gexec

SELECT 'CREATE ROLE notia_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notia_app') \gexec

ALTER ROLE notia_owner PASSWORD :'clave_owner';
ALTER ROLE notia_app PASSWORD :'clave_app';

-- ---------------------------------------------------------------------------
-- 2. Base de datos, propiedad de notia_owner.
-- ---------------------------------------------------------------------------
SELECT format('CREATE DATABASE %I OWNER notia_owner', :'nombre_bd')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'nombre_bd') \gexec

\connect :"nombre_bd"

-- ---------------------------------------------------------------------------
-- 3. Permisos dentro de la base: esquema, tablas, secuencias, funciones y
--    bitácora. Están en un archivo aparte, de SQL puro, porque la base de
--    pruebas recibe exactamente los mismos (ver backend/conftest.py).
-- ---------------------------------------------------------------------------
BEGIN;
\ir permisos/base_de_datos.sql
COMMIT;
