/* Copyright 2026 Ariku
 * SPDX-License-Identifier: Apache-2.0
 */
"use strict";

// --------------------------------------------------------------------------- //
//  Petits utilitaires
// --------------------------------------------------------------------------- //
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "style") n.setAttribute("style", v);
    else if (typeof v === "boolean") {
      // Boolean attributes: never write selected="false" / disabled="false" etc.
      // The mere presence of the attribute means true in HTML.
      if (v && k in n) n[k] = true;          // ex: option.selected = true
      // v === false → write nothing
    } else if (v != null && v !== false) {
      n.setAttribute(k, v);
    }
  }
  for (const kid of kids) {
    if (kid == null) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return n;
};

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || window.t("common.http_error", { status: r.status }));
  return data;
}

async function uploadShareFile(path, file) {
  const form = new FormData();
  form.append("file", file, file.name || "share-package");
  const r = await fetch(path, { method: "POST", body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.error) throw new Error(data.error || window.t("common.http_error", { status: r.status }));
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  clearTimeout(toastTimer);
  $$(".toast").forEach((t) => t.remove());
  const t = el("div", { class: "toast" + (isErr ? " err" : "") }, msg);
  document.body.append(t);
  toastTimer = setTimeout(() => t.remove(), 4200);
}

function imgUrl(name) {
  const filename = String(name || "").split(/[\\/]/).pop();
  return "/img/" + encodeURIComponent(filename);
}

// --------------------------------------------------------------------------- //
//  Generic modal + prompt dialog + lightbox
// --------------------------------------------------------------------------- //
function overlay(node, onBackdrop) {
  const bg = el("div", { class: "overlay" });
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") (onBackdrop || close)(); };
  bg.addEventListener("click", (e) => { if (e.target === bg) (onBackdrop || close)(); });
  document.addEventListener("keydown", onKey);
  bg.append(node);
  document.body.append(bg);
  return close;
}

// Affiche le prompt proposé, éditable, avant envoi à ComfyUI. Résout le texte (ou null si annulé).
function promptDialog(initial, title = window.t("prompt.review_title")) {
  return new Promise((resolve) => {
    const ta = el("textarea", { class: "prompt-edit", rows: "6" });
    ta.value = initial || "";
    let close;
    const done = (v) => { close(); resolve(v); };
    const card = el("div", { class: "modal-card" },
      el("h3", {}, title),
      el("p", { class: "hint" }, window.t("prompt.review_hint")),
      ta,
      el("div", { class: "row", style: "justify-content:flex-end; gap:8px; margin-top:10px;" },
        el("button", { class: "btn ghost", onclick: () => done(null) }, window.t("common.cancel")),
        el("button", { class: "btn", onclick: () => done(ta.value.trim()) }, window.t("common.generate"))));
    close = overlay(card, () => done(null));
    setTimeout(() => ta.focus(), 50);
  });
}

function lightbox(src) {
  const img = el("img", { src, class: "lightbox-img" });
  const close = overlay(img);
  img.addEventListener("click", () => close());
}

// Click a generated chat image to enlarge it. Gallery cards are handled by renderGallery.
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.tagName === "IMG" && t.classList.contains("genimg") && !t.closest(".g")) {
    lightbox(t.src.split("?")[0]);
  }
});

// --------------------------------------------------------------------------- //
//  Navigation
// --------------------------------------------------------------------------- //
$$(".nav button").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view))
);

function switchView(name) {
  $$(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  // Chaque module charge dans son propre contexte sécurisé — une error n'en bloque pas d'autres
  if (name === "characters") safeInit("characters",  loadCharacters);
  if (name === "chats")      safeInit("conversations", loadChats);
  if (name === "gallery")    safeInit("galerie",       loadGallery);
  if (name === "system")     safeInit("system",       loadSystem);
  if (name === "settings")   safeInit("settings",      () => { loadSettings(); loadAdvancedPrompts(); });
  if (name === "scenarios")  safeInit("scenarios",     loadScenarios);
  if (name === "journal")    safeInit("journal",       loadJournal);
  if (name === "studio")     safeInit("studio",        loadStudio);
  if (name === "library")    safeInit("library",  loadLibrary);
  if (name === "models")     safeInit("models",       loadModels);
  if (name === "loras")      safeInit("loras",         loadLoras);
  if (name === "diagnostic") loadDiagnostic();
}

// --------------------------------------------------------------------------- //
//  PERSONNAGES
// --------------------------------------------------------------------------- //
const CF = ["id", "name", "age", "role", "moral_limits", "personality", "appearance", "scenario",
            "greeting", "system_prompt", "image_prompt", "locked_tags", "krea_token", "voice_transcript",
            "visual_style"];

const CREATOR_VISUAL_STYLES = ["realistic", "anime", "cartoon"];
let activeCreatorStyle = "realistic";
const creatorDrafts = { realistic: null, anime: null, cartoon: null };

function normalizeCreatorStyle(value) {
  return CREATOR_VISUAL_STYLES.includes(value) ? value : "realistic";
}

function creatorStyleLabelKey(style) {
  return `char.visual_style.${normalizeCreatorStyle(style)}_title`;
}

function captureCreatorDraft() {
  const config = {};
  for (const f of CONFIG_FIELDS) {
    config[f.key] = {
      value: ($(`#cg-${f.key}`) || {}).value || "",
      custom: ($(`#cg-${f.key}-custom`) || {}).value || "",
    };
  }
  const form = {};
  for (const f of CF) form[f] = ($(`#f-${f}`) || {}).value || "";
  form.visual_style = activeCreatorStyle;
  return {
    brief: ($("#cg-brief") || {}).value || "",
    name: ($("#cg-name") || {}).value || "",
    age: ($("#cg-age") || {}).value || "25",
    config, form,
    formVisible: ($("#cg-form") || {}).style.display !== "none",
    kreaForcePhysical: !!($("#f-krea_force_physical") || {}).checked,
    avatar: currentAvatar || "",
  };
}

function clearCreatorWorkspace(style, showForm = false) {
  const normalized = normalizeCreatorStyle(style);
  if ($("#cg-brief")) $("#cg-brief").value = "";
  if ($("#cg-name")) $("#cg-name").value = "";
  if ($("#cg-age")) $("#cg-age").value = "25";
  if ($("#cg-age-val")) $("#cg-age-val").textContent = "25";
  for (const f of CONFIG_FIELDS) {
    const select = $(`#cg-${f.key}`);
    const custom = $(`#cg-${f.key}-custom`);
    if (select) select.value = "";
    if (custom) { custom.value = ""; custom.style.display = "none"; }
  }
  const empty = {};
  for (const f of CF) empty[f] = "";
  empty.visual_style = normalized;
  fillForm(empty);
  currentAvatar = "";
  if ($("#cg-form")) $("#cg-form").style.display = showForm ? "block" : "none";
  if ($("#cg-status")) $("#cg-status").textContent = "";
  if ($("#cg-save-status")) $("#cg-save-status").textContent = "";
  refreshAllThumbs();
}

function restoreCreatorDraft(draft, style) {
  const normalized = normalizeCreatorStyle(style);
  if (!draft) return clearCreatorWorkspace(normalized, false);
  if ($("#cg-brief")) $("#cg-brief").value = draft.brief || "";
  if ($("#cg-name")) $("#cg-name").value = draft.name || "";
  if ($("#cg-age")) $("#cg-age").value = draft.age || "25";
  if ($("#cg-age-val")) $("#cg-age-val").textContent = draft.age || "25";
  for (const f of CONFIG_FIELDS) {
    const saved = (draft.config || {})[f.key] || {};
    const select = $(`#cg-${f.key}`);
    const custom = $(`#cg-${f.key}-custom`);
    if (select) select.value = saved.value || "";
    if (custom) {
      custom.value = saved.custom || "";
      custom.style.display = saved.value === "custom" ? "block" : "none";
    }
  }
  fillForm({ ...(draft.form || {}), visual_style: normalized });
  const kfp = $("#f-krea_force_physical");
  if (kfp) kfp.checked = draft.kreaForcePhysical !== false;
  currentAvatar = draft.avatar || "";
  if ($("#cg-form")) $("#cg-form").style.display = draft.formVisible ? "block" : "none";
  refreshAllThumbs();
}

function refreshCreatorStyleUI() {
  document.querySelectorAll("[data-creator-style]").forEach((btn) => {
    const active = btn.dataset.creatorStyle === activeCreatorStyle;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  const panel = document.querySelector(".creator-panel");
  if (panel) panel.dataset.creatorStyleActive = activeCreatorStyle;
  const current = $("#cg-style-current");
  if (current) {
    current.dataset.i18n = creatorStyleLabelKey(activeCreatorStyle);
    current.textContent = window.t(creatorStyleLabelKey(activeCreatorStyle));
  }
  const hidden = $("#f-visual_style");
  if (hidden) hidden.value = activeCreatorStyle;
}

async function activateCreatorStyle(style, { capture = true, restore = true } = {}) {
  const normalized = normalizeCreatorStyle(style);
  if (capture && activeCreatorStyle) creatorDrafts[activeCreatorStyle] = captureCreatorDraft();
  activeCreatorStyle = normalized;
  refreshCreatorStyleUI();
  await loadOptionPreviews();
  if (restore) restoreCreatorDraft(creatorDrafts[normalized], normalized);
}


// Physical configurator: each field is a list of [value, label] options
const CONFIG_FIELDS = [
  { key: "genre", labelKey: "char.config.genre_label", opts: [
    ["female", "char.config.genre.female"],
    ["male", "char.config.genre.male"],
    ["nonbinary", "char.config.genre.nonbinary"],
    ["transfemale", "char.config.genre.transfemale"],
    ["transmale", "char.config.genre.transmale"],
    ["genderfluid", "char.config.genre.genderfluid"],
    ["agender", "char.config.genre.agender"],
    ["androgynous", "char.config.genre.androgynous"],
    ["intersex", "char.config.genre.intersex"],
  ] },
  { key: "origine", labelKey: "char.config.origine_label", opts: [
    ["european", "char.config.origine.european"],
    ["african", "char.config.origine.african"],
    ["asian", "char.config.origine.asian"],
    ["latina", "char.config.origine.latina"],
    ["middleeastern", "char.config.origine.middleeastern"],
    ["indian", "char.config.origine.indian"],
    ["mixed", "char.config.origine.mixed"],
    ["islander", "char.config.origine.islander"],
    ["native", "char.config.origine.native"],
    ["slavic", "char.config.origine.slavic"],
    ["nordic", "char.config.origine.nordic"],
    ["mediterranean", "char.config.origine.mediterranean"],
  ] },
  { key: "corps", labelKey: "char.config.corps_label", opts: [
    ["slim", "char.config.corps.slim"],
    ["lean", "char.config.corps.lean"],
    ["average", "char.config.corps.average"],
    ["soft", "char.config.corps.soft"],
    ["curvy", "char.config.corps.curvy"],
    ["athletic", "char.config.corps.athletic"],
    ["muscular", "char.config.corps.muscular"],
    ["petite", "char.config.corps.petite"],
    ["tall", "char.config.corps.tall"],
    ["stocky", "char.config.corps.stocky"],
    ["plus", "char.config.corps.plus"],
  ] },
  { key: "poitrine", labelKey: "char.config.poitrine_label", opts: [
    ["flat", "char.config.poitrine.flat"],
    ["small", "char.config.poitrine.small"],
    ["medium", "char.config.poitrine.medium"],
    ["large", "char.config.poitrine.large"],
    ["full", "char.config.poitrine.full"],
    ["broad", "char.config.poitrine.broad"],
    ["defined", "char.config.poitrine.defined"],
  ] },
  { key: "hanches", labelKey: "char.config.hanches_label", opts: [
    ["flat", "char.config.hanches.flat"],
    ["small", "char.config.hanches.small"],
    ["medium", "char.config.hanches.medium"],
    ["round", "char.config.hanches.round"],
    ["large", "char.config.hanches.large"],
    ["wide", "char.config.hanches.wide"],
    ["curvy", "char.config.hanches.curvy"],
  ] },
  { key: "cheveux_couleur", labelKey: "char.config.cheveux_couleur_label", opts: [
    ["black", "char.config.cheveux_couleur.black"],
    ["brown", "char.config.cheveux_couleur.brown"],
    ["blonde", "char.config.cheveux_couleur.blonde"],
    ["red", "char.config.cheveux_couleur.red"],
    ["auburn", "char.config.cheveux_couleur.auburn"],
    ["gray", "char.config.cheveux_couleur.gray"],
    ["white", "char.config.cheveux_couleur.white"],
    ["silver", "char.config.cheveux_couleur.silver"],
    ["blue", "char.config.cheveux_couleur.blue"],
    ["pink", "char.config.cheveux_couleur.pink"],
    ["purple", "char.config.cheveux_couleur.purple"],
    ["green", "char.config.cheveux_couleur.green"],
    ["multicolor", "char.config.cheveux_couleur.multicolor"],
  ] },
  { key: "coiffure", labelKey: "char.config.coiffure_label", opts: [
    ["bald", "char.config.coiffure.bald"],
    ["buzzcut", "char.config.coiffure.buzzcut"],
    ["pixie", "char.config.coiffure.pixie"],
    ["bob", "char.config.coiffure.bob"],
    ["lob", "char.config.coiffure.lob"],
    ["shag", "char.config.coiffure.shag"],
    ["mullet", "char.config.coiffure.mullet"],
    ["undercut", "char.config.coiffure.undercut"],
    ["mohawk", "char.config.coiffure.mohawk"],
    ["afro", "char.config.coiffure.afro"],
    ["braids", "char.config.coiffure.braids"],
    ["cornrows", "char.config.coiffure.cornrows"],
    ["dreadlocks", "char.config.coiffure.dreadlocks"],
    ["ponytail", "char.config.coiffure.ponytail"],
    ["bun", "char.config.coiffure.bun"],
    ["pigtails", "char.config.coiffure.pigtails"],
    ["curly", "char.config.coiffure.curly"],
    ["wavy", "char.config.coiffure.wavy"],
    ["straight", "char.config.coiffure.straight"],
    ["long", "char.config.coiffure.long"],
    ["short", "char.config.coiffure.short"],
    ["medium", "char.config.coiffure.medium"],
    ["layered", "char.config.coiffure.layered"],
    ["bangs", "char.config.coiffure.bangs"],
  ] },
  { key: "orientation", labelKey: "char.config.orientation_label", opts: [
    ["straight", "char.config.orientation.straight"],
    ["gay", "char.config.orientation.gay"],
    ["lesbian", "char.config.orientation.lesbian"],
    ["bisexual", "char.config.orientation.bisexual"],
    ["pansexual", "char.config.orientation.pansexual"],
    ["asexual", "char.config.orientation.asexual"],
    ["queer", "char.config.orientation.queer"],
  ] },
];

function configText(key, vars = {}) { return window.t(key, vars); }

const CUSTOM_FIELDS = new Set(["corps", "poitrine", "hanches"]);  // option « Personnalisé… »
let optionPreviews = {};                                          // {field:{gender:{value:image}}}

async function loadOptionPreviews() {
  try {
    optionPreviews = await api("/api/config/previews?visual_style=" + encodeURIComponent(activeCreatorStyle));
  } catch (e) { optionPreviews = {}; }
  refreshAllThumbs();
}

function currentGender() { return fieldValue("genre") || ""; }

function previewFor(field, value) {
  const g = field === "genre" ? "" : currentGender();
  return (((optionPreviews[field] || {})[g]) || {})[value];
}
function setPreviewLocal(field, value, image) {
  const g = field === "genre" ? "" : currentGender();
  optionPreviews[field] = optionPreviews[field] || {};
  optionPreviews[field][g] = optionPreviews[field][g] || {};
  optionPreviews[field][g][value] = image;
}

function buildConfigurator() {
  const grid = $("#cg-config-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (const f of CONFIG_FIELDS) {
    const sel = el("select", { id: "cg-" + f.key });
    sel.append(el("option", { value: "" }, "—"));
    for (const [v, labelKey] of f.opts) sel.append(el("option", { value: v }, configText(labelKey)));
    if (CUSTOM_FIELDS.has(f.key)) sel.append(el("option", { value: "custom" }, configText("char.config.custom")));

    const custom = el("input", { id: "cg-" + f.key + "-custom",
      placeholder: configText("char.config.custom_placeholder"), style: "display:none; margin-top:4px;" });
    const thumb = el("div", { id: "cg-" + f.key + "-thumb", class: "cg-thumb", style: "display:none;" });

    sel.addEventListener("change", () => {
      custom.style.display = sel.value === "custom" ? "block" : "none";
      if (sel.value === "custom") custom.focus();
      if (f.key === "genre") refreshAllThumbs(); else refreshFieldThumb(f.key);
    });
    custom.addEventListener("input", () => refreshFieldThumb(f.key));

    const head = el("div", { class: "row", style: "gap:6px; align-items:center;" },
      el("label", { style: "flex:1;" }, configText(f.labelKey)),
      el("button", { class: "btn sm ghost", type: "button", title: configText("char.config.preview_open"),
        onclick: () => openPreviewPicker(f.key) }, "🖼️"));
    grid.append(el("div", { style: "flex:1; min-width:150px;" }, head, sel, custom, thumb));
  }
}
buildConfigurator();

function relocalizeConfigurator() {
  const previous = Object.fromEntries(CONFIG_FIELDS.map((f) => [
    f.key,
    {
      value: ($("#cg-" + f.key) || {}).value || "",
      custom: ($("#cg-" + f.key + "-custom") || {}).value || "",
    },
  ]));
  buildConfigurator();
  for (const f of CONFIG_FIELDS) {
    const saved = previous[f.key];
    const select = $("#cg-" + f.key);
    const custom = $("#cg-" + f.key + "-custom");
    if (!select || !saved) continue;
    select.value = saved.value;
    if (custom) {
      custom.value = saved.custom;
      custom.style.display = saved.value === "custom" ? "block" : "none";
    }
  }
  refreshAllThumbs();
}
document.addEventListener("amiorai:lang-changed", relocalizeConfigurator);

// Les panneaux créés dynamiquement ne portent pas d'attribut data-i18n.
// Les reconstruire à chaud évite les reliquats de français (ex. bouton Envoyer)
// après un changement de langue, sans perdre un brouillon en cours.
let _chatLanguageRefresh = false;
async function relocalizeOpenChat() {
  if (_chatLanguageRefresh || !activeChat || !$("#chat-pane")) return;
  _chatLanguageRefresh = true;
  const draft = $("#composer-input")?.value || "";
  try {
    const data = await api("/api/chat?id=" + encodeURIComponent(activeChat));
    chatMembers = data.members || [];
    await renderChatPane(data);
    const composer = $("#composer-input");
    if (composer) composer.value = draft;
    // La liste peut contenir le compteur de groupe traduit.
    await loadChats();
  } catch (err) {
    console.warn("[i18n] Impossible de relocaliser la conversation ouverte", err);
  } finally {
    _chatLanguageRefresh = false;
  }
}
document.addEventListener("amiorai:lang-changed", () => { void relocalizeOpenChat(); });

function fieldValue(key) {
  const sel = $("#cg-" + key);
  if (!sel) return "";
  if (sel.value === "custom") return ($("#cg-" + key + "-custom") || {}).value.trim() || "";
  return sel.value || "";
}

function refreshFieldThumb(key) {
  const box = $("#cg-" + key + "-thumb");
  if (!box) return;
  const v = fieldValue(key);
  const img = v ? previewFor(key, v) : null;
  box.innerHTML = "";
  box.style.display = img ? "block" : "none";
  if (img) {
    box.append(el("img", { class: "genimg", src: imgUrl(img) }));
    box.append(el("span", { class: "cg-thumb-tag" }, configText("char.config.preview_selected")));
  }
}
function refreshAllThumbs() { for (const f of CONFIG_FIELDS) refreshFieldThumb(f.key); }

function chooseValue(field, v) {
  const sel = $("#cg-" + field);
  if (!sel) return;
  sel.value = v;
  sel.dispatchEvent(new Event("change"));
  toast(window.t("char.toasts.option_selected", { option: v }));
}

// --- Sélecteur visuel d'aperçus (pagination, adapté au genre) ---
function openPreviewPicker(field) {
  const f = CONFIG_FIELDS.find((x) => x.key === field);
  const opts = f.opts.filter(([v]) => v && v !== "custom");
  const per = 12; let page = 0;
  const gLabel = field === "genre" ? "" :
    (currentGender() ? " (" + configText((CONFIG_FIELDS[0].opts.find((o) => o[0] === currentGender()) || ["", currentGender()])[1]) + ")" : " (" + configText("char.config.preview_generic") + ")");
  const grid = el("div", { class: "pick-grid" });
  const pager = el("div", { class: "row", style: "justify-content:center; gap:8px; margin-top:8px;" });
  let close;

  function genOne(v, btn, box, card) {
    return (async () => {
      const t = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = await api("/api/config/preview", "POST",
          { field, value: v, gender: field === "genre" ? "" : currentGender(),
            visual_style: activeCreatorStyle, regen: true });
        setPreviewLocal(field, v, res.image);
        box.innerHTML = ""; box.append(el("img", { src: imgUrl(res.image) }));
        btn.textContent = "↻";
        refreshFieldThumb(field);
      } catch (e) { toast(e.message, true); btn.textContent = t; }
      finally { btn.disabled = false; }
    })();
  }

  async function genAll(btn) {
    const missing = opts.filter(([v]) => !previewFor(field, v));
    if (!missing.length) return toast(window.t("char.preview.all_exist"));
    btn.disabled = true; const t = btn.textContent;
    for (let i = 0; i < missing.length; i++) {
      btn.innerHTML = `<span class="spinner"></span> ${i + 1}/${missing.length}`;
      try {
        const res = await api("/api/config/preview", "POST",
          { field, value: missing[i][0], gender: field === "genre" ? "" : currentGender(),
            visual_style: activeCreatorStyle });
        setPreviewLocal(field, missing[i][0], res.image);
      } catch (e) { toast(e.message, true); break; }
      render();
    }
    btn.disabled = false; btn.textContent = t;
    refreshFieldThumb(field);
  }

  function render() {
    grid.innerHTML = "";
    const chosen = fieldValue(field);
    const slice = opts.slice(page * per, page * per + per);
    for (const [v, lab] of slice) {
      const img = previewFor(field, v);
      const box = el("div", { class: "pick-thumb" });
      if (img) box.append(el("img", { src: imgUrl(img) }));
      else box.append(el("span", { class: "hint" }, configText("char.config.preview_missing")));
      const genBtn = el("button", { class: "btn sm ghost", title: configText("char.config.preview_generate_one") }, img ? "↻" : configText("char.config.preview_generate_short"));
      const card = el("div", { class: "pick-card" + (v === chosen ? " selected" : "") }, box,
        el("div", { class: "pick-name" }, configText(lab)),
        el("div", { class: "row", style: "gap:4px; justify-content:center;" },
          el("button", { class: "btn sm", onclick: () => { chooseValue(field, v); close(); } }, configText("char.config.preview_choose")),
          genBtn));
      genBtn.addEventListener("click", () => genOne(v, genBtn, box, card));
      grid.append(card);
    }
    pager.innerHTML = "";
    const pages = Math.ceil(opts.length / per);
    if (pages > 1) {
      pager.append(
        el("button", { class: "btn sm ghost", onclick: () => { if (page > 0) { page--; render(); } } }, "‹"),
        el("span", { class: "hint", style: "align-self:center;" }, `${page + 1} / ${pages}`),
        el("button", { class: "btn sm ghost", onclick: () => { if (page < pages - 1) { page++; render(); } } }, "›"));
    }
  }

  const genAllBtn = el("button", { class: "btn sm" }, configText("char.config.preview_generate_missing"));
  genAllBtn.addEventListener("click", () => genAll(genAllBtn));
  close = overlay(el("div", { class: "modal-card wide" },
    el("h3", {}, configText("char.config.preview_title", { field: configText(f.labelKey), gender: gLabel })),
    el("p", { class: "hint" }, configText("char.config.preview_hint")),
    genAllBtn, grid, pager));
  render();
}

document.querySelectorAll("[data-creator-style]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (btn.dataset.creatorStyle === activeCreatorStyle) return;
    try {
      await activateCreatorStyle(btn.dataset.creatorStyle);
      toast(window.t("char.visual_style.switched", { style: window.t(creatorStyleLabelKey(activeCreatorStyle)) }));
    } catch (e) { toast(e.message, true); }
  });
});
refreshCreatorStyleUI();

// Slider d'âge : met à jour l'affichage
(function () {
  const a = $("#cg-age"), out = $("#cg-age-val");
  if (a && out) a.addEventListener("input", () => { out.textContent = a.value; });
})();

$("#cg-generate").addEventListener("click", async () => {
  const brief = $("#cg-brief").value.trim();
  if (!brief) return toast(window.t("char.toasts.describe_brief"), true);
  const status = $("#cg-status");
  status.innerHTML = '<span class="spinner"></span> le LLM imagine le personnage…';
  $("#cg-generate").disabled = true;
  const attrs = {};
  for (const f of CONFIG_FIELDS) attrs[f.key] = fieldValue(f.key);
  attrs.age = ($("#cg-age") || {}).value || "";
  attrs.name = ($("#cg-name") || {}).value.trim();
  attrs.visual_style = activeCreatorStyle;
  try {
    const data = await api("/api/character/generate", "POST", { brief, attrs });
    fillForm({ ...data, id: "" });
    $("#cg-form").style.display = "block";
    status.textContent = window.t("char.toasts.sheet_ready");
  } catch (e) {
    status.textContent = "";
    toast(e.message, true);
  } finally {
    $("#cg-generate").disabled = false;
  }
});

function fillForm(c) {
  c = c || {};
  c.visual_style = normalizeCreatorStyle(c.visual_style || activeCreatorStyle);
  for (const f of CF) {
    const node = $("#f-" + f);
    if (node) node.value = c[f] || "";
  }
  // Toggle Krea 2 : coché par défaut (1), décoché uniquement si explicitement 0
  const kfp = $("#f-krea_force_physical");
  if (kfp) kfp.checked = !(c.krea_force_physical === 0 || c.krea_force_physical === "0");
  $("#cg-avatar-preview").innerHTML = c.avatar
    ? `<img src="${imgUrl(c.avatar)}" style="max-width:240px;border-radius:12px;">` : "";
  const saved = !!c.id;
  $("#cg-avatar-options").style.display = saved ? "block" : "none";
  const emotEl = $("#cg-emotions"); if (emotEl) emotEl.style.display = saved ? "block" : "none";
  $("#cg-memory").style.display = "block";
  $("#cg-memory-structured").style.display = saved ? "block" : "none";
  $("#cg-export").style.display = saved ? "block" : "none";
  const voiceBtn = $("#cg-voice-upload-btn");
  if (voiceBtn) voiceBtn.disabled = !saved;
  if (saved) {
    loadMemory(c.id);
    loadCharMemory(c.id);
    loadEmotionGrid(c.id);
    renderVoicePreview(c.voice_sample);
  } else {
    $("#mem-list").innerHTML =
      '<div class="hint">Enregistre d\'abord le personnage pour ajouter des souvenirs.</div>';
    clearCharMemoryForm();
    const eg = $("#emotion-grid"); if (eg) eg.innerHTML = "";
    renderVoicePreview(null, true);
  }
}

function renderVoicePreview(voiceSample, notSaved) {
  const box = $("#cg-voice-preview");
  if (!box) return;
  box.innerHTML = "";
  if (notSaved) {
    box.append(el("div", { class: "hint" }, window.t("char.voice.save_first_hint")));
  } else if (voiceSample) {
    box.append(
      el("div", { class: "hint", style: "margin-bottom:4px;" }, window.t("char.voice.current")),
      el("audio", { controls: true, src: "/audio/" + voiceSample, style: "width:100%; max-width:320px;" })
    );
  } else {
    box.append(el("div", { class: "hint" }, window.t("char.voice.empty")));
  }
}

function readForm() {
  const o = {};
  for (const f of CF) o[f] = ($("#f-" + f) || {}).value || "";
  o.visual_style = activeCreatorStyle;
  const kfp = $("#f-krea_force_physical");
  o.krea_force_physical = (kfp && !kfp.checked) ? "0" : "1";
  if (currentAvatar) o.avatar = currentAvatar;
  return o;
}

function resetCharacterForm() {
  // Réinitialise tous les champs du formulaire et l'ID active.
  // Ne supprime jamais de données en base.
  const empty = {};
  for (const f of CF) empty[f] = "";
  fillForm(empty);   // remplit avec des chaînes vides, id absent → mode création
  currentAvatar = "";
  const status = $("#cg-save-status");
  if (status) status.textContent = "";
  // Reset aussi le configurateur physique de CE créateur uniquement.
  for (const f of (CONFIG_FIELDS || [])) {
    const select = $(`#cg-${f.key}`);
    const custom = $(`#cg-${f.key}-custom`);
    if (select) select.value = "";
    if (custom) { custom.value = ""; custom.style.display = "none"; }
  }
  const hiddenStyle = $("#f-visual_style");
  if (hiddenStyle) hiddenStyle.value = activeCreatorStyle;
  refreshAllThumbs();
  creatorDrafts[activeCreatorStyle] = null;
}

const _cgNewChar = $("#cg-new-char");
if (_cgNewChar) _cgNewChar.addEventListener("click", () => {
  const hasId  = !!($("#f-id") || {}).value;
  const isDirty = CF.some(f => {
    const node = $(`#f-${f}`);
    return node && node.value.trim() !== "";
  });
  if (isDirty || hasId) {
    if (!confirm(window.t("char.reset_confirm"))) return;
  }
  resetCharacterForm();
  $("#cg-form").style.display = "block";
  toast(window.t("char.toasts.form_reset"));
});


