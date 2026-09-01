"""
ai_client — capa de transporte para llamadas a Claude, desacoplada de los agentes.

Uso interno:
    from ai_client import get_client
    client = get_client()
    response = client.messages.create(model=..., messages=..., max_tokens=...)
    texto = response.content[0].text
"""

from .client import get_client

__all__ = ["get_client"]
