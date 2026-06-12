/* Administration : connexion, recherche de gares, gestion des lignes. */
const PERIOD_LABEL = { both: "Matin et soir", morning: "Matin", evening: "Soir" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const LOGIN_ERRORS = {
  "1": "Identifiant ou mot de passe incorrect.",
  lock: "Trop de tentatives : connexion bloquée 15 minutes.",
  disabled: "Administration désactivée : définissez ADMIN_PASSWORD côté serveur.",
};

function showLogin() {
  document.getElementById("login-panel").classList.remove("hidden");
  const code = new URLSearchParams(location.search).get("error");
  if (code) {
    const box = document.getElementById("login-error");
    box.textContent = LOGIN_ERRORS[code] || LOGIN_ERRORS["1"];
    box.classList.remove("hidden");
  }
}

// Gares sélectionnées pour le trajet en cours de création.
const picked = { from: null, to: null };

async function init() {
  const me = await (await fetch("/api/me")).json();
  if (!me.admin) { showLogin(); return; }
  document.getElementById("admin-panel").classList.remove("hidden");
  loadLines();
  loadQuota();
  makePicker("from");
  makePicker("to");
  setupAddForm();
  setupBackup();
}

// --- Quota API (compteur local — l'API SNCF n'expose pas le sien) ---
async function loadQuota() {
  const box = document.getElementById("quota");
  try {
    const q = await (await fetch("/api/admin/quota")).json();
    const dayPct = Math.min(100, (q.day_used / q.day_limit) * 100);
    const monthPct = Math.min(100, (q.used / q.limit) * 100);
    const dayWarn = dayPct >= 80;
    const monthWarn = monthPct >= 80;
    const exceeded = q.day_used >= q.day_limit
      ? `<div class="notice">🚫 Quota journalier dépassé : l'accès à l'API SNCF est
         suspendu jusqu'à demain, les horaires peuvent être erronés.</div>`
      : "";
    box.innerHTML =
      `${exceeded}
       <div class="quota-line">
         <strong>${q.day_used.toLocaleString("fr-FR")}</strong>
         <span class="card-sub">/ ${q.day_limit.toLocaleString("fr-FR")} requêtes aujourd'hui</span>
         <span class="quota-remaining${dayWarn ? " warn" : ""}">
           ${q.day_remaining.toLocaleString("fr-FR")} restantes
         </span>
       </div>
       <div class="quota-bar"><div class="quota-fill day${dayWarn ? " warn" : ""}"></div></div>
       <div class="quota-line quota-month">
         <strong>${q.used.toLocaleString("fr-FR")}</strong>
         <span class="card-sub">/ ${q.limit.toLocaleString("fr-FR")} requêtes en ${esc(q.month)}</span>
         <span class="quota-remaining${monthWarn ? " warn" : ""}">
           ${q.remaining.toLocaleString("fr-FR")} restantes
         </span>
       </div>
       <div class="quota-bar"><div class="quota-fill month${monthWarn ? " warn" : ""}"></div></div>
       <div class="card-sub quota-note">Estimation locale : l'API SNCF ne publie pas
       son compteur, chaque requête sortante est donc comptée ici. Le flux des
       voies (SIRI, open data) est gratuit et non compté.</div>`;
    // Largeurs posées via CSSOM : un attribut style inline serait bloqué par la CSP.
    box.querySelector(".quota-fill.day").style.width = dayPct.toFixed(1) + "%";
    box.querySelector(".quota-fill.month").style.width = monthPct.toFixed(1) + "%";
  } catch (e) {
    box.innerHTML = `<div class="card-sub">Quota indisponible.</div>`;
  }
}

// --- Sélecteur de gare réutilisable (départ ou arrivée) ---
function makePicker(role) {
  const input = document.getElementById("search-" + role);
  const results = document.getElementById("results-" + role);
  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { results.innerHTML = ""; return; }
    timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/admin/search?q=" + encodeURIComponent(q));
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          results.innerHTML = `<div class="notice">${esc(err.detail || "Erreur de recherche.")}</div>`;
          return;
        }
        const stations = await res.json();
        results.innerHTML = stations.map((s) =>
          `<div class="search-item">
             <span>${esc(s.name)}</span>
             <button type="button" class="ghost"
               data-id="${esc(s.id)}" data-name="${esc(s.name)}">Choisir</button>
           </div>`).join("") || `<div class="card-sub">Aucune gare trouvée.</div>`;
        results.querySelectorAll("button[data-id]").forEach((b) => {
          b.addEventListener("click", () =>
            selectStation(role, b.dataset.id, b.dataset.name));
        });
      } catch (e) {
        results.innerHTML = `<div class="notice">Erreur réseau.</div>`;
      }
    }, 300);
  });
}

