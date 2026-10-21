#!/bin/bash
# Installs the display stack Hermes needs to host Bot Desktop, computer_use and the browser in a Linux
# Space: TigerVNC + Xfce parts, Playwright Chromium, agent-browser and cua-driver. The same set as
# nousresearch/hermes-sandbox:desktop (Hermes docker/sandbox-desktop.Dockerfile). Idempotent. Needs sudo.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
CUA_DRIVER_VERSION="${CUA_DRIVER_VERSION:-0.28.2}"
case "$(uname -m)" in x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;; esac
SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo -n"
$SUDO apt-get -o Acquire::Retries=3 update
$SUDO apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
  tigervnc-standalone-server xfce4-panel xfwm4 xfdesktop4 xfce4-settings dbus-x11 x11-xserver-utils x11-utils \
  x11-xkb-utils xauth fonts-dejavu-core at-spi2-core python3-pil curl ca-certificates
$SUDO mkdir -p /opt/playwright && $SUDO chmod 0777 /opt/playwright
if ! ls /opt/playwright/chromium-*/chrome-linux*/chrome >/dev/null 2>&1; then
  $SUDO env PLAYWRIGHT_BROWSERS_PATH=/opt/playwright npx --yes playwright@1 install --with-deps chromium
  $SUDO chmod -R a+rX /opt/playwright
fi
if ! command -v agent-browser >/dev/null; then
  $SUDO npm install -g --ignore-scripts --no-audit "agent-browser@^0.26.0"
  # the npm global bin dir is not always on the exec PATH
  $SUDO ln -sf "$(npm prefix -g)/bin/agent-browser" /usr/local/bin/agent-browser
fi
# installed without scripts, so the native binary is not executable yet
$SUDO chmod a+rx "$(npm root -g)"/agent-browser/bin/agent-browser-* 2>/dev/null || true
if ! command -v cua-driver >/dev/null; then
  $SUDO mkdir -p /opt/cua-driver
  curl -fsSL "https://github.com/trycua/cua/releases/download/cua-driver-rs-v${CUA_DRIVER_VERSION}/cua-driver-rs-${CUA_DRIVER_VERSION}-linux-${arch}-binary.tar.gz" | $SUDO tar -xz -C /opt/cua-driver
  $SUDO ln -sf /opt/cua-driver/cua-driver /usr/local/bin/cua-driver
fi
$SUDO mkdir -p /tmp/.X11-unix && $SUDO chmod 1777 /tmp/.X11-unix
cua-driver --version; agent-browser --version
echo "desktop stack ready"
