#!/bin/bash
#==============================================================================
# 將 install_bastion + install_tool/install_source 打包為離線部署用 tar
#
# 前置：已執行 install_bastion/build_offline_packages.sh 產生 packages/
#
# 使用方式（在專案根目錄執行）：
#   chmod +x pack.sh
#   ./pack.sh
#
# 輸出：
#   ocp_install_offline.tar.gz
#
# 離線主機部署：
#   tar -xzf ocp_install_offline.tar.gz -C ~
#   cd ~/install_bastion
#   ./install_on_host.sh
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

OUTPUT_FILE="ocp_install_offline.tar.gz"
INSTALL_SOURCE="install_tool/install_source"
INSTALL_BASTION="install_bastion"

echo "========================================"
echo "Pack offline deployment archive"
echo "========================================"
echo "Include: ${INSTALL_BASTION}/ (with cluster_config.json from install_tool/config/)"
echo "Include: ${INSTALL_SOURCE}/ (excluding mirror/mirror-cache)"
echo "Output: ${OUTPUT_FILE}"
echo ""

# Verify prerequisites
if [ ! -d "${INSTALL_BASTION}/packages" ] || [ -z "$(ls -A ${INSTALL_BASTION}/packages/*.whl 2>/dev/null)" ]; then
    echo "ERROR: ${INSTALL_BASTION}/packages/ has no .whl files"
    echo "       Please run: cd install_bastion && ./build_offline_packages.sh"
    exit 1
fi

if [ ! -d "${INSTALL_SOURCE}" ]; then
    echo "ERROR: ${INSTALL_SOURCE} does not exist"
    exit 1
fi

# Create temp directory (auto-cleaned on exit)
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

echo "[1/4] Copying ${INSTALL_BASTION}..."
cp -r "${INSTALL_BASTION}" "${TEMP_DIR}/"

# Clean dev artifacts
find "${TEMP_DIR}/${INSTALL_BASTION}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "${TEMP_DIR}/${INSTALL_BASTION}" -type f -name '*.pyc' -delete 2>/dev/null || true

echo "[2/4] Copying cluster_config.json..."
# 將 install_tool 端產生的 cluster_config.json 帶入 install_bastion 的 config/
if [ -f "install_tool/config/cluster_config.json" ]; then
    mkdir -p "${TEMP_DIR}/${INSTALL_BASTION}/config"
    cp install_tool/config/cluster_config.json "${TEMP_DIR}/${INSTALL_BASTION}/config/"
    echo "      install_tool/config/cluster_config.json → install_bastion/config/"
else
    echo "      WARNING: install_tool/config/cluster_config.json not found"
fi

echo "[3/4] Copying ${INSTALL_SOURCE} (excluding mirror/mirror-cache)..."
rsync -a --exclude 'mirror-cache/' --exclude 'mirror/' "${INSTALL_SOURCE}/" "${TEMP_DIR}/install_source/"

echo "[4/4] Creating tar..."
tar -czf "${OUTPUT_FILE}" -C "${TEMP_DIR}" install_bastion install_source

TAR_SIZE=$(du -h "${OUTPUT_FILE}" | cut -f1)

echo ""
echo "========================================"
echo "Done"
echo "========================================"
echo "File: ${OUTPUT_FILE}"
echo "Size: ${TAR_SIZE}"
echo ""
echo "Deploy on offline host:"
echo "  1. Copy ${OUTPUT_FILE} to the offline host"
echo "  2. tar -xzf ${OUTPUT_FILE} -C ~"
echo "  3. cd ~/install_bastion"
echo "  4. ./install_on_host.sh"
echo ""
