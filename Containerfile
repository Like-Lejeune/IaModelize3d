# Formwright: API + agent + geometry workers + OrcaSlicer CLI in one image.
#   docker build --build-arg ORCA_APPIMAGE_URL=<OrcaSlicer Linux AppImage URL> -t formwright .
#   docker run -p 8000:8000 -e META_API_KEY=... -v formwright-data:/app/data formwright
FROM node:24-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/geom/package.json packages/geom/
COPY web/package.json web/
RUN npm ci
COPY packages packages
COPY web web
RUN npm run build -w web

FROM python:3.12-slim-bookworm
ARG ORCA_APPIMAGE_URL=""
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg xvfb xauth libgl1 libegl1 libglib2.0-0 libgtk-3-0 libwebkit2gtk-4.1-0 libgstreamer1.0-0 \
      libgstreamer-plugins-base1.0-0 libfuse2 file \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN if [ -n "$ORCA_APPIMAGE_URL" ]; then \
      curl -fsSL "$ORCA_APPIMAGE_URL" -o /tmp/orca.AppImage && chmod +x /tmp/orca.AppImage && \
      cd /opt && /tmp/orca.AppImage --appimage-extract >/dev/null && mv squashfs-root orca && rm /tmp/orca.AppImage; \
    fi
ENV FW_ORCA_BIN=/opt/orca/AppRun FW_ORCA_PROFILES=/opt/orca/resources/profiles FW_DATA_DIR=/app/data
WORKDIR /app
COPY server/pyproject.toml server/
RUN pip install --no-cache-dir ./server 2>/dev/null || pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic-settings openai httpx aiosqlite numpy opencv-python-headless pillow scipy python-multipart meta-sam-parser
COPY --from=web /app/node_modules node_modules
COPY --from=web /app/packages packages
COPY --from=web /app/web/build web/build
COPY server server
COPY LICENSE ./
RUN useradd -m fw && mkdir -p /app/data && chown -R fw /app/data
USER fw
WORKDIR /app/server
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "formwright.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
