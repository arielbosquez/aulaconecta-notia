# Política de seguridad de NotIA

NotIA guarda datos de estudiantes, en su mayoría menores de edad, y sus resultados académicos. Por eso tratamos cada reporte de seguridad como prioritario, aunque el sistema sea un proyecto del ramo Desarrollo Seguro.

## Versiones soportadas

NotIA se despliega de forma continua desde la rama `main`; no se mantienen versiones antiguas.

| Versión | Recibe correcciones de seguridad |
| --- | --- |
| Último commit de `main` (lo que está desplegado) | Sí |
| Ramas de trabajo y commits anteriores | No |

## Cómo reportar una vulnerabilidad

**No abras un issue ni un pull request público** para reportar una vulnerabilidad: quedaría visible antes de que exista una corrección.

1. Entra a la pestaña **Security** del repositorio en GitHub y elige **Report a vulnerability**. El reporte llega en privado al equipo.
2. Si no puedes usar esa opción, contacta directamente a la Security Champion del equipo, Javiera Quintana, por el canal institucional del ramo.

Incluye en el reporte:

- Qué encontraste y qué permitiría hacer (por ejemplo, ver las notas de otro alumno).
- Los pasos para reproducirlo, con la ruta o el endpoint afectado.
- El commit o la fecha en que lo probaste.

Para demostrar el problema usa solo las cuentas de demostración (`*.demo@aulaconecta.cl`). No accedas a datos de personas reales, no los copies y no los incluyas en el reporte. Tampoco pegues contraseñas, tokens ni llaves: basta con decir dónde están.

## Tiempos de respuesta

| Etapa | Plazo |
| --- | --- |
| Confirmación de que recibimos el reporte | 2 días hábiles |
| Evaluación inicial y severidad asignada | 5 días hábiles |
| Corrección de una vulnerabilidad crítica o alta | 7 días corridos |
| Corrección de una vulnerabilidad media | 30 días corridos |
| Corrección de una vulnerabilidad baja | Se planifica en el backlog |

La severidad se asigna según el impacto sobre los datos de los alumnos y la integridad de las evaluaciones. Te avisaremos cuando la corrección esté integrada en `main`.

## Cómo corregimos

1. La Security Champion registra el hallazgo como tarea en Azure Boards, sin detalles que permitan explotarlo.
2. La corrección se hace en una rama propia, con una prueba automatizada que reproduce el problema, y entra a `main` por pull request con el CI en verde y la aprobación de otro integrante.
3. Si cambia la verificación de un requisito de seguridad, se actualiza `docs/TRAZABILIDAD.md`.

## Procedimiento ante una brecha

Hay una brecha cuando alguien accede, modifica, pierde o divulga sin autorización datos personales o secretos del sistema. Por ejemplo: una llave subida al repositorio, una cuenta de docente comprometida o resultados de alumnos expuestos.

1. **Contener.** Quien la detecta avisa de inmediato a la Security Champion y al Scrum Master. Se corta el acceso afectado: cerrar las sesiones activas, bloquear la cuenta comprometida o detener el servicio si hace falta.
2. **Rotar los secretos.** Toda llave o contraseña expuesta se reemplaza en Azure Key Vault y en la configuración de App Service, aunque se haya borrado del repositorio: lo que llegó a GitHub se considera comprometido. Rotar la llave de firma de sesiones cierra todas las sesiones; rotar la llave de cifrado de 2FA obliga a docentes y administradores a configurar de nuevo su segundo factor.
3. **Investigar.** Con la bitácora de auditoría (de solo inserción) y los registros de App Service se determina qué pasó, desde cuándo y qué datos de qué personas quedaron expuestos. Los registros no se alteran ni se borran.
4. **Notificar.** El equipo informa al docente del ramo y al colegio, que es el responsable de los datos. Conforme a la Ley 21.719, el responsable debe comunicar la brecha a la Agencia de Protección de Datos Personales sin dilaciones indebidas y, cuando afecta datos de niños, niñas y adolescentes o datos sensibles, también a los titulares o a sus apoderados, en un lenguaje claro.
5. **Corregir y aprender.** La causa se corrige con el flujo de la sección anterior. Después se escribe un informe breve, sin culpables: qué ocurrió, cómo se detectó, qué se hizo y qué control se agrega para que no se repita.

## Controles que ya aplica el repositorio

- `main` está protegida: todo cambio entra por pull request, con aprobación de otro integrante.
- El CI (`.github/workflows/ci.yml`) bloquea el PR si fallan las pruebas, `ruff`, `bandit`, `pip-audit`, `npm audit`, ESLint o `gitleaks`, que revisa todo el historial en busca de secretos.
- Las dependencias están fijadas con hash y Dependabot propone sus actualizaciones cada semana.
- Los requisitos de seguridad y sus pruebas están en `docs/TRAZABILIDAD.md`; el diseño, en `docs/ARQUITECTURA.md`.