// ---- Prompts utilitaires de style/personnalité ----
const PROMPT_UTIL_MARKER_START = "\n\n[AMIORAI STYLE INSTRUCTIONS]\n";
const PROMPT_UTIL_MARKER_END = "\n[/AMIORAI STYLE INSTRUCTIONS]";
const PROMPT_UTIL_LANGUAGES = [
  ["French", "You only speak French. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["English", "You only speak English. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["Italiano", "You only speak Italian. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["Español", "You only speak Spanish. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["Deutsch", "You only speak German. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["Portuguese", "You only speak Portuguese. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["Nederlands", "You only speak Dutch. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["日本語", "You only speak Japanese. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["한국어", "You only speak Korean. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
  ["中文", "You only speak Chinese. Keep the character voice natural and never switch language unless the user explicitly asks for a translation."],
];
const PROMPT_UTIL_STYLES = [
  ["Gen Z", "Use a relaxed Gen Z talking style: playful, spontaneous, modern slang, short punchy reactions, but keep it readable."],
  ["Soft", "Use a soft, warm, reassuring writing style with gentle emotional nuance."],
  ["Romantique", "Use a romantic and affectionate style, tender but not exaggerated."],
  ["Cinematic", "Use a cinematic roleplay style with vivid sensory details, body language, atmosphere, and natural dialogue."],
  ["Poetic", "Use a slightly poetic style with elegant metaphors, without becoming obscure or too long."],
  ["Humour sec", "Use dry humor and subtle teasing when appropriate, without breaking character."],
  ["Taquin", "Use a playful teasing style, charming and light, never mean."],
  ["Court", "Keep replies concise: one to three short paragraphs unless the scene truly needs more."],
  ["Very expressive", "Make emotions more visible through tone, gestures, facial expressions, and small physical reactions."],
  ["SMS", "Use a casual texting style with shorter sentences and natural pauses, as if chatting on a phone."],
  ["Emoji +", "Use occasional emojis when it fits the character and the scene, without overusing them."],
  ["Sans emoji", "Do not use emojis unless the user explicitly asks for them."],
];

function splitPromptUtilBlock(text) {
  const raw = text || "";
  const start = raw.indexOf(PROMPT_UTIL_MARKER_START);
  if (start < 0) return { before: raw.trimEnd(), lines: [], after: "" };
  const afterStart = start + PROMPT_UTIL_MARKER_START.length;
  const end = raw.indexOf(PROMPT_UTIL_MARKER_END, afterStart);
  if (end < 0) {
    return { before: raw.slice(0, start).trimEnd(), lines: raw.slice(afterStart).split("\n").map(x => x.trim()).filter(Boolean), after: "" };
  }
  return {
    before: raw.slice(0, start).trimEnd(),
    lines: raw.slice(afterStart, end).split("\n").map(x => x.trim()).filter(Boolean),
    after: raw.slice(end + PROMPT_UTIL_MARKER_END.length).trimStart(),
  };
}

function joinPromptUtilBlock(parts) {
  let out = parts.before || "";
  if (parts.lines.length) out += PROMPT_UTIL_MARKER_START + parts.lines.join("\n") + PROMPT_UTIL_MARKER_END;
  if (parts.after) out += (out ? "\n\n" : "") + parts.after;
  return out.trim();
}

function addPromptUtilityInstruction(kind, instruction) {
  const ta = $("#f-system_prompt");
  if (!ta || !instruction) return;
  const parts = splitPromptUtilBlock(ta.value || "");
  const prefix = kind === "language" ? "- [language] " : "- [style] ";
  let lines = parts.lines.filter(line => kind !== "language" || !line.startsWith("- [language] "));
  const line = prefix + instruction.trim();
  if (!lines.includes(line)) lines.push(line);
  ta.value = joinPromptUtilBlock({ ...parts, lines });
  ta.focus();
  toast(kind === "language" ? "Language added to system prompt." : "Style added to system prompt.");
}

function clearPromptUtilityInstructions() {
  const ta = $("#f-system_prompt");
  if (!ta) return;
  const parts = splitPromptUtilBlock(ta.value || "");
  ta.value = ((parts.before || "") + (parts.after ? "\n\n" + parts.after : "")).trim();
  toast("Utility styles removed from system prompt.");
}

function renderPromptUtilityButtons() {
  const langBox = $("#prompt-util-languages");
  const styleBox = $("#prompt-util-styles");
  if (!langBox || !styleBox) return;
  langBox.innerHTML = "";
  styleBox.innerHTML = "";
  for (const [label, instruction] of PROMPT_UTIL_LANGUAGES) {
    langBox.append(el("button", { class: "btn sm ghost", type: "button", onclick: () => addPromptUtilityInstruction("language", instruction) }, label));
  }
  for (const [label, instruction] of PROMPT_UTIL_STYLES) {
    styleBox.append(el("button", { class: "btn sm ghost", type: "button", onclick: () => addPromptUtilityInstruction("style", instruction) }, label));
  }
  const customAdd = $("#prompt-util-custom-add");
  if (customAdd) customAdd.addEventListener("click", () => {
    const input = $("#prompt-util-custom");
    const val = (input && input.value || "").trim();
    if (!val) return toast("Write a custom instruction.", true);
    addPromptUtilityInstruction("style", val);
    input.value = "";
  });
  const clearBtn = $("#prompt-util-clear");
  if (clearBtn) clearBtn.addEventListener("click", clearPromptUtilityInstructions);
}
renderPromptUtilityButtons();

let currentAvatar = "";

$("#cg-avatar").addEventListener("click", async () => {
  const id = $("#f-id").value || null;
  const fallback = $("#f-image_prompt").value.trim();
  if (!id && !fallback) return toast(window.t("char.validation.image_prompt_required"), true);
  let proposed = fallback;
  try {
    const dr = await api("/api/character/avatar", "POST",
      { id, image_prompt: fallback, visual_style: activeCreatorStyle, dry_run: true });
    proposed = dr.prompt || fallback;
  } catch (e) { /* on garde le fallback */ }
  const edited = await promptDialog(proposed, window.t("char.avatar.review_title"));
  if (edited === null) return;
  const status = $("#cg-save-status");
  status.innerHTML = `<span class="spinner"></span> ${window.t("char.avatar.generating")}`;
  $("#cg-avatar").disabled = true;
  try {
    const data = await api("/api/character/avatar", "POST",
      { id, image_prompt: edited, prompt: edited, visual_style: activeCreatorStyle });
    currentAvatar = data.image;
    $("#cg-avatar-preview").innerHTML =
      `<img src="${imgUrl(data.image)}" style="max-width:240px;border-radius:12px;">`;
    status.textContent = window.t("char.toasts.avatar_generated");
  } catch (e) {
    status.textContent = "";
    toast(e.message, true);
  } finally {
    $("#cg-avatar").disabled = false;
  }
});

$("#cg-save").addEventListener("click", async () => {
  const data = readForm();
  if (!data.name.trim()) return toast(window.t("char.validation.name_required"), true);
  try {
    const saved = await api("/api/character/save", "POST", data);
    $("#f-id").value = saved.id;
    currentAvatar = saved.avatar || "";
    $("#cg-avatar-options").style.display = "block";
    $("#cg-memory").style.display = "block";
    $("#cg-export").style.display = "block";
    loadMemory(saved.id);
    toast(window.t("char.toasts.saved"));
    loadCharacters();
  } catch (e) { toast(e.message, true); }
});

// ---- Options avatar (perso enregistré) ----
function showAvatar(img, statusMsg) {
  currentAvatar = currentAvatar || img;
  $("#cg-avatar-preview").innerHTML =
    `<img src="${imgUrl(img)}" style="max-width:240px;border-radius:12px;display:block;margin-bottom:8px;">`;
  const setBtn = el("button", { class: "btn sm", onclick: async () => {
    try { await api("/api/character/set_avatar", "POST", { id: $("#f-id").value, image: img });
      currentAvatar = img; toast(window.t("char.toasts.avatar_set")); loadCharacters(); }
    catch (e) { toast(e.message, true); }
  } }, window.t("char.avatar.set_primary"));
  $("#cg-avatar-preview").append(setBtn);
  if (statusMsg) $("#cg-avatar-status").textContent = statusMsg;
}

async function avatarGen(opts, btn) {
  const id = $("#f-id").value;
  if (!id) return toast(window.t("char.validation.save_first"), true);
  const status = $("#cg-avatar-status");
  let proposed = "";
  // canonical_profile : pour les rerolls sans variante (= rerolls de création), on demande
  // le cadrage hanches->tête. Les variantes expression/tenue/fond restent libres.
  const isCanonical = !opts.variant;
  try {
    proposed = (await api("/api/character/avatar", "POST",
      { id, ...opts, dry_run: true, canonical_profile: isCanonical })).prompt;
  } catch (e) { return toast(e.message, true); }
  const edited = await promptDialog(proposed, window.t("char.avatar.review_title"));
  if (edited === null) return;
  status.innerHTML = '<span class="spinner"></span> ComfyUI…';
  if (btn) btn.disabled = true;
  try {
    const res = await api("/api/character/avatar", "POST",
      { id, ...opts, prompt: edited, canonical_profile: isCanonical });
    showAvatar(res.image, window.t("char.avatar.seed", { seed: res.seed }));
  } catch (e) { status.textContent = ""; toast(e.message, true); }
  finally { if (btn) btn.disabled = false; }
}

$("#cg-reroll").addEventListener("click", (e) => avatarGen({ keep_seed: false }, e.target));
$("#cg-keepseed").addEventListener("click", (e) => avatarGen({ keep_seed: true }, e.target));
$("#cg-variant-go").addEventListener("click", (e) => {
  const v = $("#cg-variant").value;
  if (!v) return toast(window.t("char.avatar.variant_required"), true);
  avatarGen({ variant: v }, e.target);
});

$("#cg-export-btn").addEventListener("click", () => {
  const id = $("#f-id").value;
  if (id) window.location.href = "/api/share/character/export?id=" + encodeURIComponent(id);
});

// --- Import d’un personnage partagé (.amiorchar ou ancien JSON) ---
const _charImportBtn = $("#char-import-btn");
if (_charImportBtn) _charImportBtn.addEventListener("click", () => $("#char-import-input").click());
const _charImportInput = $("#char-import-input");
if (_charImportInput) _charImportInput.addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const res = await uploadShareFile("/api/share/character/import", file);
    toast(window.t("char.import.success", { name: res.name }));
    await loadCharacters();
  } catch (err) {
    toast(window.t("char.import.failed", { error: err.message }), true);
  } finally {
    e.target.value = "";  // permet de réimporter le même fichier si besoin
  }
});

// ---- Memory ----
async function loadMemory(characterId) {
  const list = $("#mem-list");
  list.innerHTML = "";
  let items;
  try { items = await api("/api/memory?character_id=" + characterId); }
  catch (e) { return; }
  if (!items.length) { list.innerHTML = `<div class="hint">${window.t("char.memory.empty")}</div>`; return; }
  for (const m of items) {
    list.append(el("div", { class: "row", style: "align-items:flex-start; margin-bottom:6px;" },
      el("span", { style: "font-size:11px; padding:2px 8px; border-radius:10px; border:1px solid var(--line); color:var(--accent);" },
        m.kind === "long" ? window.t("char.memory.long") : window.t("char.memory.short")),
      el("span", { style: "flex:1;" }, m.content),
      el("button", { class: "btn sm danger", onclick: async () => {
        await api("/api/memory/delete", "POST", { id: m.id }); loadMemory(characterId);
      } }, "✕")
    ));
  }
}

function clearCharMemoryForm() {
  for (const id of ["cm-likes","cm-dislikes","cm-events","cm-prefs","cm-rel_history",
                     "cm-topic","cm-rel_state"])
    { const n = $("#" + id); if (n) n.value = ""; }
}
async function loadCharMemory(charId) {
  try {
    const m = await api("/api/char_memory?character_id=" + charId);
    const setTA = (id, val) => { const n = $("#" + id); if (n) n.value = Array.isArray(val) ? val.join("\n") : (val || ""); };
    setTA("cm-likes", m.likes); setTA("cm-dislikes", m.dislikes);
    setTA("cm-events", m.important_events); setTA("cm-prefs", m.user_preferences);
    setTA("cm-rel_history", m.relationship_history);
    setTA("cm-topic", m.last_topic);
    setTA("cm-rel_state", m.current_relationship_state);
  } catch (e) { clearCharMemoryForm(); }
}
const _cmSave = $("#cm-save");
if (_cmSave) _cmSave.addEventListener("click", async () => {
  const id = $("#f-id").value;
  if (!id) return toast(window.t("char.validation.save_first"), true);
  const lines = (sel) => (sel ? sel.value.split("\n").map(x => x.trim()).filter(Boolean) : []);
  try {
    await api("/api/char_memory/save", "POST", {
      character_id: id,
      likes: lines($("#cm-likes")), dislikes: lines($("#cm-dislikes")),
      important_events: lines($("#cm-events")), user_preferences: lines($("#cm-prefs")),
      relationship_history: ($("#cm-rel_history") || {}).value || "",
      last_topic: ($("#cm-topic") || {}).value || "",
      current_relationship_state: ($("#cm-rel_state") || {}).value || "",
    });
    toast(window.t("char.toasts.memory_structured_saved"));
  } catch (e) { toast(e.message, true); }
});

$("#mem-add").addEventListener("click", async () => {
  const id = $("#f-id").value, content = $("#mem-input").value.trim();
  if (!id || !content) return;
  try { await api("/api/memory/add", "POST", { character_id: id, kind: $("#mem-kind").value, content });
    $("#mem-input").value = ""; loadMemory(id); }
  catch (e) { toast(e.message, true); }
});

$("#mem-summarize").addEventListener("click", async (e) => {
  const id = $("#f-id").value;
  if (!id) return;
  e.target.disabled = true; e.target.textContent = window.t("char.memory.summarizing");
  try { await api("/api/memory/summarize", "POST", { character_id: id }); loadMemory(id);
    toast(window.t("char.memory.compacted")); }
  catch (err) { toast(err.message, true); }
  finally { e.target.disabled = false; e.target.textContent = window.t("char.memory.summarize_btn"); }
});

async function loadCharacters() {
  const grid = $("#char-grid");
  grid.innerHTML = "";
  let chars;
  try { chars = await api("/api/characters"); }
  catch (e) { return toast(e.message, true); }
  if (!chars.length) {
    grid.append(el("div", { class: "empty", style: "grid-column:1/-1" }, window.t("char.empty")));
    return;
  }
  for (const c of chars) {
    const av = el("div", { class: "av" });
    if (c.avatar) av.style.backgroundImage = `url(${imgUrl(c.avatar)})`;
    else av.textContent = window.t("char.no_avatar");
    grid.append(el("div", { class: "charcard" },
      av,
      el("div", { class: "body" },
        el("div", { class: "nm" }, c.name),
        el("div", { class: `char-style-badge ${normalizeCreatorStyle(c.visual_style)}` },
          window.t(creatorStyleLabelKey(c.visual_style))),
        el("div", { class: "acts" },
          el("button", { class: "btn sm", onclick: () => startChat(c.id) }, window.t("char.chat_btn")),
          el("button", { class: "btn sm ghost", onclick: () => editCharacter(c) }, window.t("common.edit")),
          el("button", { class: "btn sm ghost", onclick: () => {
            window.location.href = "/api/share/character/export?id=" + encodeURIComponent(c.id);
          } }, window.t("char.share_btn")),
          el("button", { class: "btn sm danger", onclick: () => delCharacter(c.id) }, "✕"),
        )
      )
    ));
  }
}

async function editCharacter(c) {
  await activateCreatorStyle(c.visual_style || "realistic", { capture: true, restore: false });
  fillForm(c);
  currentAvatar = c.avatar || "";
  $("#cg-form").style.display = "block";
  $("#cg-status").textContent = window.t("char.editing", { name: c.name });
  creatorDrafts[activeCreatorStyle] = captureCreatorDraft();
  $("#view-characters").scrollIntoView({ behavior: "smooth" });
}

async function delCharacter(id) {
  if (!confirm(window.t("char.delete_confirm"))) return;
  try { await api("/api/character/delete", "POST", { id }); loadCharacters(); }
  catch (e) { toast(e.message, true); }
}

async function startChat(charId) {
  try {
    const { id } = await api("/api/chat/create", "POST", { members: [charId] });
    switchView("chats");
    await loadChats();
    openChat(id);
  } catch (e) { toast(e.message, true); }
}

// --------------------------------------------------------------------------- //
//  CONVERSATIONS
// --------------------------------------------------------------------------- //
let activeChat = null;
let activeResponder = null;
let chatMembers = [];
let currentChatIsGroup = false;

async function loadChats() {
  const list = $("#chat-list");
  list.innerHTML = "";
  let chats;
  try { chats = await api("/api/chats"); }
  catch (e) { return toast(e.message, true); }
  if (!chats.length) {
    list.append(el("div", { class: "empty" }, window.t("chat.empty_runtime")));
    return;
  }
  for (const ch of chats) {
    const item = el("div", { class: "chatitem" + (ch.id === activeChat ? " active" : ""),
      onclick: () => openChat(ch.id) },
      el("div", { class: "t" }, ch.title || window.t("chat.default_title")),
      ch.is_group ? el("div", { class: "grouptag" }, window.t("chat.group_tag", { count: ch.members.length })) : null,
      el("div", { class: "l" }, ch.last ? ch.last.content : "—"),
    );
    list.append(item);
  }
}

async function openChat(id) {
  if (typeof stopSpeaking === "function") stopSpeaking();
  activeChat = id;
  activeResponder = null;
  await loadChats();
  let data;
  try { data = await api("/api/chat?id=" + id); }
  catch (e) { return toast(e.message, true); }
  chatMembers = data.members;
  renderChatPane(data);
}

function memberName(id) {
  const m = chatMembers.find((x) => x.id === id);
  return m ? m.name : "?";
}

async function renderChatPane(data) {
  const pane = $("#chat-pane");
  pane.innerHTML = "";
  const isGroup = data.chat && data.chat.is_group;
  currentChatIsGroup = !!isGroup;
  chatCharId = (!isGroup && chatMembers.length === 1) ? chatMembers[0].id : null;

  // En-tête
  const headBtns = [
    el("div", { class: "ttl" }, data.chat ? data.chat.title : ""),
    el("span", { id: "scenario-badge", class: "sc-badge", style: "display:none" }, ""),
    el("button", { class: "btn sm ghost", title: window.t("chat.add_character_title"),
      onclick: () => addCharacterToChat() }, "＋"),
    el("button", { class: "btn sm ghost", title: window.t("chat.scenario_title"),
      onclick: () => openScenarioPicker() }, "📖"),
    el("button", { class: "btn sm ghost", title: window.t("chat.memory_update_title"),
      onclick: (e) => updateMemoryFromChat(e.target) }, "🧠"),
  ];
  if (ttsEnabled) {
    const isOn = getChatAutoplay(data.chat.id);
    headBtns.push(el("button", {
      class: "btn sm ghost tts-toggle" + (isOn ? " on" : " off"),
      id: "tts-toggle-btn",
      title: isOn
        ? window.t("chat.tts_on_title")
        : window.t("chat.tts_off_title"),
      onclick: (e) => {
        stopSpeaking();  // coupe immediatement toute lecture/generation en cours
        const next = !getChatAutoplay(data.chat.id);
        setChatAutoplay(data.chat.id, next);
        e.target.classList.toggle("on", next);
        e.target.classList.toggle("off", !next);
        e.target.textContent = next ? "🔊" : "🔇";
        e.target.title = next
          ? window.t("chat.tts_on_title")
          : window.t("chat.tts_off_title");
      },
    }, isOn ? "🔊" : "🔇"));
  }
  headBtns.push(el("button", {
    class: "btn sm ghost", id: "reply-length-toggle-btn",
    title: window.t("chat.reply_length_title"),
    onclick: () => toggleReplyLengthPanel(),
  }, "🎚️"));
  headBtns.push(el("button", {
    class: "btn sm ghost", id: "chat-lora-toggle-btn",
    title: window.t("chat.lora_title"),
    onclick: () => toggleChatLoraPanel(data.chat.id),
  }, "🧬"));
  headBtns.push(el("button", { class: "btn sm danger", onclick: () => deleteChat(data.chat.id) }, "✕"));
  pane.append(el("div", { class: "chathead" }, ...headBtns));
  pane.append(buildReplyLengthPanel());
  pane.append(buildChatLoraPanel(data.chat.id));

  // Zone portrait (solo seulement) + barre humeur
  if (chatCharId) {
    pane.append(el("div", { class: "chat-portrait-wrap" },
      el("div", { id: "chat-portrait", class: "chat-portrait" }),
      el("div", { id: "mood-bar", class: "mood-bar" })
    ));
    const moodState = await loadMoodWidget(chatCharId);
    const emotion = (moodState && moodState.current_emotion)
      || MOOD_TO_EMOTION_JS[moodState && moodState.mood]
      || "calm";
    refreshChatPortrait(chatCharId, emotion);
  }

  const msgs = el("div", { class: "msgs", id: "msgs" });
  for (const m of data.messages) msgs.append(renderMsg(m));
  pane.append(msgs);

  // ... (composer appended below)
  // Après rendu complet, ajuster la visibilité du bouton Continuer
  setTimeout(updateContinueBtnVisibility, 0);

  // Composer
  const composer = el("div", { class: "composer" });
  if (isGroup) {
    const respond = el("div", { class: "respond" });
    respond.append(el("span", { class: "hint", style: "align-self:center" }, window.t("chat.active_members")));
    chatMembers.forEach((m, i) => {
      const isActive = m.active === undefined ? true : !!m.active;
      const chip = el("div", { class: "chip-wrap" });

      const nameBtn = el("button", {
        class: "chip" + (i === 0 ? " active" : "") + (isActive ? "" : " off"),
        title: window.t("chat.chip_hint"),
        onclick: () => {
          activeResponder = m.id;
          $$(".composer .chip").forEach((c) => c.classList.remove("active"));
          nameBtn.classList.add("active");
        },
        ondblclick: async () => {
          const now = !nameBtn.classList.contains("off");
          nameBtn.classList.toggle("off", now);
          try { await api("/api/chat/member_active", "POST",
            { chat_id: activeChat, character_id: m.id, active: !now }); }
          catch (e) { toast(e.message, true); }
        },
      }, m.name);

      // Bouton retirer le personnage de la conversation
      const removeBtn = el("button", { class: "chip-rm", title: window.t("chat.remove_member_title"),
        onclick: async () => {
          if (!confirm(window.t("chat.remove_member_confirm", { name: m.name }))) return;
          try {
            await api("/api/chat/remove_member", "POST",
              { chat_id: activeChat, character_id: m.id });
            openChat(activeChat);
          } catch (e) { toast(e.message, true); }
        }
      }, "×");

      chip.append(nameBtn, removeBtn);
      respond.append(chip);
    });
    activeResponder = chatMembers[0] ? chatMembers[0].id : null;
    composer.append(respond);
  }
  const ta = el("textarea", { placeholder: window.t("chat.input_placeholder"), id: "composer-input" });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  const inrow = el("div", { class: "inrow" }, ta);
  if (whisperEnabled) {
    inrow.append(el("button", { class: "btn ghost mic-btn", id: "mic-btn",
      title: window.t("chat.dictate_title"), onclick: toggleDictation }, "🎙️"));
  }
  inrow.append(el("button", { class: "btn", id: "send-btn", onclick: sendMessage }, window.t("chat.send_btn")));
  if (isGroup) {
    inrow.append(el("button", { class: "btn ghost", id: "react-btn", onclick: reactMessage,
      title: window.t("chat.send_without_message_title") }, window.t("chat.react_btn")));
  }
  composer.append(inrow);
  pane.append(composer);

  msgs.scrollTop = msgs.scrollHeight;
}

// --------------------------------------------------------------------------- //
//  Response length (slider compact dans le chat, panneau repliable)
// --------------------------------------------------------------------------- //
function toggleReplyLengthPanel() {
  const panel = $("#reply-length-panel");
  if (!panel) return;
  panel.style.display = panel.style.display === "none" ? "block" : "none";
}

// ===========================================================================
//  PANNEAU LoRA IMAGE PAR CONVERSATION
// ===========================================================================

function toggleChatLoraPanel(chatId) {
  const p = $("#chat-lora-panel");
  if (!p) return;
  const visible = p.style.display !== "none";
  p.style.display = visible ? "none" : "";
  if (!visible) loadChatLoraPanel(chatId);
}

function buildChatLoraPanel(chatId) {
  const panel = el("div", {
    id:    "chat-lora-panel",
    class: "reply-length-panel",
    style: "display:none; padding:12px 16px; min-width:340px;",
  });
  panel.dataset.chatId = chatId;
  return panel;
}

async function loadChatLoraPanel(chatId) {
  const panel = $("#chat-lora-panel");
  if (!panel) return;
  panel.innerHTML = '<span class="hint">Chargement…</span>';

  let sel, favorites;
  try {
    [sel, favorites] = await Promise.all([
      api(`/api/chat/lora?chat_id=${encodeURIComponent(chatId)}`),
      api("/api/loras"),
    ]);
  } catch (e) {
    panel.innerHTML = `<span class="hint" style="color:var(--danger);">Error: ${e.message}</span>`;
    return;
  }

  const favs = favorites.filter(lo => lo.favorite);
  panel.innerHTML = "";

  // En-tête
  panel.append(el("div", { style: "font-weight:600; margin-bottom:10px; display:flex; align-items:center; gap:8px;" },
    el("span", {}, "🧬 LoRA image — cette conversation"),
    el("span", { class: "hint", style: "margin-left:auto; font-size:11px;" }, "Max 2 LoRA")));

  // Active slots
  const slotBox = el("div", { style: "background:var(--panel-2); border-radius:8px; padding:10px; margin-bottom:12px;" });
  const mkSlot = (label, lora) => {
    const valEl = el("span", { style: "font-family:monospace; font-size:12px; flex:1;" },
      lora ? lora.file : el("em", { style: "color:var(--muted);" }, "None"));
    const clearBtn = lora ? el("button", {
      class: "btn sm ghost", style: "font-size:11px;",
      onclick: async () => {
        const np = label === "Principal" ? null : sel.primary;
        const ns = label === "Secondaire" ? null : sel.secondary;
        sel = await api("/api/chat/lora/set", "POST",
          { chat_id: chatId, primary: np, secondary: ns, apply_once: sel.apply_once });
        loadChatLoraPanel(chatId);
      }
    }, "✕") : null;
    const row = el("div", { class: "lm-meta-row", style: "margin-bottom:4px;" },
      el("span", { class: "lm-family-tag", style: "min-width:70px;" }, label), valEl);
    if (clearBtn) row.append(clearBtn);
    return row;
  };
  slotBox.append(mkSlot("Principal", sel.primary), mkSlot("Secondaire", sel.secondary));

  const applyOnceLabel = el("label", { class: "row", style: "gap:6px; align-items:center; margin-top:6px; font-size:12px;" });
  const applyOnceCb = el("input", { type: "checkbox", style: "width:auto;" });
  if (sel.apply_once) applyOnceCb.checked = true;
  applyOnceCb.addEventListener("change", async () => {
    await api("/api/chat/lora/set", "POST",
      { chat_id: chatId, primary: sel.primary, secondary: sel.secondary, apply_once: applyOnceCb.checked });
  });
  applyOnceLabel.append(applyOnceCb, el("span", {}, "Prochaine image seulement"));
  slotBox.append(applyOnceLabel,
    el("button", { class: "btn sm ghost", style: "margin-top:8px; width:100%;",
      onclick: async () => { await api("/api/chat/lora/clear", "POST", { chat_id: chatId }); loadChatLoraPanel(chatId); }
    }, "🗑 Clear selection"));
  panel.append(slotBox);

  // Favoris
  if (!favs.length) {
    panel.append(el("div", { class: "hint" },
      "No favorite LoRA. Mark LoRAs with ★ on the LoRA page to see them here."));
    return;
  }
  panel.append(el("div", { style: "font-weight:600; font-size:12px; margin-bottom:6px;" }, "★ Favoris"));
  for (const lo of favs) {
    const isPrimary   = sel.primary   && sel.primary.file   === lo.file;
    const isSecondary = sel.secondary && sel.secondary.file === lo.file;
    const famLabel    = (typeof LORA_FAMILY_LABELS !== "undefined" ? LORA_FAMILY_LABELS : {})[lo.family] || lo.family || "?";

    const setPriBtn = el("button", {
      class: "btn sm" + (isPrimary ? " ghost" : ""),
      onclick: async () => {
        if (sel.secondary && sel.secondary.file === lo.file) return toast(window.t("char.avatar_options.already_secondary"), true);
        sel = await api("/api/chat/lora/set", "POST", {
          chat_id: chatId, apply_once: sel.apply_once,
          primary: { file: lo.file, strength: lo.strength || 0.8, clip_strength: lo.clip_strength || 1.0 },
          secondary: sel.secondary,
        });
        loadChatLoraPanel(chatId);
      }
    }, isPrimary ? "✓ Principal" : "Principal");

    const setSecBtn = el("button", {
      class: "btn sm ghost" + (isSecondary ? " lm-card-active" : ""),
      onclick: async () => {
        if (sel.primary && sel.primary.file === lo.file) return toast(window.t("char.avatar_options.already_primary"), true);
        sel = await api("/api/chat/lora/set", "POST", {
          chat_id: chatId, apply_once: sel.apply_once, primary: sel.primary,
          secondary: { file: lo.file, strength: lo.strength || 0.8, clip_strength: lo.clip_strength || 1.0 },
        });
        loadChatLoraPanel(chatId);
      }
    }, isSecondary ? "✓ Secondaire" : "Secondaire");

    panel.append(el("div", { class: "lm-stack-row", style: "margin-bottom:6px; gap:8px;" },
      el("div", { class: "lm-stack-info" },
        el("span", { class: "lm-filename" }, lo.file),
        el("div", { class: "lm-meta-row" },
          el("span", { class: "lm-family-tag" }, famLabel),
          el("span", { class: "lm-strength" }, `⚖ ${lo.strength}`))),
      el("div", { class: "lm-stack-actions" }, setPriBtn, setSecBtn)));
  }
}

function replyLengthLabel(v) {
  if (v <= 125) return "Court";
  if (v <= 425) return "Normal";
  return "Long";
}

function buildReplyLengthPanel() {
  const panel = el("div", { id: "reply-length-panel", class: "panel", style: "display:none; margin:0 0 14px;" });
  panel.append(
    el("div", { class: "row", style: "justify-content:space-between; align-items:center;" },
      el("strong", {}, "Response length"),
      el("span", { id: "reply-length-value", class: "hint" }, `${currentMaxTokens} tokens`)
    ),
    el("div", { class: "row", style: "gap:10px; align-items:center; margin-top:8px;" },
      el("span", { class: "hint" }, "Court"),
      el("input", {
        type: "range", id: "reply-length-slider", min: "50", max: "600", step: "25",
        value: String(currentMaxTokens), style: "flex:1;",
        oninput: (e) => {
          const v = parseInt(e.target.value, 10);
          $("#reply-length-value").textContent = `${v} tokens (${replyLengthLabel(v)})`;
        },
      }),
      el("span", { class: "hint" }, "Long")
    ),
    el("div", { class: "row", style: "gap:8px; margin-top:10px; align-items:center;" },
      el("button", { class: "btn sm", id: "reply-length-save-btn" }, "Save"),
      el("span", { id: "reply-length-status", class: "hint" }, "")
    )
  );

  const saveBtn = panel.querySelector("#reply-length-save-btn");
  saveBtn.addEventListener("click", async () => {
    const slider = panel.querySelector("#reply-length-slider");
    const value = parseInt(slider.value, 10);
    const status = panel.querySelector("#reply-length-status");
    saveBtn.disabled = true;
    try {
      // Reutilise le systeme /api/settings existant : aucune seconde source de verite.
      // Ne sauvegarde QUE llm_max_tokens -- ne touche a aucun autre reglage, ne recharge
      // pas la page, ne ferme pas le chat, ne perd pas l'historique.
      await api("/api/settings", "POST", { llm_max_tokens: String(value) });
      currentMaxTokens = value;
      status.textContent = `✓ Response length saved: ${value} tokens`;
      // Si la page Réglages a déjà été visitée dans cette session, garde son champ
      // synchronisé pour le prochain affichage (point "Synchronisation" du cahier des charges).
      const settingsSlider = $("#s-llm_max_tokens_slider");
      if (settingsSlider) {
        settingsSlider.value = String(value);
        const settingsValueEl = $("#s-llm_max_tokens_value");
        if (settingsValueEl) settingsValueEl.textContent = `${value} tokens`;
      }
    } catch (e) {
      status.textContent = "Error: " + e.message;
    } finally {
      saveBtn.disabled = false;
    }
  });

  return panel;
}

const MOOD_TO_EMOTION_JS = {
  playful:"playful", calm:"calm", tired:"tired", distant:"cold",
  anxious:"sad", excited:"excited", warm:"romantic", cheerful:"happy",
  relaxed:"calm", neutral:"calm",
};

function openScenarioPicker() {
  if (!scenarios.length) {
    switchView("scenarios");
    return toast(window.t("scenario.toasts.create_first"));
  }
  const grid = el("div", { class: "pick-grid" });
  let close;
  for (const sc of scenarios) {
    const tags = [sc.place, sc.mood_theme, sc.theme].filter(Boolean).join(" · ");
    const card = el("div", { class: "pick-card",
      style: "cursor:pointer; text-align:left; padding:12px;" },
      el("div", { style: "font-weight:600; margin-bottom:4px;" }, sc.title || "(sans titre)"),
      el("div", { class: "hint" }, tags),
      sc.notes ? el("div", { class: "hint", style: "margin-top:4px; font-size:11px;" },
        sc.notes.slice(0,80) + (sc.notes.length>80?"…":"")) : el("span"));
    card.addEventListener("click", async () => {
      close();
      await applyScenarioToChat(sc.id, sc.title);
    });
    grid.append(card);
  }
  const clearBtn = el("button", { class: "btn sm ghost", onclick: async () => {
    close();
    try {
      await api("/api/scenario/clear", "POST", { chat_id: activeChat });
      activeScenarioId = null; renderScenarioBadge();
      toast(window.t("scenario.toasts.disabled"));
    } catch (e) { toast(e.message, true); }
  }}, "🚫 Disable scenario");
  close = overlay(el("div", { class: "modal-card" },
    el("h3", {}, "Choose a scenario"), clearBtn, grid));
}

// --------------------------------------------------------------------------- //
//  Voix : dictée (Whisper) + synthèse (TTS)
// --------------------------------------------------------------------------- //
let whisperEnabled = false;
let ttsEnabled = false;
let currentMaxTokens = 250;   // longueur des responses conversationnelles (slider dans le chat)
let ttsAutoplay = true;          // reglage global (Reglages -> Voix), valeur par defaut
let chatAutoplayOverrides = {};  // { chat_id: true|false } : etat local, prioritaire sur le reglage global

function getChatAutoplay(chatId) {
  if (Object.prototype.hasOwnProperty.call(chatAutoplayOverrides, chatId)) {
    return chatAutoplayOverrides[chatId];
  }
  return ttsAutoplay;  // pas encore touche dans cette conversation : suit le reglage global
}

function setChatAutoplay(chatId, value) {
  chatAutoplayOverrides[chatId] = value;
  try {
    const stored = JSON.parse(localStorage.getItem("amiorai-tts-overrides") || "{}");
    stored[chatId] = value;
    localStorage.setItem("amiorai-tts-overrides", JSON.stringify(stored));
  } catch (e) { /* localStorage indisponible, l'etat reste valable pour la session en cours */ }
}

function loadChatAutoplayOverrides() {
  try {
    chatAutoplayOverrides = JSON.parse(localStorage.getItem("amiorai-tts-overrides") || "{}");
  } catch (e) { chatAutoplayOverrides = {}; }
}
loadChatAutoplayOverrides();
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;

async function toggleDictation() {
  const btn = $("#mic-btn");
  if (!btn) return;
  if (isRecording) {
    mediaRecorder.stop();
    return;
  }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { return toast("Micro inaccessible : " + e.message, true); }

  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
  mediaRecorder.onstop = async () => {
    isRecording = false;
    btn.classList.remove("recording");
    btn.textContent = "🎙️";
    stream.getTracks().forEach((t) => t.stop());
    if (!recordedChunks.length) return;
    const blob = new Blob(recordedChunks, { type: "audio/webm" });
    const dataUrl = await blobToDataURL(blob);
    const ta = $("#composer-input");
    btn.disabled = true;
    const original = "🎙️";
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await api("/api/dictate", "POST", { data_url: dataUrl });
      if (ta) {
        ta.value = (ta.value ? ta.value + " " : "") + res.text;
        ta.focus();
      }
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = original; }
  };
  mediaRecorder.start();
  isRecording = true;
  btn.classList.add("recording");
  btn.textContent = "⏺️";
}

function blobToDataURL(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

let currentAudio = null;
let currentAudioMsgId = null;     // id du message dont l'audio est en cours de lecture/génération
let speakGeneration = 0;          // incrémenté à chaque nouvelle demande, invalide les anciennes

function stopSpeaking() {
  speakGeneration++;               // invalide toute génération TTS en vol
  if (currentAudio) { currentAudio.pause(); currentAudio.src = ""; currentAudio = null; }
  currentAudioMsgId = null;
}

function buildMessageTTSButton(messageId) {
  const titleKey = ttsEnabled ? "chat.listen_message_title" : "chat.tts_disabled_title";
  return el("button", {
    class: "btn sm ghost tts-play-btn" + (ttsEnabled ? "" : " tts-disabled"),
    title: window.t(titleKey),
    "data-msg-audio": messageId,
    onclick: (e) => {
      const btn = e.currentTarget;
      if (!ttsEnabled) {
        toast(window.t("chat.tts_disabled_hint"), true);
        switchView("settings");
        setTimeout(() => { const field = $("#s-tts_enabled"); if (field) field.focus(); }, 80);
        return;
      }
      playMessageAudio(messageId, btn);
    },
  }, "▶ " + window.t("chat.listen_message_btn"));
}

async function playMessageAudio(messageId, btn) {
  stopSpeaking();                  // un seul message parle à la fois : on coupe tout le reste
  const myGen = speakGeneration;
  currentAudioMsgId = messageId;

  if (btn.dataset.audio) {
    if (myGen !== speakGeneration) return;  // une autre demande a pris le dessus entre-temps
    return _playAudioFile(btn.dataset.audio, messageId, myGen);
  }
  const original = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  try {
    const res = await api("/api/message/speak", "POST", { message_id: messageId });
    if (myGen !== speakGeneration) return;  // la demande a été annulée pendant la génération
    btn.dataset.audio = res.audio;
    _playAudioFile(res.audio, messageId, myGen);
  } catch (e) { if (myGen === speakGeneration) toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = original; }
}

function _playAudioFile(filename, messageId, myGen) {
  if (myGen !== undefined && myGen !== speakGeneration) return;  // obsolète, ne joue rien
  if (currentAudio) { currentAudio.pause(); currentAudio.src = ""; }
  const audio = new Audio("/audio/" + filename);
  currentAudio = audio;
  currentAudioMsgId = messageId !== undefined ? messageId : currentAudioMsgId;
  audio.addEventListener("ended", () => {
    if (currentAudio === audio) { currentAudio = null; currentAudioMsgId = null; }
  });
  audio.play().catch((e) => toast("Lecture audio impossible : " + e.message, true));
}

// Lecture automatique : ne se déclenche QUE pour le tout dernier message envoyé, et seulement
// si le toggle voix est active POUR CETTE CONVERSATION (voir le bouton 🔊/🔇 dans l'en-tête,
// indépendant du réglage global de Réglages). N'enchaîne jamais automatiquement sur le message
// suivant : chaque nouveau message coupe proprement le précédent.
async function autoSpeakIfEnabled(messageId, chatId) {
  if (!ttsEnabled || !getChatAutoplay(chatId)) return;
  stopSpeaking();
  const myGen = speakGeneration;
  currentAudioMsgId = messageId;
  try {
    const res = await api("/api/message/speak", "POST", { message_id: messageId });
    if (myGen !== speakGeneration) return;  // un autre message ou un stop a pris le dessus
    const btn = document.querySelector(`[data-msg-audio="${messageId}"]`);
    if (btn) btn.dataset.audio = res.audio;
    _playAudioFile(res.audio, messageId, myGen);
  } catch (e) { /* silencieux : pas de voix configurée pour ce perso, ou TTS hors-ligne */ }
}

// --------------------------------------------------------------------------- //
//  Journal / Timeline
// --------------------------------------------------------------------------- //
const JOURNAL_KIND_LABEL = {
  moment:"💫 Moment", first_meeting:"🌟 First meeting", favorite:"💛 Favori",
  saved_image:"🖼️ Image", memory_event:"🧠 Souvenir",
};
let journalCharFilter = "";

async function loadJournal() {
  const sel = $("#jr-char");
  if (sel && sel.options.length <= 1) {
    try {
      const chars = await api("/api/characters");
      for (const c of chars) sel.append(el("option", { value: c.id }, c.name));
    } catch (e) {}
    sel.addEventListener("change", () => { journalCharFilter = sel.value; renderJournal(); });
  }
  renderJournal();
}

async function renderJournal() {
  const tl = $("#journal-timeline");
  if (!tl) return;
  tl.innerHTML = '<span class="spinner"></span>';
  let items;
  try {
    const url = "/api/journal" + (journalCharFilter ? "?character_id=" + journalCharFilter : "");
    items = await api(url);
  } catch (e) { tl.innerHTML = ""; return toast(e.message, true); }
  tl.innerHTML = "";
  if (!items.length) { tl.innerHTML = '<div class="hint">No entry. Generate a moment or add one.</div>'; return; }
  for (const it of items) {
    const node = el("div", { class: "tl-item" + (it.pinned ? " pinned" : "") },
      el("div", { class: "tl-date" }, it.date || ""),
      el("div", { class: "tl-body" },
        el("div", { class: "tl-kind" }, JOURNAL_KIND_LABEL[it.kind] || it.kind),
        it.title ? el("div", { class: "tl-title" }, it.title) : el("span"),
        el("div", { class: "tl-content" }, it.content || ""),
        it.image ? el("img", { class: "genimg tl-img", src: imgUrl(it.image) }) : el("span"),
        el("div", { class: "row", style: "gap:6px; margin-top:6px;" },
          el("button", { class: "btn sm ghost", onclick: async () => {
            await api("/api/journal/pin", "POST", { id: it.id, pinned: it.pinned ? 0 : 1 }); renderJournal();
          } }, it.pinned ? "📌 unpin" : "📌 pin"),
          el("button", { class: "btn sm danger", onclick: async () => {
            if (!confirm("Delete this entry?")) return;
            await api("/api/journal/delete", "POST", { id: it.id }); renderJournal();
          } }, "✕"))));
    tl.append(node);
  }
}

const _jrGen = $("#jr-generate");
if (_jrGen) _jrGen.addEventListener("click", async (e) => {
  const cid = ($("#jr-char") || {}).value;
  if (!cid) return toast(window.t("journal.toasts.select_character"), true);
  e.target.disabled = true; e.target.innerHTML = '<span class="spinner"></span>';
  try { await api("/api/journal/generate", "POST", { character_id: cid }); renderJournal(); toast(window.t("journal.toasts.moment_added")); }
  catch (err) { toast(err.message, true); }
  finally { e.target.disabled = false; e.target.textContent = window.t("journal.generate_btn"); }
});

const _jrManual = $("#jr-add-manual");
if (_jrManual) _jrManual.addEventListener("click", async () => {
  const content = await promptDialog("", "New journal entry");
  if (!content) return;
  try {
    await api("/api/journal/add", "POST", {
      character_id: journalCharFilter || null, kind: "moment", content });
    renderJournal();
  } catch (e) { toast(e.message, true); }
});

const MOOD_EMOJI = {
  playful:"😄", calm:"😌", tired:"😴", distant:"😶", anxious:"😟",
  excited:"🤩", warm:"🥰", cheerful:"😊", relaxed:"😏", neutral:"😐",
};
const MOOD_COLOR = {
  playful:"#f5a623", calm:"#7ec8e3", tired:"#9b9b9b", distant:"#8e8e8e",
  anxious:"#d0a040", excited:"#e05cff", warm:"#e0729a", cheerful:"#68d391",
  relaxed:"#a0c4ff", neutral:"#b0b0b0",
};

function renderMoodBar(state) {
  const bar = $("#mood-bar");
  if (!bar || !state) return;
  const mood = state.mood || "neutral";
  const color = MOOD_COLOR[mood] || "#b0b0b0";
  const emoji = MOOD_EMOJI[mood] || "😐";
  const stats = [
    { k: "affection", label: "💕", title: "Affection" },
    { k: "trust",     label: "🤝", title: "Confiance" },
    { k: "energy",    label: "⚡", title: "Energy" },
    { k: "curiosity", label: "🔍", title: "Curiosity" },
    { k: "stress",    label: "😓", title: "Stress", invert: true },
  ];
  bar.innerHTML = "";
  bar.append(el("span", { class: "mood-name", style: `color:${color}` }, `${emoji} ${mood}`));
  for (const s of stats) {
    const v = state[s.k] ?? 50;
    const fill = s.invert ? (100 - v) : v;  // stress : barre = "well-being" (inverse)
    const pip = el("div", { class: "mood-stat", title: `${s.title} : ${v}` },
      el("span", { class: "mood-label" }, s.label),
      el("div", { class: "mood-track" },
        el("div", { class: "mood-fill", style: `width:${fill}%; background:${color}` })));
    bar.append(pip);
  }
}

async function loadMoodWidget(charId) {
  try {
    const state = await api("/api/char_mood?character_id=" + charId);
    renderMoodBar(state);
    return state;
  } catch (e) { /* silencieux */ return null; }
}

function updateMoodAfterReply(resp) {
  if (!resp || !resp.mood) return;
  const bar = $("#mood-bar");
  if (bar) {
    const state = { mood: resp.mood, ...(resp.stats || {}) };
    renderMoodBar(state);
  }
  const emotion = MOOD_TO_EMOTION_JS[resp.mood] || "calm";
  if (chatCharId && emotion !== currentChatEmotion) {
    refreshChatPortrait(chatCharId, emotion);
  }
}

// --------------------------------------------------------------------------- //
//  Portraits d'émotions
// --------------------------------------------------------------------------- //
const EMOTION_LABELS = {
  happy:"😄 Happy", calm:"😌 Calm", playful:"😏 Playful", shy:"🫣 Shy",
  sad:"😢 Sad", angry:"😠 Angry", tired:"😴 Tired",
  excited:"🤩 Excited", romantic:"🥰 Romantic", cold:"🧊 Cold",
};
const EMOTION_ORDER = ["happy","calm","playful","shy","sad","angry","tired","excited","romantic","cold"];

let emotionCache = {};   // {charId: {emotion: imageFile}}

async function loadEmotionGrid(charId) {
  const grid = $("#emotion-grid");
  if (!grid) return;
  try { emotionCache[charId] = await api("/api/char_emotions?character_id=" + charId); }
  catch (e) { emotionCache[charId] = {}; }
  renderEmotionGrid(charId);
}

function renderEmotionGrid(charId) {
  const grid = $("#emotion-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (const em of EMOTION_ORDER) {
    const img = (emotionCache[charId] || {})[em];
    const thumb = el("div", { class: "emot-thumb" + (img ? "" : " missing") });
    if (img) thumb.append(el("img", { src: imgUrl(img), class: "genimg" }));
    else thumb.append(el("span", { class: "hint" }, "?"));
    const genBtn = el("button", { class: "btn sm" + (img ? " ghost" : "") },
      img ? "↻" : "Generate");
    genBtn.addEventListener("click", async () => {
      const proposed = (await api("/api/char_emotion/generate", "POST",
        { character_id: charId, emotion: em, dry_run: true })).prompt;
      const edited = await promptDialog(proposed, `Portrait — ${EMOTION_LABELS[em]}`);
      if (!edited) return;
      genBtn.disabled = true; genBtn.innerHTML = '<span class="spinner"></span>';
      try {
        const res = await api("/api/char_emotion/generate", "POST",
          { character_id: charId, emotion: em, prompt: edited });
        (emotionCache[charId] = emotionCache[charId] || {})[em] = res.image;
        renderEmotionGrid(charId);
        // Si on vient de generer le portrait de l'emotion actuellement affichee dans le chat
        // de ce meme personnage, on la rafraichit immediatement -- pas besoin de recharger la
        // page ni d'attendre un nouveau message pour voir le nouveau portrait.
        if (charId === chatCharId && em === currentChatEmotion) {
          refreshChatPortrait(charId, em);
        }
      } catch (e) { toast(e.message, true); }
      finally { genBtn.disabled = false; }
    });
    const card = el("div", { class: "emot-card" },
      thumb, el("div", { class: "emot-label" }, EMOTION_LABELS[em]), genBtn);
    grid.append(card);
  }
}

// Portrait dynamique dans le chat (change avec le mood)
let chatCharId = null;   // ID du personnage solo active
let currentChatEmotion = "calm";

async function refreshChatPortrait(charId, emotion) {
  const portrait = $("#chat-portrait");
  if (!portrait || !charId) return;
  if (!emotionCache[charId]) {
    try { emotionCache[charId] = await api("/api/char_emotions?character_id=" + charId); }
    catch (e) { emotionCache[charId] = {}; }
  }
  const cache = emotionCache[charId] || {};
  portrait.innerHTML = "";

  // 1. Le portrait de l'emotion demandee, s'il existe.
  let img = cache[emotion];
  let usedLabel = EMOTION_LABELS[emotion] || emotion;

  // 2. Sinon, repli sur le portrait "calm" (souvent le premier genere, le plus generique).
  if (!img && emotion !== "calm") {
    img = cache["calm"];
    if (img) usedLabel = EMOTION_LABELS["calm"];
  }

  // 3. Sinon, repli sur l'avatar principal du personnage (deja disponible via chatMembers,
  // pas d'appel reseau supplementaire necessaire).
  if (!img) {
    const member = chatMembers.find((m) => m.id === charId);
    if (member && member.avatar) {
      img = member.avatar;
      usedLabel = EMOTION_LABELS[emotion] || emotion;  // garde le libelle de l'emotion visee
    }
  }

  if (img) {
    portrait.append(el("img", { src: imgUrl(img), class: "genimg", title: usedLabel }));
  } else {
    // 4. Dernier recours seulement : aucun portrait d'emotion ET aucun avatar principal.
    portrait.innerHTML = `<div class="no-portrait hint">${EMOTION_LABELS[emotion] || emotion}</div>`;
  }
  currentChatEmotion = emotion;
}

// --------------------------------------------------------------------------- //
//  Scenarios
// --------------------------------------------------------------------------- //
let scenarios = [];
let activeScenarioId = null;

async function loadScenarios() {
  try { scenarios = await api("/api/scenarios"); }
  catch (e) { scenarios = []; }
  renderScenarioList();
}

function renderScenarioList() {
  const list = $("#scenario-list");
  if (!list) return;
  list.innerHTML = "";
  if (!scenarios.length) { list.innerHTML = `<div class="hint">${window.t("scenario.no_scenarios")}</div>`; return; }
  for (const sc of scenarios) {
    const tags = [sc.place, sc.mood_theme, sc.theme, sc.relationship].filter(Boolean);
    list.append(el("div", { class: "scenario-card" },
      el("div", { class: "sc-title" }, sc.title || "(sans titre)"),
      el("div", { class: "sc-tags" }, ...tags.map(t => el("span", { class: "sc-tag" }, t))),
      sc.notes ? el("div", { class: "sc-notes hint" }, sc.notes.slice(0, 100) + (sc.notes.length > 100 ? "…" : "")) : el("span"),
      el("div", { class: "row", style: "gap:6px; margin-top:8px; flex-wrap:wrap;" },
        el("button", { class: "btn sm ghost", onclick: () => editScenario(sc) }, window.t("scenario.edit_btn")),
        el("button", { class: "btn sm ghost", onclick: () => {
          window.location.href = "/api/share/scenario/export?id=" + encodeURIComponent(sc.id);
        } }, window.t("scenario.export_btn")),
        el("button", { class: "btn sm danger", onclick: async () => {
          if (!confirm(window.t("scenario.delete_confirm"))) return;
          await api("/api/scenario/delete", "POST", { id: sc.id }); loadScenarios();
        } }, "✕"),
        el("button", { class: "btn sm", title: window.t("scenario.apply_title"),
          onclick: () => applyScenarioToChat(sc.id, sc.title) }, window.t("scenario.apply_btn")))));
  }
}

function editScenario(sc) {
  switchView("scenarios");
  const fields = ["id","title","place","mood_theme","theme","relationship","goal","conflict","notes"];
  for (const f of fields) {
    const n = $("#sc-" + f); if (n) n.value = sc[f] || "";
  }
  $("#sc-status").textContent = "Editing “" + (sc.title || "scenario") + "”";
}

function clearScenarioForm() {
  for (const f of ["id","title","place","mood_theme","theme","relationship","goal","conflict","notes"]) {
    const n = $("#sc-" + f); if (n) n.value = "";
  }
  $("#sc-status").textContent = "";
}

async function applyScenarioToChat(scId, title) {
  if (!activeChat) return toast("No active conversation.", true);
  try {
    await api("/api/scenario/apply", "POST", { chat_id: activeChat, scenario_id: scId });
    activeScenarioId = scId;
    toast(`Scenario “${title}” activated in the conversation.`);
    renderScenarioBadge();
  } catch (e) { toast(e.message, true); }
}

function renderScenarioBadge() {
  const badge = $("#scenario-badge");
  if (!badge) return;
  if (activeScenarioId) {
    const sc = scenarios.find(s => s.id === activeScenarioId);
    badge.textContent = "📖 " + (sc ? sc.title : "Active scenario");
    badge.style.display = "inline-block";
  } else {
    badge.style.display = "none";
  }
}

const _scImportBtn = $("#sc-import-btn");
if (_scImportBtn) _scImportBtn.addEventListener("click", () => $("#sc-import-input").click());
const _scImportInput = $("#sc-import-input");
if (_scImportInput) _scImportInput.addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const res = await uploadShareFile("/api/share/scenario/import", file);
    toast(window.t("scenario.import_success", { title: res.title || window.t("scenario.new_title") }));
    await loadScenarios();
  } catch (err) {
    toast(window.t("scenario.import_failed", { error: err.message }), true);
  } finally {
    e.target.value = "";
  }
});

