# AmiorAI — Journal des modifications


## v40.1.0 — 13 juillet 2026

### Fournisseurs distants facultatifs et Pods Runpod

- Base de travail : source v40.0.9, sans régression volontaire des créateurs Réaliste, Anime et Cartoon.
- Choix indépendant du moteur de conversation et du moteur d’image.
- Ajout de LM Studio local, API compatible OpenAI, Runpod Serverless vLLM et Runpod Pod vLLM.
- Ajout de ComfyUI local, ComfyUI distant, Runpod Serverless ComfyUI et Runpod Pod ComfyUI.
- TTS conservé exclusivement en local.
- Démarrage automatique des Pods personnels au premier appel.
- Arrêt automatique après 15 minutes d’inactivité par défaut, avec minuteurs LLM et image indépendants.
- Commandes Start/Stop manuelles et état du Pod dans les réglages.
- Tentative d’arrêt des Pods configurés lors d’une fermeture normale d’AmiorAI.
- Clés Runpod et services distants stockées hors de SQLite dans le gestionnaire de secrets du système lorsqu’il est disponible.
- Routes de gestion cloud réservées au PC hôte, y compris lorsque le mode LAN est actif.
- Générations distantes sans déchargement inutile des moteurs locaux.
- Quatre kits de déploiement de référence dans `runpod_templates`.
- Documentation FR/EN, notice légale et traductions FR/EN/ES/DE mises à jour.


## v40.0.9 — 12 juillet 2026

### Créateurs visuels Réaliste, Anime et Cartoon

- Trois sections de création clairement distinctes dans l’interface : Réaliste, Anime et Cartoon.
- Chaque section conserve son propre brouillon, ses sélections physiques et sa bibliothèque d’aperçus.
- Les aperçus sont désormais isolés par moteur d’image et par style visuel afin d’éviter tout mélange.
- Les styles Anime et Cartoon ajoutent automatiquement leur préfixe au début des prompts d’avatar, d’émotions, de conversation, de groupe et de fond.
- Le mode Réaliste conserve strictement le comportement actuel, sans préfixe ajouté.
- Le style est enregistré dans la fiche, affiché sur la carte et conservé dans les paquets `.amiorchar`.
- Migration non destructive : personnages et aperçus existants deviennent Réalistes par défaut.
- Traductions FR/EN/ES/DE et fichier maître `translations_master.xlsx` synchronisés.

## v40.0.8 — 12 juillet 2026

### Personnages et scénarios partageables

- Nouveau format `.amiorchar` pour partager une fiche de personnage avec son avatar et ses visages d’humeur déjà générés.
- Nouveau format `.amiorscenario` pour exporter et importer un scénario narratif.
- Les paquets publics excluent volontairement conversations, mémoire personnelle, galerie, statistiques d’humeur, voix, réglages et identifiants locaux.
- Import compatible avec les anciens exports JSON de personnages et avec les scénarios JSON simples.
- Validation de sécurité des archives : taille limitée, chemins protégés contre le traversal, types d’images contrôlés et fichiers chiffrés refusés.
- Traductions FR/EN/ES/DE et fichier maître `translations_master.xlsx` mis à jour.

## v40.0.7 — 12 juillet 2026

### ComfyUI tiers uniquement

- Suppression complète du lanceur ComfyUI intégré à AmiorAI.
- Suppression des réglages de dossier, Python, arguments, délai et lancement automatique ComfyUI.
- Suppression des commandes Démarrer, Redémarrer, Arrêter et Kill dans la page Système.
- AmiorAI se connecte désormais uniquement à une instance ComfyUI tierce déjà démarrée via son API HTTP locale.
- Conservation des fonctions API utiles : génération, diagnostic, lecture de la file, catalogue de modèles et libération de VRAM.
- Migration automatique supprimant les anciens réglages de gestion de processus ComfyUI.
- Documentation et traductions FR/EN/ES/DE mises à jour.

## v40.0.6 — 12 juillet 2026

### Exemples de saisie génériques

- Remplacement des placeholders personnalisés ou trop spécifiques par des exemples neutres et réutilisables.
- Harmonisation des champs sur les interfaces bureau et mobile.
- Révision complète des formulations françaises, anglaises, espagnoles et allemandes.
- Mise à jour du fichier maître `translations_master.xlsx` afin que les anciens exemples ne réapparaissent pas lors d’une régénération.
- Conservation des exemples techniques utiles : URL locales, chemins de modèles et valeurs numériques.

## v40.0.5 — 12 juillet 2026

### Documentation GitHub

- Refonte complète de la page `README.md` pour présenter clairement AmiorAI avant la documentation technique.
- Ajout d’un résumé des fonctions, d’une installation rapide, d’un premier parcours utilisateur et d’un guide d’utilisation quotidien.
- Ajout de `README_FR.md`, documentation française complète accessible depuis la page principale.
- Documentation détaillée de LM Studio, ComfyUI, Krea 2, Flux 2 Klein, Chatterbox, Qwen3-TTS, du bouton `▶ Écouter`, de la VRAM et du mode LAN.
- Clarification de l’emplacement des données, de la sauvegarde, des mises à jour et des exclusions Git.
- Aucun changement fonctionnel du moteur, des conversations, des images ou du TTS.

