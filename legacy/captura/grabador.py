"""
grabador.py — CLIP-88 (épica L1, CLIP-86): graba un directo en trozos, en su propio proceso.

Lo lanza el vigilante del backend cuando una cuenta está en vivo (o el operador con "Grabar ahora"):

    python -m captura.grabador --nicho zapatillas_peru --plataforma tiktok --usuario fritzsport \
        --stream-data D:/clipeo/stream_data [--trozo-min 30] [--sin-verificar]

Escribe `<stream_data>/directo_<nicho>_<usuario>_<fecha>/captura_estado.json` y los trozos `trozo_NNN.mp4`.
Se detiene ordenado (el archivo del trozo queda legible) cuando:
- aparece `detener.flag` en la carpeta (botón "Detener" del panel),
- el directo termina (la grabación se corta y la plataforma confirma que ya no está en vivo),
- hay demasiados cortes seguidos, o el chequeo no es concluyente después de un corte.
Un corte con el directo todavía activo se reintenta (mismo criterio que tiktok_capture).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from captura import directos, tipos_directo  # noqa: E402

FLAG_DETENER = "detener.flag"
REINTENTOS_MAX = 5
ESPERA_REINTENTO_S = 5
SONDEO_S = 2
GRACIA_S = 8


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Grabador:
    def __init__(self, nicho: str, plataforma: str, usuario: str, stream_data: Path, trozo_min: int,
                 lanzar=subprocess.Popen, dormir=time.sleep, reloj=time.monotonic):
        self.tipo = tipos_directo.obtener(plataforma)
        self.nicho, self.plataforma, self.usuario = nicho, plataforma, self.tipo.normalizar_usuario(usuario)
        self.trozo_s = max(60, int(trozo_min) * 60)
        self.carpeta = stream_data / directos.nombre_captura(nicho, self.usuario)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self._lanzar, self._dormir, self._reloj = lanzar, dormir, reloj
        self.estado = {
            "nicho": nicho, "plataforma": plataforma, "usuario": self.usuario, "url": self.tipo.url(self.usuario),
            "pid": os.getpid(), "estado": "grabando", "inicio": _ahora(), "fin": None, "motivo": "",
            "trozo_min": int(trozo_min), "trozos": [],
        }
        self._guardar()

    # ── estado ──
    def _guardar(self) -> None:
        directos.escribir_json(self.carpeta / directos.ARCHIVO_ESTADO, self.estado)

    def _pidieron_detener(self) -> bool:
        return (self.carpeta / FLAG_DETENER).exists()

    def _terminar(self, estado: str, motivo: str) -> None:
        self.estado.update(estado=estado, motivo=motivo, fin=_ahora())
        self._guardar()
        print(f"[GRABADOR] {estado}: {motivo}", flush=True)

    # ── grabación de un trozo ──
    def _grabar_trozo(self, ruta: Path) -> tuple[str, int | None]:
        """Graba hasta cumplir la duración, que pidan detener o que el proceso termine solo.
        Devuelve (motivo, returncode): motivo ∈ {"tiempo", "detener", "termino"}."""
        cmd = self.tipo.comando_grabacion(self.usuario, str(ruta))
        flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" \
            else {"start_new_session": True}
        proc = self._lanzar(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **flags)
        inicio = self._reloj()
        while True:
            rc = proc.poll()
            if rc is not None:
                return "termino", rc
            if self._pidieron_detener():
                self._detener_proceso(proc)
                return "detener", None
            if self._reloj() - inicio >= self.trozo_s:
                self._detener_proceso(proc)
                return "tiempo", None
            self._dormir(SONDEO_S)

    def _detener_proceso(self, proc) -> None:
        from captura import tiktok_capture

        try:
            # Interrupción ordenada para que el muxer cierre el archivo; si no responde, se mata el árbol.
            tiktok_capture._GRACE_SEGUNDOS = GRACIA_S
            tiktok_capture._detener_ordenado(proc)
        except Exception:  # noqa: BLE001 — último recurso: que no quede yt-dlp/ffmpeg huérfano
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _registrar(self, num: int, ruta: Path, inicio: str, parcial: bool) -> None:
        self.estado["trozos"].append({
            "id": f"trozo_{num:03d}", "archivo": ruta.name, "inicio": inicio, "fin": _ahora(),
            "bytes": ruta.stat().st_size, "estado": "parcial" if parcial else "listo", "sesion": None,
        })
        self._guardar()
        print(f"[GRABADOR] {ruta.name} guardado ({ruta.stat().st_size / 1_048_576:.1f} MB)", flush=True)

    # ── bucle ──
    def correr(self, verificar: bool = True) -> dict:
        if verificar:
            vivo = self.tipo.en_vivo(self.usuario)
            if vivo is not True:
                self._terminar("sin_directo" if vivo is False else "error",
                               "no está en vivo" if vivo is False else "no se pudo verificar si está en vivo")
                return self.estado
        num, cortes = 0, 0
        try:
            while True:
                num += 1
                ruta = self.carpeta / f"trozo_{num:03d}.mp4"
                inicio = _ahora()
                print(f"[GRABADOR] grabando {ruta.name} ({self.trozo_s // 60} min)", flush=True)
                motivo, rc = self._grabar_trozo(ruta)
                valido = ruta.exists() and ruta.stat().st_size > 0
                if valido:
                    self._registrar(num, ruta, inicio, parcial=motivo == "detener")
                elif ruta.exists():
                    ruta.unlink(missing_ok=True)
                    num -= 1
                else:
                    num -= 1

                if motivo == "detener":
                    self._terminar("detenido", "detenido desde el panel")
                    return self.estado
                if motivo == "tiempo":
                    cortes = 0
                    continue

                # La grabación terminó sola: ¿terminó el directo o fue un corte?
                sigue = self.tipo.en_vivo(self.usuario)
                if sigue is True:
                    cortes += 1
                    if cortes > REINTENTOS_MAX:
                        self._terminar("error", f"{REINTENTOS_MAX} cortes seguidos con el directo activo")
                        return self.estado
                    print(f"[GRABADOR] corte con el directo activo (rc={rc}), reintento {cortes}/{REINTENTOS_MAX}",
                          flush=True)
                    self._dormir(ESPERA_REINTENTO_S)
                    continue
                if sigue is False:
                    self._terminar("terminado", "el directo terminó")
                else:
                    self._terminar("error", "la grabación se cortó y no se pudo verificar si sigue en vivo")
                return self.estado
        except KeyboardInterrupt:
            self._terminar("detenido", "interrumpido")
            return self.estado
        except Exception as e:  # noqa: BLE001 — que el estado nunca quede en "grabando" con el proceso muerto
            self._terminar("error", f"{type(e).__name__}: {e}")
            raise


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Graba un directo en trozos (CLIP-88)")
    p.add_argument("--nicho", required=True)
    p.add_argument("--plataforma", default="tiktok")
    p.add_argument("--usuario", required=True)
    p.add_argument("--stream-data", required=True)
    p.add_argument("--trozo-min", type=int, default=directos.TROZO_MIN_DEFECTO)
    p.add_argument("--sin-verificar", action="store_true", help="no verificar antes de grabar (ya se sabe que está en vivo)")
    a = p.parse_args(argv)
    g = Grabador(a.nicho, a.plataforma, a.usuario, Path(a.stream_data), a.trozo_min)
    print(f"[GRABADOR] {g.carpeta}", flush=True)
    estado = g.correr(verificar=not a.sin_verificar)
    return 0 if estado["estado"] in ("terminado", "detenido", "sin_directo") else 1


if __name__ == "__main__":
    sys.exit(main())
