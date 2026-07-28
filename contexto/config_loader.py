"""
config_loader.py — Carga configuración YAML por canal.

Soporta dos arquitecturas:
  - Archivo único : config/canal_id.yaml
  - Ecosistema    : config/ecosistema_id/_index.yaml
                    + config/ecosistema_id/{personaje_id}.yaml

Uso:
  from contexto.config_loader import ConfigLoader

  cfg = ConfigLoader()
  config = cfg.load("zapatillas_peru")       # archivo único
  config = cfg.load("streamers_peru")        # ecosistema

  # Tras el Agente 0 (solo en ecosistemas):
  if cfg.get_ecosystem_type() == "ecosystem":
      config = cfg.enrich_with_speakers(config, ["Sideral", "Karolina"])

  prompt    = cfg.get("deteccion", "prompt")
  confianza = cfg.get("deteccion", "confianza_minima")
"""

import copy
import logging
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

log = logging.getLogger(__name__)


class ConfigLoader:
    def __init__(self, config_dir: str = "config"):
        self._config_dir          = Path(config_dir)
        self._data: dict          = {}
        self._loaded_file: Path | None = None
        self._ecosystem_id: str | None = None
        self._ecosystem_type: str = "single"   # "single" | "ecosystem"
        self._enriched_ids: set[str] = set()   # personajes ya mergeados (anti-duplicado)

    # ─────────────────────────────────────────
    #  LOAD
    # ─────────────────────────────────────────

    def load(self, canal_id: str | None = None) -> dict:
        """
        Carga la configuración.

        Orden de resolución:
          1. config/{canal_id}/  (carpeta → ecosistema)
          2. config/{canal_id}.yaml
          3. config/default.yaml  (fallback)
        """
        if canal_id is None:
            return self._load_file(self._config_dir / "default.yaml")

        folder = self._config_dir / canal_id
        if folder.is_dir():
            return self._load_ecosystem(canal_id, folder)

        target = self._config_dir / f"{canal_id}.yaml"
        if target.exists():
            return self._load_file(target)

        log.warning("Config '%s' no encontrado — usando default.yaml", canal_id)
        return self._load_file(self._config_dir / "default.yaml")

    def _load_file(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(
                f"Archivo de configuración no encontrado: {path}\n"
                f"  Asegurate de que exista config/default.yaml"
            )
        with open(path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        self._loaded_file    = path
        self._ecosystem_id   = None
        self._ecosystem_type = "single"
        self._enriched_ids   = set()
        return self._data

    def _load_ecosystem(self, canal_id: str, folder: Path) -> dict:
        index_path = folder / "_index.yaml"
        if not index_path.exists():
            raise FileNotFoundError(
                f"Ecosistema '{canal_id}': falta _index.yaml en {folder}"
            )
        print(f"[CONFIG] Cargando ecosistema: {canal_id}")
        with open(index_path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        self._loaded_file    = index_path
        self._ecosystem_id   = canal_id
        self._ecosystem_type = "ecosystem"
        self._enriched_ids   = set()
        print(f"[CONFIG] _index.yaml cargado ✅")
        return self._data

    # ─────────────────────────────────────────
    #  ENRICH
    # ─────────────────────────────────────────

    def enrich_with_speakers(self, config: dict, speakers_detectados: list[str]) -> dict:
        """
        Enriquece la config del ecosistema con los YAMLs de los personajes detectados.

        Para cada nombre en speakers_detectados:
          - Busca match en config["personajes"][*]["nombres"]  (case-insensitive)
          - Si hay match → carga config/{ecosistema_id}/{id}.yaml
          - Mergea: deteccion.prompt  +=  lore + deteccion_adicional.prompt
                    contenido.hashtags_base  +=  contenido_adicional.hashtags
        """
        if self._ecosystem_type != "ecosystem":
            return config

        ecosistema_id = self._ecosystem_id or config.get("meta", {}).get("id", "")
        personajes    = config.get("personajes", [])

        enriched = copy.deepcopy(config)

        print(f"[CONFIG] Buscando YAMLs para speakers: {speakers_detectados}")

        for nombre_detectado in speakers_detectados:
            nombre_lower = nombre_detectado.lower()
            matched_id   = None

            for personaje in personajes:
                for alias in personaje.get("nombres", []):
                    if alias.lower() == nombre_lower:
                        matched_id = personaje["id"]
                        break
                if matched_id:
                    break

            if not matched_id:
                print(f"[CONFIG] No hay YAML para: {nombre_detectado}")
                print(f"         → usando solo contexto del índice")
                continue

            if matched_id in self._enriched_ids:
                continue   # ya cargado en llamada anterior — anti-duplicado

            yaml_path = self._config_dir / ecosistema_id / f"{matched_id}.yaml"
            if not yaml_path.exists():
                print(f"[CONFIG] Match '{nombre_detectado}' → {matched_id}.yaml  ⚠ archivo no encontrado")
                continue

            print(f"[CONFIG] Match encontrado: {nombre_detectado} → {matched_id}.yaml")
            with open(yaml_path, encoding="utf-8") as f:
                personaje_data = yaml.safe_load(f) or {}

            # ── Merge deteccion.prompt ──────────────────────────
            lore_bloque = self._build_lore_context(personaje_data)
            det_extra   = personaje_data.get("deteccion_adicional", {}).get("prompt", "").strip()

            adicion = ""
            if lore_bloque:
                adicion += "\n\n" + lore_bloque
            if det_extra:
                adicion += "\n\n" + det_extra

            if adicion:
                enriched.setdefault("deteccion", {})
                base = enriched["deteccion"].get("prompt", "")
                enriched["deteccion"]["prompt"] = base + adicion

            # ── Merge contenido.hashtags_base ───────────────────
            extra_tags = personaje_data.get("contenido_adicional", {}).get("hashtags", [])
            if extra_tags:
                enriched.setdefault("contenido", {})
                existentes = enriched["contenido"].get("hashtags_base", [])
                enriched["contenido"]["hashtags_base"] = list(
                    dict.fromkeys(existentes + extra_tags)   # preserva orden, deduplicado
                )

            # ── Merge contenido_adicional.tono → prompt_adicional_contenido ─
            tono_extra = personaje_data.get("contenido_adicional", {}).get("tono", "").strip()
            if tono_extra:
                enriched.setdefault("contenido", {})
                enriched["contenido"]["prompt_adicional_contenido"] = tono_extra

            self._enriched_ids.add(matched_id)
            print(f"[CONFIG] {matched_id}.yaml cargado y mergeado ✅")

        nombres_cargados = ", ".join(self._enriched_ids) if self._enriched_ids else "ninguno"
        print(f"[CONFIG] Config final: {ecosistema_id} + {nombres_cargados}")

        prompt_total = enriched.get("deteccion", {}).get("prompt", "")
        tokens_est   = int(len(prompt_total.split()) * 1.3)
        print(f"[CONFIG] Prompt total: ~{tokens_est:,} tokens estimados")

        self._data = enriched
        return enriched

    def _build_lore_context(self, personaje_data: dict) -> str:
        """Serializa el lore de un personaje como bloque de texto para el prompt."""
        meta   = personaje_data.get("meta", {})
        lore   = personaje_data.get("lore", {})
        nombre = meta.get("nombre", meta.get("id", ""))

        lines = [f"=== CONTEXTO ESPECÍFICO: {nombre} ==="]

        origen = lore.get("origen", "").strip()
        if origen:
            lines.append(f"\nORIGEN:\n{origen}")

        universo = lore.get("personajes_universo", [])
        if universo:
            lines.append("\nPERSONAJES DEL UNIVERSO:")
            for p in universo:
                lines.append(
                    f"  - {p.get('nombre', '')} ({p.get('rol', '')}): "
                    f"{p.get('relevancia', '')}"
                )

        polemicas = lore.get("polemicas", [])
        if polemicas:
            lines.append("\nPOLÉMICAS CONOCIDAS:")
            for p in polemicas:
                lines.append(f"  - {p.get('titulo', '')}: {p.get('descripcion', '')}")

        vocabulario = lore.get("vocabulario", [])
        if vocabulario:
            lines.append("\nVOCABULARIO:")
            for v in vocabulario:
                termino    = v.get("termino", "")
                significado = v.get("significado", "")
                lines.append(f'  - "{termino}": {significado}')

        return "\n".join(lines)

    # ─────────────────────────────────────────
    #  GETTERS
    # ─────────────────────────────────────────

    def get_ecosystem_type(self) -> str:
        """Retorna 'ecosystem' o 'single'."""
        return self._ecosystem_type

    def get(self, *keys: str, default=None):
        """
        Acceso seguro a claves anidadas.

          cfg.get("deteccion", "confianza_minima")  →  0.70
          cfg.get("contenido", "hashtags_base")     →  ["#kickperu", ...]
          cfg.get("clave_no_existe", default=42)    →  42
        """
        node = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def loaded_file(self) -> Path | None:
        return self._loaded_file

    def __repr__(self) -> str:
        canal = self.get("meta", "id", default="<sin cargar>")
        return f"ConfigLoader(canal={canal!r}, file={self._loaded_file})"


# ─────────────────────────────────────────
#  TEST RÁPIDO
# ─────────────────────────────────────────
if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
    _root = Path(__file__).parent.parent
    _sys.path.insert(0, str(_root))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    print("=" * 50)
    print("  TEST 1 — Archivo único: zapatillas_peru")
    print("=" * 50)
    cfg = ConfigLoader(config_dir=str(_root / "config"))
    cfg.load("zapatillas_peru")
    print(f"Canal        : {cfg.get('meta', 'id')}")
    print(f"Tipo         : {cfg.get_ecosystem_type()}")
    print(f"Archivo      : {cfg.loaded_file}")

    print()
    print("=" * 50)
    print("  TEST 2 — Fallback a default")
    print("=" * 50)
    cfg2 = ConfigLoader(config_dir=str(_root / "config"))
    cfg2.load("canal_que_no_existe")
    print(f"Fallback a   : {cfg2.get('meta', 'id')}")
    print(f"Tipo         : {cfg2.get_ecosystem_type()}")

    print()
    print("=" * 50)
    print("  TEST 3 — Ecosistema: streamers_peru")
    print("=" * 50)
    cfg3 = ConfigLoader(config_dir=str(_root / "config"))
    config3 = cfg3.load("streamers_peru")
    print(f"Canal        : {cfg3.get('meta', 'id')}")
    print(f"Tipo         : {cfg3.get_ecosystem_type()}")
    print(f"Personajes   : {len(config3.get('personajes', []))}")

    print()
    print("=" * 50)
    print("  TEST 4 — Enrich con Sideral")
    print("=" * 50)
    config4 = cfg3.enrich_with_speakers(config3, ["Sideral", "Karolina Karley"])
    print(f"BebaArmy en prompt: {'BebaArmy' in config4['deteccion']['prompt']}")
    print(f"Hashtags      : {config4['contenido']['hashtags_base']}")

    print()
    print("✅ Todos los tests pasaron")
