# AmiorAI i18n — Internationalisation

Version 40.0.6 — Système de traduction complet (FR/EN/ES/DE)

---

## Architecture

```
resources/i18n/
├── translations_master.xlsx   ← Source de vérité (4 onglets)
├── locales/
│   ├── fr.json               ← Locale complète (~957 clés)
│   ├── en.json               ← Fallback obligatoire (~957 clés)
│   ├── es.json               ← Locale complète (~957 clés)
│   └── de.json               ← Locale complète (~957 clés)
└── locales_backup/           ← Sauvegarde auto avant chaque regénération

web/
└── i18n.js                   ← Runtime (t(), setLanguage(), applyToDOM())

resources/i18n/
└── generate_locales.py        ← Excel → JSON
```

---

## API publique (`web/i18n.js`)

```js
// Traduction simple
t("nav.characters")                        // → "Personnages" (FR)

// Avec variables
t("char.toasts.created", { name: "Example character" }) // → "Personnage « Example character » créé."

// Changer la langue (persist = sauvegarder en backend)
await I18n.setLanguage("en")              // → charge en.json + applique au DOM

// Obtenir la langue active
I18n.getActiveLang()                      // → "fr"

// Réappliquer manuellement
I18n.applyToDOM()
```

---

## Attributs HTML

| Attribut                  | Usage                              |
|---------------------------|------------------------------------|
| `data-i18n="key"`         | `textContent` de l'élément         |
| `data-i18n-html="key"`    | `innerHTML` (pour les liens HTML)  |
| `data-i18n-placeholder="key"` | Attribut `placeholder`         |
| `data-i18n-title="key"`   | Attribut `title`                   |
| `data-i18n-aria="key"`    | `aria-label`                       |

---

## Flux de travail

### Modifier une traduction existante

1. Ouvrir `translations_master.xlsx` → onglet **Strings**
2. Modifier la cellule dans la colonne `fr`, `en`, `es` ou `de`
3. Enregistrer le fichier
4. Lancer :
   ```bash
   python resources/i18n/generate_locales.py
   ```
5. (Sans redémarrer) : Réglages → Développeur → ⚡ Recharger

### Ajouter une nouvelle clé

1. Ajouter une ligne dans **Strings** :
   - `key` : `section.sous_section.nom_clé` (ex: `char.form.new_label`)
   - `category` : section principale (ex: `char`)
   - `fr`, `en` : obligatoires — `es`, `de` : optionnels (fallback EN)
2. Référencer dans le HTML :
   ```html
   <button data-i18n="char.form.new_label">Libellé FR</button>
   ```
   Ou dans le JS :
   ```js
   toast(t("char.form.new_label"))
   ```
3. Générer les JSON :
   ```bash
   python resources/i18n/generate_locales.py
   ```

### Ajouter une nouvelle langue

1. Ajouter une colonne dans **Strings** (ex: `it` pour l'italien)
2. Ajouter la meta dans `generate_locales.py` (liste `LANGS` + `meta_info`)
3. Ajouter le bouton dans `index.html` (`#lang-picker`)
4. Ajouter la langue dans `web/i18n.js` (liste `SUPPORTED`)
5. Ajouter la directive de langue dans `get_effective_chargen_system()` de `app.py`

---

## Règles importantes

- **Ne jamais traduire** : attributs `value=""`, identifiants JS, routes API, champs `image_prompt`
- **L'anglais est le fallback** : toute clé absente dans `fr/es/de` utilise la valeur `en`
- **L'Excel est la source de vérité** : ne jamais modifier les JSON à la main — ils sont écrasés à chaque régénération
- **Les guillemets typographiques** dans les JSON doivent être encodés : `\u00ab`, `\u00bb`, `\u201e`, `\u201c`

---

## Scripts

### `generate_locales.py`
```bash
python resources/i18n/generate_locales.py              # génère les JSON
python resources/i18n/generate_locales.py --dry-run    # aperçu sans écriture
```
Valide : doublons, clés EN vides, cohérence des variables `{xxx}`.
Sauvegarde automatique dans `locales_backup/` avant chaque écriture.

---

## Backend

Routes disponibles :

| Méthode | Route                      | Action                                  |
|---------|----------------------------|-----------------------------------------|
| GET     | `/locales/{lang}.json`     | Sert le fichier JSON de locale          |
| GET     | `/api/settings/lang`       | Retourne la langue active (`ui_language`) |
| POST    | `/api/settings/lang`       | Change et sauvegarde la langue          |
| POST    | `/api/i18n/reload`         | Signal de rechargement (frontend reload) |
| POST    | `/api/i18n/stats`          | Stats : clés, langues complètes, manquantes |
| POST    | `/api/i18n/generate`       | Déclenche `generate_locales.py`         |
| POST    | `/api/i18n/generate` `dry_run:true` | Analyse sans écriture          |
| POST    | `/api/i18n/restore_backup` | Restaure `locales_backup/`              |
| GET/POST| `/api/i18n/export`         | Télécharge `translations_master.xlsx`   |

---

## Génération de personnages multilingue

La fonction `get_effective_chargen_system()` préfixe automatiquement le prompt CHARGEN avec une directive de langue selon `settings.ui_language` :

- **FR** : "Langue de génération : FRANÇAIS. Rédige impérativement en français..."
- **EN** : "Generation language: ENGLISH. Write all fields in English..."
- **ES** : "Idioma de generación: ESPAÑOL. Escribe todos los campos en español..."
- **DE** : "Generierungssprache: DEUTSCH. Schreibe alle Felder auf Deutsch..."

Le champ `image_prompt` reste **toujours en anglais** (requis par FLUX).
