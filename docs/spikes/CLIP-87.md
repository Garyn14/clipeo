# Spike CLIP-87 · Publicar sin depender de la PC encendida

> [Líder técnico] · 2026-11-25 · Timebox: 1 día, sin código de producción. Decide el operador.

## Pregunta

Hoy la cola de publicación (TikTok en borrador, YouTube Shorts) corre en un hilo del backend local
(`backend/app/publicacion/motor.py`): si la PC está apagada a las 8/12/16/20, ese horario se pierde. ¿Se puede sacar
**solo la publicación** a un servicio siempre encendido, con **costo ≈ 0**, sin perder lo que ya garantiza el motor
(no reenviar a ciegas, `publish_id` guardado antes de subir, eventos por llamada, horarios predecibles)?

## Qué tiene que viajar

| Pieza | Hoy | Tamaño / ritmo | Comentario |
|---|---|---|---|
| Cola y eventos | SQLite `data/publicacion.db` | KB | El motor ya es casi independiente del resto (solo lee el video y el texto del clip). |
| Videos aprobados | `stream_data/<sesión>/clips/*.mp4` | 15–40 MB c/u; ~12/día por cliente y plataforma | Es lo único pesado. Con 2 clientes × 2 plataformas: **~20 GB/mes de salida**. |
| Tokens OAuth | `publicacion.db` (TikTok y YouTube) | KB | Secretos: viajan cifrados en tránsito y quedan solo en el servidor. |
| Credenciales de las apps | `.env` (`TIKTOK_CLIENT_*`, `YOUTUBE_CLIENT_*`) | KB | Igual que hoy, pero en el `.env` del servidor. |
| Callback OAuth de YouTube | `http://localhost:8000/...` | — | Pasa a una URL https del servidor (hay que registrarla en Google Cloud). TikTok ya funciona pegando la URL de vuelta. |

Lo que **no** viaja: descarga, transcripción (Colab), agentes (Claude Code de la PC), revisión de clips y directos.
Siguen en la PC; solo se desacopla el último paso.

## Opciones con costo ≈ 0

### A. VM gratuita siempre encendida (Oracle Cloud Always Free) — **recomendada**

El motor de publicación se empaqueta como un servicio propio (`publicador/`, mismo código y misma base) en una VM
gratuita con Docker. El panel local, al aprobar un clip, **sube el video y su texto** al servicio; la página
Publicaciones lee el estado del servicio en vez de la base local.

- **A favor:** reutiliza el motor tal cual (horarios, reintentos, eventos, recuperación); sin reescritura serverless.
  Oracle incluye mucha salida gratis (lo que pesa aquí son los ~20 GB/mes de videos), disco en bloque y una VM Arm
  suficiente para este trabajo.
- **En contra:** alta de cuenta con tarjeta (verificación, sin cargo); Oracle **recortó en 2026** la asignación de
  las VM Ampere A1 (reportes de 4→2 OCPU y 24→12 GB, con fechas y alcance contradictorios) y puede **reclamar
  instancias ociosas**; hay que mantener la VM (actualizaciones, respaldos de la base) y exponer https (Cloudflare
  Tunnel gratuito o Caddy con un dominio gratuito).

### B. Serverless: contenedor con tarea programada (Google Cloud Run + Cloud Scheduler) y almacenamiento de objetos

- **A favor:** sin servidor que mantener; la capa gratuita de Cloud Run sobra para 4 ejecuciones cortas por hora.
- **En contra:** el motor actual asume un proceso vivo y SQLite local; habría que **reescribirlo sin estado** (base
  gestionada o archivo en almacenamiento de objetos con bloqueo). La salida de video desde Google Cloud **no es
  gratuita** fuera de un margen chico, así que los videos irían en Cloudflare R2 (10 GB gratis, salida gratis):
  dos proveedores, más piezas.

### C. GitHub Actions con cron

- **En contra (descartada):** el repositorio es **público** (logs visibles); los cron de Actions llegan con **5–30
  min de retraso y a veces se saltan**, inaceptable para horarios fijos; GitHub puede desactivar los cron en repos
  inactivos. Igual haría falta R2 para los videos.

### D. VPS de pago mínimo (~US$4–6/mes)

- **A favor:** lo más simple y estable (sin recortes ni reclamos de instancias ociosas).
- **En contra:** rompe "costo ≈ 0 hasta tener ingresos". Queda como plan B si Oracle falla.

## Comparación

| | A. VM gratuita | B. Serverless + R2 | C. Actions | D. VPS pago |
|---|---|---|---|---|
| Costo | 0 (con riesgo de recortes) | 0 dentro de cuotas | 0 | ~US$5/mes |
| Reescritura del motor | Mínima (empaquetar + API de sincronía) | Grande (sin estado) | Grande | Mínima |
| Horarios a tiempo | Sí | Sí | **No** | Sí |
| Mantenimiento | VM + respaldos | Bajo | Bajo | VM + respaldos |
| Riesgo principal | Política de Oracle | Más piezas y proveedores | Retrasos, repo público | Costo |

## Recomendación

**Opción A** (Oracle Always Free), con la **D** como plan B usando exactamente el mismo contenedor. El código no
cambia entre A y D: solo dónde corre. Antes de implementar, el operador debe confirmar en la página oficial de Oracle
la asignación vigente y la política de instancias ociosas, y crear la cuenta (Claude no crea cuentas ni escribe
credenciales).

**Sin cambiar todavía:** directos, transcripción y agentes siguen en la PC. Un directo solo se graba con la PC
encendida (desde una IP de centro de datos el bloqueo de TikTok sería peor), y Claude Code se usa con la sesión del
operador en su máquina.

## Borrador de tickets (si se aprueba)

1. **Publicador como servicio:** extraer `backend/app/publicacion/` a un paquete `publicador/` con su propio
   FastAPI, Dockerfile y la misma base; el backend local lo usa como hoy (sin cambios visibles). Tests en verde.
2. **Sincronía PC → servicio:** al aprobar un clip, subir video + texto al servicio (con reintento y verificación de
   hash); la página Publicaciones lee el estado remoto; modo `PUBLICADOR_URL` vacío = local como hoy.
3. **Despliegue:** VM + Docker + https (Cloudflare Tunnel), `.env` del servidor, respaldo diario de la base,
   redirect URI de YouTube nueva. Guía en `docs/OPERACION.md`.
4. **Corte y prueba:** migrar las cuentas conectadas (o reconectarlas), una semana en paralelo solo con TikTok
   borradores y luego YouTube.

## Fuentes (consultadas el 2026-11-25; reconfirmar antes de implementar)

- Oracle Always Free: [documentación oficial](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm),
  [recorte de A1 en 2026 (Linuxiac)](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/),
  [InfoQ](https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/),
  [desglose de la capa gratuita](https://fullmetalbrackets.com/blog/oci-free-tier-breakdown).
- Cloudflare R2: [precios](https://developers.cloudflare.com/r2/pricing/).
- Cloud Run: [precios](https://cloud.google.com/run/pricing).
- GitHub Actions: [límites](https://docs.github.com/en/actions/reference/limits),
  [retrasos de los cron](https://github.com/orgs/community/discussions/185355).
