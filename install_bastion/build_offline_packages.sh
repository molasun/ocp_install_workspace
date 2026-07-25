#!/bin/bash
#==============================================================================
# 使用 uv 解析依賴並下載離線 wheel，供 RHEL 9 離線環境安裝
#
# 前置：
#   - 已安裝 uv（開發環境使用 uv 管理套件）
#   - install_bastion/requirements.txt 已定義依賴
#
# 使用方式：
#   cd install_bastion
#   chmod +x build_offline_packages.sh
#   ./build_offline_packages.sh
#
# 輸出：
#   install_bastion/packages/requirements-frozen.txt  （完整的鎖定依賴清單）
#   install_bastion/packages/*.whl                    （Linux x86_64 wheel）
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGES_DIR="${SCRIPT_DIR}/packages"

echo "========================================"
echo "Build offline packages (uv)"
echo "========================================"
echo "Target:  RHEL 9 (x86_64-unknown-linux-gnu)"
echo "Python:  3.11"
echo "Output:  ${PACKAGES_DIR}"
echo ""

# Verify uv is available
if ! command -v uv &> /dev/null; then
    echo "ERROR: uv is not installed."
    echo "       Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

UV_VERSION=$(uv --version)
echo "uv:      ${UV_VERSION}"
echo ""

# Clean
rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

# === Step 1: Resolve full dependency tree with uv ===
#
#   uv pip compile reads requirements.txt, resolves ALL transitive
#   deps, and outputs a fully pinned requirements file.
#
#   --python-platform ensures platform-specific packages (like numpy)
#   are resolved for Linux, not the build machine's OS.
#
#   --only-binary :all: ensures only packages with pre-built wheels
#   are considered (offline host has no C compiler).
#
echo "[1/3] Resolving dependency tree for Linux x86_64..."

uv pip compile "${SCRIPT_DIR}/requirements.txt" \
    --python-platform x86_64-unknown-linux-gnu \
    --only-binary :all: \
    --output-file "${PACKAGES_DIR}/requirements-frozen.txt"

DEP_COUNT=$(grep -c '^\w' "${PACKAGES_DIR}/requirements-frozen.txt" || echo 0)
echo "      Resolved ${DEP_COUNT} packages"
echo ""

# === Step 2: Download wheels for Linux x86_64 ===
#   uv does not have a "pip download" equivalent.
#   Use pip download with the frozen list from uv (exact versions
#   already resolved — no dependency skipping issue).
echo "[2/3] Downloading wheels..."
echo "      (using pip download, uv has no equivalent)"

pip download \
    --platform manylinux2014_x86_64 \
    --python-version 311 \
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
