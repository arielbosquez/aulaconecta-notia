# NotIA · Trazabilidad

Tabla requisito → caso de uso → prueba automatizada → evidencia. Los requisitos de seguridad (RS) son los de la sección 15.1 de `docs/ARQUITECTURA.md` y los casos de uso (CU), los de la sección 2.1. Se actualiza en cada PR que agrega o cambia la verificación de un requisito.

## Cómo leer la tabla

- **Caso de uso:** el CU que el requisito protege. "Transversal" significa que aplica a todas las respuestas del sistema y no a un caso de uso en particular.
- **Prueba automatizada:** archivo de pruebas y nombre de las pruebas. Las rutas del backend son relativas a `backend/`; las del frontend, a `frontend/`.
- **Evidencia:** el PR y la tarea de Azure Boards donde quedó, y cómo reproducirla.
- **Estado:** *Cubierto* (el requisito está implementado y probado), *Parcial* (falta una parte, indicada en la fila) o *Pendiente* (aún no se implementa).

Cómo reproducir la evidencia en local:

```powershell
# Backend (desde backend/). Las pruebas con base necesitan PostgreSQL levantado:
#   docker compose --env-file backend/.env up -d   (desde la raíz)
pytest
ruff check .
bandit -r apps -ll
pip-audit

# Frontend (desde frontend/)
npm run test:scripts
npm run build
```

## Requisitos con verificación