---

# Changelog

## v40.0.4 — 12 juillet 2026

- Added a repository-specific `.gitignore` excluding embedded Python runtimes, downloaded models, personal data, logs, secrets and release archives.
- Added the complete Apache License 2.0 text in `LICENSE`.
- Added `NOTICE` with **Copyright 2026 Ariku** and a pointer to third-party notices.
- Added SPDX `Apache-2.0` copyright identifiers to source and launcher files.
- Updated README, legal acknowledgement, third-party notices and release metadata for public GitHub distribution.

## v40.0.3 — 12 juillet 2026

- Added a visible **▶ Listen / Écouter** button to every assistant message, including messages containing an image, on desktop and mobile.
- The manual voice button remains visible when TTS is disabled and redirects to the Voice settings with a clear explanation.
- Fixed the live settings state: enabling TTS now refreshes the active conversation immediately instead of requiring an application restart.
- Added FR/EN/ES/DE translations and a cache-busting frontend version.

## v40.0.2 — 11 juillet 2026

- Corrige l'installation partielle de Chatterbox pouvant laisser `python_chatterbox` présent sans le module `chatterbox`.
- L'installateur Chatterbox répare désormais automatiquement `_pth`, `site-packages`, pip et le paquet officiel `chatterbox-tts`.
- Ajoute `tts_server\repair_chatterbox.bat` pour une réparation simple sans supprimer les modèles téléchargés.
- Vérifie le module TTS avec le Python Embedded exact avant de démarrer le serveur.
- Évite de retélécharger PyTorch lorsqu'une installation 2.8.0 valide est déjà présente.
- Ajoute un journal détaillé `tts_server\install_chatterbox_pip.log`.

## v40.0.1 — Embedded TTS runtimes and coordinated VRAM swap (2026-07-11)

- Replaced the Windows TTS virtual environments with two autonomous official Python Embedded runtimes:
  - `tts_server/python_chatterbox` using Python 3.11.9;
  - `tts_server/python_qwen` using Python 3.12.10.
- Removed the requirement to install Python globally or modify Windows PATH for either voice engine.
- Kept Chatterbox and Qwen fully separated so incompatible ML dependencies cannot affect one another or AmiorAI's main `python_embed` runtime.
- Added the **Release VRAM between engines** setting, enabled by default and recommended for 16 GB GPUs.
- Before LM Studio or ComfyUI takes CUDA ownership, AmiorAI stops the TTS process and waits for its local server to disappear, guaranteeing that PyTorch releases the CUDA context.
- Before CUDA TTS starts, AmiorAI unloads its LM Studio models and asks idle ComfyUI to free its models.
- Added a loopback-only `/shutdown` endpoint to the local TTS server for VRAM release even when the server was launched manually.
- CPU TTS remains running because it does not occupy GPU VRAM.
- Updated the setup guide, TTS documentation, third-party notices and FR/EN/ES/DE interface strings.
- Expanded the translation catalogue to 991 keys and updated the locale metadata to 40.0.1.

## v40.0.0 — Local voice-engine rewrite (2026-07-11)

- Removed the previous XTTS/Coqui runtime and installer path; v40 no longer launches or installs it.
- Added Chatterbox Multilingual V3 as the default local multilingual voice engine.
- Added Qwen3-TTS 0.6B Base as an optional experimental engine.
- Isolated both engines in separate virtual environments to prevent incompatible `transformers` and model dependencies from breaking one another.
- Preserved existing character voice samples and added an optional exact reference transcript for higher-quality Qwen cloning.
- Added engine-aware health checks, automatic restart on engine changes and clearer diagnostic states.
- Waits for a voice model already in the `loading` state to become ready instead of sending an early request that would return HTTP 503.
- Added configurable Chatterbox expressiveness, voice fidelity and temperature controls.
- Improved long-reply reading with sentence-aware chunks, Markdown cleanup, reference-audio normalization and output stitching.
- Replaced temporary output files with an in-memory WAV response and reject invalid server audio before it can create a broken player entry.
- Added dedicated Windows, PowerShell and Linux installers for the default and experimental engines, with reliable Python 3.11/3.12 detection.
- Documented the original separate system-Python requirement for TTS installation and the explicit CPU-only installer setting; v40.0.1 later replaced that requirement with embedded runtimes.
- Completed the new voice-panel translations in French, English, Spanish and German. Fully synchronized the 989-key `translations_master.xlsx` catalogue and repaired its command-line generator path.
- Updated the legal notice with explicit voice-consent and anti-impersonation rules.
- Added `THIRD_PARTY_NOTICES.md` with upstream source and licence references.

## v39.1.9 — Section save buttons in Settings (2026-07-11)

