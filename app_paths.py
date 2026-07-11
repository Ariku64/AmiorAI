# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
app_paths.py — Source unique de vérité pour tous les chemins AmiorAI.

Importé par app.py ET engine.py.
Ne jamais redéfinir CODE_ROOT / DATA_ROOT dans les autres modules.

Ordre de résolution de DATA_ROOT (mode développement) :
  1. Env var AMIORAI_DATA_DIR (explicite, prioritaire)
  2. %LOCALAPPDATA%\\AmiorAI\\data  (Windows — persiste entre versions)
  3. <dossier projet>/data           (fallback Linux / CI / dev)
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

IS_FROZEN = getattr(sys, "frozen", False)


def _frozen_app_dir():
    """Dossier contenant le .exe (pas le dossier temporaire d'extraction PyInstaller)."""
    return os.path.dirname(os.path.abspath(sys.executable))


# ── CODE_ROOT ─────────────────────────────────────────────────────────────────
# Ressources statiques (web/, workflows/, resources/). En mode .exe : à côté du
# binaire (mode onedir). En dev : dossier du fichier Python.
if IS_FROZEN:
    CODE_ROOT = getattr(sys, "_MEIPASS", _frozen_app_dir())
else:
    CODE_ROOT = os.path.dirname(os.path.abspath(__file__))

# ── DATA_ROOT ─────────────────────────────────────────────────────────────────
# Données utilisateur (DB, images, voix, logs, réglages).
# Persiste entre les mises à jour et survit aux réinstallations.
if IS_FROZEN:
    DATA_ROOT = os.path.join(_frozen_app_dir(), "data")
else:
    _env = os.environ.get("AMIORAI_DATA_DIR", "").strip()
    if _env:
        DATA_ROOT = _env
        logger.debug("[paths] DATA_ROOT depuis AMIORAI_DATA_DIR : %s", DATA_ROOT)
    else:
        _localapp = os.environ.get("LOCALAPPDATA", "")
        if _localapp:
            DATA_ROOT = os.path.join(_localapp, "AmiorAI", "data")
            logger.debug("[paths] DATA_ROOT depuis LOCALAPPDATA : %s", DATA_ROOT)
        else:
            DATA_ROOT = os.path.join(CODE_ROOT, "data")
            logger.debug("[paths] DATA_ROOT fallback dev : %s", DATA_ROOT)

# ── Chemins dérivés ────────────────────────────────────────────────────────────
WEB_DIR    = os.path.join(CODE_ROOT, "web")
WF_DIR     = os.path.join(CODE_ROOT, "workflows")
I18N_DIR   = os.path.join(CODE_ROOT, "resources", "i18n")

DATA_DIR   = DATA_ROOT          # alias lisible
IMG_DIR    = os.path.join(DATA_ROOT, "images")
LOG_DIR    = os.path.join(DATA_ROOT, "logs")
BACKUP_DIR = os.path.join(DATA_ROOT, "backups")
DB_PATH    = os.path.join(DATA_ROOT, "companion.db")

# Dossier legacy : chemin que engine.py utilisait avant la correction.
# Utilisé uniquement pour la compatibilité de lecture des anciennes images.
_LEGACY_DATA = os.path.join(CODE_ROOT, "data")
LEGACY_IMG_DIR = os.path.join(_LEGACY_DATA, "images")

# ── Création des dossiers obligatoires ────────────────────────────────────────
for _d in (
    IMG_DIR,
    LOG_DIR,
    BACKUP_DIR,
    os.path.join(DATA_ROOT, "audio"),
    os.path.join(DATA_ROOT, "voices"),
):
    os.makedirs(_d, exist_ok=True)


def resolve_img(name: str) -> tuple[str, bool]:
    """
    Retourne (chemin_absolu, is_legacy).
    Cherche d'abord dans IMG_DIR, puis dans LEGACY_IMG_DIR si absent.
    Retourne (chemin_officiel, False) même si le fichier n'existe pas —
    l'appelant décide quoi faire.
    """
    basename = os.path.basename(name)
    official = os.path.join(IMG_DIR, basename)
    if os.path.isfile(official):
        return official, False
    legacy = os.path.join(LEGACY_IMG_DIR, basename)
    if LEGACY_IMG_DIR != IMG_DIR and os.path.isfile(legacy):
        logger.warning(
            "[paths] Image legacy utilisée (ancienne location) : %s → %s",
            basename, legacy
        )
        return legacy, True
    return official, False  # non trouvé : retourne le chemin officiel pour un 404 propre
