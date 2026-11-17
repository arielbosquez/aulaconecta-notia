"""Nombres de las cookies de sesión según el entorno (sección 8.1 de la arquitectura)."""

# La cookie de refresco solo viaja a las rutas de autenticación.
RUTA_COOKIE_REFRESCO = "/api/auth/"


def nombres_de_cookies(*, produccion: bool) -> dict[str, str]:
    """Devuelve el nombre de la cookie de acceso y el de la de refresco.

    En producción llevan prefijo. Con ``__Host-`` el navegador solo acepta la
    cookie si llega por HTTPS, con ``Secure``, con ``Path=/`` y sin ``Domain``;
    con ``__Secure-``, si llega por HTTPS y con ``Secure``. Así otro subdominio
    o una conexión sin cifrar no pueden plantar una cookie de sesión.

    En desarrollo se trabaja en ``http://localhost``, donde los navegadores no
    aceptan esos prefijos, así que los nombres van sin ellos.
    """
    if produccion:
        return {"acceso": "__Host-notia_acceso", "refresco": "__Secure-notia_refresco"}
    return {"acceso": "notia_acceso", "refresco": "notia_refresco"}


# La cookie del ticket del segundo factor solo viaja a la verificación.
RUTA_COOKIE_TICKET_MFA = "/api/auth/mfa/"


def nombre_cookie_ticket_mfa(*, produccion: bool) -> str:
    """Nombre de la cookie del ticket del 2FA.

    Lleva ``__Secure-`` y no ``__Host-`` porque su ruta no es ``/``: solo se
    envía a ``/api/auth/mfa/``.
    """
    return "__Secure-notia_ticket_mfa" if produccion else "notia_ticket_mfa"
