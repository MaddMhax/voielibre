/* Pose le thème avant le rendu pour éviter le clignotement.
   Chargé en <head> sans defer : bloquant volontairement, comme l'ancien
   script inline (externalisé pour respecter la CSP `script-src 'self'`). */
(function () {
  try {
    var saved = localStorage.getItem("theme");
    var theme = saved ||
      (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
