"""
===========================================
  VERIFICAR LIVES — IDEA MILLONARIA
===========================================

Lee un .txt con usuarios de TikTok (uno por línea) y muestra cuáles
están en vivo ahora mismo. Solo consulta — no descarga ni graba nada.

Uso:
  python verificar_lives.py --lista usuarios_lives.txt
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from captura.tiktok_capture import capturar, normalizar_usuario, verificar_live_activo, verificar_yt_dlp

CACHE_PATH = Path("live_check_cache.json")
COOLDOWN_SEGUNDOS = 600      # no re-consultar la red por el mismo usuario antes de esto
ESPACIADO_SEGUNDOS = 3       # pausa entre peticiones reales, para no ir en ráfaga


def _cargar_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def leer_usuarios(ruta: Path) -> list[str]:
    usuarios = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        usuarios.append(normalizar_usuario(linea))
    return usuarios


def main():
    parser = argparse.ArgumentParser(
        description="Verifica qué usuarios de TikTok de una lista están en vivo ahora mismo (solo consulta, no graba)"
    )
    parser.add_argument("--lista", required=True, help="Ruta al .txt con usuarios de TikTok (uno por línea)")
    args = parser.parse_args()

    ruta = Path(args.lista)
    if not ruta.exists():
        print(f"[LIVES] ❌ No se encontró el archivo: {ruta}")
        sys.exit(1)

    usuarios = leer_usuarios(ruta)
    if not usuarios:
        print(f"[LIVES] ❌ La lista está vacía: {ruta}")
        sys.exit(1)

    verificar_yt_dlp()

    print("════════════════════════════════════")
    print("  VERIFICAR LIVES — IDEA MILLONARIA")
    print(f"  Lista    : {ruta}")
    print(f"  Usuarios : {len(usuarios)}")
    print("════════════════════════════════════")

    cache = _cargar_cache()
    ahora = time.time()

    en_vivo = []
    for usuario in usuarios:
        cacheado = cache.get(usuario)
        if cacheado and (ahora - cacheado["checked_at"]) < COOLDOWN_SEGUNDOS:
            activo = cacheado["is_live"]
            estado = ("🟢 EN VIVO" if activo else "⚫ no en vivo") + " (caché)"
        else:
            url = f"https://www.tiktok.com/@{usuario}/live"
            activo = verificar_live_activo(url)
            estado = "🟢 EN VIVO" if activo else "⚫ no en vivo"
            cache[usuario] = {"checked_at": ahora, "is_live": activo}
            _guardar_cache(cache)
            time.sleep(ESPACIADO_SEGUNDOS)

        print(f"  @{usuario:<25} {estado}")
        if activo:
            en_vivo.append(usuario)

    print("════════════════════════════════════")
    if not en_vivo:
        print("[LIVES] Ningún usuario en vivo ahora mismo")
        return

    nombres = ", ".join(f"@{u}" for u in en_vivo)
    print(f"[LIVES] {len(en_vivo)} usuario(s) en vivo: {nombres}")

    respuesta = input("\n¿Deseas empezar a grabar algún live? (s/n): ").strip().lower()
    if respuesta not in ("s", "si", "sí"):
        return

    print("\nUsuarios en vivo:")
    for i, usuario in enumerate(en_vivo, start=1):
        print(f"  {i}. @{usuario}")

    eleccion = input(f"¿Cuál? (1-{len(en_vivo)}): ").strip()
    if not eleccion.isdigit() or not (1 <= int(eleccion) <= len(en_vivo)):
        print("[LIVES] Opción inválida, no se inició ninguna captura")
        return

    usuario_elegido = en_vivo[int(eleccion) - 1]
    print(f"\n[LIVES] Iniciando captura de @{usuario_elegido}...\n")
    capturar(usuario_elegido)


if __name__ == "__main__":
    main()
