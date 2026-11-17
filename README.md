# NotIA · AulaConecta

Sistema web de evaluaciones para el colegio AulaConecta, desarrollado en el ramo Desarrollo Seguro.

NotIA es una prueba de alternativas en la que la pregunta solo se escucha. En pantalla aparecen únicamente las alternativas y un temporizador controlado por el servidor, de modo que la pregunta no se puede copiar y pegar en una herramienta de inteligencia artificial. Cada docente decide si un alumno rinde la prueba NotIA o la prueba normal, para que ningún estudiante quede excluido.

## Equipo

| Integrante | Rol | Responsabilidades |
| --- | --- | --- |
| Ariel Bosquez | Scrum Master | Planificación en Azure Boards, repositorio y despliegue |
| Javiera Quintana | Security Champion | Requerimientos de seguridad, modelo de amenazas y revisión de PR |
| Jeremías Cancino | Desarrollador | Backend, base de datos y servicio de voz |

Docente: Mario Yáñez Urrutia.



## Tecnología

- Backend: Django y Django REST Framework (Python)
- Frontend: Astro con componentes Svelte
- Base de datos: PostgreSQL
- Nube: Azure App Service, Azure Database for PostgreSQL, Key Vault y Azure AI Speech (voces es-CL)
- CI/CD: GitHub Actions

## Estado

En planificación.

## Instalación en Windows

Los comandos son de PowerShell. Sigue los pasos en orden la primera vez; después basta con levantar la base, el backend y el frontend.

### Requisitos previos

| Programa | Versión | Para qué |
| --- | --- | --- |
| [Git para Windows](https://git-scm.com/download/win) | Reciente | Clonar el repositorio y trabajar con ramas |
| [Python](https://www.python.org/downloads/windows/) | 3.12 | Backend (marca "Add python.exe to PATH" al instalar) |
| [Node.js](https://nodejs.org/) | 22 o superior | Frontend |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Reciente | PostgreSQL local |

Después de instalar Docker Desktop, ábrelo y espera a que diga que está corriendo. Si acabas de instalar algo, cierra la terminal y abre una nueva para que reconozca los comandos.

### 1. Clonar el repositorio

```powershell
git clone https://github.com/arielbosquez/aulaconecta-notia.git
cd aulaconecta-notia
```

### 2. Preparar el entorno de Python

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements/dev.txt
```

Si PowerShell no deja activar el entorno, ejecuta una sola vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite la activación. Con `--require-hashes`, pip rechaza cualquier paquete cuyo contenido no coincida con el hash registrado en el repositorio.

### 3. Crear tu archivo de variables de entorno

```powershell
Copy-Item .env.example .env
```

`backend/.env` es solo tuyo: está en `.gitignore` y nunca se sube. Ábrelo y completa:

- `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY` y `MFA_ENCRYPTION_KEY`, con los tres valores que entrega `python manage.py generar_llaves`.
- `POSTGRES_PASSWORD`, `DB_OWNER_PASSWORD` y `DB_PASSWORD`, con tres contraseñas distintas entre sí, de letras, números y guiones (sin `$` ni comillas). Puedes generar cada una con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

No compartas estos valores por chat, correo ni capturas de pantalla, y no los escribas en ningún otro archivo.

### 4. Levantar la base de datos y migrar

Sigue la sección [Base de datos local](#base-de-datos-local): levanta PostgreSQL con `docker compose` desde la raíz del repositorio y luego ejecuta las migraciones desde `backend/`.

### 5. Levantar el backend

```powershell
# Desde backend/, con el entorno virtual activado
python manage.py runserver
```

La API queda en `http://127.0.0.1:8000`.

### 6. Levantar el frontend

En otra terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Abre `http://localhost:4321`. En desarrollo, las llamadas a `/api` se reenvían al backend para que todo funcione desde el mismo origen, igual que en producción.

### 7. Activar las revisiones antes de cada commit

```powershell
# Desde la raíz, con el entorno virtual del backend activado
pre-commit install
```

Desde ese momento, cada `git commit` pasa por `ruff`, `gitleaks` (búsqueda de secretos) y la revisión de fin de línea. La primera vez tarda unos minutos porque descarga las herramientas.

## Base de datos local

PostgreSQL corre en Docker solo para desarrollo. Las contraseñas están en `backend/.env` (copia de `backend/.env.example`, nunca se sube al repositorio), por eso todos los comandos llevan `--env-file`. Desde la raíz del repositorio:

```powershell
# Levantar la base (la primera vez crea los roles notia_owner y notia_app)
docker compose --env-file backend/.env up -d

# Ver sus registros o detenerla
docker compose --env-file backend/.env logs db
docker compose --env-file backend/.env down
```

Antes de levantarla, completa en `backend/.env` las variables `POSTGRES_PASSWORD`, `DB_OWNER_PASSWORD` y `DB_PASSWORD` (las dos últimas distintas entre sí). El contenedor recibe solo esas contraseñas, el nombre de la base (`DB_NAME`) y el puerto (`DB_PORT`); las llaves de Django no entran al contenedor.

Las migraciones se ejecutan con el rol dueño del esquema y la aplicación con el rol de privilegios mínimos (desde `backend/`):

```powershell
$env:DB_ROL = 'owner'; python manage.py migrate; Remove-Item Env:DB_ROL
python manage.py runserver
```

## Pruebas y análisis

Son los mismos comandos que ejecuta el CI. Córrelos antes de abrir un pull request.

```powershell
# Backend (desde backend/, con el entorno virtual activado)
pytest --cov
ruff check .
bandit -r apps -ll
pip-audit --require-hashes --disable-pip -r requirements/dev.txt

# Frontend (desde frontend/)
npm run lint
npm run check
npm run test:scripts
npm run build
npm audit --audit-level=high
```

Para cambiar una dependencia del backend, edita `requirements/base.in` o `requirements/dev.in` y vuelve a compilar con el comando que aparece al inicio de ese archivo; nunca edites los `.txt` a mano.

## Integración continua

Cada pull request y cada push a `main` ejecutan `.github/workflows/ci.yml`, con tres trabajos que funcionan como compuertas:

| Trabajo | Qué revisa |
| --- | --- |
| Backend | Instalación con hashes, `ruff`, `bandit`, `pip-audit`, `backend/db/roles.sql` y migraciones contra PostgreSQL, `pytest` con cobertura mínima y `manage.py check --deploy` con la configuración de producción |
| Frontend | `npm ci`, `npm audit`, ESLint, `astro check`, pruebas del script de hashes de CSP y build |
| Secretos | `gitleaks` sobre todo el historial del repositorio |

Si un trabajo falla, el PR no se puede integrar. El CI no usa secretos: su base de datos es temporal y sus contraseñas son valores de prueba escritos en el propio workflow.

## Seguridad

Para reportar una vulnerabilidad, y para saber qué hacer ante una brecha, lee [SECURITY.md](SECURITY.md). El diseño de seguridad está en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) y la relación entre requisitos y pruebas, en [docs/TRAZABILIDAD.md](docs/TRAZABILIDAD.md).

## Flujo de trabajo

1. Nadie trabaja directamente en `main`; la rama está protegida.
2. Cada tarea se desarrolla en su propia rama, por ejemplo `fase-1-login-seguro` o `docs/readme-equipo`.
3. Cada commit termina con el número de la tarea de Azure Boards, por ejemplo `Agrega bloqueo por intentos AB#12`.
4. Los cambios entran a `main` solo mediante un pull request aprobado por otro integrante.
