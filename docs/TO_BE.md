# Clipeo v2 — Análisis TO-BE

> Estado: **borrador v0.1 para validación** · Fecha: 2026-11-15 · Rol: análisis (sin decisiones técnicas cerradas)
> Insumos: entrevista con el operador (bloques 1–3) y [`DIAGNOSTICO_ACTUAL.md`](DIAGNOSTICO_ACTUAL.md) (AS-IS).
> Siguiente paso tras aprobación: arquitectura objetivo + roadmap + tickets.

---

## 1. Visión

Clipeo es una **plataforma interna de clipeo gestionado**: un único operador (y, a futuro, agentes de IA)
atiende a muchos streamers clientes, produciendo y publicando automáticamente clips virales adaptados al
objetivo de cada uno, y reportando sus resultados.

No es un SaaS self-service: **el cliente compra un servicio**, no usa una aplicación. La plataforma es
la herramienta del operador.

Se compone de dos sistemas:
1. **Engine agnóstico de orquestación** — ejecuta flujos de pasos (ingesta, transcripción, agentes,
   render, publicación, métricas…) sin conocer el dominio; pasos intercambiables, reanudables y medibles.
2. **Sistema de clips** — construido sobre el engine: consume fuentes, produce clips a un inventario,
   pasa por revisión, despacha a plataformas y mide resultados.

**Visión lejana:** agentes de IA en roles de negocio (crecimiento/vistas), revisión, desarrollo (calidad
de código), PO (avance de tickets) y finanzas (generación de ingresos).

## 2. Objetivos y métricas de éxito

| Horizonte | Objetivo | Métrica |
|---|---|---|
| MVP (~2 meses) | Demostrar alcance masivo | ≥ 1 clip con **1M de vistas** |
| MVP (~2 meses) | Validar que alguien paga | **1er cliente** pagando |
| MVP | Operar sin costo | Costo variable por clip ≈ **S/ 0** (medido) |
| Fase 2 | Operación repetible | 10–20 clientes activos |
| Fase 3 | Escala | ~100 clientes |

Evidencia previa (v1): cuenta de ~2K seguidores logró un clip de ~500K vistas sin gastar presupuesto.

## 3. Modelo de negocio

- **Cliente:** streamers (Perú como mercado inicial).
- **Precio inicial:** S/ 2 por clip publicado (oferta de entrada; también se contempla mensualidad).
  Referencia: 4 clips/día ≈ S/ 240/mes por cliente → 100 clientes ≈ S/ 24.000/mes.
- **Captación:** clips de contenido público de figuras del medio como **gancho** (prueba de resultado),
  seguido de mensajes directos selectivos (≈ **10 prospectos/semana**) por TikTok e Instagram.
- **Restricción clave:** **presupuesto ≈ 0** hasta tener ingresos. La economía por clip debe medirse desde
  el día 1.

## 4. Glosario

| Término | Definición |
|---|---|
| **Operador** | Quien administra la plataforma (hoy: el dueño; a futuro: agentes). |
| **Cliente** | Streamer que contrata el servicio. Sustituye al "nicho/canal" del piloto. |
| **Objetivo del cliente** | Configuración editorial y comercial de un cliente: tono, límites de contenido, KPI preferido, plataformas, cadencia. |
| **Perfil editorial** | Parte del objetivo: tono (atrevido ↔ family friendly), temas permitidos/prohibidos, estilo de texto. |
| **Fuente** | Cuenta oficial del cliente (o de un tercero, en captación) en YouTube, Kick o TikTok de donde se obtiene contenido. |
| **Contenido fuente** | Un video/VOD/live grabado obtenido de una fuente. |
| **Clip** | Fragmento vertical 9:16 editado, con texto y metadatos de publicación. |
| **Inventario** | Almacén de clips aprobados pendientes de publicar, por cliente. |
| **Caducidad** | Plazo tras el cual un clip no publicado se descarta (default 30 días). |
| **Cuenta de destino** | Cuenta de una plataforma donde se publica (propia del operador o del cliente). |
| **Despacho** | Proceso que toma clips del inventario y los publica según la cadencia del cliente. |
| **Paquete de publicación** | Video + descripción + hashtags + hora sugerida, listo para publicar a mano. |
| **Cuenta de captación** | Cuenta propia del operador usada para clips de terceros (gancho comercial). |
| **Prospecto** | Streamer candidato a cliente, en seguimiento comercial. |

