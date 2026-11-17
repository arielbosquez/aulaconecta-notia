from django.db import migrations

# La bitácora es de solo inserción (RS-16). Los permisos por omisión del
# esquema (db/permisos/base_de_datos.sql) dan a notia_app SELECT, INSERT,
# UPDATE y DELETE sobre cada tabla nueva; aquí se le quitan los que permiten
# alterar la historia. Le quedan SELECT e INSERT.
#
# La migración la ejecuta notia_owner, el dueño de la tabla. Si el rol
# notia_app no existe, falla a propósito: la tabla no debe quedar creada sin
# esta restricción. Los roles se crean antes con db/roles.sql.
QUITAR_PERMISOS = """
    REVOKE UPDATE, DELETE, TRUNCATE
    ON TABLE auditoria_registroauditoria
    FROM notia_app;
"""

# Solo para poder deshacer la migración en desarrollo.
DEVOLVER_PERMISOS = """
    GRANT UPDATE, DELETE
    ON TABLE auditoria_registroauditoria
    TO notia_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("auditoria", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=QUITAR_PERMISOS, reverse_sql=DEVOLVER_PERMISOS),
    ]
