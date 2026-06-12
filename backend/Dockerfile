FROM python:3.12-slim

WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif + frontend (pages/ = pages hors montage public /static)
COPY app ./app
COPY static ./static
COPY pages ./pages

# Exécution sans privilèges : utilisateur dédié, /data (SQLite) lui appartient.
RUN useradd --create-home --uid 1000 voielibre \
    && mkdir -p /data \
    && chown voielibre:voielibre /data
USER voielibre

EXPOSE 8000

# --proxy-headers : fait confiance aux X-Forwarded-* posés par le proxy (Caddy),
# nécessaire pour que l'app voie le bon schéma (https) et la bonne IP client.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
