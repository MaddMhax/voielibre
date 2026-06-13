"""Application FastAPI : tableau de bord public + administration protégée."""
import asyncio
import logging
import re
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import database, notify, sncf
from .config import settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# admin.html vit hors du montage /static : la page n'est servie qu'à la route
# d'administration (ADMIN_PATH), sinon /static/admin.html trahirait son existence.
PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

logger = logging.getLogger("voielibre")

# Clé de session : jamais de valeur prédictible. Sans SECRET_KEY explicite,
# clé aléatoire éphémère (sessions perdues au redémarrage, jamais forgeables).
if not settings.SECRET_KEY or settings.SECRET_KEY == "change-me-please":
    settings.SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY non définie : clé de session éphémère générée pour ce démarrage."
    )

app = FastAPI(title="Voie Libre", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    same_site="strict",
    https_only=settings.SESSION_HTTPS_ONLY,
    max_age=12 * 3600,  # session admin limitée à 12 h
)


# --------------------------------------------------------------------------- #
# En-têtes de sécurité
# --------------------------------------------------------------------------- #
def _build_csp() -> str:
    """CSP stricte : aucun script/style inline. Si Ackee est configuré, son
    origine est autorisée pour le script du traqueur et ses appels réseau."""
    script_src = ["'self'"]
    connect_src = ["'self'"]
    if settings.ACKEE_URL:
        script_src.append(settings.ACKEE_URL)
        connect_src.append(settings.ACKEE_URL)
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {' '.join(script_src)}",
            "style-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            f"connect-src {' '.join(connect_src)}",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


SECURITY_HEADERS = {
    "Content-Security-Policy": _build_csp(),
    # Ignoré par les navigateurs en HTTP simple ; prend effet derrière le
    # proxy HTTPS (Caddy) sans changement de code.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",  # redondant avec frame-ancestors, pour vieux navigateurs
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    # Sans Cache-Control, les navigateurs gardent JS/CSS en cache heuristique
    # sans revalider : après une mise à jour, pages neuves + vieux scripts.
    # no-cache = revalidation systématique (304 si inchangé, donc rapide).
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.on_event("startup")
async def _startup() -> None:
    database.init_db()
    # Vérifications planifiées + push ntfy (no-op si NTFY_URL absente).
    asyncio.create_task(notify.scheduler_loop())


# --------------------------------------------------------------------------- #
# Authentification (uniquement pour l'administration)
# --------------------------------------------------------------------------- #
def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="Authentification requise.")


# Anti-bruteforce : tentatives de connexion échouées par IP (fenêtre glissante).
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_S = 15 * 60
_login_failures: dict[str, list[float]] = {}


def _too_many_failures(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _login_failures.get(ip, []) if now - t < _LOGIN_WINDOW_S]
    if recent:
        _login_failures[ip] = recent
    else:
        _login_failures.pop(ip, None)
    return len(recent) >= _LOGIN_MAX_FAILURES


@app.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    # Sécurité par défaut : sans mot de passe configuré, l'admin est désactivée.
    if not settings.ADMIN_PASSWORD:
        return RedirectResponse(f"{settings.ADMIN_PATH}?error=disabled", status_code=303)

    ip = request.client.host if request.client else "?"
    if _too_many_failures(ip):
        logger.warning("Connexion admin bloquée (anti-bruteforce) pour %s", ip)
        return RedirectResponse(f"{settings.ADMIN_PATH}?error=lock", status_code=303)

    # Comparaison constante pour limiter le timing attack.
    ok = secrets.compare_digest(
        username, settings.ADMIN_USERNAME
    ) & secrets.compare_digest(password, settings.ADMIN_PASSWORD)
    if ok:
        _login_failures.pop(ip, None)
        request.session["admin"] = True
        return RedirectResponse(settings.ADMIN_PATH, status_code=303)

    _login_failures.setdefault(ip, []).append(time.monotonic())
    await asyncio.sleep(0.5)  # ralentit les tentatives automatisées
    return RedirectResponse(f"{settings.ADMIN_PATH}?error=1", status_code=303)


@app.get("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/api/me")
async def me(request: Request):
    return {"admin": bool(request.session.get("admin"))}