## 5. Actores

| Actor | Hoy | Futuro |
|---|---|---|
| Operador (humano) | Configura clientes, revisa, publica, prospecta, cobra | Supervisa agentes |
| Agente revisor | — | Aprueba/descarta clips según el objetivo de cada cliente |
| Agentes de producción | Agentes 0–4 del piloto | Pasos del engine |
| Agente comercial / PO / dev / finanzas | — | Visión lejana |
| Cliente (streamer) | Recibe clips y reportes | Portal propio (Fase 3) |
| Plataformas | YouTube, Kick, TikTok (fuente); TikTok, YT Shorts, FB Reels (destino) | Extensible |

## 6. Procesos objetivo

```
 ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │ 1. INGESTA   │──▶│ 2. PRODUCCIÓN│──▶│ 3. REVISIÓN  │──▶│ 4. INVENTARIO│
 │ (job/cron)   │   │ (engine)     │   │ (operador →  │   │ (por cliente,│
 │ fuentes del  │   │ transcribir, │   │  agente)     │   │  caduca 30d) │
 │ cliente      │   │ detectar,    │   │              │   │              │
 └──────────────┘   │ refinar,     │   └──────────────┘   └──────┬───────┘
                    │ copy, render │                              │
                    └──────────────┘                              ▼
 ┌──────────────┐   ┌──────────────┐                     ┌──────────────┐
 │ 7. APRENDIZAJE│◀──│ 6. MÉTRICAS  │◀────────────────────│ 5. DESPACHO  │
 │ reglas por   │   │ por clip y   │                     │ cadencia del │
 │ cliente      │   │ reporte      │                     │ cliente (4/d)│
 └──────────────┘   └──────────────┘                     └──────────────┘

 Proceso paralelo:  P. PROSPECCIÓN — clip gancho → mensaje personalizado → seguimiento
```

### P1. Alta de cliente
Operador registra cliente, fuentes oficiales, cuentas de destino (propias o del cliente), plataformas,
cadencia (default 4/día), perfil editorial, KPI de reporte. Puede partir de un cliente plantilla.

### P2. Ingesta automática
Job programado revisa periódicamente las fuentes de cada cliente; detecta contenido nuevo (VODs, lives
finalizados/grabados) y lo encola. Sin tiempo real: el margen hasta publicar es de hasta un mes.

### P3. Producción
Flujo del engine por cada contenido fuente: descarga → transcripción → identificación de hablantes →
detección de momentos → refinamiento → puntuación + copy (según perfil editorial) → render 9:16.
Registra costo y duración de cada paso. Se produce más de lo que se publica.

### P4. Revisión
El operador aprueba / edita (texto, rango) / descarta con razón. Las correcciones alimentan el aprendizaje
del cliente. Diseñado desde el inicio para que un agente revisor asuma el paso.

### P5. Inventario y caducidad
Clips aprobados quedan en inventario por cliente, con fecha de producción y **frescura**. Al cumplir el
plazo (default 30 días) sin publicarse, se descartan automáticamente.

### P6. Despacho y publicación
Según la cadencia, toma los mejores clips vigentes y los publica en cada cuenta de destino. Modos:
- **Automático por API** donde esté disponible (YouTube Shorts ya funcionó en v1).
- **Asistido**: la plataforma recibe el video como borrador/notificación y el operador lo finaliza
  (TikTok funcionó así en v1).
- **Manual (default/fallback)**: el sistema genera el **paquete de publicación** y el operador publica.

### P7. Métricas y reporte
Lee periódicamente las estadísticas de cada clip publicado (vistas, likes, compartidos, comentarios).
Reporte por cliente centrado en su KPI preferido; siempre accesible.

### P8. Aprendizaje
Métricas + correcciones de revisión → reglas por cliente que se inyectan en los pasos de producción
(evolución del ciclo de feedback del piloto, ahora alimentado también por datos reales).

### P9. Prospección
Lista curada de prospectos → clip gancho de su contenido → mensaje personalizado generado → envío
**manual** por el operador (~10/semana) → seguimiento de estado (contactado, respondió, cliente, descartado).

## 7. Requisitos funcionales (priorizados)

Prioridad: **M** = MVP, **2** = Fase 2, **3** = Fase 3.