$("#sc-save").addEventListener("click", async () => {
  const data = {};
  for (const f of ["id","title","place","mood_theme","theme","relationship","goal","conflict","notes"]) {
    const n = $("#sc-" + f); if (n) data[f] = n.value;
  }
  if (!data.title && !data.place) return toast("Donne au moins un titre ou un lieu.", true);
  try {
    const res = await api("/api/scenario/save", "POST", data);
    toast(window.t("scenario.toasts.saved"));
    clearScenarioForm();
    loadScenarios();
  } catch (e) { toast(e.message, true); }
});

const scGenBtn = $("#sc-generate");
if (scGenBtn) scGenBtn.addEventListener("click", async () => {
  const data = {};
  for (const f of ["place","mood_theme","theme","relationship"]) {
    const n = $("#sc-" + f); if (n) data[f] = n.value;
  }
  scGenBtn.disabled = true; scGenBtn.innerHTML = '<span class="spinner"></span> Generation…';
  try {
    const res = await api("/api/scenario/generate", "POST", data);
    for (const f of ["id","title","place","mood_theme","theme","relationship","goal","conflict","notes"]) {
      const n = $("#sc-" + f); if (n && res[f]) n.value = res[f];
    }
    toast(window.t("scenario.toasts.generated"));
    loadScenarios();
  } catch (e) { toast(e.message, true); }
  finally { scGenBtn.disabled = false; scGenBtn.textContent = window.t("scenario.generate_btn"); }
});

const scClearBtn = $("#sc-clear");
if (scClearBtn) scClearBtn.addEventListener("click", clearScenarioForm);

// Lieu custom dans les scenarios
const scPlace = $("#sc-place");
if (scPlace) scPlace.addEventListener("change", () => {
  const custom = $("#sc-place-custom");
  if (custom) custom.style.display = scPlace.value === "custom" ? "block" : "none";
});

if (typeof loadScenarios === "function" && $("#view-scenarios")) loadScenarios();


function appendRoleplayText(target, content, role = "assistant") {
  const text = String(content || "");
  if (role !== "assistant" || !text) {
    target.append(document.createTextNode(text));
    return;
  }

  // Affichage roleplay uniquement : la mémoire et le texte sauvegardé restent unchangeds.
  // *narration/action*  -> gris léger + italique
  // "expression" / « expression” / “expression” -> orange léger + italique
  const pattern = /\*([^*]+)\*|"([^"\n]+)"|“([^”\n]+)”|«([^»\n]+)»/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) target.append(document.createTextNode(text.slice(last, match.index)));

    const span = document.createElement("span");
    if (match[1] != null) {
      span.className = "rp-narration";
      span.textContent = match[1];
    } else {
      span.className = "rp-expression";
      span.textContent = match[0];
    }
    target.append(span);
    last = pattern.lastIndex;
  }
  if (last < text.length) target.append(document.createTextNode(text.slice(last)));
}

function setBubbleContent(bubble, content, role = "assistant") {
  if (!bubble) return;
  bubble.textContent = "";
  appendRoleplayText(bubble, content, role);
}

async function addCharacterToChat() {
  let chars;
  try { chars = await api("/api/characters"); } catch (e) { return toast(e.message, true); }
  const inChat = new Set(chatMembers.map((m) => m.id));
  const avail = chars.filter((c) => !inChat.has(c.id));
  if (!avail.length) return toast(window.t("chat.toasts.all_members_added"));
  const grid = el("div", { class: "pick-grid" });
  let close;
  avail.forEach((c) => {
    const card = el("button", { class: "pick-card", onclick: async () => {
      close();
      try {
        await api("/api/chat/add_member", "POST", { chat_id: activeChat, character_id: c.id });
        toast(window.t("chat.toasts.member_added", { name: c.name }));
        openChat(activeChat);
      } catch (e) { toast(e.message, true); }
    } });
    if (c.avatar) card.append(el("img", { src: imgUrl(c.avatar) }));
    card.append(el("div", { class: "pick-name" }, c.name));
    grid.append(card);
  });
  close = overlay(el("div", { class: "modal-card" },
    el("h3", {}, "Add character"), grid));
}

async function updateMemoryFromChat(btn) {
  let target = activeResponder;
  if (!target && chatMembers.length) target = chatMembers[0].id;
  if (!target) return toast(window.t("chat.no_character_in_conversation"), true);
  const name = memberName(target);
  const txt = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  try {
    await api("/api/memory/summarize", "POST", { character_id: target, chat_id: activeChat });
    toast(window.t("chat.toasts.memory_updated", { name }));
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = txt; }
}

async function reactMessage() {
  const msgs = $("#msgs");
  const pending = el("div", { class: "msg assistant" }, el("div", { class: "bubble" }, ""));
  pending.querySelector(".bubble").innerHTML = '<span class="spinner"></span>';
  msgs.append(pending);
  msgs.scrollTop = msgs.scrollHeight;
  try {
    const res = await api("/api/message/react", "POST",
      { chat_id: activeChat, responder_id: activeResponder });
    pending.remove();
    msgs.append(renderMsg({ role: "assistant", character_id: res.character_id,
      content: res.content, id: res.id }));
    msgs.scrollTop = msgs.scrollHeight;
  } catch (e) { pending.remove(); toast(e.message, true); }
}

function renderMsg(m) {
  const wrap = el("div", { class: "msg " + m.role });
  if (m.role === "assistant" && m.character_id) {
    wrap.append(el("div", { class: "who" }, memberName(m.character_id)));
  }
  const bubble = el("div", { class: "bubble" });
  setBubbleContent(bubble, m.content, m.role);
  wrap.append(bubble);
  if (m.image) {
    if (m.image_prompt) wrap.dataset.prompt = m.image_prompt;
    const img = el("img", { class: "genimg", src: imgUrl(m.image) });
    const rerollRow = el("div", { class: "row", style: "margin-top:4px; gap:4px; flex-wrap:wrap;" },
      el("button", { class: "btn sm ghost", title: window.t("chat.new_seed_title"),
        onclick: (e) => regenImage(m.id, false, e.target) }, window.t("chat.reroll_btn")),
      el("button", { class: "btn sm ghost", title: window.t("chat.same_seed_title"),
        onclick: (e) => regenImage(m.id, true, e.target) }, window.t("chat.same_seed_btn")),
      m.role === "assistant" ? buildMessageTTSButton(m.id) : null);
    wrap.append(img, rerollRow);
    wrap.append(el("div", { class: "row", style: "margin-top:4px;" },
      el("button", { class: "btn sm ghost", onclick: (e) => regenImage(m.id, false, e.target) }, window.t("chat.reroll_btn")),
      el("button", { class: "btn sm ghost", onclick: (e) => regenImage(m.id, true, e.target) }, window.t("chat.same_seed_btn"))
    ));
  } else if (m.role === "assistant") {
    const continueBtn = el("button", { class: "btn sm ghost continue-btn",
      title: window.t("chat.continue_title"),
      onclick: (e) => continueMessage(m.id, e.target) }, window.t("chat.continue_btn"));
    const row = el("div", { class: "row", style: "margin-top:4px; flex-wrap:wrap; gap:4px;" },
      el("button", { class: "btn sm ghost imgbtn",
        title: window.t("chat.bring_scene_title"),
        onclick: (e) => generateImage(m.id, true, e.target) }, window.t("chat.bring_scene_btn")),
      el("button", { class: "btn sm ghost",
        title: window.t("chat.character_only_title"),
        onclick: (e) => generateImage(m.id, false, e.target) }, window.t("chat.character_only_btn")),
      el("button", { class: "btn sm ghost",
        title: window.t("chat.regen_text_title"),
        onclick: (e) => regenText(m.id, e.target) }, "↺ texte"),
      continueBtn,
      el("button", { class: "btn sm ghost",
        title: window.t("chat.background_title"),
        onclick: (e) => generateBackground(m.id, e.target) }, window.t("chat.background_generated_note")));
    row.append(buildMessageTTSButton(m.id));
    if (currentChatIsGroup) {
      row.append(
        el("button", { class: "btn sm ghost", title: window.t("chat.group_scene_title"),
          onclick: (e) => groupScene(m.id, false, e.target) }, window.t("chat.group_scene_btn")),
        el("button", { class: "btn sm ghost", title: window.t("chat.group_with_persona_title"),
          onclick: (e) => groupScene(m.id, true, e.target) }, window.t("chat.group_with_persona_btn"))
      );
    }
    wrap.append(row);
  }
  // Le bouton Continuer n'est visible que sur le dernier message assistant :
  // updateContinueBtnVisibility() gère ça après chaque rendu.
  return wrap;
}

function updateContinueBtnVisibility() {
  // Masquer tous les boutons Continuer sauf celui du dernier message assistant
  const allContinue = $$(".continue-btn");
  const allMsgs = $$(".msgs .msg.assistant");
  const lastAssistant = allMsgs[allMsgs.length - 1];
  allContinue.forEach((btn) => {
    const msgWrap = btn.closest(".msg");
    btn.style.display = (msgWrap && msgWrap === lastAssistant) ? "" : "none";
  });
}

async function continueMessage(messageId, btn) {
  // Vérification locale rapide avant d'appeler le backend
  const allMsgs = $$(".msgs .msg.assistant");
  const lastAssistant = allMsgs[allMsgs.length - 1];
  if (!lastAssistant || !lastAssistant.querySelector(`[onclick*="${messageId}"]`) &&
      !btn.closest(".msg.assistant") === lastAssistant) {
    // Laisse le backend valider — si le DOM est désynchronisé il renverra une error propre
  }
  const txt = btn.textContent; btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  const msgs = $("#msgs");
  try {
    const res = await api("/api/message/continue", "POST", { message_id: messageId });
    const newMsg = renderMsg({ role: "assistant", character_id: res.character_id,
      content: res.content, id: res.id });
    msgs.append(newMsg);
    msgs.scrollTop = msgs.scrollHeight;
    updateContinueBtnVisibility();
    loadChats();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = txt;
  }
}

async function regenText(messageId, btn) {
  if (!confirm(window.t("chat.regen_text_confirm"))) return;
  const txt = btn.textContent; btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    const res = await api("/api/message/regenerate_text", "POST", { message_id: messageId });
    // Mettre à jour le texte dans le DOM
    const wrap = btn.closest(".msg");
    const bubble = wrap.querySelector(".bubble");
    if (bubble) setBubbleContent(bubble, res.content, "assistant");
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = txt; }
}

async function generateBackground(messageId, btn) {
  // Calcule d'abord le prompt, puis ouvre le dialogue avant d'envoyer à ComfyUI
  const txt = btn.textContent; btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> prompt…';
  let proposed;
  try {
    proposed = (await api("/api/message/background", "POST",
      { chat_id: activeChat, message_id: messageId, dry_run: true })).prompt;
  } catch (e) { btn.disabled = false; btn.textContent = txt; return toast(e.message, true); }
  btn.disabled = false; btn.textContent = txt;
  const edited = await promptDialog(proposed, window.t("chat.background_prompt_title"));
  if (edited === null) return;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ComfyUI…';
  try {
    const res = await api("/api/message/background", "POST",
      { chat_id: activeChat, message_id: messageId, prompt: edited });
    // Affiche le fond sous le message, cliquable pour agrandir
    const wrap = btn.closest(".msg"); const row = btn.closest(".row");
    const img = el("img", { class: "genimg", src: imgUrl(res.image),
      title: window.t("chat.background_generated_title") });
    const note = el("div", { class: "hint", style: "font-size:11px; margin-top:2px;" },
      window.t("chat.background_generated_note"));
    wrap.insertBefore(el("div", {}, img, note), row);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = txt; }
}

async function groupScene(messageId, withPersona, btn) {
  const txt = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> prompt…';
  let proposed;
  try {
    proposed = (await api("/api/message/group_image", "POST",
      { chat_id: activeChat, message_id: messageId, with_persona: withPersona, dry_run: true })).prompt;
  } catch (e) { btn.disabled = false; btn.textContent = txt; return toast(e.message, true); }
  btn.disabled = false; btn.textContent = txt;
  const edited = await promptDialog(proposed, window.t("chat.group_prompt_title"));
  if (edited === null) return;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ComfyUI…';
  try {
    const res = await api("/api/message/group_image", "POST",
      { chat_id: activeChat, message_id: messageId, with_persona: withPersona, prompt: edited });
    const wrap = btn.closest(".msg"); const row = btn.closest(".row");
    wrap.dataset.prompt = res.prompt;
    wrap.insertBefore(el("img", { class: "genimg", src: imgUrl(res.image) }), row);
    row.remove();
  } catch (e) { btn.disabled = false; btn.textContent = txt; toast(e.message, true); }
}

async function regenImage(messageId, keepSeed, btn) {
  const wrap = btn.closest(".msg");
  const edited = await promptDialog(wrap.dataset.prompt || "",
    keepSeed ? window.t("chat.regen_same_seed") : window.t("chat.regen_image"));
  if (edited === null) return;
  const txt = btn.textContent; btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    const res = await api("/api/message/regenerate", "POST",
      { message_id: messageId, keep_seed: keepSeed, prompt: edited });
    wrap.dataset.prompt = res.prompt;
    const oldImg = wrap.querySelector(".genimg");
    if (oldImg) oldImg.src = imgUrl(res.image) + "?t=" + Date.now();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = txt; }
}

async function sendMessage() {
  const input = $("#composer-input");
  const content = input.value.trim();
  if (!content) return;
  input.value = "";
  const msgs = $("#msgs");
  msgs.append(renderMsg({ role: "user", content }));
  const pending = el("div", { class: "msg assistant" },
    el("div", { class: "bubble" }, "")); 
  pending.querySelector(".bubble").innerHTML = '<span class="spinner"></span>';
  msgs.append(pending);
  msgs.scrollTop = msgs.scrollHeight;
  $("#send-btn").disabled = true;
  try {
    const res = await api("/api/message/send", "POST",
      { chat_id: activeChat, content, responder_id: activeResponder });
    pending.remove();
    msgs.append(renderMsg({ role: "assistant", character_id: res.character_id,
      content: res.content, id: res.id }));
    msgs.scrollTop = msgs.scrollHeight;
    updateContinueBtnVisibility();
    updateMoodAfterReply(res);
    loadChats();
    autoSpeakIfEnabled(res.id, activeChat);
  } catch (e) {
    pending.remove();
    toast(e.message, true);
  } finally {
    $("#send-btn").disabled = false;
  }
}

async function generateImage(messageId, withPersona, btn) {
  const row = btn.closest(".row");
  const original = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> prompt…';
  let proposed;
  try {
    proposed = (await api("/api/message/image", "POST",
      { chat_id: activeChat, message_id: messageId, with_persona: !!withPersona, dry_run: true })).prompt;
  } catch (e) { btn.disabled = false; btn.textContent = original; return toast(e.message, true); }
  btn.disabled = false; btn.textContent = original;
  const edited = await promptDialog(proposed);
  if (edited === null) return;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ComfyUI…';
  try {
    const res = await api("/api/message/image", "POST",
      { chat_id: activeChat, message_id: messageId, with_persona: !!withPersona, prompt: edited });
    const wrap = btn.closest(".msg");
    wrap.dataset.prompt = res.prompt;
    wrap.insertBefore(el("img", { class: "genimg", src: imgUrl(res.image) }), row);
    row.remove();
  } catch (e) { btn.disabled = false; btn.textContent = original; toast(e.message, true); }
}

async function deleteChat(id) {
  if (!confirm(window.t("chat.delete_confirm"))) return;
  try {
    await api("/api/chat/delete", "POST", { id });
    activeChat = null;
    $("#chat-pane").innerHTML = `<div class="empty" style="margin:auto;">${window.t("chat.select_or_create")}</div>`;
    loadChats();
  } catch (e) { toast(e.message, true); }
}

// ---- Nouvelle conversation (modale) ----
$("#new-chat").addEventListener("click", async () => {
  let chars;
  try { chars = await api("/api/characters"); }
  catch (e) { return toast(e.message, true); }
  if (!chars.length) return toast(window.t("chat.create_character_first"), true);

  const checklist = el("div", { class: "checklist" });
  for (const c of chars) {
    checklist.append(el("label", {},
      el("input", { type: "checkbox", value: c.id }), c.name));
  }
  const modal = el("div", { class: "modal-bg", onclick: (e) => {
    if (e.target.classList.contains("modal-bg")) modal.remove();
  } },
    el("div", { class: "modal" },
      el("h2", {}, window.t("chat.new_modal_title")),
      el("p", { class: "hint" }, window.t("chat.new_modal_hint")),
      checklist,
      el("label", {}, window.t("chat.title_optional")),
      el("input", { id: "nc-title" }),
      el("div", { class: "row", style: "margin-top:16px; justify-content:flex-end;" },
        el("button", { class: "btn ghost", onclick: () => modal.remove() }, window.t("common.cancel")),
        el("button", { class: "btn", onclick: async () => {
          const members = $$(".modal input[type=checkbox]:checked").map((c) => c.value);
          if (!members.length) return toast(window.t("chat.member_required"), true);
          const title = $("#nc-title").value.trim() || null;
          try {
            const { id } = await api("/api/chat/create", "POST", { members, title });
            modal.remove();
            await loadChats();
            openChat(id);
          } catch (e) { toast(e.message, true); }
        } }, window.t("common.create"))
      )
    )
  );
  $("#modal-root").append(modal);
});

// --------------------------------------------------------------------------- //
//  SYSTEM (health + contrôle process)
// --------------------------------------------------------------------------- //
function dot(status) {
  // green=ready, orange=loading, red=error, gray=offline/gray
  const color = { ready:"#46d27a", loading:"#f5a623", error:"#e0556b", offline:"#888", gray:"#555" }[status] || "#555";
  return el("span", { class: "status-dot", style: `background:${color}` });
}
function statusLine(status, text) {
  return el("div", { class: "status-line" }, dot(status), el("span", {}, text));
}

async function loadSystem() {
  const box = $("#sys-health");
  box.innerHTML = '<span class="spinner"></span>';
  let h;
  try { h = await api("/api/health"); }
  catch (e) { box.innerHTML = ""; box.append(statusLine("error", "Health error: " + e.message)); return; }

  box.innerHTML = "";
  // LLM
  if (h.llm.backend === "external") {
    box.append(statusLine(h.llm.status,
      "LLM externe (" + (h.llm.external_url || "?") + ") : " +
      (h.llm.reachable ? "connected" : "unreachable")));
  } else {
    let txt = "LLM interne : ";
    if (h.llm.status === "ready") txt += "loaded ✓";
    else if (h.llm.status === "loading") txt += "loading…";
    else if (h.llm.status === "error") txt += "error";
    else if (h.llm.status === "offline") txt += "configured (not loaded)";
    else txt += "not configured";
    box.append(statusLine(h.llm.status, txt));
  }
  // ComfyUI
  let comfyTxt = "ComfyUI : ";
  if (h.comfy.reachable) comfyTxt += window.t("system.comfy_status_connected");
  else comfyTxt += window.t("system.comfy_status_offline");
  box.append(statusLine(h.comfy.status, comfyTxt));
  // VRAM
  if (h.comfy.vram) {
    const v = h.comfy.vram;
    box.append(el("div", { class: "vram-line" },
      el("span", {}, `VRAM (${v.name}) : ${v.used_mb} / ${v.total_mb} Mo`),
      el("div", { class: "vram-track" },
        el("div", { class: "vram-fill", style:
          `width:${v.percent}%; background:${v.percent>90?"#e0556b":v.percent>70?"#f5a623":"#46d27a"}` }))));
  }
  // Workflows
  const wfLabels = { t2i_workflow:"Avatar", i2i_workflow:"Solo", duo_workflow:"Duo",
                     trio_workflow:"Trio", group_workflow:"Groupe" };
  for (const key of Object.keys(wfLabels)) {
    const w = h.workflows[key];
    if (!w) continue;
    let txt = `Workflow ${wfLabels[key]} (${w.file}) : `;
    if (w.ok) txt += "OK";
    else if (!w.exists) txt += "file missing";
    else if (w.valid_json === false) txt += "JSON invalide";
    else if (w.missing_tokens) txt += "jetons manquants : " + w.missing_tokens.join(", ");
    else txt += "problem";
    box.append(statusLine(w.status, txt));
  }
  // TTS (voix)
  if (h.tts) {
    let ttsTxt = "Voix (TTS) : ";
    if (!h.tts.enabled) ttsTxt += "disabled";
    else if (h.tts.model_status === "ready") ttsTxt += `${h.tts.engine === "qwen" ? "Qwen3-TTS 0.6B" : "Chatterbox V3"} ready (${h.tts.device || "?"})` + (h.tts.managed_by_app ? " — started by the app" : "");
    else if (h.tts.model_status === "loading") ttsTxt += "model loading…";
    else if (h.tts.error) ttsTxt += "error : " + h.tts.error;
    else ttsTxt += "offline";
    box.append(statusLine(h.tts.status, ttsTxt));
  }
  // Whisper (dictée)
  if (h.whisper) {
    let whisperTxt = "Dictation (Whisper): ";
    if (!h.whisper.enabled) whisperTxt += "disabled";
    else if (h.whisper.loaded) whisperTxt += `ready (${h.whisper.size || "?"})`;
    else if (h.whisper.error) whisperTxt += "error : " + h.whisper.error;
    else whisperTxt += "not loaded yet (loads on first dictation)";
    box.append(statusLine(h.whisper.status, whisperTxt));
  }
  // Latest error
  if (h.last_error) {
    const d = new Date(h.last_error.t * 1000).toLocaleTimeString();
    box.append(el("div", { class: "last-error" }, `⚠ Latest error [${d}] : ${h.last_error.msg}`));
  }

  const errBox = $("#sys-errors");
  errBox.innerHTML = "";
  if (!h.errors.length) { errBox.textContent = window.t("system.errors_no_recent"); }
  else for (const er of h.errors) {
    const d = new Date(er.t * 1000).toLocaleTimeString();
    errBox.append(el("div", { style: "margin:3px 0; color:var(--danger);" }, "[" + d + "] " + er.msg));
  }

  try {
    const st = await api("/api/llm/status");
    renderLLM(st);
    if (!llmPollTimer) startLLMPolling(st.state === "loading");
  } catch (e) {}
  // Charger les infos réseau local
  loadLanSettings();
}

async function sysAction(path, label, btn) {
  const txt = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  try {
    const res = await api(path, "POST", {});
    toast(res.msg || label || "OK");
    loadSystem();
  } catch (e) { toast(e.message, true); }
  finally { if (btn) { btn.disabled = false; btn.textContent = txt; } }
}

$("#sys-refresh").addEventListener("click", loadSystem);
$("#sys-comfy-free").addEventListener("click", (e) => sysAction("/api/comfy/free", "VRAM freed", e.target));
$("#sys-llm-free").addEventListener("click", (e) => sysAction("/api/llm/free", "LLM unloaded", e.target));

// ---- Suivi du chargement du LLM en temps réel ----
let llmPollTimer = null;
const LLM_LABEL = { idle: "idle", loading: "loading…", ready: "ready ✓", error: "error" };
const LLM_OK = { idle: false, loading: false, ready: true, error: false };

const EVT_COLOR = {
  load:    "#a78bfa",   // violet  – chargement
  ready:   "#7dd3a8",   // vert    – ready
  request: "#60a5fa",   // bleu    – requête entrante
  done:    "#86efac",   // vert clair – response terminée
  info:    "#c8b8d8",   // gris    – info
  error:   "#f08080",   // rouge   – error
};