@app.get("/healthz")
async def healthz():
    """Sonde de vie (healthcheck Docker / proxy). Ne touche ni la BDD ni l'API."""
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Tableau de bord public
# --------------------------------------------------------------------------- #
@app.get("/api/config")
async def public_config():
    """Configuration non sensible exposée au front (traqueur Ackee)."""
    return {
        "ackee_url": settings.ACKEE_URL,
        "ackee_domain_id": settings.ACKEE_DOMAIN_ID,
    }


# Cache serveur de /api/status : l'endpoint est public et chaque appel coûte
# des requêtes SNCF — sans cache, marteler la page viderait le quota (déni de
# service par épuisement). 30 s laissent le bouton « Rafraîchir » utile.
# Cache par période : afficher manuellement l'autre moment (bouton matin/soir)
# charge sa propre vue sans écraser celle déjà en cache.
_STATUS_TTL_S = 30
_status_cache: dict[str, dict] = {}
_status_lock = asyncio.Lock()


@app.get("/api/status")
async def status(period: str | None = Query(None)):
    """Retards des lignes pertinentes pour le matin ou le soir.

    Sans paramètre, la période est déduite de l'heure courante (matin/soir).
    Le bouton matin/soir du tableau de bord force l'autre période via `?period=`.

    Appelé uniquement au chargement de la page (ou actualisation manuelle) :
    pas de polling côté front, pour préserver le quota de l'API SNCF.
    """
    now = sncf.now_paris()
    if period not in ("morning", "evening"):
        period = "morning" if now.hour < settings.MORNING_EVENING_CUTOFF else "evening"

    cached = _status_cache.get(period)
    if cached and time.monotonic() - cached["at"] < _STATUS_TTL_S:
        return cached["payload"]

    async with _status_lock:
        cached = _status_cache.get(period)
        if cached and time.monotonic() - cached["at"] < _STATUS_TTL_S:
            return cached["payload"]

        lines = database.list_lines(period=period)

        async def fetch(line: dict) -> dict:
            try:
                result = await sncf.get_journeys(line["from_id"], line["to_id"])
                return {**line, **result, "error": None}
            except sncf.SNCFError as exc:
                # Messages métier (clé manquante, quota…) : affichables tels quels.
                return {**line, "status": "error", "trains": [], "error": str(exc)}
            except Exception:  # noqa: BLE001
                # Jamais de détail interne sur l'endpoint public.
                logger.exception("Échec du chargement du trajet %s", line.get("id"))
                return {
                    **line,
                    "status": "error",
                    "trains": [],
                    "error": "Erreur interne lors du chargement du trajet.",
                }

        results = await asyncio.gather(*(fetch(line) for line in lines))
        payload = {
            "period": period,
            "generated_at": now.strftime("%H:%M:%S"),
            # Plafond journalier atteint : le front affiche un avertissement,
            # les données peuvent être erronées (plus d'accès à l'API SNCF).
            "quota_exceeded": sncf.daily_quota_exceeded(),
            "lines": results,
        }
        _status_cache[period] = {"payload": payload, "at": time.monotonic()}
        return payload


# --------------------------------------------------------------------------- #
# API d'administration (protégée)
# --------------------------------------------------------------------------- #
@app.get("/api/admin/lines")
async def admin_lines(request: Request, _=Depends(require_admin)):
    return database.list_lines()


@app.get("/api/admin/quota")
async def admin_quota(request: Request, _=Depends(require_admin)):
    """Consommation estimée de l'API SNCF (compteur local : l'API n'expose
    pas son quota). Le flux SIRI des voies, open data, n'est pas compté."""
    now = sncf.now_paris()
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    used = database.get_api_usage(month)
    day_used = database.get_api_usage(day)
    limit = settings.SNCF_API_MONTHLY_QUOTA
    day_limit = settings.SNCF_API_DAILY_QUOTA
    return {
        "month": month,
        "used": used,
        "limit": limit,
        "remaining": max(limit - used, 0),
        "day": day,
        "day_used": day_used,
        "day_limit": day_limit,
        "day_remaining": max(day_limit - day_used, 0),
    }


