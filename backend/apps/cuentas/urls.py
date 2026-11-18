from django.urls import path

from . import vistas

urlpatterns = [
    path("csrf", vistas.VistaCsrf.as_view(), name="auth-csrf"),
    path("login", vistas.VistaLogin.as_view(), name="auth-login"),
    path("refresh", vistas.VistaRefresh.as_view(), name="auth-refresh"),
    path("logout", vistas.VistaLogout.as_view(), name="auth-logout"),
    path("cambiar-password", vistas.VistaCambiarPassword.as_view(), name="auth-cambiar-password"),
    path("mfa/verificar", vistas.VistaVerificarMfa.as_view(), name="auth-mfa-verificar"),
    path("mfa/enrolar", vistas.VistaEnrolarMfa.as_view(), name="auth-mfa-enrolar"),
    path("mfa/confirmar", vistas.VistaConfirmarMfa.as_view(), name="auth-mfa-confirmar"),
    path("yo", vistas.VistaYo.as_view(), name="auth-yo"),
]
