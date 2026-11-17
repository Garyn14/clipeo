"""
ai_client/errors.py — errores tipados del transporte de IA.

El orquestador de pasos (core/pasos.py) usa la clase para decidir si un fallo se reintenta
solo o requiere intervención:
    AIRetryableError — transitorio: límite de uso, rate limit, timeout, sobrecarga,
                       respuesta vacía o no parseable. Reintentar más tarde suele bastar.
    AIFatalError     — de configuración: CLI no instalado, sesión no iniciada, credenciales.
                       Reintentar sin corregir la causa da el mismo error.
"""


class AIError(RuntimeError):
    reintentable = True


class AIRetryableError(AIError):
    reintentable = True


class AIFatalError(AIError):
    reintentable = False
