"""
ai_client/_response.py — objeto respuesta mínimo compartido por los proveedores que no
son el SDK real (manual, claude_cli).

Expone solo lo que los agentes leen (`response.content[0].text`), más un `.meta` opcional
con datos de trazabilidad (usage, duración) que el SDK real no tiene con ese nombre.
"""


class TextBlock:
    def __init__(self, text: str):
        self.text = text


class TextResponse:
    def __init__(self, text: str, meta: dict | None = None):
        self.content = [TextBlock(text)]
        self.meta = meta or {}
