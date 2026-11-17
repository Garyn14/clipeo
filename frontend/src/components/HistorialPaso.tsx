import type { EventoHistorial, IntentoPaso, LlamadaIA, NombrePaso } from "../api/types";
import { explicarError } from "../errores";
import { PASO_LABEL, formatearDuracion, formatearHora } from "../pasos";
import { Llamada } from "./Llamada";

const RESULTADO_LABEL: Record<IntentoPaso["resultado"], string> = {
  corriendo: "En curso",
  ok: "Completado",
  omitido: "Omitido (no aplicaba)",
  error: "Falló",
  interrumpido: "Interrumpido (la corrida se detuvo)",
};

/**
 * Línea de tiempo de un paso: cada intento con su resultado, y entre intentos qué pasó
 * (espera automática, reintento manual, reinicio por un reintento anterior en la cadena).
 */
export function HistorialPaso({
  paso,
  historial,
  llamadas,
  esperandoReintento,
}: {
  paso: NombrePaso;
  historial: EventoHistorial[];
  llamadas: LlamadaIA[];
  /** El último intento falló y el pipeline está esperando para reintentar solo */
  esperandoReintento: boolean;
}) {
  return (
    <ol className="historial">
      {historial.map((ev, i) =>
        ev.tipo === "reinicio" ? (
          <li key={i} className="historial-evento historial-reinicio">
            <span className="historial-punto" aria-hidden>↺</span>
            <div>
              <span className="historial-hora">{formatearHora(ev.fecha)}</span>{" "}
              {ev.desde === paso ? (
                <strong>Reintento manual desde este paso</strong>
              ) : (
                <>
                  Se vuelve a correr porque se reintentó desde{" "}
                  <strong>{PASO_LABEL[ev.desde] ?? ev.desde}</strong>
                  {ev.chunk && <span className="hint"> ({ev.chunk})</span>}
                </>
              )}
            </div>
          </li>
        ) : (
          <Intento
            key={i}
            intento={ev}
            llamadas={llamadas}
            trasReinicio={historial[i - 1]?.tipo === "reinicio"}
          />
        ),
      )}
      {esperandoReintento && (
        <li className="historial-evento historial-espera">
          <span className="historial-punto" aria-hidden>⏳</span>
          <div>Esperando para reintentar automáticamente…</div>
        </li>
      )}
    </ol>
  );
}

function Intento({
  intento,
  llamadas,
  trasReinicio,
}: {
  intento: IntentoPaso;
  llamadas: LlamadaIA[];
  /** El evento anterior ya explica por qué se volvió a correr */
  trasReinicio: boolean;
}) {
  const propias = intento.llamadas
    ? llamadas.filter((ll) => ll.n >= intento.llamadas![0] && ll.n <= intento.llamadas![1])
    : [];
  const variante =
    intento.resultado === "error" && intento.error?.reintentable ? "error-reintentable" : intento.resultado;
  const explicacion = intento.error ? explicarError(intento.error) : null;

  return (
    <>
      {intento.origen === "automatico" && (
        <li className="historial-evento historial-espera">
          <span className="historial-punto" aria-hidden>⏳</span>
          <div>
            Esperó {formatearDuracion(intento.espera_previa_s)} y reintentó automáticamente
          </div>
        </li>
      )}
      {intento.origen === "relanzado" && !trasReinicio && (
        <li className="historial-evento historial-espera">
          <span className="historial-punto" aria-hidden>▶</span>
          <div>Se retomó en una corrida nueva</div>
        </li>
      )}
      <li className={`historial-evento historial-intento historial-${variante}`}>
        <span className="historial-punto" aria-hidden>
          {ICONO[variante] ?? "•"}
        </span>
        <div className="historial-cuerpo">
          <div>
            <strong>Intento #{intento.n}</strong>{" "}
            <span className="historial-hora">{formatearHora(intento.inicio)}</span>
            {intento.duracion_s !== null && (
              <span className="hint"> · {formatearDuracion(intento.duracion_s)}</span>
            )}
            {" — "}
            {explicacion ? explicacion.titulo : RESULTADO_LABEL[intento.resultado]}
          </div>
          {intento.error && <div className="historial-mensaje">{intento.error.mensaje.split("\n")[0]}</div>}
          {propias.length > 0 && (
            <details className="historial-llamadas">
              <summary>
                {propias.length === 1 ? "1 llamada a Claude" : `${propias.length} llamadas a Claude`}
              </summary>
              {propias.map((ll) => (
                <Llamada key={ll.n} llamada={ll} abierta={false} />
              ))}
            </details>
          )}
        </div>
      </li>
    </>
  );
}

const ICONO: Record<string, string> = {
  ok: "✓",
  omitido: "–",
  error: "✕",
  "error-reintentable": "✕",
  corriendo: "◌",
  interrumpido: "!",
};
