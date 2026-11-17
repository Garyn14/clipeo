import type { LlamadaIA } from "../api/types";
import { formatearDuracion } from "../pasos";

/** Una llamada a Claude de un paso: REQUEST (system + mensaje) y RESPONSE. */
export function Llamada({ llamada, abierta }: { llamada: LlamadaIA; abierta: boolean }) {
  const r = llamada.response;
  const usage = r?.meta?.usage as { input_tokens?: number; output_tokens?: number } | undefined;
  // El proveedor claude_cli ignora el id que pide el agente y usa AI_CLI_MODEL: mostrar el real
  const modelo = (r?.meta?.modelo as string | undefined) ?? llamada.request.modelo;

  return (
    <details className="llamada" open={abierta}>
      <summary>
        #{llamada.n}
        {modelo && <span className="hint"> · {modelo}</span>}
        {r && <span className="hint"> · {formatearDuracion(r.duracion_s)}</span>}
        {usage?.output_tokens !== undefined && (
          <span className="hint"> · {usage.output_tokens} tokens de salida</span>
        )}
        {llamada.error && <span className="pill pill-paso-error">error</span>}
      </summary>

      <h4>REQUEST</h4>
      {llamada.request.system && (
        <>
          <span className="etiqueta">system</span>
          <pre className="bloque-json">{llamada.request.system}</pre>
        </>
      )}
      <span className="etiqueta">mensaje</span>
      <pre className="bloque-json">{llamada.request.mensajes}</pre>

      <h4>RESPONSE</h4>
      {r && <pre className="bloque-json">{formatearRespuesta(r.texto)}</pre>}
      {llamada.error && (
        <pre className="bloque-json bloque-error">
          {llamada.error.tipo}: {llamada.error.mensaje}
        </pre>
      )}
      {!r && !llamada.error && <p className="hint">Sin respuesta todavía.</p>}
    </details>
  );
}

/** Si la respuesta es (o contiene) JSON, la muestra indentada. */
function formatearRespuesta(texto: string): string {
  const m = texto.match(/\{[\s\S]*\}/);
  if (!m) return texto;
  try {
    return JSON.stringify(JSON.parse(m[0]), null, 2);
  } catch {
    return texto;
  }
}
