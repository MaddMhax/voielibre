"""Voies de départ via le flux open data SIRI Lite (transport.data.gouv.fr).

L'API Navitia/SNCF n'expose pas la voie (vérifié : champ absent des réponses
`journeys` et `departures`, non documenté chez Hove). Le flux SIRI ET Lite
(données PIV SNCF, ouvert et sans clé) la fournit pour les trains circulant
dans l'heure à venir ; la SNCF la publie généralement 15 à 30 minutes avant
le départ, comme sur les écrans en gare.

Le flux est national (~15 Mo de XML, rafraîchi toutes les 2 minutes côté
producteur) : on le met en cache en mémoire pendant 2 minutes, et son
indexation se fait en streaming pour limiter l'empreinte mémoire.
"""
import asyncio
import io
import time
import xml.etree.ElementTree as ET

import httpx

SIRI_URL = (
    "https://proxy.transport.data.gouv.fr/resource/sncf-siri-lite-estimated-timetable"
)
_NS = "{http://www.siri.org.uk/siri}"
_CACHE_TTL = 120        # aligné sur la fréquence de production du flux
_RETRY_AFTER_FAIL = 30  # en cas d'échec, on ne réessaie pas avant 30 s

# clé : (code UIC de la gare, départ prévu "YYYY-MM-DDTHH:MM") -> voie
_cache: dict = {"at": 0.0, "platforms": {}}
_lock = asyncio.Lock()


def _parse(content: bytes) -> dict[tuple[str, str], str]:
    platforms: dict[tuple[str, str], str] = {}
    for _, elem in ET.iterparse(io.BytesIO(content)):
        if elem.tag != _NS + "EstimatedCall":
            continue
        stop_ref = elem.findtext(_NS + "StopPointRef") or ""
        aimed = elem.findtext(_NS + "AimedDepartureTime") or ""
        # Un train repart presque toujours de sa voie d'arrivée.
        platform = elem.findtext(_NS + "DeparturePlatformName") or elem.findtext(
            _NS + "ArrivalPlatformName"
        )
        if stop_ref and aimed and platform:
            uic = stop_ref.rstrip(":").rsplit(":", 1)[-1]  # FR:ScheduledStopPoint::87721332
            platforms[(uic, aimed[:16])] = platform  # heure locale Paris, à la minute
        elem.clear()
    return platforms


async def get_platforms() -> dict[tuple[str, str], str]:
    """Index (gare UIC, heure de départ prévue) -> voie. Best effort :
    en cas d'indisponibilité du flux, renvoie le dernier index connu."""
    if time.monotonic() - _cache["at"] < _CACHE_TTL:
        return _cache["platforms"]
    async with _lock:
        if time.monotonic() - _cache["at"] < _CACHE_TTL:  # rempli pendant l'attente
            return _cache["platforms"]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(SIRI_URL)
            resp.raise_for_status()
            _cache["platforms"] = _parse(resp.content)
            _cache["at"] = time.monotonic()
        except Exception:  # noqa: BLE001 — la voie est un bonus, jamais bloquant
            _cache["at"] = time.monotonic() - _CACHE_TTL + _RETRY_AFTER_FAIL
        return _cache["platforms"]
