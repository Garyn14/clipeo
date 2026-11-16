# Informe: Clips virales y contexto de Franco Vidal (alcalde-streamer de Ate, Perú)

Investigación combinada — scraping manual del usuario (TikTok, clips más virales) + investigación web de un agente Claude, 2026-07-30. Insumo para enriquecer `contexto/entidades/franco_vidal.yaml`.

## 1. Metodología

- **Scraping de clips (usuario):** búsquedas en TikTok por "Franco vidal clips", "Franco vidal viral" y "El vidalismo". 24 clips relevados de 12 cuentas distintas, con título/overlay, contenido y razón de viralidad estimada por cada uno.
- **Investigación web (Claude, WebSearch):** ~11 búsquedas dirigidas a biografía, familia, polémicas 2025-2026, contexto de reelección y rivalidades, usando fuentes como Infobae, La República, Peru21, Willax, Caretas y El Comercio.
- **Limitaciones:** el scraping del usuario es observacional (no cuantitativo salvo likes/comentarios puntuales). La investigación web no verificó fuentes primarias en todos los casos — un dato específico (presunto hallazgo de un cuerpo en una propiedad del padre, 2013) se dejó fuera del YAML por no estar confirmado en fuente primaria, solo citado indirectamente.

## 2. Cuentas identificadas en el scraping

**Cuentas fan/clipper dedicadas:**
`@elvidalismo`, `@clips.vidalpresi8`, `@fvidalitos.edits`, `@dibuclips`, `@francovidalismo27`, `@clip.master499`, `@francokickvidal`

**Cuentas de cruce/comunidad streaming:**
`@fvidal.kick`, `@kickasosperuoff`, `@galareacciona` (formato "reacciona a"), `@show.en.ate`

**Cuenta oficial:**
`@francovidalm`

## 3. Patrones de contenido observados (scraping)

| Patrón | Frecuencia observada | Notas |
|---|---|---|
| Confrontación/rivalidad política (candidatos, vecinos) | Alta | Choques verbales con Edde Cuéllar, vecinos por temas de basura/obras — genera comentarios polarizados |
| Obras públicas "antes/después" | Media-alta | Parques y renovaciones (ej. Parque Puruchuco) — debate aprobación vs. escepticismo |
| Cuentas fan como motor de distribución | Alta | Gran parte de la viralidad no viene de la cuenta oficial sino de terceros (@elvidalismo, @clips.vidalpresi8, @fvidalitos.edits) |
| Cruce con comunidad Kick/streaming | Media | @fvidal.kick, @kickasosperuoff — atrae audiencia joven acostumbrada al formato "streamer" |
| Formato "reacciona a" (terceros reaccionando) | Baja-media | Cruce de audiencias entre el reactor y los fans de Vidal |
| Títulos tipo "titular de noticia" (mayúsculas, tono informativo) | Alta en cuentas fan | Distinto al estilo narrativo-curiosidad ya validado editorialmente para este nicho — se deja como observación, sin cambiar las reglas de copy vigentes |
| Contenido con etiqueta de "generado por IA" (TikTok) | Aislado | Un clip revisado traía esa etiqueta — variable a monitorear, no se investigó más a fondo |

## 4. Hallazgos de la investigación web (nuevo respecto al YAML anterior)

1. **Biografía**: nacido 2 abril 1995, abogado (USMP), electo alcalde de Ate en 2022 por Avanza País.
2. **Familia — padre Manuel Vidal Camargo**: antecedentes de prisión por estafa (1997) y proxenetismo (2006, Lurigancho); investigado 120 días por usurpación de funciones (uso de personal municipal para amenazar a un tercero); es candidato a la alcaldía de Ate 2026 por Avanza País, el mismo partido que Franco dejó.
3. **Contratos a una misma familia**: investigación de La Encerrona (ago-sep 2025), 184 órdenes sin licitación, S/2.2M ampliados a casi S/30M en reportes posteriores.
4. **Demolición Cerro Candela / Av. Nicolás Ayllón**: +40 viviendas demolidas desde oct-2025, afecta a cientos de familias, conflicto extendido hasta mayo-2026, incluye la frase viral "¿Por qué te vamos a indemnizar? Cero soles" (ene-2026).
5. **Ruptura con José Jerí** (presidente interino, ene-2026): crítica en vivo por falta de presupuesto a poblaciones vulnerables.
6. **Estrategia "teniente alcalde"** (jun-2026): junto a +15 alcaldes de Lima, elude la prohibición de reelección postulando como teniente alcalde — acusaciones de "reelección encubierta".
7. **Rivalidad con Edde Cuéllar** (ex alcalde, candidato rival Podemos Perú 2026): denuncia de gasto de S/320 mil en maceteros.
8. **Entrenamiento de boxeo con el presidente Balcázar en Kick** (mar-2026), complementa la entrevista ya documentada en el lore.

## 5. Ejemplos concretos del scraping (mayor engagement reportado)

**1. @clips.vidalpresi8 — confrontación con candidato rival**
Overlay: *"FRANCO VIDAL PONE EN SU LUGAR A CANDIDATO QUE CRITICA LA BASURA FUERA DEL HORARIO ESTABLECIDO"*. 9,082 likes / 127 comentarios. El insulto/broma ("payaso") dirigido al candidato rival (Edde Cuéllar) mezcla rivalidad política con humor — coincide con el patrón de confrontación que ya prioriza el nicho.

**2. @elvidalismo — "Alcalde recuerda momento de gestión de obras"**
1,632 likes / 44 comentarios. Comentarios centrados en debate sobre obras públicas — coincide con el patrón "antes/después".

**3. @francokickvidal — Parque Puruchuco antes/después**
*"Parque Puruchuco antes y después: renovación en Ate por alcalde Franco Vidal"*. Formato comparativo genera comentarios de aprobación o crítica de gestión.

## 6. Patrones nuevos no anticipados (resumen)

1. **La distribución real de este personaje depende de un ecosistema de cuentas fan/clipper**, no solo de su cuenta oficial — relevante si en el futuro se evalúa colaborar o diferenciarse de ese contenido.
2. **Rivalidad familiar-política activa**: tanto el padre de Vidal como su propio rival político (Cuéllar) son candidatos en las mismas elecciones 2026 — un cruce narrativo poco común en el ecosistema de streamers.
3. **Escalada de conflictos con autoridades nacionales** (ruptura con José Jerí) — el personaje ya no solo confronta a nivel local/vecinal sino también a nivel de gobierno central.
4. **Etiqueta de contenido "generado por IA"** vista en al menos un clip de terceros — posible variable de rendimiento a monitorear a futuro, sin investigación adicional por ahora.