| RS | Requisito | Caso de uso | Prueba automatizada | Evidencia | Estado |
|---|---|---|---|---|---|
| RS-13 | Cabeceras de seguridad y CSP sin `unsafe-inline` | Transversal | `apps/core/tests/test_cabeceras.py`: `test_agrega_todas_las_cabeceras`, `test_la_csp_es_la_de_la_arquitectura_y_sin_unsafe`, `test_incluye_los_hashes_del_build_de_astro`, `test_descarta_hashes_mal_formados_o_con_inyeccion`, `test_archivo_danado_deja_la_politica_sin_hashes`, `test_sin_archivo_la_politica_no_permite_codigo_en_linea`, `test_la_api_no_se_guarda_en_cache`, `test_hsts_solo_con_https_y_configurado`, `test_el_middleware_esta_instalado_y_va_primero`, `test_una_ruta_inexistente_tambien_lleva_las_cabeceras`. `scripts/hash-csp.test.mjs` (10 pruebas del cálculo de hashes). | PR 0.2 (AB#28): `apps/core/middleware.py` y `frontend/scripts/hash-csp.mjs`. | **Parcial.** Falta comprobar en el navegador que no haya errores de CSP, lo que requiere que Django sirva el build de Astro y exista una isla hidratada (Fase 1). |
| RS-14 | Secretos fuera del código (variables de entorno y Key Vault) y escaneo de secretos | Transversal | `apps/core/tests/test_entorno.py`: `test_variable_obligatoria_faltante_detiene_produccion`, `test_variable_obligatoria_vacia_cuenta_como_faltante`, `test_el_error_no_muestra_valores`, `test_validar_llaves_rechaza_llaves_debiles_o_repetidas`, `test_produccion_no_arranca_si_falta_una_variable` (una por cada variable obligatoria), `test_produccion_completa_pasa_check_deploy_sin_advertencias`. `apps/core/tests/test_generar_llaves.py`: `test_imprime_las_tres_llaves_y_son_validas`, `test_cada_ejecucion_entrega_llaves_distintas`, `test_los_avisos_no_repiten_las_llaves`, `test_no_escribe_archivos`. `apps/core/tests/test_roles_sql.py`: `test_las_contrasenas_vienen_del_entorno_y_no_estan_escritas`, `test_el_contenedor_recibe_solo_las_variables_que_necesita`, `test_docker_compose_no_trae_contrasenas_escritas`. | PR 0.2 (AB#28): `config/entorno.py`, `apps/core/llaves.py`, comando `generar_llaves`, `backend/.env.example` sin valores y `backend/.env` en `.gitignore`. PR 0.3 (AB#29): trabajo "Secretos" de `.github/workflows/ci.yml` (gitleaks sobre todo el historial, con `.gitleaks.toml`) y hook de gitleaks en `.pre-commit-config.yaml`. | **Parcial.** Falta ver el trabajo "Secretos" en verde en GitHub y agregarlo como check obligatorio del ruleset, y la lectura desde Key Vault en Azure (Fase 5). |
| RS-16 | Bitácora de auditoría de solo inserción | CU-16 (y todos los que registran eventos) | `apps/auditoria/tests/test_permisos_bd.py`, conectada como `notia_app` a PostgreSQL real: `test_la_prueba_se_conecta_con_el_rol_de_la_aplicacion`, `test_notia_app_solo_tiene_select_e_insert_sobre_la_bitacora`, `test_notia_app_inserta_y_lee`, `test_postgresql_rechaza_el_update`, `test_postgresql_rechaza_el_update_de_una_sola_columna`, `test_postgresql_rechaza_el_delete`, `test_postgresql_rechaza_el_truncate`, `test_postgresql_rechaza_un_insert_que_pisa_un_registro`, `test_postgresql_rechaza_tambien_al_orm_sin_las_protecciones_del_modelo`, `test_notia_app_no_puede_devolverse_los_permisos`. `apps/auditoria/tests/test_servicios.py`: el servicio `registrar`, el enmascarado de datos prohibidos en `detalle` (`test_el_detalle_enmascara_lo_que_la_bitacora_no_guarda`, `test_registrar_nunca_guarda_datos_prohibidos`) y las protecciones del modelo (`test_el_modelo_no_deja_modificar_un_registro`, `test_el_modelo_no_deja_borrar_un_registro`). | PR 1.1 (AB#32): `apps/auditoria/models.py`, `apps/auditoria/servicios.py` y la migración `0002_bitacora_solo_insercion`, que quita UPDATE, DELETE y TRUNCATE a `notia_app`. | **Parcial.** La bitácora de solo inserción está implementada y probada contra PostgreSQL. Falta que los casos de uso escriban en ella (desde el PR 1.2), la consulta del administrador (CU-16, PR 4.2) y el comando `purgar_bitacora` de la sección 12.9, que aún no tiene PR asignado en el plan. |
| RS-18 | Errores genéricos sin trazas | Transversal | `apps/core/tests/test_errores.py`: `test_error_forzado_responde_generico_y_sin_traza`, `test_error_de_vista_de_django_tambien_es_generico`, `test_los_errores_no_repiten_el_mensaje_de_la_excepcion`, `test_error_de_negocio_muestra_su_codigo_y_mensaje`, `test_validacion_indica_los_campos_sin_exponer_nada_mas`, `test_json_mal_formado_es_solicitud_invalida`, `test_rechazo_csrf_responde_json_generico`, `test_el_proyecto_real_responde_json_en_rutas_inexistentes`, `test_debug_esta_apagado_fuera_de_desarrollo`. `apps/core/tests/test_registros.py` (registros en JSON con contraseñas, tokens, cookies y respuestas enmascarados, sección 12.8). | PR 0.2 (AB#28): `apps/core/errores.py` y `apps/core/registros.py`. | **Cubierto.** |
| RS-19 | Base de datos con usuario de privilegios mínimos y TLS | Transversal | `apps/core/tests/test_roles_sql.py`: `test_ningun_rol_tiene_privilegios_de_administracion`, `test_notia_app_solo_recibe_permisos_sobre_filas`, `test_la_bitacora_queda_sin_update_ni_delete`, `test_sin_triggers_ni_jobs_en_la_base`, `test_docker_compose_solo_escucha_en_local_y_crea_los_roles`. `apps/core/tests/test_entorno.py`: `test_produccion_exige_conexion_cifrada_a_la_base`. | PR 0.2 (AB#28): `backend/db/roles.sql`, `docker-compose.yml` y `DB_SSLMODE` restringido en `config/settings/prod.py`. Verificación manual del 16-11-2026 en PostgreSQL 17 local (ver el registro de ejecuciones): `roles.sql` aplicado, migraciones con `notia_owner` y `CREATE TABLE` y `DROP TABLE` rechazados para `notia_app`. PR 1.1 (AB#32): `backend/db/permisos/base_de_datos.sql` (los permisos, separados de `roles.sql` para que la base de pruebas reciba los mismos) y `backend/conftest.py`, que hace correr todas las pruebas con base conectadas como `notia_app`. | **Parcial.** Los privilegios mínimos ya tienen prueba automatizada contra PostgreSQL real, en local y en el CI: `apps/core/tests/test_permisos_bd.py` (`test_las_pruebas_corren_con_el_rol_de_la_aplicacion`, `test_el_rol_de_la_aplicacion_no_tiene_atributos_de_administracion`, `test_el_rol_de_la_aplicacion_no_es_dueno_de_ninguna_tabla`, `test_la_aplicacion_lee_y_escribe_filas`, `test_la_aplicacion_no_puede_cambiar_la_estructura`, `test_la_aplicacion_no_puede_crear_bases_ni_roles`, `test_otros_roles_no_entran_por_el_esquema_publico`); la bitácora se cubre en RS-16. Solo falta la conexión con TLS obligatorio, que se comprueba en Azure (Fase 5); en local se usa `DB_SSLMODE=prefer`. |

## Requisitos pendientes

Estos requisitos aún no tienen implementación ni prueba. Cada fila pasa a la tabla anterior en el PR que la implemente.

| RS | Requisito | Caso de uso | Estado |
|---|---|---|---|
| RS-01 | Contraseñas con Argon2id y política de largo por rol | CU-01, CU-04 | Pendiente |
| RS-02 | Bloqueo tras 5 fallos y límite por IP | CU-01 | Pendiente |
| RS-03 | Mensajes de login sin enumeración de usuarios | CU-01 | Pendiente |
| RS-04 | JWT de corta duración en cookies httpOnly/Secure/SameSite, con rotación y lista negra | CU-01, CU-03 | Pendiente |
| RS-05 | CSRF exigido en métodos que modifican | Transversal | Pendiente |
| RS-06 | 2FA TOTP obligatorio para docente y admin, secreto cifrado | CU-02 | Pendiente |
| RS-07 | Autorización por rol y por objeto en cada endpoint | Transversal | Pendiente |
| RS-08 | Texto de la pregunta y respuesta correcta nunca enviados al alumno NotIA | CU-05 | Pendiente |
| RS-09 | Tiempo controlado solo por el servidor | CU-05, CU-06 | Pendiente |
| RS-10 | Validación de entradas en el servidor | Transversal | Pendiente |
| RS-11 | Imágenes validadas, reconvertidas y sin metadatos | CU-09 | Pendiente |
| RS-12 | SSML escapado y llamada a terceros con tiempo de espera y validación | CU-10 | Pendiente |
| RS-15 | Dependencias fijadas con hash y auditadas | Transversal | Parcial (PR 0.3, AB#29: el CI instala con `--require-hashes` y `npm ci`, y ejecuta `pip-audit` y `npm audit --audit-level=high`; Dependabot semanal. Falta verlo en verde en GitHub y agregarlo como check obligatorio del ruleset) |
| RS-17 | Minimización de datos y consentimiento de apoderados | CU-01, CU-15 | Pendiente |
| RS-20 | Exportación CSV protegida contra inyección de fórmulas | CU-13 | Pendiente |

## Registro de ejecuciones

| Fecha | PR | Resultado |
|---|---|---|
| 16-11-2026 | 0.2 (AB#28) | Ejecución local: `pytest` 95 pruebas aprobadas; `npm run test:scripts` 10 aprobadas; `ruff`, `bandit -r apps -ll`, `pip-audit` y `npm audit --audit-level=high` sin hallazgos. No se ejecutó contra PostgreSQL: ninguna de estas pruebas usa la base de datos y `backend/db/roles.sql` aún no se ha corrido en un servidor real. |
| 16-11-2026 | 0.2 (AB#28) | Ejecución manual contra PostgreSQL real (contenedor local `postgres:17.12-alpine`, levantado con `docker compose --env-file backend/.env up -d`, publicado solo en `127.0.0.1:5432`). (1) `backend/db/roles.sql` se aplicó completo al crear el volumen: creó `notia_owner`, `notia_app` y la base `notia`, y dejó los permisos sin errores. (2) `migrate` con `DB_ROL=owner` (rol `notia_owner`) aplicó las 15 migraciones de `contenttypes`, `auth` y `cuentas`. (3) `runserver` arrancó con el rol `notia_app`, sin errores en `check`, y respondió solicitudes. (4) Conectado como `notia_app`, la aplicación lee filas (`django_migrations`), pero `CREATE TABLE` y `DROP TABLE` sobre `cuentas_usuario` fueron rechazados por PostgreSQL por falta de privilegios. Después de esto, `pytest` (95 aprobadas), `ruff` y `bandit -r apps -ll` siguieron sin hallazgos. Es una comprobación manual: no queda como prueba automatizada (pendiente para el PR 1.1). |
| 16-11-2026 | 0.3 (AB#29) | Simulación local de los tres trabajos de `.github/workflows/ci.yml` en contenedores Linux, sin GitHub Actions. Backend (`python:3.12` con un PostgreSQL 17 desechable y los valores de prueba del workflow): instalación con `--require-hashes`, `ruff`, `bandit`, `pip-audit`, `roles.sql`, migraciones con `notia_owner`, `pytest` (107 pruebas aprobadas), cobertura sobre los mínimos (100% en `cuentas`, `rendicion` y `resultados`; 98% en el resto) y `check --deploy` sin advertencias. Frontend (`node:22`): `npm ci`, `npm audit`, ESLint, `astro check`, 10 pruebas de scripts y build, sin hallazgos. Secretos: gitleaks 8.30.1 sobre todo el historial, sin hallazgos tras exceptuar tres falsos positivos en `.gitleaks.toml`. Aún no se ejecuta en GitHub: falta el push. |
| 16-11-2026 | 1.1 (AB#32) | Ejecución local contra PostgreSQL 17 (contenedor de `docker compose`) y simulación del trabajo Backend del CI en `python:3.12` con un PostgreSQL desechable. En ambos, `pytest` crea la base `test_notia`, la migra con `notia_owner` y corre las 152 pruebas conectado como `notia_app`: PostgreSQL rechaza UPDATE, DELETE y TRUNCATE sobre `auditoria_registroauditoria`, y CREATE, DROP y ALTER sobre el esquema. Al quitar a propósito el REVOKE de la migración, 7 de las pruebas de la bitácora fallan, así que la prueba detecta el retroceso. Cobertura: 100% en `auditoria` y `cuentas`, 98% en el resto. `ruff`, `bandit -r apps -ll` y `pip-audit` sin hallazgos. En la base local de desarrollo, tras migrar, `has_table_privilege` confirma que `notia_app` solo tiene SELECT e INSERT sobre la bitácora. Aún no se ejecuta en GitHub: falta el push. |