function renderLLM(st) {
  const box = $("#llm-state");
  if (!box) return;
  const label = LLM_LABEL[st.state] || st.state;
  let txt = label;
  if (st.state === "loading") txt += "  ·  " + st.elapsed + " s";
  else if (st.state === "ready" && st.elapsed) txt += "  ·  loaded in " + st.elapsed + " s";
  box.innerHTML = "";
  box.append(dot(LLM_OK[st.state]), document.createTextNode("LLM : " + txt));
  if (st.gen_active) {
    box.append(el("span", { style: "color:#60a5fa; margin-left:10px;" },
      `⏳ generation… ${st.gen_tokens} tokens · ${st.gen_elapsed} s`));
  }

  const logbox = $("#llm-logbox");

  // Construit les lignes : d'abord les événements du ring buffer, puis le log de chargement
  const rows = [];

  // Log de chargement (visible pendant loading ou juste après ready)
  if (st.log_lines && st.log_lines.length && st.state !== "idle") {
    for (const ln of st.log_lines) {
      const col = /cuda|gpu|offload|CUDA|GPU/i.test(ln) ? "#7dd3a8"
                : /error|failed/i.test(ln) ? "#f08080" : "#888";
      rows.push({ col, msg: ln, ts: null });
    }
  }

  // Ring buffer d'activité (toutes les actions)
  if (st.events && st.events.length) {
    for (const ev of st.events) {
      const col = EVT_COLOR[ev.kind] || "#c8b8d8";
      const hm = new Date(ev.t * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      rows.push({ col, msg: ev.msg, ts: hm, kind: ev.kind });
    }
  }

  if (!rows.length) {
    logbox.innerHTML = '<span style="color:#555">— waiting for activity —</span>';
    return;
  }

  const atBottom = logbox.scrollHeight - logbox.scrollTop - logbox.clientHeight < 32;
  logbox.innerHTML = "";
  for (const r of rows) {
    const d = document.createElement("div");
    d.style.color = r.col;
    d.textContent = (r.ts ? "[" + r.ts + "] " : "  ") + r.msg;
    logbox.append(d);
  }
  if (atBottom) logbox.scrollTop = logbox.scrollHeight;
}

async function refreshLLM() {
  try { renderLLM(await api("/api/llm/status")); } catch (e) {}
}

let llmEventCount = 0;

function startLLMPolling(fast = true) {
  if (llmPollTimer) clearInterval(llmPollTimer);
  const interval = fast ? 1200 : 3000;
  llmPollTimer = setInterval(async () => {
    let st; try { st = await api("/api/llm/status"); } catch { return; }
    renderLLM(st);
    const n = (st.events || []).length;
    // Reste rapide tant qu'il charge ou génère
    if (st.state === "loading" || st.gen_active) {
      if (!fast) startLLMPolling(true);
      return;
    }
    if (n !== llmEventCount) {          // nouvelle activité → repasse en rapide
      llmEventCount = n;
      if (!fast) startLLMPolling(true);
      return;
    }
    if (fast) startLLMPolling(false);   // plus rien → ralentit
  }, interval);
}

$("#sys-llm-load").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    await api("/api/llm/load", "POST", {});
    toast(window.t("system.llm_load_started"));
    startLLMPolling();
  } catch (err) { toast(err.message, true); }
  finally { e.target.disabled = false; }
});

// --------------------------------------------------------------------------- //
//  GALERIE
// --------------------------------------------------------------------------- //
// Libellés courts affichés en badge sur chaque vignette de la galerie, selon la colonne
// "source" (gallery.source). Les anciennes images sans source (NULL/legacy) n'affichent pas
// de badge plutôt qu'un badge incorrect.
const GALLERY_SOURCE_LABELS = {
  avatar: "Avatar", chat: "Chat", emotion: "Emotion",
  studio: "Studio", group: "Groupe", background: "Fond",
};

async function loadGallery() {
  const filter = $("#gallery-filter");
  let chars;
  try { chars = await api("/api/characters"); } catch { chars = []; }
  const cur = filter.value;
  filter.innerHTML = "";
  filter.append(el("option", { value: "" }, "Tous les characters"));
  for (const c of chars) filter.append(el("option", { value: c.id }, c.name));
  filter.value = cur;
  filter.onchange = () => renderGallery(filter.value);
  renderGallery(filter.value);
}

async function renderGallery(characterId) {
  const grid = $("#gallery-grid");
  grid.innerHTML = "";
  let items;
  try {
    items = await api("/api/gallery" + (characterId ? "?character_id=" + characterId : ""));
  } catch (e) { return toast(e.message, true); }
  if (!items.length) {
    grid.append(el("div", { class: "empty", style: "grid-column:1/-1" },
      "No image — generate an avatar, a chat image, or a Studio creation."));
    return;
  }
  for (const it of items) {
    const label = GALLERY_SOURCE_LABELS[it.source];
    const cell = el("div", { class: "g" },
      el("img", { src: imgUrl(it.image), loading: "lazy" }),
      el("div", { class: "cap" }, it.prompt || "")
    );
    if (label) {
      cell.append(el("span", { class: "g-badge" }, label));
    }
    // Clic sur n'importe quelle zone de la carte -> lightbox
    cell.addEventListener("click", (e) => {
      // Ne pas intercepter les futurs boutons internes explicites
      if (e.target.tagName === "BUTTON" || e.target.closest("button")) return;
      const img = cell.querySelector("img");
      if (img) lightbox(img.src.split("?")[0]);
    });
    grid.append(cell);
  }
}

// --------------------------------------------------------------------------- //
//  SETTINGS
// --------------------------------------------------------------------------- //
const SF = ["llm_backend", "lmstudio_url", "lmstudio_model", "lmstudio_api_key",
            "lmstudio_native_timeout", "lmstudio_request_timeout", "lmstudio_load_wait_timeout",
            "lmstudio_post_load_delay", "lmstudio_post_unload_delay",
            "comfy_vram_release_timeout", "comfy_busy_wait_timeout",
            "llm_temperature", "llm_util_enabled", "llm_util_model",
            "tts_enabled", "tts_url", "tts_autolaunch", "tts_engine", "tts_device",
            "tts_vram_offload_enabled", "tts_language", "tts_speed", "tts_exaggeration", "tts_cfg_weight",
            "tts_temperature", "tts_autoplay",
            "whisper_enabled", "whisper_model_size", "whisper_device", "whisper_language",
            "comfy_url",
            "image_resolution",
            "persona_name", "persona_description", "krea2_user_token", "krea2_char2_lora", "krea2_char2_lora_strength", "default_negative", "vram_mode"]

let personaImage = "";

async function refreshLMStudioModelLists(settings = null) {
  const mainSel = $("#s-lmstudio_model");
  const utilSel = $("#s-llm_util_model");
  const status = $("#lmstudio-model-list-status");
  const currentMain = settings ? (settings.lmstudio_model || "") : (mainSel?.value || "");
  const currentUtil = settings ? (settings.llm_util_model || "") : (utilSel?.value || "");
  if (status) status.textContent = "Reading models from LM Studio…";
  try {
    const res = await api("/api/llm/catalog");
    const ids = (res.entries || []).map(x => x.id || x.name).filter(Boolean);
    const fill = (sel, firstLabel, current) => {
      if (!sel) return;
      sel.innerHTML = "";
      sel.append(el("option", { value: "" }, firstLabel));
      for (const id of ids) sel.append(el("option", { value: id }, id));
      if (current && !ids.includes(current)) {
        sel.append(el("option", { value: current }, `${current} (not currently exposed)`));
      }
      sel.value = current;
    };
    fill(mainSel, "— auto / only loaded model —", currentMain);
    fill(utilSel, "— reuse conversation model —", currentUtil);
    if (status) status.textContent = res.reachable
      ? `${ids.length} model(s) exposed by LM Studio /v1/models.`
      : (res.error || "LM Studio is unavailable.");
  } catch (e) {
    if (status) status.textContent = e.message;
  }
}

async function refreshPersonaKreaLoraSelect(settings = null) {
  const sel = $("#s-krea2_char2_lora");
  if (!sel) return;
  const current = settings ? (settings.krea2_char2_lora || "") : (sel.value || "");
  sel.innerHTML = "";
  sel.append(el("option", { value: "" }, "— none / disabled —"));
  let names = [];
  try {
    const allComfy = (await api("/api/comfy/loras")).loras || [];
    let kreaCatalog = [];
    try { kreaCatalog = await api("/api/models/files?kind=lora&family=krea2"); } catch (e) {}
    const portableBase = name => String(name || "").replace(/\\/g, "/").split("/").pop().toLowerCase();
    const kreaBases = new Set(kreaCatalog.map(f => portableBase(f.name)));
    names = kreaBases.size ? allComfy.filter(n => kreaBases.has(portableBase(n))) : allComfy;
    if (!names.length && kreaCatalog.length) names = kreaCatalog.map(f => f.loader_name || f.name).filter(Boolean);
  } catch (e) {}
  for (const n of names) sel.append(el("option", { value: n }, n));
  if (current && !names.includes(current)) {
    sel.append(el("option", { value: current }, current + " (not listed by ComfyUI)"));
  }
  sel.value = current;
}

async function loadSettings() {
  let s;
  try { s = await api("/api/settings"); }
  catch (e) { return toast(e.message, true); }
  for (const k of SF) { const n = $("#s-" + k); if (n) n.value = s[k] || ""; }
  await refreshLMStudioModelLists(s);
  const utilFallbackCb = $("#s-llm_util_fallback");
  if (utilFallbackCb) utilFallbackCb.checked = String(s.llm_util_fallback) === "true";
  const vramOffloadCb = $("#s-lmstudio_vram_offload_enabled");
  if (vramOffloadCb) vramOffloadCb.checked = String(s.lmstudio_vram_offload_enabled) !== "false";
  const vramReloadCb = $("#s-lmstudio_reload_on_demand");
  if (vramReloadCb) vramReloadCb.checked = String(s.lmstudio_reload_on_demand) !== "false";
  const comfyOffloadCb = $("#s-comfy_vram_offload_before_lmstudio");
  if (comfyOffloadCb) comfyOffloadCb.checked = String(s.comfy_vram_offload_before_lmstudio) !== "false";
  const unloadConvCb = $("#s-lmstudio_unload_conversation_before_utility");
  if (unloadConvCb) unloadConvCb.checked = String(s.lmstudio_unload_conversation_before_utility) !== "false";
  const unloadUtilCb = $("#s-lmstudio_unload_utility_after_use");
  if (unloadUtilCb) unloadUtilCb.checked = String(s.lmstudio_unload_utility_after_use) !== "false";
  const retryLmCb = $("#s-lmstudio_retry_after_load_error");
  if (retryLmCb) retryLmCb.checked = String(s.lmstudio_retry_after_load_error) !== "false";
  currentMaxTokens = parseInt(s.llm_max_tokens, 10) || 250;
  const ctxSlider = $("#s-llm_ctx_slider");
  if (ctxSlider) {
    ctxSlider.value = String(parseInt(s.llm_ctx, 10) || 8192);
    refreshContextBudgetPreview();
  }
  personaImage = s.persona_image || "";
  await refreshPersonaKreaLoraSelect(s);
  renderPersonaPreview();
  toggleLLMBackendFields();
  whisperEnabled = String(s.whisper_enabled) === "true";
  ttsEnabled = String(s.tts_enabled) === "true";
  ttsAutoplay = String(s.tts_autoplay) !== "false";
  updateTTSEngineUI();
  refreshTTSStatusLine();
  refreshLLMUtilStatus();
  refreshLMStudioVRAMStatus();
  loadFlux2ModeSection(s);
}


// ===========================================================================
//  FLUX 2 KLEIN — mode GGUF / Safetensors
// ===========================================================================
async function loadFlux2ModeSection(s) {
  const mode = s.flux2_loader_mode || "gguf";
  const modeGguf = $("#s-flux2_mode_gguf");
  const modeSt   = $("#s-flux2_mode_st");
  if (modeGguf) modeGguf.checked = mode === "gguf";
  if (modeSt)   modeSt.checked   = mode === "safetensors";
  await Promise.all([
    populateFlux2UnetSelect("s-img_unet_gguf",        "gguf",         s.img_unet_gguf || s.img_unet || ""),
    populateFlux2UnetSelect("s-img_unet_safetensors", "safetensors",  s.img_unet_safetensors || ""),
  ]);
  updateFlux2ModeUI(mode);
}

async function populateFlux2UnetSelect(selectId, kind, currentVal) {
  const sel = $("#" + selectId);
  if (!sel) return;
  sel.innerHTML = '<option value="">— choisir —</option>';
  try {
    const files = await api("/api/models/files?kind=unet&family=flux2_klein").catch(() => []);
    const ext   = kind === "gguf" ? ".gguf" : ".safetensors";
    const filtered = files.filter(f => f.name && f.name.toLowerCase().endsWith(ext));
    for (const f of filtered) {
      sel.append(el("option", { value: f.name }, f.name + " (" + (f.size_human || "?") + ")"));
    }
    sel.value = currentVal || "";
  } catch (e) { /* silencieux */ }
}

function updateFlux2ModeUI(mode) {
  const ggufRow = $("#flux2-unet-gguf-row");
  const stRow   = $("#flux2-unet-st-row");
  const status  = $("#flux2-mode-status");
  if (ggufRow) ggufRow.style.display = (mode === "gguf")        ? "" : "none";
  if (stRow)   stRow.style.display   = (mode === "safetensors") ? "" : "none";
  if (status) {
    const sel = mode === "gguf"
      ? ($("#s-img_unet_gguf")        || {}).value
      : ($("#s-img_unet_safetensors") || {}).value;
    if (!sel) {
      status.innerHTML = "<span style='color:var(--danger);'>\u2717 No UNet " + (mode === "gguf" ? "GGUF" : "Safetensors") + " configured — select a file above.</span>";
    } else {
      status.innerHTML = "<span style='color:var(--ok);'>\u2713 Mode " + (mode === "gguf" ? "GGUF" : "Safetensors") + " active \u2014 " + sel + "</span>";
    }
  }
}

for (const radioId of ["s-flux2_mode_gguf", "s-flux2_mode_st"]) {
  const radio = $("#" + radioId);
  if (radio) radio.addEventListener("change", () => updateFlux2ModeUI(radio.value));
}
for (const selId of ["s-img_unet_gguf", "s-img_unet_safetensors"]) {
  const sel = $("#" + selId);
  if (sel) sel.addEventListener("change", () => {
    const mode = ($("#s-flux2_mode_gguf") || {}).checked ? "gguf" : "safetensors";
    updateFlux2ModeUI(mode);
  });
}

const QWEN_TTS_LANGUAGES = new Set(["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"]);

function updateTTSEngineUI() {
  const engine = (($("#s-tts_engine") || {}).value || "chatterbox").toLowerCase();
  const note = $("#tts-engine-note");
  const controls = $("#tts-chatterbox-controls");
  if (controls) controls.style.display = engine === "chatterbox" ? "flex" : "none";
  if (note) {
    note.textContent = engine === "qwen"
      ? window.t("settings.tts_qwen_note")
      : window.t("settings.tts_chatterbox_note");
  }
  const language = $("#s-tts_language");
  if (language) {
    for (const option of language.options) {
      option.disabled = engine === "qwen" && !QWEN_TTS_LANGUAGES.has(option.value);
    }
    if (language.selectedOptions[0] && language.selectedOptions[0].disabled) language.value = "en";
  }
}

const _ttsEngineSelect = $("#s-tts_engine");
if (_ttsEngineSelect) _ttsEngineSelect.addEventListener("change", updateTTSEngineUI);

async function refreshTTSStatusLine() {
  const line = $("#tts-status-line");
  if (!line) return;
  try {
    const st = await api("/api/tts/status");
    const engineLabel = st.engine === "qwen" ? "Qwen3-TTS 0.6B" : "Chatterbox V3";
    if (st.engine_mismatch) line.textContent = window.t("common.error") + " : " + st.error;
    else if (st.model_status === "ready") line.textContent = `${engineLabel} — ${window.t("system.model_ready_device", { device: st.device || "?" })}`;
    else if (st.model_status === "loading") line.textContent = `${engineLabel} — ${window.t("system.model_loading")}`;
    else if (st.error) line.textContent = window.t("common.error") + " : " + st.error;
    else line.textContent = st.reachable ? window.t("system.waiting") : window.t("system.offline");
  } catch (e) { line.textContent = ""; }
}
const _ttsStartBtn = $("#tts-start-btn");
if (_ttsStartBtn) _ttsStartBtn.addEventListener("click", async () => {
  _ttsStartBtn.disabled = true; _ttsStartBtn.innerHTML = '<span class="spinner"></span>';
  try { await api("/api/tts/start", "POST", {}); toast(window.t("settings.tts_starting")); refreshTTSStatusLine(); }
  catch (e) { toast(e.message, true); }
  finally { _ttsStartBtn.disabled = false; _ttsStartBtn.textContent = window.t("settings.tts_start_btn"); }
});
const _ttsRestartBtn = $("#tts-restart-btn");
if (_ttsRestartBtn) _ttsRestartBtn.addEventListener("click", async () => {
  try { await api("/api/tts/restart", "POST", {}); toast(window.t("system.tts_restarting")); refreshTTSStatusLine(); }
  catch (e) { toast(e.message, true); }
});
const _ttsKillBtn = $("#tts-kill-btn");
if (_ttsKillBtn) _ttsKillBtn.addEventListener("click", async () => {
  if (!confirm(window.t("settings.tts_stop_confirm"))) return;
  try { await api("/api/tts/kill", "POST", {}); toast(window.t("system.tts_stopped")); refreshTTSStatusLine(); }
  catch (e) { toast(e.message, true); }
});

function toggleLLMBackendFields() {
  const lm = $("#llm-lmstudio-fields");
  if (lm) lm.style.display = "block";
  refreshLLMBackendStatus();
  updateContextBackendNote("lmstudio");
}

// --------------------------------------------------------------------------- //
//  Contexte maximal (slider indépendant du backend) — miroir JS de
//  context_manager.get_context_distribution() pour un aperçu local instantané,
//  sans aller-retour serveur a chaque deplacement du slider.
// --------------------------------------------------------------------------- //
function clientClamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function clientContextDistribution(contextLimit, responseMaxTokens) {
  contextLimit = clientClamp(contextLimit, 2048, 32768);
  responseMaxTokens = clientClamp(responseMaxTokens, 50, 600);
  const safetyMargin = 384;
  const hardInputLimit = Math.max(768, contextLimit - responseMaxTokens - safetyMargin);
  let inputBudget = Math.min(hardInputLimit, Math.round(contextLimit * 0.75));
  inputBudget = Math.max(768, inputBudget);

  let memoryBudget, summaryBudget, recentMessages;
  if (inputBudget >= 4500) {
    memoryBudget = clientClamp(Math.round(inputBudget * 0.20), 700, 1400);
    summaryBudget = clientClamp(Math.round(inputBudget * 0.20), 900, 1500);
    recentMessages = clientClamp(Math.round(inputBudget / 500), 8, 14);
  } else if (inputBudget >= 2500) {
    memoryBudget = clientClamp(Math.round(inputBudget * 0.17), 400, 900);
    summaryBudget = clientClamp(Math.round(inputBudget * 0.17), 500, 1000);
    recentMessages = clientClamp(Math.round(inputBudget / 575), 6, 10);
  } else {
    memoryBudget = clientClamp(Math.round(inputBudget * 0.15), 250, 500);
    summaryBudget = clientClamp(Math.round(inputBudget * 0.15), 300, 600);
    recentMessages = clientClamp(Math.round(inputBudget / 650), 4, 7);
  }
  return { contextLimit, responseMaxTokens, safetyMargin, inputBudget, memoryBudget, summaryBudget, recentMessages };
}

function updateContextBackendNote() {
  const note = $("#llm-context-backend-note");
  if (!note) return;
  note.textContent = "AmiorAI uses this value to build prompts below the real context configured for the selected LM Studio model.";
}

function refreshContextBudgetPreview() {
  const slider = $("#s-llm_ctx_slider");
  const valueEl = $("#s-llm_ctx_value");
  const preview = $("#llm-context-budget-preview");
  if (!slider || !valueEl || !preview) return;
  const ctx = parseInt(slider.value, 10);
  valueEl.textContent = `${ctx} tokens`;
  const dist = clientContextDistribution(ctx, currentMaxTokens);
  preview.textContent = `Memory ~${dist.memoryBudget} · Summary ~${dist.summaryBudget} · ${dist.recentMessages} recent messages`;
}

const _llmCtxSlider = $("#s-llm_ctx_slider");
if (_llmCtxSlider) _llmCtxSlider.addEventListener("input", refreshContextBudgetPreview);

const _llmContextSaveBtn = $("#llm-context-save-btn");
if (_llmContextSaveBtn) _llmContextSaveBtn.addEventListener("click", async () => {
  const slider = $("#s-llm_ctx_slider");
  const status = $("#llm-context-status");
  const value = parseInt(slider.value, 10);
  _llmContextSaveBtn.disabled = true;
  try {
    // Reutilise /api/settings existant, sauvegarde uniquement llm_ctx. Le recalcul
    // memoire/resume/messages recents se fait cote serveur au prochain message (mode
    // "auto" de get_context_distribution) : pas besoin de forcer quoi que ce soit ici.
    await api("/api/settings", "POST", { llm_ctx: String(value) });
    status.textContent = window.t("settings.context_saved");
    const panel = _llmContextSaveBtn.closest(".panel");
    const sectionStatus = panel ? panel.querySelector(".settings-section-status") : null;
    const sectionButton = panel ? panel.querySelector(".settings-section-save") : null;
    if (sectionStatus) {
      sectionStatus.style.color = "var(--ok)";
      sectionStatus.textContent = "✓ " + window.t("settings.section_saved");
    }
    if (sectionButton) sectionButton.classList.remove("attention");
    refreshContextBudgetPreview();
  } catch (e) {
    status.textContent = "Error: " + e.message;
  } finally {
    _llmContextSaveBtn.disabled = false;
  }
});

function statusBadge(kind, text) {
  // kind: "ready" (vert) / "warn" (orange) / "error" (rouge) / "active" (bleu/violet)
  return el("span", { class: "badge badge-" + kind }, text);
}

async function refreshLLMBackendStatus() {
  const box = $("#llm-backend-status");
  if (!box) return;
  box.innerHTML = '<span class="hint">Checking LM Studio…</span>';
  try {
    const st = await api("/api/llm/backend_status?backend=lmstudio");
    box.innerHTML = "";
    box.append(st.reachable ? statusBadge("ready", "✓ LM Studio connected") : statusBadge("error", "LM Studio unreachable"));
    if (st.models && st.models.length) {
      const names = st.models.map(m => (typeof m === "string" ? m : m.id)).filter(Boolean).join(", ");
      box.append(el("span", { class: "hint" }, `Available model IDs: ${names}`));
    }
  } catch (e) { box.innerHTML = ""; box.append(statusBadge("error", window.t("system.check_error"))); }
}

const _llmLoadBtn = $("#llm-load-btn");
if (_llmLoadBtn) _llmLoadBtn.addEventListener("click", async () => {
  const st = $("#llm-action-status");
  _llmLoadBtn.disabled = true; st.innerHTML = '<span class="spinner"></span> loading…';
  try {
    const res = await api("/api/llm/load", "POST", {});
    st.textContent = res.ok ? window.t("system.llm_load_started_short") : (window.t("common.error") + " : " + res.error);
    setTimeout(refreshLLMBackendStatus, 1000);
  } catch (e) { st.textContent = "Error: " + e.message; }
  finally { _llmLoadBtn.disabled = false; }
});
const _llmUnloadBtn = $("#llm-unload-btn");
if (_llmUnloadBtn) _llmUnloadBtn.addEventListener("click", async () => {
  const st = $("#llm-action-status");
  try { await api("/api/llm/unload", "POST", {}); st.textContent = window.t("system.llm_unloaded"); refreshLLMBackendStatus(); }
  catch (e) { st.textContent = "Erreur : " + e.message; }
});
const _llmTestBtn = $("#llm-test-btn");
if (_llmTestBtn) _llmTestBtn.addEventListener("click", async () => {
  const st = $("#llm-action-status");
  _llmTestBtn.disabled = true; st.innerHTML = '<span class="spinner"></span> test in progress…';
  try {
    const res = await api("/api/llm/test", "POST", {});
    st.textContent = res.ok
      ? `✓ response received in ${res.duration_s}s : "${res.reply}"`
      : `✗ failed (${res.duration_s}s) : ${res.error}`;
  } catch (e) { st.textContent = "Error: " + e.message; }
  finally { _llmTestBtn.disabled = false; }
});

// ---- LLM utilitaire : statut et test, totalement separes du panneau conversationnel ----
async function refreshLLMUtilStatus() {
  const box = $("#llm-util-status");
  if (!box) return;
  const enabled = (($("#s-llm_util_enabled") || {}).value || "false") === "true";
  if (!enabled) {
    box.innerHTML = "";
    box.append(statusBadge("warn", "disabled"));
    return;
  }
  box.innerHTML = '<span class="hint">Checking…</span>';
  try {
    const st = await api("/api/llm/util_status");
    box.innerHTML = "";
    box.append(st.reachable ? statusBadge("ready", "✓ connected") : statusBadge("error", "unreachable"));
    if (st.models && st.models.length) {
      box.append(el("span", { class: "hint" }, `Model(s) detected: ${st.models.join(", ")}`));
    } else if (st.error) {
      box.append(el("span", { class: "hint" }, st.error));
    }
  } catch (e) { box.innerHTML = ""; box.append(statusBadge("error", window.t("system.check_error"))); }
}

const _llmUtilEnabledSel = $("#s-llm_util_enabled");
if (_llmUtilEnabledSel) _llmUtilEnabledSel.addEventListener("change", refreshLLMUtilStatus);

const _llmUtilTestBtn = $("#llm-util-test-btn");
if (_llmUtilTestBtn) _llmUtilTestBtn.addEventListener("click", async () => {
  const result = $("#llm-util-test-result");
  _llmUtilTestBtn.disabled = true;
  result.innerHTML = '<span class="spinner"></span> test in progress…';
  try {
    const res = await api("/api/llm/util_test", "POST", {});
    result.textContent = res.ok
      ? `✓ Utility: model ${res.model} via ${res.url} — response ${res.reply} (${res.duration_s}s)`
      : `✗ Utility unavailable (${res.duration_s}s) : ${res.error}`;
    refreshLLMUtilStatus();
  } catch (e) { result.textContent = "Error: " + e.message; }
  finally { _llmUtilTestBtn.disabled = false; }
});

// ---- Gestion VRAM LM Studio : statut et bouton Unload maintenant ----
async function refreshLMStudioVRAMStatus() {
  const box = $("#lmstudio-vram-status");
  if (!box) return;
  box.innerHTML = '<span class="hint">Checking…</span>';
  let st;
  try { st = await api("/api/llm/lmstudio_vram_status"); }
  catch (e) { box.innerHTML = ""; box.append(statusBadge("error", window.t("system.check_error"))); return; }

  box.innerHTML = "";
  if (!st.applicable) {
    box.append(statusBadge("warn", "LM Studio VRAM management unavailable"));
    return;
  }
  if (st.error) {
    box.append(statusBadge("error", "unreachable"));
    box.append(el("span", { class: "hint" }, st.error));
    return;
  }
  if (st.conversational_applicable) {
    box.append(st.conversational_loaded
      ? statusBadge("active", "chat model loaded")
      : statusBadge("ready", "conversationnel libre"));
  }
  if (st.utility_applicable) {
    box.append(st.utility_loaded
      ? statusBadge("active", "utility model loaded")
      : statusBadge("ready", "utilitaire libre"));
  }
}


const _lmstudioVramUnloadBtn = $("#lmstudio-vram-unload-btn");
if (_lmstudioVramUnloadBtn) _lmstudioVramUnloadBtn.addEventListener("click", async () => {
  const result = $("#lmstudio-vram-unload-result");
  _lmstudioVramUnloadBtn.disabled = true;
  result.innerHTML = '<span class="spinner"></span> unloading…';
  try {
    const res = await api("/api/llm/lmstudio_vram_unload_now", "POST", {});
    result.textContent = res.ok ? res.message : ("✗ " + res.error);
    refreshLMStudioVRAMStatus();
  } catch (e) { result.textContent = "Error: " + e.message; }
  finally { _lmstudioVramUnloadBtn.disabled = false; }
});

// ===========================================================================
//  LoRA MANAGER — v14
//  Trois zones :
//    1. Pile active (loras table) — injectée dans les workflows
//    2. Bibliothèque (model_files kind=lora) — catalogue local scanné
//    3. Presets — snapshots de la pile active
// ===========================================================================

const LORA_FAMILY_LABELS = {
  flux2_klein: "Flux 2 Klein", flux: "Flux 1", sdxl: "SDXL", krea2: "Krea 2",
  sd15: "SD 1.5", zimage: "Z-Image",
};

// Familys supportant un CLIP strength distinct
const LORA_HAS_CLIP = new Set(["sd15", "sdxl", "flux", "flux2_klein"]);

// --------------------------------------------------------------------------
//  1. PILE ACTIVE
// --------------------------------------------------------------------------
async function loadLoras() {
  await refreshLoraStack();
  await refreshLoraLib();
  await refreshLoraPresets();
  refreshCivitaiTokenStatus();
}

async function refreshLoraStack() {
  const box = $("#lora-active-list");
  if (!box) return;
  let loras;
  try { loras = await api("/api/loras"); } catch (e) { box.innerHTML = ""; return; }
  box.innerHTML = "";
  if (!loras.length) {
    box.append(el("div", { class: "hint" }, "No LoRA in the stack — add one from the library or manually."));
    return;
  }
  // Family du workflow active (pour signaler les incompatibilités)
  const activeFamilyEl = $("#studio-family");
  const activeFamily = activeFamilyEl ? activeFamilyEl.value : "";

  for (const lo of loras) {
    const loFamily = lo.family || "";
    const compat = !loFamily || !activeFamily || loFamily === activeFamily;
    const compatBadge = !loFamily ? el("span", { class: "lm-badge lm-badge-unknown", title: "Unknown family — will be attempted" }, "?")
      : compat ? el("span", { class: "lm-badge lm-badge-ok", title: `Compatible ${LORA_FAMILY_LABELS[loFamily]||loFamily}` }, "✓")
               : el("span", { class: "lm-badge lm-badge-warn", title: `Family ${loFamily} ≠ workflow ${activeFamily}` }, "⚠");

    const alwaysBtn = el("button", {
      class: "btn sm ghost lm-toggle" + (lo.always_on ? " active" : ""),
      title: lo.always_on ? "Always active — clic pour passer en mode trigger" : "Trigger mode — click for always active",
      onclick: async () => {
        await api("/api/lora/toggle", "POST", { id: lo.id, always_on: !lo.always_on });
        refreshLoraStack();
      }
    }, lo.always_on ? "⭐ Toujours" : "🔑 Trigger");

    const favBtn = el("button", {
      class: "btn sm ghost" + (lo.favorite ? " lm-fav-on" : ""),
      title: lo.favorite ? "Retirer des favoris" : "Marquer comme favori",
      onclick: async () => {
        await api("/api/lora/favorite", "POST", { id: lo.id, favorite: !lo.favorite });
        refreshLoraStack();
      }
    }, "★");

    const strengthInfo = el("span", { class: "lm-strength" },
      `⚖ ${lo.strength}` + (lo.clip_strength && lo.clip_strength !== 1.0 ? ` / ${lo.clip_strength}` : ""));

    const trigInfo = lo.always_on ? el("span") : el("span", { class: "lm-trigger" },
      lo.trigger ? `🔑 "${lo.trigger}"` : el("em", {}, "(pas de trigger — idle)"));

    const familyTag = loFamily
      ? el("span", { class: "lm-family-tag" }, LORA_FAMILY_LABELS[loFamily] || loFamily)
      : el("span");

    const row = el("div", { class: "lm-stack-row" + (compat ? "" : " lm-incompat") },
      compatBadge,
      el("div", { class: "lm-stack-info" },
        el("span", { class: "lm-filename" }, lo.file),
        el("div", { class: "lm-meta-row" }, strengthInfo, trigInfo, familyTag,
          lo.note ? el("span", { class: "lm-note" }, lo.note) : el("span"))),
      el("div", { class: "lm-stack-actions" }, alwaysBtn, favBtn,
        el("button", { class: "btn sm danger", title: "Retirer de la pile",
          onclick: async () => {
            await api("/api/lora/delete", "POST", { id: lo.id }); refreshLoraStack();
          }
        }, "✕"))
    );
    box.append(row);
  }
}

// Vider toute la pile
const _loraStackClear = $("#lora-stack-clear-btn");
if (_loraStackClear) _loraStackClear.addEventListener("click", async () => {
  if (!confirm("Clear the whole active stack? LoRAs will no longer be injected.")) return;
  const loras = await api("/api/loras");
  for (const lo of loras) await api("/api/lora/delete", "POST", { id: lo.id });
  refreshLoraStack();
  toast(window.t("lora.toasts.stack_cleared"));
});

// Refresh la pile
const _loraStackRefresh = $("#lora-stack-refresh");
if (_loraStackRefresh) _loraStackRefresh.addEventListener("click", refreshLoraStack);

// Ajouter manuellement à la pile
const _loraAdd = $("#lora-add");
if (_loraAdd) _loraAdd.addEventListener("click", async () => {
  const file = ($("#lora-file") || {}).value.trim();
  if (!file) return toast("Enter the LoRA file.", true);
  try {
    await api("/api/lora/save", "POST", {
      file,
      trigger:        ($("#lora-trigger") || {}).value.trim(),
      strength:       parseFloat(($("#lora-strength") || {}).value || "0.8"),
      clip_strength:  parseFloat(($("#lora-clip-strength") || {}).value || "1.0"),
      always_on:      ($("#lora-always") || {}).value === "1",
      family:         ($("#lora-family") || {}).value || "",
      note:           ($("#lora-note") || {}).value.trim(),
    });
    const f = $("#lora-file"); if (f) f.value = "";
    const t = $("#lora-trigger"); if (t) t.value = "";
    const n = $("#lora-note"); if (n) n.value = "";
    toast(window.t("lora.toasts.added")); refreshLoraStack();
  } catch (e) { toast(e.message, true); }
});

// --------------------------------------------------------------------------
//  2. BIBLIOTHÈQUE
// --------------------------------------------------------------------------
async function refreshLoraLib() {
  const box = $("#lora-lib-list");
  if (!box) return;
  box.innerHTML = '<span class="hint">Chargement…</span>';
  const family   = ($("#lora-lib-family") || {}).value  || "";
  const search   = ($("#lora-lib-search") || {}).value.trim() || "";
  const favonly  = ($("#lora-lib-favonly") || {}).checked;
  const prevFilter = ($("#lora-lib-preview-filter") || {}).value || "all";

  let items = [], comfyLoras = [], previews = {}, civitaiMeta = {};
  try {
    const qs = [family && `family=${encodeURIComponent(family)}`,
                search && `search=${encodeURIComponent(search)}`,
                favonly && `favorites_only=true`].filter(Boolean).join("&");
    [items, { loras: comfyLoras = [] }, previews, civitaiMeta] = await Promise.all([
      api("/api/lora/library" + (qs ? "?" + qs : "")),
      api("/api/comfy/loras").catch(() => ({ loras: [] })),
      api("/api/lora/previews").catch(() => ({})),
      api("/api/civitai/metadata").catch(() => ({})),
    ]);
  } catch (e) {
    box.innerHTML = '<span class="hint">Library loading error.</span>'; return;
  }

  const comfySet      = new Set(comfyLoras);
  const comfyBasenames = new Map(comfyLoras.map(n => [n.split(/[/\\]/).pop().toLowerCase(), n]));

  // Filtre preview
  if (prevFilter === "with") items = items.filter(it => previews[it.name]);
  if (prevFilter === "without") items = items.filter(it => !previews[it.name]);

  box.innerHTML = "";
  if (!items.length) {
    box.append(el("div", { class: "hint" },
      "No LoRA matches these filters."));
    return;
  }

  for (const it of items) {
    // Civitai : chercher par model_file_id (champ id de la library)
    const civMeta = civitaiMeta[it.id] || null;
    box.append(buildLoraCard(it, previews[it.name] || null, comfyLoras, comfySet, comfyBasenames, civMeta));
  }
}

