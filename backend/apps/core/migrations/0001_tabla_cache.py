from django.db import migrations

# Tabla de la caché en base de datos (DatabaseCache, CACHES en
# config/settings/base.py). La usan los límites de intentos por IP.
#
# Normalmente se crea con "manage.py createcachetable", pero ese comando
# corre con la conexión de la aplicación y notia_app no puede crear tablas
# (RS-19). Como migración la ejecuta notia_owner, igual que el resto del
# esquema, en local, en el CI y en la base de pruebas. Los permisos por
# omisión de db/permisos/base_de_datos.sql le dan a notia_app SELECT, INSERT,
# UPDATE y DELETE sobre ella, que es lo que necesita DatabaseCache.
#
# Es el mismo SQL que genera "createcachetable --dry-run" para PostgreSQL. El
# nombre debe coincidir con TABLA_CACHE de la configuración.
CREAR_TABLA = """
    CREATE TABLE notia_cache (
        cache_key varchar(255) NOT NULL PRIMARY KEY,
        value text NOT NULL,
        expires timestamp with time zone NOT NULL
    );
    CREATE INDEX notia_cache_expires ON notia_cache (expires);
"""

BORRAR_TABLA = "DROP TABLE notia_cache;"


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(sql=CREAR_TABLA, reverse_sql=BORRAR_TABLA),
    ]
