import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ErrorFila, ReintentoLoteResultado } from "../api/types";
import { PASO_LABEL, formatearFecha } from "../pasos";

const claveFila = (f: ErrorFila) => `${f.session_id}|${f.chunk ?? "_"}|${f.paso}`;

export function Errores() {
  const queryClient = useQueryClient();
  const [paso, setPaso] = useState("");
  const [tipo, setTipo] = useState<"" | "si" | "no">("");
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [resultado, setResultado] = useState<ReintentoLoteResultado[] | null>(null);

  const erroresQuery = useQuery({
    queryKey: ["errores", paso, tipo],
    queryFn: () =>
      api.getErrores({
        paso: paso || undefined,
        reintentable: tipo === "" ? undefined : tipo === "si",
      }),
    refetchInterval: 10000,
  });

  const filas = erroresQuery.data ?? [];
  const seleccionables = filas.filter((f) => !f.run_activo);
  const todasMarcadas = seleccionables.length > 0 && seleccionables.every((f) => seleccion.has(claveFila(f)));

  const reintentarMutation = useMutation({
    mutationFn: () =>
      api.reintentarLote(
        filas
          .filter((f) => seleccion.has(claveFila(f)))
          .map((f) => ({ session_id: f.session_id, paso: f.paso, chunk: f.chunk })),
      ),
    onSuccess: (res) => {
      setResultado(res);
      setSeleccion(new Set());
      queryClient.invalidateQueries({ queryKey: ["errores"] });
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const alternar = (f: ErrorFila) => {
    const nueva = new Set(seleccion);
    const k = claveFila(f);
    if (nueva.has(k)) nueva.delete(k);
    else nueva.add(k);
    setSeleccion(nueva);
  };

  const alternarTodas = () =>
    setSeleccion(todasMarcadas ? new Set() : new Set(seleccionables.map(claveFila)));

  return (
    <section className="panel">
      <h1>Instancias con error</h1>
      <p className="hint">
        Pasos que quedaron en error en cualquier sesión. Los reintentables (límite de uso de Claude,
        Colab caído, red) ya agotaron sus reintentos automáticos; los no reintentables necesitan
        corregir la causa antes.
      </p>

      <div className="filtros">
        <label>
          Paso
          <select value={paso} onChange={(e) => setPaso(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(PASO_LABEL)
              .filter(([k]) => k !== "revision" && k !== "fin")
              .map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
          </select>
        </label>
        <label>
          Tipo
          <select value={tipo} onChange={(e) => setTipo(e.target.value as "" | "si" | "no")}>
            <option value="">Todos</option>
            <option value="si">Reintentable</option>
            <option value="no">No reintentable</option>
          </select>
        </label>
        <button
          type="button"
          className="btn btn-primary"
          disabled={seleccion.size === 0 || reintentarMutation.isPending}
          onClick={() => reintentarMutation.mutate()}
        >
          {reintentarMutation.isPending ? "Lanzando..." : `Reintentar seleccionados (${seleccion.size})`}
        </button>
      </div>

      {reintentarMutation.isError && <p className="error">{(reintentarMutation.error as Error).message}</p>}
      {resultado && (
        <ul className="resultado-lote">
          {resultado.map((r) => (
            <li key={`${r.session_id}-${r.paso}`} className={r.error ? "error" : "hint"}>
              {r.session_id} · {PASO_LABEL[r.paso]}: {r.error ?? "reintento lanzado"}
            </li>
          ))}
        </ul>
      )}

      {erroresQuery.isLoading && <p className="hint">Cargando...</p>}
      {erroresQuery.isError && <p className="error">{(erroresQuery.error as Error).message}</p>}
      {!erroresQuery.isLoading && filas.length === 0 && <p className="hint">Sin errores.</p>}

      {filas.length > 0 && (
        <div className="tabla-scroll">
          <table className="tabla-sesiones">
            <thead>
              <tr>
                <th>
                  <input type="checkbox" checked={todasMarcadas} onChange={alternarTodas} aria-label="Todas" />
                </th>
                <th>Sesión</th>
                <th>Paso</th>
                <th>Descripción</th>
                <th>Detalle</th>
                <th>Fecha/hora error</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f) => (
                <tr key={claveFila(f)}>
                  <td>
                    <input
                      type="checkbox"
                      checked={seleccion.has(claveFila(f))}
                      onChange={() => alternar(f)}
                      disabled={f.run_activo}
                      title={f.run_activo ? "La sesión tiene una corrida en curso" : undefined}
                    />
                  </td>
                  <td>
                    <Link to={`/sesiones/${f.session_id}`}>{f.session_id}</Link>
                  </td>
                  <td>
                    {PASO_LABEL[f.paso]}
                    {f.chunk && <span className="hint"> · {f.chunk}</span>}
                  </td>
                  <td>
                    <span className={`pill ${f.reintentable ? "pill-error-reintentable" : "pill-paso-error"}`}>
                      {f.reintentable ? "Error reintentar" : "Error no reintentar"}
                    </span>
                  </td>
                  <td className="celda-mensaje" title={f.mensaje}>
                    <strong>{f.tipo}</strong> {f.mensaje}
                  </td>
                  <td>{formatearFecha(f.fecha)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
