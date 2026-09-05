FROM python:3.12-slim

# FFmpeg powers the local demo media adapter; git/curl are convenience tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts
COPY run.py ./run.py

# The image runs in production mode, which refuses the demo secrets. Provide
# real TZ_TOKEN_SECRET and TZ_MEDIA_SERVICE_KEY (and TZ_ALLOWED_ORIGINS) at run.
ENV TZ_ENV=production \
    TZ_HTTP_HOST=0.0.0.0 \
    TZ_WS_HOST=0.0.0.0 \
    TZ_DATABASE_PATH=/data/three_zone.sqlite3

VOLUME ["/data"]
EXPOSE 8000 8765

CMD ["python", "run.py", "--host", "0.0.0.0"]
