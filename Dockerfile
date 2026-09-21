# 前端仅在构建阶段需要 Node；运行镜像由同一个后端提供页面和 API。
FROM node:22-alpine AS web
ARG NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry="${NPM_REGISTRY}"
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    AIQ_CONTROL_DATABASE=/srv/app/runtime/control.duckdb \
    AIQ_SESSION_WORKSPACE=/srv/app/runtime/session-workspaces
WORKDIR /srv/app
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /srv/app/runtime \
    && chown -R appuser:appuser /srv/app/runtime
COPY --from=web /build/dist ./frontend/dist/
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ui-api/health', timeout=3)"
# 原生会话锁和消息总线为进程内实现，当前必须使用单 worker。
CMD ["python", "-m", "app.main"]
