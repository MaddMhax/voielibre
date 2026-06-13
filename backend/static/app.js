/* Tableau de bord public.

   Économie de crédits API : /api/status (qui interroge l'API SNCF) n'est appelé
   qu'au chargement de la page ou via le bouton « Actualiser » — aucun polling.
   Entre deux chargements, l'horloge et le masquage des départs échus sont
   calculés localement, en heure de Paris. */
const STATUS_LABEL = {
  ok: "À l'heure",
  slight: "Léger retard",
  late: "En retard",
  cancelled: "Supprimé",
  error: "Indisponible",
};
const PERIOD_LABEL = { morning: "🌅 Matin", evening: "🌇 Soir" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* --- Heure de Paris, calculée côté client (aucun appel réseau) --- */
const CLOCK_FMT = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris", hour12: false,
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const DATE_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Paris",
  year: "numeric", month: "2-digit", day: "2-digit",
});

// "YYYY-MM-DDTHH:MM:SS" en heure de Paris — comparable aux dep_realtime_iso
// (naïfs, locaux Paris) renvoyés par le backend, par simple ordre lexical.
function parisNowIso() {
  const d = new Date();
  return DATE_FMT.format(d) + "T" + CLOCK_FMT.format(d);
}

/* --- Rendu --- */
function trainRow(t) {
  const delayed = t.delay_min > 0;
  let depHtml = `<span class="time">${esc(t.dep_realtime)}</span>`;
  if (t.cancelled) {
    depHtml = `<span class="time cancelled-time">${esc(t.dep_planned)}</span>`;
  } else if (delayed) {
    depHtml = `<span class="strike">${esc(t.dep_planned)}</span>
               <span class="time delayed">${esc(t.dep_realtime)}</span>`;
  }
  const platform = t.platform
    ? `<span class="platform">Voie ${esc(t.platform)}</span>`
    : `<span class="platform unknown">Voie —</span>`;
  const tag = t.cancelled
    ? `<span class="late-tag">supprimé</span>`
    : delayed ? `<span class="late-tag">+${t.delay_min} min</span>` : "";
  return `<div class="dep">${depHtml} ${platform}
            <span class="dest">→ ${esc(t.arr_realtime)}</span> ${tag}</div>`;
}

// Trains encore à venir (départ non échu, heure de Paris).
function upcoming(line, nowIso) {
  return (line.trains || []).filter(
    (t) => !t.dep_realtime_iso || t.dep_realtime_iso >= nowIso
  );
}

// Statut recalculé sur les trains visibles (même logique que le backend),
// pour qu'un retard déjà parti ne laisse pas la carte en rouge.
function deriveStatus(trains) {
  if (!trains.length) return { status: "ok", worst: 0 };
  if (trains.every((t) => t.cancelled)) return { status: "cancelled", worst: 0 };
  const worst = Math.max(...trains.map((t) => t.delay_min || 0), 0);
  if (trains.some((t) => t.cancelled) || worst >= 5) return { status: "late", worst };
  if (worst > 0) return { status: "slight", worst };
  return { status: "ok", worst: 0 };
}

function warningBanner(status, worst) {
  if (status === "cancelled") {
    return `<div class="warn-banner">⚠️ <strong>Trains supprimés</strong> sur ce trajet</div>`;
  }
  if (status === "late") {
    const delay = worst > 0 ? ` — jusqu'à <strong>+${worst} min</strong>` : "";
    return `<div class="warn-banner">⚠️ <strong>Retard en cours</strong>${delay}</div>`;
  }
  return "";
}

function disruptionCauses(line, st) {
  if (st !== "late" && st !== "cancelled" && st !== "slight") return "";
  const msgs = line.disruption_messages || [];
  if (!msgs.length) return "";
  return `<div class="causes">${msgs.map((m) =>
    `<div class="cause">ℹ️ ${esc(m)}</div>`).join("")}</div>`;
}

