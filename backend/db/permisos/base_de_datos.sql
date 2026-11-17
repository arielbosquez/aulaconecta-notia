-- NotIA · Permisos dentro de una base de datos (privilegios mínimos, RS-16 y RS-19)
--
-- Deja la base a la que se está conectado con notia_owner como dueño del
-- esquema y notia_app limitado a leer y escribir filas. Los dos roles ya deben
-- existir: los crea roles.sql.
--
-- Es SQL puro, sin comandos de psql, porque se ejecuta desde dos lugares:
--   * roles.sql lo incluye para la base de la aplicación (local y producción).
--   * backend/conftest.py lo ejecuta sobre la base de pruebas, para que las
--     pruebas corran con los mismos permisos que la aplicación real.
--
-- Lo ejecuta un administrador del servidor. Se puede volver a ejecutar sin
-- problemas. Sin triggers ni jobs: aquí solo hay permisos.

-- ---------------------------------------------------------------------------
-- 1. Nadie entra a la base por el solo hecho de existir en el servidor.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO notia_app', current_database());
END $$;

-- ---------------------------------------------------------------------------
-- 2. Esquema: notia_owner es el dueño; notia_app solo lo usa.
-- ---------------------------------------------------------------------------
ALTER SCHEMA public OWNER TO notia_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO notia_app;

-- ---------------------------------------------------------------------------
-- 3. Permisos de notia_app sobre lo que cree notia_owner con las migraciones.
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
-- 4. Bitácora de auditoría: solo inserción y lectura (RS-16).
--    La migración que crea la tabla ya quita UPDATE y DELETE a notia_app. Se
--    repite aquí porque el paso anterior los vuelve a conceder cuando el
--    script se ejecuta con la tabla ya creada.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.auditoria_registroauditoria') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON public.auditoria_registroauditoria FROM notia_app;
    END IF;
END $$;