# Identifiants Navitia attendus (ex. stop_area:SNCF:87721332) : tout le reste
# est rejeté avant d'être stocké ou injecté dans une requête API.
_STOP_ID_RE = re.compile(r"stop_area:[A-Za-z0-9:_\-]{1,64}")
_TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _validate_line_fields(
    label: str, from_id: str, from_name: str, to_id: str, to_name: str,
    period: str, notify_time: str,
) -> dict:
    label, from_name, to_name = label.strip(), from_name.strip(), to_name.strip()
    notify_time = notify_time.strip()
    if not (1 <= len(label) <= 80) or not (1 <= len(from_name) <= 120) or not (
        1 <= len(to_name) <= 120
    ):
        raise HTTPException(status_code=400, detail="Libellé ou nom de gare invalide.")
    if not _STOP_ID_RE.fullmatch(from_id) or not _STOP_ID_RE.fullmatch(to_id):
        raise HTTPException(status_code=400, detail="Identifiant de gare invalide.")
    if notify_time and not _TIME_RE.fullmatch(notify_time):
        raise HTTPException(status_code=400, detail="Heure de notification invalide.")
    if period not in ("morning", "evening", "both"):
        period = "both"
    return {
        "label": label, "from_id": from_id, "from_name": from_name,
        "to_id": to_id, "to_name": to_name, "period": period,
        "notify_time": notify_time,
    }


@app.get("/api/admin/search")
async def admin_search(request: Request, q: str, _=Depends(require_admin)):
    if not (1 <= len(q.strip()) <= 80):
        raise HTTPException(status_code=400, detail="Recherche invalide.")
    try:
        return await sncf.search_stations(q.strip())
    except sncf.SNCFError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/lines")
async def admin_add(
    request: Request,
    label: str = Form(...),
    from_id: str = Form(...),
    from_name: str = Form(...),
    to_id: str = Form(...),
    to_name: str = Form(...),
    period: str = Form("both"),
    notify_time: str = Form(""),
    _=Depends(require_admin),
):
    fields = _validate_line_fields(
        label, from_id, from_name, to_id, to_name, period, notify_time
    )
    line_id = database.add_line(**fields)
    return {"id": line_id}


@app.delete("/api/admin/lines/{line_id}")
async def admin_delete(line_id: int, request: Request, _=Depends(require_admin)):
    database.delete_line(line_id)
    return JSONResponse({"ok": True})


@app.post("/api/admin/lines/{line_id}/move")
async def admin_move(
    line_id: int,
    request: Request,
    direction: str = Form(...),
    _=Depends(require_admin),
):
    if direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Direction invalide.")
    return {"moved": database.move_line(line_id, direction)}


@app.get("/api/admin/export")
async def admin_export(request: Request, _=Depends(require_admin)):
    """Sauvegarde des trajets au format JSON (réimportable)."""
    lines = [
        {k: ln[k] for k in (
            "label", "from_id", "from_name", "to_id", "to_name", "period", "notify_time"
        )}
        for ln in database.list_lines()
    ]
    return JSONResponse(
        {"voie_libre_export": 1, "lines": lines},
        headers={"Content-Disposition": 'attachment; filename="voie-libre-trajets.json"'},
    )


@app.post("/api/admin/import")
async def admin_import(request: Request, _=Depends(require_admin)):
    """Restauration d'un export : REMPLACE tous les trajets existants."""
    try:
        payload = await request.json()
        raw_lines = payload["lines"]
        assert isinstance(raw_lines, list) and len(raw_lines) <= 50
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Fichier d'export invalide.")
    validated = [
        _validate_line_fields(
            str(ln.get("label", "")), str(ln.get("from_id", "")),
            str(ln.get("from_name", "")), str(ln.get("to_id", "")),
            str(ln.get("to_name", "")), str(ln.get("period", "both")),
            str(ln.get("notify_time", "")),
        )
        for ln in raw_lines
    ]
    count = database.replace_lines(validated)
    return {"imported": count}


# --------------------------------------------------------------------------- #
# Pages statiques
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get(settings.ADMIN_PATH)
async def admin_page():
    return FileResponse(PAGES_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
