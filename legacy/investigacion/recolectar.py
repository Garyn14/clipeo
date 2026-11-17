"""
recolectar.py — Mide los últimos videos de cada cuenta del nicho (solo metadata vía yt-dlp,
sin descargar) y los agrega a investigacion/<nicho>/videos.jsonl.

Uso:
    python investigacion/recolectar.py zapatillas_peru [--por-cuenta 60] [--pausa 20]

Cuentas: investigacion/<nicho>/cuentas.yaml. Un video ya medido se reemplaza por la medición
nueva (las vistas cambian con el tiempo); no se duplica. Pausa entre cuentas para no provocar
el bloqueo de TikTok por IP (usa cookies.txt de la raíz si existe).
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import yaml  # noqa: E402

from investigacion.comun import RAIZ, carpeta_nicho, leer_videos  # noqa: E402


def leer_cuenta(cuenta: str, por_cuenta: int) -> list[dict]:
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(por_cuenta), "-J",
           f"https://www.tiktok.com/@{cuenta}"]
    if (RAIZ / "cookies.txt").exists():
        cmd[1:1] = ["--cookies", str(RAIZ / "cookies.txt")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    i = r.stdout.find("{")
    if r.returncode != 0 or i < 0:
        error = (r.stderr.strip().splitlines() or ["sin salida"])[-1]
        print(f"  ⚠ @{cuenta}: {error[:160]}", flush=True)
        return []
    return json.loads(r.stdout[i:]).get("entries") or []


def a_fila(e: dict, cuenta: dict, ahora: datetime) -> dict:
    vistas = e.get("view_count") or 0
    ts = e.get("timestamp")
    return {
        "id":          e.get("id"),
        "url":         f"https://www.tiktok.com/@{cuenta['cuenta']}/video/{e.get('id')}",
        "plataforma":  "tiktok",
        "cuenta":      cuenta["cuenta"],
        "tipo_cuenta": cuenta["tipo"],
        "universo":    cuenta["universo"],
        "texto":       (e.get("title") or e.get("description") or "").strip(),
        "duracion_s":  e.get("duration"),
        "publicado":   datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None,
        "edad_dias":   round((ahora.timestamp() - ts) / 86400, 1) if ts else None,
        "vistas":      vistas,
        "likes":       e.get("like_count"),
        "comentarios": e.get("comment_count"),
        "compartidos": e.get("repost_count"),
        "medido":      ahora.isoformat(timespec="seconds"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    ap.add_argument("--por-cuenta", type=int, default=60)
    ap.add_argument("--pausa", type=int, default=20, help="segundos entre cuentas")
    args = ap.parse_args()

    carpeta = carpeta_nicho(args.nicho)
    cuentas = yaml.safe_load((carpeta / "cuentas.yaml").read_text(encoding="utf-8"))["cuentas"]
    ahora = datetime.now(timezone.utc)

    nuevas: list[dict] = []
    for n, cuenta in enumerate(cuentas, 1):
        print(f"[{n}/{len(cuentas)}] @{cuenta['cuenta']}...", flush=True)
        entradas = [e for e in leer_cuenta(cuenta["cuenta"], args.por_cuenta) if e.get("view_count") is not None]
        nuevas += [a_fila(e, cuenta, ahora) for e in entradas]
        if entradas:
            print(f"  {len(entradas)} videos", flush=True)
        if n < len(cuentas):
            time.sleep(args.pausa)

    ids_nuevos = {f["id"] for f in nuevas}
    todas = [f for f in leer_videos(args.nicho) if f["id"] not in ids_nuevos] + nuevas
    archivo = carpeta / "videos.jsonl"
    archivo.write_text("\n".join(json.dumps(f, ensure_ascii=False) for f in todas) + "\n", encoding="utf-8")
    print(f"\n✅ {len(nuevas)} videos medidos · {len(todas)} en total → {archivo.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