- Added a local **Save this section** action after the long editable Settings sections:
  - language model;
  - utility model;
  - TTS;
  - voice dictation;
  - ComfyUI;
  - VRAM management.
- Each section now shows:
  - unsaved-change warning after an edit;
  - saving state;
  - visible success or failure feedback.
- Kept a final **Save all settings** button as a global fallback.
- Persona keeps its dedicated save button and now warns when its fields have unsaved changes.
- Appearance and language explicitly indicate that they are applied and saved immediately.
- Fixed the French language selector, which incorrectly pointed to `en`.
- Added and synchronized the new labels in EN/FR/ES/DE and in `translations_master.xlsx`.

## v39.1.8 — Legal notice and complete installation guide (2026-07-11)

- Added a bilingual `LEGAL_NOTICE.md` covering as-is distribution, AI outputs, user responsibility, third-party software, local-network security, technical risks, adult/consensual roleplay, mandatory legal carve-outs and voluntary donations.
- Added a one-time legal acknowledgement to both `install.bat` and `start.bat`.
- Rebuilt `README.md` as a complete Windows installation and configuration guide for AmiorAI, LM Studio and ComfyUI.
- Added explicit LM Studio model-list/testing steps, ComfyUI path/Python examples, Krea 2 model locations, Flux 2 Klein setup, missing-node diagnostics, first-run checklist, backup instructions and LAN safety.

## v39.1.7 — Full audit and clean distribution hierarchy (2026-07-11)

- Renamed `setup_embedded_python.bat` to the clearer `install.bat`.
- Kept only `install.bat` and `start.bat` as visible Windows entry scripts in the root.
- Moved the optional Linux launcher to `platform/linux/start.sh`.
- Moved user documentation to `docs/` and removed historical audit/merge files from the runtime archive.
- Removed the unused PyInstaller/pywebview shell, build specification, developer test tools, caches, duplicate logos and unused icon assets.
- Corrected ComfyUI/TTS log and generated-audio paths to use the persistent `DATA_ROOT` hierarchy.
- Hardened uploaded filenames and base64 payload handling against path traversal and oversized payloads.
- Updated documentation for the current immersive illustration behavior and three optional Krea 2 LoRA slots.

## v39.1.6 — Immersive scene default and persona LoRA shortcut (2026-07-11)

- Reworked chat illustration buttons:
  - main action is now “Bring this scene to life”, using the user persona path when relevant;
  - secondary action is “Character only”, forcing a solo contemplative image with no user persona or secondary actor.
- Added character-only Krea planner context so the previous user message can preserve setting/mood without adding the user into solo images.
- Added Krea persona controls directly in Settings → Persona:
  - Krea persona token;
  - Krea persona LoRA selector;
  - persona LoRA strength.
- The persona LoRA selector writes to the existing Krea Character LoRA 2 slot and stays inactive when set to none.
- Flux immersive illustration now falls back to a generic-user prompt instead of hard failing when no persona image is configured.

## v39.1.5 — Immersive illustration planner and 3-slot Krea LoRA chain (2026-07-11)

- Illustrate now sends the previous user message plus the selected assistant message to the Krea 2 utility scene planner, so user/character actions are preserved instead of turning into generic portraits.
- Krea 2 scene planner prompt updated for explicit, literal, interaction-aware descriptions with a consent/adult guard and no added moralizing language.
- Conversation roleplay system now includes a global editable style instruction for concrete, precise, embodied action narration.
- Advanced Prompts now exposes Character Creation, Conversation Style, Flux Scene Planner and Krea 2 Scene Planner.
- Krea 2 unified workflow now supports three optional LoRA slots: character 1, character 2/user persona and utility. Setting a slot to none bypasses it completely.
- Added optional Krea user/persona token field for the second character LoRA.

## v39.1.4 — LM Studio model selectors and reasoning-response compatibility (2026-07-11)

- Replaced manual LM Studio model-ID entry with refreshable selectors populated from `/v1/models`.
- Added separate conversation and utility model selectors while keeping “reuse conversation model” as the utility default.
- Added compatibility for content arrays, `output_text`, `text`, `reasoning_content`, and `reasoning` response fields.
- Increased the utility diagnostic test budget from 10 to 96 tokens to avoid reasoning models consuming the entire budget before producing a final answer.
- Empty replies now report `finish_reason` and explain the likely reasoning-token-budget issue.

## v39.1.3 — Conversation numeric fix and live runtime diagnostic (2026-07-11)

- Fixed conversation failures caused by empty numeric settings such as `llm_temperature` or `llm_max_tokens`; empty/invalid values now fall back safely.
- Added a Diagnostic image-engine selector to run checks specifically for Flux 2 Klein or Krea 2.
- Added Krea 2 diagnostic checks for diffusion model, text encoder, VAE, unified workflow, ResolutionSelector and both LoRA slots.
- Added live LM Studio lifecycle states: checking, loading, waiting, stabilizing, generating, unloading, loaded and error.
- Added live ComfyUI generation states: submitting, queued, generating, processing, downloading, complete and error, with queue counts and elapsed time.
- Added `/api/runtime/status` and localized Diagnostic UI labels in English, French, Spanish and German.
- The live displays intentionally report real textual phases rather than inventing an unsupported percentage.