| ID | Requisito | Prio |
|---|---|---|
| RF-01 | Gestionar clientes y su objetivo (perfil editorial, KPI, plataformas, cadencia, caducidad). | M |
| RF-02 | Gestionar fuentes por cliente (YouTube, Kick, TikTok), extensible a nuevas plataformas. | M |
| RF-03 | Ingesta programada que detecta contenido nuevo de las fuentes. | M |
| RF-04 | Flujo de producción ejecutado por el engine, reanudable por paso. | M |
| RF-05 | Copy y selección guiados por el perfil editorial del cliente. | M |
| RF-06 | Revisión del operador: aprobar / editar / descartar con razón. | M |
| RF-07 | Inventario por cliente con caducidad configurable (default 30 días). | M |
| RF-08 | Despacho según cadencia por cliente (default 4/día). | M |
| RF-09 | Publicación: paquete manual (default) + API YouTube Shorts + borrador TikTok. | M |
| RF-10 | Cuentas de destino propias del operador o del cliente. | M |
| RF-11 | Recolección de métricas por clip publicado. | M |
| RF-12 | Reporte por cliente según su KPI. | M (simple) / 2 (completo) |
| RF-13 | Prospección: prospectos, clip gancho, mensaje generado, estado. | M |
| RF-14 | Registro de costo por paso y por clip. | M |
| RF-15 | Publicación automática en Facebook Reels. | 2 |
| RF-16 | Panel web del operador. | 2 |
| RF-17 | Agente revisor por cliente. | 2 |
| RF-18 | Aprendizaje automático desde métricas. | 2 |
| RF-19 | Cobro y facturación. | 2 |
| RF-20 | Portal del cliente. | 3 |
| RF-21 | Agentes de negocio / PO / dev / finanzas. | 3 |

## 8. Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | **Costo ≈ 0 en MVP**: IA, transcripción e infraestructura gratuitas o cubiertas por suscripciones existentes. |
| RNF-02 | **Proveedor de IA intercambiable** por paso (Claude Code / API Claude / modelos open source / free tiers). |
| RNF-03 | **Extensible**: nuevas fuentes, plataformas de destino y pasos sin tocar el núcleo del engine. |
| RNF-04 | **Portable**: sin rutas ni comandos atados a una PC concreta. |
| RNF-05 | **Idempotente y reanudable**: cualquier paso puede reintentarse sin duplicar clips ni publicaciones. |
| RNF-06 | **Trazable**: cada clip conserva su origen, decisiones, costo y resultado. |
| RNF-07 | **Seguro**: credenciales de cuentas fuera del repositorio, cifradas, por cliente. |
| RNF-08 | **Continuidad para agentes**: `CLAUDE.md` + docs de estado permiten a otra sesión retomar el trabajo. |
| RNF-09 | **Multi-cliente** desde el modelo de datos, aunque se opere con pocos clientes. |

## 9. Estrategia de IA (por aterrizar)

Hay tres opciones, combinables por paso gracias a RNF-02:

| Opción | Costo | Calidad (español peruano, jerga, copy) | Automatización | Comentario |
|---|---|---|---|---|
| **Claude Code como operador** (modo manual del piloto) | Incluido en la suscripción | Alta | Semi-automática (requiere una sesión activa) | Ideal para MVP con bajo volumen. Los límites de uso de la suscripción y sus términos no la hacen viable para 100 clientes. |
| **Modelos open source** (Llama, Qwen, Gemma, Mistral) locales vía Ollama o en free tiers (Groq, OpenRouter, Gemini free) | 0 (local) o gratuito con límites | Media; hay que evaluar | Total | Buenos para pasos simples (clasificar, filtrar, resumir). Local requiere GPU o es lento. |
| **API de Claude** | Por uso | Alta | Total | Activar cuando haya ingresos; medir costo por clip vs. S/ 2. |

**Propuesta a validar:** en el MVP, pasos de juicio fino (detección, copy) con Claude Code; pasos
mecánicos con open source/free tiers; benchmark con clips y feedback reales del piloto para decidir
qué pasos pueden migrar a modelos gratuitos. La transcripción ya es open source (WhisperX).

## 10. Alcance

### MVP (~2 meses, referencial)
RF-01 a RF-14. Un cliente de prueba (Fritz Sport) + cuentas de captación. Operación por CLI/archivos
o interfaz mínima; sin portal de cliente, sin cobro automatizado.

