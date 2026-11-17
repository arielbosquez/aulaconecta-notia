# NotIA · Trazabilidad

Tabla requisito → caso de uso → prueba automatizada → evidencia. Los requisitos de seguridad (RS) son los de la sección 15.1 de `docs/ARQUITECTURA.md` y los casos de uso (CU), los de la sección 2.1. Se actualiza en cada PR que agrega o cambia la verificación de un requisito.

## Cómo leer la tabla

- **Caso de uso:** el CU que el requisito protege. "Transversal" significa que aplica a todas las respuestas del sistema y no a un caso de uso en particular.
- **Prueba automatizada:** archivo de pruebas y nombre de las pruebas. Las rutas del backend son relativas a `backend/`; las del frontend, a `frontend/`.
- **Evidencia:** el PR y la tarea de Azure Boards donde quedó, y cómo reproducirla.
- **Estado:** *Cubierto* (el requisito está implementado y probado), *Parcial* (falta una parte, indicada en la fila) o *Pendiente* (aún no se implementa).

Cómo reproducir la evidencia en local:

```powershell
# Backend (desde backend/)
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
| RS-18 | Errores genéricos sin trazas | Transversal | `apps/core/tests/test_errores.py`: `test_error_forzado_responde_generico_y_sin_traza`, `test_error_de_vista_de_django_tambien_es_generico`, `test_los_errores_no_repiten_el_mensaje_de_la_excepcion`, `test_error_de_negocio_muestra_su_codigo_y_mensaje`, `test_validacion_indica_los_campos_sin_exponer_nada_mas`, `test_json_mal_formado_es_solicitud_invalida`, `test_rechazo_csrf_responde_json_generico`, `test_el_proyecto_real_responde_json_en_rutas_inexistentes`, `test_debug_esta_apagado_fuera_de_desarrollo`. `apps/core/tests/test_registros.py` (registros en JSON con contraseñas, tokens, cookies y respuestas enmascarados, sección 12.8). | PR 0.2 (AB#28): `apps/core/errores.py` y `apps/core/registros.py`. | **Cubierto.** |
| RS-19 | Base de datos con usuario de privilegios mínimos y TLS | Transversal | `apps/core/tests/test_roles_sql.py`: `test_ningun_rol_tiene_privilegios_de_administracion`, `test_notia_app_solo_recibe_permisos_sobre_filas`, `test_la_bitacora_queda_sin_update_ni_delete`, `test_sin_triggers_ni_jobs_en_la_base`, `test_docker_compose_solo_escucha_en_local_y_crea_los_roles`. `apps/core/tests/test_entorno.py`: `test_produccion_exige_conexion_cifrada_a_la_base`. | PR 0.2 (AB#28): `backend/db/roles.sql`, `docker-compose.yml` y `DB_SSLMODE` restringido en `config/settings/prod.py`. Verificación manual del 16-11-2026 en PostgreSQL 17 local (ver el registro de ejecuciones): `roles.sql` aplicado, migraciones con `notia_owner` y `CREATE TABLE` y `DROP TABLE` rechazados para `notia_app`. | **Parcial.** Los privilegios mínimos ya se comprobaron a mano contra PostgreSQL real, pero las pruebas automatizadas de `roles.sql` siguen siendo una revisión estática del archivo. Falta la prueba automatizada contra la base de que `notia_app` no puede crear ni borrar objetos, y la de que no puede hacer UPDATE o DELETE en la bitácora, cuya tabla aún no existe (PR 1.1, junto con RS-16). La conexión con TLS obligatorio se comprueba en Azure (Fase 5); en local se usa `DB_SSLMODE=prefer`. |

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
| RS-16 | Bitácora de auditoría de solo inserción | CU-16 | Pendiente |
| RS-17 | Minimización de datos y consentimiento de apoderados | CU-01, CU-15 | Pendiente |
| RS-20 | Exportación CSV protegida contra inyección de fórmulas | CU-13 | Pendiente |

## Registro de ejecuciones

| Fecha | PR | Resultado |
|---|---|---|
| 16-11-2026 | 0.2 (AB#28) | Ejecución local: `pytest` 95 pruebas aprobadas; `npm run test:scripts` 10 aprobadas; `ruff`, `bandit -r apps -ll`, `pip-audit` y `npm audit --audit-level=high` sin hallazgos. No se ejecutó contra PostgreSQL: ninguna de estas pruebas usa la base de datos y `backend/db/roles.sql` aún no se ha corrido en un servidor real. |
| 16-11-2026 | 0.2 (AB#28) | Ejecución manual contra PostgreSQL real (contenedor local `postgres:17.12-alpine`, levantado con `docker compose --env-file backend/.env up -d`, publicado solo en `127.0.0.1:5432`). (1) `backend/db/roles.sql` se aplicó completo al crear el volumen: creó `notia_owner`, `notia_app` y la base `notia`, y dejó los permisos sin errores. (2) `migrate` con `DB_ROL=owner` (rol `notia_owner`) aplicó las 15 migraciones de `contenttypes`, `auth` y `cuentas`. (3) `runserver` arrancó con el rol `notia_app`, sin errores en `check`, y respondió solicitudes. (4) Conectado como `notia_app`, la aplicación lee filas (`django_migrations`), pero `CREATE TABLE` y `DROP TABLE` sobre `cuentas_usuario` fueron rechazados por PostgreSQL por falta de privilegios. Después de esto, `pytest` (95 aprobadas), `ruff` y `bandit -r apps -ll` siguieron sin hallazgos. Es una comprobación manual: no queda como prueba automatizada (pendiente para el PR 1.1). |
| 16-11-2026 | 0.3 (AB#29) | Simulación local de los tres trabajos de `.github/workflows/ci.yml` en contenedores Linux, sin GitHub Actions. Backend (`python:3.12` con un PostgreSQL 17 desechable y los valores de prueba del workflow): instalación con `--require-hashes`, `ruff`, `bandit`, `pip-audit`, `roles.sql`, migraciones con `notia_owner`, `pytest` (107 pruebas aprobadas), cobertura sobre los mínimos (100% en `cuentas`, `rendicion` y `resultados`; 98% en el resto) y `check --deploy` sin advertencias. Frontend (`node:22`): `npm ci`, `npm audit`, ESLint, `astro check`, 10 pruebas de scripts y build, sin hallazgos. Secretos: gitleaks 8.30.1 sobre todo el historial, sin hallazgos tras exceptuar tres falsos positivos en `.gitleaks.toml`. Aún no se ejecuta en GitHub: falta el push. |
