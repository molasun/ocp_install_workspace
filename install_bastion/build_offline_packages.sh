#!/bin/bash
#==============================================================================
# 使用 uv 解析並安裝依賴，再匯出清單供 pip 下載離線 wheel
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
echo "Output:  ${PACKAGES_DIR}"
echo ""

if ! command -v uv &> /dev/null; then
    echo "ERROR: uv is not installed."
    exit 1
fi

echo "uv:      $(uv --version)"
echo ""

rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

# === Step 1: Resolve by actually INSTALLING (not just compiling) ===
#
#   uv pip compile 使用快取的索引，曾解析出 PyPI 不存在的 altair 6.2.2。
#   改用實際 uv pip install → uv pip freeze：
#     — uv 必須從 PyPI 真實下載套件，保證解析的版本確實存在
#
echo "[1/3] Resolving dependencies via uv pip install..."

TMP_VENV=$(mktemp -d)
trap "rm -rf ${TMP_VENV}" EXIT

uv venv "${TMP_VENV}" --seed
uv pip install \
    --reinstall \
    --no-deps \
    -r "${SCRIPT_DIR}/requirements.txt" \
    --python "${TMP_VENV}/bin/python3"

uv pip install \
    -r "${SCRIPT_DIR}/requirements.txt" \
    --python "${TMP_VENV}/bin/python3"

uv pip freeze \
    --python "${TMP_VENV}/bin/python3" \
    > "${PACKAGES_DIR}/requirements-frozen.txt"

ST_VERSION=$(grep '^streamlit==' "${PACKAGES_DIR}/requirements-frozen.txt" || echo "streamlit")
DEP_COUNT=$(wc -l < "${PACKAGES_DIR}/requirements-frozen.txt")
echo "      ${ST_VERSION} + ${DEP_COUNT} transitive deps"
echo ""

# === Step 2: pip download the exact frozen list ===
echo "[2/3] Downloading wheels..."

pip download \
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
