import re

# --------------------------------------------------------------- configuracion

DEFAULT_VIDEO = {
    "width": 1920,
    "height": 1080,
    "font_size": 59,
    "margin_left": 30,
    "margin_right": 30,
    "margin_vertical": 45,
}

DEFAULT_GROUP = {
    "pause_threshold_ms": 800,
    "max_chars": 40,  # linea legible mientras se canta
    "lead_in_ms": 2000,  # anticipacion MAXIMA; se recorta si no cabe
    "hold_out_ms": 600,  # permanencia MAXIMA despues de la ultima silaba
    "min_syllable_cs": 6,  # por debajo de esto no se trocea la palabra
}

DEFAULT_STYLE = {
    "name": "Karaoke",
    "font": "Arial Black",
    "primary": "&H00FFFF00",
    "secondary": "&H00FF00FF",
    "outline": "&H00000000",
    "back": "&H80000000",
    "outline_width": 3,
    "shadow": 2,
    "alignment": 2,  # bottom-center
}


def config_video_desde_resolucion(width, height):
    """Deriva la configuracion del ASS de la resolucion real del video.

    Antes estaba fijada a 1920x1080, lo que obligaba a reescalar todos los
    videos a 1080p solo para que encajaran con el subtitulo.
    """
    return {
        "width": int(width),
        "height": int(height),
        "font_size": max(24, round(height * 0.055)),
        "margin_left": max(16, round(width * 0.016)),
        "margin_right": max(16, round(width * 0.016)),
        "margin_vertical": max(20, round(height * 0.042)),
    }


# ------------------------------------------------------------------- silabeado

VOCALES_FUERTES = set("aeoAEOáéóÁÉÓ")
VOCALES_DEBILES = set("iuIUüÜíúÍÚ")
VOCALES = VOCALES_FUERTES | VOCALES_DEBILES
DEBIL_ACENTUADA = set("íúÍÚ")
_E_I = set("eiEIéíÉÍ")

# Grupos consonanticos que nunca se separan en espanol
INSEPARABLES = {
    "pr",
    "br",
    "tr",
    "dr",
    "cr",
    "gr",
    "fr",
    "pl",
    "bl",
    "cl",
    "gl",
    "fl",
    "ch",
    "ll",
    "rr",
    "qu",
    "gu",
}


def _es_vocal(c):
    return c in VOCALES


def _u_muda(p, i):
    """La u de que/qui/gue/gui no forma nucleo silabico."""
    return (
        p[i] in "uU"
        and i > 0
        and p[i - 1] in "qgQG"
        and i + 1 < len(p)
        and p[i + 1] in _E_I
    )


def _mismo_nucleo(a, b):
    """True si dos vocales contiguas forman diptongo (misma silaba)."""
    if a in DEBIL_ACENTUADA or b in DEBIL_ACENTUADA:
        return False  # hiato: di-a, ba-ul
    if a in VOCALES_FUERTES and b in VOCALES_FUERTES:
        return False  # hiato: le-on, ca-os
    return True  # diptongo: sie, nue, ai


