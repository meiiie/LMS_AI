FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH
ARG GOOGLE_CHROME_VERSION=152.0.7977.64-1
ARG GOOGLE_CHROME_AMD64_SHA256=4eae0736a812d9bc851cd2937f7af00e47dbaf8305845eed452703ff009873c7
ARG GOOGLE_CHROME_ARM64_SHA256=6ccab79a7afe1d174c89e28cf0d5a265e6e8855ff3b45c6a2151a65d7ddae9e8

RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
       ca-certificates \
       at-spi2-core \
       adwaita-icon-theme \
       curl \
       dbus-x11 \
       fonts-dejavu-core \
       fonts-liberation \
       fonts-noto-color-emoji \
       lxpanel \
       lxterminal \
       libatomic1 \
       libpulse0 \
       libpulse-mainloop-glib0 \
       librsvg2-bin \
       libxcb-icccm4 \
       libxcb-image0 \
       libxcb-keysyms1 \
       libxcb-render-util0 \
       libxcb-shape0 \
       libxcb-xinerama0 \
       libxcb-xkb1 \
       libxkbcommon-x11-0 \
       libreoffice-calc \
       novnc \
       openbox \
       pcmanfm \
       procps \
       python3 \
       python3-pyatspi \
       python3-uno \
       python3-websocket \
       tigervnc-standalone-server \
       tigervnc-tools \
       tini \
       websockify \
       wmctrl \
    && chrome_arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$chrome_arch" in \
         amd64) chrome_sha="$GOOGLE_CHROME_AMD64_SHA256" ;; \
         arm64) chrome_sha="$GOOGLE_CHROME_ARM64_SHA256" ;; \
         *) echo "Google Chrome is unavailable for architecture: $chrome_arch" >&2; exit 64 ;; \
       esac \
    && chrome_deb="/tmp/google-chrome-stable_${GOOGLE_CHROME_VERSION}_${chrome_arch}.deb" \
    && curl --fail --location --silent --show-error --retry 3 \
       "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${GOOGLE_CHROME_VERSION}_${chrome_arch}.deb" \
       --output "$chrome_deb" \
    && printf '%s  %s\n' "$chrome_sha" "$chrome_deb" | sha256sum --check --strict \
    && apt-get install -y --no-install-recommends "$chrome_deb" \
    && rm -f "$chrome_deb" /etc/apt/sources.list.d/google-chrome.list \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash neko \
    && install -d -o neko -g neko /workspace/project /home/neko/.config /home/neko/.vnc \
    && install -d -o root -g root /run/secrets

COPY --chown=root:root wiii.html /usr/share/novnc/wiii.html
COPY --chown=root:root semantic_bridge.py /usr/local/lib/wiii-computer/semantic_bridge.py
COPY --chown=root:root work_plane_bridge.py /usr/local/lib/wiii-computer/work_plane_bridge.py
COPY --chown=root:root panel.conf /usr/share/wiii-computer/panel.conf
COPY --chown=root:root wallpaper.svg /usr/share/wiii-computer/wallpaper.svg
COPY --chown=root:root desktop-items-0.conf /usr/share/wiii-computer/desktop-items-0.conf
COPY --chown=root:root desktop/ /usr/share/wiii-computer/desktop/
COPY --chown=root:root chrome-managed-policies.json /etc/opt/chrome/policies/managed/wiii-ai.json
COPY --chown=root:root entrypoint.sh /usr/local/bin/wiii-computer-entrypoint
COPY --chown=root:root wiii-browser /usr/local/bin/wiii-browser
RUN rsvg-convert --width 1440 --height 900 \
      /usr/share/wiii-computer/wallpaper.svg \
      --output /usr/share/wiii-computer/wallpaper.png \
    && chmod 0755 \
      /usr/local/bin/wiii-computer-entrypoint \
      /usr/local/bin/wiii-browser \
      /usr/local/lib/wiii-computer/semantic_bridge.py \
      /usr/local/lib/wiii-computer/work_plane_bridge.py \
      /usr/share/wiii-computer/desktop/*.desktop

USER neko
WORKDIR /workspace/project
ENV DISPLAY=:1 \
    HOME=/home/neko \
    LANG=C.UTF-8 \
    GTK_MODULES=atk-bridge \
    NO_AT_BRIDGE=0 \
    QT_ACCESSIBILITY=1

EXPOSE 6080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=1s --retries=3 \
  CMD curl --fail --silent --show-error --max-time 2 http://127.0.0.1:9234/health >/dev/null \
      && curl --fail --silent --show-error --max-time 2 http://127.0.0.1:9222/json/version >/dev/null \
      && pgrep -x websockify >/dev/null \
      && pgrep -x Xtigervnc >/dev/null \
      && pgrep -x openbox >/dev/null \
      || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/wiii-computer-entrypoint"]