// --------------------------------------------------------------------------
//  Construction d'une carte LoRA visuelle
// --------------------------------------------------------------------------
function buildLoraCard(it, preview, comfyLoras, comfySet, comfyBasenames, civMeta) {
  const inStack      = it.in_stack;
  const stackEntry   = it.stack_entry;
  const famLabel     = LORA_FAMILY_LABELS[it.family] || (it.family || "?");
  const nameLower    = it.name.toLowerCase();
  const comfyKnown   = comfyLoras.length === 0 ? null
    : comfySet.has(it.name) || comfyBasenames.has(nameLower);
  const resolvedName = comfySet.has(it.name) ? it.name
    : (comfyBasenames.get(nameLower) || it.name);

  // --- Priorité preview : locale choisie > locale générée > Civitai > placeholder ---
  const civitaiPreviewUrl = (civMeta && civMeta.civitai_preview_path)
    ? `/lora_preview/civitai/${civMeta.civitai_preview_path}` : null;
  const effectivePreviewUrl = (preview && preview.preview_path)
    ? imgUrl(preview.preview_path)
    : civitaiPreviewUrl;
  const previewSource = (preview && preview.preview_path) ? "local"
    : civitaiPreviewUrl ? "civitai" : null;

  // --- Miniature ---
  let thumb;
  if (effectivePreviewUrl) {
    thumb = el("img", {
      class: "lm-card-thumb",
      src: effectivePreviewUrl,
      title: previewSource === "civitai" ? "Preview Civitai (clic pour agrandir)" : "Clic pour agrandir",
      onclick: () => lightbox(effectivePreviewUrl),
    });
  } else {
    thumb = el("div", { class: "lm-card-thumb lm-card-nothumb" },
      el("span", {}, "Preview\nabsent"));
  }

  // --- Badge ComfyUI ---
  const comfyBadge = comfyLoras.length === 0 ? null :
    comfyKnown
      ? el("span", { class: "lm-badge lm-badge-ok", title: `Reconnu par ComfyUI : ${resolvedName}` }, "C✓")
      : el("span", { class: "lm-badge lm-badge-warn", title: "Not found in ComfyUI" }, "C?");

  // --- Badges overlay (ComfyUI + source preview) ---
  const overlayBadges = el("div", { class: "lm-card-badge-overlay" });
  if (comfyBadge) overlayBadges.append(comfyBadge);
  if (previewSource === "civitai") {
    overlayBadges.append(el("span", {
      class: "lm-badge", style: "background:rgba(30,144,255,.85); color:#fff; margin-top:4px;",
      title: "Preview depuis Civitai"
    }, "Civ"));
  }

  // --- Civitai info block ---
  let civBlock = null;
  if (civMeta) {
    const st = civMeta.civitai_match_status;
    const isFound = st && st.startsWith("found");
    if (isFound) {
      const triggers = (civMeta.civitai_trigger_words || []).join(", ") || "—";
      const hashLabel = civMeta.hash_type === "AutoV2" ? "metadata" : "SHA-256 complet";

      // Statut preview granulaire
      let previewStatusEl;
      if (st === "found_with_preview") {
        previewStatusEl = el("span", { class: "lm-note", style: "color:var(--ok);" }, "✅ Preview downloaded");
      } else if (st === "found_preview_error") {
        previewStatusEl = el("span", { class: "lm-note", style: "color:var(--danger);" },
          `⚠ Preview error : ${civMeta.civitai_last_error || "unknown"}`);
      } else if (st === "found_no_preview_url") {
        previewStatusEl = el("span", { class: "lm-note" }, "— No preview available");
      } else {
        previewStatusEl = el("span");
      }

      civBlock = el("div", { class: "lm-civitai-block" },
        el("div", { class: "lm-civitai-badge" }, "🌐 Civitai"),
        el("div", { class: "lm-civitai-info" },
          el("strong", {}, civMeta.civitai_model_name || ""),
          civMeta.civitai_version_name ? el("span", { class: "hint" }, ` · ${civMeta.civitai_version_name}`) : el("span"),
          civMeta.civitai_creator ? el("div", { class: "hint" }, `par ${civMeta.civitai_creator}`) : el("span"),
          civMeta.civitai_base_model ? el("div", { class: "hint" }, `Base : ${civMeta.civitai_base_model}`) : el("span"),
          triggers !== "—" ? el("div", { class: "hint" }, `Triggers : ${triggers}`) : el("span"),
          el("div", { class: "hint", style: "margin-top:2px;" }, `Hash : ${hashLabel}`),
          previewStatusEl,
          el("div", { class: "row", style: "gap:4px; margin-top:6px; flex-wrap:wrap;" },
            civMeta.civitai_url
              ? el("a", { href: civMeta.civitai_url, target: "_blank", rel: "noopener",
                          class: "btn sm ghost", style: "font-size:11px;" }, "🔗 Fiche")
              : el("span"),
            // “Use as main” button only if Civitai preview exists
            // And a prioritized local preview already exists
            civitaiPreviewUrl && preview && preview.preview_path
              ? el("button", {
                  class: "btn sm ghost", style: "font-size:11px;",
                  title: "Use Civitai preview as main image",
                  onclick: async () => {
                    await api("/api/lora/preview/assign", "POST", {
                      lora_name: it.name, family: it.family || "",
                      source: "selected_gallery", image: civMeta.civitai_preview_path,
                    });
                    toast(window.t("lora.toasts.preview_set")); refreshLoraLib();
                  }
                }, "⬆ Use Civitai preview")
              : el("span"),
            // Retry preview button on error
            st === "found_preview_error"
              ? el("button", {
                  class: "btn sm ghost", style: "font-size:11px; color:var(--danger);",
                  onclick: async () => {
                    if (!it.id) return toast("ID manquant.", true);
                    await civitaiEnrichCard(it.id, null);
                  }
                }, "↺ Retry preview")
              : el("span")
          )
        )
      );
    } else if (st === "no_match") {
      civBlock = el("div", { class: "lm-civitai-block lm-civitai-nomatch" },
        el("span", { class: "hint" }, "No Civitai profile"));
    } else if (st) {
      // Error réseau, token, etc.
      const errLabel = _CIVITAI_STATUS_LABELS_SIMPLE[st] || st;
      civBlock = el("div", { class: "lm-civitai-block lm-civitai-nomatch" },
        el("span", { class: "hint", style: "color:var(--danger);" }, errLabel));
    }
  }

  // --- Boutons d'action ---
  const genBtn = el("button", {
    class: "btn sm ghost", title: "Generate une preview locale pour cette LoRA",
    onclick: () => openLoraPreviewGenModal(it.name, it.family || "", resolvedName, comfyKnown),
  }, "🎨 Generate");

  const chooseBtn = el("button", {
    class: "btn sm ghost", title: "Assigner une image existante",
    onclick: () => openLoraChooseModal(it.name, it.family || ""),
  }, "🖼 Choose");

  const civRefreshBtn = el("button", {
    class: "btn sm ghost civ-refresh-btn",
    title: "Interroger Civitai pour cette LoRA (automatique par hash)",
    onclick: async (e) => {
      if (!it.id) return toast("Missing file ID.", true);
      await civitaiEnrichCard(it.id, e.target.closest(".lm-card"));
    },
  }, "🌐 Civitai");

  const civLinkBtn = el("button", {
    class: "btn sm ghost",
    title: "Associer manuellement une fiche Civitai via URL",
    onclick: () => openCivitaiLinkModal(it.id, it.name),
  }, "🔗 Link Civitai");

  const editIdBtn = el("button", {
    class: "btn sm ghost",
    title: "Correct detected type and family",
    onclick: () => openIdentificationModal(it.id, it.name, civMeta),
  }, "✏ Identification");

  const viewBtn = effectivePreviewUrl
    ? el("button", { class: "btn sm ghost", onclick: () => lightbox(effectivePreviewUrl) }, "🔍 Voir")
    : null;

  const activateBtn = el("button", {
    class: "btn sm" + (inStack ? " ghost" : ""),
    title: inStack ? "Retirer de la pile active" : "Add to active stack",
    onclick: async () => {
      if (inStack && stackEntry) {
        await api("/api/lora/delete", "POST", { id: stackEntry.id });
        toast(`${it.name} removed from stack.`);
      } else {
        await api("/api/lora/save", "POST", {
          file: resolvedName, family: it.family || "",
          strength: 0.8, clip_strength: 1.0, always_on: false,
        });
        toast(`${resolvedName} added to stack.`);
      }
      refreshLoraStack(); refreshLoraLib();
    },
  }, inStack ? "✓ Active" : "＋ Enable");

  const favBtn = el("button", {
    class: "btn sm ghost" + (stackEntry && stackEntry.favorite ? " lm-fav-on" : ""),
    style: inStack ? "" : "opacity:.4",
    onclick: async () => {
      if (!stackEntry) return;
      await api("/api/lora/favorite", "POST", { id: stackEntry.id, favorite: !stackEntry.favorite });
      refreshLoraStack(); refreshLoraLib();
    },
  }, "★");

  // Bouton suppression fiche catalogue LoRA
  const deleteLoraBtn = el("div", {
    class: "lm-card-action",
    title: "Delete this catalog entry (file remains on disk)",
    style: "color:var(--danger); opacity:.65; cursor:pointer; font-size:1rem;",
    onclick: async () => {
      if (!confirm(`Delete entry “${it.name}” du catalogue LoRA ?

The file on disk is kept. You can reimport it via Refresh.`)) return;
      try {
        await api("/api/models/files/delete", "POST", { id: it.id });
        toast(`Entry deleted: ${it.name}`);
        refreshLoraLib();
      } catch(e) { toast(e.message, true); }
    },
  }, "🗑");

  const actions = el("div", { class: "lm-card-actions" }, genBtn, chooseBtn, civRefreshBtn, civLinkBtn, editIdBtn);
  if (viewBtn) actions.append(viewBtn);
  actions.append(activateBtn, favBtn, deleteLoraBtn);

  // Family effective + source d'identification (manuel > civitai > auto)
  const effFamily   = (civMeta && civMeta.effective_family) || it.family || "";
  const effFamLabel = LORA_FAMILY_LABELS[effFamily] || effFamily || "?";
  const idSource    = (civMeta && civMeta.identification_source_label) || "Automatic detection";
  const idSourceNote = (civMeta && (civMeta.manual_file_type || civMeta.manual_family))
    ? el("span", { class: "lm-note", style: "color:var(--accent);" }, "✎ Manuel")
    : (civMeta && civMeta.civitai_association_confirmed)
      ? el("span", { class: "lm-note", style: "color:#1e90ff;" }, "Civitai")
      : el("span");

  // --- Assemblage ---
  const card = el("div", {
    class: "lm-card" + (inStack ? " lm-card-active" : "")
                     + (comfyKnown === false ? " lm-incompat" : ""),
  },
    el("div", { class: "lm-card-thumb-wrap" }, thumb, overlayBadges),
    el("div", { class: "lm-card-body" },
      el("div", { class: "lm-filename", title: it.name }, it.name),
      el("div", { class: "lm-meta-row" },
        el("span", { class: "lm-family-tag", title: `Source : ${idSource}` }, effFamLabel),
        idSourceNote,
        el("span", { class: "hint" }, it.size_human),
        comfyKnown === false
          ? el("span", { class: "lm-note", style: "color:var(--danger)" }, "⚠ unknown ComfyUI")
          : (resolvedName !== it.name
              ? el("span", { class: "lm-note" }, `→ ${resolvedName}`)
              : el("span")),
        !effectivePreviewUrl
          ? el("span", { class: "lm-note", style: "color:var(--muted)" }, "— sans preview")
          : el("span", { class: "lm-note", style: "color:var(--ok)" },
              previewSource === "civitai" ? "✓ preview Civitai" : "✓ preview locale")),
      civBlock || el("span"),
      actions));
  return card;
}

// --------------------------------------------------------------------------
//  MODAL : Generate une preview LoRA
// --------------------------------------------------------------------------
const LORA_PREVIEW_DEFAULT_PROMPT =
  "A clear high-quality portrait of a person, centered composition, upper body, " +
  "neutral pose, looking at the camera, simple background, balanced lighting.";

function openLoraPreviewGenModal(loraName, family, resolvedName, comfyKnown) {
  if (comfyKnown === false) {
    toast(`⚠ This LoRA is not found in ComfyUI. Place the file in ComfyUI models/loras/ before generating.`, true);
  }
  const ta = el("textarea", { class: "prompt-edit", rows: 5 });
  ta.value = LORA_PREVIEW_DEFAULT_PROMPT;

  const wfInfo = el("div", { class: "hint", style: "margin-bottom:8px;" },
    `Workflow : preview.json · LoRA : ${resolvedName || loraName}`);

  const previewBox = el("div", { id: "lora-prev-gen-result" });

  const resetBtn = el("button", { class: "btn sm ghost",
    onclick: () => { ta.value = LORA_PREVIEW_DEFAULT_PROMPT; }
  }, "Default prompt");

  let close;
  const genBtn = el("button", { class: "btn", onclick: async () => {
    const prompt = ta.value.trim();
    if (!prompt) return toast(window.t("common.prompt_required"), true);
    genBtn.disabled = true;
    genBtn.innerHTML = '<span class="spinner"></span> Generation…';
    try {
      const res = await api("/api/lora/preview/generate", "POST", {
        lora_name: loraName, family: family || "flux2_klein",
        prompt, seed: null,
      });
      // Afficher l'image générée dans la modal
      previewBox.innerHTML = "";
      const img = el("img", {
        src: imgUrl(res.image),
        style: "width:100%; border-radius:8px; margin-top:12px; cursor:zoom-in;",
        onclick: () => lightbox(imgUrl(res.image)),
      });
      previewBox.append(img,
        el("div", { class: "hint", style: "margin-top:4px;" }, `Graine : ${res.seed}`));
      toast(`Preview generated and saved for ${loraName}.`);
      refreshLoraLib();  // mettre à jour la galerie
    } catch (e) {
      toast(e.message, true);
    } finally {
      genBtn.disabled = false; genBtn.textContent = window.t("common.generate");
    }
  }}, "Generate");

  const card = el("div", { class: "modal-card", style: "max-width:540px; width:90vw;" },
    el("h3", {}, `Preview LoRA`),
    wfInfo,
    el("label", {}, "Prompt"),
    ta,
    el("div", { class: "row", style: "gap:8px; margin-top:6px;" }, resetBtn),
    previewBox,
    el("div", { class: "row", style: "justify-content:flex-end; gap:8px; margin-top:14px;" },
      el("button", { class: "btn ghost", onclick: () => close() }, "Fermer"),
      genBtn));

  close = overlay(card, () => close());
  setTimeout(() => ta.focus(), 50);
}

// --------------------------------------------------------------------------
//  MODAL : Choose une image existante comme preview LoRA
// --------------------------------------------------------------------------
function openLoraChooseModal(loraName, family) {
  let close;

  // Section A : choisir depuis la galerie AmiorAI
  const galBox = el("div", { class: "lm-choose-grid" });
  const galLoader = el("div", { class: "hint" }, "Chargement de la galerie…");

  // Section B : importer un fichier local
  const fileInput = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp",
    style: "margin-top:4px;" });
  const importBtn = el("button", { class: "btn sm ghost", onclick: async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return toast(window.t("common.file_required"), true);
    const MAX = 5 * 1024 * 1024;
    if (f.size > MAX) return toast("Image trop volumineuse (max 5 Mo).", true);
    const b64 = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result.split(",")[1]);
      r.onerror = rej;
      r.readAsDataURL(f);
    });
    try {
      await api("/api/lora/preview/assign", "POST", {
        lora_name: loraName, family, source: "imported_file", image_b64: b64,
      });
      toast(`Preview assigned (imported file) for ${loraName}.`);
      close(); refreshLoraLib();
    } catch (e) { toast(e.message, true); }
  }}, "Import this file");

  const card = el("div", { class: "modal-card", style: "max-width:640px; width:95vw;" },
    el("h3", {}, `Choose une preview — ${loraName}`),

    el("h4", { style: "font-size:13px; margin: 12px 0 6px;" }, "Depuis la galerie AmiorAI"),
    galLoader, galBox,

    el("h4", { style: "font-size:13px; margin: 16px 0 6px;" }, "Import a local file"),
    el("div", { class: "row", style: "gap:8px; align-items:center;" }, fileInput, importBtn),

    el("div", { class: "row", style: "justify-content:flex-end; margin-top:16px;" },
      el("button", { class: "btn ghost", onclick: () => close() }, "Fermer")));

  close = overlay(card, () => close());

  // Charger les 48 images les plus récentes de la galerie SQL
  (async () => {
    try {
      const imgs = await api("/api/gallery?limit=48");
      galLoader.remove();
      if (!imgs || !imgs.length) {
        galBox.append(el("span", { class: "hint" }, "Gallery is empty."));
        return;
      }
      for (const g of imgs) {
        const thumb = el("img", {
          src: imgUrl(g.image),
          class: "lm-choose-thumb",
          title: "Cliquer pour utiliser comme preview",
          onclick: async () => {
            try {
              await api("/api/lora/preview/assign", "POST", {
                lora_name: loraName, family, source: "selected_gallery", image: g.image,
              });
              toast(`Preview assigned for ${loraName}.`);
              close(); refreshLoraLib();
            } catch (e) { toast(e.message, true); }
          },
        });
        galBox.append(thumb);
      }
    } catch (e) {
      galLoader.textContent = "Impossible de charger la galerie.";
    }
  })();
}

// --------------------------------------------------------------------------
//  MODAL : Association manuelle via URL Civitai
// --------------------------------------------------------------------------
function openCivitaiLinkModal(modelFileId, loraName) {
  let close;
  const urlInput = el("input", { type: "url",
    placeholder: "https://civitai.com/models/… ou civitai.red/…",
    style: "width:100%; margin-bottom:8px; font-family:monospace;" });

  const statusEl  = el("div", { class: "hint", style: "margin-bottom:8px; min-height:18px;" });
  const previewPane = el("div");
  let pendingData = null;

  const analyzeBtn = el("button", { class: "btn sm", onclick: async () => {
    const url = urlInput.value.trim();
    if (!url) return toast("Colle une URL Civitai (civitai.com ou civitai.red).", true);
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = '<span class="spinner"></span> Analyzing…';
    statusEl.textContent = "";
    previewPane.innerHTML = "";
    pendingData = null;

    try {
      const data = await api("/api/civitai/fetch_by_url", "POST", { url });

      if (data.needs_version_selection) {
        // Plusieurs versions : afficher un sélecteur
        statusEl.textContent = `${data.versions.length} versions available — choose the one matching your file.`;
        previewPane.append(buildVersionSelector(data, modelFileId, () => close()));
      } else {
        pendingData = data;
        statusEl.textContent = window.t("lora.civitai.profile_found");
        previewPane.append(buildConfirmPane(data, modelFileId, () => close()));
      }
    } catch (e) {
      statusEl.innerHTML = `<span style="color:var(--danger);">✗ ${e.message}</span>`;
    } finally {
      analyzeBtn.disabled = false; analyzeBtn.textContent = "Analyze link";
    }
  }}, "Analyze link");

  const card = el("div", { class: "modal-card", style: "max-width:580px; width:95vw;" },
    el("h3", {}, `Associer une fiche Civitai — ${loraName}`),
    el("p", { class: "hint", style: "margin-bottom:10px;" },
      "Accepte les liens civitai.com et civitai.red. The association is saved only after your confirmation."),
    urlInput,
    el("div", { class: "row", style: "gap:8px; margin-bottom:10px;" }, analyzeBtn),
    statusEl,
    previewPane,
    el("div", { class: "row", style: "justify-content:flex-end; margin-top:14px;" },
      el("button", { class: "btn ghost", onclick: () => close() }, "Cancel")));

  close = overlay(card, () => close());
  setTimeout(() => urlInput.focus(), 50);
}

function buildVersionSelector(data, modelFileId, closeFn) {
  const container = el("div");
  container.append(el("div", { style: "font-weight:600; margin-bottom:8px;" },
    `Model : ${data.civitai_model_name || ""}`));

  for (const v of data.versions) {
    const thumb = v.preview_url
      ? el("img", { src: v.preview_url, style: "width:60px; height:60px; object-fit:cover; border-radius:6px; flex-shrink:0;",
          onerror(e) { e.target.style.display = "none"; } })
      : el("div", { style: "width:60px; height:60px; background:var(--panel-2); border-radius:6px; flex-shrink:0;" });

    const triggers = (v.trigger_words || []).join(", ");
    const row = el("div", {
      class: "lm-stack-row",
      style: "cursor:pointer; margin-bottom:6px;",
      onclick: async () => {
        row.style.opacity = "0.5";
        try {
          const full = await api("/api/civitai/fetch_version", "POST", { version_id: v.version_id });
          container.innerHTML = "";
          container.append(buildConfirmPane(full, modelFileId, closeFn));
        } catch (e) { toast(e.message, true); row.style.opacity = "1"; }
      },
    },
      thumb,
      el("div", { class: "lm-stack-info" },
        el("span", { class: "lm-filename" }, v.version_name || `Version ${v.version_id}`),
        el("div", { class: "lm-meta-row" },
          v.base_model ? el("span", { class: "lm-family-tag" }, v.base_model) : el("span"),
          v.published_at ? el("span", { class: "hint" }, v.published_at) : el("span"),
          triggers ? el("span", { class: "lm-trigger" }, `Triggers : ${triggers}`) : el("span"))));
    container.append(row);
  }
  return container;
}

function buildConfirmPane(data, modelFileId, closeFn) {
  const tags     = (data.civitai_tags || []).slice(0, 6).join(", ") || "—";
  const triggers = (data.civitai_trigger_words || []).join(", ") || "—";
  const previewImg = data.civitai_preview_url
    ? el("img", { src: data.civitai_preview_url,
        style: "width:110px; height:110px; object-fit:cover; border-radius:8px; flex-shrink:0;",
        onerror(e) { e.target.style.display = "none"; } })
    : el("div", { style: "width:110px; height:110px; background:var(--panel-2); border-radius:8px; flex-shrink:0; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:11px;" }, "Sans preview");

  const infoRows = [
    ["Nom",        data.civitai_model_name || "—"],
    ["Version",    data.civitai_version_name || "—"],
    ["Creator",   data.civitai_creator || "—"],
    ["Base Model", data.civitai_base_model || "—"],
    ["Tags",       tags],
    ["Triggers",   triggers],
  ];
  const table = el("table", { style: "font-size:12px; border-collapse:collapse; flex:1;" });
  for (const [k, v] of infoRows) {
    table.append(el("tr", {},
      el("td", { style: "padding:2px 10px 2px 0; color:var(--muted); white-space:nowrap; vertical-align:top;" }, k),
      el("td", { style: "padding:2px 0; word-break:break-word;" }, v)));
  }

  const confirmBtn = el("button", { class: "btn", onclick: async () => {
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<span class="spinner"></span> Enregistrement…';
    try {
      const res = await api("/api/civitai/associate", "POST",
        { model_file_id: modelFileId, civitai_data: data });
      const msg = res.preview_cached ? " Preview mise en cache." : res.preview_error ? ` (preview : ${res.preview_error})` : "";
      toast(`Civitai association saved.${msg}`);
      closeFn(); refreshLoraLib();
    } catch (e) { toast(e.message, true); confirmBtn.disabled = false; confirmBtn.textContent = "Confirmer l'association"; }
  }}, "Confirmer l'association");

  const srcLink = data.civitai_url
    ? el("a", { href: data.civitai_url, target: "_blank", rel: "noopener", class: "btn sm ghost" }, "🔗 Fiche")
    : el("span");

  return el("div", {},
    el("div", { style: "background:var(--panel-2); border-radius:10px; padding:12px; display:flex; gap:12px; margin-bottom:12px;" },
      previewImg, table),
    el("div", { class: "row", style: "gap:8px; flex-wrap:wrap;" }, confirmBtn, srcLink));
}


// --------------------------------------------------------------------------
//  MODAL : Identification manuelle — type et famille
// --------------------------------------------------------------------------

const LORA_FILE_TYPES = [
  ["lora",        "LoRA"],
  ["lycoris",     "LyCORIS"],
  ["checkpoint",  "Checkpoint"],
  ["unet",        "UNet / Diffusion Model"],
  ["vae",         "VAE"],
  ["clip",        "CLIP / Text Encoder"],
  ["controlnet",  "ControlNet"],
  ["embedding",   "Embedding"],
  ["other",       "Autre / Inconnu"],
];

const LORA_FAMILIES_MANUAL = [
  ["sd15",       "SD 1.5"],
  ["sdxl",       "SDXL"],
  ["flux",       "Flux 1"],
  ["flux2_klein","Flux 2 Klein"],
  ["krea2",      "Krea 2"],
  ["zimage",     "Z-Image"],
  ["pony",       "Pony"],
  ["illustrious","Illustrious"],
  ["wan",        "Wan"],
  ["ltx_video",  "LTX Video"],
  ["unknown",    "Inconnu"],
  ["other",      "Autre"],
];

// Compatibilité workflow par famille effective
const FAMILY_WORKFLOW_COMPAT = {
  flux2_klein: ["T2I", "I2I", "Duo", "Trio", "Group4", "Preview"],
  krea2:       ["Krea 2 Unified"],
  flux:        ["Flux T2I"],
  sdxl:        ["SDXL T2I"],
  sd15:        ["SD1.5 T2I"],
  zimage:      ["Z-Image T2I"],
};

function openIdentificationModal(modelFileId, loraName, civMeta) {
  let close;
  const currentType   = (civMeta && civMeta.manual_file_type)   || (civMeta && civMeta.detected_file_type) || "lora";
  const currentFamily = (civMeta && civMeta.manual_family)       || (civMeta && civMeta.effective_family)  || "";
  const idSource      = (civMeta && civMeta.identification_source_label) || "Automatic detection";
  const hasManual     = !!(civMeta && (civMeta.manual_file_type || civMeta.manual_family));

  const typeSelect = el("select", { style: "width:100%; margin-top:4px;" });
  for (const [val, label] of LORA_FILE_TYPES) {
    const opt = el("option", { value: val }, label);
    if (val === currentType) opt.selected = true;
    typeSelect.append(opt);
  }

  const familySelect = el("select", { style: "width:100%; margin-top:4px;" });
  for (const [val, label] of LORA_FAMILIES_MANUAL) {
    const opt = el("option", { value: val }, label);
    if (val === currentFamily) opt.selected = true;
    familySelect.append(opt);
  }

  // Zone de compatibilité workflow (mise à jour dynamique)
  const compatBox = el("div", { class: "hint", style: "margin-top:10px; padding:10px; "
    + "background:var(--panel-2); border-radius:8px;" });

  function updateCompatBox() {
    const fam = familySelect.value;
    const wfs = FAMILY_WORKFLOW_COMPAT[fam];
    compatBox.innerHTML = "";
    if (!fam || fam === "unknown" || fam === "other") {
      compatBox.textContent = window.t("lora.compat_unknown");
      return;
    }
    if (!wfs) {
      compatBox.textContent = `Family ${fam} : no AmiorAI workflow declared yet.`;
      return;
    }
    const all = Object.values(FAMILY_WORKFLOW_COMPAT).flat();
    const allFams = Object.keys(FAMILY_WORKFLOW_COMPAT);
    compatBox.append(
      el("div", { style: "font-weight:600; margin-bottom:4px;" },
        `Flux 2 Klein compatibility — ${LORA_FAMILIES_MANUAL.find(([v]) => v === fam)?.[1] || fam} :`),
      ...wfs.map(w => el("div", { style: "color:var(--ok);" }, `✓ ${w}`)),
      ...allFams.filter(f => f !== fam).map(f => {
        const label = LORA_FAMILIES_MANUAL.find(([v]) => v === f)?.[1] || f;
        return el("div", { style: "color:var(--muted);" }, `✗ ${label}`);
      })
    );
  }
  familySelect.addEventListener("change", updateCompatBox);
  updateCompatBox();

  const saveBtn = el("button", { class: "btn", onclick: async () => {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner"></span>';
    try {
      await api("/api/lora/set_identification", "POST", {
        model_file_id:    modelFileId,
        manual_file_type: typeSelect.value || null,
        manual_family:    familySelect.value || null,
        reset:            false,
      });
      toast(window.t("lora.toasts.manual_identification"));
      close(); refreshLoraLib();
    } catch (e) { toast(e.message, true); }
    finally { saveBtn.disabled = false; saveBtn.textContent = "Save"; }
  }}, "Save");

  const resetBtn = el("button", { class: "btn sm ghost",
    style: hasManual ? "" : "opacity:.4",
    title: hasManual ? "Remove override and return to automatic detection"
                     : "No manual override to reset",
    onclick: async () => {
      if (!hasManual) return;
      if (!confirm("Remove manual identification and return to automatic detection?")) return;
      try {
        await api("/api/lora/set_identification", "POST", { model_file_id: modelFileId, reset: true });
        toast(window.t("lora.toasts.auto_detection_restored"));
        close(); refreshLoraLib();
      } catch (e) { toast(e.message, true); }
    },
  }, "↺ Reset");

  const card = el("div", { class: "modal-card", style: "max-width:480px; width:95vw;" },
    el("h3", {}, `Identification — ${loraName}`),
    el("p", { class: "hint", style: "margin-bottom:12px;" },
      `Source actuelle : ${idSource}. `
      + "Manual values take priority over automatic detection and Civitai."),

    el("label", {}, "File type"),
    typeSelect,
    el("label", { style: "margin-top:10px; display:block;" }, "Family / Base Model"),
    familySelect,
    compatBox,

    el("div", { class: "row", style: "justify-content:space-between; margin-top:16px; flex-wrap:wrap; gap:8px;" },
      resetBtn,
      el("div", { class: "row", style: "gap:8px;" },
        el("button", { class: "btn ghost", onclick: () => close() }, "Cancel"),
        saveBtn)));

  close = overlay(card, () => close());
}

// Filtres library
for (const id of ["lora-lib-search", "lora-lib-family", "lora-lib-favonly", "lora-lib-preview-filter"]) {
  const n = $("#" + id);
  if (n) n.addEventListener(id === "lora-lib-search" ? "input" : "change", refreshLoraLib);
}
const _loraLibRefresh = $("#lora-lib-refresh");
if (_loraLibRefresh) _loraLibRefresh.addEventListener("click", refreshLoraLib);

// --------------------------------------------------------------------------
//  3. PRESETS
// --------------------------------------------------------------------------
async function refreshLoraPresets() {
  const box = $("#lora-presets-list");
  if (!box) return;
  let presets;
  try { presets = await api("/api/lora/presets"); } catch { presets = []; }
  box.innerHTML = "";
  if (!presets.length) {
    box.append(el("div", { class: "hint" }, "No preset — save your active stack to create one."));
    return;
  }
  for (const p of presets) {
    const count = (p.stack || []).length;
    const row = el("div", { class: "lm-preset-row" },
      el("div", { class: "lm-stack-info" },
        el("span", { class: "lm-filename" }, p.name),
        el("div", { class: "lm-meta-row" },
          p.family ? el("span", { class: "lm-family-tag" }, LORA_FAMILY_LABELS[p.family] || p.family) : el("span"),
          el("span", { class: "hint" }, `${count} LoRA`),
          p.context && p.context !== "global" ? el("span", { class: "hint" }, p.context) : el("span"))),
      el("div", { class: "lm-stack-actions" },
        el("button", { class: "btn sm ghost", title: "Charger ce preset dans la pile active",
          onclick: async () => {
            if (!confirm(`Remplacer la pile active par le preset « ${p.name}” ?`)) return;
            await api("/api/lora/preset/apply", "POST", { id: p.id });
            toast(`Preset « ${p.name}” loaded.`);
            refreshLoraStack();
          }
        }, "▶ Appliquer"),
        el("button", { class: "btn sm danger", onclick: async () => {
          if (!confirm(`Delete preset « ${p.name}” ?`)) return;
          await api("/api/lora/preset/delete", "POST", { id: p.id });
          refreshLoraPresets();
        }}, "✕")));
    box.append(row);
  }
}

// Sauvegarder la pile courante comme preset
const _loraPresetSave = $("#lora-preset-save-current");
if (_loraPresetSave) _loraPresetSave.addEventListener("click", async () => {
  const name = prompt("Nom du preset ?", "Mon preset LoRA");
  if (!name || !name.trim()) return;
  const loras = await api("/api/loras");
  if (!loras.length) return toast(window.t("lora.toasts.empty_stack"), true);
  await api("/api/lora/preset/save", "POST", { name: name.trim(), stack: loras });
  toast(`Preset « ${name.trim()}” saved.`);
  refreshLoraPresets();
});

// ===========================================================================
//  ADVANCED PROMPTS — éditeur dans Réglages
// ===========================================================================

async function loadAdvancedPrompts() {
  const container = $("#adv-prompts-container");
  if (!container) return;
  container.innerHTML = '<span class="hint">Chargement…</span>';
  let data;
  try { data = await api("/api/advanced_prompts"); }
  catch (e) { container.innerHTML = `<span class="hint" style="color:var(--danger);">Error: ${e.message}</span>`; return; }
  container.innerHTML = "";
  for (const [pkey, info] of Object.entries(data)) {
    container.append(buildPromptEditor(pkey, info));
  }
}

function buildPromptEditor(pkey, info) {
  const isOverride = info.has_override;
  const badge = el("span", {
    class: "lm-badge " + (isOverride ? "lm-badge-warn" : "lm-badge-ok"),
    style: "margin-left:8px; font-size:10px;",
  }, isOverride ? "Override active" : "Prompt officiel");

  const ta = el("textarea", {
    style: "width:100%; height:220px; font-family:monospace; font-size:12px; resize:vertical; margin-top:8px;",
  });
  ta.value = info.effective;

  const warnEl = el("div", { class: "hint", style: "color:var(--danger); margin-top:4px; display:none;" });

  // Validation scene planner prompts
  function validateScenePlanner() {
    if (!(pkey === "scene_planner" || pkey === "krea_scene_planner")) { warnEl.style.display = "none"; return true; }
    const val  = ta.value;
    const keys = info.required_keys || [];
    const missing = keys.filter(k => !val.includes(`"${k}"`));
    if (missing.length) {
      warnEl.textContent = window.t("settings.advanced_prompts.keys_missing", { keys: missing.join(", ") });
      warnEl.style.display = "";
      return false;
    }
    warnEl.style.display = "none";
    return true;
  }
  ta.addEventListener("input", validateScenePlanner);

  const saveBtn = el("button", { class: "btn sm", onclick: async () => {
    const val = ta.value.trim();
    if (!val) return toast(window.t("common.prompt_required"), true);
    validateScenePlanner();  // affiche l'avertissement mais laisse sauvegarder
    saveBtn.disabled = true; saveBtn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await api("/api/advanced_prompts/save", "POST",
        { key: info.key, value: val });
      if (res.warnings && res.warnings.length) {
        toast(window.t("settings.advanced_prompts.saved_warning", { warning: res.warnings[0] }), true);
      } else {
        toast(`Prompt “${info.title}” saved.`);
      }
      loadAdvancedPrompts();
    } catch (e) { toast(e.message, true); }
    finally { saveBtn.disabled = false; saveBtn.textContent = "Save"; }
  }}, "Save");

  const cancelBtn = el("button", { class: "btn sm ghost", onclick: () => {
    ta.value = info.effective; warnEl.style.display = "none";
  }}, "Cancel changes");

  const copyBtn = el("button", { class: "btn sm ghost", title: "Copy official prompt into editor",
    onclick: () => { ta.value = info.official; validateScenePlanner(); }
  }, "📋 Copy official");

  const resetBtn = el("button", {
    class: "btn sm ghost", style: isOverride ? "" : "opacity:.4",
    title: isOverride ? "Remove override and return to official prompt" : "No active override",
    onclick: async () => {
      if (!isOverride) return;
      if (!confirm(`Reset « ${info.title}” ? The override will be removed and the official prompt restored.`)) return;
      await api("/api/advanced_prompts/reset", "POST", { key: info.key });
      toast(`Prompt « ${info.title}” reset.`); loadAdvancedPrompts();
    },
  }, "↺ Reset");

  const restoreBtn = el("button", { class: "btn sm ghost", title: "Restore previous override version",
    onclick: async () => {
      try {
        const res = await api("/api/advanced_prompts/restore", "POST", { key: info.key });
        toast(window.t("settings.advanced_prompts.restored")); loadAdvancedPrompts();
      } catch (e) { toast(e.message, true); }
    },
  }, "⏪ Restaurer");

  return el("div", { style: "margin-bottom:20px; padding:14px; background:var(--panel-2); border-radius:12px;" },
    el("div", { class: "row", style: "align-items:center; margin-bottom:4px;" },
      el("strong", {}, info.title), badge),
    el("div", { class: "hint", style: "margin-bottom:4px;" }, info.description),
    ta, warnEl,
    el("div", { class: "row", style: "gap:6px; flex-wrap:wrap; margin-top:8px;" },
      saveBtn, cancelBtn, copyBtn, resetBtn, restoreBtn));
}