function selectStation(role, id, name) {
  picked[role] = { id, name };
  document.getElementById("results-" + role).innerHTML = "";
  document.getElementById("search-" + role).value = name;
  document.getElementById("chosen-" + role).innerHTML =
    `<div class="search-item"><span>✓ ${esc(name)}</span></div>`;
  refreshAddForm();
}

// Affiche le formulaire final quand départ ET arrivée sont choisis.
function refreshAddForm() {
  const form = document.getElementById("add-form");
  if (picked.from && picked.to) {
    form.classList.remove("hidden");
    const label = document.getElementById("label");
    // Pré-remplit un libellé si l'utilisateur ne l'a pas déjà personnalisé.
    if (!label.dataset.touched) {
      label.value = `${picked.from.name} → ${picked.to.name}`;
    }
  } else {
    form.classList.add("hidden");
  }
}

// --- Ajout ---
function setupAddForm() {
  const label = document.getElementById("label");
  label.addEventListener("input", () => { label.dataset.touched = "1"; });

  document.getElementById("add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!picked.from || !picked.to) return;
    const form = e.target;
    const body = new URLSearchParams({
      label: form.label.value,
      from_id: picked.from.id,
      from_name: picked.from.name,
      to_id: picked.to.id,
      to_name: picked.to.name,
      period: form.period.value,
      notify_time: form.notify_time.value || "",
    });
    const res = await fetch("/api/admin/lines", { method: "POST", body });
    if (res.ok) {
      // Réinitialise tout le formulaire.
      picked.from = picked.to = null;
      form.reset();
      delete label.dataset.touched;
      form.classList.add("hidden");
      ["from", "to"].forEach((r) => {
        document.getElementById("search-" + r).value = "";
        document.getElementById("results-" + r).innerHTML = "";
        document.getElementById("chosen-" + r).innerHTML = "";
      });
      loadLines();
    }
  });
}

// --- Liste / réordonnancement / suppression ---
async function loadLines() {
  const lines = await (await fetch("/api/admin/lines")).json();
  const list = document.getElementById("lines-list");
  if (!lines.length) { list.innerHTML = `<div class="card-sub">Aucune ligne.</div>`; return; }
  list.innerHTML = lines.map((l, i) =>
    `<div class="line-row">
       <div class="reorder">
         <button type="button" class="ghost mini" data-move="up" data-id="${l.id}"
           ${i === 0 ? "disabled" : ""} aria-label="Monter">▲</button>
         <button type="button" class="ghost mini" data-move="down" data-id="${l.id}"
           ${i === lines.length - 1 ? "disabled" : ""} aria-label="Descendre">▼</button>
       </div>
       <div class="line-info">
         <strong>${esc(l.label)}</strong>
         <div class="meta">${esc(l.from_name)} → ${esc(l.to_name)}
           · ${PERIOD_LABEL[l.period]}${l.notify_time ? ` · 🔔 ${esc(l.notify_time)}` : ""}</div>
       </div>
       <button type="button" class="danger" data-del="${l.id}">Supprimer</button>
     </div>`).join("");
  list.querySelectorAll("button[data-del]").forEach((b) => {
    b.addEventListener("click", () => delLine(b.dataset.del));
  });
  list.querySelectorAll("button[data-move]").forEach((b) => {
    b.addEventListener("click", async () => {
      await fetch(`/api/admin/lines/${b.dataset.id}/move`, {
        method: "POST",
        body: new URLSearchParams({ direction: b.dataset.move }),
      });
      loadLines();
    });
  });
}

async function delLine(id) {
  if (!confirm("Supprimer cette ligne ?")) return;
  await fetch("/api/admin/lines/" + id, { method: "DELETE" });
  loadLines();
}

// --- Sauvegarde : export / import ---
function setupBackup() {
  const status = document.getElementById("backup-status");

  document.getElementById("export-btn").addEventListener("click", async () => {
    const res = await fetch("/api/admin/export");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "voie-libre-trajets.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  const fileInput = document.getElementById("import-file");
  document.getElementById("import-btn").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (!confirm("L'import REMPLACE tous les trajets actuels. Continuer ?")) {
      fileInput.value = "";
      return;
    }
    try {
      const payload = JSON.parse(await file.text());
      const res = await fetch("/api/admin/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const out = await res.json();
      status.textContent = res.ok
        ? `${out.imported} trajet(s) importé(s).`
        : (out.detail || "Import refusé.");
      loadLines();
    } catch (e) {
      status.textContent = "Fichier illisible (JSON attendu).";
    }
    fileInput.value = "";
  });
}

// --- Aide (tutoriel clé API) ---
document.getElementById("help-btn").addEventListener("click", () => {
  document.getElementById("help-content").classList.toggle("hidden");
});

init();
