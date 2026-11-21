import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { AdministrarFuentes } from "../components/AdministrarFuentes";
import type { ClienteFuentes, FuentesNicho, ResumenEjecucion, VideoFuente } from "../api/types";

// S14 · CLIP-63: fuentes estáticas por cliente. Flujo guiado: elegir cliente → buscar → elegir y procesar.
// Todo manual ("Buscar ahora"), sin cron.

type Ventana = "ultima" | "dias" | "ultimos";
type FiltroHistorial = "todos" | "nuevo" | "procesando" | "procesado" | "descartado" | "error";

const ESTADOS: Record<string, { texto: string; clase: string }> = {
  nuevo: { texto: "Por procesar", clase: "pill-warn" },
  procesando: { texto: "Procesando", clase: "pill-corriendo" },
  procesado: { texto: "Procesado", clase: "pill-ok" },
  descartado: { texto: "Descartado", clase: "pill-muted" },
  error: { texto: "Error", clase: "pill-fallido" },
};

function fechaCorta(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString("es-PE", { day: "numeric", month: "short" });
}

function haceCuanto(iso?: string | null): string {
  if (!iso) return "nunca";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (isNaN(min)) return "—";
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} días`;
}

export function Fuentes() {
  const [clientes, setClientes] = useState<ClienteFuentes[]>([]);
  const [nicho, setNicho] = useState("");
  const [datos, setDatos] = useState<FuentesNicho | null>(null);
  const [ventana, setVentana] = useState<Ventana>("ultima");
  const [valor, setValor] = useState(7);
  const [resumen, setResumen] = useState<ResumenEjecucion | null>(null);
  const [elegidos, setElegidos] = useState<Set<string>>(new Set());
  const [buscando, setBuscando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [filtro, setFiltro] = useState<FiltroHistorial>("todos");

  const cargarClientes = useCallback(() => {
    api.getNichosFuentes().then((c) => {
      setClientes(c);
      setNicho((actual) => actual || (c[0]?.nicho ?? ""));
    }).catch((e) => setAviso({ tipo: "error", texto: String(e) }));
  }, []);

  const recargar = useCallback(() => {
    if (!nicho) return;
    api.getFuentes(nicho).then(setDatos).catch((e) => setAviso({ tipo: "error", texto: String(e) }));
  }, [nicho]);

  useEffect(cargarClientes, [cargarClientes]);
  useEffect(() => {
    setDatos(null);
    setResumen(null);
    setElegidos(new Set());
    recargar();
  }, [recargar]);

  const buscar = async () => {
    setBuscando(true);
    setAviso(null);
    try {
      const body = ventana === "dias" ? { dias: valor } : ventana === "ultimos" ? { ultimos: valor } : {};
      setResumen(await api.ejecutarFuentes(nicho, body));
      recargar();
      cargarClientes();
    } catch (e) {
      setAviso({ tipo: "error", texto: String(e) });
    } finally {
      setBuscando(false);
    }
  };

  const procesar = async () => {
    const ids = [...elegidos];
    if (!ids.length) return;
    try {
      const r = await api.procesarFuentes(nicho, ids);
      setAviso({ tipo: "ok", texto: `Procesando ${r.iniciado.length} video(s) en segundo plano. Sigue el avance en Sesiones.` });
      setElegidos(new Set());
      setTimeout(() => { recargar(); cargarClientes(); }, 2000);
    } catch (e) {
      setAviso({ tipo: "error", texto: String(e) });
    }
  };

  const alternar = (id: string) => {
    const s = new Set(elegidos);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setElegidos(s);
  };

  const candidatos = datos?.candidatos ?? [];
  const todosElegidos = candidatos.length > 0 && candidatos.every((c) => elegidos.has(c.id));
  const ultimaRevision = useMemo(() => {
    const fechas = (datos?.canales ?? []).map((c) => c.ultima_revision).filter(Boolean) as string[];
    return fechas.sort().pop() ?? null;
  }, [datos]);
  const conteo = useMemo(() => {
    const c: Record<string, number> = {};
    (datos?.historial ?? []).forEach((h) => { c[h.estado] = (c[h.estado] ?? 0) + 1; });
    return c;
  }, [datos]);
  const historial = (datos?.historial ?? []).filter((h) => filtro === "todos" || h.estado === filtro);
  const totalNuevos = resumen?.canales.reduce((a, c) => a + (c.nuevos || 0), 0) ?? 0;
  const totalDescartados = resumen?.canales.reduce((a, c) => a + (c.descartados || 0), 0) ?? 0;
  const conError = resumen?.canales.filter((c) => c.error) ?? [];
  const propios = datos?.canales.filter((c) => c.rol === "propio").length ?? 0;
  const medios = (datos?.canales.length ?? 0) - propios;

  return (
    <section className="fu">
      <h1>Fuentes</h1>
      <p className="hint">Videos nuevos de los canales fijos de cada cliente, listos para convertir en clips.</p>

      {/* Cliente */}
      <div className="fu-clientes">
        {clientes.map((c) => (
          <button key={c.nicho} className={`fu-cliente ${c.nicho === nicho ? "activo" : ""}`} onClick={() => setNicho(c.nicho)}>
            <span className="fu-cliente-nombre">{c.cliente}</span>
            <span className="fu-cliente-meta">{c.canales} canales</span>
            {c.candidatos > 0 && <span className="pill pill-warn">{c.candidatos} por procesar</span>}
          </button>
        ))}
        {clientes.length === 0 && <p className="hint">Ningún cliente tiene fuentes configuradas.</p>}
      </div>

      {aviso && <div className={`pub-alerta pub-alerta-${aviso.tipo}`}>{aviso.texto}</div>}

      {datos && (
        <>
          {!datos.activo && <div className="pub-alerta pub-alerta-warn">Las fuentes de {datos.cliente} están desactivadas.</div>}

          {/* Paso 1 */}
          <div className="fu-paso">
            <div className="fu-paso-cabecera">
              <span className="fu-num">1</span>
              <div>
                <h2>Buscar videos nuevos</h2>
                <p className="hint">
                  Revisa {datos.canales.length} canales de {datos.cliente} ({propios} propio{propios === 1 ? "" : "s"}, {medios} de
                  TV). Última búsqueda: <strong>{haceCuanto(ultimaRevision)}</strong>.
                </p>
              </div>
            </div>
            <div className="fu-buscar">
              <select value={ventana} onChange={(e) => setVentana(e.target.value as Ventana)}>
                <option value="ultima">Desde la última búsqueda</option>
                <option value="dias">De los últimos días…</option>
                <option value="ultimos">Los últimos videos de cada canal…</option>
              </select>
              {ventana !== "ultima" && (
                <label className="fu-valor">
                  <input type="number" min={1} max={60} value={valor} onChange={(e) => setValor(Number(e.target.value))} />
                  {ventana === "dias" ? "días" : "videos"}
                </label>
              )}
              <button className="btn btn-primary" onClick={buscar} disabled={buscando || !datos.activo}>
                {buscando ? "Buscando…" : "Buscar ahora"}
              </button>
            </div>
            {resumen && (
              <div className="fu-resumen">
                <strong>{totalNuevos === 0 ? "No hay videos nuevos." : `${totalNuevos} video(s) nuevo(s) para procesar.`}</strong>{" "}
                <span className="hint">
                  {totalDescartados} descartado(s) por repetidos o porque no hablan de {datos.cliente}.
                </span>
                {conError.length > 0 && (
                  <div className="pub-alerta pub-alerta-warn">
                    No se pudo revisar: {conError.map((c) => c.canal).join(", ")}.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Paso 2 */}
          <div className="fu-paso">
            <div className="fu-paso-cabecera">
              <span className="fu-num">2</span>
              <div>
                <h2>Elegir qué convertir en clips {candidatos.length > 0 && <span className="pill pill-warn">{candidatos.length}</span>}</h2>
                <p className="hint">Cada video elegido se transcribe en Colab y pasa por el detector; sus clips llegan a la revisión.</p>
              </div>
            </div>

            <div className={`pub-alerta ${datos.colab.vivo ? "pub-alerta-ok" : "pub-alerta-error"}`}>
              {datos.colab.vivo
                ? "● Colab conectado: se puede procesar."
                : "● Colab apagado: levántalo (o pídeselo a Claude) antes de procesar."}
            </div>

            {candidatos.length === 0 ? (
              <p className="fu-vacio">No hay videos pendientes. Pulsa <strong>Buscar ahora</strong> en el paso 1.</p>
            ) : (
              <>
                <label className="fu-todos">
                  <input type="checkbox" checked={todosElegidos}
                         onChange={() => setElegidos(todosElegidos ? new Set() : new Set(candidatos.map((c) => c.id)))} />
                  Seleccionar todos
                </label>
                <ul className="fu-lista">
                  {candidatos.map((c: VideoFuente) => (
                    <li key={c.id} className={`fu-video ${elegidos.has(c.id) ? "elegido" : ""}`} onClick={() => alternar(c.id)}>
                      <input type="checkbox" checked={elegidos.has(c.id)} onChange={() => alternar(c.id)} onClick={(e) => e.stopPropagation()} />
                      <div className="fu-video-cuerpo">
                        <span className="fu-video-titulo">{c.titulo}</span>
                        <span className="fu-video-meta">
                          {c.canal} · {c.rol === "propio" ? "canal propio" : "TV / prensa"} · {fechaCorta(c.publicado)}
                        </span>
                      </div>
                      {c.url && (
                        <a href={c.url} target="_blank" rel="noreferrer" className="btn-link" onClick={(e) => e.stopPropagation()}>
                          Ver ↗
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
                <button className="btn btn-primary" onClick={procesar} disabled={!elegidos.size || !datos.colab.vivo}>
                  Procesar {elegidos.size || ""} video{elegidos.size === 1 ? "" : "s"}
                </button>
              </>
            )}
          </div>

          {/* Detalle */}
          <details className="plegable">
            <summary>Historial ({datos.historial.length})</summary>
            <div className="pub-tabs fu-filtros">
              {(["todos", "nuevo", "procesando", "procesado", "descartado", "error"] as FiltroHistorial[]).map((f) => (
                <a key={f} className={filtro === f ? "activo" : ""} onClick={() => setFiltro(f)}>
                  {f === "todos" ? "Todos" : ESTADOS[f].texto} ({f === "todos" ? datos.historial.length : conteo[f] ?? 0})
                </a>
              ))}
            </div>
            <ul className="fu-historial">
              {historial.map((h) => (
                <li key={h.id}>
                  <span className={`pill ${ESTADOS[h.estado]?.clase ?? "pill-muted"}`}>{ESTADOS[h.estado]?.texto ?? h.estado}</span>
                  <div className="fu-video-cuerpo">
                    <span>{h.titulo}</span>
                    <span className="fu-video-meta">
                      {h.canal} · {fechaCorta(h.detectado)}{h.motivo ? ` · ${h.motivo}` : ""}{h.sesion ? ` · sesión ${h.sesion}` : ""}
                    </span>
                  </div>
                </li>
              ))}
              {historial.length === 0 && <li className="hint">Nada en esta categoría.</li>}
            </ul>
          </details>

          <details className="plegable fu-administrar">
            <summary>Administrar fuentes de {datos.cliente} ({datos.canales.length} canales)</summary>
            <AdministrarFuentes datos={datos} alCambiar={() => { recargar(); cargarClientes(); }} />
          </details>
        </>
      )}
    </section>
  );
}
