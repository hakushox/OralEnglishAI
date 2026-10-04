#!/usr/bin/env bash
# 本机打包的快捷入口，真正的逻辑在 build_web.py（Windows 和 CI 也用那一份）。
#
#   ./build_web.sh          只打包
#   ./build_web.sh --app    打包并写进 SpeakNaturalLauncher.app
set -euo pipefail
cd "$(dirname "$0")"
exec venv/bin/python build_web.py "$@"