### Fuera del MVP
Panel web completo, agente revisor, Facebook Reels por API, cobro, portal del cliente, agentes de
negocio. Envío automatizado de mensajes directos (**excluido por diseño**, ver R-03).

## 11. Supuestos, riesgos y decisiones

| ID | Tipo | Descripción | Mitigación / estado |
|---|---|---|---|
| R-01 | **Supuesto y riesgo aceptado — contenido de terceros** | En captación se clipea contenido de acceso público de figuras del medio y se publica en cuentas propias del operador. Práctica habitual del ecosistema de clips, operada dentro de las políticas de cada plataforma y aceptando sus mecanismos de control (reclamos, retiro, desmonetización, reparto de ingresos con el titular). No constituye dictamen legal. | (1) Cuentas de captación separadas de las de clientes; (2) monitoreo de reclamos/strikes por cuenta y freno automático de publicación; (3) retiro inmediato ante solicitud; (4) lista de creadores que pidieron no ser clipeados; (5) paso a contenido autorizado cuando el creador se vuelve cliente; (6) consulta legal breve cuando el negocio escale. |
| R-02 | Riesgo | Acceso a APIs de publicación (auditoría TikTok, revisión de app Meta, cuota YouTube). | Publicación manual por defecto; reutilizar integraciones de v1 (YouTube automático, TikTok como borrador). |
| R-03 | Riesgo | Mensajes directos masivos → bloqueo de cuenta por spam. | Envío manual, ~10/semana, selectivo. |
| R-04 | Riesgo | Dependencia de la suscripción de Claude para producción. | Capa de IA intercambiable; benchmark de modelos gratuitos. |
| R-05 | Riesgo | Transcripción en Colab efímero. | Versionar el servidor Colab; alternativa local. |
| R-06 | Riesgo | Operador único = cuello de botella (revisión, ventas, desarrollo). | Diseñar revisión delegable a agente; automatizar ingesta/despacho. |
| R-07 | Supuesto | El margen de 1 mes hasta publicar permite procesamiento por lotes, sin tiempo real. | Confirmado por el operador. |
| R-08 | Supuesto | Clips de actualidad pierden valor rápido. | Atributo de frescura en inventario; priorización. |
| D-01 | Decisión | "Nicho" del piloto → "Cliente" en v2. | Confirmado. |
| D-02 | Decisión | Producción y despacho son flujos separados con inventario en medio. | Confirmado. |
| D-03 | Decisión | Defaults: 4 clips publicados/día, caducidad 30 días, configurables. | Confirmado. |

## 12. Brechas frente al piloto (AS-IS → TO-BE)

| Área | AS-IS | TO-BE |
|---|---|---|
| Orquestación | `pipeline.py` imperativo | Engine de flujos declarativo y reanudable |
| Unidad de negocio | Nicho/canal (YAML) | Cliente con objetivo, fuentes y cuentas |
| Ingesta | Manual por CLI | Job programado por fuentes del cliente |
| Salida | Carpeta `clips/` | Inventario con estados y caducidad |
| Revisión | `input()` en terminal | Interfaz de revisión, delegable a agente |
| Publicación | Fuera del repo (v1: YouTube auto, TikTok notificación) | Módulo de despacho multi-plataforma |
| Métricas | Feedback manual 24–48 h | Recolección automática por API |
| IA | Claude API / modo manual, modelo fijo | Proveedor por paso, costo medido |
| Comercial | — | Módulo de prospección |
| Portabilidad | PC Windows del operador | Portable |

## 13. Preguntas abiertas

1. **Código de publicación de v1** (YouTube Shorts automático, TikTok por notificación) no está en el
   repo: ¿se puede subir para reutilizarlo?
2. Publicación desde la computadora del operador con sus sesiones (control remoto del navegador):
   ¿se mantiene como respaldo? (Recomendación: no como mecanismo principal — frágil y riesgoso para
   las credenciales; preferir APIs + paquete manual.)
3. ¿Se incluye Instagram Reels como destino (además de Facebook Reels)?
4. ¿Formato del reporte al cliente (enlace web, PDF, mensaje por WhatsApp)?
5. ¿Precio por clip publicado o por clip producido? ¿Mensualidad mínima?
6. ¿Quién es dueño de las cuentas de captación y cuántas se prevén por nicho?
