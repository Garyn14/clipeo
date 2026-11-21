import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { FilaNegocioGlobal, GrupoNegocio, ReporteNegocio, ResumenConVariacion, VideoNegocio } from "../api/types";

// S17 · CLIP-74: sección Negocio. Vista global (todos los clientes) y minidashboard por cliente y mes.
// Los datos salen de la última "foto" de las cuentas (CLIP-73); "Actualizar" vuelve a leerlas. Seguidores: CLIP-75.

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function nombreMes(mes?: string | null): string {
  if (!mes) return "";
  return `${MESES[Number(mes.slice(5, 7)) - 1]} ${mes.slice(0, 4)}`;
}

function num(n?: number | null): string {
  return n === null || n === undefined ? "—" : Math.round(n).toLocaleString("es-PE");
}

function pct(n?: number | null): string {
  return n === null || n === undefined ? "—" : `${(n * 100).toLocaleString("es-PE", { maximumFractionDigits: 1 })}%`;
}

function fecha(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleString("es-PE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function Variacion({ v }: { v?: number | null }) {
  if (v === null || v === undefined) return <span className="ng-var ng-var-neutra">sin comparación</span>;
  const signo = v > 0 ? "▲" : v < 0 ? "▼" : "■";
  return <span className={`ng-var ${v > 0 ? "ng-var-sube" : v < 0 ? "ng-var-baja" : "ng-var-neutra"}`}>{signo} {pct(Math.abs(v))}</span>;
}

function Tarjetas({ r }: { r: ResumenConVariacion }) {
  const items: { t: string; v: string; var?: number | null; ant: string }[] = [
    { t: "Videos publicados", v: num(r.videos), var: r.variacion.videos, ant: num(r.anterior.videos) },
    { t: "Vistas", v: num(r.vistas), var: r.variacion.vistas, ant: num(r.anterior.vistas) },
    { t: "Interacciones", v: num(r.interacciones), var: r.variacion.interacciones, ant: num(r.anterior.interacciones) },
    { t: "Tasa de interacción", v: pct(r.tasa_interaccion), ant: pct(r.anterior.tasa_interaccion) },
    { t: "Vistas medianas por video", v: num(r.mediana_vistas), var: r.variacion.mediana_vistas, ant: num(r.anterior.mediana_vistas) },
  ];
  return (
    <div className="ng-tarjetas">
      {items.map((i) => (
        <div key={i.t} className="ng-tarjeta">
          <span className="ng-tarjeta-titulo">{i.t}</span>
          <strong className="ng-tarjeta-valor">{i.v}</strong>
          <span className="ng-tarjeta-meta">
            {i.var !== undefined && <Variacion v={i.var} />} mes anterior: {i.ant}
          </span>
        </div>
      ))}
    </div>
  );
}

function TablaGrupos({ titulo, grupos }: { titulo: string; grupos?: GrupoNegocio[] }) {
  return (
    <div className="ng-bloque">
      <h3>{titulo}</h3>
      {!grupos?.length ? (
        <p className="hint">Sin datos este mes.</p>
      ) : (
        <table className="ng-tabla">
          <thead>
            <tr><th></th><th>Videos</th><th>Vistas</th><th>Mediana</th><th>Interacción</th></tr>
          </thead>
          <tbody>
            {grupos.map((g) => (
              <tr key={g.grupo}>
                <td>{g.grupo}</td><td>{num(g.videos)}</td><td>{num(g.vistas)}</td><td>{num(g.mediana_vistas)}</td><td>{pct(g.tasa_interaccion)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ListaVideos({ titulo, videos }: { titulo: string; videos?: VideoNegocio[] }) {
  return (
    <div className="ng-bloque">
      <h3>{titulo}</h3>
      {!videos?.length ? (
        <p className="hint">Sin datos este mes.</p>
      ) : (
        <ol className="ng-videos">
          {videos.map((v) => (
            <li key={v.url}>
              <span className="ng-video-vistas">{num(v.vistas)}</span>
              <div className="ng-video-cuerpo">
                <a href={v.url} target="_blank" rel="noreferrer">{v.titulo || "(sin título)"}</a>
                <span className="fu-video-meta">
                  <span className="fu-plataforma">{v.plataforma === "tiktok" ? "TikTok" : "YouTube"}</span>
                  {v.clipeo ? `Clipeo · ${v.origen ?? ""}${v.tipo ? ` · ${v.tipo}` : ""}` : "no es de Clipeo"}
                  {" · "}{num(v.likes)} likes · {num(v.comentarios)} coment.
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Evolucion({ r }: { r: ReporteNegocio }) {
  const meses = r.evolucion ?? [];
  const max = Math.max(1, ...meses.map((m) => m.vistas));
  return (
    <div className="ng-bloque">
      <h3>Evolución (vistas de los videos publicados cada mes)</h3>
      <div className="ng-barras">
        {meses.map((m) => (
          <div key={m.mes} className={`ng-barra ${m.mes === r.mes ? "activa" : ""}`}>
            <span className="ng-barra-valor">{num(m.vistas)}</span>
            <div className="ng-barra-relleno" style={{ height: `${Math.max(2, (m.vistas / max) * 100)}%` }} />
            <span className="ng-barra-mes">{nombreMes(m.mes)}</span>
            <span className="ng-barra-meta">{m.videos} videos</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Global() {
  const [filas, setFilas] = useState<FilaNegocioGlobal[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.getNegocioGlobal().then(setFilas).catch((e) => setError(String(e)));
  }, []);
  return (
    <>
      {error && <div className="pub-alerta pub-alerta-error">{error}</div>}
      <table className="ng-tabla ng-global">
        <thead>
          <tr><th>Cliente</th><th>Mes</th><th>Videos</th><th>Vistas</th><th>vs mes anterior</th><th>Interacción</th><th>Datos al</th></tr>
        </thead>
        <tbody>
          {(filas ?? []).map((f) => (
            <tr key={f.nicho}>
              <td><Link to={`/negocio/${f.nicho}`}>{f.cliente}</Link></td>
              {f.resumen ? (
                <>
                  <td>{nombreMes(f.mes)}</td><td>{num(f.resumen.videos)}</td><td>{num(f.resumen.vistas)}</td>
                  <td><Variacion v={f.resumen.variacion.vistas} /></td><td>{pct(f.resumen.tasa_interaccion)}</td><td>{fecha(f.foto)}</td>
                </>
              ) : (
                <td colSpan={6} className="hint">Sin datos: entra y pulsa Actualizar.</td>
              )}
            </tr>
          ))}
          {filas?.length === 0 && <tr><td colSpan={7} className="hint">Ningún cliente tiene cuentas configuradas.</td></tr>}
        </tbody>
      </table>
    </>
  );
}

function Detalle({ nicho }: { nicho: string }) {
  const [r, setR] = useState<ReporteNegocio | null>(null);
  const [mes, setMes] = useState<string | undefined>(undefined);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");

  const cargar = useCallback((m?: string) => {
    setError("");
    api.getNegocio(nicho, m).then(setR).catch((e) => setError(String(e)));
  }, [nicho]);

  useEffect(() => { cargar(mes); }, [cargar, mes]);

  const actualizar = async () => {
    setCargando(true);
    setError("");
    try {
      setR(await api.actualizarNegocio(nicho, mes));
    } catch (e) {
      setError(String(e));
    } finally {
      setCargando(false);
    }
  };

  return (
    <>
      <div className="ng-cabecera">
        <div>
          <h2>{r?.cliente ?? nicho}</h2>
          <p className="hint">
            {r?.foto ? <>Datos al <strong>{fecha(r.foto)}</strong>. </> : "Todavía no se leyeron sus cuentas. "}
            "Vistas del mes" = vistas acumuladas de los videos publicados ese mes.
          </p>
        </div>
        <div className="ng-controles">
          {r?.meses && r.meses.length > 0 && (
            <select value={r.mes} onChange={(e) => setMes(e.target.value)}>
              {r.meses.map((m) => <option key={m} value={m}>{nombreMes(m)}</option>)}
            </select>
          )}
          <button className="btn btn-primary" onClick={actualizar} disabled={cargando}>
            {cargando ? "Leyendo cuentas…" : "Actualizar"}
          </button>
        </div>
      </div>

      {error && <div className="pub-alerta pub-alerta-error">{error}</div>}
      {cargando && <div className="pub-alerta pub-alerta-ok">Leyendo todas las cuentas del cliente: puede tardar un minuto.</div>}
      {r?.avisos?.map((a) => <div key={a} className="pub-alerta pub-alerta-warn">{a}</div>)}
      {r?.por_cuenta?.filter((c) => c.error).map((c) => (
        <div key={c.cuenta} className="pub-alerta pub-alerta-warn">No se pudo leer {c.cuenta}: {c.error}</div>
      ))}

      {r?.resumen && (
        <>
          <div className="ng-bloque">
            <h3>Resumen de {nombreMes(r.mes)} <span className="hint">vs {nombreMes(r.mes_anterior)}</span></h3>
            <Tarjetas r={r.resumen} />
          </div>

          <div className="ng-bloque">
            <h3>Por cuenta</h3>
            <table className="ng-tabla">
              <thead>
                <tr><th>Cuenta</th><th>Videos</th><th>Vistas</th><th>vs mes anterior</th><th>Mediana</th><th>Interacción</th><th>Videos en total</th></tr>
              </thead>
              <tbody>
                {r.por_cuenta?.map((c) => (
                  <tr key={c.cuenta}>
                    <td><span className="fu-plataforma">{c.plataforma === "tiktok" ? "TikTok" : "YouTube"}</span>
                      <a href={c.url} target="_blank" rel="noreferrer">{c.plataforma === "tiktok" ? c.cuenta : "canal"}</a></td>
                    <td>{num(c.videos)}</td><td>{num(c.vistas)}</td><td><Variacion v={c.variacion.vistas} /></td>
                    <td>{num(c.mediana_vistas)}</td><td>{pct(c.tasa_interaccion)}</td><td>{num(c.total_videos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="ng-columnas">
            <ListaVideos titulo={`Top ${r.top?.length ?? 0} del mes`} videos={r.top} />
            <ListaVideos titulo="Los que menos rindieron" videos={r.bottom} />
          </div>

          <div className="ng-columnas">
            <TablaGrupos titulo="Por origen" grupos={r.por_origen} />
            <TablaGrupos titulo="Clipeo vs resto de la cuenta" grupos={r.clipeo_vs_resto} />
          </div>
          <TablaGrupos titulo="Clips de Clipeo por tipo de momento" grupos={r.por_tipo} />

          {r.produccion && (
            <div className="ng-bloque">
              <h3>Producción de {nombreMes(r.mes)}</h3>
              <div className="ng-tarjetas">
                <div className="ng-tarjeta"><span className="ng-tarjeta-titulo">Clips revisados</span><strong className="ng-tarjeta-valor">{num(r.produccion.revisados)}</strong></div>
                <div className="ng-tarjeta"><span className="ng-tarjeta-titulo">Aprobados</span><strong className="ng-tarjeta-valor">{num(r.produccion.aprobados)}</strong></div>
                {Object.entries(r.produccion.enviados).map(([p, n]) => (
                  <div key={p} className="ng-tarjeta"><span className="ng-tarjeta-titulo">Enviados a {p === "tiktok" ? "TikTok" : "YouTube"}</span><strong className="ng-tarjeta-valor">{num(n)}</strong></div>
                ))}
              </div>
            </div>
          )}

          <Evolucion r={r} />

          <div className="ng-bloque ng-proximamente">
            <h3>Seguidores</h3>
            <p className="hint">Próximamente (CLIP-75): total, ganados en el mes y seguidores por cada 1.000 vistas.</p>
          </div>
        </>
      )}
    </>
  );
}

export function Negocio() {
  const { nicho } = useParams();
  const navigate = useNavigate();
  return (
    <section className="ng">
      <h1>Negocio</h1>
      <p className="hint">
        {nicho ? <a onClick={() => navigate("/negocio")} className="btn-link">← Todos los clientes</a>
          : "Cómo van las cuentas de cada cliente, mes a mes. Entra a un cliente y pulsa Actualizar para leer sus cuentas."}
      </p>
      {nicho ? <Detalle nicho={nicho} /> : <Global />}
    </section>
  );
}
