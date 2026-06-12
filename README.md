# 🚦 Voie Libre — vos TER en temps réel

**Voie Libre** (terme ferroviaire : la voie est dégagée, le train peut passer)
est une application web auto-hébergée, simple et épurée, qui indique **d'un coup
d'œil** si vos trains TER sont **à l'heure** ou **en retard**, selon le moment
de la journée (matin / soir). Configurez vos trajets favoris (gare de départ →
gare d'arrivée) et obtenez les prochains trains directs : horaires temps réel,
**voie de départ**, retards et suppressions.

> **Identité visuelle** — DA « affiche jaune des départs » : bleu nuit encre et
> jaune doré inspirés des panneaux de départ des gares françaises (thème clair
> façon papier d'affiche). Les statuts reprennent la signalisation ferroviaire :
> vert / orange / rouge / violet. Le logo (`backend/static/logo.svg`) : un « V »
> formé de deux rails convergents, surmonté du signal vert « voie libre ».

## Fonctionnalités

- **Tableau de bord public** (`/`) : sans authentification, cartes
  vert / orange / rouge, horloge **Europe/Paris**, thème clair/sombre.
- **Voie de départ** pour chaque train, issue du **flux open data SIRI Lite**
  (données PIV SNCF) — l'API Navitia ne la fournit pas. « Voie — » tant que la
  SNCF ne l'a pas publiée (petites gares : plusieurs heures à l'avance ; grandes
  gares : ~20 min avant le départ, comme les écrans en gare).
- **Avertissements visibles** : bandeau rouge animé sur la carte en retard +
  alerte globale en haut de page, avec la **cause de la perturbation** quand la
  SNCF la publie (« présence de personnes sur les voies »…). Les **trains
  supprimés** restent affichés (horaire barré, mention « supprimé ») au lieu de
  disparaître silencieusement.
- **Notifications push** (optionnel, via [ntfy](https://ntfy.sh)) : chaque trajet
  peut définir une heure de vérification quotidienne — vous êtes prévenu sur
  votre téléphone si votre train est en retard ou supprimé, sans surveillance
  continue (2 requêtes API par vérification).
- **PWA installable** : ajoutez le tableau de bord à l'écran d'accueil de votre
  téléphone, il s'ouvre plein écran comme une app native.
- **Économe en crédits API** : l'API SNCF n'est interrogée qu'au chargement de
  la page (ou via le bouton **⟳ Rafraîchir**) — aucun polling. Cache serveur de
  30 s, masquage local des départs échus, suivi de quota jour/mois dans l'admin
  et avertissement public en cas de dépassement.
- **Administration** : protégée par mot de passe, sur une **route
  personnalisable** (`ADMIN_PATH`) non référencée sur les pages publiques.
  Recherche de gares, gestion et **réordonnancement** des trajets,
  **export/import JSON** (sauvegarde), quota API, aide intégrée.
- **Sécurisée par design** (voir [§ 6](#6-sécurité)) et **100 % conteneurisée**.

---

## 1. Obtenir une clé API SNCF (gratuit)

L'application utilise l'**API SNCF** (basée sur Navitia), qui expose les horaires
théoriques **et le temps réel** (retards, suppressions).

1. Rendez-vous sur le portail développeurs SNCF :
   **https://numerique.sncf.com/startup/api/**
2. Cliquez sur **« Demander un token »** / créez un compte (gratuit).
3. Validez votre adresse e-mail.
4. Vous recevez une **clé API** (un long jeton alphanumérique) par e-mail
   et/ou dans votre espace.
5. C'est tout : cette clé donne accès à `https://api.sncf.com/v1/`
   (offre gratuite : **5 000 requêtes/jour**, **150 000/mois**).

> ℹ️ L'authentification se fait en **HTTP Basic** : la clé sert d'identifiant,
> le mot de passe est vide. L'application gère cela automatiquement.
> Un mini-tutoriel est aussi disponible dans le panneau d'administration
> (bouton **« ❓ Comment obtenir une clé API SNCF »**).

Les **voies de départ** proviennent d'un flux open data séparé
(SIRI Lite, transport.data.gouv.fr) qui ne nécessite **aucune clé**.

---

## 2. Configuration

```bash
cp .env.example .env
```

Éditez `.env` :

| Variable                 | Requis | Description                                              |
|--------------------------|:------:|----------------------------------------------------------|
| `SNCF_API_KEY`           | ✅     | Votre clé API SNCF (étape 1). Démarrage refusé sans elle. |
| `ADMIN_PASSWORD`         | ✅     | Mot de passe admin. **Aucune valeur par défaut** : sans lui, l'admin est désactivée. |
| `ADMIN_USERNAME`         |        | Identifiant admin (défaut `admin`).                       |
| `ADMIN_PATH`             |        | Route (secrète) du panneau admin (défaut `/voielibre-admin`). |
| `SECRET_KEY`             |        | Signature des sessions (`openssl rand -hex 32`). Si absente, clé éphémère générée à chaque démarrage. |
| `BIND_ADDR`              |        | Adresse d'écoute (défaut `127.0.0.1` — derrière un proxy ; `0.0.0.0` pour exposer). |
| `MORNING_EVENING_CUTOFF` |        | Heure (0-23) qui bascule l'affichage matin → soir (défaut 14). |
| `SNCF_API_DAILY_QUOTA`   |        | Plafond journalier de l'offre API (défaut 5 000).         |
| `SNCF_API_MONTHLY_QUOTA` |        | Plafond mensuel de l'offre API (défaut 150 000).          |
| `SESSION_HTTPS_ONLY`     |        | `true` derrière un proxy HTTPS : cookie admin `Secure`.   |
| `NTFY_URL`               |        | URL complète d'un topic ntfy pour les notifications (§ 8). |
| `ACKEE_URL`              |        | URL de votre instance Ackee (optionnel, § 7).             |
| `ACKEE_DOMAIN_ID`        |        | Identifiant de domaine Ackee (optionnel, § 7).            |

---

## 3. Lancer l'application

```bash
docker compose up --build -d
```

Puis ouvrez **http://localhost:8000**.

- Tableau de bord : http://localhost:8000/
- Administration : http://localhost:8000/voielibre-admin (ou votre `ADMIN_PATH`)

Pour arrêter : `docker compose down`.

Les trajets configurés et le compteur de quota sont stockés dans un volume
Docker (`ter_data`), conservés entre les redémarrages.

---

## 4. Utilisation

1. Connectez-vous à votre route d'administration (`ADMIN_PATH`) avec
   `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
2. **Choisissez votre gare de départ** puis votre **gare d'arrivée** : tapez le
   nom (ex. « Lyon Part-Dieu », « Villefranche-sur-Saône »), l'application
   interroge l'API SNCF et propose les gares correspondantes.
3. Ajustez le **libellé** (pré-rempli) et la **période** (matin / soir / les
   deux), puis ajoutez le trajet.
4. Sur le tableau de bord, vos trajets s'affichent : uniquement les **trains
   directs** dont le départ (temps réel) n'est pas passé, avec retard, voie et
   suppressions. Les trajets **du matin** s'affichent avant
   `MORNING_EVENING_CUTOFF`, ceux **du soir** après.
5. Les horaires sont chargés **une seule fois** (heure affichée en pied de
   page) ; bouton **⟳ Rafraîchir** pour actualiser. L'horloge et le retrait des
   trains partis fonctionnent en continu sans consommer de quota.

### Code couleur

| Couleur     | Signification              |
|-------------|----------------------------|
| 🟢 Vert     | À l'heure                  |
| 🟠 Orange   | Léger retard (< 5 min)     |
| 🔴 Rouge    | En retard (≥ 5 min)        |
| 🟣 Violet   | Train supprimé             |

### Détection des suppressions

L'app compare le plan de transport **théorique** au **temps réel**
(2 requêtes API par trajet) : Navitia retire les trains annulés des résultats
temps réel au lieu de les marquer, un train présent dans le théorique mais
absent du temps réel est donc affiché comme supprimé.

### Quota API

Le panneau admin montre la consommation **du jour et du mois** (compteur local :
l'API SNCF n'expose pas son quota). Si le plafond journalier est atteint, un
**bandeau rouge s'affiche sur le tableau de bord public** : les horaires peuvent
être erronés, l'accès à l'API étant suspendu jusqu'au lendemain.

---

## 5. Architecture

```
voie-libre/
├── docker-compose.yml      # Orchestration (1 service + volume persistant)
├── .env.example            # Modèle de configuration
└── backend/
    ├── Dockerfile          # Image non-root
    ├── requirements.txt
    ├── pages/
    │   └── admin.html      # Page admin, servie uniquement sur ADMIN_PATH (hors /static)
    ├── app/
    │   ├── main.py         # API FastAPI + routes + en-têtes de sécurité
    │   ├── config.py       # Variables d'environnement
    │   ├── database.py     # SQLite (trajets + compteur API)
    │   ├── sncf.py         # Client API SNCF (retards, suppressions, causes)
    │   ├── siri.py         # Voies de départ (flux open data SIRI Lite, cache 2 min)
    │   └── notify.py       # Notifications ntfy (vérifications planifiées)
    └── static/             # Frontend (HTML/CSS/JS, sans script inline — CSP)
        ├── index.html      # Tableau de bord public
        ├── style.css
        ├── logo.svg        # Logo + favicon
        ├── theme-init.js   # Pose le thème avant le rendu (anti-clignotement)
        ├── theme.js        # Bascule clair / sombre
        ├── app.js          # Logique du tableau de bord
        ├── admin.js        # Logique de l'administration
        └── analytics.js    # Traqueur Ackee (inactif si non configuré)
```

**Stack :** Python 3.12 · FastAPI · SQLite · Vanilla JS — aucune dépendance lourde.

---

## 6. Sécurité

L'application est pensée pour être **déployée publiquement** :

**Authentification & administration**
- Aucun mot de passe par défaut : sans `ADMIN_PASSWORD`, l'admin est
  **désactivée** (et `docker compose` refuse de démarrer sans la variable).
- **Anti-bruteforce** : 5 échecs de connexion par IP → blocage 15 minutes,
  temporisation de 500 ms par échec, comparaison en temps constant.
- Session admin : cookie `HttpOnly` + `SameSite=Strict`, durée max 12 h,
  `Secure` avec `SESSION_HTTPS_ONLY=true`. Clé de signature jamais prédictible
  (générée aléatoirement si `SECRET_KEY` est absente).
- **Route admin personnalisable** (`ADMIN_PATH`) : non devinable, jamais
  référencée sur les pages publiques, page servie hors du montage `/static`.
- Entrées admin validées (format des identifiants de gare, longueurs bornées).

**Endpoints publics**
- **Cache serveur 30 s** sur `/api/status` : marteler la page publique ne peut
  pas épuiser le quota API SNCF (anti-DoS par épuisement de ressource).
- Aucun détail interne dans les erreurs publiques (messages génériques,
  détail dans les logs serveur uniquement).

**En-têtes & transport**
- **CSP stricte** (`script-src 'self'`, aucun script/style inline ; origine
  Ackee ajoutée automatiquement si configurée), **HSTS**, `X-Frame-Options:
  DENY` + `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy: no-referrer`,
  **Permissions-Policy** restrictive, COOP/CORP `same-origin`.

**Conteneur**
- Image **non-root** (utilisateur dédié), volume de données dont il est
  propriétaire, écoute sur `127.0.0.1` par défaut (exposition via proxy).

### Déploiement derrière Caddy

```caddyfile
ter.mondomaine.fr {
    reverse_proxy localhost:8000
}
```

Aucun en-tête à dupliquer côté proxy (uvicorn est lancé avec `--proxy-headers`
et lit les `X-Forwarded-*`). En production : `SESSION_HTTPS_ONLY=true`.

### Dépannage : volume créé avant la version non-root

L'image s'exécute sans privilèges (utilisateur `voielibre`, uid 1000). Si votre
volume `ter_data` a été créé par une **ancienne version** (qui tournait en root),
SQLite ne peut plus y écrire : lignes en erreur, ajout de trajet impossible.
Corrigez la propriété du volume une fois pour toutes :

```bash
docker compose exec --user root app chown -R voielibre:voielibre /data
```

(Les volumes créés à partir de cette version ont d'office le bon propriétaire.)

---

## 7. Analytics avec Ackee (optionnel)

[Ackee](https://ackee.electerious.com) est un outil d'analytics **auto-hébergé
et respectueux de la vie privée** (pas de cookies). Le front est déjà prêt : le
traqueur ne se charge que si `ACKEE_URL` et `ACKEE_DOMAIN_ID` sont renseignés
(`backend/static/analytics.js`, configuration servie par `/api/config`).

### 7.1 Déployer une instance Ackee

```yaml
services:
  ackee:
    image: electerious/ackee
    ports:
      - "3000:3000"
    environment:
      ACKEE_USERNAME: admin
      ACKEE_PASSWORD: changez-moi
      ACKEE_MONGODB: mongodb://mongo:27017/ackee
      # Indispensable : autorise le site à envoyer ses événements (CORS)
      ACKEE_ALLOW_ORIGIN: "https://ter.mondomaine.fr"
    depends_on:
      - mongo
  mongo:
    image: mongo:7
    volumes:
      - ackee_mongo:/data/db
volumes:
  ackee_mongo:
```

### 7.2 Brancher le site sur Ackee

1. Ouvrez l'interface Ackee et connectez-vous.
2. **Settings → Domains → New domain** : créez un domaine.
3. Copiez son **Domain ID** et renseignez le `.env` :
   `ACKEE_URL=https://ackee.mondomaine.fr` et `ACKEE_DOMAIN_ID=le-uuid`.
4. Relancez (`docker compose up -d --build`).

La **CSP est ajustée automatiquement** pour l'origine Ackee. Le traqueur est en
mode **non détaillé** et **respecte « Do Not Track »** ; la page d'administration
n'est pas suivie.

---

## 8. Notifications push avec ntfy (optionnel)

[ntfy](https://ntfy.sh) est un service de notifications push **gratuit et
auto-hébergeable** (app Android/iOS, aucune inscription).

1. Choisissez un nom de topic difficile à deviner (il fait office de secret),
   ex. `voie-libre-x7k2m9`, et abonnez-vous-y dans l'app ntfy.
2. Renseignez le `.env` : `NTFY_URL=https://ntfy.sh/voie-libre-x7k2m9`
   (ou l'URL de votre instance auto-hébergée), puis relancez.
3. Dans l'administration, donnez à chaque trajet une **heure de vérification**
   (champ 🔔, ex. 15 min avant votre train habituel).

Chaque jour à l'heure dite, l'app vérifie le trajet (2 requêtes API) et pousse
une notification **uniquement si** un train est en retard ou supprimé, avec les
horaires impactés et la cause. Train à l'heure = silence.

---

## 9. Développement local (sans Docker, optionnel)

```bash
cd backend
pip install -r requirements.txt
export SNCF_API_KEY=... ADMIN_PASSWORD=... DB_PATH=./ter.db
uvicorn app.main:app --reload
```

---

## Licence & contributions

Projet distribué sous licence **MIT** (voir [LICENSE](LICENSE)).
Les issues et pull requests sont bienvenues. Avant de publier un déploiement,
vérifiez que votre `.env` n'est pas commité (il est couvert par `.gitignore`)
et que `ADMIN_PATH` vous est propre.
