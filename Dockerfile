FROM alpine:3.24

LABEL maintainer="Tobias Rös - <roes@amicaldo.de>"

# official Ookla speedtest CLI, see https://www.speedtest.net/apps/cli
ARG OOKLA_VERSION=1.2.0
# set by BuildKit, falls back to the architecture of the build host
ARG TARGETARCH
ARG TARGETVARIANT

# install dependencies
RUN apk add --no-cache \
  ca-certificates \
  git \
  nodejs \
  npm \
  python3 \
  py3-pip \
  tzdata

# fallback engine (speedtest-cli is no longer maintained)
RUN pip install --no-cache-dir --break-system-packages speedtest-cli==2.1.3

# not fatal: without the Ookla CLI the runner falls back to speedtest-cli
RUN ( ARCH="${TARGETARCH:-$(apk --print-arch)}${TARGETVARIANT}" \
  && case "$ARCH" in \
    amd64|x86_64) OOKLA_ARCH=x86_64 ;; \
    arm64*|aarch64) OOKLA_ARCH=aarch64 ;; \
    armv7|armv7*) OOKLA_ARCH=armhf ;; \
    armv6|armv6*|armhf) OOKLA_ARCH=armel ;; \
    386|x86) OOKLA_ARCH=i386 ;; \
    *) echo "unsupported architecture $ARCH" && exit 1 ;; \
  esac \
  && mkdir -p /opt/ookla \
  && wget -qO /tmp/ookla.tgz "https://install.speedtest.net/app/cli/ookla-speedtest-${OOKLA_VERSION}-linux-${OOKLA_ARCH}.tgz" \
  && tar -xzf /tmp/ookla.tgz -C /opt/ookla speedtest \
  && /opt/ookla/speedtest --version ) \
  || echo "WARNING: Ookla CLI could not be installed, speedtest-cli will be used" ; \
  rm -f /tmp/ookla.tgz

WORKDIR /var/www/html

# install frontend dependencies first to keep them cached
COPY package.json yarn.lock ./
RUN npm install -g yarn && yarn install && npm uninstall -g yarn && npm cache clean --force

# install webroot files
COPY ./ ./

EXPOSE 80

HEALTHCHECK --interval=1m --timeout=10s CMD wget -qO /dev/null http://127.0.0.1:${PORT:-80}/ || exit 1

ENTRYPOINT ["python3", "-u", "/var/www/html/scripts/server.py"]
