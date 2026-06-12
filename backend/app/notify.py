"""Notifications de perturbation via ntfy (https://ntfy.sh, auto-hébergeable).

Économie de quota : pas de surveillance continue. Chaque trajet peut définir
une heure de vérification (`notify_time`, ex. 15 min avant le train habituel) ;
à cette heure-là uniquement, l'app interroge l'API SNCF (2 requêtes) et pousse
une notification si le trajet est en retard ou supprimé. Rien sinon.

Le corps du message est en UTF-8 (les en-têtes ntfy étant limités à l'ASCII,
le titre reste implicite : le nom du topic).
"""
import asyncio
import logging

import httpx

from . import database, sncf
from .config import settings

logger = logging.getLogger("voielibre")

# (line_id, "YYYY-MM-DD") -> déjà vérifié ce jour-là (évite les doublons).
_checked: dict[tuple[int, str], bool] = {}


async def _push(message: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            settings.NTFY_URL,
            content=message.encode("utf-8"),
            headers={"Priority": "high", "Tags": "warning,train"},
        )
        resp.raise_for_status()


async def _check_line(line: dict) -> None:
    result = await sncf.get_journeys(line["from_id"], line["to_id"])
    status = result["status"]
    if status not in ("late", "cancelled"):
        return  # tout va bien : pas de bruit

    if status == "cancelled":
        headline = f"🚫 {line['label']} : trains supprimés"
    else:
        worst = result["worst_delay"]
        headline = f"⚠️ {line['label']} : retard"
        if worst:
            headline += f" jusqu'à +{worst} min"

    details = []
    for t in result["trains"][:3]:
        if t["cancelled"]:
            details.append(f"• {t['dep_planned']} supprimé")
        elif t["delay_min"] > 0:
            details.append(f"• {t['dep_planned']} → {t['dep_realtime']} (+{t['delay_min']} min)")
        else:
            details.append(f"• {t['dep_realtime']} à l'heure")
    causes = result.get("disruption_messages") or []
    body = "\n".join([headline, *details, *(f"ℹ️ {c}" for c in causes[:1])])
    await _push(body)
    logger.info("Notification ntfy envoyée pour « %s »", line["label"])


async def _tick() -> None:
    now = sncf.now_paris()
    hhmm = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")

    # Purge des marqueurs des jours précédents.
    for key in [k for k in _checked if k[1] != today]:
        _checked.pop(key, None)

    for line in database.list_lines():
        if (line.get("notify_time") or "") != hhmm:
            continue
        key = (line["id"], today)
        if _checked.get(key):
            continue
        _checked[key] = True
        try:
            await _check_line(line)
        except Exception:  # noqa: BLE001 — la notification ne doit rien casser
            logger.exception("Vérification ntfy en échec pour « %s »", line.get("label"))


async def scheduler_loop() -> None:
    """Boucle de fond (démarrée au startup) : un tick par minute."""
    if not settings.NTFY_URL:
        logger.info("Notifications ntfy désactivées (NTFY_URL non configurée).")
        return
    logger.info("Notifications ntfy actives (topic : %s).", settings.NTFY_URL)
    while True:
        try:
            await _tick()
        except Exception:  # noqa: BLE001
            logger.exception("Tick de notification en échec")
        await asyncio.sleep(60)
