"""Pruebas del comando generar_llaves (RS-14)."""

import io

from django.core.management import call_command

from apps.core.llaves import es_llave_fernet, validar_llaves


def _ejecutar() -> tuple[dict[str, str], str]:
    salida, avisos = io.StringIO(), io.StringIO()
    call_command("generar_llaves", stdout=salida, stderr=avisos)
    lineas = salida.getvalue().strip().splitlines()
    return dict(linea.split("=", 1) for linea in lineas), avisos.getvalue()


def test_imprime_las_tres_llaves_y_son_validas():
    llaves, _ = _ejecutar()

    assert list(llaves) == ["DJANGO_SECRET_KEY", "JWT_SIGNING_KEY", "MFA_ENCRYPTION_KEY"]
    assert es_llave_fernet(llaves["MFA_ENCRYPTION_KEY"])
    # Las mismas reglas que exige la configuración de producción.
    validar_llaves(
        secreta=llaves["DJANGO_SECRET_KEY"],
        jwt=llaves["JWT_SIGNING_KEY"],
        mfa=llaves["MFA_ENCRYPTION_KEY"],
    )


def test_cada_ejecucion_entrega_llaves_distintas():
    primera, _ = _ejecutar()
    segunda, _ = _ejecutar()

    assert set(primera.values()).isdisjoint(segunda.values())


def test_los_avisos_no_repiten_las_llaves():
    llaves, avisos = _ejecutar()

    assert "ningún archivo" in avisos
    for valor in llaves.values():
        assert valor not in avisos


def test_no_escribe_archivos(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _ejecutar()

    assert list(tmp_path.iterdir()) == []
