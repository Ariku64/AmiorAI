/* Copyright 2026 Ariku
 * SPDX-License-Identifier: Apache-2.0
 */
/**
 * AmiorAI Icon System v37.5
 * SVG icons avec dégradé cyan → bleu → violet.
 * Usage : amIcon("characters", 20)  → HTMLElement <svg>
 * Le dégradé #ai-grad est défini une fois dans index.html (hidden defs SVG).
 */



/* Icon assets supplied with the project and prepared for the v39 navigation.
   They remain raster images because they are original visual assets, while the
   SVG set below stays available as a lightweight fallback everywhere else. */
const AMIORAI_NAV_ASSETS = Object.freeze({
  characters: "/assets/icons/brand-mark.png", // AmiorAI logo mark
  chats:      "/assets/icons/chats.png",
  scenarios:  "/assets/icons/scenarios.png",
  journal:    "/assets/icons/journal.png",
  gallery:    "/assets/icons/gallery.png",
  studio:     "/assets/icons/studio.png",
  library:    "/assets/icons/library.png",
  models:     "/assets/icons/models.png",
  loras:      "/assets/icons/loras.png",
  system:     "/assets/icons/system.png",
  settings:   "/assets/icons/settings.png",
  diagnostic: "/assets/icons/diagnostic.png",
});

