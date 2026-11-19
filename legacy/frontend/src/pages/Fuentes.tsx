import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { FuentesNicho, ResumenEjecucion } from "../api/types";

// S14 · CLIP-63: fuentes estáticas por nicho. Todo manual ("Ejecutar"), sin cron.
export function Fuentes() {
  const [nichos, setNichos] = useState<string[]>([]);
  const [nicho, setNicho] = useState<string>("");
  const [datos, setDatos] = useState<FuentesNicho | null>(null);
  const [ventana, setVentana] = useState<"ultima" | "dias" | "ultimos">("ultima");
  const [valor, setValor] = useState<number>(7);
  const [resumen, setResumen] = useState<ResumenEjecucion | null>(null);
  const [elegidos, setElegidos] = useState<Set<string>>(new Set());
  const [cargando, setCargando] = useState(false);
  const [mensaje, setMensaje] = useState<string>("");

  useEffect(() => {
    api.getNichosFuentes().then((n) => {
      setNichos(n);
      if (n.length) setNicho(n[0]);
    }).catch((e) => setMensaje(String(e)));
  }, []);

  const recargar = useCallback(() => {
    if (!nicho) return;
    api.getFuentes(nicho).then(setDatos).catch((e) => setMensaje(String(e)));
  }, [nicho]);

  useEffect(recargar, [recargar]);

  const ejecutar = async () => {
    setCargando(true);
    setMensaje("");
    try {
      const body = ventana === "dias" ? { dias: valor } : ventana === "ultimos" ? { ultimos: valor } : {};
      setResumen(await api.ejecutarFuentes(nicho, body));
      setElegidos(new Set());
      recargar();
    } catch (e) {
      setMensaje(String(e));
    } finally {
      setCargando(false);
    }
  };

  const procesar = async (ids: string[]) => {
    if (!ids.length) return;
    try {
      const r = await api.procesarFuentes(nicho, ids);
      setMensaje(`Procesando ${r.iniciado.length} video(s) en segundo plano (log: ${r.log}). Aparecerán en Sesiones.`);
      setElegidos(new Set());
      setTimeout(recargar, 2000);
    } catch (e) {
      setMensaje(String(e));
    }
  };

  const alternar = (id: string) => {
    const s = new Set(elegidos);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setElegidos(s);
  };

  return (
    <section>
      <h2>Fuentes</h2>
      <p className="hint">
        Canales fijos de cada cliente. "Ejecutar" revisa lo nuevo desde la última vez, descarta lo repetido y lo que no
        menciona al cliente (en medios), y deja los candidatos listos para procesar.
      </p>

      {nichos.length > 1 && (
        <select value={nicho} onChange={(e) => setNicho(e.target.value)}>
          {nichos.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      )}

      {datos && (
        <>
          <h3>Canales {datos.activo ? "" : "(nicho inactivo)"}</h3>
          <table>
            <thead><tr><th>Canal</th><th>Rol</th><th>Activo</th><th>Última revisión</th></tr></thead>
            <tbody>
              {datos.canales.map((c) => (
                <tr key={c.url}>
                  <td><a href={c.url} target="_blank" rel="noreferrer">{c.nombre}</a></td>
                  <td>{c.rol === "propio" ? "propio (entra todo)" : "medios (filtrado)"}</td>
                  <td>{c.activo === false ? "no" : "sí"}</td>
                  <td>{c.ultima_revision ? new Date(c.ultima_revision).toLocaleString() : "nunca"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Ejecutar</h3>
          <div>
            <label>
              <input type="radio" checked={ventana === "ultima"} onChange={() => setVentana("ultima")} /> Desde la
              última revisión (la primera vez: {datos.ventana_inicial_dias} días)
            </label>{" "}
            <label>
              <input type="radio" checked={ventana === "dias"} onChange={() => setVentana("dias")} /> Últimos
            </label>{" "}
            <label>
              <input type="radio" checked={ventana === "ultimos"} onChange={() => setVentana("ultimos")} /> Últimos N
              videos por canal
            </label>{" "}
            {ventana !== "ultima" && (
              <input type="number" min={1} max={60} value={valor} style={{ width: 60 }}
                     onChange={(e) => setValor(Number(e.target.value))} />
            )}
            {ventana === "dias" && " días"}{" "}
            <button onClick={ejecutar} disabled={cargando || !datos.activo}>
              {cargando ? "Revisando..." : "Ejecutar"}
            </button>
          </div>
          {resumen && (
            <ul className="hint">
              {resumen.canales.map((c) => (
                <li key={c.canal}>
                  {c.canal}: {c.error ? `⚠ ${c.error}` : `${c.nuevos} nuevo(s), ${c.descartados} descartado(s)`}
                </li>
              ))}
            </ul>
          )}

          <h3>Candidatos ({datos.candidatos.length})</h3>
          {!datos.colab.vivo && (
            <p className="hint" style={{ color: "#b45309" }}>
              ⚠ Colab no está disponible ({datos.colab.motivo}): levántalo antes de procesar.
            </p>
          )}
          {datos.candidatos.length > 0 && (
            <div>
              <button onClick={() => procesar([...elegidos])} disabled={!elegidos.size}>
                Procesar elegidos ({elegidos.size})
              </button>{" "}
              <button onClick={() => procesar(datos.candidatos.map((c) => c.id))}>Procesar todos</button>
            </div>
          )}
          <table>
            <tbody>
              {datos.candidatos.map((c) => (
                <tr key={c.id}>
                  <td><input type="checkbox" checked={elegidos.has(c.id)} onChange={() => alternar(c.id)} /></td>
                  <td>{c.canal} <span className="pill">{c.rol}</span></td>
                  <td><a href={c.url} target="_blank" rel="noreferrer">{c.titulo}</a></td>
                  <td>{(c.publicado || "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Historial</h3>
          <table>
            <thead><tr><th>Detectado</th><th>Canal</th><th>Video</th><th>Estado</th></tr></thead>
            <tbody>
              {datos.historial.map((h) => (
                <tr key={h.id}>
                  <td>{(h.detectado || "").slice(0, 16).replace("T", " ")}</td>
                  <td>{h.canal}</td>
                  <td>{h.titulo}</td>
                  <td>{h.estado}{h.motivo ? ` · ${h.motivo}` : ""}{h.sesion ? ` · ${h.sesion}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {mensaje && <p className="hint">{mensaje}</p>}
    </section>
  );
}
