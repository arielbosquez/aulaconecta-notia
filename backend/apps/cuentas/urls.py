from django.urls import path

from . import vistas

urlpatterns = [
    path("csrf", vistas.VistaCsrf.as_view(), name="auth-csrf"),
    path("login", vistas.VistaLogin.as_view(), name="auth-login"),
    path("refresh", vistas.VistaRefresh.as_view(), name="auth-refresh"),
    path("yo", vistas.VistaYo.as_view(), name="auth-yo"),
]
