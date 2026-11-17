# Propuesta de cambios a la memoria del nicho (CLIP-30)

> Fecha: 2026-11-17 · Nicho: `zapatillas_peru` · Archivo afectado: `legacy/investigacion/zapatillas_peru/referencias.yaml`
> **Requiere aprobación del operador.** Hasta que la apruebe, la memoria no se modifica.

## 1. De dónde sale

- **73 videos de @nandoclips93** medidos el 2026-11-17 con `yt-dlp` (solo metadata, sin login) y agregados a
  `videos.jsonl` (outlier = vistas ÷ mediana de la cuenta; mediana: 4.990 vistas).
- El **texto en pantalla** de cada video se leyó de su portada y cada video se clasificó por categoría:
  `legacy/investigacion/zapatillas_peru/cuenta_propia.jsonl` (id, título, categoría, vistas, outlier, fecha).
- Limitaciones: n chico por categoría; la clasificación es una lectura del título, no del video completo.

## 2. Qué funciona en tu cuenta

| Categoría | n | Mediana outlier | Sobre lo normal de la cuenta | Ejemplos |
|---|---|---|---|---|
| **Medios (TV/prensa sobre el personaje)** | 7 | **51,4** | **7/7** | Magaly "cómo justifica 100K", Panorama "chaleco antibala", "billetes y partidos son puro show" |
| Oferta de trabajo con sueldo | 1 | 18,0 | 1/1 | "busca personal con sueldo acorde al mercado XD" |
| **Jefe y trabajadores** | 8 | **3,7** | **6/8** | "sorprende a Rafo por supervisar bien" (23x), "exige cinco videos diarios a su editor" (7,6x) |
| Dinero y show | 7 | 1,8 | 5/7 | "revela S/200K multiplicado por 70" (7,5x), "ficha a Cueva por 200K" (3,4x) |
| Generosidad | 9 | 1,4 | 5/9 | Arriba: "descuento a mamita que no tenía cómo pagar" (106x), "apoya a chamo de Copa América" (27x). Abajo: "regala pelota a dos hermanitos" (0,2x), "SÍ REGALA DE VERDAD" (0,2x) |
| Producto y precio | 13 | 1,1 | 7/13 | Arriba: "tecnología de 599.00 a 99.90" (37x), "número uno en Adidas y Reebok" (19x). Abajo: "Shenlong" (0,2x), "chocolateras" (0,3x) |
| Humor y personaje | 11 | 0,7 | 5/11 | Arriba: "Se me paró mi Fritz XD" (21x), "indirecta a Yolu" (17x), "vouchers del tío Supera" (11x). Abajo: "graduado de la universidad de la vida" (0,1x) |
| **Retos de dominadas** | 8 | **0,35** | **0/8** | "reto 500 dominadas", "regala ferrito si llegas a cien", "le da la pelota aunque llegó a 39" |
| Anuncios | 6 | 0,27 | 1/6 | "abre tienda propia", "aumenta ventas 70%", "cuatro contenedores" |
| Nada pasa | 2 | 0,11 | 0/2 | "Todos quieren una foto con el tío Fritz" |

## 3. Cambios propuestos a la memoria

| # | Cambio | Evidencia | Efecto esperado en el juez |
|---|---|---|---|
| 1 | **Nuevo tipo `medios_y_polemica`**: el personaje en TV/prensa, polémica, dinero cuestionado, extorsión | 7/7 sobre lo normal, mediana 51x | Reconoce ese tipo de momento. **Ojo:** hoy el pipeline no procesa medios (CLIP-27), así que el efecto inmediato es menor |
| 2 | **`rivalidad_y_apuestas`: los retos de dominadas están agotados en la cuenta propia** | 8/8 bajo lo normal, mediana 0,35x | Deja de premiar "reto con premio" por sí solo; exige algo nuevo (rival, cifra grande, giro) |
| 3 | **`jefe_y_trabajadores`: no exigir "conflicto fuerte"**: sorpresa, premio, exigencia concreta o pillada ya funcionan | 6/8 sobre lo normal; "sorprende a Rafo" 23x | Acepta momentos de jefe y trabajadores que hoy rechaza por "chatos". **Coincide con tu criterio como editor** |
| 4 | **`generosidad_con_humilde`: precisar** que funciona con alguien vulnerable + necesidad concreta (no tenía cómo pagar, viaja a jugar), no con el regalo genérico | 106x y 27x frente a 0,2x | Distingue mejor la generosidad que rinde |
| 5 | **`producto_y_precio` (nuevo tipo o regla):** funciona la comparación concreta o el reclamo de ser el número uno; no la charla técnica | 37x y 19x frente a 0,2–0,3x | Rescata comparaciones de precio y descarta el pitch técnico |
| 6 | **`lo_que_no_funciona`: agregar** anuncios de negocio (salvo oferta de trabajo con sueldo), "nada pasa" (fotos, saludos) y monólogos de vida | Anuncios 1/6; "fotos" 0,1x; "universidad de la vida" 0,1x | Refuerza lo que ya hace |
| 7 | **Nota (hipótesis, no regla):** publicaciones en tanda el mismo día coinciden con bajo rendimiento | Tandas 19–26 jul y 4 oct | Ninguno (es para la publicación, Q5) |

## 4. Hallazgo clave: ni el juez ni el editor predicen bien

Diez de tus clips aprobados en la revisión ya están publicados, así que **tienen resultado real**:

| Clip | ¿Lo aprobó el juez? | Resultado real | ¿Acertó el juez? |
|---|---|---|---|
| Sorprende a Rafo | No | **23x** ✅ | ❌ |
| Exige cinco videos | Sí | **7,6x** ✅ | ✅ |
| Regala billetera | No | **6,0x** ✅ | ❌ |
| Reclama al encargado de cámaras | No | 1,7x ✅ | ❌ |
| Reta a cliente: 40 dominadas | Sí | 0,8x ❌ | ❌ |
| Pilla a Rafael (2 casos) | Uno sí, otro no | 0,7x ❌ | 1 de 2 |
| Pide perdón a sus hijos | Sí | 0,3x ❌ | ❌ |
| Reta a sus trabajadores (baile) | No | 0,3x ❌ | ✅ |
| Pelota a dos hermanitos | No | 0,2x ❌ | ✅ |

- **El juez acierta 4 de 10.**
- **Tu aprobación como editor acierta 4 de 10:** aprobaste los 10 y rindieron 4.
- Con n tan chico no es concluyente, pero confirma lo que conversamos: **la audiencia es la única verdad**. Los
  cambios 2 y 3 apuntan justo a estos errores (retos de dominadas aprobados que fallan; jefe y trabajadores
  rechazados que funcionan).

**Propuesta adicional:** sumar estos 10 casos al conjunto de evaluación con su **resultado real** como etiqueta
(en vez de "aprobado por el editor"). Son la mejor señal que tenemos.

## 5. Qué necesito del operador

1. Aprobar, ajustar o rechazar cada cambio (1–7).
2. Confirmar si los 10 casos con resultado real se usan como etiqueta en la evaluación.
