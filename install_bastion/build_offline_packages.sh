#!/bin/bash
#==============================================================================
# 使用 pip 解析並下載離線 wheel，供 RHEL 9 離線環境安裝
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

rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

# === Step 1: Resolve with pip ===
#   用 pip 解析和 freeze（同一 index，保證 resolve 和 download 一致）
echo "[1/3] Resolving dependencies..."

TMP_VENV=$(mktemp -d)
trap "rm -rf ${TMP_VENV}" EXIT

python3 -m venv "${TMP_VENV}"
"${TMP_VENV}/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"
"${TMP_VENV}/bin/pip" freeze --local > "${PACKAGES_DIR}/requirements-frozen.txt"

ST_VERSION=$(grep '^streamlit==' "${PACKAGES_DIR}/requirements-frozen.txt" || echo "streamlit")
DEP_COUNT=$(wc -l < "${PACKAGES_DIR}/requirements-frozen.txt")
echo "      ${ST_VERSION} + ${DEP_COUNT} transitive deps"
echo ""

# === Step 2: pip download the frozen list ===
#   建置機器 Python 版本可能與離線主機不同（如 3.9 vs 3.12）。
#   加上 --python-version + --only-binary 強制下載目標版本的 wheel。
echo "[2/3] Downloading wheels (target Python 3.12)..."

pip download \
    --python-version 3.12 \
    --only-binary=:all: \
    -r "${PACKAGES_DIR}/requirements-frozen.txt" \
    -d "${PACKAGES_DIR}"

FILE_COUNT=$(ls -1 "${PACKAGES_DIR}"/*.whl 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${PACKAGES_DIR}" 2>/dev/null | cut -f1)

echo ""
echo "[3/3] Downloading pip / setuptools / wheel (for offline venv bootstrap)..."
# vanilla RHEL 9 不包含 python3-pip RPM，離線 venv 內沒有 pip。
# 下載 pip/setuptools/wheel wheel + get-pip.py，供 install_on_host.sh 引導 pip。
pip download pip setuptools wheel -d "${PACKAGES_DIR}"
curl -sS https://bootstrap.pypa.io/get-pip.py -o "${PACKAGES_DIR}/get-pip.py"

echo "[4/4] Done — ${FILE_COUNT} wheels, ${TOTAL_SIZE}"
echo ""

echo "========================================"
echo "Deploy to offline host"
echo "========================================"
echo " 1. Copy install_bastion/ to the offline host"
echo " 2. cd ~/install_bastion"
echo " 3. ./install_on_host.sh"
echo ""
