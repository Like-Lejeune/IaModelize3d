# IaModelize3d: API + agent + geometry workers + OrcaSlicer CLI in one image.
#   docker build -f Containerfile -t iamodelize3d .
#   docker run -d -p 127.0.0.1:8000:8000 -e META_API_KEY=... -e FW_PUBLIC_URL=https://<your host> -v iamodelize3d-data:/app/data iamodelize3d
# A VPS with HTTPS in front: deploy/compose.yaml (it builds this file).
# Slicing needs OrcaSlicer: the Ubuntu 24.04 build of v2.4.2, the version the farm's A1 0.4 quotes were calibrated
# on (glibc 2.38+ and webkit2gtk-4.1, so the runtime below is Debian 13 trixie). v2.3.0 cannot slice the A1 preset
# from the CLI ('Relative extruder addressing requires resetting the extruder position', exit 205).
#   --build-arg ORCA_APPIMAGE_URL=https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage
# PCB pipeline: tscircuit and its converters (~770 MB of node_modules, its own lock, not a workspace) bundled into
# packages/pcb/dist; only dist reaches the runtime, where the sandboxed worker may read nothing else.
FROM node:24-bookworm-slim AS pcb
WORKDIR /app/packages/pcb
COPY packages/pcb/package.json packages/pcb/package-lock.json ./
# manifold-3d on its own: on Linux the bundle step cannot otherwise resolve manifold-3d/manifold.wasm
RUN npm ci --ignore-scripts --no-audit --no-fund && npm install --no-save --ignore-scripts --no-audit --no-fund manifold-3d@3.5.4
COPY packages/geom/src/boards.json /app/packages/geom/src/boards.json
COPY packages/pcb/src src
COPY packages/pcb/scripts scripts
RUN npm run bundle

FROM node:24-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/geom/package.json packages/geom/
COPY web/package.json web/
RUN npm ci
COPY packages packages
COPY web web
RUN npm run build -w web

FROM python:3.12-slim-trixie
ARG ORCA_APPIMAGE_URL=""
# what the extracted AppImage loads from the host (its own check names libopengl0 and libglu1-mesa); no FUSE is needed.
# g++: the firmware check compiles each device's sketch against the stub Arduino headers (firmware_check.py; no link)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg xvfb xauth libgl1 libegl1 libopengl0 libglu1-mesa libglib2.0-0t64 libgtk-3-0t64 \
      libwebkit2gtk-4.1-0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 file g++ \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN if [ -n "$ORCA_APPIMAGE_URL" ]; then \
      curl -fsSL "$ORCA_APPIMAGE_URL" -o /tmp/orca.AppImage && chmod +x /tmp/orca.AppImage && \
      cd /opt && /tmp/orca.AppImage --appimage-extract >/dev/null && mv squashfs-root orca && rm /tmp/orca.AppImage; \
    fi
ENV FW_ORCA_BIN=/opt/orca/AppRun FW_ORCA_PROFILES=/opt/orca/resources/profiles FW_DATA_DIR=/app/data
WORKDIR /app
# the dependencies only, cached until pyproject.toml or constraints.txt changes; the code runs from /app/server
# (PYTHONPATH), so however iamodelize3d is started it finds the repo around it (config.REPO_DIR: packages/, web/build),
# not a copy in site-packages. constraints.txt pins every version to the tested venv's, so a rebuild cannot pull a
# breaking fastapi/openai/pydantic release; a new dependency in pyproject.toml needs its pin there too
COPY server/pyproject.toml server/constraints.txt server/
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('server/pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt -c server/constraints.txt && rm /tmp/requirements.txt
COPY server server
ENV PYTHONPATH=/app/server
COPY --from=web /app/node_modules node_modules
COPY --from=web /app/packages packages
COPY --from=pcb /app/packages/pcb/dist packages/pcb/dist
COPY --from=web /app/web/build web/build
COPY LICENSE ./
RUN useradd -m fw && mkdir -p /app/data && chown -R fw /app/data
USER fw
WORKDIR /app/server
# Client addresses (the per-address cap for anonymous visitors) come from X-Forwarded-For, read by the server itself
# (app.client_ip): it takes the entry FW_PROXY_HOPS places from the right, the one the nearest proxy of ours appended,
# so whatever a visitor writes further left never counts. 1 is the supported setup: the port published to localhost
# only (-p 127.0.0.1:8000:8000) behind one TLS reverse proxy (Caddy, nginx) that appends the address it sees. A CDN in
# front of that proxy: -e FW_PROXY_HOPS=2. Nothing in front: -e FW_PROXY_HOPS=0 -e FORWARDED_ALLOW_IPS="" (and no
# docker userland proxy in between, or every visitor shares its address).
# uvicorn --proxy-headers stays for X-Forwarded-Proto (secure cookies behind TLS). It believes it only from
# FORWARDED_ALLOW_IPS: the proxy as the container sees it, for a proxy on the host the docker bridge gateway, which
# the private ranges below cover; narrow them to the gateway (e.g. 172.17.0.1) when other containers share the
# network. Never "*": a forged header would then set the scheme, and uvicorn would pick the visitor-written entry.
ENV FW_PROXY_HOPS=1 FORWARDED_ALLOW_IPS="127.0.0.1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 CMD curl -fs http://localhost:8000/api/examples >/dev/null || exit 1
CMD ["python", "-m", "uvicorn", "iamodelize3d.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
