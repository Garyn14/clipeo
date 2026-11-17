import type { ProgresoSubpaso, Subpaso } from "../api/types";
import { formatearBytes, formatearDuracion } from "../pasos";

const ICONO: Record<Subpaso["estado"], string> = {
  pendiente: "○",
  corriendo: "◌",
  ok: "✓",
  error: "✕",
};

/** Tareas internas de un paso (ej. Descarga: metadata → video → audio → verificación). */
export function SubpasosPaso({ subpasos, pasoCorriendo }: { subpasos: Subpaso[]; pasoCorriendo: boolean }) {
  return (
    <ul className="subpasos">
      {subpasos.map((s) => {
        // Un subpaso "corriendo" de un paso que ya no corre quedó cortado (proceso detenido)
        const estado = s.estado === "corriendo" && !pasoCorriendo ? "error" : s.estado;
        return (
          <li key={s.id} className={`subpaso subpaso-${estado}`}>
            <span className="subpaso-icono" aria-hidden>
              {ICONO[estado]}
            </span>
            <div className="subpaso-cuerpo">
              <div>
                <span className="subpaso-label">{s.label}</span>
                {s.detalle && <span className="hint"> · {s.detalle}</span>}
              </div>
              {estado === "corriendo" && s.progreso && <Progreso p={s.progreso} />}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Progreso({ p }: { p: ProgresoSubpaso }) {
  const partes: string[] = [];
  if (p.pct !== null && p.pct !== undefined) partes.push(`${p.pct.toFixed(0)}%`);
  if (p.bytes) partes.push(p.total ? `${formatearBytes(p.bytes)} de ${formatearBytes(p.total)}` : formatearBytes(p.bytes));
  if (p.velocidad) partes.push(`${formatearBytes(p.velocidad)}/s`);
  if (p.eta_s) partes.push(`faltan ~${formatearDuracion(p.eta_s)}`);
  if (p.pistas && p.pistas > 1 && p.pista) partes.push(`pista ${p.pista} de ${p.pistas}`);

  return (
    <div className="subpaso-progreso">
      {p.pct !== null && p.pct !== undefined && (
        <div className="barra-progreso" role="progressbar" aria-valuenow={p.pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="barra-progreso-relleno" style={{ width: `${Math.min(p.pct, 100)}%` }} />
        </div>
      )}
      {partes.length > 0 && <span className="hint">{partes.join(" · ")}</span>}
    </div>
  );
}