const AMIORAI_ICONS = {

  /* ── Navigation ─────────────────────────────────────────────────────── */

  characters: `
    <path d="M3.2 20V8.8c0-2.2 2.7-3.1 4.1-1.4L12 13l4.7-5.6c1.4-1.7 4.1-.8 4.1 1.4V20h-3.2V11.7L12 18.1l-5.6-6.4V20z"/>
    <circle cx="9.4" cy="17.2" r=".75" fill="white" opacity=".82"/>
    <circle cx="14.6" cy="17.2" r=".75" fill="white" opacity=".82"/>
    <path d="M10.1 19.3c1.25.9 2.55.9 3.8 0" fill="none" stroke="white" stroke-width="1.1" stroke-linecap="round" opacity=".8"/>
    <path d="M12 1.2l.65 1.8 1.85.65-1.85.65L12 6.1l-.65-1.8-1.85-.65 1.85-.65z"/>
    <circle cx="7.4" cy="3.4" r=".65"/><circle cx="16.6" cy="3.4" r=".65"/>`,

  chats: `
    <path d="M20 3H4C2.9 3 2 3.9 2 5v10c0 1.1.9 2 2 2h4.5l5.5 4 5.5-4H20c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>
    <circle cx="8.5" cy="10" r="1.3"/>
    <circle cx="12" cy="10" r="1.3"/>
    <circle cx="15.5" cy="10" r="1.3"/>`,

  scenarios: `
    <rect x="9" y="1.5" width="6" height="5" rx="1.5"/>
    <path d="M11.5 6.5v3M8.5 9.5H15.5"/>
    <rect x="2" y="9.5" width="6" height="4.5" rx="1.5"/>
    <rect x="16" y="9.5" width="6" height="4.5" rx="1.5"/>
    <circle cx="12" cy="3.8" r="1" fill="white" opacity=".7"/>`,

  journal: `
    <path d="M9 3.5C9 2.7 9.7 2 10.5 2h8C19.3 2 20 2.7 20 3.5v17L15.5 18 11 20.5V3.5z"/>
    <path d="M9 4H5C3.9 4 3 4.9 3 6v14l4-2"/>
    <line x1="12.5" y1="7" x2="17.5" y2="7" stroke="white" stroke-width="1.2" stroke-linecap="round" opacity=".6"/>
    <line x1="12.5" y1="10" x2="17.5" y2="10" stroke="white" stroke-width="1.2" stroke-linecap="round" opacity=".6"/>
    <line x1="12.5" y1="13" x2="16" y2="13" stroke="white" stroke-width="1.2" stroke-linecap="round" opacity=".6"/>`,

  memory: `
    <path d="M12 4C9 4 7 6 7 9c0 1.5.6 2.8 1.5 3.7L12 21l3.5-8.3A5 5 0 0 0 17 9c0-3-2-5-5-5z"/>
    <circle cx="9.5" cy="8.5" r="1" fill="white" opacity=".7"/>
    <circle cx="12.5" cy="7" r="1" fill="white" opacity=".7"/>
    <circle cx="12.5" cy="10.5" r="1" fill="white" opacity=".7"/>
    <path d="M9.5 8.5L12.5 7M12.5 7l-3 3.5" stroke="white" stroke-width=".8" opacity=".5"/>`,

  gallery: `
    <rect x="2" y="3" width="20" height="17" rx="2.5"/>
    <path d="M2 14l5-5.5 5 5.5 3.5-4 4.5 4" fill="white" opacity=".25" stroke="none"/>
    <path d="M2 14l5-5.5 5 5.5 3.5-4 4.5 4" fill="none" stroke="white" stroke-width="1.3" stroke-linejoin="round" opacity=".7"/>
    <circle cx="7.5" cy="8.5" r="1.8" fill="white" opacity=".6"/>`,

  studio: `
    <rect x="9.5" y="4" width="3" height="14" rx="1.5" transform="rotate(-45 12 12)"/>
    <path d="M16 4.5l.5 1.5 1.5.5-1.5.5-.5 1.5-.5-1.5-1.5-.5 1.5-.5z"/>
    <path d="M19.5 8l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z"/>
    <path d="M7.5 15.5l.3.9.9.3-.9.3-.3.9-.3-.9-.9-.3.9-.3z"/>`,

  library: `
    <rect x="2.5" y="4" width="5" height="16" rx="1.2"/>
    <rect x="9.5" y="6" width="5" height="14" rx="1.2"/>
    <rect x="16.5" y="2" width="5" height="18" rx="1.2"/>
    <line x1="2" y1="21" x2="22" y2="21" stroke-linecap="round" stroke-width="1.5" stroke="white" opacity=".4"/>`,

  models: `
    <rect x="7" y="7" width="10" height="10" rx="2.5"/>
    <text x="12" y="15" font-size="6" font-weight="700" text-anchor="middle" fill="white" font-family="system-ui" opacity=".85">AI</text>
    <circle cx="12" cy="2" r="1.3"/><line x1="12" y1="3.3" x2="12" y2="7"/>
    <circle cx="22" cy="12" r="1.3"/><line x1="17" y1="12" x2="20.7" y2="12"/>
    <circle cx="12" cy="22" r="1.3"/><line x1="12" y1="17" x2="12" y2="20.7"/>
    <circle cx="2" cy="12" r="1.3"/><line x1="3.3" y1="12" x2="7" y2="12"/>`,

  loras: `
    <path d="M12 3.5L20 8v.5L12 13 4 8.5V8z"/>
    <path d="M4 11.5L12 16l8-4.5"/>
    <path d="M4 15L12 19.5 20 15"/>
    <path d="M11 5.5l.5 1.3 1.4.5-1.4.5L11 9.3l-.5-1.5-1.4-.5 1.4-.5z" fill="white" opacity=".7"/>`,

  system: `
    <rect x="4" y="2" width="16" height="8" rx="2"/>
    <rect x="4" y="12" width="16" height="8" rx="2"/>
    <circle cx="8" cy="6" r="1.2" fill="white" opacity=".7"/>
    <rect x="11" y="5" width="6" height="2" rx="1" fill="white" opacity=".4"/>
    <circle cx="8" cy="16" r="1.2" fill="white" opacity=".7"/>
    <rect x="11" y="15" width="4" height="2" rx="1" fill="white" opacity=".4"/>
    <line x1="12" y1="20" x2="12" y2="23" stroke-width="1.5"/>
    <line x1="8" y1="23" x2="16" y2="23" stroke-width="2" stroke-linecap="round"/>`,

  settings: `
    <path d="M12 1.5A2 2 0 0 1 14 3.4l.1.5a7.5 7.5 0 0 1 1.5.87l.5-.18a2 2 0 0 1 2.53 1l1 1.73a2 2 0 0 1-.47 2.55l-.4.32a7.6 7.6 0 0 1 0 1.74l.4.32a2 2 0 0 1 .47 2.55l-1 1.73a2 2 0 0 1-2.53 1l-.5-.18c-.46.34-.97.63-1.5.87l-.1.5a2 2 0 0 1-4 0l-.1-.5a7.5 7.5 0 0 1-1.5-.87l-.5.18a2 2 0 0 1-2.53-1l-1-1.73a2 2 0 0 1 .47-2.55l.4-.32a7.6 7.6 0 0 1 0-1.74l-.4-.32A2 2 0 0 1 3.87 7.4l1-1.73a2 2 0 0 1 2.53-1l.5.18c.46-.34.97-.63 1.5-.87l.1-.5A2 2 0 0 1 12 1.5z"/>
    <circle cx="12" cy="12" r="3" fill="white" opacity=".3"/>
    <line x1="8" y1="12" x2="10" y2="12" stroke="white" stroke-width="1.3" opacity=".6"/>
    <line x1="14" y1="12" x2="16" y2="12" stroke="white" stroke-width="1.3" opacity=".6"/>`,

  diagnostic: `
    <circle cx="12" cy="12" r="9.5"/>
    <path d="M4.5 12h2.8L9 8.5l2.5 7 2-4 1.5 2.5H19.5" fill="none" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>
    <circle cx="19.5" cy="12" r="1.2" fill="white" opacity=".7"/>`,

  /* ── Actions ─────────────────────────────────────────────────────────── */

  add: `
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="7" x2="12" y2="17" stroke="white" stroke-width="2" stroke-linecap="round"/>
    <line x1="7" y1="12" x2="17" y2="12" stroke="white" stroke-width="2" stroke-linecap="round"/>`,

  edit: `
    <path d="M17 3.5a2.12 2.12 0 0 1 3 3L7.5 20 3 21l1-4.5z"/>
    <line x1="3" y1="21" x2="10" y2="21" stroke-width="1.5" stroke-linecap="round" opacity=".4"/>`,

  delete: `
    <polyline points="3 6 5 6 21 6" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
    <path d="M9 6V4h6v2"/>
    <line x1="10" y1="11" x2="10" y2="17" stroke-linecap="round"/>
    <line x1="14" y1="11" x2="14" y2="17" stroke-linecap="round"/>`,

  generate: `
    <rect x="9.5" y="4" width="3" height="14" rx="1.5" transform="rotate(-45 12 12)"/>
    <path d="M17 3l.6 1.8 1.9.6-1.9.6L17 8l-.6-1.8-1.9-.6 1.9-.6z"/>
    <path d="M20 9l.4 1.2 1.2.4-1.2.4L20 12.2l-.4-1.2-1.2-.4 1.2-.4z"/>`,

  regenerate: `
    <path d="M20 12a8 8 0 1 1-2.34-5.66"/>
    <polyline points="16 3 20.66 6.34 20 12"/>
    <line x1="12" y1="9" x2="12" y2="15" stroke-linecap="round"/>
    <line x1="9" y1="12" x2="15" y2="12" stroke-linecap="round"/>`,

  save: `
    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
    <polyline points="17 21 17 13 7 13 7 21"/>
    <polyline points="7 3 7 8 15 8"/>`,

  tts: `
    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19"/>
    <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
    <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>`,

  mic: `
    <rect x="9" y="2" width="6" height="12" rx="3"/>
    <path d="M5 11a7 7 0 0 0 14 0"/>
    <line x1="12" y1="18" x2="12" y2="22" stroke-linecap="round"/>
    <line x1="8" y1="22" x2="16" y2="22" stroke-linecap="round"/>`,

  image_icon: `
    <rect x="2.5" y="3" width="19" height="16" rx="2.5"/>
    <path d="M2.5 13l5-5.5 5 5.5 3.5-4 5.5 5" fill="none" stroke-width="1.4" stroke-linejoin="round"/>
    <circle cx="7.5" cy="8" r="1.8" fill="white" opacity=".6"/>`,

  lock: `
    <rect x="3" y="11" width="18" height="12" rx="2"/>
    <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
    <circle cx="12" cy="16.5" r="1.5" fill="white" opacity=".6"/>`,

  network: `
    <rect x="9" y="1.5" width="6" height="5" rx="1.5"/>
    <rect x="1" y="17.5" width="6" height="5" rx="1.5"/>
    <rect x="17" y="17.5" width="6" height="5" rx="1.5"/>
    <line x1="4" y1="17.5" x2="12" y2="6.5"/>
    <line x1="20" y1="17.5" x2="12" y2="6.5"/>
    <line x1="4" y1="17.5" x2="20" y2="17.5"/>`,

  mobile_icon: `
    <rect x="6.5" y="1.5" width="11" height="21" rx="2.5"/>
    <line x1="10" y1="5.5" x2="14" y2="5.5" stroke="white" stroke-width="1.5" stroke-linecap="round" opacity=".5"/>
    <circle cx="12" cy="19" r="1.3" fill="white" opacity=".5"/>`,

  server: `
    <rect x="2" y="2" width="20" height="5.5" rx="1.5"/>
    <rect x="2" y="9.5" width="20" height="5.5" rx="1.5"/>
    <rect x="2" y="17" width="20" height="5" rx="1.5"/>
    <circle cx="6.5" cy="4.8" r="1.2" fill="white" opacity=".7"/>
    <circle cx="6.5" cy="12.3" r="1.2" fill="white" opacity=".7"/>
    <rect x="10" y="4" width="6" height="1.5" rx=".75" fill="white" opacity=".4"/>
    <rect x="10" y="11.5" width="4" height="1.5" rx=".75" fill="white" opacity=".4"/>`,

  health: `
    <path d="M12 21.5C12 21.5 3 15.5 3 9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6.5-9 12.5-9 12.5z"/>
    <path d="M7 10h2.5l1.5-2.5 2 5 1.5-2.5H17" fill="none" stroke="white" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity=".8"/>`,

  /* Actions utilitaires */
  refresh: `
    <path d="M23 4v6h-6"/>
    <path d="M1 20v-6h6"/>
    <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10"/>
    <path d="M3.51 15a9 9 0 0 0 14.85 3.36L23 14"/>`,

  close: `
    <line x1="18" y1="6" x2="6" y2="18" stroke-linecap="round"/>
    <line x1="6" y1="6" x2="18" y2="18" stroke-linecap="round"/>`,

  check: `
    <polyline points="20 6 9 17 4 12" stroke-linecap="round" stroke-linejoin="round"/>`,

  copy: `
    <rect x="9" y="9" width="13" height="13" rx="2"/>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>`,

  scan: `
    <rect x="3" y="3" width="18" height="18" rx="2"/>
    <path d="M3 9h18M9 3v18" stroke-linecap="round"/>`,

  info: `
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="8" x2="12" y2="12" stroke-linecap="round" stroke-width="2"/>
    <line x1="12" y1="16" x2="12.01" y2="16" stroke-linecap="round" stroke-width="2"/>`,

  link: `
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>`,

  star: `
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"/>`,

  play: `
    <circle cx="12" cy="12" r="10"/>
    <polygon points="10 8 17 12 10 16" fill="white" opacity=".8"/>`,

  wand: `
    <rect x="9.5" y="4" width="3" height="14" rx="1.5" transform="rotate(-45 12 12)"/>
    <path d="M16 4l.6 1.8 1.9.6-1.9.6L16 8.8l-.6-1.8-1.9-.6 1.9-.6z"/>
    <path d="M20 9.5l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z"/>`,
};

