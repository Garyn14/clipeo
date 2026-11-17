import type { NombrePaso, Paso } from "../api/types";
import { explicarError } from "../errores";
import { ESTADO_PASO_LABEL, PASO_LABEL, formatearDuracion, formatearHora, subpasoActivo } from "../pasos";

/** Un paso del pipeline como círculo: color por estado, click abre el detalle. */
export function CirculoPaso({
  nombre,
  paso,
  onClick,
}: {
  nombre: NombrePaso;
  paso: Paso;
  onClick: () => void;
}) {
  // Error reintentable (naranja) vs no reintentable (rojo), como en el HUB
  const variante =
    paso.estado === "error" && paso.error?.reintentable ? "error-reintentable" : paso.estado;

  const detalle =
    paso.estado === "ok" || paso.estado === "error"
      ? formatearDuracion(paso.duracion_s)
      : paso.estado === "corriendo"
        ? textoCorriendo(paso)
        : null;

  return (
    <button
      type="button"
      className={`circulo circulo-${variante}`}
      onClick={onClick}
      title={paso.nota ?? (paso.error ? explicarError(paso.error).titulo : ESTADO_PASO_LABEL[paso.estado])}
    >
      <span className="circulo-icono" aria-hidden>
        {ICONO[variante] ?? "•"}
      </span>
      <span className="circulo-nombre">{PASO_LABEL[nombre]}</span>
      <span className="circulo-estado">{ESTADO_PASO_LABEL[paso.estado]}</span>
      {detalle && <span className="circulo-detalle">{detalle}</span>}
      {paso.intentos > 1 && <span className="circulo-intentos">{paso.intentos} intentos</span>}
    </button>
  );
}

// Etiquetas cortas de subpasos: el círculo no tiene lugar para "Descarga del video"
const SUBPASO_CORTO: Record<string, string> = {
  metadata: "Info",
  video: "Video",
  audio: "Audio",
  duracion: "Verificando",
};

function textoCorriendo(paso: Paso): string {
  const activo = subpasoActivo(paso.subpasos);
  if (!activo) return `desde ${formatearHora(paso.inicio)}`;
  const nombre = SUBPASO_CORTO[activo.id] ?? activo.label;
  return activo.pct !== null ? `${nombre} ${activo.pct.toFixed(0)}%` : `${nombre}…`;
}

const ICONO: Record<string, string> = {
  ok: "✓",
  omitido: "–",
  error: "✕",
  "error-reintentable": "↻",
  corriendo: "◌",
  pendiente: "○",
  esperando: "⏸",
  interrumpido: "!",
};