## v39.1.2 — Krea 2 resolution controls, icon reliability and LM Studio utility fix (2026-07-11)

- Added Krea 2 ResolutionSelector support: aspect ratio, megapixels and multiple are now configurable from the Krea panel and injected into the unified Krea workflow.
- Updated the bundled `workflows/krea2/krea2_unified.json` to use a ResolutionSelector node feeding EmptyLatentImage width and height.
- Fixed `name 'time' is not defined` in `lmstudio_vram.py`, which could break the utility-model route during first load/unload operations.
- Made the icon system self-contained by embedding a gradient inside each generated SVG, preventing invisible icons when document-level gradient references fail in some webviews/browsers.
- Bumped icon asset cache-busting to `v39.1.2`.

# Changelog

## v39.1.1 — Source package cleanup (2026-07-11)

- Removed `build_exe.bat` because the executable packaging path is not part of the current supported workflow.
- Removed the obsolete `build_exe.ps1` wrapper that depended on the deleted batch file.
- Kept `AmiorAI.spec` as an optional manual PyInstaller configuration for later use.
- Updated packaging comments and version metadata without changing application behavior.

## v39.1.0 — Non-destructive v39 + Krea 2 merge (2026-07-11)

- Uses v39.0.3 as the interface, icon, translation and diagnostic foundation.
- Preserves the v39 sidebar, official icons, dynamic chat/scenario localization and fully localized diagnostic page.
- Merges the LM Studio-only conversation and utility architecture from v38.1.3.
- Merges the global Flux 2 Klein / Krea 2 selector across avatars, previews, conversations, emotions, groups, LoRA previews and Studio, including mobile.
- Merges the unified Krea 2 workflow, exact ComfyUI loader-name resolution, diffusion/CLIP/VAE selection and separate character/utility LoRA slots.
- Restores character writing helpers and roleplay rendering: narration in gray italics and quoted expressions in orange italics.
- Keeps existing user data and database migrations non-destructive.

## v39.0.3 — Diagnostic multilingue (2026-07-02)

### Traductions
- La page **Diagnostic** est maintenant traduite intégralement : chargement, erreurs, statuts, résumé, durée, sections, contrôles, détails techniques et rapport copiable.
- Les résultats générés par le backend exposent des clés i18n et variables ; changer de langue relocalise un rapport déjà affiché immédiatement, sans relancer le diagnostic.
- **101 nouvelles clés** ajoutées au catalogue : **892 clés synchronisées** en FR / EN / ES / DE.
- Les messages système bruts provenant directement de LM Studio, ComfyUI ou du réseau restent techniques, afin de préserver le détail utile au dépannage.

### Qualité
- Nouveau contrôle `tools/check_v3903_diagnostic_i18n.py` : parité des 4 langues, variables, clés runtime, métadonnées backend et rapport réel minimal.
- Correctif ciblé : aucune donnée utilisateur ni workflow n’est modifié.

## v39.0.2 — Icône Personnages AmiorAI (2026-07-02)

### Interface
- L’entrée **Personnages** utilise désormais le monogramme officiel AmiorAI, au lieu de l’icône générique de groupe.
- Le logo transparent conserve le dégradé cyan → bleu → violet et les effets de survol / état actif du menu v39.
- L’ancienne icône générique est retirée des assets de navigation afin d’éviter toute régression.

### Contrôle
- Le contrôle UI vérifie maintenant explicitement que l’icône Personnages pointe vers `brand-mark.png`.

## v39.0.1 — Correctif menu

- Ajout de l’icône raster **Personnages** dans la navigation principale.
- L’icône utilise désormais le même système d’affichage, de survol et d’état actif que les autres entrées du menu.

## v39.0.0 — Creative Companion UI Refresh (2026-07-02)

### Interface
- Nouvelle barre latérale sombre structurée, inspirée du template validé : groupes clairs, icônes homogènes, état actif cyan-violet discret et meilleure densité visuelle.
- Intégration des icônes fournies dans le menu : conversations, scénarios, journal, galerie, Studio Image, bibliothèque, modèles, LoRA, système, réglages et diagnostic.
- Vue Conversation affinée : cartes de conversations, panneau principal, bulles, composeur et actions gagnent en lisibilité sans modifier le fonctionnement existant.
- Le thème sombre est le choix initial sur une installation neuve. Les préférences utilisateur existantes restent prioritaires.

### Traductions
- Correction du composeur de conversation : placeholder, dictée, bouton **Envoyer** et **Réagir** proviennent désormais du catalogue i18n.
- Changer de langue réaffiche la conversation ouverte immédiatement et préserve le brouillon saisi.
- Sélecteurs de scénario entièrement localisés : lieu, ambiance, thème et relation.
- 52 nouvelles clés ajoutées, pour un catalogue synchronisé de **791 clés** FR / EN / ES / DE.
- Les chaînes usuelles Chat + Scénarios reçoivent désormais des traductions ES et DE au lieu du repli anglais.