/**
 * Crée un élément SVG à partir du nom d'icône.
 * @param {string} name - Clé dans AMIORAI_ICONS
 * @param {number} size - Taille en px (défaut: 20)
 * @param {string} extraClass - Classes CSS supplémentaires sur le wrapper
 * @returns {HTMLElement} span.ai-ic contenant l'<svg>
 */
function amIcon(name, size = 20, extraClass = "") {
  const paths = AMIORAI_ICONS[name];
  const wrapper = document.createElement("span");
  wrapper.className = "ai-ic" + (extraClass ? " " + extraClass : "");

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  const gradId = "ai-grad-" + Math.random().toString(36).slice(2, 10);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("fill", `url(#${gradId})`);
  svg.setAttribute("stroke", `url(#${gradId})`);
  svg.setAttribute("stroke-width", "0");
  svg.setAttribute("xmlns", svgNS);

  const defs = document.createElementNS(svgNS, "defs");
  const gradient = document.createElementNS(svgNS, "linearGradient");
  gradient.setAttribute("id", gradId);
  gradient.setAttribute("x1", "0%");
  gradient.setAttribute("y1", "0%");
  gradient.setAttribute("x2", "100%");
  gradient.setAttribute("y2", "100%");
  for (const [offset, color] of [["0%", "#00d4ff"], ["55%", "#3b82f6"], ["100%", "#7c3aed"]]) {
    const stop = document.createElementNS(svgNS, "stop");
    stop.setAttribute("offset", offset);
    stop.setAttribute("stop-color", color);
    gradient.appendChild(stop);
  }
  defs.appendChild(gradient);
  svg.appendChild(defs);

  if (paths) {
    const group = document.createElementNS(svgNS, "g");
    group.innerHTML = paths;
    svg.appendChild(group);
  } else {
    svg.innerHTML += `<rect x="3" y="3" width="18" height="18" rx="3" opacity=".4"/>`;
  }
  wrapper.append(svg);
  return wrapper;
}

