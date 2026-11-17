# Decisiones de diseño — backend v1

## Revisión post-hoc, no pausa en vivo del pipeline

`pipeline.py --revisar` bloquea el proceso a mitad de la corrida (`input()` de terminal) antes de que el Agente 4 corte cada clip. Sincronizar eso con una API HTTP requeriría un protocolo de espera entre el subproceso del pipeline y el backend — en espíritu parecido al de `ai_client/manual_provider.py` (que ya resuelve un problema similar para las llamadas a Claude en modo manual), pero aplicado a aprobación de clips. Mucho más caro que lo que un v1 necesita.

En cambio, `revisar_clips.py` ya resuelve exactamente el flujo de revisión que se quiere, pero **después** de que el Agente 4 cortó todo. El backend adopta ese mismo momento: lanza el pipeline siempre sin `--revisar` (auto-publica lo que Agente 3 marcó `publicar`), y expone por API las mismas acciones que `revisar_clips.py` ya hace a mano (aprobar / editar título / editar rango / descartar), reusando sus mismas funciones de bajo nivel.

**Tradeoff aceptado**: cada clip se corta una vez de más (los descartados sí llegaron a pasar por FFmpeg) comparado con un modelo de aprobación previa al corte. Es el mismo costo que ya paga hoy cualquiera que corra el pipeline sin `--revisar` y revise después con `revisar_clips.py` — no es un costo nuevo introducido por el backend.

## Colab-only para transcripción, sin toggle

Confirmado explícitamente con el usuario: el frontend descarta por completo WhisperX local. `pipeline_runner.py` siempre agrega `--colab` en modo `video`; no existe ningún parámetro en la API para desactivarlo. Motivo (documentado también en `docs/ARQUITECTURA.md` de la raíz del repo, §16): WhisperX local corre por CPU en esta máquina y puede tardar más de una hora en un video de ~20 min — inviable para un flujo pensado para operarse desde un panel web con expectativa de respuesta rápida.

## Sin `--revisar` expuesto, sin auth, sin multi-usuario

Herramienta interna de un solo operador corriendo en local. No hay capa de autenticación, no hay aislamiento entre usuarios, no hay Docker/deploy — decisiones de alcance para v1, no vencimientos técnicos. El toggle `--revisar` de terminal tampoco se expone porque quedó reemplazado por completo por la revisión web (ver arriba); no tiene sentido ofrecer ambos caminos a la vez.

## Subprocess para correr el pipeline, import directo para todo lo demás

Ver `ARQUITECTURA.md` §"Dos formas de tocar el pipeline". Correr el pipeline completo in-process (importando y llamando `run_pipeline()` directamente en vez de via subprocess) acoplaría el ciclo de vida de una corrida de horas al proceso de la API — un reinicio de la API mataría la corrida real. El subprocess evita eso; su rastro sobrevive a reinicios gracias al registro en `runs_logs/runs.json` (ver `ARQUITECTURA.md` §"Registro de corridas persistente").

## Sin base de datos: archivo de corridas + `stream_data/`

Se sigue sin introducir una base de datos (ni siquiera SQLite) para una herramienta de una sola persona: el filesystem (`stream_data/`, con el estado por pasos en `pipeline_estado.json`) es la fuente de verdad real, igual que para el resto del pipeline. Lo único propio del backend es `runs_logs/runs.json` (qué corrida/pid va con qué sesión), que reemplazó al tracking solo en memoria del v1 (2026-09-30).

## Orquestación por pasos dentro del pipeline, no en el backend (2026-09-30)

Para la vista tipo hub de despachos (círculos por paso, error reintentable/no, reintento) se evaluó un orquestador genérico en el backend que llamara a los módulos del pipeline como pasos. Se eligió el camino incremental: el motor de pasos vive en `core/pasos.py` y lo usa `pipeline.py`, que sigue siendo el ejecutor. Así el mismo estado, los reintentos automáticos y `--reintentar` funcionan igual por terminal y por web, y el backend solo lanza/lee. La separación orquestación (agnóstica, `core/pasos.py`) / negocio (funciones de paso en `pipeline.py`) se mantiene dentro del pipeline.

