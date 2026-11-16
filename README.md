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

## Flujo de trabajo

1. Nadie trabaja directamente en `main`; la rama está protegida.
2. Cada tarea se desarrolla en su propia rama, por ejemplo `fase-1-login-seguro` o `docs/readme-equipo`.
3. Cada commit termina con el número de la tarea de Azure Boards, por ejemplo `Agrega bloqueo por intentos AB#12`.
4. Los cambios entran a `main` solo mediante un pull request aprobado por otro integrante.