def split_syllables(palabra):
    """Divide una palabra espanola en silabas segun las reglas ortograficas."""
    if not palabra:
        return [palabra]
    if not any(c.isalpha() for c in palabra):
        return [palabra]

    p = palabra
    n = len(p)

    # 1) nucleos vocalicos (con diptongos e hiatos)
    nucleos = []
    i = 0
    while i < n:
        if _es_vocal(p[i]) and not _u_muda(p, i):
            j = i + 1
            while (
                j < n
                and _es_vocal(p[j])
                and not _u_muda(p, j)
                and _mismo_nucleo(p[j - 1], p[j])
            ):
                j += 1
            nucleos.append((i, j))
            i = j
        else:
            i += 1

    if len(nucleos) <= 1:
        return [p]

    # 2) reparto de consonantes entre nucleos consecutivos
    cortes = []
    for k in range(len(nucleos) - 1):
        fin_v = nucleos[k][1]
        ini_v = nucleos[k + 1][0]
        cons = p[fin_v:ini_v]
        c = len(cons)
        if c == 0:
            corte = ini_v
        elif c == 1:
            corte = fin_v
        elif c == 2:
            corte = fin_v if cons.lower() in INSEPARABLES else fin_v + 1
        elif c == 3:
            corte = (
                fin_v + 1 if cons[1:].lower() in INSEPARABLES else fin_v + 2
            )
        else:
            corte = (
                fin_v + 2
                if cons[2:].lower() in INSEPARABLES
                else fin_v + c - 1
            )
        cortes.append(corte)

    partes, prev = [], 0
    for c in cortes:
        partes.append(p[prev:c])
        prev = c
    partes.append(p[prev:])
    return [x for x in partes if x]


# --------------------------------------------------------------------- tiempos


def segundos_a_tiempo_srt(segundos):
    segundos = float(segundos)
    horas, resto = divmod(segundos, 3600)
    minutos, resto = divmod(resto, 60)
    segs, frac = divmod(resto, 1)
    return "{:02}:{:02}:{:02},{:03}".format(
        int(horas), int(minutos), int(segs), int(frac * 1000)
    )


def parse_time_to_ms(time_str):
    m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", time_str)
    if not m:
        raise ValueError("Formato de tiempo invalido: " + str(time_str))
    h, mm, s, ms = map(int, m.groups())
    return h * 3600000 + mm * 60000 + s * 1000 + ms


def ms_to_ass_time(ms):
    ms = max(0, int(ms))
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return "{}:{:02d}:{:02d}.{:02d}".format(h, m, s, cs)


def parse_srt_word_level(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    words = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"([\d:,]+)\s*-->\s*([\d:,]+)", lines[1])
        if not m:
            continue
        text = " ".join(lines[2:]).strip()
        if not text:
            continue
        start_ms = parse_time_to_ms(m.group(1))
        end_ms = parse_time_to_ms(m.group(2))
        if end_ms < start_ms:
            end_ms = start_ms
        words.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return words


# -------------------------------------------------------------------- agrupado


def group_words(words, cfg_video, cfg_group):
    """Agrupa palabras sueltas en lineas cantables."""
    if not words:
        return []

    max_chars = cfg_group.get("max_chars", DEFAULT_GROUP["max_chars"])
    pausa = cfg_group.get(
        "pause_threshold_ms", DEFAULT_GROUP["pause_threshold_ms"]
    )

    def largo(grupo, extra=None):
        textos = [w["text"] for w in grupo]
        if extra:
            textos.append(extra["text"])
        return len(" ".join(textos))

    frases = []
    actual = [words[0]]
    for i in range(1, len(words)):
        prev_w, w = words[i - 1], words[i]
        hueco = w["start_ms"] - prev_w["end_ms"]
        cortar = (
            hueco > pausa
            or (
                prev_w["text"].rstrip().endswith((".", "!", "?"))
                and hueco > 500
            )
            or largo(actual, w) > max_chars
        )
        if cortar:
            frases.append(actual)
            actual = [w]
        else:
            actual.append(w)
    if actual:
        frases.append(actual)

    # Fusiona lineas huerfanas muy cortas con la siguiente si caben y van
    # seguidas
    optimizado = []
    i = 0
    while i < len(frases):
        cur = frases[i]
        if len(cur) < 3 and i + 1 < len(frases):
            nxt = frases[i + 1]
            hueco = nxt[0]["start_ms"] - cur[-1]["end_ms"]
            if hueco < 600 and largo(cur + nxt) <= max_chars:
                optimizado.append(cur + nxt)
                i += 2
                continue
        optimizado.append(cur)
        i += 1
    return optimizado


# ------------------------------------------------------------------ generacion


