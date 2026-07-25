#!/bin/bash
#==============================================================================
# 離線環境部署 install_bastion
#
# 使用 uv 建立 venv + 離線安裝（速度快），無 uv 時自動退回到 pip
#
# 前置：
#   - packages/ 目錄內有 .whl + requirements-frozen.txt
#   - config/cluster_config.json 已就緒
#   - install_source/ 已就緒
#
# 使用方式：
#   cd install_bastion
#   ./install_on_host.sh
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "========================================"
echo "install_bastion offline deploy"
echo "========================================"
echo ""

# === Step 1: Verify packages ===
if [ ! -f "packages/requirements-frozen.txt" ]; then
    echo "ERROR: packages/requirements-frozen.txt not found"
    echo "       Run build_offline_packages.sh in the online environment first"
    exit 1
fi

if [ -z "$(ls -A packages/*.whl 2>/dev/null)" ]; then
    echo "ERROR: packages/ has no .whl files"
    exit 1
fi

WHL_COUNT=$(ls -1 packages/*.whl 2>/dev/null | wc -l)
echo "[1/4] Found ${WHL_COUNT} offline wheels"
echo ""

# === Step 2: Create / update venv ===
echo "[2/4] Setting up venv..."

# 清理舊 venv（上次 sudo streamlit 可能讓目錄被 root 擁有）
if [ -d ".venv" ]; then
    for f in ".venv/bin" ".venv/lib" ".venv/include"; do
        if [ -e "$f" ]; then
            rm -rf "$f" 2>/dev/null || sudo rm -rf "$f"
        fi
    done
    rm -rf ".venv" 2>/dev/null || sudo rm -rf ".venv"
    echo "      Cleaned old venv"
fi

if command -v uv &> /dev/null; then
    echo "      Using uv to create venv"
    uv venv .venv --python 3.12 2>/dev/null || uv venv .venv
else
    echo "      Using python3 -m venv (uv not found)"
    python3 -m venv .venv
fi

echo ""

# === Step 3: Offline install ===
echo "[3/4] Installing packages..."

if command -v uv &> /dev/null; then
    echo "      uv pip install --no-index..."
    uv pip install \
        --no-index \
        --find-links ./packages \
        -r packages/requirements-frozen.txt
else
    echo "      pip install --no-index... (uv not found)"
    .venv/bin/pip install \
        --no-index \
        --find-links ./packages \
        -r packages/requirements-frozen.txt
fi

# Verify
if ! .venv/bin/streamlit version > /dev/null 2>&1; then
    echo "ERROR: streamlit install failed"
    exit 1
fi

ST_VERSION=$(.venv/bin/streamlit version 2>&1 | head -1)
echo "      ${ST_VERSION}"
echo ""

# === Step 4: Start Streamlit ===
echo "[4/4] Starting Streamlit..."

# Stop old processes
sudo pkill -f "streamlit run" 2>/dev/null || true
sleep 1

# Start with sudo (needed for firewall/selinux/systemctl)
sudo "${SCRIPT_DIR}/.venv/bin/streamlit" run \
    "${SCRIPT_DIR}/install_app.py" \
    --server.port 8501 \
    --server.headless true \
    --server.address 0.0.0.0 &

# Wait for ready — check port listening (more reliable than health endpoint)
echo "      Waiting for service..."
for i in $(seq 1 15); do
    if ss -tlnp 2>/dev/null | grep -q ':8501' || \
       netstat -tlnp 2>/dev/null | grep -q ':8501'; then
        break
    fi
    sleep 1
done

# Trigger initial connection to complete startup
curl -sk http://localhost:8501 > /dev/null 2>&1 &

echo ""
echo "========================================"
echo "install_bastion is running"
echo "========================================"
echo " Web UI:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8501"
echo ""
echo " Stop:    sudo pkill -f 'streamlit run'"
echo " Status:  ps aux | grep streamlit"
echo ""