/**
 * Remplace le contenu d'un span.ic dans la navigation par un amIcon SVG.
 * @param {string} selector - Sélecteur CSS du span.ic
 * @param {string} iconName - Nom de l'icône
 */
function _navIcon(selector, iconName) {
  const el = document.querySelector(selector);
  if (!el) return;
  const icon = amIcon(iconName, 20);
  icon.className = "ic ai-ic";
  el.replaceWith(icon);
}


/**
 * Mount all declarative menu icons. This is intentionally owned by icons.js so
 * the navigation remains visible even when another application module fails
 * during startup. The operation is idempotent and also supports late DOM nodes.
 */
function mountAmiorIcons(root = document) {
  root.querySelectorAll?.(".ic[data-icon]:not([data-icon-mounted='1'])").forEach((placeholder) => {
    const name = placeholder.dataset.icon;
    const size = Number(placeholder.dataset.iconSize || 20);
    const icon = amIcon(name, size);
    icon.className = placeholder.className.includes("m-nav") ? placeholder.className + " ai-ic" : "ic ai-ic";
    icon.dataset.icon = name;
    icon.dataset.iconMounted = "1";
    placeholder.replaceWith(icon);
  });
}

function initAmiorIconSystem() {
  mountAmiorIcons(document);
  if (!window.__amiorIconObserver) {
    window.__amiorIconObserver = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches?.(".ic[data-icon]")) mountAmiorIcons(node.parentElement || document);
          else if (node.querySelector?.(".ic[data-icon]")) mountAmiorIcons(node);
        }
      }
    });
    window.__amiorIconObserver.observe(document.documentElement, { childList: true, subtree: true });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAmiorIconSystem, { once: true });
} else {
  initAmiorIconSystem();
}
