# ============================================================
# Stage 1: builder — venv с зависимостями
# ============================================================
FROM python:3.12-alpine AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY webui/requirements.txt .
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

# wget — только для healthcheck (тот же приём, что pgrep у ad-sync)
RUN apk add --no-cache tzdata tini wget && \
    cp /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo "$TZ" > /etc/timezone && \
    addgroup -g 1000 -S webui && adduser -u 1000 -S -G webui webui

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY webui/ /app/

RUN mkdir -p /app/data /app/sync-logs && chown -R webui:webui /app

USER webui

EXPOSE 8000

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "--threads=4", "wsgi:application"]
