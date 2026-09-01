# Informe: Investigación web de contexto para Tío Yolu

Investigación web realizada por un agente Claude Code (WebSearch, sin gastar la API de Anthropic — ver memoria `preferencia-claude-code-reemplaza-scripts-de-api`), 2026-07-31. Insumo para enriquecer `contexto/entidades/yolu.yaml` de cara a la primera prueba real del pipeline con contenido del canal propio de Yolu. Complementa `yolu_investigacion_clips_2026-07-29.md` (barrido de patrones de clips virales, hecho dos días antes) — ese informe cubre CÓMO se edita/distribuye el contenido; este cubre QUÉ hechos reales hay detrás del lore.

## Alcance

Por decisión explícita del usuario, esta investigación cubrió **solo Yolu y sus personajes directos** (Tía Yolu, Matiwasi, Jorgito Muñoz) — Fritz y Noto (las otras 2 entidades del nicho `zapatillas_peru`) quedan fuera, para cuando les toque su propia prueba.

## Hallazgos confirmados (múltiples fuentes)

1. **Origen del negocio**: Jordy/Yordi Picón Andrade empezó vendiendo ambulante en Gamarra a los 17 años; hoy abastece 1,800 tiendas en Perú, 3,000-4,000 pares diarios (La República, Infobae, marzo 2025).
2. **Caso Farfán (mayo 2026)**: enriquecido con timeline exacto (joven esperó de 1:45pm a 4:30pm) y cobertura nacional amplia (La República, ATV, Wapa, El Popular, RPP) — fue noticia de farándula real.
3. **Atentado con explosivo (13 de octubre de 2023)**: más antiguo de lo que el YAML anterior implicaba (decía "2026" sin fecha exacta). Conectado a una visita del cantante Chechito, disparos contra el segundo piso habitado por la familia, amenazas de "El Tren de Aragua" por S/30,000.
4. **Extorsión en vivo (abril 2026)**: pedido de $200,000 USD durante una transmisión, investigado por Depincri Huánuco — evento distinto y más reciente que el atentado de 2023 (antes estaban mezclados en una sola polémica genérica).
5. **Policías dados de baja (2026)**: 3 suboficiales sancionados por Resolución N° 863 tras protagonizar un spot publicitario de Yolu disfrazado de intervención policial — polémica nueva, no estaba documentada.
6. **César Acuña** (político real, gobernador de La Libertad, fundador de la Universidad César Vallejo): visitante recurrente de la tienda, contenido de humor probándose zapatillas de lujo junto a Yolu/Matiwasi — mismo tipo de cruce político-viral que Franco Vidal en `streamers_peru`.

## Hallazgo descartado por decisión del usuario

Se encontró (en una sola fuente, Diario Ahora, no replicada en medios grandes) una denuncia de una extrabajadora contra ambos dueños por agresión física durante una reunión del 20 de junio, con detención inicial de Picón por sospecha de tentativa de homicidio y posterior liberación. **El usuario decidió excluir este hallazgo por completo** — no se incluyó en `yolu.yaml` ni en los eventos nuevos, ni la versión con detalle ni una versión genérica. La polémica de "conflicto laboral" que ya existía en el YAML (genérica, sin estos detalles) se dejó tal cual estaba, sin modificar.

## Archivos actualizados

- `contexto/entidades/yolu.yaml` — descripción enriquecida, nuevo personaje (César Acuña), 3 polémicas nuevas/separadas (atentado 2023 y extorsión 2026 separados en dos entradas en vez de una mezclada; policías dados de baja), señales de detección ampliadas.
- `contexto/eventos/2026-07/yolu_extorsion_llamada_200k.yaml` (nuevo)
- `contexto/eventos/2026-07/yolu_atentado_explosivo_chechito.yaml` (nuevo)
- `contexto/eventos/2026-07/yolu_policias_retiro_spot.yaml` (nuevo)

## Pendiente

`seo_base` de `zapatillas_peru` ya se pobló en la sesión anterior (hashtags/notas de TikTok y YouTube Shorts) — no requirió actualización en esta investigación. La entidad sigue marcada en su propio YAML como "sin datos de vistas confirmados aún" para las señales de detección — esta investigación agrega hechos reales del lore, pero no valida todavía qué tan bien detecta/redacta el sistema con contenido real del canal propio de Yolu (eso lo resuelve la primera corrida real).
