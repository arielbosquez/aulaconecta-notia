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

BEGIN;

-- Nadie entra a la base por el solo hecho de existir en el servidor.
REVOKE ALL ON DATABASE :"nombre_bd" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"nombre_bd" TO notia_app;

-- ---------------------------------------------------------------------------
-- 3. Esquema: notia_owner es el dueño; notia_app solo lo usa.
-- ---------------------------------------------------------------------------
ALTER SCHEMA public OWNER TO notia_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO notia_app;

-- ---------------------------------------------------------------------------
-- 4. Permisos de notia_app sobre lo que cree notia_owner con las migraciones.
--    Solo filas: SELECT, INSERT, UPDATE y DELETE. Sin TRUNCATE, REFERENCES ni
--    TRIGGER, y sin CREATE en el esquema.
-- ---------------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES FOR ROLE notia_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO notia_app;
ALTER DEFAULT PRIVILEGES FOR ROLE notia_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO notia_app;

-- Las funciones (por ejemplo fn_calcular_resultado) no quedan ejecutables
-- por cualquiera: solo por notia_app.
ALTER DEFAULT PRIVILEGES FOR ROLE notia_owner
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE notia_owner IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO notia_app;

-- Lo mismo para los objetos que ya existan (cuando el script se vuelve a ejecutar).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO notia_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO notia_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO notia_app;

-- ---------------------------------------------------------------------------
-- 5. Bitácora de auditoría: solo inserción y lectura (RS-16).
--    La tabla se crea en la Fase 1; su migración quita UPDATE y DELETE a
--    notia_app. Aquí se repite por si el script se ejecuta con la tabla ya creada.
-- ---------------------------------------------------------------------------
SELECT 'REVOKE UPDATE, DELETE, TRUNCATE ON public.auditoria_registroauditoria FROM notia_app'
WHERE to_regclass('public.auditoria_registroauditoria') IS NOT NULL \gexec

COMMIT;
