# Security Policy

## Reporte de exposición de datos sensibles

Si detectas exposición de credenciales, tokens, URLs privadas o cualquier dato sensible:

1. **No publiques** el secreto en issues públicos.
2. Reporta de forma privada al mantenedor del repositorio.
3. Incluye solo contexto mínimo y evidencia sanitizada.
4. Indica archivo, commit y pasos para reproducir sin revelar credenciales.

## Alcance de este proyecto

- El importador rechaza parámetros y patrones de credenciales conocidos.
- Se bloquean esquemas inseguros y hosts locales/privados.
- Los reportes no deben incluir valores de query strings ni URLs rechazadas completas.

## Respuesta esperada

- Confirmación de recepción.
- Evaluación del impacto.
- Mitigación y limpieza de historial si aplica.
- Comunicación de cierre cuando el riesgo esté resuelto.
