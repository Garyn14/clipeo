import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api/client";
import type { DetallePaso, ErrorPaso, IntentoPaso, NombrePaso } from "../api/types";
import { explicarError } from "../errores";
import {
  ESTADO_PASO_LABEL,
  PASO_LABEL,
  esReintentable,
  formatearBytes,
  formatearDuracion,
  formatearFecha,
  formatearHora,
  subpasoActivo,
} from "../pasos";
import { HistorialPaso } from "./HistorialPaso";
import { Llamada } from "./Llamada";
import { DecisionesJuez } from "./DecisionesJuez";
import { SubpasosPaso } from "./SubpasosPaso";

/** Detalle de un paso (estado, error, REQUEST/RESPONSE de IA, salidas) + Reintentar. */
export function PasoModal({
  sessionId,
  chunk,
  paso,
  onClose,
}: {
  sessionId: string;
  chunk: string | null;
  paso: NombrePaso;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const pasoQuery = useQuery({
    queryKey: ["paso", sessionId, chunk, paso],
    queryFn: () => api.getPaso(sessionId, chunk, paso),
    refetchInterval: (q) => (q.state.data?.estado === "corriendo" ? 3000 : false),
  });

  const reintentarMutation = useMutation({
    mutationFn: () => api.reintentar(sessionId, paso, chunk ? [chunk] : undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["paso", sessionId] });
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = pasoQuery.data;
  const historial = d?.historial ?? [];
  const intentos = historial.filter((ev): ev is IntentoPaso => ev.tipo === "intento");
  const ultimo = intentos[intentos.length - 1];
  // Entre un intento fallido y el siguiente automático el paso sigue "corriendo"
  const esperandoReintento = d?.estado === "corriendo" && ultimo?.resultado === "error";
  // Llamadas que no caen en el rango de ningún intento (trazas previas al historial)
  const llamadasSueltas = (d?.llamadas ?? []).filter(
    (ll) => !intentos.some((i) => i.llamadas && ll.n >= i.llamadas[0] && ll.n <= i.llamadas[1]),
  );
  const puedeReintentar =
    !!d && esReintentable(paso) && !d.run_activo && d.estado !== "corriendo";

  return (
    <div className="modal-fondo" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal>
        <header className="modal-cabecera">
          <div>
            <h2>
              {PASO_LABEL[paso]}
              {chunk && <span className="modal-chunk"> · {chunk}</span>}
            </h2>
            {d && <span className={`pill pill-paso-${d.estado}`}>{ESTADO_PASO_LABEL[d.estado]}</span>}
          </div>
          <button type="button" className="btn btn-secondary" onClick={onClose} aria-label="Cerrar">
            ✕
          </button>
        </header>

        {pasoQuery.isLoading && <p className="hint">Cargando...</p>}
        {pasoQuery.isError && <p className="error">{(pasoQuery.error as Error).message}</p>}

        {d && (
          <div className="modal-cuerpo">
            <Resumen d={d} intentos={intentos} esperandoReintento={esperandoReintento} />

            {d.subpasos && d.subpasos.length > 0 && (
              <SubpasosPaso subpasos={d.subpasos} pasoCorriendo={d.estado === "corriendo"} />
            )}

            {d.decisiones && d.decisiones.length > 0 && <DecisionesJuez decisiones={d.decisiones} />}

            {d.error && (d.estado === "error" || esperandoReintento) && (
              <QuePaso error={d.error} />
            )}

            {d.nota && <p className="hint">{d.nota}</p>}

            {historial.length > 0 ? (
              <section>
                <h3 className="subtitulo">Intentos</h3>
                <HistorialPaso
                  paso={paso}
                  historial={historial}
                  llamadas={d.llamadas}
                  esperandoReintento={esperandoReintento}
                />
              </section>
            ) : (
              <dl className="ficha">
                <dt>Inicio</dt>
                <dd>{formatearFecha(d.inicio)}</dd>
                <dt>Fin</dt>
                <dd>{formatearFecha(d.fin)}</dd>
                <dt>Duración</dt>
                <dd>{formatearDuracion(d.duracion_s)}</dd>
                <dt>Intentos</dt>
                <dd>{d.intentos}</dd>
              </dl>
            )}

            {d.error?.detalle && (
              <details className="plegable">
                <summary>Detalle técnico del último error</summary>
                <p className="hint">
                  {d.error.tipo} · {d.error.reintentable ? "reintentable" : "no reintentable"}
                </p>
                <pre className="bloque-json">{d.error.mensaje}</pre>
                <pre className="bloque-json">{d.error.detalle}</pre>
              </details>
            )}

            {llamadasSueltas.length > 0 && (
              <details className="plegable" open={historial.length === 0 && llamadasSueltas.length === 1}>
                <summary>
                  {historial.length > 0 ? "Llamadas a Claude sin intento asociado" : "Llamadas a Claude"} (
                  {llamadasSueltas.length})
                </summary>
                {llamadasSueltas.map((ll) => (
                  <Llamada key={ll.n} llamada={ll} abierta={llamadasSueltas.length === 1} />
                ))}
              </details>
            )}

            {d.salidas.length > 0 && (
              <details className="plegable">
                <summary>Archivos generados ({d.salidas.length})</summary>
                <ul className="salidas">
                  {d.salidas.map((s) => (
                    <li key={s.ruta} className={s.existe ? "" : "salida-ausente"}>
                      <code>{s.ruta}</code> <span className="hint">{s.existe ? formatearBytes(s.bytes) : "no existe"}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {d && esReintentable(paso) && (
          <footer className="modal-pie">
            {d.run_activo && <span className="hint">Hay una corrida en curso sobre esta sesión.</span>}
            {reintentarMutation.isSuccess && <span className="hint">Reintento lanzado.</span>}
            {reintentarMutation.isError && (
              <span className="error">{(reintentarMutation.error as Error).message}</span>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={!puedeReintentar || reintentarMutation.isPending || reintentarMutation.isSuccess}
              onClick={() => reintentarMutation.mutate()}
              title="Vuelve este paso y los siguientes a pendiente, borra lo que produjeron y los corre de nuevo"
            >
              {reintentarMutation.isPending ? "Lanzando..." : "Reintentar desde este paso"}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

/** El estado del paso en una línea, para entenderlo sin leer nada más. */
function Resumen({
  d,
  intentos,
  esperandoReintento,
}: {
  d: DetallePaso;
  intentos: IntentoPaso[];
  esperandoReintento: boolean;
}) {
  const fallos = intentos.filter((i) => i.resultado === "error").length;
  const n = Math.max(d.intentos, intentos.length);
  let icono = "○";
  let texto: string;
  let clase = "resumen-neutro";

  switch (d.estado) {
    case "ok":
      icono = "✓";
      clase = "resumen-ok";
      texto =
        n > 1
          ? `Completado en el intento #${n} (falló ${fallos} ${fallos === 1 ? "vez" : "veces"} antes) · ${formatearDuracion(d.duracion_s)}`
          : `Completado en ${formatearDuracion(d.duracion_s)}`;
      break;
    case "omitido":
      icono = "–";
      texto = "Omitido: este paso no aplicaba";
      break;
    case "error":
      if (d.error?.reintentable) {
        icono = "↻";
        clase = "resumen-reintentable";
        texto = `Falló ${n === 1 ? "1 vez" : `${n} veces`} (error pasajero): se agotaron los reintentos automáticos`;
      } else {
        icono = "✕";
        clase = "resumen-error";
        texto = "Falló: hay que corregir algo antes de reintentar";
      }
      break;
    case "corriendo": {
      icono = "◌";
      clase = esperandoReintento ? "resumen-reintentable" : "resumen-corriendo";
      const activo = subpasoActivo(d.subpasos);
      const enCurso = activo
        ? `${activo.label}${activo.pct !== null ? `: ${activo.pct.toFixed(0)}%` : "…"}`
        : `En curso desde las ${formatearHora(d.inicio)}`;
      texto = esperandoReintento
        ? `Falló el intento #${n}; se va a reintentar solo`
        : `${enCurso}${n > 1 ? ` (intento #${n})` : ""}`;
      break;
    }
    case "interrumpido":
      icono = "!";
      clase = "resumen-reintentable";
      texto = "Interrumpido: la corrida se detuvo con este paso a medias. Reintenta para continuar";
      break;
    case "esperando":
      icono = "⏸";
      texto = "Esperando tu revisión";
      break;
    default:
      texto = n > 0 ? "Pendiente: se va a correr de nuevo" : "Pendiente: todavía no se ejecutó";
  }

  return (
    <p className={`resumen-paso ${clase}`}>
      <span aria-hidden>{icono}</span> {texto}
    </p>
  );
}

/** El último error explicado en lenguaje humano, con la acción sugerida. */
function QuePaso({ error }: { error: ErrorPaso }) {
  const e = explicarError(error);
  return (
    <section className={`caja-error ${error.reintentable ? "caja-error-reintentable" : ""}`}>
      <h3>{e.titulo}</h3>
      <p>
        <strong>Qué hacer:</strong> {e.accion}
      </p>
    </section>
  );
}
