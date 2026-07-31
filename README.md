# ocp_install_workspace ( OCP 離線安裝部署標準作業程序 )

## 1. 目的

本程序說明如何於**連線環境**中準備 OCP 離線安裝所需之工具、設定檔與套件，並於**離線環境（RHEL 9）** 中部署安裝操作介面 `install_bastion`。

---

## 2. 系統架構與版本資訊

### 2.1 架構示意


### 2.2 版本要求
| 元件 | 版本 / 工具 |
|------|------------|
| Python | 3.12 |
| 套件管理 | uv（建議）或 pip |
| 主要套件 | streamlit, pyyaml |
| 目標系統 | RHEL 9 x86_64（離線主機） |

---

## 3. 準備階段（連線環境）

> **執行位置**：具網路連線之建置主機

### 3.1 安裝 uv（選擇性）
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3.2 建立 Python 虛擬環境
```bash
uv venv --python 3.12
# 或
python3 -m venv .venv
```

### 3.3 安裝必要套件
```bash
uv pip install streamlit pyyaml
# 或
pip install streamlit pyyaml
```

### 3.4 產生離線安裝所需檔案

#### 步驟 1：執行 prep_app.py 產生設定檔
> **⚠️ 必須在 `install_tool` 目錄下執行**，否則無法正確產出路徑與設定檔。

```bash
cd install_tool
streamlit run prep_app.py
```
- 產出檔案：
  - `install_tool/install_source/ocp/install-config.yaml`
  - `install_tool/install_source/ocp/agent-config.yaml`
  - `install_tool/install_source/mirror/imageset-config.yaml`
  - `install_tool/install_source/*.tar.gz`（OCP 工具包）

#### 步驟 2：下載 Python 離線套件
```bash
cd install_bastion
./build_offline_packages.sh
```
- 輸出：`packages/*.whl` 及 `packages/requirements-frozen.txt`

### 3.5 打包離線部署檔案
```bash
cd ..
./pack.sh
```
- 輸出：`ocp_install_offline.tar.gz`
- 包含：`install_bastion/` 全部、`install_source/`（排除 `mirror/`、`mirror-cache/`）
- **`mirror/` 因體積過大不納入打包**，需手動搬移到離線環境（見 3.6）

### 3.6 離線部署必備檔案檢查清單

> 以下檔案需**手動複製**到離線主機。

| # | 檔案 / 目錄 | 說明 | 傳輸方式 |
|---|------------|------|---------|
| 1 | `ocp_install_offline.tar.gz` | 部署主程式包（pack.sh 產出） | USB / 網路 |
| 2 | `install_tool/install_source/mirror/` | **鏡像同步目錄**（* 整包複製） | USB / 網路 |

`mirror/` 目錄內容包含：

```
install_tool/install_source/mirror/
  ├── imageset-config.yaml     # oc-mirror 設定檔
  └── ...                      # mirror 檔案
```

**離線主機上的預期目錄結構：**

```
~/
├── install_bastion/           # 來自 ocp_install_offline.tar.gz
│   ├── install_on_host.sh
│   ├── packages/
│   └── ...
├── install_source/            # 來自 ocp_install_offline.tar.gz
│   ├── mirror/                # ← 手動複製！
│   │   ├── imageset-config.yaml
│   │   └── *.tar.gz
│   └── ocp/
│       ├── install-config.yaml
│       └── agent-config.yaml
└── ocp_install_offline.tar.gz
```

---

## 4. 部署階段（離線環境）

> **執行位置**：目標 RHEL 9 離線主機

### 4.1 解壓縮部署檔案
```bash
tar -xzf ocp_install_offline.tar.gz -C ~
```

### 4.2 執行部署腳本
```bash
cd ~/install_bastion
./install_on_host.sh
```
- 若無執行權限，請先執行 `chmod +x install_on_host.sh`
- 腳本會自動：
  1. 驗證離線套件
  2. 建立 Python 虛擬環境（.venv）
  3. 以離線方式安裝所有 wheel
  4. 啟動 Streamlit 服務（Port 8501）

### 4.3 連線操作介面
- 瀏覽器開啟：`http://{主機IP}:8501`
- 可取得本機 IP：
  ```bash
  hostname -I | awk '{print $1}'
  ```

---

## 5. 服務管理

| 操作 | 指令 |
|------|------|
| 查看服務狀態 | `ps aux \| grep streamlit` |
| 停止服務 | `sudo pkill -f 'streamlit run'` |
| 重新啟動 | 重新執行 `./install_on_host.sh` |

---

## 6. 附錄：腳本說明

### 6.1 `build_offline_packages.sh`
- 用途：於連線環境下載所有相依套件為 `.whl`
- 輸入：`install_bastion/requirements.txt`
- 輸出：`install_bastion/packages/*.whl` + `requirements-frozen.txt`
- 特點：
  - 目前強制指定 Python 3.12 版本
  - 僅下載 binary wheel（`--only-binary=:all:`）

### 6.2 `pack.sh`
- 用途：將 `install_bastion` 與 `install_source` 打包為 `ocp_install_offline.tar.gz`
- 排除：`mirror/` `mirror-cache/`
- 前置條件：需先執行 `build_offline_packages.sh` 產生離線套件

### 6.3 `install_on_host.sh`
- 用途：於離線主機完成安裝並啟動服務
- 行為：
  - 優先使用 `uv`，若無則退回到 `pip`
  - 自動清理舊的 `.venv`（含 sudo 權限問題）
  - 以 `sudo` 啟動 Streamlit（避開權限與防火牆問題）
  - 檢查 Port 8501 是否監聽，確認服務啟動成功

---

## 7. 注意事項

1. **`prep_app.py` 必須在 `install_tool` 目錄下執行**，否則設定檔路徑會錯誤。
2. **`mirror/` 目錄必須手動複製到離線主機**（`pack.sh` 因體積過大將其排除，見 3.6 檢查清單）。
3. 離線環境的套件 **必須同為 RHEL 9**，以確保套件相容性。
4. 若 `.venv` 目錄因先前執行 `sudo` 而權限錯亂，腳本會自動以 `sudo rm -rf` 清理。
5. 若需變更 Streamlit Port，請修改 `install_on_host.sh` 中的 `--server.port` 參數。
6. 若有防火牆，請開放 8501 Port 或調整 SELinux 規則。

---
