/* Analytics Ackee (https://ackee.electerious.com) — chargé uniquement si le
   serveur est configuré (ACKEE_URL + ACKEE_DOMAIN_ID, exposés via /api/config).
   Le traqueur respecte par défaut "Do Not Track" côté visiteur. */
(async function () {
  try {
    const cfg = await (await fetch("/api/config")).json();
    if (!cfg.ackee_url || !cfg.ackee_domain_id) return;
    const s = document.createElement("script");
    s.async = true;
    s.src = cfg.ackee_url + "/tracker.js";
    s.setAttribute("data-ackee-server", cfg.ackee_url);
    s.setAttribute("data-ackee-domain-id", cfg.ackee_domain_id);
    // Mode non détaillé : pas de collecte d'attributs personnels
    // (taille d'écran, langue, etc.). Passer à "true" si souhaité.
    s.setAttribute("data-ackee-opts", '{"detailed": false}');
    document.head.appendChild(s);
  } catch (e) {
    /* L'analytics ne doit jamais casser la page. */
  }
})();
