#!/bin/bash
#==============================================================================
# 下載 streamlit 及其所有遞迴依賴的 Linux wheel，供離線環境安裝
#
# 使用方式（需在 Linux 或 WSL 執行）：
#   cd install_bastion
#   chmod +x build_offline_packages.sh
#   ./build_offline_packages.sh
#
# 輸出：
#   install_bastion/packages/*.whl
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGES_DIR="${SCRIPT_DIR}/packages"

echo "========================================"
echo "Download offline packages"
echo "========================================"
echo "Target platform: manylinux2014_x86_64 (RHEL 9)"
echo "Target Python:   3.11 (cp311)"
echo "Output: ${PACKAGES_DIR}"
echo ""

# Clean old packages
rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

# Step 1: Resolve ALL transitive dependencies in a temp venv
#   pip download --platform does not reliably resolve transitive deps
#   (e.g. numpy is missed for streamlit). Run a native install first to
#   get the complete dependency list, then download those exact packages.
echo "[1/3] Resolving full dependency tree..."

TMP_VENV=$(mktemp -d)
trap "rm -rf ${TMP_VENV}" EXIT

python3 -m venv "${TMP_VENV}"
"${TMP_VENV}/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"
"${TMP_VENV}/bin/pip" freeze --local > "${PACKAGES_DIR}/requirements-frozen.txt"

DEP_COUNT=$(wc -l < "${PACKAGES_DIR}/requirements-frozen.txt")
echo "       Resolved ${DEP_COUNT} packages (streamlit + all transitive deps)"
echo ""

# Step 2: Download exact resolved packages for the target Linux platform
echo "[2/3] Downloading for manylinux2014_x86_64 / cp311..."

pip download \
    --platform manylinux2014_x86_64 \
    --python-version 311 \
    --abi cp311 \
    --only-binary=:all: \
    -r "${PACKAGES_DIR}/requirements-frozen.txt" \
    -d "${PACKAGES_DIR}"

# Clean up the frozen list (it's already captured in the wheels)
rm -f "${PACKAGES_DIR}/requirements-frozen.txt"

FILE_COUNT=$(ls -1 "${PACKAGES_DIR}"/*.whl 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${PACKAGES_DIR}" 2>/dev/null | cut -f1)

echo ""
echo "[3/3] Done. ${FILE_COUNT} wheels, ${TOTAL_SIZE}"
echo ""
echo "========================================"
echo "Deploy"
echo "========================================"
echo " 1. Copy install_bastion/ to the offline host"
echo " 2. Ensure config/cluster_config.json is in place"
echo " 3. Run: ./install_on_host.sh"
echo ""