// Reset global
const _advResetAll = $("#adv-prompts-reset-all");
if (_advResetAll) _advResetAll.addEventListener("click", async () => {
  if (!confirm("Reset ALL advanced prompts? All overrides will be removed.")) return;
  await api("/api/advanced_prompts/reset", "POST", {});
  toast(window.t("settings.advanced_prompts.reset_done")); loadAdvancedPrompts();
});

// ---------- Statut du token ----------
async function refreshCivitaiTokenStatus() {
  const badge  = $("#civitai-status-badge");
  const status = $("#civitai-token-status");
  if (!badge) return;
  try {
    const s = await api("/api/civitai/token_status");
    if (!s.configured) {
      badge.textContent = "Token absent";
      badge.className   = "lm-badge lm-badge-warn";
      if (status) status.textContent = window.t("lora.token_missing");
    } else {
      badge.textContent = window.t("lora.token_saved_badge");
      badge.className   = "lm-badge lm-badge-ok";
      if (status) status.textContent =
        `Token saved (${s.storage === "keyring" ? "secure system storage" : "⚠ session memory — restart = token loss"}).`
        + (s.warning ? `\n⚠ ${s.warning}` : "");
    }
  } catch { if (badge) { badge.textContent = "?"; badge.className = "lm-badge"; } }
}

// Sauvegarder le token
const _civitaiSaveBtn = $("#civitai-token-save");
if (_civitaiSaveBtn) _civitaiSaveBtn.addEventListener("click", async () => {
  const input = $("#civitai-token-input");
  const token = (input ? input.value : "").trim();
  if (!token) return toast("Colle ton token Civitai avant de sauvegarder.", true);
  try {
    await api("/api/civitai/token/save", "POST", { token });
    if (input) input.value = "";  // effacer immédiatement du DOM
    toast(window.t("lora.toasts.token_saved"));
    refreshCivitaiTokenStatus();
  } catch (e) { toast(e.message, true); }
});

// Tester le token
const _civitaiTestBtn = $("#civitai-token-test");
if (_civitaiTestBtn) _civitaiTestBtn.addEventListener("click", async () => {
  const status = $("#civitai-token-status");
  if (status) status.textContent = "Test en cours…";
  try {
    const r = await api("/api/civitai/test");
    if (status) status.textContent = r.ok ? `✓ ${r.message}` : `✗ ${r.error}`;
    if (r.ok) refreshCivitaiTokenStatus();
  } catch (e) { if (status) status.textContent = `✗ ${e.message}`; }
});

// Supprimer le token
const _civitaiDeleteBtn = $("#civitai-token-delete");
if (_civitaiDeleteBtn) _civitaiDeleteBtn.addEventListener("click", async () => {
  if (!confirm("Delete the Civitai token? Sync will be impossible until you enter a new one.")) return;
  await api("/api/civitai/token/delete", "POST", {});
  toast(window.t("lora.toasts.token_deleted"));
  refreshCivitaiTokenStatus();
});

// ---------- Synchronisation globale ----------
let _civitaiSyncPoll = null;

function _civitaiStartPoll() {
  if (_civitaiSyncPoll) return;
  _civitaiSyncPoll = setInterval(async () => {
    try {
      const s = await api("/api/civitai/sync_status");
      const prog  = $("#civitai-sync-progress");
      const msg   = $("#civitai-sync-msg");
      const bar   = $("#civitai-sync-bar");
      const res   = $("#civitai-sync-result");
      if (msg) msg.textContent = s.message || "";
      if (bar && s.total > 0) { bar.max = s.total; bar.value = s.done; }
      if (!s.running) {
        clearInterval(_civitaiSyncPoll); _civitaiSyncPoll = null;
        if (prog) prog.style.display = "none";
        if (res) {
          res.innerHTML = `<div class="hint" style="color:var(--ok);">${s.message || "Synchronization complete."}</div>`;
        }
        refreshLoraLib();  // mettre à jour les cartes
      }
    } catch { clearInterval(_civitaiSyncPoll); _civitaiSyncPoll = null; }
  }, 600);
}

const _civitaiSyncBtn = $("#civitai-sync-btn");
if (_civitaiSyncBtn) _civitaiSyncBtn.addEventListener("click", async () => {
  // Choix du mode
  const modes = [
    ["missing",    "LoRA without Civitai data"],
    ["no_preview", "LoRA sans preview Civitai"],
    ["stale",      "Not synchronized for 30 days"],
    ["all",        "Toutes (forcer)"],
  ];
  let close;
  const modeCards = modes.map(([key, label]) =>
    el("button", { class: "btn sm ghost", style: "width:100%; margin-bottom:6px; text-align:left;",
      onclick: async () => {
        close();
        const prog = $("#civitai-sync-progress");
        const msg  = $("#civitai-sync-msg");
        const res  = $("#civitai-sync-result");
        if (prog) prog.style.display = "";
        if (msg)  msg.textContent = "Starting…";
        if (res)  res.innerHTML   = "";
        try {
          await api("/api/civitai/sync", "POST", { mode: key });
          _civitaiStartPoll();
        } catch (e) {
          if (prog) prog.style.display = "none";
          toast(e.message, true);
        }
      }
    }, label)
  );
  const card = el("div", { class: "modal-card", style: "max-width:420px;" },
    el("h3", {}, "Synchronize with Civitai"),
    el("p", { class: "hint", style: "margin-bottom:10px;" },
      "Choose LoRAs to enrich. Each file hash is computed once (recomputed only if the file changes), then compared with the Civitai database."),
    ...modeCards,
    el("div", { class: "row", style: "justify-content:flex-end; margin-top:10px;" },
      el("button", { class: "btn ghost", onclick: () => close() }, "Cancel")));
  close = overlay(card, () => close());
});

const _civitaiSyncCancel = $("#civitai-sync-cancel");
if (_civitaiSyncCancel) _civitaiSyncCancel.addEventListener("click", async () => {
  await api("/api/civitai/sync/cancel", "POST", {});
  toast(window.t("lora.sync.cancel_requested"));
});

// --------------------------------------------------------------------------
//  Civitai par carte LoRA (debug modal)
// --------------------------------------------------------------------------
const _CIVITAI_STATUS_LABELS = {
  found_with_preview:   "✅ Civitai match — preview downloaded",
  found_no_preview_url: "✓ Correspondance Civitai — aucune URL preview",
  found_preview_error:  "⚠ Civitai match — preview download error",
  found:                "✓ Civitai match found",
  no_match:             "— No Civitai match",
  file_missing:         "✗ File not found",
  hash_error:           "✗ Hash calculation error",
  token_error:          "✗ Token Civitai invalide",
  rate_limit:           "⏳ Civitai limit reached — retry later",
  network_error:        "✗ Network error",
};

const _CIVITAI_STATUS_LABELS_SIMPLE = {
  file_missing:  "✗ File not found",
  hash_error:    "✗ Hash error",
  token_error:   "✗ Token invalide",
  rate_limit:    "⏳ Rate limit",
  network_error: "✗ Network error",
};

async function civitaiEnrichCard(modelFileId, cardEl) {
  const badge = cardEl ? cardEl.querySelector(".civ-status") : null;
  if (badge) { badge.textContent = "Sync…"; badge.className = "lm-badge civ-status"; }

  let res;
  try {
    res = await api("/api/civitai/enrich", "POST", { model_file_id: modelFileId });
  } catch (e) {
    toast(e.message, true);
    return;
  }

  const st = res.status || "network_error";
  const label = _CIVITAI_STATUS_LABELS[st] || st;

  // Modal debug
  const lines = [
    ["Statut",          label],
    ["Hash used",    res.hash_used   ? res.hash_used.slice(0, 24) + "…" : "—"],
    ["Type de hash",    res.hash_type   || "—"],
    ["Origine",         res.hash_origin || "—"],
    ["Model Civitai",  res.civitai_model_name || "—"],
    ["Version",         res.civitai_version    || "—"],
    ["URL preview",     res.preview_url ? "present" : "absent"],
    ["Preview file", res.preview_path || "—"],
    ["Preview error",  res.preview_error || "—"],
    ["Global error",  res.error || "—"],
  ];
  const table = el("table", { style: "width:100%; border-collapse:collapse; font-size:12px;" });
  for (const [k, v] of lines) {
    const tr = el("tr", {},
      el("td", { style: "padding:3px 10px 3px 0; color:var(--muted); white-space:nowrap; vertical-align:top;" }, k),
      el("td", { style: "padding:3px 0; word-break:break-all; font-family:monospace;" }, String(v)));
    table.append(tr);
  }

  let closeDebug;
  const card = el("div", { class: "modal-card", style: "max-width:480px;" },
    el("h3", {}, "Civitai — result"),
    el("p", { class: "hint", style: "margin-bottom:10px;" }, label),
    table,
    el("div", { class: "row", style: "justify-content:flex-end; margin-top:14px;" },
      el("button", { class: "btn ghost", onclick: () => closeDebug() }, "Fermer")));
  closeDebug = overlay(card, () => closeDebug());

  // Refresh la galerie si succès
  if (["found_with_preview", "found_no_preview_url", "found_preview_error", "found"].includes(st)) {
    refreshLoraLib();
  }
}


function renderPersonaPreview() {
  $("#persona-preview").innerHTML = personaImage
    ? `<img src="${imgUrl(personaImage)}" style="max-width:180px;border-radius:12px;">` : "";
}

// Lit un fichier image et le renvoie en data URL (base64)
function fileToDataURL(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}

// Upload generique : envoie une image au serveur, renvoie le nom de fichier local
async function uploadImage(file, prefix) {
  const data_url = await fileToDataURL(file);
  const res = await api("/api/upload", "POST", { data_url, prefix });
  return res.image;
}

// --- Persona ---
$("#persona-upload-btn").addEventListener("click", () => $("#persona-upload").click());
$("#persona-upload").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try { personaImage = await uploadImage(file, "persona"); renderPersonaPreview();
    $("#persona-status").textContent = window.t("settings.persona.image_imported_save"); }
  catch (err) { toast(err.message, true); }
});
$("#persona-save").addEventListener("click", async () => {
  const button = $("#persona-save");
  const status = $("#persona-status");
  const originalText = button.textContent;
  const out = {
    persona_name: $("#s-persona_name").value,
    persona_description: $("#s-persona_description").value,
    persona_image: personaImage,
    krea2_user_token: ($("#s-krea2_user_token") || {}).value || "",
    krea2_char2_lora: ($("#s-krea2_char2_lora") || {}).value || "",
    krea2_char2_lora_strength: ($("#s-krea2_char2_lora_strength") || {}).value || "1.0",
  };
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>';
  status.style.color = "";
  status.textContent = window.t("settings.saving");
  try {
    await api("/api/settings", "POST", out);
    toast(window.t("settings.persona.saved"));
    status.style.color = "var(--ok)";
    status.textContent = "✓ " + window.t("settings.section_saved");
  } catch (e) {
    status.style.color = "var(--danger)";
    status.textContent = window.t("settings.save_failed") + ": " + e.message;
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

const personaFields = ["#s-persona_name", "#s-persona_description", "#s-krea2_user_token",
  "#s-krea2_char2_lora", "#s-krea2_char2_lora_strength"];
personaFields.forEach((selector) => {
  const field = $(selector);
  if (!field) return;
  const markPersonaDirty = () => {
    const status = $("#persona-status");
    if (status) {
      status.style.color = "var(--warn)";
      status.textContent = window.t("settings.unsaved_changes");
    }
  };
  field.addEventListener("input", markPersonaDirty);
  field.addEventListener("change", markPersonaDirty);
});

// --- Upload d'avatar pour un personnage ---
$("#cg-upload-btn").addEventListener("click", () => $("#cg-upload").click());
$("#cg-upload").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const status = $("#cg-save-status");
  status.innerHTML = '<span class="spinner"></span> import…';
  try {
    const name = await uploadImage(file, "avatar");
    currentAvatar = name;
    $("#cg-avatar-preview").innerHTML =
      `<img src="${imgUrl(name)}" style="max-width:240px;border-radius:12px;">`;
    const id = $("#f-id").value;
    if (id) { await api("/api/character/set_avatar", "POST", { id, image: name }); loadCharacters(); }
    status.textContent = id ? window.t("char.toasts.avatar_imported_set") : window.t("char.toasts.image_imported_save");
  } catch (err) { status.textContent = ""; toast(err.message, true); }
});

// --- Upload d'échantillon de voix pour un personnage ---
const _voiceUploadBtn = $("#cg-voice-upload-btn");
if (_voiceUploadBtn) _voiceUploadBtn.addEventListener("click", () => $("#cg-voice-upload").click());
const _voiceUploadInput = $("#cg-voice-upload");
if (_voiceUploadInput) _voiceUploadInput.addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const id = $("#f-id").value;
  if (!id) return toast(window.t("char.validation.save_first"), true);
  const status = $("#cg-voice-status");
  status.innerHTML = '<span class="spinner"></span> import…';
  try {
    const data_url = await fileToDataURL(file);
    const res = await api("/api/voice/upload", "POST", { character_id: id, data_url });
    renderVoicePreview(res.voice_sample);
    status.textContent = window.t("char.toasts.sample_imported");
  } catch (err) { status.textContent = ""; toast(err.message, true); }
});

const _lmstudioRefreshModelsBtn = $("#lmstudio-refresh-models-btn");
if (_lmstudioRefreshModelsBtn) _lmstudioRefreshModelsBtn.addEventListener("click", async () => {
  _lmstudioRefreshModelsBtn.disabled = true;
  try { await refreshLMStudioModelLists(); }
  finally { _lmstudioRefreshModelsBtn.disabled = false; }
});

function collectSettingsPayload() {
  const out = {};
  for (const k of SF) out[k] = ($("#s-" + k) || {}).value || "";
  out.llm_backend = "lmstudio";
  const ctxSlider = $("#s-llm_ctx_slider");
  if (ctxSlider) out.llm_ctx = String(parseInt(ctxSlider.value, 10) || 8192);

  const utilFallbackCb = $("#s-llm_util_fallback");
  out.llm_util_fallback = utilFallbackCb && utilFallbackCb.checked ? "true" : "false";
  const vramOffloadCb = $("#s-lmstudio_vram_offload_enabled");
  out.lmstudio_vram_offload_enabled = vramOffloadCb && vramOffloadCb.checked ? "true" : "false";
  const vramReloadCb = $("#s-lmstudio_reload_on_demand");
  out.lmstudio_reload_on_demand = vramReloadCb && vramReloadCb.checked ? "true" : "false";
  const comfyOffloadCb = $("#s-comfy_vram_offload_before_lmstudio");
  out.comfy_vram_offload_before_lmstudio = comfyOffloadCb && comfyOffloadCb.checked ? "true" : "false";
  const unloadConvCb = $("#s-lmstudio_unload_conversation_before_utility");
  out.lmstudio_unload_conversation_before_utility = unloadConvCb && unloadConvCb.checked ? "true" : "false";
  const unloadUtilCb = $("#s-lmstudio_unload_utility_after_use");
  out.lmstudio_unload_utility_after_use = unloadUtilCb && unloadUtilCb.checked ? "true" : "false";
  const retryLmCb = $("#s-lmstudio_retry_after_load_error");
  out.lmstudio_retry_after_load_error = retryLmCb && retryLmCb.checked ? "true" : "false";

  // Flux 2 Klein loader mode
  const flux2GgufRadio = $("#s-flux2_mode_gguf");
  out.flux2_loader_mode = (flux2GgufRadio && flux2GgufRadio.checked) ? "gguf" : "safetensors";
  const ggufSel = $("#s-img_unet_gguf");
  if (ggufSel && ggufSel.value) out.img_unet_gguf = ggufSel.value;
  const stSel = $("#s-img_unet_safetensors");
  if (stSel && stSel.value) out.img_unet_safetensors = stSel.value;
  return out;
}

async function saveSettingsFromForm(button, statusEl, showToast = true) {
  const originalText = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>';
  }
  if (statusEl) {
    statusEl.style.color = "";
    statusEl.textContent = window.t("settings.saving");
  }
  try {
    const payload = collectSettingsPayload();
    const previousTTSEnabled = ttsEnabled;
    const previousTTSAutoplay = ttsAutoplay;
    await api("/api/settings", "POST", payload);

    // Synchronise immédiatement l'état de la conversation après une sauvegarde.
    // Avant v40.0.3, activer le TTS dans Réglages ne faisait apparaître les
    // boutons qu'après un redémarrage complet de l'interface.
    ttsEnabled = String(payload.tts_enabled) === "true";
    ttsAutoplay = String(payload.tts_autoplay) !== "false";
    const ttsUIChanged = previousTTSEnabled !== ttsEnabled || previousTTSAutoplay !== ttsAutoplay;
    if (ttsUIChanged && activeChat) await openChat(activeChat);

    const savedText = window.t("settings.section_saved");
    document.querySelectorAll(".settings-section-status").forEach((localStatus) => {
      localStatus.style.color = "var(--ok)";
      localStatus.textContent = "✓ " + savedText;
    });
    document.querySelectorAll(".settings-section-save").forEach((localButton) => {
      localButton.classList.remove("attention");
    });
    if (statusEl && !statusEl.classList.contains("settings-section-status")) {
      statusEl.style.color = "var(--ok)";
      statusEl.textContent = "✓ " + savedText;
    }
    if (showToast) toast(window.t("settings.toasts.saved"));
    refreshLLMUtilStatus();
    refreshLMStudioVRAMStatus();
    return true;
  } catch (e) {
    if (statusEl) {
      statusEl.style.color = "var(--danger)";
      statusEl.textContent = window.t("settings.save_failed") + ": " + e.message;
    }
    toast(e.message, true);
    return false;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

const _saveAllSettingsBtn = $("#s-save");
if (_saveAllSettingsBtn) _saveAllSettingsBtn.addEventListener("click", async () => {
  await saveSettingsFromForm(_saveAllSettingsBtn, $("#s-status"), true);
});

document.querySelectorAll(".settings-section-save").forEach((button) => {
  const panel = button.closest(".panel");
  const status = panel ? panel.querySelector(".settings-section-status") : null;

  button.addEventListener("click", async () => {
    await saveSettingsFromForm(button, status, true);
  });

  if (panel && status) {
    const markDirty = () => {
      status.style.color = "var(--warn)";
      status.textContent = window.t("settings.unsaved_changes");
      button.classList.add("attention");
    };
    panel.querySelectorAll("input, select, textarea").forEach((field) => {
      field.addEventListener("input", markDirty);
      field.addEventListener("change", markDirty);
    });
  }
});

// --------------------------------------------------------------------------- //
//  Theme (clair / sombre / system)
// --------------------------------------------------------------------------- //
const THEME_KEY = "amiorai-theme";

function resolveTheme(choice) {
  if (choice === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return choice;
}

function applyTheme(choice) {
  const resolved = resolveTheme(choice);
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.setAttribute("data-theme-choice", choice);
  try { localStorage.setItem(THEME_KEY, choice); } catch (e) { /* localStorage indisponible */ }
  renderThemePicker(choice);
}

function getThemeChoice() {
  try { return localStorage.getItem(THEME_KEY) || "dark"; }
  catch (e) { return "dark"; }
}

function renderThemePicker(choice) {
  const picker = $("#theme-picker");
  if (!picker) return;
  for (const btn of $$(".theme-opt", picker)) {
    btn.classList.toggle("active", btn.dataset.themeChoice === choice);
  }
}

const _themePicker = $("#theme-picker");
if (_themePicker) {
  _themePicker.addEventListener("click", (e) => {
    const btn = e.target.closest(".theme-opt");
    if (!btn) return;
    applyTheme(btn.dataset.themeChoice);
  });
  renderThemePicker(getThemeChoice());
}

// Si l'utilisateur est en mode "Système", suit en direct le changement de theme
// Windows/OS (sans avoir besoin de recharger la page).
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (getThemeChoice() === "system") applyTheme("system");
  });
}

// --------------------------------------------------------------------------- //
//  GLOBAL IMAGE ENGINE — one switch for the whole application
// --------------------------------------------------------------------------- //
let globalImageFamily = "flux2_klein";

function syncGlobalImageSelectors(family) {
  const globalSel = $("#global-image-family");
  const studioSel = $("#studio-family");
  if (globalSel) globalSel.value = family;
  if (studioSel && [...studioSel.options].some(o => o.value === family)) studioSel.value = family;
}

async function setGlobalImageFamily(family, persist = true, refreshStudio = false) {
  if (!["flux2_klein", "krea2"].includes(family)) family = "flux2_klein";
  globalImageFamily = family;
  studioCurrentFamily = family;
  studioRefImages = [];
  syncGlobalImageSelectors(family);
  if (persist) await api("/api/image/set_family", "POST", { family });
  if (refreshStudio && $("#studio-family") && $("#studio-family").options.length) {
    await refreshStudioWorkflows();
    await refreshStudioCompatibility();
  }
  // Configurator previews are cached separately per engine; reload visible cards.
  if (typeof loadOptionPreviews === "function") {
    try { await loadOptionPreviews(); } catch (_) { /* non-blocking */ }
  }
  if (persist) toast(`Global image engine: ${family === "krea2" ? "Krea 2" : "Flux 2 Klein"}`);
}

const _globalImageFamily = $("#global-image-family");
if (_globalImageFamily) {
  _globalImageFamily.addEventListener("change", async () => {
    try { await setGlobalImageFamily(_globalImageFamily.value, true, true); }
    catch (e) { toast(e.message, true); }
  });
}

// --------------------------------------------------------------------------- //
//  STUDIO IMAGE
// --------------------------------------------------------------------------- //
const FAMILY_LABELS = {
  sd15: "SD 1.5", sdxl: "SDXL", flux: "Flux", flux2_klein: "Flux Klein (Flux.2)", krea2: "Krea 2",
  zimage: "Z-Image", wan_video: "Wan (video)", ltx_video: "LTX (video)", custom: "Custom",
};
const KIND_LABELS = {
  checkpoint: "Checkpoint", unet: "UNet", clip: "CLIP / Encodeur", vae: "VAE",
  lora: "LoRA", controlnet: "ControlNet", video_model: "Video model",
};

let studioFamilies = [];
let studioWorkflows = [];
let studioCurrentFamily = null;
let studioRefImages = [];   // noms de fichiers déjà uploadés, dans l'ordre attendu par le workflow

async function loadStudio() {
  try {
    studioFamilies = (await api("/api/image/families"))
      .filter(f => ["flux2_klein", "krea2"].includes(f.id));
  } catch (e) {
    // Panne familles : Studio dégradé mais n'interrompt pas le reste de l'appli
    const box = $("#studio-components");
    if (box) box.innerHTML = `<div class="hint" style="color:var(--danger);">Studio Image indisponible : ${e.message}<br>Les autres fonctions d’AmiorAI restent disponibles.</div>`;
    throw e;  // remonté à safeInit
  }

  const sel = $("#studio-family");
  sel.innerHTML = "";
  for (const f of studioFamilies) {
    sel.append(el("option", { value: f.id }, FAMILY_LABELS[f.id] || f.label));
  }

  let settings;
  try { settings = await api("/api/settings"); } catch (e) { settings = {}; }
  studioCurrentFamily = ["flux2_klein", "krea2"].includes(settings.image_family)
    ? settings.image_family : "flux2_klein";
  globalImageFamily = studioCurrentFamily;
  syncGlobalImageSelectors(studioCurrentFamily);

  sel.onchange = async () => {
    await setGlobalImageFamily(sel.value, true, true);
  };

  await refreshStudioWorkflows();
  await refreshStudioCompatibility();
}

async function refreshStudioWorkflows() {
  const sel = $("#studio-workflow");
  if (!sel) return;
  sel.innerHTML = "";
  try {
    studioWorkflows = await api("/api/image/workflows?family=" + encodeURIComponent(studioCurrentFamily));
  } catch (e) { studioWorkflows = []; }
  if (!studioWorkflows.length) {
    sel.append(el("option", { value: "" }, "No workflow for this family"));
    renderStudioRefs();
    return;
  }
  for (const w of studioWorkflows) {
    const label = w.label + (w.exists ? "" : " (missing file)");
    sel.append(el("option", { value: w.file }, label));
  }
  sel.onchange = () => { studioRefImages = []; renderStudioRefs(); };
  renderStudioRefs();
}

function currentStudioWorkflowManifest() {
  const file = ($("#studio-workflow") || {}).value;
  return studioWorkflows.find(w => w.file === file) || null;
}

function renderStudioRefs() {
  const panel = $("#studio-refs-panel");
  const box = $("#studio-refs");
  const manifest = currentStudioWorkflowManifest();
  const nRefs = manifest ? (manifest.refs || 0) : 0;

  if (nRefs === 0) {
    panel.style.display = "none";
    box.innerHTML = "";
    studioRefImages = [];
    return;
  }
  panel.style.display = "block";
  box.innerHTML = "";
  // Conserve les references deja uploadees si on en a deja assez, tronque/etend sinon
  if (studioRefImages.length > nRefs) studioRefImages = studioRefImages.slice(0, nRefs);

  for (let i = 0; i < nRefs; i++) {
    const current = studioRefImages[i];
    const slot = el("div", { class: "component-card", style: "display:flex; align-items:center; gap:12px;" });
    const preview = el("div", { style: "width:64px; height:64px; border-radius:8px; overflow:hidden; background:var(--panel-2); flex-shrink:0; display:flex; align-items:center; justify-content:center;" });
    if (current) preview.append(el("img", { src: imgUrl(current), style: "width:100%; height:100%; object-fit:cover;" }));
    else preview.append(el("span", { class: "hint" }, "—"));

    const fileInput = el("input", { type: "file", accept: "image/*", style: "display:none;" });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) return;
      try {
        const name = await uploadImage(file, "studio_ref");
        studioRefImages[i] = name;
        renderStudioRefs();
      } catch (e) { toast(e.message, true); }
    });

    const label = (nRefs > 1) ? `Image ${i + 1}` : "Reference image";
    slot.append(
      preview,
      el("div", { style: "flex:1;" },
        el("strong", {}, label),
        el("div", { class: "row", style: "gap:6px; margin-top:6px;" },
          el("button", { class: "btn sm ghost", onclick: () => fileInput.click() },
            current ? "Changer…" : "Importer…"),
          current ? el("button", { class: "btn sm danger", onclick: () => {
            studioRefImages[i] = undefined; renderStudioRefs();
          } }, "✕") : el("span")
        )
      ),
      fileInput
    );
    box.append(slot);
  }
}

async function refreshStudioCompatibility() {
  const box = $("#studio-components");
  const badgeBox = $("#studio-overall-badge");
  box.innerHTML = '<span class="hint">Checking…</span>';
  let compat;
  try {
    compat = await api("/api/image/compatibility?family=" + encodeURIComponent(studioCurrentFamily));
  } catch (e) { box.innerHTML = ""; box.append(statusBadge("error", e.message)); return; }

  badgeBox.innerHTML = "";
  badgeBox.append(compat.ok ? statusBadge("ready", "✓ ready to generate") : statusBadge("error", "missing component"));

  box.innerHTML = "";
  if (!compat.components.length) {
    box.append(el("div", { class: "hint" }, "This custom workflow does not declare interface-managed components — edit it directly in its JSON file."));
  }

  // ── Flux 2 Klein : récapitulatif mode global ──────────────────────────────
  if (studioCurrentFamily === "flux2_klein" && compat.flux2_summary) {
    const s = compat.flux2_summary;
    const summaryCard = el("div", { class: "component-card", style: "background:var(--panel-2);" },
      el("strong", {}, "Flux 2 Klein active"),
      el("div", { class: "hint", style: "margin-top:6px; line-height:1.8;" },
        `Mode : ${s.mode_label}`, el("br"),
        `UNet : ${s.active_unet}`, el("br"),
        `Workflow effectif (T2I) : ${s.workflow_example}`
      ),
      el("div", { class: "hint", style: "margin-top:8px; font-style:italic;" },
        "The selected mode and UNet apply to Avatar, Conversation, Preview, Duo, Trio, and Group."
      )
    );
    box.append(summaryCard);
  }

  // ── Rendu des composants ──────────────────────────────────────────────────
  // Pour flux2_klein : on fusionne les deux composants UNet en une seule section
  // mode-selector + sélecteur filtré par extension.
  const flux2UnetRendered = { gguf: false, safetensors: false };

  for (const comp of compat.components) {
    // Flux 2 Klein UNet : traitement spécial (regroupé une seule fois)
    if (studioCurrentFamily === "flux2_klein" && comp.comp_mode !== null && comp.comp_mode !== undefined) {
      if (flux2UnetRendered.gguf && flux2UnetRendered.safetensors) continue;
      if (comp.comp_mode === "gguf" && flux2UnetRendered.gguf) continue;
      if (comp.comp_mode === "safetensors" && flux2UnetRendered.safetensors) continue;

      // On rend la section UNet la première fois qu'on tombe sur un comp UNet
      if (!flux2UnetRendered.gguf && !flux2UnetRendered.safetensors) {
        const activeMode = compat.flux2_mode || "gguf";
        // Trouver les deux comps UNet
        const compGguf = compat.components.find(c => c.comp_mode === "gguf");
        const compSt   = compat.components.find(c => c.comp_mode === "safetensors");

        const card = el("div", { class: "component-card" });
        card.append(el("strong", {}, "UNet Flux 2 Klein"));

        // Sélecteur GGUF
        const ggufSel = el("select", { style: "width:100%; margin-top:6px;" });
        ggufSel.append(el("option", { value: "" }, "— choisir un UNet GGUF —"));
        const sfSel = el("select", { style: "width:100%; margin-top:6px;" });
        sfSel.append(el("option", { value: "" }, "— choisir un UNet Safetensors —"));

        // Charger les fichiers unet flux2_klein depuis le catalogue, filtrer par ext côté client
        let allUnet = [];
        try { allUnet = await api("/api/models/files?kind=unet&family=flux2_klein"); } catch(e) {}
        if (!allUnet.length) {
          try { allUnet = await api("/api/models/files?kind=unet"); } catch(e) {}
        }
        const ggufFiles = allUnet.filter(f => (f.name||"").toLowerCase().endsWith(".gguf"));
        const sfFiles   = allUnet.filter(f => (f.name||"").toLowerCase().endsWith(".safetensors"));

        for (const f of ggufFiles) ggufSel.append(el("option", { value: f.name }, `${f.name} (${f.size_human})`));
        if (compGguf?.value && !ggufFiles.some(f => f.name === compGguf.value))
          ggufSel.append(el("option", { value: compGguf.value }, compGguf.value + " (hors library)"));
        ggufSel.value = compGguf?.value || "";

        for (const f of sfFiles) sfSel.append(el("option", { value: f.name }, `${f.name} (${f.size_human})`));
        if (compSt?.value && !sfFiles.some(f => f.name === compSt.value))
          sfSel.append(el("option", { value: compSt.value }, compSt.value + " (hors library)"));
        sfSel.value = compSt?.value || "";

        // Inputs de secours quand le catalogue est vide (nom de fichier direct)
        function makeManualInput(currentVal, settingKey, placeholder) {
          const wrap = el("div", { style: "margin-top:6px;" });
          const inp = el("input", {
            type: "text", class: "input-inline",
            placeholder, style: "width:100%; font-size:12px;",
          });
          inp.value = currentVal || "";
          const saveBtn = el("button", { class: "btn sm ghost", style: "margin-top:4px;" },
            "Save this name");
          saveBtn.addEventListener("click", async () => {
            const v = inp.value.trim();
            if (!v) return toast("Empty filename.", true);
            try {
              await api("/api/image/set_component", "POST",
                { family: "flux2_klein", component: settingKey, value: v });
              toast(`${settingKey} saved : ${v}`);
              refreshStudioCompatibility();
            } catch(e) { toast(e.message, true); }
          });
          wrap.append(inp, saveBtn);
          return wrap;
        }

        // Lignes GGUF / Safetensors (visibilité selon mode)
        const ggufEmptyHint = el("div", { style: "margin-top:6px;" },
          el("div", { class: "hint", style: "color:var(--warn); font-size:11px; margin-bottom:4px;" },
            "No GGUF UNet detected in the catalog. Run a scan from Library, or enter the filename directly:"),
          makeManualInput(compGguf?.value, "img_unet_gguf", "ex : BigLoveKlein3-Q5_K_M.gguf")
        );

        const sfEmptyHint = el("div", { style: "margin-top:6px;" },
          el("div", { class: "hint", style: "color:var(--warn); font-size:11px; margin-bottom:4px;" },
            "No Safetensors UNet detected. Run a scan from Library, or enter the filename directly:"),
          makeManualInput(compSt?.value, "img_unet_safetensors", "ex : flux2_klein_model.safetensors")
        );

        const ggufRow = el("div", {},
          el("label", { class: "hint", style: "display:block; margin-top:8px;" }, "UNet GGUF"),
          ggufSel,
          !ggufFiles.length ? ggufEmptyHint : el("span")
        );
        const sfRow = el("div", {},
          el("label", { class: "hint", style: "display:block; margin-top:8px;" }, "UNet Safetensors"),
          sfSel,
          !sfFiles.length ? sfEmptyHint : el("span")
        );
        ggufRow.style.display = activeMode === "gguf" ? "" : "none";
        sfRow.style.display   = activeMode === "safetensors" ? "" : "none";
        card.append(ggufRow, sfRow);

        // Sauvegarder à la sélection
        ggufSel.addEventListener("change", async () => {
          try {
            await api("/api/image/set_component", "POST",
              { family: "flux2_klein", component: "img_unet_gguf", value: ggufSel.value });
            refreshStudioCompatibility();
          } catch(e) { toast(e.message, true); }
        });
        sfSel.addEventListener("change", async () => {
          try {
            await api("/api/image/set_component", "POST",
              { family: "flux2_klein", component: "img_unet_safetensors", value: sfSel.value });
            refreshStudioCompatibility();
          } catch(e) { toast(e.message, true); }
        });

        // Bouton auto-détection weight_dtype (visible uniquement en mode Safetensors)
        const dtypeBtn = el("button", { class: "btn sm ghost", style: "margin-top:8px;" },
          "⟳ Detect weight_dtype from ComfyUI");
        dtypeBtn.style.display = activeMode === "safetensors" ? "" : "none";
        dtypeBtn.addEventListener("click", async () => {
          try {
            const info = await api("/api/image/unet_loader_info");
            if (info && info.default) {
              await api("/api/settings", "POST",
                { flux2_safetensors_weight_dtype: info.default });
              const allowed = (info.allowed || []).join(", ");
              toast(`weight_dtype auto-detected : "${info.default}" (values : ${allowed})`);
            } else {
              toast(`ComfyUI inaccessible — weight_dtype reste sur "default"`, true);
            }
          } catch(e) { toast(e.message, true); }
        });
        sfRow.append(dtypeBtn);

        box.append(card);
      }
      flux2UnetRendered.gguf = true;
      flux2UnetRendered.safetensors = true;
      continue;
    }

    // Rendu générique pour tous les autres composants ─────────────────────────
    const card = el("div", { class: "component-card" + (comp.required && !comp.filled ? " missing" : "") });
    const head = el("div", { class: "row" },
      el("strong", {}, comp.label + (comp.required ? " *" : " (optional)")),
      comp.filled
        ? (comp.found_in_catalog === false
            ? statusBadge("warn", "not found in the library")
            : statusBadge("ready", "defined"))
        : statusBadge("error", "missing"));
    card.append(head);

    if (Array.isArray(comp.value)) {
      card.append(el("div", { class: "hint" }, comp.value.length
        ? `${comp.value.length} LoRA configured (managed in Settings → LoRA)`
        : "No active LoRA — configurable in Settings → LoRA"));
    } else {
      const select = el("select", {});
      select.append(el("option", { value: "" }, "— choose —"));
      let files = [];
      try { files = await api(`/api/models/files?kind=${comp.kind}&family=${studioCurrentFamily}`); }
      catch (e) { files = []; }
      if (!files.length) {
        try { files = await api(`/api/models/files?kind=${comp.kind}`); } catch (e) { files = []; }
      }
      if (comp.ext) files = files.filter(f => (f.ext || "").toLowerCase() === comp.ext.toLowerCase());
      for (const f of files) {
        const loaderName = f.loader_name || f.name;
        select.append(el("option", { value: loaderName }, `${loaderName} (${f.size_human})`));
      }
      if (comp.value && !files.some(f => (f.loader_name || f.name) === comp.value)) {
        select.append(el("option", { value: comp.value }, comp.value + " (outside library)"));
      }
      select.value = comp.value || "";
      select.addEventListener("change", async () => {
        try {
          await api("/api/image/set_component", "POST",
            { family: studioCurrentFamily, component: comp.setting, value: select.value });
          refreshStudioCompatibility();
        } catch (e) { toast(e.message, true); }
      });
      card.append(select);
      if (!files.length) {
        card.append(el("div", { class: "hint" }, "No model of this type found — add a folder in Model Library."));
      }
    }
    box.append(card);
  }

  // ── Krea 2 : panneau dédié (LoRA personnage/utilitaire, forces, sampler) ──
  if (studioCurrentFamily === "krea2") {
    await renderKrea2Panel(box);
  }
}