function card(line, nowIso) {
  const trains = upcoming(line, nowIso);
  const derived = line.error ? { status: "error", worst: 0 } : deriveStatus(trains);
  const st = derived.status;
  let body;
  if (line.error) {
    body = `<div class="card-sub">${esc(line.error)}</div>`;
  } else if (!trains.length) {
    body = `<div class="card-sub">Aucun train direct à venir.</div>`;
  } else {
    body = `<div class="departures">${trains.slice(0, 4).map(trainRow).join("")}</div>`;
  }
  const trajet = `${esc(line.from_name)} → ${esc(line.to_name)}`;
  return `<div class="card ${st}">
    <div class="card-head">
      <div>
        <div class="card-title">${esc(line.label)}</div>
        <div class="card-sub">${trajet}</div>
      </div>
      <span class="pill ${st}">${STATUS_LABEL[st] || st}</span>
    </div>
    ${warningBanner(st, derived.worst)}
    ${disruptionCauses(line, st)}
    ${body}
  </div>`;
}

function globalAlert(lines, nowIso) {
  const bad = lines.filter((l) => {
    if (l.error) return false;
    const st = deriveStatus(upcoming(l, nowIso)).status;
    return st === "late" || st === "cancelled";
  });
  if (!bad.length) return "";
  const names = bad.map((l) => esc(l.label)).join(", ");
  return `<div class="global-alert" role="alert">
    <span class="global-alert-icon">⚠️</span>
    <div>
      <strong>Perturbation${bad.length > 1 ? "s" : ""} en cours</strong>
      <div class="global-alert-sub">${names}</div>
    </div>
  </div>`;
}

/* --- Cycle de vie --- */
let lastData = null;       // dernière réponse de /api/status
let renderedKey = "";      // signature du dernier rendu (pour ne pas re-rendre pour rien)
let forcedPeriod = null;   // null = vue auto (selon l'heure) ; "morning"/"evening" = forcée
let autoPeriod = null;     // période « naturelle » renvoyée par le serveur (sans forçage)

function quotaAlert() {
  if (!lastData.quota_exceeded) return "";
  return `<div class="global-alert" role="alert">
    <span class="global-alert-icon">🚫</span>
    <div>
      <strong>Quota API journalier dépassé</strong>
      <div class="global-alert-sub">Les horaires affichés peuvent être erronés :
      l'accès à l'API SNCF est suspendu jusqu'à demain.</div>
    </div>
  </div>`;
}

function render() {
  if (!lastData) return;
  const nowIso = parisNowIso();
  document.getElementById("global-alert").innerHTML =
    quotaAlert() + globalAlert(lastData.lines, nowIso);
  const cards = document.getElementById("cards");
  if (!lastData.lines.length) {
    cards.innerHTML = `<div class="empty">Aucune ligne configurée.<br>
      Ajoutez-en une depuis la page d'administration.</div>`;
    return;
  }
  cards.innerHTML = lastData.lines.map((l) => card(l, nowIso)).join("");
}

function updatePeriodBadge() {
  const badge = document.getElementById("period");
  badge.textContent = PERIOD_LABEL[lastData.period] || lastData.period;
  // Surligne le badge quand on regarde une période autre que le moment courant.
  badge.classList.toggle("forced", forcedPeriod !== null);
}

// Bascule la vue matin ↔ soir. Revenir à la période « naturelle » (celle de
// l'heure courante) repasse en mode auto plutôt que de la figer.
function togglePeriod() {
  const shown = (lastData && lastData.period) || autoPeriod || "morning";
  const target = shown === "morning" ? "evening" : "morning";
  forcedPeriod = target === autoPeriod ? null : target;
  load();
}

async function load() {
  try {
    const url = forcedPeriod ? `/api/status?period=${forcedPeriod}` : "/api/status";
    const res = await fetch(url);
    const data = await res.json();
    lastData = data;
    if (!forcedPeriod) autoPeriod = data.period;  // mémorise la vue du moment
    updatePeriodBadge();
    document.getElementById("updated").textContent = data.generated_at;
    render();
  } catch (e) {
    document.getElementById("cards").innerHTML =
      `<div class="error-msg">Impossible de charger les données.</div>`;
  }
}

// Horloge Europe/Paris (locale, gratuite) ; quand un départ affiché devient
// échu, la liste est re-rendue — toujours sans appel API.
function tick() {
  const nowIso = parisNowIso();
  document.getElementById("clock").textContent = nowIso.slice(11);
  if (!lastData) return;
  const key = lastData.lines
    .map((l) => upcoming(l, nowIso).length)
    .join(",");
  if (key !== renderedKey) {
    renderedKey = key;
    render();
  }
}

document.getElementById("refresh").addEventListener("click", load);
document.getElementById("period").addEventListener("click", togglePeriod);

load();
tick();
setInterval(tick, 1000);
