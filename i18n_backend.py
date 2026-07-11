# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
i18n_backend.py — Traductions côté serveur pour AmiorAI.

Fournit :
  t_backend(key, lang, **vars)   → chaîne traduite avec fallback EN → clé visible
  get_chargen_prompts(lang)      → (system_prompt, user_template, config_desc_fn, orientation_fn)

Les traductions sont lues depuis les JSON de locales (mêmes fichiers que le frontend).
Cache en mémoire — rechargé à la demande via reload_locales().
"""

import json
import logging
import os
import re

from app_paths import CODE_ROOT

logger = logging.getLogger(__name__)

LOCALES_DIR  = os.path.join(CODE_ROOT, "resources", "i18n", "locales")
SUPPORTED    = ("fr", "en", "es", "de")
FALLBACK     = "en"

_catalog: dict[str, dict] = {}


# ── Chargement du catalogue ────────────────────────────────────────────────────

def _load_locale(lang: str) -> dict:
    if lang in _catalog:
        return _catalog[lang]
    path = os.path.join(LOCALES_DIR, lang + ".json")
    if not os.path.isfile(path):
        logger.warning("[i18n_backend] Locale %s introuvable : %s", lang, path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _catalog[lang] = data
        return data
    except Exception as e:
        logger.error("[i18n_backend] Erreur chargement %s : %s", lang, e)
        return {}


def reload_locales():
    """Vide le cache — les locales seront rechargées au prochain accès."""
    _catalog.clear()
    logger.info("[i18n_backend] Cache locales vidé.")


def _resolve(lang: str, key: str) -> str | None:
    data = _load_locale(lang)
    parts = key.split(".")
    node = data
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return str(node) if isinstance(node, str) else None


def _interpolate(s: str, vars_: dict) -> str:
    if not vars_:
        return s
    return re.sub(r"\{(\w+)\}", lambda m: str(vars_.get(m.group(1), m.group(0))), s)


def t_backend(key: str, lang: str, **vars_) -> str:
    """
    Traduit une clé pour le backend (prompt LLM, log, message utilisateur).

    Fallback : lang active → EN → clé technique visible.
    Une cellule vide ne produit jamais une chaîne vide — la clé est retournée à la place.
    """
    lang = lang if lang in SUPPORTED else FALLBACK
    val = _resolve(lang, key)
    if val is None and lang != FALLBACK:
        val = _resolve(FALLBACK, key)
        if val is not None:
            logger.warning("[i18n_backend] Fallback EN pour clé '%s' (lang=%s)", key, lang)
    if val is None:
        logger.warning("[i18n_backend] Clé introuvable : '%s'", key)
        return key  # jamais de chaîne vide
    return _interpolate(val, vars_)


# ── Textes CHARGEN système par langue ─────────────────────────────────────────

# Prompts système complets par langue.
# Chaque prompt explique au LLM dans sa propre langue la structure JSON attendue.
# Le champ image_prompt reste TOUJOURS en anglais (requis par FLUX).
_CHARGEN_SYSTEM: dict[str, str] = {
    "fr": (
        "Tu es un assistant qui crée des fiches de personnage pour une application de compagnon IA adulte "
        "(jeu de rôle immersif). "
        "Respecte impérativement les attributs physiques imposés. "
        "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, sans balises Markdown, avec ces clés :\n"
        '"name", "age", "personality", "appearance", "scenario", "greeting", "system_prompt", "image_prompt",\n'
        '"role", "moral_limits", "memory_seeds".\n\n'
        '"role" : étiquette courte du type de relation (ex: amant, mentor, rival, serviteur, dominant, ami confidentiel).\n'
        '"personality" : traits de caractère, ton, façon de parler, tics de langage — en FRANÇAIS, riche et spécifique.\n'
        '"moral_limits" : 3 à 6 sujets/comportements qui dégoûtent ou agacent ce personnage, '
        "écrits en première personne en FRANÇAIS (ex: 'Je ne supporte pas qu'on crache en public.').\n"
        '"memory_seeds" : objet JSON : "likes" (2-4), "dislikes" (2-4), "important_events" (1-3), '
        '"user_preferences" ([]), "relationship_history" (1 phrase en FRANÇAIS).\n'
        '"appearance" : le physique en FRANÇAIS.\n'
        '"scenario" : contexte narratif en FRANÇAIS.\n'
        '"greeting" : premier message en FRANÇAIS, EN IMMERSION, à la première personne.\n'
        '"system_prompt" : ÉCRIT À LA DEUXIÈME PERSONNE ("Tu es..."), en FRANÇAIS, 4 à 8 phrases.\n'
        '"image_prompt" : description VISUELLE en ANGLAIS UNIQUEMENT, 1-2 phrases naturelles (pas de tags), '
        "pour FLUX.2 (ex: 'A young woman with long wavy auburn hair and green eyes, soft warm lighting').\n"
        "NE PAS mettre d'instruction méta dans system_prompt. Le personnage doit être vivant, comme une fiche de roman."
    ),
    "en": (
        "You are an assistant creating character sheets for an adult AI companion application "
        "(immersive roleplay). "
        "You must strictly respect any imposed physical attributes. "
        "Reply ONLY with a valid JSON object, no surrounding text, no Markdown, with these keys:\n"
        '"name", "age", "personality", "appearance", "scenario", "greeting", "system_prompt", "image_prompt",\n'
        '"role", "moral_limits", "memory_seeds".\n\n'
        '"role": short label for the relationship type (e.g.: lover, mentor, rival, servant, dominant, confidant).\n'
        '"personality": character traits, tone, way of speaking, verbal tics — in ENGLISH, rich and specific.\n'
        '"moral_limits": 3 to 6 topics/behaviors that disgust or annoy this character, '
        "written in first person in ENGLISH (e.g.: 'I can't stand people who chew loudly.').\n"
        '"memory_seeds": JSON object: "likes" (2-4), "dislikes" (2-4), "important_events" (1-3), '
        '"user_preferences" ([]), "relationship_history" (1 sentence in ENGLISH).\n'
        '"appearance": physical description in ENGLISH.\n'
        '"scenario": narrative context in ENGLISH.\n'
        '"greeting": first message in ENGLISH, IN CHARACTER, first person.\n'
        '"system_prompt": WRITTEN IN SECOND PERSON ("You are..."), in ENGLISH, 4 to 8 sentences.\n'
        '"image_prompt": VISUAL description in ENGLISH ONLY, 1-2 natural sentences (no tags), '
        "for FLUX.2 (e.g.: 'A young woman with long wavy auburn hair and green eyes, soft warm lighting').\n"
        "Do NOT put meta-instructions in system_prompt. The character must feel alive, like a novel character sheet."
    ),
    "es": (
        "Eres un asistente que crea fichas de personaje para una aplicación de compañero IA adulta "
        "(juego de rol inmersivo). "
        "Debes respetar estrictamente cualquier atributo físico impuesto. "
        "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional, sin Markdown, con estas claves:\n"
        '"name", "age", "personality", "appearance", "scenario", "greeting", "system_prompt", "image_prompt",\n'
        '"role", "moral_limits", "memory_seeds".\n\n'
        '"role": etiqueta corta del tipo de relación (ej: amante, mentor, rival, sirviente, dominante, confidente).\n'
        '"personality": rasgos de carácter, tono, forma de hablar — en ESPAÑOL, rico y específico.\n'
        '"moral_limits": 3 a 6 temas/comportamientos que disgustan o molestan a este personaje, '
        "escritos en primera persona en ESPAÑOL (ej: 'No soporto que la gente hable con la boca llena.').\n"
        '"memory_seeds": objeto JSON: "likes" (2-4), "dislikes" (2-4), "important_events" (1-3), '
        '"user_preferences" ([]), "relationship_history" (1 frase en ESPAÑOL).\n'
        '"appearance": descripción física en ESPAÑOL.\n'
        '"scenario": contexto narrativo en ESPAÑOL.\n'
        '"greeting": primer mensaje en ESPAÑOL, EN PERSONAJE, primera persona.\n'
        '"system_prompt": ESCRITO EN SEGUNDA PERSONA ("Eres..."), en ESPAÑOL, 4 a 8 frases.\n'
        '"image_prompt": descripción VISUAL en INGLÉS ÚNICAMENTE, 1-2 frases naturales (sin etiquetas), '
        "para FLUX.2 (ej: 'A young woman with long wavy auburn hair and green eyes, soft warm lighting').\n"
        "NO pongas meta-instrucciones en system_prompt. El personaje debe sentirse vivo."
    ),
    "de": (
        "Du bist ein Assistent, der Charakterbögen für eine Erwachsenen-KI-Begleit-App erstellt "
        "(immersives Rollenspiel). "
        "Du musst alle auferlegten physischen Attribute strikt einhalten. "
        "Antworte NUR mit einem gültigen JSON-Objekt, ohne umgebenden Text, ohne Markdown, mit diesen Schlüsseln:\n"
        '"name", "age", "personality", "appearance", "scenario", "greeting", "system_prompt", "image_prompt",\n'
        '"role", "moral_limits", "memory_seeds".\n\n'
        '"role": kurze Bezeichnung des Beziehungstyps (z.B.: Geliebter, Mentor, Rivale, Diener, Dominant, Vertrauter).\n'
        '"personality": Charakterzüge, Ton, Sprechweise, Sprachmuster — auf DEUTSCH, reich und spezifisch.\n'
        '"moral_limits": 3 bis 6 Themen/Verhaltensweisen, die diesen Charakter anwidern oder nerven, '
        "in der ersten Person auf DEUTSCH (z.B.: 'Ich kann es nicht ausstehen, wenn Leute schmatzen.').\n"
        '"memory_seeds": JSON-Objekt: "likes" (2-4), "dislikes" (2-4), "important_events" (1-3), '
        '"user_preferences" ([]), "relationship_history" (1 Satz auf DEUTSCH).\n'
        '"appearance": physische Beschreibung auf DEUTSCH.\n'
        '"scenario": narrativer Kontext auf DEUTSCH.\n'
        '"greeting": erste Nachricht auf DEUTSCH, IM CHARAKTER, erste Person.\n'
        '"system_prompt": IN DER ZWEITEN PERSON GESCHRIEBEN ("Du bist..."), auf DEUTSCH, 4 bis 8 Sätze.\n'
        '"image_prompt": VISUELLE Beschreibung NUR AUF ENGLISCH, 1-2 natürliche Sätze (keine Tags), '
        "für FLUX.2 (z.B.: 'A young woman with long wavy auburn hair and green eyes, soft warm lighting').\n"
        "KEINE Meta-Anweisungen in system_prompt. Der Charakter soll lebendig wirken."
    ),
}

# ── Templates de message utilisateur par langue ────────────────────────────────
# Variables : {brief}, {name_line}, {age_line}, {attrs_line}, {orientation_line}, {generate_line}

_USER_TEMPLATE: dict[str, dict[str, str]] = {
    "fr": {
        "description":   "Description : {brief}",
        "name":          "Nom imposé : {name}.",
        "age":           "Âge imposé : {age} ans.",
        "attributes":    "Attributs physiques imposés : {attrs}.",
        "orientation":   "Orientation : {orientation}.",
        "generate":      "Génère la fiche JSON.",
    },
    "en": {
        "description":   "Description: {brief}",
        "name":          "Imposed name: {name}.",
        "age":           "Imposed age: {age} years old.",
        "attributes":    "Imposed physical attributes: {attrs}.",
        "orientation":   "Orientation: {orientation}.",
        "generate":      "Generate the JSON character sheet.",
    },
    "es": {
        "description":   "Descripción: {brief}",
        "name":          "Nombre impuesto: {name}.",
        "age":           "Edad impuesta: {age} años.",
        "attributes":    "Atributos físicos impuestos: {attrs}.",
        "orientation":   "Orientación: {orientation}.",
        "generate":      "Genera la ficha JSON.",
    },
    "de": {
        "description":   "Beschreibung: {brief}",
        "name":          "Vorgegebener Name: {name}.",
        "age":           "Vorgegebenes Alter: {age} Jahre.",
        "attributes":    "Vorgegebene physische Attribute: {attrs}.",
        "orientation":   "Orientierung: {orientation}.",
        "generate":      "Erstelle den JSON-Charakterbogen.",
    },
}

# ── Configurateur physique : description LLM par langue + tag image EN ─────────
# Structure : { "categorie": { "valeur": { "fr": "...", "en": "...", "es": "...", "de": "...", "image_tag": "..." } } }

CONFIG_MAP: dict[str, dict[str, dict]] = {
    "genre": {
        "female":      {"fr": "une femme",                    "en": "a woman",             "es": "una mujer",            "de": "eine Frau",              "image_tag": "a woman"},
        "male":        {"fr": "un homme",                     "en": "a man",               "es": "un hombre",            "de": "ein Mann",               "image_tag": "a man"},
        "nonbinary":   {"fr": "une personne non-binaire",     "en": "a non-binary person", "es": "una persona no binaria","de": "eine nicht-binäre Person","image_tag": "a non-binary person"},
        "transfemale": {"fr": "une femme trans",              "en": "a trans woman",       "es": "una mujer trans",      "de": "eine trans Frau",        "image_tag": "a trans woman"},
        "transmale":   {"fr": "un homme trans",               "en": "a trans man",         "es": "un hombre trans",      "de": "ein trans Mann",         "image_tag": "a trans man"},
        "genderfluid": {"fr": "une personne de genre fluide", "en": "a genderfluid person","es": "una persona genderfluid","de": "eine genderfluide Person","image_tag": "a genderfluid person"},
        "agender":     {"fr": "une personne agenre",          "en": "an agender person",   "es": "una persona agénero",  "de": "eine agender Person",    "image_tag": "an agender person"},
        "androgynous": {"fr": "une personne androgyne",       "en": "an androgynous person","es": "una persona andrógina","de": "eine androgyne Person",  "image_tag": "an androgynous person"},
        "intersex":    {"fr": "une personne intersexe",       "en": "an intersex person",  "es": "una persona intersexual","de": "eine intersexuelle Person","image_tag": "an intersex person"},
    },
    "origine": {
        "european":     {"fr": "d'origine européenne",             "en": "of European origin",         "es": "de origen europeo",         "de": "europäischer Herkunft",       "image_tag": "European"},
        "african":      {"fr": "d'origine africaine",              "en": "of African origin",          "es": "de origen africano",        "de": "afrikanischer Herkunft",      "image_tag": "African"},
        "asian":        {"fr": "d'origine asiatique",              "en": "of East Asian origin",       "es": "de origen asiático",        "de": "ostasiatischer Herkunft",     "image_tag": "East Asian"},
        "latina":       {"fr": "d'origine latino-américaine",      "en": "of Latin American origin",   "es": "de origen latinoamericano", "de": "lateinamerikanischer Herkunft","image_tag": "Latin American"},
        "middleeastern":{"fr": "d'origine moyen-orientale",        "en": "of Middle Eastern origin",   "es": "de origen árabe",           "de": "nahöstlicher Herkunft",       "image_tag": "Middle Eastern"},
        "indian":       {"fr": "d'origine indienne / sud-asiatique","en": "of South Asian origin",     "es": "de origen indio",           "de": "südasiatischer Herkunft",     "image_tag": "South Asian"},
        "mixed":        {"fr": "métisse",                          "en": "of mixed ethnicity",         "es": "mestizo/a",                 "de": "gemischter Herkunft",         "image_tag": "mixed ethnicity"},
        "islander":     {"fr": "d'origine insulaire du Pacifique", "en": "Pacific Islander",           "es": "de las islas del Pacífico", "de": "Pazifikinsulaner",            "image_tag": "Pacific Islander"},
        "native":       {"fr": "autochtone d'Amérique",            "en": "Native American",            "es": "indígena americano/a",      "de": "indigene Amerikanerin",       "image_tag": "Native American"},
        "slavic":       {"fr": "d'origine slave",                  "en": "of Slavic origin",           "es": "de origen eslavo",          "de": "slawischer Herkunft",         "image_tag": "Slavic"},
        "nordic":       {"fr": "d'origine nordique",               "en": "of Nordic origin",           "es": "de origen nórdico",         "de": "nordischer Herkunft",         "image_tag": "Nordic"},
        "mediterranean":{"fr": "d'origine méditerranéenne",        "en": "of Mediterranean origin",    "es": "de origen mediterráneo",    "de": "mediterraner Herkunft",       "image_tag": "Mediterranean"},
    },
    "corps": {
        "slim":     {"fr": "une silhouette svelte",    "en": "a slim figure",         "es": "una figura esbelta",   "de": "eine schlanke Figur",      "image_tag": "slim figure"},
        "lean":     {"fr": "un corps élancé",          "en": "a lean figure",         "es": "una figura atlética",  "de": "eine schlanke Figur",      "image_tag": "lean figure"},
        "average":  {"fr": "une corpulence moyenne",   "en": "an average build",      "es": "complexión media",     "de": "durchschnittliche Figur",  "image_tag": "average build"},
        "soft":     {"fr": "une silhouette douce",     "en": "a soft body",           "es": "figura suave",         "de": "weiche Figur",             "image_tag": "soft body"},
        "curvy":    {"fr": "des formes pulpeuses",     "en": "a curvy figure",        "es": "figura curvilínea",    "de": "kurvige Figur",            "image_tag": "curvy figure"},
        "athletic": {"fr": "un corps athlétique",      "en": "an athletic toned body","es": "cuerpo atlético",      "de": "athletischer Körper",      "image_tag": "athletic toned body"},
        "muscular": {"fr": "un corps musclé",          "en": "a muscular body",       "es": "cuerpo musculoso",     "de": "muskulöser Körper",        "image_tag": "muscular body"},
        "petite":   {"fr": "une silhouette menue",     "en": "a petite frame",        "es": "figura menuda",        "de": "zierliche Figur",          "image_tag": "petite frame"},
        "tall":     {"fr": "une grande taille",        "en": "tall stature",          "es": "estatura alta",        "de": "große Statur",             "image_tag": "tall stature"},
        "stocky":   {"fr": "un corps trapu",           "en": "a stocky build",        "es": "complexión robusta",   "de": "gedrungene Figur",         "image_tag": "stocky build"},
        "plus":     {"fr": "une forte corpulence",     "en": "a plus-size figure",    "es": "talla grande",         "de": "üppige Figur",             "image_tag": "plus-size figure"},
    },
    "poitrine": {
        "flat":    {"fr": "un torse plat",          "en": "a flat chest",     "es": "pecho plano",       "de": "flache Brust",     "image_tag": "flat chest"},
        "small":   {"fr": "une petite poitrine",    "en": "a small chest",    "es": "pecho pequeño",     "de": "kleine Brust",     "image_tag": "small chest"},
        "medium":  {"fr": "une poitrine moyenne",   "en": "a medium chest",   "es": "pecho mediano",     "de": "mittlere Brust",   "image_tag": "medium chest"},
        "large":   {"fr": "une poitrine généreuse", "en": "a large chest",    "es": "pecho generoso",    "de": "große Brust",      "image_tag": "large chest"},
        "full":    {"fr": "une poitrine pleine",    "en": "a full chest",     "es": "pecho lleno",       "de": "volle Brust",      "image_tag": "full chest"},
        "broad":   {"fr": "un torse large",         "en": "a broad chest",    "es": "tórax ancho",       "de": "breite Brust",     "image_tag": "broad chest"},
        "defined": {"fr": "un torse dessiné",       "en": "a defined chest",  "es": "pecho definido",    "de": "definierte Brust", "image_tag": "defined chest"},
    },
    "hanches": {
        "flat":   {"fr": "des hanches plates",       "en": "flat hips",    "es": "caderas planas",    "de": "flache Hüften",       "image_tag": "flat hips"},
        "small":  {"fr": "de petites fesses",        "en": "small hips",   "es": "caderas pequeñas",  "de": "schmale Hüften",      "image_tag": "small hips"},
        "medium": {"fr": "des fesses moyennes",      "en": "medium hips",  "es": "caderas medianas",  "de": "mittlere Hüften",     "image_tag": "medium hips"},
        "round":  {"fr": "des fesses rondes",        "en": "round hips",   "es": "caderas redondeadas","de": "runde Hüften",        "image_tag": "round hips"},
        "large":  {"fr": "des fesses généreuses",    "en": "large hips",   "es": "caderas grandes",   "de": "große Hüften",        "image_tag": "large hips"},
        "wide":   {"fr": "des hanches larges",       "en": "wide hips",    "es": "caderas anchas",    "de": "breite Hüften",       "image_tag": "wide hips"},
        "curvy":  {"fr": "des hanches galbées",      "en": "curvy hips",   "es": "caderas curvilíneas","de": "kurvige Hüften",      "image_tag": "curvy hips"},
    },
    "cheveux_couleur": {
        "black":      {"fr": "cheveux noirs",       "en": "black hair",        "es": "cabello negro",      "de": "schwarzes Haar",      "image_tag": "black hair"},
        "brown":      {"fr": "cheveux châtains",    "en": "brown hair",        "es": "cabello castaño",    "de": "braunes Haar",        "image_tag": "brown hair"},
        "blonde":     {"fr": "cheveux blonds",      "en": "blonde hair",       "es": "cabello rubio",      "de": "blondes Haar",        "image_tag": "blonde hair"},
        "red":        {"fr": "cheveux roux",        "en": "red hair",          "es": "cabello pelirrojo",  "de": "rotes Haar",          "image_tag": "red hair"},
        "auburn":     {"fr": "cheveux auburn",      "en": "auburn hair",       "es": "cabello caoba",      "de": "auburn Haar",         "image_tag": "auburn hair"},
        "gray":       {"fr": "cheveux gris",        "en": "gray hair",         "es": "cabello gris",       "de": "graues Haar",         "image_tag": "gray hair"},
        "white":      {"fr": "cheveux blancs",      "en": "white hair",        "es": "cabello blanco",     "de": "weißes Haar",         "image_tag": "white hair"},
        "silver":     {"fr": "cheveux argentés",    "en": "silver hair",       "es": "cabello plateado",   "de": "silbernes Haar",      "image_tag": "silver hair"},
        "blue":       {"fr": "cheveux bleus",       "en": "blue hair",         "es": "cabello azul",       "de": "blaues Haar",         "image_tag": "blue hair"},
        "pink":       {"fr": "cheveux roses",       "en": "pink hair",         "es": "cabello rosa",       "de": "rosa Haar",           "image_tag": "pink hair"},
        "purple":     {"fr": "cheveux violets",     "en": "purple hair",       "es": "cabello morado",     "de": "violettes Haar",      "image_tag": "purple hair"},
        "green":      {"fr": "cheveux verts",       "en": "green hair",        "es": "cabello verde",      "de": "grünes Haar",         "image_tag": "green hair"},
        "multicolor": {"fr": "cheveux multicolores","en": "multicolored hair", "es": "cabello multicolor", "de": "mehrfarbiges Haar",   "image_tag": "multicolored hair"},
    },
    "coiffure": {
        "bald":      {"fr": "le crâne rasé",           "en": "bald",              "es": "rapado",             "de": "glatzköpfig",          "image_tag": "bald"},
        "buzzcut":   {"fr": "une coupe très courte",   "en": "buzzcut",           "es": "corte al rape",      "de": "Bürstenschnitt",       "image_tag": "buzzcut"},
        "pixie":     {"fr": "une coupe pixie",         "en": "pixie cut",         "es": "corte pixie",        "de": "Pixie-Schnitt",        "image_tag": "pixie cut"},
        "bob":       {"fr": "un carré",               "en": "bob cut",            "es": "corte bob",          "de": "Bob-Schnitt",          "image_tag": "bob cut"},
        "lob":       {"fr": "un carré long",           "en": "long bob",          "es": "lob largo",          "de": "langer Bob",           "image_tag": "long bob"},
        "shag":      {"fr": "une coupe shag",          "en": "shag haircut",      "es": "corte shag",         "de": "Shag-Schnitt",         "image_tag": "shag haircut"},
        "mullet":    {"fr": "une nuque longue",        "en": "mullet",            "es": "mullet",             "de": "Vokuhila",             "image_tag": "mullet"},
        "undercut":  {"fr": "un undercut",             "en": "undercut",          "es": "undercut",           "de": "Undercut",             "image_tag": "undercut"},
        "mohawk":    {"fr": "une crête iroquoise",     "en": "mohawk",            "es": "mohicano",           "de": "Irokesenschnitt",      "image_tag": "mohawk"},
        "afro":      {"fr": "une coupe afro",          "en": "afro",              "es": "afro",               "de": "Afro",                 "image_tag": "afro"},
        "braids":    {"fr": "des tresses",             "en": "braids",            "es": "trenzas",            "de": "Zöpfe",                "image_tag": "braids"},
        "cornrows":  {"fr": "des cornrows",            "en": "cornrows",          "es": "trenzas africanas",  "de": "Cornrows",             "image_tag": "cornrows"},
        "dreadlocks":{"fr": "des dreadlocks",          "en": "dreadlocks",        "es": "rastas",             "de": "Dreadlocks",           "image_tag": "dreadlocks"},
        "ponytail":  {"fr": "une queue de cheval",     "en": "ponytail",          "es": "cola de caballo",    "de": "Pferdeschwanz",        "image_tag": "ponytail"},
        "bun":       {"fr": "un chignon",              "en": "hair in a bun",     "es": "moño",               "de": "Haarknoten",           "image_tag": "hair in a bun"},
        "pigtails":  {"fr": "des couettes",            "en": "pigtails",          "es": "coletas",            "de": "Zöpfe",                "image_tag": "pigtails"},
        "curly":     {"fr": "des cheveux bouclés",     "en": "curly hair",        "es": "cabello rizado",     "de": "lockiges Haar",        "image_tag": "curly hair"},
        "wavy":      {"fr": "des cheveux ondulés",     "en": "wavy hair",         "es": "cabello ondulado",   "de": "welliges Haar",        "image_tag": "wavy hair"},
        "straight":  {"fr": "des cheveux raides",      "en": "straight hair",     "es": "cabello liso",       "de": "glattes Haar",         "image_tag": "straight hair"},
        "long":      {"fr": "des cheveux longs",       "en": "long hair",         "es": "cabello largo",      "de": "langes Haar",          "image_tag": "long hair"},
        "short":     {"fr": "des cheveux courts",      "en": "short hair",        "es": "cabello corto",      "de": "kurzes Haar",          "image_tag": "short hair"},
        "medium":    {"fr": "des cheveux mi-longs",    "en": "medium-length hair","es": "cabello a media melena","de": "mittellanges Haar",  "image_tag": "medium-length hair"},
        "layered":   {"fr": "des cheveux dégradés",    "en": "layered hair",      "es": "cabello en capas",   "de": "gestufte Haare",       "image_tag": "layered hair"},
        "bangs":     {"fr": "une frange",              "en": "with bangs",        "es": "con flequillo",      "de": "mit Pony",             "image_tag": "with bangs"},
    },
}

# Orientation : contexte RP uniquement (jamais dans l'image)
ORIENTATION_MAP: dict[str, dict[str, str]] = {
    "straight":  {"fr": "hétérosexuel(le)",   "en": "heterosexual",   "es": "heterosexual",   "de": "heterosexuell"},
    "gay":       {"fr": "gay",                "en": "gay",            "es": "gay",            "de": "schwul/lesbisch"},
    "lesbian":   {"fr": "lesbienne",          "en": "lesbian",        "es": "lesbiana",       "de": "lesbisch"},
    "bisexual":  {"fr": "bisexuel(le)",       "en": "bisexual",       "es": "bisexual",       "de": "bisexuell"},
    "pansexual": {"fr": "pansexuel(le)",      "en": "pansexual",      "es": "pansexual",      "de": "pansexuell"},
    "asexual":   {"fr": "asexuel(le)",        "en": "asexual",        "es": "asexual",        "de": "asexuell"},
    "queer":     {"fr": "queer",              "en": "queer",          "es": "queer",          "de": "queer"},
}

CONFIG_ORDER = ("genre", "origine", "corps", "poitrine", "hanches", "cheveux_couleur", "coiffure")


def config_to_text_and_tags(attrs: dict, lang: str) -> tuple[str, str]:
    """
    Convertit les attributs physiques en :
      - description texte dans la langue active (pour le prompt LLM)
      - tags image en anglais (pour FLUX — toujours EN)
    """
    lang = lang if lang in SUPPORTED else FALLBACK
    attrs = attrs or {}
    descs, tags = [], []
    bald = attrs.get("coiffure") == "bald"
    for key in CONFIG_ORDER:
        if key == "cheveux_couleur" and bald:
            continue
        val = (attrs.get(key, "") or "").strip()
        if not val:
            continue
        entry = CONFIG_MAP.get(key, {}).get(val)
        if entry:
            descs.append(entry.get(lang) or entry.get(FALLBACK) or val)
            tags.append(entry["image_tag"])
        else:
            # Valeur custom : utilisée telle quelle dans les deux
            descs.append(val)
            tags.append(val)
    return ", ".join(descs), ", ".join(tags)


def orientation_text(val: str, lang: str) -> str:
    """Retourne la description de l'orientation dans la langue donnée."""
    lang = lang if lang in SUPPORTED else FALLBACK
    entry = ORIENTATION_MAP.get(val, {})
    return entry.get(lang) or entry.get(FALLBACK) or val


