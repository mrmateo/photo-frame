#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/photo-frame}"
PYTHON_BIN="${PYTHON_BIN:-${APP_DIR}/venv/bin/python}"
CONFIG_PATH="${CONFIG_PATH:-${APP_DIR}/config.json}"

if [[ "${LANG:-}" != *"UTF-8"* && "${LANG:-}" != *"utf8"* ]]; then
  export LANG="C.UTF-8"
fi

if [[ -n "${LC_ALL:-}" && "${LC_ALL}" != *"UTF-8"* && "${LC_ALL}" != *"utf8"* ]]; then
  export LC_ALL="C.UTF-8"
fi

export QT_QUICK_CONTROLS_STYLE="Basic"
export QSG_RENDER_LOOP="${QSG_RENDER_LOOP:-basic}"
export QSG_RHI_BACKEND="${QSG_RHI_BACKEND:-opengl}"

if [[ -z "${QT_QPA_PLATFORM:-}" ]]; then
  if [[ -n "${WAYLAND_DISPLAY:-}" || "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    export QT_QPA_PLATFORM="wayland"
  elif [[ -n "${DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM="xcb"
  else
    export QT_QPA_PLATFORM="eglfs"
  fi
fi

if [[ "${QT_QPA_PLATFORM}" == "xcb" ]] && command -v ldconfig >/dev/null 2>&1; then
  if ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor.so.0'; then
    echo "Missing runtime dependency for Qt xcb platform plugin: libxcb-cursor0" >&2
    echo "Install it with: sudo apt install -y libxcb-cursor0" >&2
    exit 1
  fi
fi

exec "${PYTHON_BIN}" "${APP_DIR}/main.py" --config "${CONFIG_PATH}"
