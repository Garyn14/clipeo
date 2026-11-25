import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CapturaDirecto, ClienteDirectos, CuentaDirecto, EstadoCaptura, ResumenDirectos } from "../api/types";
import { PageHeader, Vacio } from "../components/ui";

// CLIP-90 (épica L1): directos en vivo por cliente — cuentas vigiladas, lo que se graba ahora y capturas recientes.

const ESTADO_CAPTURA: Record<EstadoCaptura, { texto: string; clase: string }> = {
  grabando: { texto: "grabando", clase: "pill-vivo" },
  terminado: { texto: "terminado", clase: "pill-ok" },
  detenido: { texto: "detenido", clase: "pill-muted" },
  sin_directo: { texto: "no estaba en vivo", clase: "pill-muted" },
  error: { texto: "error", clase: "pill-error" },
  interrumpido: { texto: "interrumpido", clase: "pill-warn" },
};

function hace(iso: string | null | undefined): string {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  return h < 24 ? `hace ${h} h` : `hace ${Math.floor(h / 24)} d`;
}

function duracion(desde: string, hasta?: string | null): string {
  const s = Math.max(0, Math.round(((hasta ? new Date(hasta) : new Date()).getTime() - new Date(desde).getTime()) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

function mb(bytes: number): string {
  return `${(bytes / 1_048_576).toFixed(0)} MB`;
}

function fecha(iso: string): string {
  return new Date(iso).toLocaleString("es-PE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function Directos() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["directos"], queryFn: api.getDirectos, refetchInterval: 15000 });
  const [elegido, setElegido] = useState<string | null>(null);
  const refrescar = () => queryClient.invalidateQueries({ queryKey: ["directos"] });
  const revisar = useMutation({ mutationFn: api.revisarDirectos, onSuccess: () => setTimeout(refrescar, 3000) });

  const datos = query.data;
  const clientes = datos?.clientes ?? [];
  const actual = clientes.find((c) => c.nicho === elegido) ?? clientes[0];
  const enVivo = clientes.flatMap((c) => c.capturas.filter((cap) => cap.estado === "grabando").map((cap) => ({ c, cap })));

  return (
    <section className="panel">
      <PageHeader
        seccion="Producción"
        titulo="Directos"
        descripcion="Vigila las cuentas en vivo de cada cliente: cuando una entra en vivo se graba en trozos, y cada trozo pasa solo al pipeline y a la Revisión."
        acciones={
          <button className="btn btn-secondary" onClick={() => revisar.mutate()} disabled={revisar.isPending}>
            {revisar.isPending ? "Revisando..." : "Revisar ahora"}
          </button>
        }
      />

      {query.isLoading && <p className="hint">Cargando...</p>}
      {query.isError && <p className="error">{(query.error as Error).message}</p>}
      {datos && <Vigilante datos={datos} />}

      {enVivo.length > 0 && (
        <div className="dv-envivo">
          {enVivo.map(({ c, cap }) => (
            <CapturaEnVivo key={cap.carpeta} cliente={c.cliente} cap={cap} onCambio={refrescar} />
          ))}
        </div>
      )}

      {datos && clientes.length === 0 && (
        <Vacio titulo="Todavía no hay clientes.">Los clientes aparecen aquí cuando tienen fuentes configuradas.</Vacio>
      )}

      {actual && (
        <>
          <nav className="tabs" aria-label="Clientes">
            {clientes.map((c) => (
              <button
                key={c.nicho}
                className={c.nicho === actual.nicho ? "activo" : ""}
                onClick={() => setElegido(c.nicho)}
                type="button"
              >
                {c.cliente}
                <span className="tab-meta">{c.cuentas.length}</span>
              </button>
            ))}
          </nav>
          <Cliente cliente={actual} plataformas={datos!.plataformas} onCambio={refrescar} />
        </>
      )}
    </section>
  );
}

function Vigilante({ datos }: { datos: ResumenDirectos }) {
  const v = datos.vigilante;
  if (!v.activo) {
    return (
      <p className="pub-alerta pub-alerta-warn">
        El vigilante está apagado (DIRECTOS_MOTOR=0): no se revisa solo. "Revisar ahora" y "Grabar ahora" siguen
        funcionando.
      </p>
    );
  }
  const u = v.ultima_vuelta;
  return (
    <p className="hint dv-vigilante">
      Revisa cada {Math.round(v.intervalo_s / 60)} min.{" "}
      {u.fin ? (
        <>
          Última vuelta {hace(u.fin)}: <span className="mono">{u.resumen}</span>
        </>
      ) : u.inicio ? (
        "Revisando ahora..."
      ) : (
        "Todavía no hizo ninguna vuelta."
      )}
    </p>
  );
}

function CapturaEnVivo({ cliente, cap, onCambio }: { cliente: string; cap: CapturaDirecto; onCambio: () => void }) {
  const [confirmar, setConfirmar] = useState(false);
  const detener = useMutation({ mutationFn: () => api.detenerCaptura(cap.carpeta), onSuccess: onCambio });
  return (
    <div className="dv-envivo-fila">
      <span className="pill pill-vivo">en vivo</span>
      <strong>@{cap.usuario}</strong>
      <span className="hint">{cliente}</span>
      <span className="mono dv-dato">{duracion(cap.inicio)}</span>
      <span className="mono dv-dato">{cap.trozos.length} trozo(s)</span>
      <span className="dv-envivo-acciones">
        {confirmar ? (
          <>
            <span className="hint">¿Detener la grabación?</span>
            <button className="btn btn-danger btn-chico" onClick={() => detener.mutate()} disabled={detener.isPending}>
              Sí, detener
            </button>
            <button className="btn btn-secondary btn-chico" onClick={() => setConfirmar(false)}>
              No
            </button>
          </>
        ) : (
          <button className="btn btn-secondary btn-chico" onClick={() => setConfirmar(true)}>
            Detener
          </button>
        )}
      </span>
      {detener.isError && <p className="error">{(detener.error as Error).message}</p>}
    </div>
  );
}

function Cliente({
  cliente,
  plataformas,
  onCambio,
}: {
  cliente: ClienteDirectos;
  plataformas: ResumenDirectos["plataformas"];
  onCambio: () => void;
}) {
  return (
    <div className="dv-cliente">
      <div className="bloque">
        <h2 className="bloque-titulo">Cuentas vigiladas</h2>
        {cliente.cuentas.length === 0 ? (
          <Vacio titulo={`${cliente.cliente} no tiene cuentas de directo.`}>
            Agrega la cuenta de TikTok del cliente (o de un tercero, con R-01) para que se grabe cuando entre en vivo.
          </Vacio>
        ) : (
          <div className="tabla-scroll">
            <table className="tabla">
              <thead>
                <tr>
                  <th>Cuenta</th>
                  <th>Estado</th>
                  <th className="num">Trozo</th>
                  <th>Procesar</th>
                  <th>Vigilar</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {cliente.cuentas.map((c) => (
                  <FilaCuenta key={`${c.plataforma}/${c.usuario}`} nicho={cliente.nicho} cuenta={c} onCambio={onCambio} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <NuevaCuenta nicho={cliente.nicho} plataformas={plataformas} onCambio={onCambio} />
      </div>

      <div className="bloque">
        <h2 className="bloque-titulo">Capturas recientes</h2>
        {cliente.capturas.length === 0 ? (
          <p className="hint">Todavía no se grabó ningún directo de este cliente.</p>
        ) : (
          <ul className="dv-capturas">
            {cliente.capturas.map((cap) => (
              <Captura key={cap.carpeta} cap={cap} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EstadoCuenta({ cuenta }: { cuenta: CuentaDirecto }) {
  if (cuenta.grabando) return <span className="pill pill-vivo">grabando · {duracion(cuenta.grabando.inicio)}</span>;
  const ch = cuenta.chequeo;
  if (!ch) return <span className="hint">sin revisar todavía</span>;
  const texto = ch.en_vivo === true ? "en vivo" : ch.en_vivo === false ? "no en vivo" : "no concluyente";
  const clase = ch.en_vivo === true ? "pill-vivo" : ch.en_vivo === false ? "pill-muted" : "pill-warn";
  return (
    <span className="dv-estado" title={ch.detalle}>
      <span className={`pill ${clase}`}>{texto}</span> <span className="hint">{hace(ch.ts)}</span>
    </span>
  );
}

function FilaCuenta({ nicho, cuenta, onCambio }: { nicho: string; cuenta: CuentaDirecto; onCambio: () => void }) {
  const [quitarConfirmar, setQuitarConfirmar] = useState(false);
  const cambiar = useMutation({
    mutationFn: (cambios: { activo?: boolean; procesar?: boolean }) =>
      api.actualizarCuentaDirecto(nicho, cuenta.plataforma, cuenta.usuario, cambios),
    onSuccess: onCambio,
  });
  const grabar = useMutation({ mutationFn: () => api.grabarDirecto(nicho, cuenta.plataforma, cuenta.usuario), onSuccess: onCambio });
  const quitar = useMutation({ mutationFn: () => api.quitarCuentaDirecto(nicho, cuenta.plataforma, cuenta.usuario), onSuccess: onCambio });
  const error = cambiar.error ?? grabar.error ?? quitar.error;
  const url = `https://www.tiktok.com/@${cuenta.usuario}/live`;

  return (
    <>
      <tr className={cuenta.activo ? "" : "dv-pausada"}>
        <td>
          <a href={url} target="_blank" rel="noreferrer">
            @{cuenta.usuario}
          </a>
          <div className="hint">{cuenta.plataforma === "tiktok" ? "TikTok Live" : cuenta.plataforma}</div>
        </td>
        <td>
          <EstadoCuenta cuenta={cuenta} />
        </td>
        <td className="num">{cuenta.trozo_min} min</td>
        <td>
          <input
            type="checkbox"
            checked={cuenta.procesar}
            onChange={(e) => cambiar.mutate({ procesar: e.target.checked })}
            aria-label={`Procesar los trozos de @${cuenta.usuario}`}
            title="Cada trozo pasa solo al pipeline; si no, solo se graba"
          />
        </td>
        <td>
          <input
            type="checkbox"
            checked={cuenta.activo}
            onChange={(e) => cambiar.mutate({ activo: e.target.checked })}
            aria-label={`Vigilar a @${cuenta.usuario}`}
          />
        </td>
        <td className="dv-acciones">
          <button
            className="btn btn-vivo btn-chico"
            disabled={!!cuenta.grabando || grabar.isPending}
            onClick={() => grabar.mutate()}
            aria-label={`Grabar ahora a @${cuenta.usuario}`}
            title="Ya viste que está en vivo: graba sin verificar"
          >
            Grabar ahora
          </button>
          {quitarConfirmar ? (
            <>
              <button className="btn btn-danger btn-chico" onClick={() => quitar.mutate()}>
                Sí, quitar
              </button>
              <button className="btn btn-secondary btn-chico" onClick={() => setQuitarConfirmar(false)}>
                No
              </button>
            </>
          ) : (
            <button className="btn btn-secondary btn-chico" onClick={() => setQuitarConfirmar(true)}>
              Quitar
            </button>
          )}
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={6}>
            <p className="error">{(error as Error).message}</p>
          </td>
        </tr>
      )}
    </>
  );
}

function NuevaCuenta({
  nicho,
  plataformas,
  onCambio,
}: {
  nicho: string;
  plataformas: ResumenDirectos["plataformas"];
  onCambio: () => void;
}) {
  const [usuario, setUsuario] = useState("");
  const [plataforma, setPlataforma] = useState("tiktok");
  const [trozo, setTrozo] = useState(30);
  const [procesar, setProcesar] = useState(true);
  const agregar = useMutation({
    mutationFn: () => api.agregarCuentaDirecto(nicho, { plataforma, usuario, trozo_min: trozo, procesar }),
    onSuccess: () => {
      setUsuario("");
      onCambio();
    },
  });
  return (
    <form
      className="dv-nueva"
      onSubmit={(e) => {
        e.preventDefault();
        agregar.mutate();
      }}
    >
      <label>
        Cuenta
        <input value={usuario} onChange={(e) => setUsuario(e.target.value)} placeholder="@usuario o enlace del perfil" />
      </label>
      <label>
        Plataforma
        <select value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
          {plataformas.map((p) => (
            <option key={p.clave} value={p.clave} disabled={!p.disponible}>
              {p.nombre}
              {p.disponible ? "" : " (próximamente)"}
            </option>
          ))}
        </select>
      </label>
      <label>
        Trozo (min)
        <input type="number" min={1} max={120} value={trozo} onChange={(e) => setTrozo(Number(e.target.value))} />
      </label>
      <label className="dv-check">
        <input type="checkbox" checked={procesar} onChange={(e) => setProcesar(e.target.checked)} />
        Procesar cada trozo
      </label>
      <button type="submit" className="btn btn-primary" disabled={!usuario.trim() || agregar.isPending}>
        Agregar
      </button>
      {agregar.isError && <p className="error">{(agregar.error as Error).message}</p>}
    </form>
  );
}

function Captura({ cap }: { cap: CapturaDirecto }) {
  const estado = ESTADO_CAPTURA[cap.estado] ?? { texto: cap.estado, clase: "pill-muted" };
  return (
    <li className="dv-captura">
      <div className="dv-captura-cabecera">
        <span className={`pill ${estado.clase}`}>{estado.texto}</span>
        <strong>@{cap.usuario}</strong>
        <span className="mono hint">
          {fecha(cap.inicio)} · {duracion(cap.inicio, cap.fin)}
        </span>
        {cap.motivo && cap.estado !== "grabando" && <span className="hint">— {cap.motivo}</span>}
      </div>
      {cap.trozos.length > 0 && (
        <ol className="dv-trozos">
          {cap.trozos.map((t) => (
            <li key={t.id}>
              <span className="mono">{t.id.replace("trozo_", "#")}</span>
              <span className="mono hint">{mb(t.bytes)}</span>
              {t.estado === "parcial" && <span className="hint">parcial</span>}
              {t.sesion ? (
                <Link to={`/sesiones/${t.sesion}`}>ver sesión</Link>
              ) : t.omitido ? (
                <span className="hint">{t.omitido}</span>
              ) : (
                <span className="hint">en espera del pipeline</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}
