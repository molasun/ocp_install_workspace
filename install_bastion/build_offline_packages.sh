#!/bin/bash
#==============================================================================
# 下載 streamlit 及其所有遞迴依賴的 Linux wheel，供離線環境安裝
#
# 使用方式（可在任何平台執行，Windows/macOS/WSL 皆可）：
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
echo "📦 下載離線套件"
echo "========================================"
echo "目標平台: manylinux2014_x86_64 (RHEL 9)"
echo "Python:    3.11 (cp311)"
echo "輸出目錄:  ${PACKAGES_DIR}"
echo ""

# 清理舊的 packages
rm -rf "${PACKAGES_DIR}"
mkdir -p "${PACKAGES_DIR}"

echo "📥 下載 streamlit 及所有遞迴依賴..."
echo "   (僅下載 binary wheel，跳過 source distribution)"
echo ""

pip download \
    --platform manylinux2014_x86_64 \
    --python-version 311 \
    --abi cp311 \
    --only-binary=:all: \
    -r "${SCRIPT_DIR}/requirements.txt" \
    -d "${PACKAGES_DIR}"

FILE_COUNT=$(ls -1 "${PACKAGES_DIR}"/*.whl 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${PACKAGES_DIR}" 2>/dev/null | cut -f1)

echo ""
echo "========================================"
echo "✅ 完成！"
echo "========================================"
echo "📦 檔案數量: ${FILE_COUNT}"
echo "📏 總大小:   ${TOTAL_SIZE}"
echo ""
echo "📋 部署步驟："
echo "   1. 將整個 install_bastion/ 目錄複製到離線主機"
echo "   2. 確保 config/ 下有 cluster_config.json"
echo "   3. 執行: ./install_on_host.sh"
echo ""
