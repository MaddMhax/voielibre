"""Client pour l'API SNCF (Navitia) : recherche de gares et trajets temps réel.

Pour un trajet (gare A -> gare B), on interroge l'endpoint `journeys` qui renvoie
les vrais trains reliant A à B, avec horaires théoriques et temps réel.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from . import database, siri
from .config import settings

_DT_FMT = "%Y%m%dT%H%M%S"

# L'API SNCF (Navitia) parle en heure locale de la couverture : Europe/Paris.
# Le conteneur tourne en UTC, il faut donc convertir explicitement.
PARIS_TZ = ZoneInfo("Europe/Paris")


def now_paris() -> datetime:
    """Heure courante à Paris, naïve (comparable aux horaires Navitia)."""
    return datetime.now(PARIS_TZ).replace(tzinfo=None)


class SNCFError(Exception):
    pass


def _auth() -> tuple[str, str]:
    if not settings.SNCF_API_KEY:
        raise SNCFError("Clé API SNCF manquante (variable SNCF_API_KEY).")
    # Navitia : authentification HTTP Basic, clé = identifiant, mot de passe vide.
    return (settings.SNCF_API_KEY, "")


logger = logging.getLogger("voielibre")
_usage_write_warned = False


def _count_api_call() -> None:
    """Compteur local de consommation : l'API SNCF n'expose pas son quota
    (aucun en-tête X-RateLimit-*), on tient donc nos propres comptes,
    par mois et par jour. Le flux SIRI des voies (open data) n'est pas compté.

    Best effort : une statistique auxiliaire ne doit jamais faire échouer le
    chargement des horaires (ex. base en lecture seule)."""
    global _usage_write_warned
    now = now_paris()
    try:
        database.bump_api_usage(now.strftime("%Y-%m"))
        database.bump_api_usage(now.strftime("%Y-%m-%d"))
        _usage_write_warned = False
    except Exception:  # noqa: BLE001
        if not _usage_write_warned:
            _usage_write_warned = True
            logger.exception(
                "Compteur d'usage API non enregistré (volume /data en lecture "
                "seule ? voir README, section dépannage)"
            )


def daily_quota_exceeded() -> bool:
    """Vrai si le plafond journalier de l'offre gratuite est atteint."""
    used = database.get_api_usage(now_paris().strftime("%Y-%m-%d"))
    return used >= settings.SNCF_API_DAILY_QUOTA


def _parse(dt: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(dt, _DT_FMT) if dt else None
    except (ValueError, TypeError):
        return None


def _hm(dt: Optional[datetime]) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def _disruption_messages(data: dict) -> list[str]:
    """Motifs des perturbations (« présence de personnes sur les voies »…),
    déjà présents dans la réponse `journeys` : aucune requête supplémentaire."""
    messages: list[str] = []
    for disruption in data.get("disruptions", []):
        for msg in disruption.get("messages", []):
            text = (msg.get("text") or "").strip()
            if text and text not in messages:
                messages.append(text)
    return messages[:3]  # les 3 premiers motifs distincts suffisent


def _platform(section: dict) -> str:
    """Voie de départ d'une section, si l'API la fournit.

    Navitia expose la voie sous `platform_code` sur le stop_point, parfois
    uniquement dans `stop_date_times`. Champ souvent absent en théorique ;
    il se remplit en temps réel à l'approche du départ.
    """
    candidates = []
    stop_times = section.get("stop_date_times") or []
    if stop_times:
        candidates.append(stop_times[0].get("stop_point") or {})
    candidates.append((section.get("from") or {}).get("stop_point") or {})
    for sp in candidates:
        code = sp.get("platform_code")
        if code:
            return str(code)
    return ""


async def search_stations(query: str) -> list[dict]:
    """Recherche des gares (stop_area) par nom pour le menu d'administration."""
    url = f"{settings.SNCF_API_BASE}/places"
    params = {"q": query, "type[]": "stop_area", "count": 10}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params, auth=_auth())
    _count_api_call()
    if resp.status_code == 401:
        raise SNCFError("Clé API SNCF invalide (401).")
    if resp.status_code == 429:
        raise SNCFError("Quota API SNCF dépassé (429) — réessayez demain.")
    resp.raise_for_status()
    places = resp.json().get("places", [])
    return [
        {"id": p["id"], "name": p["name"]}
        for p in places
        if p.get("embedded_type") == "stop_area"
    ]


async def _fetch_journeys(
    from_id: str, to_id: str, count: int, freshness: str
) -> dict:
    url = f"{settings.SNCF_API_BASE}/journeys"
    params = {
        "from": from_id,
        "to": to_id,
        "datetime": now_paris().strftime(_DT_FMT),
        "data_freshness": freshness,
        "count": count,
        "max_nb_transfers": 0,  # trajets directs uniquement (TER classiques)
        "depth": 2,  # détail des stop_point (nécessaire pour platform_code / voie)
    }
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.get(url, params=params, auth=_auth())
    _count_api_call()
    if resp.status_code == 401:
        raise SNCFError("Clé API SNCF invalide (401).")
    if resp.status_code == 429:
        raise SNCFError("Quota API SNCF dépassé (429) — réessayez demain.")
    resp.raise_for_status()
    return resp.json()


