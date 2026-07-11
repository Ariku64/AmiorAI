# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
model_catalog.py — catalogue local des modèles (image + vidéo), détection et cache.

Principe : AUCUN scan automatique au démarrage. L'utilisateur déclare des dossiers dans
Réglages → Bibliothèque de modèles, puis lance un scan manuel (bouton Rafraîchir). Le résultat
est mis en cache en base (table model_files) pour ne pas rescanner à chaque ouverture de page.

Détection de famille :
  1. override manuel utilisateur  (manual_kind / manual_family dans model_files)
  2. métadonnées Civitai confirmées
  3. dossier parent ComfyUI (models/<type>/ — très fiable)
  4. sous-dossiers du chemin relatif
  5. nom de fichier
  6. heuristique extension
  7. inconnu

Ce module ne dépend que de la bibliothèque standard (os, re, time) — pas de torch,
pas de safetensors, pour rester léger et rapide même avec des dossiers volumineux.
"""
import os
import re
import time

import model_manifests as mm

# --------------------------------------------------------------------------- #
#  Heuristiques de détection de famille / type, par nom de fichier
# --------------------------------------------------------------------------- #
_FAMILY_HINTS = [
    # (case-insensitive regex on filename, family)
    (r"krea[\s_.-]*2|\bkrea\b", "krea2"),
    (r"\bsdxl\b|sd_xl|sd-xl", "sdxl"),
    (r"\bsd15\b|sd_1[._-]?5|\bsd1\.5\b|v1-5|v1_5", "sd15"),
    (r"flux\s*\.?\s*2|flux2|klein", "flux2_klein"),
    (r"\bflux\b|flux1|flux\.1|flux-dev|flux-schnell", "flux"),
    (r"z[_-]?image|zimage", "zimage"),
    (r"\bpony\b|ponyxl|pony[_-]xl", "pony"),
    (r"\billustri", "illustrious"),
    (r"\bwan\b|wan2|wan_2|wan-2", "wan_video"),
    (r"\bltx\b|ltx-video|ltxv", "ltx_video"),
]

# Dossiers/sous-dossiers → famille (priorité sur le nom de fichier seul)
_FOLDER_FAMILY_HINTS = [
    # (regex on relative path or subfolder name, family)
    (r"krea[\s_.-]*2|\bkrea\b", "krea2"),
    (r"flux2|klein",           "flux2_klein"),
    (r"\bflux1?\b|flux-dev|flux-schnell", "flux"),
    (r"\bsdxl\b|sd[_-]?xl",   "sdxl"),
    (r"\bsd15\b|sd[_-]?1\.?5", "sd15"),
    (r"z[_-]?image|zimage",    "zimage"),
    (r"\bpony\b|ponyxl",       "pony"),
    (r"illustri",              "illustrious"),
    (r"\bwan\b",               "wan_video"),
    (r"\bltx\b|ltxv",         "ltx_video"),
]

_KIND_HINTS = [
    # (regex, kind) - ordre important : motifs les plus specifiques d'abord
    (r"vae", "vae"),
    (r"controlnet|control[_-]?net|\bcn[_-]", "controlnet"),
    (r"lora|lycoris", "lora"),
    (r"clip|t5xxl|t5_xxl|text[_-]?encoder|qwen.*\d+b", "clip"),
    (r"unet|diffusion[_-]?model|\bdit\b", "unet"),
    (r"checkpoint|\bckpt\b", "checkpoint"),
]

# Dossiers ComfyUI conventionnels : nom de dossier -> type de composant.
_FOLDER_NAME_HINTS = {
    "checkpoints": "checkpoint", "checkpoint": "checkpoint",
    "unet": "unet", "diffusion_models": "unet",
    "vae": "vae",
    "clip": "clip", "text_encoders": "clip",
    "loras": "lora", "lora": "lora",
    "controlnet": "controlnet",
    "video_models": "video_model",
}


def _guess_family_from_path(full_path, base_folder_path):
    """Déduit la famille depuis le chemin relatif (sous-dossiers).
    Retourne None si aucun indice trouvé."""
    try:
        rel = os.path.relpath(full_path, base_folder_path)
    except ValueError:
        rel = full_path
    # On regarde uniquement les dossiers intermédiaires (pas le nom du fichier)
    rel_dir = os.path.dirname(rel).lower()
    if not rel_dir or rel_dir == ".":
        return None
    for pattern, family in _FOLDER_FAMILY_HINTS:
        if re.search(pattern, rel_dir):
            return family
    return None


def _guess_family(filename, full_path=None, base_folder_path=None):
    """Détecte la famille :
      1. chemin relatif (sous-dossiers)
      2. nom de fichier
    """
    # Priorité : sous-dossiers
    if full_path and base_folder_path:
        path_family = _guess_family_from_path(full_path, base_folder_path)
        if path_family:
            return path_family
    # Fallback : nom de fichier
    low = filename.lower()
    for pattern, family in _FAMILY_HINTS:
        if re.search(pattern, low):
            return family
    return None


def _guess_kind(filename, declared_kind=None, parent_dir=None):
    """declared_kind : si le dossier est explicitement marqué comme contenant un type
    précis (ex : un dossier 'loras/'), on le prend en priorité sur tout le reste.
    Sinon on regarde le nom du dossier parent (convention ComfyUI models/<type>/),
    puis le nom du fichier, puis en dernier recours."""
    if declared_kind and declared_kind in mm.COMPONENT_KINDS:
        return declared_kind
    if parent_dir:
        folder_kind = _FOLDER_NAME_HINTS.get(os.path.basename(parent_dir.rstrip(os.sep)).lower())
        if folder_kind:
            return folder_kind
    low = filename.lower()
    for pattern, kind in _KIND_HINTS:
        if re.search(pattern, low):
            return kind
    # Repli : un .safetensors/.ckpt dont la famille (sd15/sdxl/flux) est reconnue, mais
    # sans aucun autre indice de type, est très probablement un checkpoint complet.
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".safetensors", ".ckpt") and _guess_family(filename):
        return "checkpoint"
    return None


def _ext_of(filename):
    return os.path.splitext(filename)[1].lower()


def scan_folder(folder_path, declared_kind=None, max_depth=4):
    """Scan un dossier (récursif, profondeur bornée) et renvoie une liste de dicts décrivant
    chaque fichier modèle trouvé. Ne lit jamais le contenu des fichiers, seulement les métadonnées
    du système de fichiers (stat). Tolérant aux erreurs."""
    results = []
    if not folder_path or not os.path.isdir(folder_path):
        return results, f"Folder not found: {folder_path}"

    all_exts = set()
    for exts in mm.EXTENSIONS_BY_KIND.values():
        all_exts.update(exts)

    base_depth = folder_path.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(folder_path, onerror=lambda e: None):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        for fname in files:
            ext = _ext_of(fname)
            if ext not in all_exts:
                continue
            full = os.path.join(root, fname)
            try:
                st = os.stat(full)
            except OSError:
                continue
            kind = _guess_kind(fname, declared_kind, parent_dir=root)
            family = _guess_family(fname, full_path=full, base_folder_path=folder_path)
            results.append({
                "name": fname,
                "path": full,
                "ext": ext,
                "kind": kind,
                "family": family,
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    return results, None


def format_size(n_bytes):
    if n_bytes is None:
        return "?"
    units = ["o", "Ko", "Mo", "Go", "To"]
    size = float(n_bytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f} {u}" if u != "o" else f"{int(size)} {u}"
        size /= 1024
    return f"{n_bytes} o"


# --------------------------------------------------------------------------- #
#  Persistance (table model_folders + model_files)
# --------------------------------------------------------------------------- #
def ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS model_folders (
            id          TEXT PRIMARY KEY,
            path        TEXT NOT NULL,
            kind_hint   TEXT,
            enabled     INTEGER DEFAULT 1,
            created_at  REAL,
            last_scan   REAL,
            last_count  INTEGER DEFAULT 0,
            last_error  TEXT
        );
        CREATE TABLE IF NOT EXISTS model_files (
            id                  TEXT PRIMARY KEY,
            folder_id           TEXT NOT NULL,
            name                TEXT,
            path                TEXT,
            ext                 TEXT,
            kind                TEXT,   -- valeur effective (auto ou manuel)
            family              TEXT,   -- valeur effective (auto ou manuel)
            detected_kind       TEXT,   -- résultat du dernier scan automatique
            detected_family     TEXT,   -- résultat du dernier scan automatique
            manual_kind         TEXT,   -- override manuel utilisateur
            manual_family       TEXT,   -- override manuel utilisateur
            identification_source TEXT DEFAULT 'auto', -- 'auto' | 'civitai' | 'manual'
            size                INTEGER,
            mtime               REAL,
            scanned_at          REAL,
            missing             INTEGER DEFAULT 0,
            updated_at          REAL,
            FOREIGN KEY (folder_id) REFERENCES model_folders(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_model_files_kind   ON model_files(kind);
        CREATE INDEX IF NOT EXISTS idx_model_files_family ON model_files(family);
        """
    )
    # Migrations non-destructives pour installations existantes
    for col, coltype in [
        ("detected_kind",          "TEXT"),
        ("detected_family",        "TEXT"),
        ("manual_kind",            "TEXT"),
        ("manual_family",          "TEXT"),
        ("identification_source",  "TEXT DEFAULT 'auto'"),
        ("updated_at",             "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE model_files ADD COLUMN {col} {coltype}")
        except Exception:
            pass  # colonne déjà présente


def _effective_kind(manual_kind, detected_kind):
    return manual_kind if manual_kind else detected_kind


def _effective_family(manual_family, detected_family):
    return manual_family if manual_family else detected_family


def rescan_folder(conn, new_id_fn, folder_row):
    """Relance le scan d'UN dossier et met à jour son cache.
    Les overrides manuels (manual_kind / manual_family) sont préservés :
    le rescan met à jour detected_kind/detected_family, mais ne touche pas
    aux valeurs manuelles déjà posées par l'utilisateur."""
    fid = folder_row["id"]
    files, error = scan_folder(folder_row["path"], folder_row["kind_hint"])

    conn.execute("UPDATE model_files SET missing=1 WHERE folder_id=?", (fid,))
    now = time.time()
    for f in files:
        existing = conn.execute(
            "SELECT id, manual_kind, manual_family FROM model_files WHERE folder_id=? AND path=?",
            (fid, f["path"])
        ).fetchone()

        det_kind   = f["kind"]
        det_family = f["family"]

        if existing:
            mk = existing["manual_kind"]   if existing["manual_kind"]   else None
            mf = existing["manual_family"] if existing["manual_family"] else None
            src = "manual" if (mk or mf) else "auto"
            eff_kind   = mk if mk else det_kind
            eff_family = mf if mf else det_family
            conn.execute(
                "UPDATE model_files SET name=?, ext=?, "
                "detected_kind=?, detected_family=?, "
                "kind=?, family=?, "
                "identification_source=?, "
                "size=?, mtime=?, scanned_at=?, missing=0, updated_at=? "
                "WHERE id=?",
                (f["name"], f["ext"],
                 det_kind, det_family,
                 eff_kind, eff_family,
                 src,
                 f["size"], f["mtime"], now, now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO model_files("
                "  id, folder_id, name, path, ext, "
                "  kind, family, detected_kind, detected_family, "
                "  manual_kind, manual_family, identification_source, "
                "  size, mtime, scanned_at, missing, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
                (new_id_fn(), fid, f["name"], f["path"], f["ext"],
                 det_kind, det_family, det_kind, det_family,
                 None, None, "auto",
                 f["size"], f["mtime"], now, now),
            )
    conn.execute(
        "UPDATE model_folders SET last_scan=?, last_count=?, last_error=? WHERE id=?",
        (now, len(files), error, fid),
    )
    return {"count": len(files), "error": error}