## IA vía Claude Code CLI, desacoplada (2026-09-30)

El pipeline corre solo, sin API key: cada llamada de los Agentes 0-3 la responde Claude Code headless (`AI_PROVIDER=claude_cli`, default). El modo `manual` (respuestas escritas a mano por una sesión de Claude Code vía `_pending/`) fue solo para desarrollo y queda como opción de depuración; no se expone en la web. Volver a la API es cambiar `AI_PROVIDER=anthropic` en Configuración — los agentes no cambian. Tradeoff aceptado: se consume el límite de uso de la suscripción; un límite agotado es un error reintentable (el paso se reintenta solo y, si sigue, queda en error para reintentar después).

## SQLite solo para la cola de publicación (2026-10-09)

Excepción acotada a "sin base de datos": el motor de publicación puede correr en dos procesos a la vez (uvicorn `--reload`) y tiene que ser imposible ocupar un horario dos veces o enviar dos veces el mismo clip; eso lo da un `UPDATE` condicional + un índice único parcial, algo que un JSON no garantiza. El resto del backend sigue leyendo `stream_data/` y `runs.json`. La base guarda tokens de TikTok: está en `.gitignore`.

## Publicación: borrador a la bandeja, trazabilidad hasta ahí (2026-10-09)

Acordado con el usuario: solo TikTok en v1, una cuenta por nicho (primera: `zapatillas_peru`), horarios 8/12/16/20, todo clip aprobado entra solo (solo los aprobados desde que existe la función), sin editar después de aprobar. Sin auditoría de la app, TikTok solo permite publicar en privado o mandar un borrador a la bandeja; se eligió el borrador y que el usuario lo active. **El sistema se hace responsable hasta que TikTok confirma que el borrador llegó** (`SEND_TO_USER_INBOX`): no se rastrea si se publicó después. El texto (descripción/hashtags) queda para v2: el endpoint de bandeja no lo acepta. El publicador es intercambiable (`base.Publicador`) por si más adelante hay auditoría o un intermediario. El modo (real/simulado) es por cuenta, no global: una cuenta de prueba nunca toca TikTok.

## YouTube Shorts: cola independiente, privado, trazabilidad hasta "processed" (2026-10-10)

Acordado con el usuario: todo clip aprobado entra también a una cola de YouTube Shorts **independiente** de la de TikTok (cuenta, horarios propios —arrancan en 8/12/16/20—, orden, pausas y errores propios; mover o quitar en una no toca la otra; descartar o editar en la Revisión saca de ambas). Mismo motor y misma base con la plataforma como parámetro, en vez de copiar el sistema: las garantías (un clip por horario, nunca reenviar a ciegas, recuperación) ya están probadas. Solo los clips aprobados desde ahora; como prueba única, se copió a YouTube lo que estaba en cola en TikTok. Según Google, todo video subido por un proyecto de API no auditado queda bloqueado en privado; en la prueba real (2026-10-10) el usuario sí pudo pasarlo a público a mano desde YouTube Studio. v1 sube **privado** y el usuario lo publica con título, descripción y tags del Agente 3 tal cual (categoría Gente y blogs, español, no es para niños). **El sistema se hace responsable hasta que YouTube confirma `uploadStatus = processed`**. Subir directo como público/programado (`publishAt`) queda para una v2, después de confirmar que YouTube no bloquea los videos más tarde (o tras la auditoría).

**Actualización (2026-10-10):** a pedido del usuario, YouTube sube directo como **público** (`youtube.VISIBILIDAD`). Al terminar se lee la visibilidad real del video; si YouTube no respetó la pedida (proyecto sin auditoría), queda un evento de error en las trazas, pero el envío cuenta como entregado.
