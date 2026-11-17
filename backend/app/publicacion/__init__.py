"""
publicacion/ — Cola de publicación de clips aprobados (v1: TikTok, borrador a la bandeja).

Todo clip aprobado en la Revisión web entra a la cola de su nicho (cola.py); un motor
dentro del backend (motor.py) revisa al arrancar y cada 10 min, y si toca un horario
(horarios.py) envía el primero de la cola con el publicador de la cuenta (tiktok.py real,
simulado.py para probar). Estado en SQLite (db.py). Ver backend/docs/DECISIONES.md.

Alcance: hasta que TikTok confirma que el borrador llegó a la bandeja del usuario
(SEND_TO_USER_INBOX). Si después lo publica o no, ya no lo sigue este sistema.
"""
