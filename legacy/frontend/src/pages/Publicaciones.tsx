import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, NavLink, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ClienteFuentes, EstadoPublicacion, Plataforma, Publicacion, ResumenNicho } from "../api/types";
import { PageHeader, Vacio } from "../components/ui";
import { formatearFecha } from "../pasos";

/** Lo que cambia de una plataforma a otra en la pantalla. */
const PLATAFORMA_UI: Record<
  Plataforma,
  {
    nombre: string;
    entregado: string;
    columnaEntregado: string;
    marcarRecibido: string;
    marcarRecibidoAyuda: string;
    botonTexto: string;
    sinTexto: string;
  }
> = {
  tiktok: {
    nombre: "TikTok",
    entregado: "En tu bandeja",
    columnaEntregado: "En bandeja",
    marcarRecibido: "Llegó a la bandeja",
    marcarRecibidoAyuda: "Verificaste en la app que el borrador sí llegó",
    botonTexto: "texto para TikTok",
    sinTexto: "sin texto para TikTok",
  },
  youtube: {
    nombre: "YouTube Shorts",
    entregado: "Publicado",
    columnaEntregado: "Procesado",
    marcarRecibido: "Está en YouTube Studio",
    marcarRecibidoAyuda: "Verificaste en YouTube Studio que el video sí se subió",
    botonTexto: "texto enviado",
    sinTexto: "sin texto para YouTube",
  },
};

const PLATAFORMAS = Object.keys(PLATAFORMA_UI) as Plataforma[];

function estadoLabel(plataforma: Plataforma, estado: EstadoPublicacion): string {
  return estado === "en_bandeja" ? PLATAFORMA_UI[plataforma].entregado : ESTADO_LABEL[estado];
}

const ESTADO_LABEL: Record<EstadoPublicacion, string> = {
  en_cola: "En cola",
  enviando: "Enviando",
  en_bandeja: "En tu bandeja",
  sin_confirmar: "Sin confirmar",
  error: "Error",
  cancelado: "Cancelado",
};

const CUENTA_LABEL: Record<string, string> = {
  conectada: "Conectada",
  pausada: "Pausada",
  requiere_reconexion: "Requiere reconexión",
};

function hora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-PE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const ZONA = "America/Lima"; // la del backend: los horarios son de Lima

function diaClave(d: Date): string {
  return d.toLocaleDateString("es-PE", { timeZone: ZONA });
}