async function renderKrea2Panel(box) {
  let settings = {};
  try { settings = await api("/api/settings"); } catch (e) {}

  // Prefer Krea-compatible LoRAs identified by the local model catalogue.
  // Keep the exact names returned by ComfyUI so nested folders remain valid.
  let allComfyLoras = [];
  let kreaCatalogLoras = [];
  try {
    const res = await api("/api/comfy/loras");
    allComfyLoras = res.loras || [];
  } catch (e) {}
  try {
    kreaCatalogLoras = await api("/api/models/files?kind=lora&family=krea2");
  } catch (e) {}

  const portableBase = name => String(name || "").replace(/\\/g, "/").split("/").pop().toLowerCase();
  const kreaBases = new Set(kreaCatalogLoras.map(f => portableBase(f.name)));
  let loraNames = kreaBases.size
    ? allComfyLoras.filter(name => kreaBases.has(portableBase(name)))
    : allComfyLoras;
  if (!loraNames.length && kreaCatalogLoras.length) {
    loraNames = kreaCatalogLoras.map(f => f.loader_name || f.name);
  }

  function saveSetting(key, value) {
    api("/api/settings", "POST", { [key]: value }).catch(e => toast(e.message, true));
  }

  function loraRow(labelTxt, selKey, strKey, defStrength) {
    const sel = el("select", { style: "width:100%; margin-top:4px;" });
    sel.append(el("option", { value: "" }, "— none —"));
    for (const n of loraNames) sel.append(el("option", { value: n }, n));
    const current = settings[selKey] || "";
    if (current && !loraNames.includes(current)) {
      sel.append(el("option", { value: current }, current + " (not listed by ComfyUI)"));
    }
    sel.value = current;

    const strengthVal = el("span", { style: "min-width:36px; text-align:right;" },
      String(settings[strKey] || defStrength));
    const slider = el("input", { type: "range", min: "0", max: "2", step: "0.05",
      style: "flex:1;", value: settings[strKey] || defStrength });
    slider.addEventListener("input", () => { strengthVal.textContent = slider.value; });
    slider.addEventListener("change", () => saveSetting(strKey, slider.value));
    sel.addEventListener("change", () => saveSetting(selKey, sel.value));

    return el("div", { style: "margin-top:10px;" },
      el("label", { class: "hint", style: "display:block;" }, labelTxt),
      sel,
      el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:4px;" },
        el("span", { class: "hint", style: "font-size:11px;" }, "Strength"), slider, strengthVal));
  }

  function numRow(labelTxt, key, def, min, max, step) {
    const inp = el("input", { type: "number", min: String(min), max: String(max),
      step: String(step), style: "width:90px;", value: settings[key] || def });
    inp.addEventListener("change", () => saveSetting(key, inp.value));
    return el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:8px;" },
      el("span", { class: "hint", style: "min-width:120px;" }, labelTxt), inp);
  }

  function resolutionSelectorRow() {
    const wrap = el("div", { style: "margin-top:10px;" });
    const ratioSel = el("select", { style: "width:240px;" },
      el("option", { value: "1:1 (Square)" }, "1:1 (Square)"),
      el("option", { value: "2:3 (Portrait Photo)" }, "2:3 (Portrait Photo)"),
      el("option", { value: "3:2 (Landscape Photo)" }, "3:2 (Landscape Photo)"),
      el("option", { value: "3:4 (Portrait)" }, "3:4 (Portrait)"),
      el("option", { value: "4:3 (Landscape)" }, "4:3 (Landscape)"),
      el("option", { value: "4:5 (Portrait Social)" }, "4:5 (Portrait Social)"),
      el("option", { value: "5:4 (Landscape Social)" }, "5:4 (Landscape Social)"),
      el("option", { value: "9:16 (Vertical)" }, "9:16 (Vertical)"),
      el("option", { value: "16:9 (Widescreen)" }, "16:9 (Widescreen)"));
    ratioSel.value = settings.krea2_aspect_ratio || "2:3 (Portrait Photo)";
    ratioSel.addEventListener("change", () => saveSetting("krea2_aspect_ratio", ratioSel.value));

    const mp = el("input", { type: "number", min: "0.25", max: "8", step: "0.25", style: "width:90px;", value: settings.krea2_megapixels || "2" });
    mp.addEventListener("change", () => saveSetting("krea2_megapixels", mp.value));

    const mult = el("input", { type: "number", min: "1", max: "128", step: "1", style: "width:90px;", value: settings.krea2_multiple || "8" });
    mult.addEventListener("change", () => saveSetting("krea2_multiple", mult.value));

    wrap.append(
      el("div", { class: "row", style: "gap:8px; align-items:center; flex-wrap:wrap;" },
        el("span", { class: "hint", style: "min-width:120px;" }, "Aspect ratio"), ratioSel),
      el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap;" },
        el("span", { class: "hint", style: "min-width:120px;" }, "Megapixels"), mp,
        el("span", { class: "hint", style: "min-width:80px; margin-left:12px;" }, "Multiple"), mult),
    );
    return wrap;
  }

  function textRow(labelTxt, key, placeholder = "") {
    const inp = el("input", { type: "text", style: "width:260px;", placeholder, value: settings[key] || "" });
    inp.addEventListener("change", () => saveSetting(key, inp.value.trim()));
    return el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap;" },
      el("span", { class: "hint", style: "min-width:120px;" }, labelTxt), inp);
  }

  function samplerProfileRow() {
    const sel = el("select", { style: "width:220px;" },
      el("option", { value: "auto" }, "Auto from model name"),
      el("option", { value: "turbo" }, "Turbo / distilled — 8 steps, CFG 1"),
      el("option", { value: "raw" }, "RAW — 52 steps, CFG 3.5"),
      el("option", { value: "custom" }, "Custom values below"));
    sel.value = settings.krea2_sampler_profile || "auto";
    sel.addEventListener("change", () => saveSetting("krea2_sampler_profile", sel.value));
    return el("div", { class: "row", style: "gap:8px; align-items:center; margin-top:10px; flex-wrap:wrap;" },
      el("span", { class: "hint", style: "min-width:120px;" }, "Sampler profile"), sel);
  }

  const card = el("div", { class: "component-card", style: "background:var(--panel-2);" },
    el("strong", {}, "Krea 2 Unified — LoRA & sampler"),
    el("div", { class: "hint", style: "margin-top:4px;" },
      "One unified pipeline for avatars, conversations, template previews and Studio. " +
      "Base model → character LoRA 1 → character LoRA 2 → utility LoRA."),
    el("div", { class: "hint", style: "margin-top:4px;" },
      kreaBases.size ? `${loraNames.length} Krea-compatible LoRA(s) detected.` :
      "No Krea family metadata found: showing all ComfyUI LoRAs. Classify Krea files in Model Library to filter this list."),
    resolutionSelectorRow(),
    loraRow("Character LoRA 1 — main character", "krea2_char_lora", "krea2_char_lora_strength", "1.0"),
    loraRow("Character LoRA 2 — user persona / second subject", "krea2_char2_lora", "krea2_char2_lora_strength", "1.0"),
    textRow("User/persona token", "krea2_user_token", "optional LoRA trigger"),
    loraRow("Utility LoRA 1 — style / rendering / effect", "krea2_util_lora", "krea2_util_lora_strength", "0.8"),
    samplerProfileRow(),
    numRow("Sampler steps", "krea2_steps", "8", 1, 100, 1),
    numRow("CFG", "krea2_cfg", "1.0", 0, 20, 0.1),
    numRow("Preview steps", "krea2_preview_steps", "6", 1, 100, 1),
    el("div", { class: "hint", style: "margin-top:10px; font-style:italic;" },
      "Set LoRA slots to none to bypass them completely. Character LoRA 2 can represent the user/persona " +
      "when you use the illustrate-with-me flow. Avatar, chat-image and Studio prompts stay editable before generation.")
  );
  box.append(card);
}

const _studioGenBtn = $("#studio-generate-btn");
if (_studioGenBtn) _studioGenBtn.addEventListener("click", async () => {
  const prompt = ($("#studio-prompt") || {}).value.trim();
  if (!prompt) return toast("Write a prompt.", true);
  const workflow = ($("#studio-workflow") || {}).value;
  const negative = ($("#studio-negative") || {}).value.trim();
  const manifest = currentStudioWorkflowManifest();
  const nRefs = manifest ? (manifest.refs || 0) : 0;
  const images = studioRefImages.filter(Boolean);
  if (nRefs > 0 && images.length < nRefs) {
    return toast(`This workflow expects ${nRefs} reference image(s) — import them before generating.`, true);
  }
  const status = $("#studio-generate-status");
  const result = $("#studio-result");
  _studioGenBtn.disabled = true;
  status.innerHTML = '<span class="spinner"></span> generation in progress…';
  result.innerHTML = "";
  try {
    const res = await api("/api/image/generate", "POST",
      { family: studioCurrentFamily, workflow, prompt, negative: negative || undefined, images });
    status.textContent = window.t("gallery.toasts.done_seed", { seed: res.seed });
    result.append(el("img", { class: "genimg", src: imgUrl(res.image) }));
    // Le DOM de la Galerie existe en permanence (vues basculées par CSS, pas recréées) :
    // on rafraîchit son contenu en arrière-plan pour qu'elle soit à jour si l'utilisateur y
    // va ensuite, sans jamais changer la vue actuellement affichée (pas de switchView ici).
    const galleryGrid = $("#gallery-grid");
    if (galleryGrid) {
      const galleryFilter = $("#gallery-filter");
      renderGallery(galleryFilter ? galleryFilter.value : "");
    }
  } catch (e) {
    status.textContent = "";
    toast(e.message, true);
  } finally {
    _studioGenBtn.disabled = false;
  }
});

// --------------------------------------------------------------------------- //
//  MODEL LIBRARY
// --------------------------------------------------------------------------- //
let libraryFolders = [];
let libraryFiles = [];

async function loadLibrary() {
  await refreshLibraryFolders();
  await refreshLibraryFiles();
}

async function refreshLibraryFolders() {
  const box = $("#library-folders");
  box.innerHTML = '<span class="hint">Chargement…</span>';
  try { libraryFolders = await api("/api/models/folders"); }
  catch (e) { box.innerHTML = ""; return toast(e.message, true); }

  box.innerHTML = "";
  if (!libraryFolders.length) {
    box.append(el("div", { class: "hint" }, "No watched folder yet."));
    return;
  }
  for (const f of libraryFolders) {
    const row = el("div", { class: "folder-row" + (f.enabled ? "" : " disabled") },
      el("span", { class: "path" }, f.path),
      el("span", { class: "hint" }, f.kind_hint ? `(${KIND_LABELS[f.kind_hint] || f.kind_hint})` : ""),
      el("span", { class: "hint" }, f.last_count != null ? `${f.last_count} file(s)` : "never scanned"),
      f.last_error ? statusBadge("error", "error") : el("span"),
      el("button", { class: "btn sm ghost", onclick: async () => {
        try { await api("/api/models/folders/toggle", "POST", { id: f.id, enabled: !f.enabled }); refreshLibraryFolders(); refreshLibraryFiles(); }
        catch (e) { toast(e.message, true); }
      } }, f.enabled ? "Disable" : "Enable"),
      el("button", { class: "btn sm ghost", onclick: async () => {
        try {
          await api("/api/models/folders/rescan", "POST", { id: f.id });
          toast(window.t("library.toasts.folder_rescanned"));
          refreshLibraryFolders(); refreshLibraryFiles();
        } catch (e) { toast(e.message, true); }
      } }, "🔄"),
      el("button", { class: "btn sm danger", onclick: async () => {
        if (!confirm("Remove this folder from the list? Files will not be deleted from disk.")) return;
        try { await api("/api/models/folders/remove", "POST", { id: f.id }); refreshLibraryFolders(); refreshLibraryFiles(); }
        catch (e) { toast(e.message, true); }
      } }, "✕")
    );
    box.append(row);
  }
}

const _libAddBtn = $("#library-add-folder-btn");
if (_libAddBtn) _libAddBtn.addEventListener("click", async () => {
  const input = $("#library-new-folder");
  const kindSel = $("#library-new-kind");
  const path = input.value.trim();
  if (!path) return toast("Enter a folder path.", true);
  try {
    await api("/api/models/folders/add", "POST", { path, kind_hint: kindSel.value || null });
    input.value = "";
    toast(window.t("library.toasts.folder_added_scan"));
    refreshLibraryFolders();
  } catch (e) { toast(e.message, true); }
});

const _libRescanAllBtn = $("#library-rescan-all-btn");
if (_libRescanAllBtn) _libRescanAllBtn.addEventListener("click", async () => {
  const status = $("#library-scan-status");
  _libRescanAllBtn.disabled = true;
  status.innerHTML = '<span class="spinner"></span> scanning…';
  try {
    const res = await api("/api/models/folders/rescan", "POST", {});
    const total = res.folders.reduce((s, f) => s + (f.count || 0), 0);
    status.textContent = `✓ ${total} file(s) detected in ${res.folders.length} folder(s).`;
    refreshLibraryFolders();
    refreshLibraryFiles();
  } catch (e) { status.textContent = ""; toast(e.message, true); }
  finally { _libRescanAllBtn.disabled = false; }
});

// ---- Identification constants ----
const MANUAL_KIND_OPTIONS = [
  ["", "— unchanged —"],
  ["checkpoint", "Checkpoint (all-in-one)"],
  ["unet", "UNet / Diffusion Model"],
  ["vae", "VAE"],
  ["clip", "CLIP / Text Encoder"],
  ["lora", "LoRA"],
  ["controlnet", "ControlNet"],
  ["embedding", "Embedding"],
  ["video_model", "Video model"],
];
const MANUAL_FAMILY_OPTIONS = [
  ["", "— unchangede —"],
  ["flux2_klein", "Flux 2 Klein"],
  ["krea2", "Krea 2"],
  ["flux", "Flux 1"],
  ["sdxl", "SDXL"],
  ["sd15", "SD 1.5"],
  ["zimage", "Z-Image"],
  ["pony", "Pony"],
  ["illustrious", "Illustrious"],
  ["wan_video", "Wan"],
  ["ltx_video", "LTX Video"],
  ["unknown", "Inconnue"],
];