### Qualité
- Nouveau contrôle `tools/check_v39_ui.py` : assets icônes, mapping de navigation, relocalisation dynamique du chat et parité des catalogues.
- Validation projet conservée : 0 erreur, 0 avertissement ; 12 workflows Flux 2 valides.

## v38.1.0 — Audit, localisation et interface harmonisée (2026-06-30)

### Audit et fiabilité
- Validation complète du backend, des imports critiques et des 12 workflows Flux 2 : **0 erreur, 0 avertissement**.
- Contrôle statique des appels API : aucun endpoint frontend orphelin détecté.
- Suppression de 8 imports Python inutilisés.
- Base locale `data/companion.db` exclue de la livraison source ; le dossier de données reste créé au premier lancement.

### Traductions
- Langue par défaut réglée sur **anglais** pour les nouvelles installations, sans écraser les préférences déjà enregistrées.
- Catalogue maître synchronisé à **739 clés** dans les quatre locales FR / EN / ES / DE.
- Ajout de la localisation des retours dynamiques : création de personnage, avatar, mémoire, conversations, Studio mobile, galerie et contrôles de langue.
- Le configurateur physique est désormais traduit et se réaffiche lors d’un changement de langue tout en conservant les choix déjà saisis.
- ES et DE sont complets au niveau des clés ; les anciennes cellules qui n’avaient pas de traduction utilisent temporairement le texte EN comme repli explicite, à reprendre dans une passe éditoriale dédiée.

### Interface
- Sélecteur de langue rapide dans la barre latérale desktop et dans le menu mobile.
- Hiérarchie, densité des panneaux, états de focus clavier et marges harmonisés.
- Correction d’un attribut `style` dupliqué dans la vue Diagnostic.

## v38.0.1 — Image Path, Character Generation Localization & Dev Tools Fix (2026-06)

### Correctifs appliqués

**Fix 1 — Chemins d'images unifiés (`app_paths.py`)**
- Nouveau module `app_paths.py` : source unique de vérité pour `CODE_ROOT`, `DATA_ROOT`, `IMG_DIR`, `WF_DIR`, `LOG_DIR`, `BACKUP_DIR`, `DB_PATH`, `LEGACY_IMG_DIR`, `resolve_img()`
- `engine.py` et `app.py` importent depuis `app_paths` — aucune divergence possible
- `IS_FROZEN` exporté depuis `app_paths` (corrigé après audit : engine.py l'utilisait sans l'importer)
- Route `/img/` : `urllib.parse.unquote`, `os.path.basename`, 404 propre avec log, fallback legacy avec warning
- `comfy_queue_and_fetch()` : vérification `os.path.isfile(dest_path)`, log chemin complet via `log.info`
- `imgUrl()` dans `app.js` : `encodeURIComponent` + extraction basename

**Fix 2 — Génération personnage vraiment localisée (`i18n_backend.py`)**
- Nouveau module `i18n_backend.py` : prompts CHARGEN complets par langue (FR/EN/ES/DE), CONFIG_MAP restructuré (`{"fr", "en", "es", "de", "image_tag"}`), `build_chargen_messages()`, `config_to_text_and_tags()`, `orientation_text()`, `t_backend()`
- `generate_character()` appelle `build_chargen_messages(lang)` — plus aucun français codé en dur
- `CHARGEN_SYSTEM` (variable morte) supprimée — remplacée par un commentaire documentant la nouvelle architecture
- `_en_phrase()` dans `app.py` corrigée pour la nouvelle structure dict de CONFIG_MAP (était `entry[1]`, devient `entry.get("image_tag")`)
- `get_effective_chargen_system()` simplifiée — retourne le prompt localisé depuis `_CHARGEN_SYSTEM`

**Fix 3 — Dev Tools opérationnels**
- `generate_locales()` est maintenant une fonction Python importable directement (pas de subprocess)
- Routes corrigées : `GET /api/i18n/export`, `POST /api/i18n/import-file` (multipart réel), `POST /api/i18n/analyze`, `POST /api/i18n/generate`, `POST /api/i18n/reload`, `POST /api/i18n/restore-last-backup`
- `_read_body()` gère multipart/form-data ; `_extract_multipart_file()` extrait le binaire par nom de champ
- Frontend : export via `window.location.href` (GET), import via vrai `FormData`, erreurs affichées avec `error_code + message + details`
- `openpyxl` ajouté à `requirements.txt`

### Bugs supplémentaires corrigés pendant l'audit
- `/api/llm/load` dupliqué dans le handler POST → doublon supprimé
- `import sys` dupliqué → nettoyé
- `IS_FROZEN` non exporté depuis `app_paths` → corrigé (`from app_paths import ..., IS_FROZEN`)
- Log `logging.info` dans `engine.py` harmonisé avec le logger local `log`
- Log debug `/img/` trop verbeux en prod → retiré (seuls les warnings legacy et 404 restent)

