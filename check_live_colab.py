"""
===========================================
  CHECK LIVE COLAB — IDEA MILLONARIA
===========================================

Prueba directa del endpoint /live/check en Colab (Flask + túnel Cloudflare),
sin pasar por tiktok_capture.py/verificar_lives.py. Pensado para diagnosticar
el túnel o confirmar rápido si un usuario está en vivo.

Uso:
  python check_live_colab.py pinkyshoww
"""

import sys

from tiktok_capture import normalizar_usuario, verificar_live_via_colab

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python check_live_colab.py <usuario>")
        sys.exit(1)

    usuario = normalizar_usuario(sys.argv[1])
    print(f"[CHECK] Consultando @{usuario} vía Colab...")
    try:
        activo = verificar_live_via_colab(usuario)
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)

    print(f"@{usuario}: {'🟢 EN VIVO' if activo else '⚫ no en vivo'}")
