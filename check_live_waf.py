"""
===========================================
  CHECK LIVE WAF — IDEA MILLONARIA
===========================================

Diagnóstico local (sin depender de Colab): revisa si una cuenta de
TikTok está en vivo usando cookies.txt, distinguiendo un "no en vivo"
real de un bloqueo del WAF o un error técnico. Usa la misma lógica de
diagnóstico que el capturador (_diagnosticar_live en tiktok_capture.py)
para no mantener dos implementaciones del mismo chequeo por separado.

Uso:
  python check_live_waf.py <usuario>
"""
import sys

from tiktok_capture import normalizar_usuario, _diagnosticar_live


def main():
    if len(sys.argv) != 2:
        print("Uso: python check_live_waf.py <usuario>")
        sys.exit(1)

    usuario = normalizar_usuario(sys.argv[1])
    print(f"[CHECK] Consultando @{usuario}...")

    try:
        en_vivo = _diagnosticar_live(usuario)
    except RuntimeError as e:
        print(f"@{usuario}: ⚠️ NO SE PUDO VERIFICAR — {e}")
        return

    if en_vivo:
        print(f"@{usuario}: 🟢 EN VIVO (verificado, sin bloqueo)")
    else:
        print(f"@{usuario}: ⚫ no en vivo (real, sin marcadores de WAF)")


if __name__ == "__main__":
    main()
