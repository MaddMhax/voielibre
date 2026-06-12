/* Gestion du thème clair/sombre, partagée entre les pages.
   Le réglage initial est posé en <head> (inline) pour éviter tout clignotement ;
   ce fichier ne gère que le bouton de bascule. */
(function () {
  function current() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  function updateIcon() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    const dark = current() === "dark";
    // En sombre on propose de passer en clair (soleil), et inversement.
    btn.textContent = dark ? "☀️" : "🌙";
    btn.setAttribute(
      "aria-label",
      dark ? "Passer en thème clair" : "Passer en thème sombre"
    );
    btn.title = btn.getAttribute("aria-label");
  }

  function toggleTheme() {
    const next = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    updateIcon();
  }

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    // Listener plutôt qu'attribut onclick : compatible CSP `script-src 'self'`.
    if (btn) btn.addEventListener("click", toggleTheme);
    updateIcon();
  });
})();