def ass_header(cfg_video, style):
    return (
        "[Script Info]\n"
        "Title: Karaoke\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        "PlayDepth: 0\n"
        "Timer: 100.0000\n"
        # PlayResX/PlayResY son los campos validos del formato ASS. Sin ellos
        # libass asume 384x288 y escala la tipografia ~3.75x sobre 1080p.
        "PlayResX: {}\n".format(cfg_video["width"])
        + "PlayResY: {}\n".format(cfg_video["height"])
        + "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        + (
            "Style: {},{},{},{},{},{},{},1,0,0,0,100,100,0,0,1,"
            "{},{},{},{},{},{},1\n\n"
        ).format(
            style["name"],
            style["font"],
            cfg_video["font_size"],
            style["primary"],
            style["secondary"],
            style["outline"],
            style["back"],
            style["outline_width"],
            style["shadow"],
            style["alignment"],
            cfg_video["margin_left"],
            cfg_video["margin_right"],
            cfg_video["margin_vertical"],
        )
        + "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )


def _tiene_letras(tok):
    return any(ch.isalpha() for ch in tok)


def _reparte_silabas(texto, dur_cs, min_cs):
    """Reparte la duracion de una palabra entre sus silabas.

    La suma de los trozos es EXACTAMENTE la duracion de la palabra. Aplicar un
    minimo por silaba inflaba el total y hacia que el resaltado se retrasara un
    poco mas en cada palabra, acumulando desfase a lo largo de la frase.
    """
    tokens = split_syllables(texto) or [texto]
    cronometradas = [t for t in tokens if _tiene_letras(t)]

    if not cronometradas:
        return [(tokens[0], dur_cs)] + [(t, 0) for t in tokens[1:]]

    # Palabra demasiado rapida para trocearla de forma perceptible: se deja
    # entera en lugar de partirla en destellos.
    if dur_cs < min_cs * len(cronometradas):
        return [(texto, dur_cs)]

    total_chars = sum(len(t) for t in cronometradas)
    partes = []
    asignado = 0
    restantes = len(cronometradas)
    for tok in tokens:
        if not _tiene_letras(tok):
            partes.append((tok, 0))
            continue
        restantes -= 1
        if restantes == 0:
            cs = dur_cs - asignado  # el ultimo absorbe el resto: suma exacta
        else:
            cs = int(round(dur_cs * len(tok) / total_chars))
            cs = max(0, min(cs, dur_cs - asignado))
        asignado += cs
        partes.append((tok, cs))
    return partes


def _texto_karaoke(phrase_words, inicio_linea, cfg_group):
    """Construye el texto con las marcas de karaoke.

    Invariante: la suma de todas las marcas es exactamente
    (fin de la ultima palabra - inicio de la linea). Asi el resaltado llega a
    cada silaba en el instante en que se canta, sin acumular desfase.
    """
    min_cs = cfg_group.get("min_syllable_cs", DEFAULT_GROUP["min_syllable_cs"])
    primera = phrase_words[0]["start_ms"]

    # Silaba vacia inicial: consume la anticipacion sin pintar nada, de modo
    # que el barrido arranca justo cuando empieza a cantarse.
    espera_cs = max(0, int(round((primera - inicio_linea) / 10)))
    texto = "{\\k" + str(espera_cs) + "}" if espera_cs > 0 else ""

    ultimo = len(phrase_words) - 1
    for idx, w in enumerate(phrase_words):
        # Duracion real de la palabra, sin estirar.
        dur_cs = max(0, int(round((w["end_ms"] - w["start_ms"]) / 10)))

        for tok, cs in _reparte_silabas(w["text"], dur_cs, min_cs):
            texto += "{\\kf" + str(cs) + "}" + tok

        if idx < ultimo:
            # El hueco hasta la siguiente palabra se consume en el espacio, no
            # estirando la palabra anterior: asi el resaltado alcanza cada
            # palabra justo cuando toca cantarla.
            hueco_cs = max(
                0,
                int(
                    round(
                        (phrase_words[idx + 1]["start_ms"] - w["end_ms"]) / 10
                    )
                ),
            )
            texto += "{\\kf" + str(hueco_cs) + "} "

    return texto