### Tests audit (37/37)
Tous les tests fonctionnels passent : chemins, imgUrl, i18n_backend (12 langues × 4 tests), CONFIG_MAP, generate_locales (dry-run + écriture réelle + erreur structurée), locales JSON, intégrité app.py, engine.py, compilation.

---

## v38.0 — Internationalisation Foundation (2026-06)


### Nouveau : Système i18n complet (FR / EN / ES / DE)

**Architecture**
- `resources/i18n/translations_master.xlsx` — source de vérité, 436 clés, 4 onglets (Strings / Glossary / Config / Notes)
- `resources/i18n/locales/fr.json` — locale complète (~436 clés)
- `resources/i18n/locales/en.json` — fallback obligatoire (~436 clés)
- `resources/i18n/locales/es.json` — core strings (~80 clés)
- `resources/i18n/locales/de.json` — core strings (~80 clés)
- Fallback chain : langue active → EN → clé technique visible (jamais de chaîne vide)

**Runtime i18n (`web/i18n.js`)**
- `t("key", { vars })` — traduction avec substitution de variables `{name}`, `{n}`, etc.
- `I18n.setLanguage(lang)` — charge le JSON, applique au DOM, persiste en `localStorage` + `POST /api/settings/lang`
- `I18n.applyToDOM()` — applique `data-i18n`, `data-i18n-placeholder`, `data-i18n-title`, `data-i18n-aria`, `data-i18n-html`
- Event `amiorai:lang-changed` dispatché pour reconstruire les menus dynamiques
- Chargé dans `<head>` (avant le premier rendu)

**Interface (`web/index.html`)**
- Attributs `data-i18n` sur tous les éléments statiques de l'interface
- Panel **Langue** dans Réglages → sélecteur FR / EN / ES / DE (boutons `data-lang`)
- Panel **Développeur → Traductions** (caché par défaut) :
  - Export / Import `translations_master.xlsx`
  - Analyse avant import (dry-run)
  - Actualisation des JSON depuis le maître
  - Rechargement sans redémarrage
  - Restauration de la dernière sauvegarde
  - Stats : nb clés, langues complètes, clés manquantes

**Backend (`app.py`)**
- `"ui_language": "fr"` ajouté dans `DEFAULT_SETTINGS`
- Routes GET : `/i18n.js`, `/locales/{lang}.json`, `/api/settings/lang`
- Routes POST : `/api/settings/lang`, `/api/i18n/reload`, `/api/i18n/stats`, `/api/i18n/generate`, `/api/i18n/restore_backup`, `/api/i18n/export`
- `get_effective_chargen_system()` — injecte une directive de langue (fr/en/es/de) avant le prompt CHARGEN ; le champ `image_prompt` reste toujours en anglais (requis par FLUX)

**Interface mobile (`web/mobile.html`)**
- `i18n.js` chargé dans `<head>`
- Attributs `data-i18n` sur la nav et les boutons principaux
- Init i18n au démarrage (synchronisé avec `settings.ui_language`)

**Outils développeur**
- `tools/generate_locales.py` — Excel → JSON avec validation (doublons, EN vide, variables), sauvegarde auto dans `locales_backup/`
- `tools/audit_hardcoded.py` — détecte les chaînes françaises codées en dur dans `web/` (catégories : TRANSLATE / TECHNICAL / SUSPECT)
- `resources/i18n/README_i18n.md` — documentation complète du flux de travail

---

## v37.2 — Stabilisation (2026-06)


### Correctifs critiques

