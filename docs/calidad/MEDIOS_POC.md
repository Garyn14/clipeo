# Medios como fuente — prueba de concepto (CLIP-34)

> 2026-11-17 · Nicho `zapatillas_peru` · Videos aprobados por el operador · Sin cortar ni publicar (R-01)

## 1. Qué se probó

Pasar videos de TV/prensa sobre Fritz por el piloto (detector A1 → A2, dirección editorial, juez con la memoria
nueva y umbral de fuerza) usando los **subtítulos automáticos de YouTube** como transcripción (sin descargar video ni
usar Colab). Herramienta: `python -m evaluacion.medios_poc <url> [--vtt archivo]`.

| Video | Resultado |
|---|---|
| Magaly TV, "pichangas millonarias" (`-lMVPYu-GMo`, 2,5 min) | ✅ Procesado |
| Panorama, entrevista exclusiva tras el ataque (`eudv9pU4Vvo`, 13 min) | ✅ Procesado en la laptop del operador (desde la nube YouTube pide "confirmar que no eres un bot") |

## 2. Resultado (Magaly)

- El detector propuso 4 picos y los fusionó en **1 momento** (00:41 → 01:30): apuestas de 50, 100 y 200 mil soles,
  fajos de billetes exhibidos "cual narcos", "¿quién lo controla? ¿la SBS? ¿Sunat?".
- La dirección editorial lo hizo arrancar en las cifras, sin la presentación.
- El juez lo aprobó con **fuerza 7/10 (⭐ prioridad)**, tipo **`medios_y_polemica`**, citando que es el tipo que más
  rinde en la cuenta propia.
- Es el mismo tema de tu clip con mejor resultado ("Máquina contadora de billetes en una pichanga de 100K soles",
  64x): **el sistema reconoce el momento que la audiencia premió.**

## 2b. Resultado (Panorama) — contra clips propios ya publicados de esa entrevista

Detector: 15 picos → 11 momentos; juez: 8 aprobados (7 con ⭐ prioridad), 3 rechazados.

| Clip propio publicado | Outlier real | Sistema |
|---|---|---|
| Fritz confiesa que las pichangas de 200k y el Corvette eran puro show | 51x | ✅ ⭐ 9/10 (Corvette aparte: ⭐ 7/10) |
| Fritz confiesa que sus vendedores usan chaleco antibala | 40x | ✅ ⭐ 8/10 |
| Fritz confiesa que los billetes y los partidos son puro show | 23x | ✅ ⭐ 7/10 |
| Máquina contadora de billetes en una pichanga de 100K soles | 64x | ✅ 6/10 (conteo de billetes) |
| Fritz llora en Panorama por empezar con 70 soles y vivir bajo extorsión | 1,6x | ✅ ⭐ 7/10 (sobrevalorado) |
| **Fritz jura que Louis Vuitton y Gucci son 100% originales en su tienda** | **58x** | ❌ **3/10 "pitch de producto"** |

- **Encuentra los 6 momentos publicados y aprueba 5.** Propone además otros no publicados (lavado de dinero ⭐ 8/10,
  guardia en cuidados intensivos ⭐ 8/10).
- **Error a corregir en la memoria:** en medios, defender la originalidad o el origen de lo que vende es **polémica**
  (`medios_y_polemica`), no `producto_y_precio` ni pitch. Propuesta para el S5, con aprobación del operador.
- La emoción sin polémica (llanto) se sobrevalora: la audiencia sigue siendo la verdad.

## 3. Qué falta para usarlo en producción (alcance propuesto para CLIP-27)

1. **Fuente:** subtítulos automáticos sirven para detectar (gratis, rápido); el corte necesita el video, que se
   descarga en la laptop (la nube está bloqueada por YouTube).
2. **Nombre del personaje:** en el segmento de Magaly no se nombra a Fritz ("estos streamers"); el título del juez
   quedó genérico ("Periodista cuestiona…"). La memoria dice que el título debe nombrar al personaje → indicar en la
   config que el video es sobre Fritz (contexto de la fuente).
3. **Hablantes:** conductores e invitados de TV no están en el mapa de hablantes del nicho; con subtítulos no hay
   diarización. Para el MVP no bloquea.
4. **Búsqueda de fuentes:** un paso que liste segmentos nuevos de TV/prensa sobre el personaje (búsqueda en YouTube por
   nombre + canales de noticias) para que el operador apruebe cuáles procesar.
5. **R-01:** contenido de terceros (canales de TV) → cuentas de captación separadas, retiro inmediato ante solicitud.

**Recomendación:** avanzar con CLIP-27 como "fuente de medios" con aprobación del operador por video, empezando por
la descarga en la laptop y el contexto "sobre quién trata".

## 4. Conclusión

Medios como fuente **funciona**: con subtítulos automáticos el sistema encuentra los momentos que la audiencia
premió (Magaly 1/1, Panorama 6/6 encontrados, 5/6 aprobados). Recomendación: CLIP-27 en el S5.
