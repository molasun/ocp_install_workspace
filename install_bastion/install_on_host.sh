#!/bin/bash
#==============================================================================
# 離線環境：建立 venv、安裝 streamlit、以 sudo 啟動應用
#
# 前置條件：
#   - packages/ 目錄內有 .whl 檔案（由 build_offline_packages.sh 產生）
#   - config/ 目錄內有 cluster_config.json
#   - install_source/ 內有 OCP 安裝工具包
#
# 使用方式：
#   cd install_bastion
#   chmod +x install_on_host.sh
#   ./install_on_host.sh
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "========================================"
echo "📦 install_bastion 離線部署"
echo "========================================"
echo ""

# === 步驟 1: 確認 packages/ 存在 ===
if [ ! -d "packages" ] || [ -z "$(ls -A packages/*.whl 2>/dev/null)" ]; then
    echo "❌ packages/ 目錄不存在或無 .whl 檔案"
    echo "   請先在連線環境執行 build_offline_packages.sh 產生套件"
    exit 1
fi

PACKAGE_COUNT=$(ls -1 packages/*.whl 2>/dev/null | wc -l)
echo "✅ [1/4] 找到 ${PACKAGE_COUNT} 個離線套件"
echo ""

# === 步驟 2: 建立 / 更新 venv ===
echo "📦 [2/4] 建立 Python venv..."

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✅ venv 已建立"
else
    echo "✅ venv 已存在，跳過"
fi

# 確保 venv 內有 pip
if [ ! -f ".venv/bin/pip" ]; then
    python3 -m ensurepip --upgrade 2>/dev/null || true
    .venv/bin/python3 -m ensurepip --upgrade 2>/dev/null || true
fi

echo ""

# === 步驟 3: 離線安裝套件 ===
echo "📥 [3/4] 離線安裝 streamlit 及依賴..."

.venv/bin/pip install --no-index --find-links ./packages streamlit

# 驗證
if ! .venv/bin/streamlit version > /dev/null 2>&1; then
    echo "❌ streamlit 安裝失敗"
    exit 1
fi

ST_VERSION=$(.venv/bin/streamlit version 2>&1 | head -1)
echo "✅ 安裝完成 (${ST_VERSION})"
echo ""

# === 步驟 4: 以 sudo 啟動 Streamlit ===
echo "🚀 [4/4] 啟動 Streamlit..."
echo ""

# 停止舊的 streamlit 進程
sudo pkill -f "streamlit run" 2>/dev/null || true
sleep 1

# 啟動（確保 firewall/selinux/systemctl 等指令有 root 權限）
sudo "${SCRIPT_DIR}/.venv/bin/streamlit" run \
    "${SCRIPT_DIR}/install_app.py" \
    --server.port 8501 \
    --server.headless true \
    --server.address 0.0.0.0 &

STREAMLIT_PID=$!

# 等待就緒
echo "⏳ 等待服務啟動..."
for i in $(seq 1 15); do
    if curl -sk http://localhost:8501/_stcore/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo ""
echo "========================================"
echo "✅ install_bastion 已啟動！"
echo "========================================"
echo "🌐 Web UI: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8501"
echo ""
echo "📋 停止服務:   sudo pkill -f 'streamlit run'"
echo "📋 查看進程:   ps aux | grep streamlit"
echo ""