- **Données persistantes** : dossier de données migré vers `%LOCALAPPDATA%\AmiorAI\data\` (Windows),
  indépendant du dossier de build. Variable `AMIORAI_DATA_DIR` supportée. Migration automatique
  au premier lancement si un ancien `data\companion.db` valide est détecté.
- **Scan LoRA immédiat** : `api_model_folder_add` déclenche maintenant un scan réel après ajout,
  avec classification `kind=lora` forcée pour `kind_hint=lora`. Réponse enrichie avec `lora_count`.
- **Normalisation chemins dossiers** : `D:\loras\` et `D:\loras` reconnus comme doublons.
- **NameError Safetensors** : variable `unet_st` corrigée en `unet_sf` dans `engine.py` (ligne 1225).
- **Secrets masqués** : `llm_util_key` et `lmstudio_api_key` ajoutés à `_SETTINGS_NEVER_EXPOSE`.
  Indicateurs `llm_util_key_set` et `lmstudio_api_key_set` retournés à la place.
- **Mobile LAN** : déconnexion via `POST /api/lan/logout` (cookie HttpOnly non modifiable en JS).
  Sélection explicite d'un personnage avant création de conversation. Fix `r.id` pour la réponse
  de `/api/chat/create`.
- **Chemin persistant** : `%LOCALAPPDATA%\AmiorAI\data\` sur Windows, `AMIORAI_DATA_DIR` partout.

### Sécurité

- Protection des secrets renforcée dans `GET /api/settings`.
- Route `POST /api/lan/logout` invalidant la session côté serveur avec cookie expiré.

### Non-régression

- `tools/check_project.py` étendu : version, secrets, unet_st, logout, scan LoRA, absence de companion.db.
- Workflows Flux et slots LoRA 301/302 inchangés.

---

# AmiorAI — Journal des modifications




## v26 — 2026-06

### Nouveautés

- **Bibliothèque de modèles — classification manuelle** : chaque fichier peut désormais recevoir
  un type et une famille forcés via le bouton **✎ Identifier**. La correction est persistante
  et survit aux rescans. Champs `detected_kind`, `detected_family`, `manual_kind`,
  `manual_family`, `identification_source` ajoutés à la base de données.
- **Détection par chemin** : la famille d'un modèle est maintenant déduite du chemin relatif
  (ex. `diffusion_models/flux2/mon_modele.safetensors` → `flux2_klein`) avant le nom de fichier.
- **Mode Safetensors Flux 2 Klein** : 6 nouveaux workflows `*_st.json` utilisant `UNETLoader`
  avec le paramètre `weight_dtype`. Détection automatique de la valeur correcte via
  `/object_info/UNETLoader` de ComfyUI.
- **Résolveur central `resolve_flux2_workflow_variant()`** : toutes les générations Flux passent
  par cette fonction — plus aucun bypass silencieux possible. Validation pré-envoi des workflows.
- **Studio Image mode-aware** : le sélecteur UNet affiche uniquement les fichiers compatibles
  avec le mode actif (GGUF → `.gguf`, Safetensors → `.safetensors`). Récapitulatif mode/UNet/
  workflow effectif visible dans Studio.
- **Diagnostic intégré** : nouveau panneau 🔍 vérifiant Application, LM Studio, ComfyUI,
  Flux 2 Klein et Bibliothèque. Rapport copiable en texte brut.
- **`safeInit()` étendu** : chaque module (Studio, LoRA, Bibliothèque, Réglages…) s'initialise
  indépendamment. Une erreur dans un module n'interrompt plus les autres.
- **Bandeau d'erreurs non-bloquant** : les erreurs d'initialisation apparaissent en haut de page
  sans bloquer l'interface.
- **`FLUX2_WORKFLOW_VARIANTS`** : table de correspondance GGUF ↔ Safetensors centralisée dans
  `model_manifests.py` (source unique de vérité).
- **`LORA_SLOT_PRIMARY` / `LORA_SLOT_SECONDARY`** : constantes centralisées (`301` / `302`).
- **`tools/check_project.py`** : script de vérification pré-livraison (compilation, workflows,
  slots LoRA, doublons JS).

### Corrections

- **`api_model_folders_list()` restaurée** : le corps de la fonction était orphelin après un
  `return` dans `api_advanced_prompts_restore`. La vue Bibliothèque était inaccessible.
- **Workflows `*_st.json`** : `weight_dtype` ajouté dans tous les nodes `UNETLoader`, et
  les références à un fichier `.gguf` dans `unet_name` supprimées.
- **Erreur de syntaxe JavaScript** : deux chaînes de caractères cassaient le parsing de `app.js`
  au chargement, rendant toute l'interface non-cliquable.
- **`loadLoras()` déclarée deux fois** : fusionnée en une seule fonction canonique.
- **Import `socket` inutile** supprimé de `diagnostic.py`.

### Changements internes

- `model_catalog.py` : réécriture complète avec `rescan_folder()` préservant les overrides
  manuels, `_guess_family_from_path()` pour la détection par chemin.
- `engine.py` : variable locale `unet_st` renommée `unet_sf` pour clarté ; `_flux2_workflow`
  devient alias public `resolve_flux2_workflow_variant`.
- `app.py` : `api_image_compatibility()` retourne `flux2_mode` et `flux2_summary` ; validation
  mode-aware (seul l'UNet du mode actif est `required`).
- `web/app.js` : `switchView()` passe tous les modules par `safeInit()`.

### Incompatibilités

- La base de données est automatiquement migrée au démarrage (colonnes `detected_kind`,
  `detected_family`, `manual_kind`, `manual_family`, `identification_source`, `updated_at`
  ajoutées à `model_files` si absentes).
- Aucune modification des workflows GGUF existants ni des slots LoRA 301/302.


## v38.1.3 — Menu icon restoration

- Restored the AmiorAI cyan/blue/violet SVG icon set in the desktop sidebar.
- Made icon initialization independent from the main application JavaScript, so menu icons remain visible even if another module reports a startup error.
- Replaced the generic Characters symbol with a compact AmiorAI mascot/logo icon.
- Applied the same icon system to the mobile bottom navigation instead of platform-dependent emojis.
- Added asset cache-busting to prevent an older empty icon state from persisting after an update.
- Preserved all LM Studio-only, global Flux/Krea 2 and ComfyUI loader fixes from v38.1.2.


## v38.1.2 — LM Studio-only and global Krea/Flux engine

- Removed Kobold, Ollama and in-process llama.cpp runtime/install routes.
- Conversation and utility models now use the same LM Studio server exclusively.
- Resolved the exact `/v1/models` ID before `/v1/chat/completions`, preventing misleading HTTP 400 failures caused by invalid placeholder/native IDs.
- Preserved LM Studio HTTP error details in diagnostics.
- Made ComfyUI release confirmation and active-job wait limits configurable (defaults: 30 s and 180 s).
- Added one global Flux 2 Klein / Krea 2 selector for avatars, configurator previews, chat images, emotion portraits, group scenes, LoRA previews and Image Studio, on both desktop and mobile.
- Fixed Krea 2 model-path validation by resolving catalog paths against ComfyUI loader choices.
- Added strict Krea model/CLIP/VAE/LoRA validation with readable available-value errors.
- Krea group scenes no longer require avatar files; they use the unified descriptive T2I workflow.
- Simplified installers, requirements and PyInstaller configuration for the LM Studio-only architecture.
- Updated README, quick start and troubleshooting documentation.


## v38.1.1 — Krea 2 integration audit and fixes

- Audited the Krea 2 workflow graph and verified all four LoRA states: none, character only, utility only, and both chained.
- Added Krea 2 family detection for model filenames and folders, plus Krea 2 entries in manual classification and library filters.
- Filtered the Krea 2 LoRA selectors to Krea-compatible catalogue entries when family metadata is available, while keeping an all-LoRA fallback for unclassified libraries.
- Enforced component file extensions in Image Studio so the Krea `UNETLoader` cannot accidentally receive a GGUF file.
- Added safe sampler profiles: Auto, Turbo/distilled (8 steps, CFG 1), RAW (52 steps, CFG 3.5), and Custom.
- Fixed duplicated physical descriptions when `locked_tags` were already prepended to `image_prompt`.
- Fixed the `Force physical base description` toggle for canonical avatar generation.
- Made configurator preview caching family-aware so cached Flux previews are never reused as Krea previews.
- Improved cross-platform LoRA path resolution for Windows backslashes and Linux forward slashes.
- Added Krea 2 setup and user-data/memory locations to the README.
- Preserved ComfyUI subfolder paths for selectable Krea models and catalogue-only LoRA fallbacks.
- Made reduced preview steps effective for Turbo/distilled checkpoints while retaining the safe RAW profile.
- Prevented Flux chat-level “apply once” LoRA overrides from being consumed during a Krea generation.
- Added an offline Krea integration smoke-test tool covering graph rewiring, profiles, prompts, paths, and guards.

## v38.1.0 — Krea 2 unified workflow

- New image family "Krea 2" with a SINGLE unified workflow (`workflows/krea2/krea2_unified.json`, based on the provided reference workflow) used for avatars, conversation images, character/template previews, LoRA previews and Studio generation.
- Selectable Krea diffusion model, CLIP encoder (type krea2) and VAE via Studio Image (settings `krea2_unet` / `krea2_clip` / `krea2_vae`), injected dynamically into the graph.
- Two dedicated LoRA slots with independent strength sliders: character LoRA (identity, slot 301) and utility LoRA (style/rendering, slot 302), chained base model → character → utility. Both optional, both combinable. Empty slots are bypassed by node removal + rewiring (architectural invariant preserved, never `lora_name=""`).
- New dedicated Krea 2 prompt builder (`krea_prompt_builder.py`): explicit, literal, physically complete descriptive prompts (identity token, physical base, framing, pose, outfit, environment, weather, lighting, mood, style traits) — never the compact Flux template.
- Per-character options: `krea_token` (identity/LoRA trigger word) and `krea_force_physical` (force the configurator's physical base description into every Krea prompt, ON by default). Editable in the character editor.
- Template/option previews and LoRA previews route through the same unified workflow with lighter settings (reduced steps, 512×512).
- Krea prompts are editable for avatar, chat-image and Studio generation; automated template previews use their fixed preview prompt.
- No change to any Flux workflow, prompt path, VRAM management, LoRA stack or existing family.
- Known limitations: Krea 2 is text-to-image only (no i2i/duo/trio/group/persona scenes — clear error suggests Flux for those); the Krea scene planner has no "advanced prompt override" entry yet; the chat-level LoRA override applies to the Flux LoRA stack only.

## v38.0.4

- Audited the release after v38.0.3.
- Set English as the default UI and TTS language.
- Translated remaining hardcoded user-facing UI strings in the frontend.
- Reworked README, quickstart, troubleshooting, launch, install, TTS, CUDA build, and desktop build scripts in English.
- Kept French locale files intentionally for optional French mode.
- Preserved the v38.0.3 chat rendering improvements for narration and quoted expressions.
- Preserved the v38.0.2 safer LM Studio model reload delays, waits, and retry behavior.

## v38.0.3

- Added visual rendering for roleplay narration and quoted expressions in chat messages.
- Kept stored message text unchanged; formatting is display-only.

## v38.0.2

- Improved LM Studio model reload timing.
- Added utility prompt buttons for character/personality instructions.
