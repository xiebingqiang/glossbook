"""Language table: names, word segmentation (space-delimited vs CJK), letter case,
abbreviations, and the UI strings used inside notes."""

RTL = {"ar", "he", "fa", "ur", "yi", "ps", "sd", "ug", "dv"}
CJK = {"zh", "ja"}
CASELESS = {"ko", "th", "ka", "hy"}  # no letter case: don't require a capital after a full stop

NAMES = {
    "en": "English", "it": "Italian", "fr": "French", "es": "Spanish", "pt": "Portuguese",
    "de": "German", "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian",
    "nb": "Norwegian", "fi": "Finnish", "pl": "Polish", "cs": "Czech", "sk": "Slovak",
    "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish", "el": "Greek", "ro": "Romanian",
    "hu": "Hungarian", "ca": "Catalan", "hr": "Croatian", "sr": "Serbian", "bg": "Bulgarian",
    "ko": "Korean", "zh": "Chinese (Simplified)", "zh-hant": "Chinese (Traditional)",
    "ja": "Japanese", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
    "la": "Latin", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "ur": "Urdu",
}

# Abbreviations that end with a period but don't end a sentence (lowercase, without the final
# period). Single capital letters (initials) are handled separately.
ABBR = {
    "en": {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "vs", "etc", "e.g", "i.e", "no", "mt",
           "gen", "col", "capt", "lt", "sgt", "rev", "fig"},
    "it": {"sig", "sigg", "sig.ra", "dott", "dott.ssa", "prof", "ecc", "avv", "ing", "on", "p.es",
           "n.d.t", "s", "ss"},
    "fr": {"m", "mm", "mme", "mlle", "dr", "st", "ste", "etc", "cf", "p.ex", "n.d.t", "av", "apr", "j.-c"},
    "es": {"sr", "sra", "srta", "d", "dña", "dr", "dra", "ud", "uds", "etc", "p.ej", "pág", "núm"},
    "pt": {"sr", "sra", "srta", "dr", "dra", "d", "etc", "p.ex", "pág", "v.exa"},
    "de": {"hr", "fr", "dr", "prof", "z.b", "usw", "bzw", "ca", "vgl", "evtl", "d.h", "u.a", "nr", "st", "str"},
    "nl": {"dhr", "mevr", "dr", "prof", "bijv", "enz", "d.w.z", "o.a", "nr", "st"},
    "la": {"cn", "sex", "ti", "tib", "ap", "sp", "ser", "kal", "non", "id", "a.d", "cos", "coss", "procos",
           "trib", "pl", "leg", "imp", "praef", "cf"},   # praenomina and dates: "Cn. Pompeius", "a.d. III Kal. Mai."
    "ru": {"г", "гг", "т.е", "т.д", "т.п", "др", "им", "ул", "стр", "см", "проф"},
}


def base(code):
    """'it-IT' -> 'it'; Traditional Chinese ('zh-Hant', 'zh-TW', ...) -> 'zh-hant'."""
    code = (code or "").strip().lower().replace("_", "-")
    if code.startswith("zh") and ("hant" in code or code.endswith(("-tw", "-hk", "-mo"))):
        return "zh-hant"
    return code.split("-")[0]


def _family(code):
    return base(code).split("-")[0]


def is_cjk(code):
    return _family(code) in CJK


def is_rtl(code):
    return base(code) in RTL


def has_case(code):
    return not (is_cjk(code) or base(code) in CASELESS)


def name(code):
    return NAMES.get(base(code)) or NAMES.get(_family(code)) or code


def known(code):
    return base(code) in NAMES or _family(code) in NAMES


def abbreviations(code):
    return ABBR.get(_family(code), set()) | ABBR["en"]


# Labels shown in notes and in the preview: summary / characters / key words / cultural note
UI = {
    "en": {"summary": "Summary", "who": "Characters", "kw": "Key words", "culture": "Note"},
    "zh": {"summary": "大意", "who": "人物", "kw": "关键词", "culture": "注"},
    "zh-hant": {"summary": "大意", "who": "人物", "kw": "關鍵詞", "culture": "注"},
    "ja": {"summary": "あらすじ", "who": "登場人物", "kw": "キーワード", "culture": "注"},
    "ko": {"summary": "줄거리", "who": "등장인물", "kw": "핵심어", "culture": "주"},
    "fr": {"summary": "Résumé", "who": "Personnages", "kw": "Mots clés", "culture": "Note"},
    "de": {"summary": "Überblick", "who": "Figuren", "kw": "Schlüsselwörter", "culture": "Anm."},
    "es": {"summary": "Resumen", "who": "Personajes", "kw": "Palabras clave", "culture": "Nota"},
    "it": {"summary": "Riassunto", "who": "Personaggi", "kw": "Parole chiave", "culture": "Nota"},
    "pt": {"summary": "Resumo", "who": "Personagens", "kw": "Palavras-chave", "culture": "Nota"},
    "ru": {"summary": "Кратко", "who": "Персонажи", "kw": "Ключевые слова", "culture": "Прим."},
}


def ui(code):
    return UI.get(base(code)) or UI.get(_family(code)) or UI["en"]


TITLE_SUFFIX = {"zh": "（注释版）", "zh-hant": "（註釋版）", "ja": "（注釈版）"}


def title_suffix(code):
    """Appended to the book title so the annotated copy is distinguishable in the library."""
    return TITLE_SUFFIX.get(base(code), "(annotated)")


def list_sep(code):
    """Separator between items inside a note."""
    return "；" if is_cjk(code) else "; "