def planificar_lineas(phrases, cfg_group):
    """Decide cuando entra y sale cada linea.

    Dos reglas que no se pueden romper, porque son las que hacen que el karaoke
    siga el ritmo de la cancion:

      1. Una linea NUNCA desaparece antes de que se termine de cantar.
      2. Una linea NUNCA aparece despues de su primera silaba.

    La anticipacion y la permanencia son maximos deseables: cuando dos frases
    van muy pegadas se recortan ellas, en vez de cortar el canto. Antes se
    hacia al reves (se truncaba el final de la linea anterior), y por eso las
    frases se esfumaban a media palabra.
    """
    lead = cfg_group.get("lead_in_ms", DEFAULT_GROUP["lead_in_ms"])
    hold = cfg_group.get("hold_out_ms", DEFAULT_GROUP["hold_out_ms"])

    plan = []
    fin_anterior = 0
    total = len(phrases)

    for i, p in enumerate(phrases):
        primera = p[0]["start_ms"]
        ultima = max(primera, p[-1]["end_ms"])

        # Entrada: lo antes posible sin pisar la linea anterior, y como muy
        # tarde justo cuando empieza a cantarse.
        inicio = max(0, primera - lead)
        inicio = max(inicio, fin_anterior)
        inicio = min(inicio, primera)

        # Salida: tras la ultima silaba, sin invadir la primera palabra de la
        # siguiente frase, pero jamas antes de que acabe el canto de esta.
        fin = ultima + hold
        if i + 1 < total:
            fin = min(fin, max(ultima, phrases[i + 1][0]["start_ms"]))
        if fin <= inicio:
            fin = inicio + 10

        plan.append((inicio, fin))
        fin_anterior = fin

    return plan


def ass_line(phrase_words, cfg_video, cfg_group=None):
    cfg_group = dict(DEFAULT_GROUP, **(cfg_group or {}))
    inicio, fin = planificar_lineas([phrase_words], cfg_group)[0]
    texto = _texto_karaoke(phrase_words, inicio, cfg_group)
    return "Dialogue: 0,{},{},{},,0,0,0,,{}".format(
        ms_to_ass_time(inicio),
        ms_to_ass_time(fin),
        DEFAULT_STYLE["name"],
        texto,
    )


def write_ass(phrases, output_path, cfg_video, cfg_group=None, style=None):
    cfg_group = dict(DEFAULT_GROUP, **(cfg_group or {}))
    style = style or DEFAULT_STYLE

    plan = planificar_lineas(phrases, cfg_group)

    lineas = []
    for (inicio, fin), p in zip(plan, phrases):
        texto = _texto_karaoke(p, inicio, cfg_group)
        lineas.append(
            "Dialogue: 0,{},{},{},,0,0,0,,{}".format(
                ms_to_ass_time(inicio),
                ms_to_ass_time(fin),
                style["name"],
                texto,
            )
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header(cfg_video, style) + "\n".join(lineas) + "\n")


def convertir_srt_a_ass(
    srt_path, ass_output, cfg_video=None, cfg_group=None, style=None
):
    cfg_video = cfg_video or DEFAULT_VIDEO
    cfg_group = dict(DEFAULT_GROUP, **(cfg_group or {}))
    style = style or DEFAULT_STYLE

    words = parse_srt_word_level(srt_path)
    if not words:
        raise ValueError("El SRT no contiene palabras validas.")

    phrases = group_words(words, cfg_video, cfg_group)
    write_ass(phrases, ass_output, cfg_video, cfg_group, style)
    return {"phrases": len(phrases), "words": len(words), "ass": ass_output}
