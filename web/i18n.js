/* Copyright 2026 Ariku
 * SPDX-License-Identifier: Apache-2.0
 */
/**
 * AmiorAI i18n — Runtime de traduction
 * Version 39.0.3
 *
 * API publique :
 *   t("key.nested", { name: "Mia" })  → chaîne traduite
 *   I18n.setLanguage("en")             → charge + applique la langue
 *   I18n.getActiveLang()               → "fr" / "en" / ...
 *   I18n.applyToDOM()                  → réapplique toutes les traductions statiques
 *
 * Fallback chain : langue active → "en" → clé technique visible + warning console
 */

(function () {
  "use strict";

  const DEFAULT_LANG  = "en";
  const FALLBACK_LANG = "en";
  const SUPPORTED     = ["fr", "en", "es", "de"];
  const STORAGE_KEY   = "amiorai-lang";

  // Catalogue chargé en mémoire { lang: { ...keys } }
  const _catalog = {};
  let   _active  = DEFAULT_LANG;
  let   _loaded  = false;

  // ── Résolution de clé ────────────────────────────────────────────────────
  function _resolve(lang, key) {
    const data = _catalog[lang];
    if (!data) return undefined;
    const parts = key.split(".");
    let node = data;
    for (const p of parts) {
      if (node == null || typeof node !== "object") return undefined;
      node = node[p];
    }
    return typeof node === "string" ? node : undefined;
  }

  // ── Substitution des variables {name}, {count}, etc. ────────────────────
  function _interpolate(str, vars) {
    if (!vars || typeof str !== "string") return str;
    return str.replace(/\{(\w+)\}/g, (_, k) =>
      vars[k] !== undefined ? vars[k] : "{" + k + "}"
    );
  }

  // ── Fonction principale t() ──────────────────────────────────────────────
  function t(key, vars) {
    // Langue active
    let val = _resolve(_active, key);
    if (val === undefined && _active !== FALLBACK_LANG) {
      // Fallback anglais
      val = _resolve(FALLBACK_LANG, key);
      if (val !== undefined && _loaded) {
        console.warn("[i18n] EN fallback for key:", key, "(active language:", _active + ")");
      }
    }
    if (val === undefined) {
      console.warn("[i18n] Missing key:", key);
      return key; // Affiche la clé technique — jamais de chaîne vide
    }
    return _interpolate(val, vars);
  }

  // ── Chargement d'un JSON de locale ──────────────────────────────────────
  async function _loadLocale(lang) {
    if (_catalog[lang]) return _catalog[lang];
    try {
      const r = await fetch("/locales/" + lang + ".json?v=" + Date.now());
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      _catalog[lang] = data;
      return data;
    } catch (e) {
      console.error("[i18n] Unable to load locale:", lang, e);
      return null;
    }
  }

  // ── Applique les attributs data-i18n au DOM ──────────────────────────────
  function applyToDOM() {
    // data-i18n="key" → textContent
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      if (key) el.textContent = t(key);
    });
    // data-i18n-html="key" → innerHTML (pour les liens)
    document.querySelectorAll("[data-i18n-html]").forEach(el => {
      const key = el.getAttribute("data-i18n-html");
      if (key) el.innerHTML = t(key);
    });
    // data-i18n-placeholder="key"
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) el.placeholder = t(key);
    });
    // data-i18n-title="key"
    document.querySelectorAll("[data-i18n-title]").forEach(el => {
      const key = el.getAttribute("data-i18n-title");
      if (key) el.title = t(key);
    });
    // data-i18n-aria="key"
    document.querySelectorAll("[data-i18n-aria]").forEach(el => {
      const key = el.getAttribute("data-i18n-aria");
      if (key) el.setAttribute("aria-label", t(key));
    });
    // data-i18n-opt="key" → traduit les <option> selon leur value (via sous-clé)
    // Ex: data-i18n-opt="library.kind_" + value → library.kind_checkpoint
    document.querySelectorAll("select[data-i18n-opt]").forEach(sel => {
      const prefix = sel.getAttribute("data-i18n-opt");
      sel.querySelectorAll("option").forEach(opt => {
        const val = opt.value;
        if (!val) return; // skip default empty
        const k = prefix + val;
        const tr = _resolve(_active, k) || _resolve(FALLBACK_LANG, k);
        if (tr) opt.textContent = tr;
      });
    });
    // data-i18n-label="key" — pour les <label> wrapping des <input>
    document.querySelectorAll("[data-i18n-label]").forEach(el => {
      const key = el.getAttribute("data-i18n-label");
      if (key) {
        // cherche un noeud texte direct (après les éléments enfants)
        const tn = [...el.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
        if (tn) tn.textContent = t(key) + " ";
        else el.prepend(t(key) + " ");
      }
    });
  }

  // ── Changement de langue ──────────────────────────────────────────────────
  async function setLanguage(lang, persist = true) {
    if (!SUPPORTED.includes(lang)) {
      console.warn("[i18n] Unsupported language:", lang, "— falling back to", DEFAULT_LANG);
      lang = DEFAULT_LANG;
    }
    // Toujours s'assurer que EN est chargé (fallback obligatoire)
    await _loadLocale(FALLBACK_LANG);
    await _loadLocale(lang);
    _active = lang;
    _loaded = true;

    // Mise à jour <html lang>
    document.documentElement.lang = lang;

    // Persistance locale
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) { /* ignore */ }

    // Persistance backend (sans bloquer le reste)
    if (persist) {
      fetch("/api/settings/lang", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang })
      }).catch(() => { /* silencieux — non critique */ });
    }

    // Applique le DOM
    applyToDOM();

    // Dispatch un événement pour que app.js puisse reconstruire les menus dynamiques
    document.dispatchEvent(new CustomEvent("amiorai:lang-changed", { detail: { lang } }));
  }

  function getActiveLang() { return _active; }

  // ── Init au chargement de la page ────────────────────────────────────────
  async function init() {
    // Priorité : localStorage → backend (chargé via /api/settings par app.js, pas ici)
    let lang = DEFAULT_LANG;
    try { lang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG; } catch (_) { /* ignore */ }
    if (!SUPPORTED.includes(lang)) lang = DEFAULT_LANG;

    // Pré-charge la locale par défaut immédiatement (synchronise le DOM avant le premier render)
    await _loadLocale(FALLBACK_LANG);
    await _loadLocale(lang);
    _active = lang;
    _loaded = true;
    document.documentElement.lang = lang;
    // DOM pas encore complet ici, applyToDOM sera appelé par app.js après DOMContentLoaded
  }

  // Expose l'API publique
  window.I18n = { t, setLanguage, getActiveLang, applyToDOM, getSupportedLangs: () => SUPPORTED };
  window.t    = t; // raccourci global

  // Lance l'init (Promise, non bloquant)
  init().catch(console.error);

})();
