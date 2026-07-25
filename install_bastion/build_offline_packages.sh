#!/bin/bash
#==============================================================================
# 使用 uv 解析依賴並下載離線 wheel，供 RHEL 9 離線環境安裝
#
# 前提：建置機器與目標離線主機皆為 RHEL 9 x86_64
#
# 使用方式：
#   cd install_bastion
#   chmod +x build_offline_packages.sh
#   ./build_offline_packages.sh
#
# 輸出：
#   install_bastion/packages/requirements-frozen.txt
#   install_bastion/packages/*.whl
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGES_DIR="${SCRIPT_DIR}/packages"

echo "========================================"
echo "Build offline packages"
echo "========================================"
echo "System:  $(uname -m), $(. /etc/os-release 2>/dev/null && echo ${PRETTY_NAME:-RHEL})"
echo "Output:  ${PACKAGES_DIR}"
echo ""

# Verify uv is available
if ! command -v uv &> /dev/null; then
    echo "ERROR: uv is not installed."
    echo "       Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "uv:      $(uv --version)"
echo ""

# Clean
rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

# === Step 1: uv pip compile ===
#   建置機器就是目標 RHEL 9，不需要 --python-platform 跨平台標記。
#   uv 直接使用本地 Python 和平台解析，解析結果與離線主機一致。
echo "[1/3] Resolving dependency tree..."

uv pip compile "${SCRIPT_DIR}/requirements.txt" \
    --only-binary :all: \
    --output-file "${PACKAGES_DIR}/requirements-frozen.txt"

DEP_COUNT=$(grep -c '^\w' "${PACKAGES_DIR}/requirements-frozen.txt" || echo 0)
echo "      Resolved ${DEP_COUNT} packages"
echo ""

# === Step 2: pip download ===
#   下載當前機器架構對應的 wheel。建置機器 = 目標機器，
#   不需要 --platform 標記。
echo "[2/3] Downloading wheels..."

pip download \
    --only-binary=:all: \
    -r "${PACKAGES_DIR}/requirements-frozen.txt" \
    -d "${PACKAGES_DIR}"

FILE_COUNT=$(ls -1 "${PACKAGES_DIR}"/*.whl 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${PACKAGES_DIR}" 2>/dev/null | cut -f1)

echo ""
echo "[3/3] Done — ${FILE_COUNT} wheels, ${TOTAL_SIZE}"
echo ""

echo "========================================"
echo "Deploy to offline host"
echo "========================================"
echo " 1. Copy install_bastion/ to the offline host"
echo " 2. cd ~/install_bastion"
echo " 3. ./install_on_host.sh"
echo ""
