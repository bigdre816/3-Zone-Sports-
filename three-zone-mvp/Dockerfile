FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts
COPY run.py ./run.py
COPY THREE_ZONE_MASTERY.md ./THREE_ZONE_MASTERY.md
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh && mkdir -p /data /app/data

ENV TZ_ENV=demo \
    TZ_HTTP_HOST=0.0.0.0 \
    TZ_WS_HOST=0.0.0.0 \
    TZ_DATABASE_PATH=/data/three_zone.sqlite3 \
    TZ_ALLOWED_ORIGINS=https://3zonesports.com,https://www.3zonesports.com,https://three-zone-sports.onrender.com \
    TZ_PUBLIC_BASE_URL=https://3zonesports.com \
    TZ_LIVE_MEDIA_PROVIDER=demo \
    TZ_UGC_MEDIA_PROVIDER=fake \
    TZ_PHOTO_STORAGE=fake \
    TZ_XRPL_MODE=demo

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