def _parse_trains(
    data: dict, siri_platforms: dict, uic_from: str
) -> list[tuple[str, dict]]:
    """Liste de (clé de départ théorique "YYYY-MM-DDTHH:MM", train)."""
    trains = []
    for journey in data.get("journeys", []):
        pt_sections = [
            s for s in journey.get("sections", []) if s.get("type") == "public_transport"
        ]
        if not pt_sections:
            continue
        first, last = pt_sections[0], pt_sections[-1]
        info = first.get("display_informations", {})

        dep_base = _parse(first.get("base_departure_date_time"))
        dep_rt = _parse(first.get("departure_date_time"))
        arr_base = _parse(last.get("base_arrival_date_time"))
        arr_rt = _parse(last.get("arrival_date_time"))

        # Départ déjà passé (heure de Paris) : on ne l'affiche pas.
        dep_effective = dep_rt or dep_base
        if dep_effective and dep_effective < now_paris():
            continue

        delay_min = 0
        if dep_base and dep_rt:
            delay_min = round((dep_rt - dep_base).total_seconds() / 60)

        cancelled = journey.get("status") == "NO_SERVICE"

        # Voie : Navitia ne la fournit pas (platform_code toujours absent sur
        # la couverture SNCF) ; on la prend dans le flux SIRI, indexé par
        # l'heure de départ théorique. Publiée ~15-30 min avant le départ.
        platform = _platform(first)
        if not platform and (dep_base or dep_rt):
            aimed = (dep_base or dep_rt).isoformat()[:16]
            platform = siri_platforms.get((uic_from, aimed), "")

        aimed_key = (dep_base or dep_rt).isoformat()[:16] if (dep_base or dep_rt) else ""
        trains.append(
            (
                aimed_key,
                {
                    "train": (
                        f"{info.get('commercial_mode', '')} "
                        f"{info.get('headsign', '')}"
                    ).strip(),
                    "direction": info.get("direction", ""),
                    "platform": platform,
                    "dep_planned": _hm(dep_base or dep_rt),
                    "dep_realtime": _hm(dep_rt),
                    # ISO local Paris : permet au front de masquer les départs
                    # échus sans nouvel appel API.
                    "dep_realtime_iso": dep_effective.isoformat() if dep_effective else None,
                    "arr_planned": _hm(arr_base or arr_rt),
                    "arr_realtime": _hm(arr_rt),
                    "delay_min": delay_min,
                    "cancelled": cancelled,
                },
            )
        )
    return trains


async def get_journeys(from_id: str, to_id: str, count: int = 4) -> dict:
    """Prochains trains directs de `from_id` vers `to_id`, avec retard temps réel.

    Deux interrogations (théorique + temps réel) : en mode temps réel, Navitia
    retire les trains supprimés du calcul d'itinéraire au lieu de les marquer.
    Un train présent dans le théorique mais absent du temps réel est donc
    affiché comme supprimé, plutôt que de disparaître silencieusement.
    """
    # Index des voies (flux SIRI open data) : (UIC gare, départ prévu) -> voie.
    siri_platforms = await siri.get_platforms()
    uic_from = from_id.rstrip(":").rsplit(":", 1)[-1]

    rt_data, base_data = await asyncio.gather(
        _fetch_journeys(from_id, to_id, count, "realtime"),
        _fetch_journeys(from_id, to_id, count, "base_schedule"),
    )
    rt = _parse_trains(rt_data, siri_platforms, uic_from)
    base = _parse_trains(base_data, siri_platforms, uic_from)

    trains = [t for _, t in rt]
    rt_keys = {k for k, _ in rt}
    # Fenêtre comparable : au-delà du dernier train temps réel, une absence
    # dans les résultats ne prouve pas une suppression (limite de `count`).
    horizon = max(rt_keys) if rt_keys else None
    for key, train in base:
        if key in rt_keys:
            continue
        if horizon is not None and key > horizon:
            continue
        train["cancelled"] = True
        trains.append(train)
    trains.sort(key=lambda t: t["dep_realtime_iso"] or "")

    # Statut global du trajet : pire cas parmi les prochains trains.
    status = "ok"
    worst_delay = 0
    if trains and all(t["cancelled"] for t in trains):
        status = "cancelled"
    elif any(t["cancelled"] for t in trains):
        status = "late"
    else:
        worst_delay = max((t["delay_min"] for t in trains), default=0)
        if worst_delay >= 5:
            status = "late"
        elif worst_delay > 0:
            status = "slight"

    return {
        "status": status,
        "worst_delay": worst_delay,
        "trains": trains,
        "disruption_messages": _disruption_messages(rt_data),
    }
