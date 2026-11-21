import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { FuentesNicho, ResultadoLink, TipoFuente, VistaPreviaCanal } from "../api/types";

// CLIP-66/67: administrar las fuentes de un cliente (canales, tipo de fuente, lista manual, palabras clave).
// Todo se guarda en investigacion/<nicho>/fuentes.yaml (la fuente de verdad sigue siendo el YAML).

const ROLES = [
  { valor: "propio", texto: "Propio (entra todo)" },
  { valor: "medios", texto: "TV / prensa (solo si lo menciona)" },
];

function mensaje(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function AdministrarFuentes({ datos, alCambiar }: { datos: FuentesNicho; alCambiar: () => void }) {
  const nicho = datos.nicho;
  const [tipos, setTipos] = useState<TipoFuente[]>([]);
  const [tipo, setTipo] = useState("youtube");
  const [entrada, setEntrada] = useState("");
  // Sin rol preseleccionado: obliga a elegir Propio o TV / prensa (un canal del cliente quedaba como TV por descuido)
  const [rol, setRol] = useState("");
  const [vista, setVista] = useState<VistaPreviaCanal | null>(null);
  const [links, setLinks] = useState("");
  const [resultados, setResultados] = useState<ResultadoLink[] | null>(null);
  const [palabras, setPalabras] = useState<string[]>(datos.palabras_clave);
  const [nuevaPalabra, setNuevaPalabra] = useState("");
  const [ocupado, setOcupado] = useState(false);
  // Confirmación en la página (los diálogos nativos como window.confirm se bloquean en algunos navegadores)
  const [aQuitar, setAQuitar] = useState<string | null>(null);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);

  useEffect(() => { api.getTiposFuente().then(setTipos).catch(() => setTipos([])); }, []);
  useEffect(() => { setPalabras(datos.palabras_clave); }, [datos.palabras_clave]);

  const tipoActual = tipos.find((t) => t.clave === tipo);
  // CLIP-70: cada tipo admite ciertos roles (Kick: solo Propio, sus títulos no sirven para filtrar)
  const rolesDe = (clave?: string) => {
    const admitidos = tipos.find((t) => t.clave === clave)?.roles;
    return admitidos ? ROLES.filter((r) => admitidos.includes(r.valor)) : ROLES;
  };

  const accion = async (fn: () => Promise<void>, ok?: string) => {
    setOcupado(true);
    setAviso(null);
    try {
      await fn();
      if (ok) setAviso({ tipo: "ok", texto: ok });
      alCambiar();
    } catch (e) {
      setAviso({ tipo: "error", texto: mensaje(e) });
    } finally {
      setOcupado(false);
    }
  };

  const verPrevia = () => accion(async () => {
    setVista(await api.previsualizarCanal(nicho, { plataforma: tipo, entrada }));
  });

  const guardarCanal = () => accion(async () => {
    await api.agregarCanal(nicho, { plataforma: tipo, entrada, rol });
    setVista(null);
    setEntrada("");
    setRol("");
  }, "Canal agregado: entra en la próxima búsqueda.");

  const agregarSugerencia = (url: string, canal: string) => accion(async () => {
    await api.agregarCanal(nicho, { plataforma: "youtube", entrada: url, rol: "medios", nombre: canal });
  }, `«${canal}» agregado como TV / prensa.`);

  const agregarLinks = () => accion(async () => {
    const r = await api.agregarLinks(nicho, links.split(/\s+/).filter(Boolean), rol);
    setResultados(r.resultados);
    if (r.resultados.some((x) => x.ok)) setLinks("");
  });

  const guardarPalabras = (lista: string[]) => accion(async () => {
    setPalabras((await api.guardarPalabras(nicho, lista)).palabras);
  });

  return (
    <div className="fu-paso">
      <div className="fu-paso-cabecera">
        <span className="fu-num">⚙</span>
        <div>
          <h2>Fuentes de {datos.cliente}</h2>
          <p className="hint">Qué canales se revisan, con qué rol y qué palabras identifican al cliente en la TV.</p>
        </div>
      </div>

      {aviso && <div className={`pub-alerta pub-alerta-${aviso.tipo}`}>{aviso.texto}</div>}

      {/* Canales */}
      <ul className="fu-lista">
        {datos.canales.map((c) => (
          <li key={c.url} className={`fu-canal ${c.activo === false ? "pausado" : ""}`}>
            <label className="fu-switch" title={c.activo === false ? "Pausado: no se revisa" : "Activo"}>
              <input type="checkbox" checked={c.activo !== false} disabled={ocupado}
                     onChange={(e) => accion(() => api.editarCanal(nicho, { url: c.url, activo: e.target.checked }).then(() => undefined))} />
              {c.activo === false ? "Pausado" : "Activo"}
            </label>
            <div className="fu-video-cuerpo">
              <a href={c.url} target="_blank" rel="noreferrer">{c.nombre}</a>
              <span className="fu-video-meta">
                {tipos.find((t) => t.clave === c.plataforma)?.nombre ?? c.plataforma} · {c.aportes?.procesado ?? 0} procesados ·{" "}
                {c.aportes?.nuevo ?? 0} por procesar · {c.aportes?.descartado ?? 0} descartados
              </span>
            </div>
            <select value={c.rol} disabled={ocupado}
                    onChange={(e) => accion(() => api.editarCanal(nicho, { url: c.url, rol: e.target.value }).then(() => undefined))}>
              {rolesDe(c.plataforma).map((r) => <option key={r.valor} value={r.valor}>{r.texto}</option>)}
            </select>
            {aQuitar === c.url ? (
              <span className="fu-confirmar">
                ¿Quitar? El historial se conserva.
                <button className="btn btn-danger" disabled={ocupado}
                        onClick={() => accion(() => api.quitarCanal(nicho, c.url).then(() => setAQuitar(null)),
                          `«${c.nombre}» quitado.`)}>
                  Sí, quitar
                </button>
                <button className="btn-link" onClick={() => setAQuitar(null)}>Cancelar</button>
              </span>
            ) : (
              <button className="btn-link fu-quitar" disabled={ocupado} onClick={() => setAQuitar(c.url)}>Quitar</button>
            )}
          </li>
        ))}
      </ul>

      {/* Agregar */}
      <h3 className="fu-subtitulo">Agregar fuente</h3>
      <div className="fu-buscar">
        <select value={tipo} onChange={(e) => { setTipo(e.target.value); setVista(null); setResultados(null); setRol(""); }}>
          {tipos.map((t) => (
            <option key={t.clave} value={t.clave} disabled={!t.implementado}>
              {t.nombre}{t.implementado ? "" : " (próximamente)"}
            </option>
          ))}
        </select>
        <select value={rol} onChange={(e) => setRol(e.target.value)} className={rol ? "" : "fu-falta"}>
          <option value="" disabled>Elige el rol…</option>
          {rolesDe(tipo).map((r) => <option key={r.valor} value={r.valor}>{r.texto}</option>)}
        </select>
        {!rol && <span className="hint">Propio = canal del cliente (entra todo) · TV / prensa = terceros (solo si lo mencionan)</span>}
      </div>

      {tipoActual?.automatico !== false ? (
        <>
          <div className="fu-buscar">
            <input className="fu-entrada" value={entrada} placeholder={tipoActual?.pide ?? "Link del canal"}
                   onChange={(e) => { setEntrada(e.target.value); setVista(null); }} />
            <button className="btn btn-secondary" onClick={verPrevia} disabled={ocupado || !entrada.trim() || !rol}>
              {ocupado && !vista ? "Buscando…" : "Vista previa"}
            </button>
          </div>
          {vista && (
            <div className="fu-previa">
              <strong>{vista.nombre}</strong> <span className="hint">· últimos videos:</span>
              <ul>
                {vista.videos.map((v) => (
                  <li key={v.id}><a href={v.url} target="_blank" rel="noreferrer">{v.titulo}</a>{" "}
                    <span className="fu-video-meta">{(v.publicado ?? "").slice(0, 10)}</span></li>
                ))}
              </ul>
              <button className="btn btn-primary" onClick={guardarCanal} disabled={ocupado || !rol}>Guardar canal</button>
            </div>
          )}
        </>
      ) : (
        <>
          <textarea className="fu-entrada fu-links" rows={3} value={links} placeholder={tipoActual?.pide}
                    onChange={(e) => setLinks(e.target.value)} />
          <button className="btn btn-primary" onClick={agregarLinks} disabled={ocupado || !links.trim() || !rol}>
            {ocupado ? "Revisando links…" : "Agregar a candidatos"}
          </button>
          {resultados && (
            <ul className="fu-historial">
              {resultados.map((r) => (
                <li key={r.link}>
                  <span className={`pill ${r.ok ? "pill-ok" : "pill-fallido"}`}>{r.ok ? "Agregado" : "No"}</span>
                  <div className="fu-video-cuerpo">
                    <span>{r.titulo ?? r.link}</span>
                    {!r.ok && <span className="fu-video-meta">{r.motivo}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {/* Palabras clave */}
      <h3 className="fu-subtitulo">Palabras que identifican a {datos.cliente}</h3>
      <p className="hint">Un video de TV o prensa entra solo si su título o descripción menciona alguna (además del nombre y los apodos del cliente).</p>
      <div className="fu-chips">
        {palabras.map((p) => (
          <span key={p} className="fu-chip">
            {p}
            <button aria-label={`Quitar ${p}`} disabled={ocupado} onClick={() => guardarPalabras(palabras.filter((x) => x !== p))}>×</button>
          </span>
        ))}
        <input className="fu-chip-entrada" value={nuevaPalabra} placeholder="Agregar palabra…"
               onChange={(e) => setNuevaPalabra(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === "Enter" && nuevaPalabra.trim()) {
                   guardarPalabras([...palabras, nuevaPalabra.trim()]);
                   setNuevaPalabra("");
                 }
               }} />
      </div>

      {/* Sugerencias */}
      {datos.sugerencias.length > 0 && (
        <>
          <h3 className="fu-subtitulo">Canales sugeridos</h3>
          <p className="hint">Aparecieron en búsquedas sobre {datos.cliente} y todavía no están en la lista.</p>
          <ul className="fu-historial">
            {datos.sugerencias.map((s) => (
              <li key={s.canal}>
                <div className="fu-video-cuerpo">
                  <span>{s.canal}</span>
                  <span className="fu-video-meta">{s.apariciones} aparición(es)</span>
                </div>
                <button className="btn btn-secondary" disabled={ocupado || !s.url} onClick={() => agregarSugerencia(s.url, s.canal)}>
                  Agregar
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
