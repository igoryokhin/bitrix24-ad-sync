# ============================================================
# Stage 1: builder — venv с зависимостями
# ============================================================
FROM python:3.12-alpine AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY bot/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ============================================================
# Stage 2: runtime
# ============================================================
FROM python:3.12-alpine AS runtime

ENV TZ=Europe/Moscow \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apk add --no-cache tzdata tini && \
    cp /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo "$TZ" > /etc/timezone && \
    addgroup -g 1000 -S bot && adduser -u 1000 -S -G bot bot

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY bot/ /app/

RUN mkdir -p /app/data && chown -R bot:bot /app

USER bot

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "bot.py"]
