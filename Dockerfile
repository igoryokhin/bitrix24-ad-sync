# ============================================================
# Stage 1: builder — ставим venv и скачиваем supercronic
# ============================================================
FROM python:3.12-alpine AS builder

ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH=amd64

WORKDIR /build

# venv с зависимостями
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# supercronic
RUN wget -q -O /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" && \
    chmod +x /usr/local/bin/supercronic


# ============================================================
# Stage 2: runtime — тот же python:3.12-alpine
# ============================================================
FROM python:3.12-alpine AS runtime

ENV TZ=Europe/Moscow \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Runtime-пакеты: tzdata (для TZ), tini (PID 1)
RUN apk add --no-cache tzdata tini && \
    cp /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo "$TZ" > /etc/timezone && \
    addgroup -g 1000 -S sync && adduser -u 1000 -S -G sync sync

# venv из builder
COPY --from=builder /opt/venv /opt/venv

# supercronic из builder
COPY --from=builder /usr/local/bin/supercronic /usr/local/bin/supercronic

WORKDIR /app

COPY ad_common.py full_sync.py delta_sync.py ./
COPY crontab /app/crontab
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/logs && \
    chown -R sync:sync /app

USER sync

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/entrypoint.sh"]