function openModelIdentificationModal(f) {
  // Supprime une éventuelle modal précédente
  const existing = document.getElementById("model-id-modal");
  if (existing) existing.remove();

  const srcLabel = { auto: "automatique", civitai: "Civitai", manual: "manuel" };
  const src = f.identification_source || "auto";

  const kindSel = el("select", { class: "select-inline", style: "width:100%;" });
  for (const [v, l] of MANUAL_KIND_OPTIONS)
    kindSel.append(el("option", { value: v }, l));
  kindSel.value = f.manual_kind || "";

  const familySel = el("select", { class: "select-inline", style: "width:100%;" });
  for (const [v, l] of MANUAL_FAMILY_OPTIONS)
    familySel.append(el("option", { value: v }, l));
  familySel.value = f.manual_family || "";

  const overlay = el("div", { id: "model-id-modal", class: "modal-overlay" },
    el("div", { class: "modal-box", style: "max-width:520px;" },
      el("h3", {}, "Corriger l'identification"),
      el("p", { class: "hint", style: "margin-bottom:12px;" }, f.name),

      el("div", { class: "form-group" },
        el("label", {}, "Automatic detection"),
        el("div", { class: "hint" },
          `Type : ${KIND_LABELS[f.detected_kind] || f.detected_kind || "unknown"}  ·  `
          + `Family : ${FAMILY_LABELS[f.detected_family] || f.detected_family || "unknowne"}  ·  `
          + `Origine : ${srcLabel[src] || src}`
        )
      ),
      el("hr", { style: "margin:10px 0;" }),
      el("div", { class: "form-group" },
        el("label", {}, "Type (override manuel)"),
        kindSel
      ),
      el("div", { class: "form-group", style: "margin-top:10px;" },
        el("label", {}, "Family (override manuel)"),
        familySel
      ),
      el("div", { class: "row gap-sm", style: "margin-top:18px;justify-content:flex-end;" },
        el("button", { class: "btn ghost sm", onclick: async () => {
          try {
            await api("/api/models/files/identify", "POST", { id: f.id, reset: true });
            toast(window.t("lora.toasts.auto_detection_restored"));
            overlay.remove();
            refreshLibraryFiles();
          } catch(e) { toast(e.message, true); }
        } }, "↺ Reset"),
        el("button", { class: "btn ghost sm", onclick: () => overlay.remove() }, "Cancel"),
        el("button", { class: "btn sm", onclick: async () => {
          const mk = kindSel.value || null;
          const mf = familySel.value || null;
          if (!mk && !mf) return toast("Select at least one type or family.", true);
          try {
            await api("/api/models/files/identify", "POST", {
              id: f.id,
              manual_kind: mk,
              manual_family: mf
            });
            toast(window.t("library.toasts.identification_updated"));
            overlay.remove();
            refreshLibraryFiles();
          } catch(e) { toast(e.message, true); }
        } }, "Save")
      )
    )
  );
  document.body.append(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
}

// ── État sélection multiple Bibliothèque ─────────────────────────────────────
let _libMultiSelMode = false;
let _libSelected = new Set();   // IDs des fichiers cochés

function _libUpdateBatchBar() {
  const bar      = $("#library-batch-bar");
  const countEl  = $("#library-batch-count");
  if (!bar) return;
  bar.style.display = _libMultiSelMode ? "flex" : "none";
  if (countEl) countEl.textContent = `${_libSelected.size} selected`;
  // Cocher/décocher les checkboxes selon l'état courant
  document.querySelectorAll(".lib-row-check").forEach(cb => {
    cb.checked = _libSelected.has(cb.dataset.id);
  });
}

async function refreshLibraryFiles() {
  const box = $("#library-files");
  const countEl = $("#library-count");
  box.innerHTML = '<span class="hint">Chargement…</span>';
  const kind = ($("#library-filter-kind") || {}).value || "";
  const family = ($("#library-filter-family") || {}).value || "";
  const search = (($("#library-search") || {}).value || "").toLowerCase();
  const showIncompatible = ($("#library-show-incompatible") || {}).checked;

  try {
    let qs = [];
    if (kind) qs.push("kind=" + encodeURIComponent(kind));
    if (family) qs.push("family=" + encodeURIComponent(family));
    libraryFiles = await api("/api/models/files" + (qs.length ? "?" + qs.join("&") : ""));
  } catch (e) { box.innerHTML = ""; return toast(e.message, true); }

  let shown = libraryFiles.filter(f => !search || f.name.toLowerCase().includes(search));
  if (!showIncompatible) shown = shown.filter(f => f.family || f.kind);

  countEl.textContent = `(${shown.length} shown / ${libraryFiles.length} au total)`;
  box.innerHTML = "";
  if (!shown.length) {
    box.append(el("div", { class: "hint" }, "No model matches these filters."));
    _libUpdateBatchBar();
    return;
  }

  for (const f of shown) {
    const familyKnown = !!f.family;
    const isManual = f.has_manual_override;
    const familyBadge = familyKnown
      ? (isManual
          ? statusBadge("ok", "✎ " + (FAMILY_LABELS[f.family] || f.family))
          : statusBadge("ready", FAMILY_LABELS[f.family] || f.family))
      : statusBadge("warn", "famille incertaine");

    const pathParts = (f.path || "").replace(/\\/g, "/").split("/");
    const relPath = pathParts.length > 2 ? pathParts.slice(-3).join("/") : (f.path || "");

    // Checkbox de sélection multiple
    const checkbox = el("input", {
      type: "checkbox", class: "lib-row-check",
      "data-id": f.id,
      style: `display:${_libMultiSelMode ? "block" : "none"};flex-shrink:0;width:16px;height:16px;cursor:pointer;accent-color:var(--accent);`,
    });
    checkbox.checked = _libSelected.has(f.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) _libSelected.add(f.id);
      else _libSelected.delete(f.id);
      _libUpdateBatchBar();
    });

    const correctBtn = el("button", { class: "btn sm ghost", style: "flex-shrink:0;" }, "✎ Identifier");
    correctBtn.addEventListener("click", () => openModelIdentificationModal(f));

    const deleteBtn = el("button", {
      class: "btn sm ghost",
      style: "flex-shrink:0; color:var(--danger); opacity:.7;",
      title: "Delete this catalog entry (file remains on disk)",
    }, "🗑");
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete entry “${f.name}” from the catalog?

The file on disk is kept. You can reimport it via Refresh.`)) return;
      deleteBtn.disabled = true;
      try {
        await api("/api/models/files/delete", "POST", { id: f.id });
        toast(`Entry deleted: ${f.name}`);
        _libSelected.delete(f.id);
        refreshLibraryFiles();
      } catch(err) { toast(err.message, true); deleteBtn.disabled = false; }
    });

    // En mode multi-sélection : clic sur la ligne = cocher
    const row = el("div", {
      class: "model-row" + (_libSelected.has(f.id) && _libMultiSelMode ? " lib-row-selected" : ""),
      style: "flex-wrap:wrap;gap:4px 10px;",
    });
    row.addEventListener("click", e => {
      if (!_libMultiSelMode) return;
      if ([checkbox, correctBtn, deleteBtn].includes(e.target)) return;
      checkbox.checked = !checkbox.checked;
      if (checkbox.checked) _libSelected.add(f.id); else _libSelected.delete(f.id);
      row.classList.toggle("lib-row-selected", checkbox.checked);
      _libUpdateBatchBar();
    });

    row.append(
      el("div", { class: "row gap-sm", style: "width:100%;align-items:center;" },
        checkbox, familyBadge,
        el("span", { class: "name", style: "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" }, f.name),
        correctBtn, deleteBtn
      ),
      el("div", { class: "row gap-sm hint", style: "width:100%;font-size:0.8em;" },
        el("span", {}, "Type : " + (KIND_LABELS[f.kind] || f.kind || "unknown")),
        el("span", {}, "·"),
        el("span", {}, f.size_human || "?"),
        el("span", {}, "·"),
        el("span", { style: "opacity:0.7;" }, relPath),
        isManual ? el("span", { class: "badge badge-manual", style: "margin-left:4px;" }, "Manuel") : el("span")
      )
    );
    box.append(row);
  }
  _libUpdateBatchBar();
}

// ── Bindings Bibliothèque batch — dans DOMContentLoaded pour garantir la présence du DOM ──
document.addEventListener("DOMContentLoaded", () => {
  // ── Init icônes navigation AmiorAI (remplace les data-icon spans) ──────────
  document.querySelectorAll(".ic[data-icon]").forEach(span => {
    const name = span.dataset.icon;
    const asset = (typeof AMIORAI_NAV_ASSETS !== "undefined") ? AMIORAI_NAV_ASSETS[name] : null;
    if (asset) {
      const img = document.createElement("img");
      img.src = asset;
      img.alt = "";
      img.decoding = "async";
      const imageIcon = document.createElement("span");
      imageIcon.className = "ic nav-asset";
      imageIcon.dataset.icon = name;
      imageIcon.append(img);
      span.replaceWith(imageIcon);
    } else if (typeof amIcon !== "undefined") {
      const svgIcon = amIcon(name, 20);
      svgIcon.className = "ic ai-ic";
      svgIcon.dataset.icon = name;
      span.replaceWith(svgIcon);
    }
  });

  const multiBtn = document.getElementById("library-multisel-btn");
  if (multiBtn) {
    multiBtn.addEventListener("click", () => {
      _libMultiSelMode = !_libMultiSelMode;
      _libSelected.clear();
      multiBtn.textContent = _libMultiSelMode ? window.t("library.multi.exit") : window.t("library.multi.enter");
      multiBtn.style.background = _libMultiSelMode ? "var(--accent)" : "var(--panel-2,#221535)";
      multiBtn.style.color = _libMultiSelMode ? "#fff" : "var(--accent)";
      refreshLibraryFiles();
    });
  }

  const batchSelAll  = document.getElementById("library-batch-selall");
  const batchDeselAll= document.getElementById("library-batch-deselall");
  const batchApply   = document.getElementById("library-batch-apply-btn");
  const batchReset   = document.getElementById("library-batch-reset-btn");

  if (batchSelAll) batchSelAll.addEventListener("click", () => {
    libraryFiles.forEach(f => _libSelected.add(f.id));
    _libUpdateBatchBar();
    document.querySelectorAll(".lib-row-check").forEach(cb => cb.checked = true);
    document.querySelectorAll(".model-row").forEach(r => r.classList.add("lib-row-selected"));
  });
  if (batchDeselAll) batchDeselAll.addEventListener("click", () => {
    _libSelected.clear();
    _libUpdateBatchBar();
    document.querySelectorAll(".lib-row-check").forEach(cb => cb.checked = false);
    document.querySelectorAll(".model-row").forEach(r => r.classList.remove("lib-row-selected"));
  });

  async function _applyBatch(reset=false) {
    if (!_libSelected.size) return toast(window.t("common.file_required"), true);
    const kindSel   = document.getElementById("library-batch-kind");
    const familySel = document.getElementById("library-batch-family");
    const mk = kindSel?.value || null;
    const mf = familySel?.value || null;
    if (!reset && !mk && !mf) return toast("Choisis au moins un type ou une famille.", true);
    const ids = Array.from(_libSelected);
    const btn = reset ? batchReset : batchApply;
    if (btn) btn.disabled = true;
    try {
      const r = await api("/api/models/files/identify/batch", "POST", {
        ids, manual_kind: mk, manual_family: mf, reset,
      });
      toast(`${r.updated} file(s) updated.${r.errors?.length ? ` ${r.errors.length} error(s).` : ""}`);
      _libSelected.clear();
      refreshLibraryFiles();
    } catch(e) { toast(e.message, true); }
    finally { if (btn) btn.disabled = false; }
  }

  if (batchApply) batchApply.addEventListener("click", () => _applyBatch(false));
  if (batchReset) batchReset.addEventListener("click", () => {
    if (!_libSelected.size) return toast(window.t("common.file_required"), true);
    if (!confirm(`Réinitialiser la détection sur ${_libSelected.size} fichier(s) ?`)) return;
    _applyBatch(true);
  });
});

for (const id of ["library-search", "library-filter-kind", "library-filter-family", "library-show-incompatible"]) {
  const node = $("#" + id);
  if (node) node.addEventListener(id === "library-search" ? "input" : "change", refreshLibraryFiles);
}



// ─────────────────────────────────────────────────────────────────────────── //
//  MODELS (vue "models") — Réutilise intégralement l'infra Civitai LoRA
// ─────────────────────────────────────────────────────────────────────────── //

const MODEL_KIND_LABELS = {
  checkpoint: "Checkpoint", unet: "UNet", vae: "VAE", clip: "CLIP",
  controlnet: "ControlNet", video_model: "Video model", embedding: "Embedding",
};
const MODEL_KIND_ICONS = {
  checkpoint: "🧱", unet: "🔲", vae: "📐", clip: "📝",
  controlnet: "🎛️", video_model: "🎬", embedding: "💬",
};

let _modelsKindFilter = "";

// ── Cartes models ────────────────────────────────────────────────────────
async function setModelAsActive(settingKey, filename, label) {
  try {
    await api("/api/settings", "POST", { [settingKey]: filename });
    toast(`${label} saved: ${filename}`);
    loadModels();
  } catch(e) { toast(e.message, true); }
}

function buildSetActiveButtons(m) {
  const buttons = [];
  const ext = (m.name || "").toLowerCase().split(".").pop();
  const kind = m.kind || "";
  const family = m.family || "";

  if (kind === "unet" && family === "flux2_klein") {
    if (ext === "gguf") {
      const b = el("button", { class: "btn sm", title: "Set as active GGUF UNet" },
        "▶ UNet GGUF");
      b.addEventListener("click", async () => {
        await setModelAsActive("img_unet_gguf", m.name, "UNet GGUF");
        await setModelAsActive("img_unet", m.name, "");
        const mode = await api("/api/settings").then(s => s.flux2_loader_mode);
        if (mode !== "gguf") toast(window.t("studio.unet.gguf_saved_hint"), true);
      });
      buttons.push(b);
    } else if (ext === "safetensors") {
      const b = el("button", { class: "btn sm", title: "Set as active Safetensors UNet" },
        "▶ UNet ST");
      b.addEventListener("click", async () => {
        await setModelAsActive("img_unet_safetensors", m.name, "UNet Safetensors");
        const mode = await api("/api/settings").then(s => s.flux2_loader_mode);
        if (mode !== "safetensors") toast(window.t("studio.unet.st_saved_hint"), true);
      });
      buttons.push(b);
    }
  }

  if (kind === "clip") {
    const b = el("button", { class: "btn sm", title: "Set as active CLIP" }, "▶ CLIP");
    b.addEventListener("click", () => setModelAsActive("img_clip", m.name, "CLIP"));
    buttons.push(b);
  }

  if (kind === "vae") {
    const b = el("button", { class: "btn sm", title: "Set as active VAE" }, "▶ VAE");
    b.addEventListener("click", () => setModelAsActive("img_vae", m.name, "VAE"));
    buttons.push(b);
  }

  return buttons;
}

function buildModelCard(m) {
  const hasCivitai = m.has_civitai;
  const kindLabel  = MODEL_KIND_LABELS[m.kind] || m.kind || "?";
  const kindIcon   = MODEL_KIND_ICONS[m.kind] || "📦";
  const famLabel   = LORA_FAMILY_LABELS[m.family] || m.family || "";
  const src        = m.identification_source || "auto";

  // Badges
  const badges = el("div", { class: "lm-badges", style: "margin-top:6px;" });
  badges.append(el("span", { class: "lm-badge" }, "LOCAL"));
  if (hasCivitai) {
    badges.append(el("span", { class: "lm-badge lm-badge-ok" },
      m.has_manual_civitai ? "MANUAL LINK" : "CIVITAI LINKED"));
  }
  if (src === "manual") badges.append(el("span", { class: "lm-badge lm-badge-warn" }, "IDENTIFIED"));

  // Preview
  const previewEl = m.preview_local_url
    ? el("img", { src: m.preview_local_url, class: "lm-preview", loading: "lazy" })
    : el("div", { class: "lm-preview-placeholder" }, kindIcon);

  // Info
  const infoEl = el("div", { class: "lm-info" },
    el("div", { class: "lm-name", title: m.name }, m.name),
    el("div", { class: "lm-meta" }, `${kindLabel}${famLabel ? " · " + famLabel : ""}${m.size_human ? " · " + m.size_human : ""}`),
    hasCivitai
      ? el("div", { class: "hint", style: "font-size:11px; margin-top:3px;" },
          (m.civitai_model_name || "") + (m.civitai_version_name ? " (" + m.civitai_version_name + ")" : ""),
          m.civitai_creator ? el("span", { style: "opacity:.6;" }, " — " + m.civitai_creator) : el("span"))
      : el("span"),
    badges
  );

  // Actions
  const actLink   = el("button", { class: "btn sm ghost", title: "Link to Civitai" }, "🔗 Link");
  const actOpen   = el("button", { class: "btn sm ghost", title: "Ouvrir sur Civitai" }, "↗");
  const actRefresh = el("button", { class: "btn sm ghost", title: "Actualiser les infos" }, "↺");
  const actDissoc = el("button", { class: "btn sm ghost", title: "Unlink from Civitai",
                                   style: "color:var(--danger);" }, "✕");
  if (!hasCivitai) { actOpen.disabled = true; actRefresh.disabled = true; actDissoc.disabled = true; }
  else if (!m.civitai_url) { actOpen.disabled = true; }

  actLink.addEventListener("click",    () => openModelCivitaiModal(m));
  actOpen.addEventListener("click",    () => { if (m.civitai_url) window.open(m.civitai_url, "_blank"); });
  actRefresh.addEventListener("click", () => refreshModelCivitai(m.id));
  actDissoc.addEventListener("click",  () => dissociateModelCivitai(m.id));

  // Boutons "Set comme active" selon kind + famille + extension
  const setButtons = buildSetActiveButtons(m);

  const actRow = el("div", { class: "lm-actions row gap-sm", style: "flex-wrap:wrap;" },
    actLink, actOpen, actRefresh, actDissoc, ...setButtons);

  const card = el("div", { class: "lm-card" }, previewEl, infoEl, actRow);
  return card;
}

// ── Cartes wishlist ────────────────────────────────────────────────────────
function buildWishlistCard(w) {
  const isInstalled = w.is_installed;
  const previewEl = w.preview_local_url
    ? el("img", { src: w.preview_local_url, class: "lm-preview", loading: "lazy" })
    : el("div", { class: "lm-preview-placeholder" }, "📦");

  const badges = el("div", { class: "lm-badges", style: "margin-top:6px;" });
  badges.append(el("span", { class: "lm-badge" + (isInstalled ? " lm-badge-ok" : "") },
    isInstalled ? "INSTALLED LOCALLY" : "NOT INSTALLED"));
  badges.append(el("span", { class: "lm-badge" }, "MANUAL LINK"));

  const infoEl = el("div", { class: "lm-info" },
    el("div", { class: "lm-name" }, w.civitai_model_name || "(sans nom)"),
    el("div", { class: "lm-meta" },
      (w.civitai_version_name || "") + (w.civitai_base_model ? " · " + w.civitai_base_model : "")),
    w.civitai_creator ? el("div", { class: "hint", style: "font-size:11px;" }, w.civitai_creator) : el("span"),
    badges
  );

  const checkBtn  = el("button", { class: "btn sm" }, "🔍 Check if installed");
  const openBtn   = el("button", { class: "btn sm ghost" }, "↗ Civitai");
  const removeBtn = el("button", { class: "btn sm ghost", style: "color:var(--danger);" }, "✕ Retirer");
  if (!w.civitai_url) openBtn.disabled = true;

  checkBtn.addEventListener("click", async () => {
    try {
      const r = await api("/api/models/wishlist/check", "POST", { id: w.id });
      if (r.installed) {
        toast(`File found: ${r.local_file_name}`);
        loadModels();
      } else {
        toast(window.t("models.file_not_detected"), true);
      }
    } catch(e) { toast(e.message, true); }
  });
  openBtn.addEventListener("click",   () => { if (w.civitai_url) window.open(w.civitai_url, "_blank"); });
  removeBtn.addEventListener("click", async () => {
    if (!confirm(`Retirer « ${w.civitai_model_name || "(sans nom)"}” de la liste ?`)) return;
    try { await api("/api/models/wishlist/remove", "POST", { id: w.id }); loadModels(); }
    catch(e) { toast(e.message, true); }
  });

  return el("div", { class: "lm-card", style: "opacity:.85; border-style:dashed;" },
    previewEl, infoEl,
    el("div", { class: "lm-actions row gap-sm", style: "flex-wrap:wrap;" }, checkBtn, openBtn, removeBtn));
}

// ── Modal liaison Civitai ─────────────────────────────────────────────────
function openModelCivitaiModal(m) {
  const existing = document.getElementById("model-civitai-modal");
  if (existing) existing.remove();

  const urlInput = el("input", {
    type: "text", class: "input-inline",
    placeholder: "https://civitai.com/models/... or numeric ID",
    style: "width:100%;"
  });

  const statusEl = el("div", { class: "hint", style: "min-height:20px; margin-top:8px;" });

  const searchBtn = el("button", { class: "btn sm" }, "Fetch info");
  const confirmBtn = el("button", { class: "btn sm", disabled: true }, "Save la liaison");
  let fetchedData = null;

  const previewBox = el("div", { style: "margin-top:12px; display:none;" });

  searchBtn.addEventListener("click", async () => {
    const url = urlInput.value.trim();
    if (!url) return toast("Colle une URL ou un ID Civitai.", true);
    searchBtn.disabled = true;
    statusEl.textContent = "Recherche en cours…";
    try {
      fetchedData = await api("/api/civitai/fetch_by_url", "POST", { url });
      statusEl.textContent = "";
      previewBox.style.display = "block";
      previewBox.innerHTML = "";
      previewBox.append(
        el("div", { class: "row gap-sm", style: "align-items:flex-start;" },
          fetchedData.civitai_preview_url
            ? el("img", { src: fetchedData.civitai_preview_url, style: "width:80px; border-radius:8px; object-fit:cover;" })
            : el("div", { class: "lm-preview-placeholder", style: "width:80px; height:80px; border-radius:8px;" }, "📦"),
          el("div", {},
            el("div", { style: "font-weight:600;" }, fetchedData.civitai_model_name || "(sans nom)"),
            el("div", { class: "hint" }, fetchedData.civitai_version_name || ""),
            el("div", { class: "hint" }, `Auteur : ${fetchedData.civitai_creator || "?"}`),
            el("div", { class: "hint" }, `Base : ${fetchedData.civitai_base_model || "?"}`),
            (fetchedData.civitai_tags || []).length
              ? el("div", { class: "hint", style: "font-size:11px;" }, (fetchedData.civitai_tags || []).slice(0,6).join(", "))
              : el("span")
          )
        )
      );
      confirmBtn.disabled = false;
    } catch(e) {
      statusEl.textContent = "Error: " + e.message;
    } finally {
      searchBtn.disabled = false;
    }
  });

  confirmBtn.addEventListener("click", async () => {
    if (!fetchedData) return;
    confirmBtn.disabled = true;
    try {
      await api("/api/civitai/associate", "POST", {
        model_file_id: m.id,
        civitai_data: fetchedData
      });
      toast(window.t("models.civitai_link_saved"));
      overlay.remove();
      loadModels();
    } catch(e) {
      toast(e.message, true);
      confirmBtn.disabled = false;
    }
  });

  const overlay = el("div", { id: "model-civitai-modal", class: "modal-overlay" },
    el("div", { class: "modal-box", style: "max-width:540px;" },
      el("h3", {}, "Link to Civitai"),
      el("p", { class: "hint" }, m.name),
      el("div", { class: "form-group", style: "margin-top:12px;" },
        el("label", {}, "URL ou ID Civitai"),
        urlInput,
        el("div", { class: "row gap-sm", style: "margin-top:8px;" }, searchBtn)
      ),
      statusEl,
      previewBox,
      el("div", { class: "row gap-sm", style: "margin-top:16px; justify-content:flex-end;" },
        el("button", { class: "btn sm ghost", onclick: () => overlay.remove() }, "Cancel"),
        confirmBtn
      )
    )
  );
  document.body.append(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
}

// ── Modal ajout wishlist ──────────────────────────────────────────────────
function openWishlistAddModal() {
  const existing = document.getElementById("wishlist-add-modal");
  if (existing) existing.remove();

  const urlInput = el("input", {
    type: "text", class: "input-inline",
    placeholder: "https://civitai.com/models/... ou ID",
    style: "width:100%;"
  });
  const notesInput = el("textarea", {
    class: "input-inline", rows: "2",
    placeholder: "Optional notes…",
    style: "width:100%; margin-top:8px; resize:vertical;"
  });
  const statusEl = el("div", { class: "hint", style: "min-height:18px; margin-top:6px;" });
  const addBtn = el("button", { class: "btn sm" }, "Add to my list");

  addBtn.addEventListener("click", async () => {
    const url = urlInput.value.trim();
    if (!url) return toast("Colle une URL ou un ID Civitai.", true);
    addBtn.disabled = true;
    statusEl.textContent = window.t("models.civitai_fetching");
    try {
      const r = await api("/api/models/wishlist/add", "POST", {
        url, notes: notesInput.value.trim()
      });
      toast(`Added: ${r.name}`);
      overlay.remove();
      loadModels();
    } catch(e) {
      statusEl.textContent = "Error: " + e.message;
      addBtn.disabled = false;
    }
  });

  const overlay = el("div", { id: "wishlist-add-modal", class: "modal-overlay" },
    el("div", { class: "modal-box", style: "max-width:480px;" },
      el("h3", {}, "Add model from Civitai"),
      el("p", { class: "hint" },
        "Add a profile even if the file is not installed locally yet. ",
        "This model cannot be activated in AmiorAI until a local file is detected."),
      el("div", { class: "form-group", style: "margin-top:12px;" },
        el("label", {}, "URL ou ID Civitai"), urlInput,
        el("label", { style: "margin-top:8px; display:block;" }, "Notes"), notesInput
      ),
      statusEl,
      el("div", { class: "row gap-sm", style: "margin-top:14px; justify-content:flex-end;" },
        el("button", { class: "btn sm ghost", onclick: () => overlay.remove() }, "Cancel"),
        addBtn
      )
    )
  );
  document.body.append(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
}

// ── Actions Civitai par card ──────────────────────────────────────────────
async function refreshModelCivitai(fileId) {
  try {
    await api("/api/civitai/enrich", "POST", { model_file_id: fileId });
    toast(window.t("models.civitai_refreshed"));
    loadModels();
  } catch(e) { toast(e.message, true); }
}

async function dissociateModelCivitai(fileId) {
  if (!confirm("Unlink this model from Civitai? The local preview will be kept.")) return;
  try {
    // Utilise la même route que pour les LoRA (même table lora_civitai_metadata)
    await api("/api/lora/civitai/dissociate", "POST", { model_file_id: fileId });
    toast(window.t("models.civitai_unlinked"));
    loadModels();
  } catch(e) { toast(e.message, true); }
}

// ── Chargement principal ──────────────────────────────────────────────────
async function loadModels() {
  const grid         = $("#models-grid");
  const wishlistGrid = $("#models-wishlist-grid");
  if (!grid) return;
  grid.innerHTML = '<span class="hint">Chargement…</span>';

  try {
    const qs = _modelsKindFilter ? `?kind=${encodeURIComponent(_modelsKindFilter)}` : "";
    const [models, wishlist] = await Promise.all([
      api(`/api/models/enriched${qs}`),
      api("/api/models/wishlist"),
    ]);

    grid.innerHTML = "";
    if (!models.length) {
      grid.append(el("div", { class: "hint" },
        "No model detected. Run a scan from the Library view."));
    } else {
      for (const m of models) grid.append(buildModelCard(m));
    }

    if (wishlistGrid) {
      wishlistGrid.innerHTML = "";
      const section = $("#models-wishlist-section");
      if (wishlist.length) {
        if (section) section.style.display = "";
        for (const w of wishlist) wishlistGrid.append(buildWishlistCard(w));
      } else {
        if (section) section.style.display = "none";
      }
    }
  } catch(e) {
    grid.innerHTML = "";
    grid.append(el("div", { class: "hint", style: "color:var(--danger);" },
      "Loading error: " + e.message));
  }
}

// ── Bindings ──────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Bouton analyse doublons LoRA (dans la vue LoRA si présent)
  const dupBtn = document.getElementById("lora-analyze-dup-btn");
  if (dupBtn) dupBtn.addEventListener("click", runLoraDuplicateAnalysis);

  const refreshBtn = $("#models-refresh-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadModels);

  const addBtn = $("#models-wishlist-add-btn");
  if (addBtn) addBtn.addEventListener("click", openWishlistAddModal);

  // Filtres par kind
  document.querySelectorAll(".models-kind-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".models-kind-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _modelsKindFilter = btn.dataset.kind || "";
      loadModels();
    });
  });
});



// ─────────────────────────────────────────────────────────────────────────── //
//  RÉSEAU LOCAL (LAN)
// ─────────────────────────────────────────────────────────────────────────── //

async function loadLanSettings() {
  try {
    const info = await api("/api/lan/info");
    if (info.ok === false) return; // pas localhost, silencieux
    const localRadio   = document.getElementById("lan-local");
    const networkRadio = document.getElementById("lan-network");
    const infoBox      = document.getElementById("lan-info-box");
    const urlDisplay   = document.getElementById("lan-url-display");
    const restartNote  = document.getElementById("lan-restart-note");
    const sessCount    = document.getElementById("lan-sessions-count");
    const revokeBtn    = document.getElementById("lan-revoke-btn");
    if (!localRadio) return;

    const isLan = info.mode === "lan";
    localRadio.checked   = !isLan;
    networkRadio.checked =  isLan;
    // Afficher la section LAN toujours (pour configurer le code avant activation)
    infoBox.style.display = "";
    if (restartNote) restartNote.style.display = "none"; // masqué au chargement
    if (urlDisplay) {
      urlDisplay.textContent = isLan && info.url
        ? `Network address: ${info.url}`
        : `LAN address (local mode active): http://${info.local_ip}:${info.port}`;
    }
    if (sessCount) sessCount.textContent = window.t("system.lan.active_sessions", { count: info.active_sessions || 0 });
    if (info.code_set) {
      const codeStatus = document.getElementById("lan-code-status");
      if (codeStatus) codeStatus.textContent = window.t("system.lan.code_configured");
    }

    const setMode = async (mode) => {
      try {
        await api("/api/settings", "POST", { lan_mode: mode });
        if (restartNote) restartNote.style.display = "";
      } catch(e) { toast(e.message, true); }
    };

    localRadio.addEventListener("change",   () => { if (localRadio.checked)   setMode("local"); });
    networkRadio.addEventListener("change", () => { if (networkRadio.checked) setMode("lan"); });

    const copyBtn = document.getElementById("lan-copy-url-btn");
    if (copyBtn) copyBtn.addEventListener("click", () => {
      const url = info.url || `http://${info.local_ip}:${info.port}`;
      navigator.clipboard.writeText(url).catch(() => {});
      toast(window.t("system.lan.address_copied", { url }));
    });

    const genCodeBtn = document.getElementById("lan-gen-code-btn");
    if (genCodeBtn && !genCodeBtn._bound) {
      genCodeBtn._bound = true;
      genCodeBtn.addEventListener("click", async () => {
        if (!confirm(window.t("system.lan.new_code_confirm"))) return;
        try {
          const r = await api("/api/lan/code/generate", "POST", {});
          if (r.ok && r.code) {
            const display = document.getElementById("lan-code-display");
            if (display) {
              const formatted = r.code.slice(0,4) + " " + r.code.slice(4);
              display.innerHTML = `<strong style="font-size:1.4em;letter-spacing:4px;">${formatted}</strong>`;
              display.style.display = "";
            }
            const codeStatus = document.getElementById("lan-code-status");
            if (codeStatus) codeStatus.textContent = window.t("system.lan.code_configured");
            if (sessCount) sessCount.textContent = window.t("system.lan.active_sessions", { count: 0 });
            toast(window.t("system.lan.new_code_done"));
          }
        } catch(e) { toast(e.message, true); }
      });
    }

    if (revokeBtn && !revokeBtn._bound) {
      revokeBtn._bound = true;
      revokeBtn.addEventListener("click", async () => {
        if (!confirm("Disconnect all LAN devices?")) return;
        try {
          await api("/api/lan/sessions/revoke", "POST", {});
          if (sessCount) sessCount.textContent = window.t("system.lan.active_sessions", { count: 0 });
          toast(window.t("system.lan.sessions_revoked"));
        } catch(e) { toast(e.message, true); }
      });
    }

  } catch(e) {
    console.warn("[LAN] Unable to load network info:", e.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────── //
//  DOUBLONS LORA
// ─────────────────────────────────────────────────────────────────────────── //

let _dupAnalysisTimer = null;

async function runLoraDuplicateAnalysis() {
  const btn  = document.getElementById("lora-analyze-dup-btn");
  const prog = document.getElementById("lora-dup-progress");
  if (!btn) return;
  btn.disabled = true;
  if (prog) prog.textContent = "Analysis in progress…";
  try {
    const r = await api("/api/loras/analyze_duplicates", "POST", {});
    if (!r.ok) { toast(r.error || "Analysis error", true); btn.disabled = false; return; }
    // Poll statut
    if (_dupAnalysisTimer) clearInterval(_dupAnalysisTimer);
    _dupAnalysisTimer = setInterval(async () => {
      try {
        const s = await api("/api/loras/duplicates/status");
        if (prog) prog.textContent = `Analysis: ${s.done} / ${s.total}`;
        if (!s.running) {
          clearInterval(_dupAnalysisTimer);
          btn.disabled = false;
          if (prog) prog.textContent = `Done — ${s.done} LoRAs analyzed.`;
          refreshLoraLib(); // rafraîchir la galerie avec les badges doublons
        }
      } catch(e) { clearInterval(_dupAnalysisTimer); btn.disabled = false; }
    }, 800);
  } catch(e) { toast(e.message, true); btn.disabled = false; }
}

function buildDuplicateBadge(count) {
  return el("span", { class: "lm-badge lm-badge-dupe", title: "Identical copies detected" },
    `${count} COPIES`);
}

async function showDuplicateCopies(primaryId) {
  try {
    const result = await api("/api/loras/duplicates");
    const group = (result.groups || []).find(g => g.primary.id === primaryId);
    if (!group) return toast(window.t("lora.duplicates.none_for_file"), true);

    const existing = document.getElementById("lora-dup-detail-modal");
    if (existing) existing.remove();

    const copyList = el("div", { style: "margin-top:10px;" });
    copyList.append(el("div", { class: "hint", style: "margin-bottom:6px;" },
      `Copie principale : ${group.primary.path || group.primary.name}`));
    for (const c of group.copies) {
      const row = el("div", { class: "row gap-sm", style: "margin-bottom:4px; flex-wrap:wrap;" },
        el("span", { class: "hint", style: "flex:1; word-break:break-all;" }, c.path || c.name),
        el("button", { class: "btn sm ghost", onclick: () => {
          navigator.clipboard.writeText(c.path || c.name).catch(() => {});
          toast(window.t("common.path_copied"));
        }}, "⎘")
      );
      copyList.append(row);
    }

    const overlay = el("div", { id: "lora-dup-detail-modal", class: "modal-overlay" },
      el("div", { class: "modal-box", style: "max-width:520px;" },
        el("h3", {}, "Copies identiques"),
        el("p", { class: "hint" }, `Hash SHA256 : ${group.hash.slice(0,16)}…`),
        copyList,
        el("div", { style: "margin-top:16px; text-align:right;" },
          el("button", { class: "btn sm ghost", onclick: () => overlay.remove() }, "Fermer"))
      )
    );
    document.body.append(overlay);
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
  } catch(e) { toast(e.message, true); }
}


// ─────────────────────────────────────────────────────────────────────────── //
//  DIAGNOSTIC — rendu localisable à chaud
// ─────────────────────────────────────────────────────────────────────────── //
let _diagReport = null;
let _diagLoading = false;

const DIAG_ICON  = { ok: "✓", warning: "!", error: "✗", skipped: "–" };
const DIAG_CLASS = { ok: "diag-ok", warning: "diag-warn", error: "diag-err", skipped: "diag-skip" };

// Le backend retourne désormais des clés + variables i18n. Les champs texte
// historiques restent comme filet de sécurité pour les rapports créés par une
// version antérieure ou pour une extension tierce.
function diagT(key, vars, fallback = "") {
  if (!key || typeof window.t !== "function") return fallback;
  const translated = window.t(key, vars);
  return translated === key ? fallback : translated;
}

function diagCheckName(check) {
  return diagT(check && check.name_key, check && check.name_vars, (check && check.name) || "");
}

function diagCheckDetail(check) {
  return diagT(check && check.detail_key, check && check.detail_vars, (check && check.detail) || "");
}

function diagSectionLabel(section) {
  return diagT(section && section.label_key, null, (section && section.label) || "");
}

function diagTechnicalText(check) {
  const items = Array.isArray(check && check.technical_items) ? check.technical_items : [];
  const rendered = items
    .map(item => diagT(item && item.key, item && item.vars, item && item.fallback ? item.fallback : ""))
    .filter(Boolean);
  return rendered.length ? rendered.join(" · ") : ((check && check.technical) || "");
}

function setDiagRunButton(loading) {
  const runBtn = $("#diag-run-btn");
  if (!runBtn) return;
  runBtn.disabled = loading;
  runBtn.textContent = loading
    ? diagT("diagnostic.ui.run_in_progress", null, "⟳ En cours…")
    : diagT("diagnostic.run_btn", null, "▶ Lancer");
}

function renderDiagnostic(report) {
  _diagReport = report;
  const sectBox = $("#diag-sections");
  const sumBox  = $("#diag-summary");
  const copyBtn = $("#diag-copy-btn");
  if (!sectBox || !sumBox || !copyBtn) return;
  sectBox.innerHTML = "";

  if (report.error) {
    sectBox.append(el("div", { class: "diag-err-banner" },
      diagT("diagnostic.ui.run_failed", { error: report.error }, "Impossible de lancer le diagnostic : " + report.error)));
    return;
  }

  // Résumé
  const summary = report.summary || {};
  sumBox.style.display = "block";
  sumBox.innerHTML = "";
  sumBox.append(
    el("div", { class: "row gap-sm", style: "align-items:center;" },
      el("span", { class: "diag-ok", style: "font-size:1.05em;" },
        diagT("diagnostic.ui.summary_ok", { count: summary.ok || 0 }, `✓ ${summary.ok || 0} OK`)),
      summary.warning ? el("span", { class: "diag-warn", style: "font-size:1.05em;" },
        diagT("diagnostic.ui.summary_warning", { count: summary.warning }, `! ${summary.warning} avertissement(s)`)) : el("span"),
      summary.error ? el("span", { class: "diag-err", style: "font-size:1.05em;" },
        diagT("diagnostic.ui.summary_error", { count: summary.error }, `✗ ${summary.error} erreur(s)`)) : el("span"),
      el("span", { class: "hint", style: "margin-left:auto;" },
        diagT("diagnostic.ui.duration", { seconds: report.elapsed, timestamp: report.timestamp }, `Durée : ${report.elapsed}s — ${report.timestamp}`))
    )
  );

  // Sections
  for (const section of (report.sections || [])) {
    const sectionCard = el("div", { class: "panel diag-section" });
    sectionCard.append(el("h2", { style: "margin-top:0; margin-bottom:10px;" }, diagSectionLabel(section)));

    for (const check of (section.checks || [])) {
      const cssClass = DIAG_CLASS[check.status] || "";
      const icon = DIAG_ICON[check.status] || "?";
      const row = el("div", { class: "diag-row" });
      row.append(
        el("span", { class: `diag-icon ${cssClass}` }, icon),
        el("span", { class: "diag-name" }, diagCheckName(check)),
        el("span", { class: `diag-detail ${cssClass}` }, diagCheckDetail(check))
      );

      const technical = diagTechnicalText(check);
      if (technical) {
        const details = el("details", { class: "diag-technical" },
          el("summary", {}, diagT("diagnostic.ui.technical_details", null, "Détail technique")),
          el("pre", {}, technical)
        );
        sectionCard.append(el("div", { class: "diag-row-wrap" }, row, details));
      } else {
        sectionCard.append(row);
      }
    }
    sectBox.append(sectionCard);
  }

  copyBtn.disabled = false;
}

function buildDiagText(report) {
  if (!report || report.error) {
    return diagT("diagnostic.ui.report_unavailable", null, "Diagnostic non disponible.");
  }
  const lines = [
    diagT("diagnostic.ui.report_header", { timestamp: report.timestamp }, `AMIORAI DIAGNOSTIC — ${report.timestamp}`),
    "",
  ];
  for (const section of (report.sections || [])) {
    lines.push(diagSectionLabel(section));
    for (const check of (section.checks || [])) {
      const tag = diagT(`diagnostic.report_status.${check.status}`, null,
        ({ ok: "OK", warning: "WARNING", error: "ERROR", skipped: "SKIP" }[check.status] || "?"));
      lines.push(`  [${tag}] ${diagCheckName(check)} — ${diagCheckDetail(check)}`);
      const technical = diagTechnicalText(check);
      if (technical && check.status === "error") {
        lines.push(diagT("diagnostic.ui.report_technical", { detail: technical }, `        → ${technical}`));
      }
    }
    lines.push("");
  }
  const summary = report.summary || {};
  lines.push(diagT("diagnostic.ui.report_summary", {
    ok: summary.ok || 0,
    warning: summary.warning || 0,
    error: summary.error || 0,
  }, `Résumé : ${summary.ok || 0} OK  ${summary.warning || 0} avertissement(s)  ${summary.error || 0} erreur(s)`));
  lines.push(diagT("diagnostic.ui.report_duration", { seconds: report.elapsed }, `Durée : ${report.elapsed}s`));
  return lines.join("\n");
}

async function loadDiagnostic() {
  const sectBox = $("#diag-sections");
  const sumBox  = $("#diag-summary");
  const copyBtn = $("#diag-copy-btn");
  if (!sectBox || !sumBox || !copyBtn) return;

  _diagLoading = true;
  setDiagRunButton(true);
  sumBox.style.display = "none";
  sectBox.innerHTML = "";
  sectBox.append(el("div", { class: "hint", style: "padding:20px 0;" },
    diagT("diagnostic.ui.loading", null, "Diagnostic en cours, patientez…")));
  copyBtn.disabled = true;

  try {
    const family = (($("#diag-image-family") || {}).value || "flux2_klein");
    const report = await api("/api/diagnostic?family=" + encodeURIComponent(family));
    renderDiagnostic(report);
  } catch (error) {
    sectBox.innerHTML = "";
    sectBox.append(el("div", { class: "diag-err-banner" },
      diagT("diagnostic.ui.request_error", { error: error.message }, "Erreur lors du diagnostic : " + error.message)));
  } finally {
    _diagLoading = false;
    setDiagRunButton(false);
  }
}

function liveStateLabel(state) {
  return diagT(`diagnostic.live.states.${state}`, null, state || "idle");
}

function liveStateClass(state, reachable, hasError) {
  if (hasError || reachable === false || state === "error") return "live-error";
  if (["loading", "waiting", "stabilizing", "checking", "unloading", "active",
       "submitting", "queued", "generating", "processing", "downloading"].includes(state)) return "live-busy";
  return "live-ok";
}

function renderLiveCard(target, title, state, message, meta, cssClass) {
  if (!target) return;
  target.className = "diag-live-card " + cssClass;
  target.innerHTML = "";
  target.append(
    el("div", { class: "live-title" }, el("span", { class: "live-dot" }), title),
    el("div", { class: "live-main" }, liveStateLabel(state)),
    el("div", { class: "live-meta" }, message || ""),
    meta ? el("div", { class: "live-meta", style: "margin-top:4px;" }, meta) : el("span")
  );
}

async function refreshDiagnosticRuntime() {
  const lmBox = $("#diag-live-lm");
  const comfyBox = $("#diag-live-comfy");
  if (!lmBox || !comfyBox || document.hidden) return;
  const diagView = $("#view-diagnostic");
  if (diagView && !diagView.classList.contains("active")) return;
  try {
    const status = await api("/api/runtime/status");
    const lm = status.lmstudio || {};
    const activity = lm.activity || {};
    const lifecycle = lm.lifecycle || {};
    let lmState = activity.gen_active ? "generating" : (lifecycle.state || "idle");
    let lmMessage = activity.gen_active
      ? `LM Studio is generating a ${lifecycle.role || "text"} response`
      : (lifecycle.message || (lm.reachable ? "LM Studio is reachable" : "LM Studio is unavailable"));
    const loaded = [
      lm.conversational_loaded ? "conversation loaded" : "conversation unloaded",
      lm.utility_applicable ? (lm.utility_loaded ? "utility loaded" : "utility unloaded") : "utility disabled",
    ].join(" · ");
    const lmElapsed = (activity.gen_active ? activity.gen_elapsed : lifecycle.elapsed) || 0;
    const lmMeta = `${loaded}${lmElapsed ? ` · ${lmElapsed}s` : ""}`;
    renderLiveCard(lmBox, "LM Studio", lmState, lmMessage, lmMeta,
      liveStateClass(lmState, lm.reachable, lifecycle.error || activity.error));

    const comfy = status.comfyui || {};
    const generation = comfy.generation || {};
    const comfyState = generation.stage || generation.state || (comfy.reachable ? "ready" : "offline");
    const comfyMessage = generation.message || (comfy.reachable ? "ComfyUI is reachable" : (comfy.error || "ComfyUI is unavailable"));
    const comfyMeta = `queue: ${generation.queue_running || 0} running · ${generation.queue_pending || 0} waiting${generation.elapsed ? ` · ${generation.elapsed}s` : ""}`;
    renderLiveCard(comfyBox, "ComfyUI", comfyState, comfyMessage, comfyMeta,
      liveStateClass(comfyState, comfy.reachable, generation.error || comfy.error));

    const updated = $("#diag-live-updated");
    if (updated) updated.textContent = new Date().toLocaleTimeString();
  } catch (error) {
    renderLiveCard(lmBox, "LM Studio", "status unavailable", error.message, "", "live-error");
    renderLiveCard(comfyBox, "ComfyUI", "status unavailable", error.message, "", "live-error");
  }
}

let _diagRuntimeTimer = null;
function startDiagnosticRuntimePolling() {
  if (_diagRuntimeTimer) return;
  refreshDiagnosticRuntime();
  _diagRuntimeTimer = setInterval(refreshDiagnosticRuntime, 1000);
}

// Boutons
 document.addEventListener("DOMContentLoaded", () => {
  const runBtn  = $("#diag-run-btn");
  const copyBtn = $("#diag-copy-btn");
  const familySel = $("#diag-image-family");
  if (runBtn) runBtn.addEventListener("click", () => loadDiagnostic());
  if (familySel) {
    api("/api/settings").then(settings => {
      familySel.value = settings.image_family === "krea2" ? "krea2" : "flux2_klein";
    }).catch(() => {});
    familySel.addEventListener("change", () => loadDiagnostic());
  }
  startDiagnosticRuntimePolling();
  if (copyBtn) copyBtn.addEventListener("click", () => {
    const text = buildDiagText(_diagReport);
    navigator.clipboard.writeText(text)
      .then(() => toast(window.t("diagnostic.report_copied_clipboard")))
      .catch(() => {
        // Fallback pour les navigateurs sans clipboard API
        const textarea = document.createElement("textarea");
        textarea.value = text;
        document.body.append(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
        toast(window.t("diagnostic.report_copied"));
      });
  });
});

// Une langue peut être changée après l'exécution du diagnostic. Re-rendre le
// rapport à partir des clés reçues évite toute relance réseau et traduit aussi
// le contenu dynamique (résumé, checks, détails et rapport copiable).
document.addEventListener("amiorai:lang-changed", () => {
  setDiagRunButton(_diagLoading);
  if (_diagReport) renderDiagnostic(_diagReport);
});

// --------------------------------------------------------------------------- //
//  Démarrage — isolation par module (une error n'en bloque pas d'autres)
// --------------------------------------------------------------------------- //

// Bandeau non-blocking pour les errors d'initialisation
const _initWarnings = [];
function showInitWarning(name, err) {
  _initWarnings.push({ name, err });
  const bar = document.getElementById("init-warning-bar");
  if (!bar) return;
  bar.style.display = "block";
  const list = bar.querySelector("#init-warning-list");
  if (list) {
    const item = el("div", { class: "init-warn-item" },
      el("span", {}, `${name} : ${err && err.message ? err.message : String(err)}`),
      el("button", { class: "btn sm ghost", onclick: () => {
        item.remove();
        if (!list.children.length) bar.style.display = "none";
      } }, "✕")
    );
    list.append(item);
  }
}

async function safeInit(name, fn) {
  try {
    await fn();
  } catch (err) {
    console.error(`[Init] ${name} failed`, err);
    showInitWarning(name, err);
  }
}

(async () => {
  // Réglages globaux en premier (bloquant, tout le reste en dépend)
  try {
    const s = await api("/api/settings");
    personaImage = s.persona_image || "";
    whisperEnabled = String(s.whisper_enabled) === "true";
    ttsEnabled = String(s.tts_enabled) === "true";
    ttsAutoplay = String(s.tts_autoplay) !== "false";
    currentMaxTokens = parseInt(s.llm_max_tokens, 10) || 250;
    globalImageFamily = ["flux2_klein", "krea2"].includes(s.image_family) ? s.image_family : "flux2_klein";
    syncGlobalImageSelectors(globalImageFamily);
    // Applique la langue sauvegardée côté backend (priorité sur localStorage)
    if (s.ui_language && window.I18n) {
      await window.I18n.setLanguage(s.ui_language, false); // false = ne pas re-POST
    }
  } catch (e) {
    console.error("[Init] /api/settings inaccessible", e);
  }
  // Applique les traductions au DOM une fois les locales chargées
  if (window.I18n) {
    window.I18n.applyToDOM();
    _i18nInitLangPicker();
    _i18nInitDevTools();
  }

  // Modules indépendants — tolérants aux pannes
  await safeInit("characters",  () => loadCharacters());
  await safeInit("options",      () => loadOptionPreviews());
  await safeInit("scenarios",    () => loadScenarios());

  startLLMPolling(false); // permanent slow polling, speeds up as soon as there is activity
})();

// ── i18n — Sélecteur de langue ─────────────────────────────────────────────
function _i18nInitLangPicker() {
  const picker = document.getElementById("lang-picker");
  const quickPicker = document.getElementById("quick-lang-picker");
  if (!picker && !quickPicker) return;

  function _updateActive(lang) {
    picker?.querySelectorAll(".lang-btn[data-lang]").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.lang === lang);
    });
    if (quickPicker) quickPicker.value = lang;
  }

  _updateActive(window.I18n ? window.I18n.getActiveLang() : "en");

  picker?.addEventListener("click", async e => {
    const btn = e.target.closest(".lang-btn[data-lang]");
    if (!btn || !window.I18n) return;
    await window.I18n.setLanguage(btn.dataset.lang, true);
    _updateActive(btn.dataset.lang);
  });

  quickPicker?.addEventListener("change", async () => {
    if (!window.I18n) return;
    await window.I18n.setLanguage(quickPicker.value, true);
    _updateActive(window.I18n.getActiveLang());
  });

  document.addEventListener("amiorai:lang-changed", e => {
    _updateActive(e.detail?.lang || (window.I18n ? window.I18n.getActiveLang() : "en"));
  });
}

// ── i18n — Developer tools (panel Traductions) ─────────────────────────
function _i18nInitDevTools() {
  const toggle = document.getElementById("dev-tools-toggle");
  const panel  = document.getElementById("dev-tools-panel");
  if (!toggle || !panel) return;

  const stored = localStorage.getItem("amiorai-dev-tools") === "1";
  toggle.checked = stored;
  panel.style.display = stored ? "" : "none";

  toggle.addEventListener("change", () => {
    panel.style.display = toggle.checked ? "" : "none";
    localStorage.setItem("amiorai-dev-tools", toggle.checked ? "1" : "0");
    if (toggle.checked) _devLoadStats();
  });
  if (stored) _devLoadStats();

  // ── Affichage d'une error structurée ──
  function _devToastResult(d, okMsg) {
    if (d.ok) {
      toast(typeof okMsg === "string" ? okMsg : t(okMsg));
    } else {
      const cause = d.message || d.error || "Unknown error";
      const code  = d.error_code ? `[${d.error_code}] ` : "";
      const detail = d.details ? `\n${d.details.slice(0, 200)}` : "";
      toast(`${code}${cause}${detail}`, true);
    }
  }

  function _devShowAnalysis(d) {
    const box = document.getElementById("dev-analysis-result");
    const pre = document.getElementById("dev-analysis-content");
    if (!box || !pre) return;
    box.style.display = "";
    let txt = d.message || "";
    if (d.details)   txt += "\n\n" + d.details;
    if (d.warnings?.length) txt += "\n\nWarnings:\n" + d.warnings.join("\n");
    if (d.generated?.length) txt += "\n\nGenerated:\n" + d.generated.join("\n");
    pre.textContent = txt;
  }

  // Export — GET (téléchargement direct)
  document.getElementById("dev-export-xlsx")?.addEventListener("click", () => {
    window.location.href = "/api/i18n/export";
  });

  // Import — vrai FormData multipart vers /api/i18n/import-file
  const importBtn   = document.getElementById("dev-import-xlsx-btn");
  const importInput = document.getElementById("dev-import-xlsx-input");
  importBtn?.addEventListener("click", () => importInput?.click());
  importInput?.addEventListener("change", async () => {
    const file = importInput.files[0];
    if (!file) return;
    if (!file.name.endsWith(".xlsx")) {
      toast(window.t("dev.xlsx_required"), true);
      importInput.value = "";
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/i18n/import-file", { method: "POST", body: fd });
      const d = await r.json().catch(() => ({ ok: false, message: `HTTP ${r.status}` }));
      _devToastResult(d, "dev.toasts.import_ok");
      _devShowAnalysis(d);
      _devLoadStats();
      if (d.ok && window.I18n) {
        await window.I18n.setLanguage(window.I18n.getActiveLang(), false);
      }
    } catch (e) { toast(`Import impossible : ${e.message}`, true); }
    importInput.value = "";
  });

  // Analyser (dry-run) — retourne la structure JSON lisible
  document.getElementById("dev-analyze-btn")?.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/i18n/analyze", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dry_run: true }) });
      const d = await r.json().catch(() => ({ ok: false, message: `HTTP ${r.status}` }));
      _devShowAnalysis(d);
      toast(d.ok ? t("dev.toasts.analyze_done") : (d.message || "Analysis failed"), !d.ok);
    } catch (e) { toast(`Analysis impossible : ${e.message}`, true); }
  });

  // Actualiser les JSON depuis le maître actuel
  document.getElementById("dev-refresh-btn")?.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/i18n/generate", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}) });
      const d = await r.json().catch(() => ({ ok: false, message: `HTTP ${r.status}` }));
      _devToastResult(d, "dev.toasts.refresh_ok");
      _devShowAnalysis(d);
      _devLoadStats();
      if (d.ok && window.I18n) await window.I18n.setLanguage(window.I18n.getActiveLang(), false);
    } catch (e) { toast(`Generation impossible : ${e.message}`, true); }
  });

  // Recharger les traductions (cache backend + reload frontend)
  document.getElementById("dev-reload-btn")?.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/i18n/reload", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const d = await r.json().catch(() => ({ ok: false, message: `HTTP ${r.status}` }));
      _devToastResult(d, "dev.toasts.reload_ok");
      if (window.I18n) await window.I18n.setLanguage(window.I18n.getActiveLang(), false);
    } catch (e) { toast(`Reload impossible : ${e.message}`, true); }
  });

  // Restaurer la dernière sauvegarde
  document.getElementById("dev-restore-btn")?.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/i18n/restore-last-backup", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const d = await r.json().catch(() => ({ ok: false, message: `HTTP ${r.status}` }));
      _devToastResult(d, "dev.toasts.restore_ok");
      if (d.ok && window.I18n) await window.I18n.setLanguage(window.I18n.getActiveLang(), false);
      _devLoadStats();
    } catch (e) { toast(`Restauration impossible : ${e.message}`, true); }
  });
}

async function _devLoadStats() {
  const el = document.getElementById("dev-stats");
  if (!el) return;
  el.textContent = t("dev.stats_loading");
  try {
    const r = await fetch("/api/i18n/stats", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    const d = await r.json().catch(() => ({}));
    const parts = [];
    parts.push(t("dev.stats_keys", { n: d.total_keys_en || 0 }));
    const complete = Object.values(d.langs || {}).filter(l => l.exists && l.missing === 0).length;
    parts.push(t("dev.stats_langs", { n: complete }));
    const totalMissing = Object.values(d.langs || {}).reduce((s, l) => s + (l.missing || 0), 0);
    if (totalMissing > 0) parts.push(t("dev.stats_missing", { n: totalMissing }));
    el.textContent = parts.join(" · ");
  } catch (_) { el.textContent = ""; }
}