def build_chargen_messages(brief: str, lang: str, attrs: dict,
                            system_override: str = "") -> list[dict]:
    """
    Construit la liste de messages (system + user) pour la génération de personnage,
    entièrement dans la langue demandée.

    system_override : si non vide, remplace le system prompt par défaut.
    """
    lang = lang if lang in SUPPORTED else FALLBACK

    # System prompt
    if system_override:
        system = system_override
        logger.info("[i18n_backend] Override system utilisé pour chargen (lang=%s)", lang)
    else:
        system = _CHARGEN_SYSTEM.get(lang) or _CHARGEN_SYSTEM[FALLBACK]

    # Description physique + tags image
    attrs_text, _tags = config_to_text_and_tags(attrs, lang)

    # Orientation
    orient_val = attrs.get("orientation", "")
    orient_text = orientation_text(orient_val, lang) if orient_val else ""

    # Message utilisateur
    tpl = _USER_TEMPLATE.get(lang) or _USER_TEMPLATE[FALLBACK]
    name  = (attrs.get("name") or "").strip()
    age   = str(attrs.get("age") or "").strip()

    lines = [tpl["description"].format(brief=brief)]
    if name:
        lines.append(tpl["name"].format(name=name))
    if age:
        lines.append(tpl["age"].format(age=age))
    if attrs_text:
        lines.append(tpl["attributes"].format(attrs=attrs_text))
    if orient_text:
        lines.append(tpl["orientation"].format(orientation=orient_text))
    lines.append(tpl["generate"])

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": "\n".join(lines)},
    ]
