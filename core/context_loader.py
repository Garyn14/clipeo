"""
context_loader.py — Carga contexto modular desde contexto/.

Arquitectura:
  contexto/nichos/{nicho_id}.yaml       → config base + lista de entidades
  contexto/entidades/{entidad_id}.yaml  → lore + señales adicionales por personaje
  contexto/eventos/{mes}/{entidad_id}_*.yaml → resultados reales + aprendizajes

Uso:
  from core.context_loader import ContextLoader

  ctx = ContextLoader()
  config = ctx.load_nicho("zapatillas_peru")

  # API compatible con ConfigLoader:
  ctx.get("meta", "id")
  ctx.loaded_file
  ctx.get_ecosystem_type()
  ctx.enrich_with_speakers(config, speakers)
"""

import copy
import logging
from pathlib import Path

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

log = logging.getLogger(__name__)


class ContextLoader:
    def __init__(self, contexto_dir: str = "contexto"):
        self._dir          = Path(contexto_dir)
        self._data: dict   = {}
        self._loaded_file: Path | None = None
        self._nicho_id: str | None = None

    # ─────────────────────────────────────────
    #  LOAD
    # ─────────────────────────────────────────

    def load_nicho(self, nicho_id: str) -> dict:
        """
        Ensambla el config completo para un nicho:
          1. Lee contexto/nichos/{nicho_id}.yaml (base + lista de entidades)
          2. Para cada entidad, lee contexto/entidades/{id}.yaml
          3. Busca eventos en contexto/eventos/*/{id}_*.yaml
          4. Ensambla y retorna dict compatible con los agentes
        """
        nicho_path = self._dir / "nichos" / f"{nicho_id}.yaml"
        if not nicho_path.exists():
            raise FileNotFoundError(f"[CONTEXT] Nicho no encontrado: {nicho_path}")

        print(f"[CONTEXT] Cargando nicho: {nicho_id}")
        with open(nicho_path, encoding="utf-8") as f:
            nicho_data = yaml.safe_load(f) or {}

        self._loaded_file = nicho_path
        self._nicho_id    = nicho_id

        entidades_ids = nicho_data.get("nicho", {}).get("entidades", [])
        print(f"[CONTEXT] Entidades: {', '.join(entidades_ids) if entidades_ids else '(ninguna)'}")

        todas_entidades: list[dict] = []
        todos_eventos: list[dict]   = []

        for eid in entidades_ids:
            ent_path = self._dir / "entidades" / f"{eid}.yaml"
            if not ent_path.exists():
                print(f"[CONTEXT] ⚠ Entidad no encontrada: {ent_path}")
                continue
            with open(ent_path, encoding="utf-8") as f:
                ent_data = yaml.safe_load(f) or {}
            print(f"[CONTEXT] {eid}.yaml cargado ✅")
            todas_entidades.append(ent_data)

            eventos = self._load_eventos(eid)
            count   = len(eventos)
            plural  = "s" if count != 1 else ""
            print(f"[CONTEXT] Eventos de {eid}: {count} encontrado{plural}")
            todos_eventos.extend(eventos)

        assembled = self._assemble(nicho_data, todas_entidades, todos_eventos)

        prompt_total = assembled.get("deteccion", {}).get("prompt", "")
        tokens_est   = int(len(prompt_total.split()) * 1.3)
        print(f"[CONTEXT] Contexto ensamblado — ~{tokens_est:,} tokens estimados")

        self._data = assembled
        return assembled

    def _load_eventos(self, entidad_id: str) -> list[dict]:
        eventos     = []
        eventos_dir = self._dir / "eventos"
        if not eventos_dir.exists():
            return eventos
        for mes_dir in sorted(eventos_dir.iterdir()):
            if not mes_dir.is_dir():
                continue
            for yaml_path in sorted(mes_dir.glob(f"{entidad_id}_*.yaml")):
                with open(yaml_path, encoding="utf-8") as f:
                    ev = yaml.safe_load(f) or {}
                eventos.append(ev)
        return eventos

    def _assemble(
        self,
        nicho_data: dict,
        entidades: list[dict],
        eventos: list[dict],
    ) -> dict:
        nicho    = nicho_data.get("nicho", {})
        det_base = nicho_data.get("deteccion_base", {})
        cnt_base = nicho_data.get("contenido_base", {})
        ref_base = nicho_data.get("refinamiento_base", {})

        det_prompt = det_base.get("prompt", "")
        cnt_prompt = cnt_base.get("prompt", "")
        hashtags   = list(cnt_base.get("hashtags_base", []))

        for ent_data in entidades:
            det_extra = ent_data.get("deteccion_adicional", {}).get("prompt", "").strip()
            if det_extra:
                det_prompt += "\n\n" + det_extra

            cnt_tono = ent_data.get("contenido_adicional", {}).get("tono", "").strip()
            if cnt_tono:
                cnt_prompt += "\n\n" + cnt_tono

            extra_tags = ent_data.get("contenido_adicional", {}).get("hashtags", [])
            if extra_tags:
                hashtags = list(dict.fromkeys(hashtags + extra_tags))

        personajes = [
            {
                "id":      ent_data["entidad"]["id"],
                "nombres": [ent_data["entidad"]["nombre"]] + ent_data["entidad"].get("apodos", []),
            }
            for ent_data in entidades
        ]

        return {
            "meta": {
                "id":          nicho.get("id"),
                "descripcion": nicho.get("descripcion"),
            },
            "identificacion": copy.deepcopy(nicho.get("identificacion", {})),
            "deteccion": {
                "confianza_minima": det_base.get("confianza_minima", 0.75),
                "prompt":           det_prompt,
            },
            "refinamiento": {
                "contexto_antes_segundos":   ref_base.get("contexto_antes_segundos", 45),
                "contexto_despues_segundos": ref_base.get("contexto_despues_segundos", 45),
                "duracion_minima_segundos":  ref_base.get("duracion_minima_segundos", 20),
                "duracion_maxima_segundos":  ref_base.get("duracion_maxima_segundos", 90),
                "prompt":                    ref_base.get("prompt", ""),
            },
            "contenido": {
                "score_minimo_publicar": cnt_base.get("score_minimo_publicar", 7),
                "hashtags_base":         hashtags,
                "prompt":                cnt_prompt,
            },
            "personajes": personajes,
            "entidades":  entidades,
            "eventos":    eventos,
        }

    # ─────────────────────────────────────────
    #  API COMPATIBLE CON ConfigLoader
    # ─────────────────────────────────────────

    def get(self, *keys: str, default=None):
        """Acceso seguro a claves anidadas — mismo comportamiento que ConfigLoader.get()."""
        node = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def loaded_file(self) -> Path | None:
        return self._loaded_file

    def get_ecosystem_type(self) -> str:
        """ContextLoader siempre es 'single' — el enriquecimiento ocurre en load_nicho()."""
        return "single"

    def enrich_with_speakers(self, config: dict, speakers: list[str]) -> dict:
        """
        No-op compatible con ConfigLoader.enrich_with_speakers().

        En ContextLoader todo el contexto de entidades se pre-carga en load_nicho(),
        por lo que no hay enriquecimiento lazy. Retorna copia del config sin modificar.
        """
        return copy.deepcopy(config)