function horaCorta(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-PE", { timeZone: ZONA, hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "hoy 13:10" / "mañana 08:00" / "lun 13/10 08:00" */
function cuando(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hoy = new Date();
  const manana = new Date(hoy.getTime() + 86400000);
  if (diaClave(d) === diaClave(hoy)) return `hoy ${horaCorta(iso)}`;
  if (diaClave(d) === diaClave(manana)) return `mañana ${horaCorta(iso)}`;
  const dia = d.toLocaleDateString("es-PE", { timeZone: ZONA, weekday: "short", day: "2-digit", month: "2-digit" });
  return `${dia} ${horaCorta(iso)}`;
}

function hace(iso: string | null | undefined): string {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  return h < 24 ? `hace ${h} h ${min % 60} min` : `hace ${Math.floor(h / 24)} d`;
}

function Explicacion({ plataforma, minutos }: { plataforma: Plataforma; minutos: number }) {
  const comun =
    "Cada clip aprobado entra a la cola de su cliente en cada plataforma; las colas son independientes. " +
    `El backend revisa al arrancar y cada ${minutos} min: en cada horario envía un clip`;
  if (plataforma === "youtube") {
    return (
      <p className="hint">
        {comun} a YouTube con su título, descripción y tags, <strong>publicado como público</strong>. El seguimiento
        termina cuando YouTube confirma que el video está subido y procesado; si YouTube lo deja en otra visibilidad,
        queda anotado en las trazas.
      </p>
    );
  }
  return (
    <p className="hint">
      {comun} a TikTok como <strong>borrador a tu bandeja</strong> y tú lo activas en la app. El seguimiento termina
      cuando TikTok confirma que el borrador llegó.
    </p>
  );
}

// ── CLIP-85: Publicaciones por cliente ──

/** Un cliente con lo suyo en cada plataforma (resumen del motor + clientes con fuentes aunque no publiquen aún). */
interface ClientePublicacion {
  nicho: string;
  cliente: string;
  plataformas: Partial<Record<Plataforma, ResumenNicho>>;
}

const CLAVE_ULTIMO = "publicaciones.ultimoCliente";

function leerUltimo(): string {
  try {
    return localStorage.getItem(CLAVE_ULTIMO) ?? "";
  } catch {
    return "";
  }
}

function guardarUltimo(nicho: string): void {
  try {
    localStorage.setItem(CLAVE_ULTIMO, nicho);
  } catch {
    /* sin almacenamiento: no se recuerda, no pasa nada */
  }
}

function agruparClientes(nichos: ResumenNicho[], conFuentes: ClienteFuentes[]): ClientePublicacion[] {
  const mapa = new Map<string, ClientePublicacion>();
  for (const n of nichos) {
    const c = mapa.get(n.nicho) ?? { nicho: n.nicho, cliente: n.cliente || n.nicho, plataformas: {} };
    c.plataformas[n.plataforma] = n;
    mapa.set(n.nicho, c);
  }
  for (const f of conFuentes) {
    if (!mapa.has(f.nicho)) mapa.set(f.nicho, { nicho: f.nicho, cliente: f.cliente, plataformas: {} });
  }
  return [...mapa.values()].sort((a, b) => a.cliente.localeCompare(b.cliente, "es"));
}

export function Publicaciones() {
  const { nicho: nichoParam, plataforma: plataformaParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const conexion = searchParams.get("conexion");

  const resumenQuery = useQuery({
    queryKey: ["publicaciones-resumen"],
    queryFn: api.getResumenPublicaciones,
    refetchInterval: 10000,
  });
  const fuentesQuery = useQuery({ queryKey: ["fuentes-nichos"], queryFn: api.getNichosFuentes });

  // Enlaces viejos (/publicaciones/tiktok, /publicaciones/youtube) → vista de todos los clientes
  if (nichoParam && (PLATAFORMAS as string[]).includes(nichoParam)) {
    return <Navigate to={`/publicaciones?vista=todos${conexion ? `&${searchParams}` : ""}`} replace />;
  }
  if (nichoParam && !plataformaParam) return <Navigate to={`/publicaciones/${nichoParam}/tiktok`} replace />;

  const ultimo = leerUltimo();
  const verTodos = searchParams.get("vista") === "todos";
  if (!nichoParam && ultimo && !verTodos && !conexion) {
    return <Navigate to={`/publicaciones/${ultimo}/tiktok`} replace />;
  }

  const clientes = agruparClientes(resumenQuery.data?.nichos ?? [], fuentesQuery.data ?? []);
  const actual = nichoParam ? clientes.find((c) => c.nicho === nichoParam) : undefined;
  const plataforma: Plataforma = plataformaParam === "youtube" ? "youtube" : "tiktok";
  const minutos = Math.round((resumenQuery.data?.intervalo_s ?? 600) / 60);

  if (nichoParam && nichoParam !== ultimo) guardarUltimo(nichoParam);

  return (
    <section className="panel">
      <PageHeader
        seccion="Distribución · publicaciones"
        titulo={actual ? actual.cliente : "Publicaciones"}
        descripcion={
          actual
            ? "Cuentas, cola e historial de este cliente en cada plataforma."
            : "Cómo va la cola de cada cliente. Entra a uno para ver su cuenta, su cola y su historial."
        }
      />

      <nav className="tabs" aria-label="Clientes">
        <Link to="/publicaciones?vista=todos" className={!nichoParam ? "activo" : ""} onClick={() => guardarUltimo("")}>
          Todos
        </Link>
        {clientes.map((c) => (
          <Link
            key={c.nicho}
            to={`/publicaciones/${c.nicho}/${plataforma}`}
            className={c.nicho === nichoParam ? "activo" : ""}
          >
            {c.cliente}
            <span className="tab-meta">
              {(c.plataformas.tiktok?.conteos.en_cola ?? 0) + (c.plataformas.youtube?.conteos.en_cola ?? 0)}
            </span>
          </Link>
        ))}
      </nav>

      {conexion && (
        <p className={`pub-alerta ${conexion === "ok" ? "pub-alerta-ok" : "pub-alerta-error"}`}>
          {conexion === "ok"
            ? "Cuenta de YouTube conectada."
            : `No se pudo conectar la cuenta: ${searchParams.get("motivo") ?? "error desconocido"}`}{" "}
          <button className="btn-link" onClick={() => setSearchParams({})}>
            cerrar
          </button>
        </p>
      )}

      {resumenQuery.isLoading && <p className="hint">Cargando...</p>}
      {resumenQuery.isError && <p className="error">{(resumenQuery.error as Error).message}</p>}

      {!nichoParam && !resumenQuery.isLoading && <Todos clientes={clientes} />}

      {nichoParam && !resumenQuery.isLoading && (
        <>
          <nav className="tabs tabs-sub" aria-label="Plataformas">
            {PLATAFORMAS.map((p) => (
              <NavLink
                key={p}
                to={`/publicaciones/${nichoParam}/${p}`}
                className={({ isActive }) => (isActive ? "activo" : "")}
              >
                {PLATAFORMA_UI[p].nombre}
                <span className="tab-meta">{actual?.plataformas[p]?.conteos.en_cola ?? 0} en cola</span>
              </NavLink>
            ))}
          </nav>
          <Explicacion plataforma={plataforma} minutos={minutos} />
          {actual?.plataformas[plataforma] ? (
            <NichoPublicacion key={`${plataforma}-${nichoParam}`} resumen={actual.plataformas[plataforma]!} />
          ) : (
            <div className="pub-bloque">
              <Vacio titulo={`${actual?.cliente ?? nichoParam} no tiene cuenta de ${PLATAFORMA_UI[plataforma].nombre}`}>
                Sus clips aprobados se encolan igual y salen cuando conectes la cuenta.
              </Vacio>
              <Conexion plataforma={plataforma} nicho={nichoParam} />
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** Vista de todos los clientes: una tarjeta por cliente con lo esencial de cada plataforma. */
function Todos({ clientes }: { clientes: ClientePublicacion[] }) {
  if (clientes.length === 0) {
    return (
      <Vacio titulo="Todavía no hay clientes con cuentas ni clips aprobados.">
        Aprueba un clip en la Revisión o configura las fuentes de un cliente.
      </Vacio>
    );
  }
  return (
    <div className="pub-clientes">
      {clientes.map((c) => (
        <article key={c.nicho} className="pub-cliente">
          <header className="pub-cliente-cabecera">
            <h2>{c.cliente}</h2>
            <Link to={`/publicaciones/${c.nicho}/tiktok`} className="btn-link">
              Abrir →
            </Link>
          </header>
          {PLATAFORMAS.map((p) => {
            const r = c.plataformas[p];
            return (
              <Link key={p} to={`/publicaciones/${c.nicho}/${p}`} className="pub-cliente-plataforma">
                <span className="pub-cliente-nombre">{PLATAFORMA_UI[p].nombre}</span>
                {r?.cuenta ? (
                  <span className={`pill pub-cuenta-${r.cuenta.estado}`}>{CUENTA_LABEL[r.cuenta.estado]}</span>
                ) : (
                  <span className="pill pill-muted">sin cuenta</span>
                )}
                <span className="pub-cliente-dato">
                  <strong className="mono">{r?.conteos.en_cola ?? 0}</strong> en cola
                  {r?.dias_cola !== null && r?.dias_cola !== undefined && <> · {r.dias_cola} d</>}
                </span>
                <span className="pub-cliente-dato">
                  {r?.proximo_envio ? <>sale {cuando(r.proximo_envio.sale)}</> : <span className="hint">sin envío programado</span>}
                </span>
                {r && r.alertas.length > 0 && (
                  <span className={`pill ${r.alertas.some((a) => a.nivel === "error") ? "pill-error" : "pill-warn"}`}>
                    {r.alertas.length} aviso{r.alertas.length > 1 ? "s" : ""}
                  </span>
                )}
              </Link>
            );
          })}
        </article>
      ))}
    </div>
  );
}

function NichoPublicacion({ resumen }: { resumen: ResumenNicho }) {
  const queryClient = useQueryClient();
  const { plataforma, nicho, cuenta } = resumen;
  const ui = PLATAFORMA_UI[plataforma];

  const pubsQuery = useQuery({
    queryKey: ["publicaciones", plataforma, nicho],
    queryFn: () => api.getPublicaciones(plataforma, nicho),
    refetchInterval: 10000,
  });

  const refrescar = () => {
    queryClient.invalidateQueries({ queryKey: ["publicaciones-resumen"] });
    queryClient.invalidateQueries({ queryKey: ["publicaciones", plataforma, nicho] });
  };

  const revisarMutation = useMutation({
    mutationFn: api.revisarAhora,
    onSuccess: () => setTimeout(refrescar, 1500),
  });
  const enviarMutation = useMutation({ mutationFn: () => api.enviarAhora(plataforma, nicho), onSuccess: refrescar });
  const reanudarMutation = useMutation({ mutationFn: () => api.reanudarCuenta(cuenta!.id), onSuccess: refrescar });

  const pubs = pubsQuery.data ?? [];
  const enCola = pubs.filter((p) => p.estado === "en_cola");
  const historial = pubs.filter((p) => p.estado !== "en_cola");
  const rev = resumen.ultima_revision;
  const errorAccion = revisarMutation.error ?? enviarMutation.error ?? reanudarMutation.error;

  return (
    <div className="pub-nicho">

      {resumen.alertas.map((a) => (
        <p key={a.texto} className={`pub-alerta pub-alerta-${a.nivel}`}>
          {a.texto}
        </p>
      ))}

      <div className="pub-bloque pub-cuenta">
        {cuenta ? (
          <>
            <div className="pub-cuenta-fila">
              <strong>{cuenta.nombre ?? `Cuenta de ${ui.nombre}`}</strong>
              <span className={`pill pub-cuenta-${cuenta.estado}`}>{CUENTA_LABEL[cuenta.estado]}</span>
              {cuenta.modo === "simulado" && <span className="pill pill-warn">modo prueba (simulado)</span>}
            </div>
            <dl className="pub-datos">
              <dt>Horarios</dt>
              <dd>{cuenta.horarios.split(",").map((h) => `${h}:00`).join(" · ")}</dd>
              <dt>Próximo envío</dt>
              <dd>
                {resumen.proximo_envio ? (
                  <>
                    <strong className="pub-proximo">{cuando(resumen.proximo_envio.sale)}</strong> —{" "}
                    {resumen.proximo_envio.titulo ?? resumen.proximo_envio.clip_id}{" "}
                    <span className="hint">(horario de las {horaCorta(resumen.proximo_envio.horario)})</span>
                  </>
                ) : resumen.proximo_envio_motivo ? (
                  <span className="hint">{resumen.proximo_envio_motivo}</span>
                ) : (
                  <span className="hint">
                    Cola vacía{resumen.siguiente_libre && <> — un clip aprobado ahora saldría {cuando(resumen.siguiente_libre)}</>}
                  </span>
                )}
              </dd>
              <dt>En cola</dt>
              <dd>
                {resumen.conteos.en_cola ?? 0} clip(s)
                {resumen.dias_cola !== null && <span className="hint"> · alcanza para {resumen.dias_cola} día(s)</span>}
              </dd>
              {cuenta.estado === "pausada" && (
                <>
                  <dt>Pausada hasta</dt>
                  <dd>{formatearFecha(cuenta.pausada_hasta)}</dd>
                </>
              )}
              {cuenta.modo === "real" && (
                <>
                  <dt>Conexión vence</dt>
                  <dd>{formatearFecha(cuenta.refresh_vence)}</dd>
                </>
              )}
            </dl>
          </>
        ) : (
          <p className="hint">Este nicho no tiene cuenta conectada: sus clips esperan en la cola.</p>
        )}

        {rev && (
          <p className="pub-revision">
            <span className="hint">Última revisión {hace(rev.hasta)}:</span> {rev.decision}
            {rev.veces > 1 && <span className="hint"> (igual desde {hora(rev.desde)}, {rev.veces} revisiones)</span>}
          </p>
        )}

        <div className="acciones">
          <button className="btn btn-secondary" onClick={() => revisarMutation.mutate()} disabled={revisarMutation.isPending}>
            Revisar ahora
          </button>
          {cuenta && (
            <button
              className="btn btn-secondary"
              disabled={enviarMutation.isPending || !enCola.length || cuenta.estado !== "conectada"}
              title="Envía el primero de la cola sin esperar el horario"
              onClick={() => enviarMutation.mutate()}
            >
              {enviarMutation.isPending ? "Enviando..." : "Enviar ahora (prueba)"}
            </button>
          )}
          {cuenta?.estado === "pausada" && (
            <button className="btn btn-secondary" onClick={() => reanudarMutation.mutate()}>
              Reanudar cuenta
            </button>
          )}
        </div>
        {errorAccion && <p className="error">{(errorAccion as Error).message}</p>}

        {(!cuenta || cuenta.estado === "requiere_reconexion" || cuenta.modo === "simulado") && (
          <Conexion plataforma={plataforma} nicho={nicho} reconectar={!!cuenta} />
        )}
      </div>

      <div className="pub-bloque">
        <h3>Cola ({enCola.length})</h3>
        {enCola.length === 0 ? (
          <p className="hint">Vacía. Los clips aprobados en la Revisión aparecen aquí.</p>
        ) : (
          <>
            <ColaTabla pubs={enCola} onChanged={refrescar} />
            <p className="hint">
              Horas calculadas con las mismas reglas del sistema (revisa a las :00, :10, :20…). Se cumplen si el
              backend está encendido a esa hora y {ui.nombre} no rechaza el envío.
            </p>
          </>
        )}
      </div>

      <div className="pub-bloque">
        <h3>Historial</h3>
        {historial.length === 0 ? (
          <p className="hint">Todavía no se envió nada.</p>
        ) : (
          <HistorialTabla pubs={historial} onChanged={refrescar} />
        )}
      </div>
    </div>
  );
}

function Conexion({
  plataforma,
  nicho,
  reconectar = false,
}: {
  plataforma: Plataforma;
  nicho: string;
  reconectar?: boolean;
}) {
  const queryClient = useQueryClient();
  const [urlAutorizacion, setUrlAutorizacion] = useState<string | null>(null);
  const [urlPegada, setUrlPegada] = useState("");

  const refrescar = () => queryClient.invalidateQueries({ queryKey: ["publicaciones-resumen"] });

  const autorizarMutation = useMutation({
    mutationFn: () => (plataforma === "youtube" ? api.autorizarYouTube(nicho) : api.autorizarTikTok(nicho)),
    onSuccess: (r) => {
      if (plataforma === "youtube") {
        // Google vuelve directo al backend, que conecta la cuenta y regresa a esta pantalla
        window.location.href = r.url;
        return;
      }
      setUrlAutorizacion(r.url);
      window.open(r.url, "_blank", "noopener");
    },
  });
  const conectarMutation = useMutation({
    mutationFn: () => api.conectarTikTok(nicho, urlPegada),
    onSuccess: () => {
      setUrlAutorizacion(null);
      setUrlPegada("");
      refrescar();
    },
  });
  const simuladaMutation = useMutation({
    mutationFn: () => api.conectarCuentaSimulada(plataforma, nicho),
    onSuccess: refrescar,
  });

  const error = autorizarMutation.error ?? conectarMutation.error ?? simuladaMutation.error;
  const conectarCon = plataforma === "youtube" ? "Conectar con Google" : "Conectar con TikTok";

  return (
    <details className="pub-conexion" open={!reconectar || undefined}>
      <summary>{reconectar ? conectarCon : "Conectar cuenta"}</summary>
      <div className="acciones">
        <button className="btn btn-primary" onClick={() => autorizarMutation.mutate()} disabled={autorizarMutation.isPending}>
          {conectarCon}
        </button>
        {!reconectar && (
          <button className="btn btn-secondary" onClick={() => simuladaMutation.mutate()}>
            Usar cuenta de prueba (simulada)
          </button>
        )}
      </div>
      {urlAutorizacion && (
        <form
          className="pub-pegar"
          onSubmit={(e) => {
            e.preventDefault();
            conectarMutation.mutate();
          }}
        >
          <p className="hint">
            Se abrió TikTok en otra pestaña (si no, <a href={urlAutorizacion} target="_blank" rel="noreferrer">ábrela aquí</a>).
            Autoriza la app; TikTok te devuelve a la Redirect URI configurada (no importa si la página no carga).
            Copia la URL completa de la barra del navegador y pégala aquí:
          </p>
          <input
            value={urlPegada}
            onChange={(e) => setUrlPegada(e.target.value)}
            placeholder="https://...?code=...&state=..."
          />
          <button type="submit" className="btn btn-primary" disabled={!urlPegada || conectarMutation.isPending}>
            {conectarMutation.isPending ? "Conectando..." : "Terminar conexión"}
          </button>
        </form>
      )}
      {error && <p className="error">{(error as Error).message}</p>}
    </details>
  );
}

async function copiar(texto: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(texto);
  } catch {
    // Sin la API del portapapeles (contexto no seguro): copia con un textarea temporal
    const area = document.createElement("textarea");
    area.value = texto;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

/** Link de la línea gris que abre/cierra el texto de la publicación (o avisa que no hay). */
function BotonTexto({ pub, abierto, onToggle }: { pub: Publicacion; abierto: boolean; onToggle: () => void }) {
  const ui = PLATAFORMA_UI[pub.plataforma];
  if (!pub.texto) return <span>{ui.sinTexto}</span>;
  return (
    <button className="btn-link" onClick={onToggle}>
      {abierto ? "ocultar texto" : ui.botonTexto}
    </button>
  );
}

/** TikTok: descripción + # tal cual se pegan al activar el borrador. YouTube: lo que se envió por la API. */
function CajaTexto({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="pub-texto">
      <div className="pub-texto-cuerpo">{texto}</div>
      <button
        className="btn btn-secondary"
        onClick={() =>
          copiar(texto).then(() => {
            setCopiado(true);
            setTimeout(() => setCopiado(false), 2000);
          })
        }
      >
        {copiado ? "Copiado ✓" : "Copiar"}
      </button>
    </div>
  );
}

function ColaTabla({ pubs, onChanged }: { pubs: Publicacion[]; onChanged: () => void }) {
  const [verVideo, setVerVideo] = useState<number | null>(null);
  const [verTexto, setVerTexto] = useState<number | null>(null);
  const mover = useMutation({
    mutationFn: ({ id, dir }: { id: number; dir: "arriba" | "abajo" }) => api.moverPublicacion(id, dir),
    onSuccess: onChanged,
  });
  const quitar = useMutation({ mutationFn: (id: number) => api.quitarPublicacion(id), onSuccess: onChanged });

  return (
    <div className="tabla-scroll">
      <table className="tabla-sesiones">
        <thead>
          <tr>
            <th>#</th>
            <th>Sale</th>
            <th>Clip</th>
            <th>Encolado</th>
            <th>Intentos</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {pubs.map((p, i) => (
            <tr key={p.id}>
              <td>{i + 1}</td>
              <td className="pub-sale">
                {p.sale_aprox ? (
                  <>
                    <strong>{cuando(p.sale_aprox)}</strong>
                    {p.horario_estimado && <div className="hint">horario {horaCorta(p.horario_estimado)}</div>}
                  </>
                ) : (
                  <span className="hint">—</span>
                )}
              </td>
              <td>
                <div>{p.titulo ?? p.clip_id}</div>
                <div className="hint">
                  <Link to={`/sesiones/${p.session_id}/revision`}>{p.session_id}</Link> · {p.clip_id} ·{" "}
                  <button className="btn-link" onClick={() => setVerVideo(verVideo === p.id ? null : p.id)}>
                    {verVideo === p.id ? "ocultar video" : "ver video"}
                  </button>{" "}
                  ·{" "}
                  <BotonTexto pub={p} abierto={verTexto === p.id} onToggle={() => setVerTexto(verTexto === p.id ? null : p.id)} />
                </div>
                {verTexto === p.id && p.texto && <CajaTexto texto={p.texto} />}
                {verVideo === p.id && (
                  <video className="pub-video" controls preload="metadata" src={api.clipVideoUrl(p.session_id, p.clip_id)} />
                )}
                {p.error_mensaje && <div className="pub-error-texto">Último intento: {p.error_mensaje}</div>}
              </td>
              <td>{hora(p.encolada_en)}</td>
              <td>{p.intentos}</td>
              <td className="pub-acciones-fila">
                <button className="btn btn-secondary" disabled={i === 0} onClick={() => mover.mutate({ id: p.id, dir: "arriba" })} title="Subir">
                  ↑
                </button>
                <button
                  className="btn btn-secondary"
                  disabled={i === pubs.length - 1}
                  onClick={() => mover.mutate({ id: p.id, dir: "abajo" })}
                  title="Bajar"
                >
                  ↓
                </button>
                <button className="btn btn-danger" onClick={() => quitar.mutate(p.id)}>
                  Quitar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HistorialTabla({ pubs, onChanged }: { pubs: Publicacion[]; onChanged: () => void }) {
  const [abierta, setAbierta] = useState<number | null>(null);
  return (
    <div className="tabla-scroll">
      <table className="tabla-sesiones">
        <thead>
          <tr>
            <th>Estado</th>
            <th>Clip</th>
            <th>Horario</th>
            <th>Enviado</th>
            <th>{pubs[0] ? PLATAFORMA_UI[pubs[0].plataforma].columnaEntregado : "Entregado"}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {pubs.map((p) => (
            <FilaHistorial
              key={p.id}
              pub={p}
              abierta={abierta === p.id}
              onToggle={() => setAbierta(abierta === p.id ? null : p.id)}
              onChanged={onChanged}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FilaHistorial({
  pub,
  abierta,
  onToggle,
  onChanged,
}: {
  pub: Publicacion;
  abierta: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const detalleQuery = useQuery({
    queryKey: ["publicacion", pub.id, pub.actualizada_en],
    queryFn: () => api.getPublicacion(pub.id),
    enabled: abierta,
  });
  const reintentar = useMutation({ mutationFn: () => api.reintentarPublicacion(pub.id), onSuccess: onChanged });
  const recibido = useMutation({ mutationFn: () => api.marcarRecibido(pub.id), onSuccess: onChanged });
  const error = reintentar.error ?? recibido.error;
  const [verTexto, setVerTexto] = useState(false);

  return (
    <>
      <tr>
        <td>
          <span className={`pill pub-estado-${pub.estado}`}>{estadoLabel(pub.plataforma, pub.estado)}</span>
        </td>
        <td>
          <div>{pub.titulo ?? pub.clip_id}</div>
          <div className="hint">
            {pub.session_id} · {pub.clip_id} · <BotonTexto pub={pub} abierto={verTexto} onToggle={() => setVerTexto(!verTexto)} />
          </div>
          {verTexto && pub.texto && <CajaTexto texto={pub.texto} />}
          {pub.error_mensaje && pub.estado !== "en_bandeja" && <div className="pub-error-texto">{pub.error_mensaje}</div>}
        </td>
        <td>{pub.slot ? hora(pub.slot) : pub.enviada_en ? "prueba" : "—"}</td>
        <td>{hora(pub.enviada_en)}</td>
        <td>{pub.estado === "en_bandeja" ? hora(pub.confirmada_en) : "—"}</td>
        <td className="pub-acciones-fila">
          <button className="btn btn-secondary" onClick={onToggle}>
            {abierta ? "Ocultar" : "Trazas"}
          </button>
          {(pub.estado === "error" || pub.estado === "sin_confirmar" || pub.estado === "cancelado") && (
            <button className="btn btn-secondary" onClick={() => reintentar.mutate()} disabled={reintentar.isPending}>
              {pub.estado === "cancelado" ? "Volver a la cola" : "Reintentar"}
            </button>
          )}
          {pub.estado === "sin_confirmar" && (
            <button
              className="btn btn-secondary"
              onClick={() => recibido.mutate()}
              title={PLATAFORMA_UI[pub.plataforma].marcarRecibidoAyuda}
            >
              {PLATAFORMA_UI[pub.plataforma].marcarRecibido}
            </button>
          )}
        </td>
      </tr>
      {(abierta || error) && (
        <tr className="pub-trazas-fila">
          <td colSpan={6}>
            {error && <p className="error">{(error as Error).message}</p>}
            {abierta && detalleQuery.isLoading && <p className="hint">Cargando trazas...</p>}
            {abierta && detalleQuery.data && (
              <>
                <p className="hint">
                  {pub.plataforma === "youtube" ? "id del video" : "publish_id"}: {detalleQuery.data.publish_id ?? "—"} · intentos: {detalleQuery.data.intentos}
                  {detalleQuery.data.error_codigo && <> · código: {detalleQuery.data.error_codigo}</>}
                </p>
                <ol className="pub-eventos">
                  {detalleQuery.data.eventos.map((e, i) => (
                    <li key={i} className={`pub-evento pub-evento-${e.tipo}`}>
                      <span className="pub-evento-ts">{formatearFecha(e.ts)}</span>
                      <span className="pill pill-muted">{e.tipo}</span> {e.mensaje}
                      {e.detalle && (
                        <code className="pub-evento-detalle">
                          {Object.entries(e.detalle)
                            .filter(([k, v]) => v !== null && v !== undefined && k !== "traza")
                            .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
                            .join("  ")}
                        </code>
                      )}
                    </li>
                  ))}
                </ol>
              </>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
