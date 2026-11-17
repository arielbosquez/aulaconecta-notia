<!-- Título del PR: el del plan con su tarea, por ejemplo "PR 1.2 · API de login AB#31". -->

## Qué cambia

<!-- Dos o tres líneas: qué hace este PR y por qué. -->

## Tarea de Azure Boards

AB#

## Cómo se probó

<!-- Marca lo que ejecutaste y agrega lo que probaste a mano en el navegador. -->

- [ ] `pytest` (desde `backend/`)
- [ ] `ruff check .`, `bandit -r apps -ll` y `pip-audit`
- [ ] `npm run lint`, `npm run check` y `npm run build` (desde `frontend/`)
- [ ] Prueba manual:

## Lista de verificación de seguridad

Marca cada punto que revisaste. Si alguno no aplica a este PR, márcalo y escribe "no aplica" al lado.

- [ ] No hay secretos, contraseñas, llaves ni datos reales de personas en el código, los commits ni los ejemplos.
- [ ] Cada endpoint nuevo o modificado declara sus permisos por rol y por objeto, y tiene una prueba de acceso denegado.
- [ ] Las entradas se validan en el servidor; el navegador no decide nada sensible (texto de la pregunta, respuesta correcta, puntajes, notas ni tiempo restante).
- [ ] No se usa `{@html}` en Svelte ni templates de Django.
- [ ] Los errores responden mensajes genéricos, sin trazas, y los registros no llevan contraseñas, tokens ni respuestas.
- [ ] Los cambios en la base de datos no usan triggers ni jobs, y `notia_app` conserva solo los privilegios mínimos.
- [ ] No se agregan datos personales nuevos (Ley 21.719); si se agregan, están justificados en `docs/PRIVACIDAD.md`.
- [ ] Las dependencias nuevas están fijadas (`pip-compile --generate-hashes` o `package-lock.json`) y pasan las auditorías.
- [ ] `docs/TRAZABILIDAD.md` está actualizado si cambió la verificación de un requisito de seguridad.

## Revisión

- [ ] Todos los commits terminan en el `AB#` de la tarea.
- [ ] El CI está en verde.
- [ ] Si toca login, permisos o datos personales, lo revisa la Security Champion.
