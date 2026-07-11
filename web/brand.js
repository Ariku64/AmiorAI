/* Copyright 2026 Ariku
 * SPDX-License-Identifier: Apache-2.0
 */
"use strict";
// ===========================================================================
//  Configuration de marque centralisee.
//  Pour renommer l'application affichee a l'utilisateur, change UNIQUEMENT
//  les valeurs ci-dessous. Le reste du code (JS, HTML, CSS) lit ces
//  constantes et ne contient jamais le nom en dur.
// ===========================================================================
const APP_BRAND = {
  name: "AmiorAI",
  tagline: "Ton compagnon IA",
  // Court suffixe utilise dans le titre d'onglet / fenetre, ex: "AmiorAI — Chat"
  windowTitleSuffix: "",
};

// Applique le nom partout ou un data-brand-name est present dans le DOM statique,
// et met a jour le titre de la page / fenetre.
document.addEventListener("DOMContentLoaded", () => {
  document.title = APP_BRAND.windowTitleSuffix
    ? `${APP_BRAND.name} — ${APP_BRAND.windowTitleSuffix}`
    : APP_BRAND.name;
  for (const node of document.querySelectorAll("[data-brand-name]")) {
    node.textContent = APP_BRAND.name;
  }
  for (const node of document.querySelectorAll("[data-brand-tagline]")) {
    node.textContent = APP_BRAND.tagline;
  }
});
