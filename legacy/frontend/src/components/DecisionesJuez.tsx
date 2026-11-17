import type { DecisionJuez } from "../api/types";
import { TIPO_MOMENTO_LABEL as TIPO_LABEL } from "../pasos";

/** Veredicto del juez por candidato: qué salió, qué no y por qué. */
export function DecisionesJuez({ decisiones }: { decisiones: DecisionJuez[] }) {
  const publicados = decisiones.filter((d) => d.publicar).length;
  return (
    <section>
      <h3 className="subtitulo">
        Decisiones · {publicados} de {decisiones.length} para publicar
      </h3>
      <ul className="decisiones">
        {decisiones.map((d) => (
          <li key={d.n} className={`decision ${d.publicar ? "decision-si" : "decision-no"}`}>
            <div className="decision-cabecera">
              <span aria-hidden>{d.publicar ? "✅" : "❌"}</span>
              <span className="hint">
                {d.inicio} → {d.fin}
              </span>
              <span className="pill">{TIPO_LABEL[d.tipo ?? ""] ?? d.tipo ?? "—"}</span>
              {d.fuerza !== null && <span className="hint">fuerza {d.fuerza}/10</span>}
            </div>
            {d.publicar && d.linea1 && (
              <div className="decision-titulo">
                {d.linea1}
                {d.linea2 && <> / {d.linea2}</>}
              </div>
            )}
            {d.en_juego && (
              <div>
                <strong>En juego:</strong> {d.en_juego}
              </div>
            )}
            {d.parecidos && d.parecidos.length > 0 && (
              <div className="hint">Se parece a: «{d.parecidos[0]}»</div>
            )}
            {d.por_que && <div className="hint">{d.por_que}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}
