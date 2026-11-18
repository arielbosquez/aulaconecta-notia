# NotIA · Instrucciones para Claude Code

NotIA es un sistema web de evaluaciones para el colegio AulaConecta en el que la pregunta solo se escucha: en pantalla aparecen las alternativas y un temporizador controlado por el servidor. Es el proyecto del ramo Desarrollo Seguro (CI3V64, INACAP), y se evalúa la seguridad del código, la trazabilidad (Azure Boards, GitHub, PR) y que la solución funcione.

Antes de trabajar, lee siempre:

- `docs/ARQUITECTURA.md`: especificación completa (modelo de datos, reglas, API, seguridad, privacidad, frontend, pruebas y CI/CD). Es la fuente de verdad.
- `docs/PLAN_DESARROLLO.md`: orden de los PR, sus ramas, sus commits y la tarea de Azure Boards de cada uno.

## Equipo

| Integrante | Rol |
| --- | --- |
| Ariel Bosquez | Scrum Master |
| Javiera Quintana | Security Champion |
| Jeremías Cancino | Desarrollador |

## Reglas obligatorias

1. **Código original.** No copies código de tutoriales, blogs, Stack Overflow, repositorios ni plantillas de internet. Puedes usar librerías instaladas con pip o npm, pero el código propio se escribe para este proyecto. Lo mismo para el frontend: nada de plantillas ni kits de UI; identidad visual propia y creativa (sección 14 de la arquitectura).
2. **Un PR a la vez, según el plan.** Trabaja solo el PR que te indiquen, en su rama, creada desde `main` actualizada, con los commits en el orden del plan. Nunca trabajes directamente en `main`.
3. **AB# en cada commit.** Cada mensaje de commit termina en `AB#<id>` de la tarea de Azure Boards del PR. Si no te dieron el número, pregúntalo antes del primer commit. Mensajes en español, en presente, un cambio por commit (ejemplo: `Agrega bloqueo por intentos fallidos AB#23`).
4. **Sin acciones remotas.** No hagas `push`, no abras PR y no cambies la configuración de GitHub sin permiso explícito.
5. **Al terminar cada PR:** ejecuta las pruebas y los analizadores de seguridad, corrige lo que falle, actualiza `docs/TRAZABILIDAD.md` cuando corresponda, muestra un resumen y detente.
6. **Pregunta antes de suponer.** Si algo es ambiguo o contradictorio, pregunta. No inventes requisitos.
7. **Nunca** escribas secretos, contraseñas, llaves ni datos reales de personas en el código, los commits ni los archivos de ejemplo. Los datos de demostración son ficticios y evidentes (por ejemplo, `alumno.demo@aulaconecta.cl`). No pidas que te peguen llaves en el chat.
8. **Idioma.** Interfaz, comentarios, mensajes de error y documentación en español de Chile. Modelos y campos del dominio en español; nombres técnicos del framework en inglés.
9. **Nada sensible en el navegador.** El texto de la pregunta en NotIA, la respuesta correcta, los puntajes, las notas y el tiempo restante oficial se deciden en el servidor. El JavaScript solo muestra lo que el servidor ya decidió. Prohibido `{@html}` en Svelte.
10. **Sin templates de Django.** Django solo expone la API REST; todas las pantallas son de Astro. `django.contrib.admin` no se usa en producción.
11. **Base de datos.** Se permiten funciones y procedimientos almacenados en PostgreSQL. Prohibido usar triggers y jobs programados en la base.
12. **Modelo de usuario.** `Usuario` es un modelo propio (`AUTH_USER_MODEL`) que existe desde la primera migración.
13. **README.** El `README.md` ya existe: amplíalo, no lo reemplaces.

## Stack

- Backend: Python 3.12, Django 5.2 LTS, Django REST Framework, simplejwt, psycopg 3, argon2-cffi, pyotp, cryptography, Pillow, django-storages, whitenoise y gunicorn. Dependencias fijadas con `pip-compile --generate-hashes`.
- Frontend: Astro estático con islas Svelte 5 y TypeScript estricto. Fuentes autoalojadas con `@fontsource`. Sin librerías de UI.
- Base de datos: PostgreSQL 16 o superior (Docker en local, Azure Database for PostgreSQL en producción).
- Nube: Azure App Service, Blob Storage privado, Key Vault y Azure AI Speech (voces es-CL).
- CI/CD: GitHub Actions con pruebas, ruff, Bandit, pip-audit, npm audit y gitleaks como compuertas.

## Estructura

```
aulaconecta-notia/
├── backend/         # Django: config/ y apps/ (core, cuentas, academico, evaluaciones, voz, rendicion, resultados, integridad, auditoria)
├── frontend/        # Astro + Svelte: src/pages, src/components, src/lib, src/styles
├── docs/            # ARQUITECTURA.md, PLAN_DESARROLLO.md, TRAZABILIDAD.md, PRIVACIDAD.md, diagramas/
├── .github/         # workflows de CI y despliegue, Dependabot, plantilla de PR
├── docker-compose.yml
├── CLAUDE.md
├── README.md
└── SECURITY.md
```

## Comandos

Estos comandos son los previstos; actualízalos aquí si cambian al implementar la Fase 0.

```powershell
# Base de datos local. --env-file es obligatorio: de backend/.env salen las contraseñas.
# El contenedor recibe solo las suyas (no las llaves de Django) y crea los roles con backend/db/roles.sql.
docker compose --env-file backend/.env up -d

# Backend (desde backend/)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements/dev.txt
# Las migraciones se ejecutan con el rol dueño del esquema (notia_owner)
$env:DB_ROL = 'owner'; python manage.py migrate; Remove-Item Env:DB_ROL
# La aplicación corre con el rol de privilegios mínimos (notia_app)
python manage.py runserver
pytest
# Pantallas en el navegador (Playwright): primero npm run build en frontend/
# y una vez python -m playwright install chromium
pytest -m e2e
ruff check .
bandit -r apps -ll
pip-audit

# Frontend (desde frontend/)
npm ci
npm run dev
npm run build
npm run lint
npx --no-install audit-ci --config audit-ci.jsonc
```

## Lo que no haces

Crear cuentas o recursos en Azure, configurar Azure DevOps o Azure Boards, cambiar la protección de ramas o los secretos de GitHub, hacer push o abrir PR sin permiso e invitar al docente. Cuando un PR necesite algo de esto, di exactamente qué falta y continúa con lo que no dependa de ello.
