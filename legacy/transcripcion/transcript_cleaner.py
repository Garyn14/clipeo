"""
transcript_cleaner.py — Corrige errores de transcripción de nombres conocidos.

Usa los personajes definidos en el config del ecosistema para detectar y
corregir variantes erróneas que Whisper genera (confusión S/C, vocales
dobles, vocales extras al final).
"""

import re

_VOWELS = set("aeiouáéíóú")


def _first_letter_swap(name: str) -> str | None:
    if not name:
        return None
    first = name[0].upper()
    if first == "S":
        return "C" + name[1:]
    if first == "C":
        return "S" + name[1:]
    return None


def _generate_variants(canonical: str) -> set[str]:
    result: set[str] = set()

    def _add_with_swap(s: str) -> None:
        result.add(s)
        sw = _first_letter_swap(s)
        if sw:
            result.add(sw)

    # 1. Primera letra S↔C
    sw = _first_letter_swap(canonical)
    if sw:
        result.add(sw)

    # 2. Agregar/quitar vocal al final
    if canonical[-1].lower() in _VOWELS:
        trimmed = canonical[:-1]
        _add_with_swap(trimmed)
    else:
        for v in ("a", "e", "o"):
            _add_with_swap(canonical + v)

    # 3. Doblar cada vocal en su propia posición (ej: Sideral → Siideral)
    for i, ch in enumerate(canonical):
        if ch.lower() in _VOWELS:
            doubled = canonical[:i] + ch + canonical[i:]
            _add_with_swap(doubled)

    # 4. Re-insertar cada vocal antes de vocales posteriores
    #    (cubre Sideral → Sidereal: la 'e' de pos 3 insertada antes de la 'a' en pos 5)
    vowel_positions = [i for i, c in enumerate(canonical) if c.lower() in _VOWELS]
    for k, i in enumerate(vowel_positions):
        ch = canonical[i]
        for j in vowel_positions[k + 1:]:
            inserted = canonical[:j] + ch + canonical[j:]
            _add_with_swap(inserted)

    result.discard(canonical)
    return result


def clean_known_names(text: str, config: dict, silent: bool = False) -> str:
    """
    Reemplaza variantes erróneas de nombres conocidos por su forma canónica.

    El nombre canónico es el primero en la lista "nombres" de cada personaje.
    Si config no tiene "personajes", retorna el texto sin cambios.
    """
    personajes = config.get("personajes")
    if not personajes:
        return text

    resultado = text
    total_corrections = 0

    for personaje in personajes:
        nombres = personaje.get("nombres", [])
        if not nombres:
            continue
        canonical = nombres[0]
        variants = _generate_variants(canonical)

        # Correcciones explícitas: nombres multi-palabra del config
        # (evita falsos positivos de nombres de una sola palabra)
        for nombre_extra in nombres[1:]:
            if " " in nombre_extra:
                variants.add(nombre_extra)

        # Mayor longitud primero para evitar reemplazos parciales
        for variant in sorted(variants, key=len, reverse=True):
            pattern = r"\b" + re.escape(variant) + r"\b"
            count = len(re.findall(pattern, resultado, flags=re.IGNORECASE))
            if count > 0:
                resultado = re.sub(pattern, canonical, resultado, flags=re.IGNORECASE)
                print(f'[CLEANER] "{variant}" → "{canonical}" ({count} ocurrencias)')
                total_corrections += count

    if total_corrections > 0:
        print("[CLEANER] Transcripción limpiada ✅")
    elif not silent:
        print("[CLEANER] Sin correcciones necesarias")

    return resultado
