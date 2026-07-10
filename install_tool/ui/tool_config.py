import streamlit as st
import json
import os
from datetime import datetime
import time
import re
from typing import Optional, Callable, Any

from src.config_manager import ConfigManager
from src.setup_wizard import SetupWizard
from src.registry_manager import RegistryManager


class SessionKeys:
    """Session State 鍵名常數"""
    PULL_SECRET_MERGED = 'pull_secret_merged'
    REGISTRY_LOGGED_IN = 'registry_logged_in'
    ENV_READY = 'env_ready'
    TOOLS_DOWNLOADED = 'tools_downloaded'
    CURRENT_VIEW = 'current_view'
    SSH_KEYGEN_DONE = 'ssh_keygen_done'
    SSH_PUBKEY = 'generated_ssh_pubkey'
    IMAGES_PREPARED = 'images_prepared'


class ToolConfigUI:
    """工具配置頁面 UI 類別"""
    
    # === 常數 ===
    CONFIG_FILE = 'tool_config.json'
    INDEX_FILE = 'operator_index.json'
    
    def __init__(self):
        """初始化 UI 類別"""
        self.current_dir = os.getcwd()
        self.config_dir = os.path.join(self.current_dir, 'config')
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 初始化後端組件
        self.config_manager = ConfigManager(self.CONFIG_FILE)
        self.wizard = SetupWizard(self.current_dir)
    
    # === 主渲染方法 ===
    
    def render(self) -> None:
        """渲染整個工具配置頁面"""
        st.title("1. 🔧 Tool Configuration & Environment Setup")
        st.markdown("配置需要下載的工具版本，並執行環境初始化。")
        
        config = self.config_manager.get_config()
        
        self._render_pull_secret_section()
        st.divider()
        self._render_ssh_keygen_section()
        st.divider()
        self._render_tool_config_section(config)
        self._render_operator_catalog_section(config)
        self._render_container_images_section(config)
        st.divider()
        self._render_next_button()
    
    # === Pull Secret 區塊 ===
    
    def _render_pull_secret_section(self) -> None:
        """渲染 Pull Secret 上傳區塊"""
        with st.expander("🔐 OpenShift Pull Secret Configuration", expanded=True):
            if st.session_state.get(SessionKeys.PULL_SECRET_MERGED, False):
                self._render_pull_secret_success()
                return
            
            self._render_pull_secret_instructions()
            pull_secret_json = self._get_pull_secret_input()
            
            if pull_secret_json:
                self._validate_and_apply_pull_secret(pull_secret_json)
    
    def _render_pull_secret_success(self) -> None:
        """渲染 Pull Secret 已配置狀態"""
        st.success("✅ Pull secret 已配置完成")
        if st.button("🔄 重新上傳"):
            st.session_state[SessionKeys.PULL_SECRET_MERGED] = False
            st.rerun()
    
    def _render_pull_secret_instructions(self) -> None:
        """渲染 Pull Secret 說明"""
        st.markdown("""
        請提供 OpenShift Pull Secret。
        從 [Red Hat Console](https://console.redhat.com/openshift/install/pull-secret) 下載。
        """)
    
    def _get_pull_secret_input(self) -> Optional[dict]:
        """取得 Pull Secret 輸入"""
        upload_method = st.radio(
            "選擇上傳方式",
            ["📋 貼上 JSON 內容", "📁 上傳 pull-secret.txt"],
            horizontal=True
        )
        
        if upload_method == "📋 貼上 JSON 內容":
            return self._get_pull_secret_from_text()
        else:
            return self._get_pull_secret_from_file()
    
    def _get_pull_secret_from_text(self) -> Optional[dict]:
        """從文字框取得 Pull Secret"""
        pull_secret_text = st.text_area(
            "Pull Secret (JSON)", height=200,
            placeholder='{"auths":{"cloud.openshift.com":{...},...}}',
            key="pull_secret_text"
        )
        if pull_secret_text:
            try:
                return json.loads(pull_secret_text)
            except json.JSONDecodeError:
                st.error("❌ 無效的 JSON 格式")
        return None
    
    def _get_pull_secret_from_file(self) -> Optional[dict]:
        """從上傳檔案取得 Pull Secret"""
        uploaded_file = st.file_uploader(
            "上傳 pull-secret.txt",
            type=["txt", "json"],
            key="pull_secret_file"
        )
        if uploaded_file:
            try:
                data = json.loads(uploaded_file.read().decode('utf-8'))
                st.success(f"✅ 已讀取: {uploaded_file.name}")
                return data
            except json.JSONDecodeError:
                st.error("❌ 無效的 JSON 格式")
        return None
    
    def _validate_and_apply_pull_secret(self, pull_secret_json: dict) -> None:
        """驗證並套用 Pull Secret"""
        if 'auths' not in pull_secret_json:
            st.error("❌ 缺少 'auths' 欄位")
            return
        
        registries = list(pull_secret_json['auths'].keys())
        required = ['quay.io', 'registry.redhat.io']
        missing = [r for r in required if r not in registries]
        
        st.info(f"📋 包含 {len(registries)} 個 registry 認證")
        
        if missing:
            st.error(f"❌ 缺少必要認證：{', '.join(missing)}")
            return
        
        st.success("✅ 包含 quay.io 和 registry.redhat.io 認證")
        
        if st.button("🔗 套用 Pull Secret", type="primary"):
            if self.wizard.apply_pull_secret(pull_secret_json):
                st.session_state[SessionKeys.PULL_SECRET_MERGED] = True
                st.session_state[SessionKeys.REGISTRY_LOGGED_IN] = True
                st.rerun()
            else:
                st.error("❌ 寫入失敗")
    
    # === SSH Key Generation 區塊 ===

    def _render_ssh_keygen_section(self) -> None:
        """渲染 SSH 金鑰生成區塊"""
        with st.expander("🔑 SSH Key Generation", expanded=True):
            existing_pubkey = self.wizard.get_ssh_pubkey()

            if existing_pubkey:
                st.session_state[SessionKeys.SSH_KEYGEN_DONE] = True
                st.session_state[SessionKeys.SSH_PUBKEY] = existing_pubkey

            if st.session_state.get(SessionKeys.SSH_KEYGEN_DONE, False):
                self._render_ssh_keygen_success(existing_pubkey)
                return

            self._render_ssh_keygen_instructions()

            if st.button("🔑 Generate SSH Key Pair", type="primary"):
                self._execute_ssh_keygen()

    def _render_ssh_keygen_success(self, pubkey_content: Optional[str]) -> None:
        """渲染 SSH 金鑰已存在的成功狀態"""
        st.success("✅ SSH 金鑰已就緒")

        key_path = os.path.join(self.wizard.install_source_dir, '.ssh', 'id_rsa')
        st.caption(f" Private key: `{key_path}`")

        if pubkey_content:
            with st.expander("📋 Public Key (id_rsa.pub)"):
                st.code(pubkey_content, language="text")

        if st.button("🔄 重新生成"):
            self._execute_ssh_keygen(force=True)

    def _render_ssh_keygen_instructions(self) -> None:
        """渲染 SSH 金鑰生成說明"""
        st.markdown("""
        生成 SSH 金鑰對，用於 OpenShift 安裝時的節點存取認證。

        - **演算法**: RSA 4096
        - **註解**: install-automation
        - **存放路徑**: `install_source/.ssh/id_rsa`
        - **Passphrase**: 無（自動化場景）

        生成後的公鑰將自動套用至步驟2 的 Cluster Config SSH Key 欄位。
        """)

    def _execute_ssh_keygen(self, force: bool = False) -> None:
        """執行 SSH 金鑰生成"""
        if force:
            ssh_dir = os.path.join(self.wizard.install_source_dir, '.ssh')
            for fname in ['id_rsa', 'id_rsa.pub']:
                fpath = os.path.join(ssh_dir, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)

        with st.spinner("正在生成 SSH 金鑰..."):
            success, _ = self.wizard.run_ssh_keygen()

        if success:
            pubkey = self.wizard.get_ssh_pubkey()
            st.session_state[SessionKeys.SSH_KEYGEN_DONE] = True
            st.session_state[SessionKeys.SSH_PUBKEY] = pubkey
            st.success("✅ SSH 金鑰已生成！")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ SSH 金鑰生成失敗，請檢查 ssh-keygen 是否可用")

    # === 工具配置表單 ===
    
    def _render_tool_config_section(self, config: dict) -> None:
        """渲染工具版本配置表單"""
        with st.form("tool_config_form"):
            st.subheader("Version Information")
            
            updated_config = self._render_version_form_fields(config)
            
            if st.form_submit_button("Save & Run Environment Setup"):
                self._execute_environment_setup(updated_config)
    
    def _render_version_form_fields(self, config: dict) -> dict:
        """渲染版本配置欄位"""
        col1, col2 = st.columns(2)
        
        with col1:
            config['version_info']['OCP_RELEASE'] = st.text_input(
                "OCP Release (e.g. 4.20.8)",
                value=config['version_info']['OCP_RELEASE']
            )
            config['version_info']['RHEL_VERSION'] = st.selectbox(
                "RHEL Version", ["rhel9", "rhel10"],
                index=0 if config['version_info']['RHEL_VERSION'] == 'rhel9' else 1
            )
        
        with col2:
            config['version_info']['ARCHITECTURE'] = st.selectbox(
                "Architecture", ["amd64", "arm64"],
                index=0 if config['version_info']['ARCHITECTURE'] == 'amd64' else 1
            )
            config['version_info']['HELM_VERSION'] = st.text_input(
                "Helm Version",
                value=config['version_info']['HELM_VERSION']
            )
            config['version_info']['MIRROR_REGISTRY_VERSION'] = st.text_input(
                "Mirror Registry Version",
                value=config['version_info']['MIRROR_REGISTRY_VERSION']
            )
        
        return config
    
    def _execute_environment_setup(self, config: dict) -> None:
        """執行環境初始化流程"""
        self.config_manager.save_config(config)
        st.success("配置已保存！開始執行環境初始化...")
        
        if not self._run_env_prep_step():
            return
        
        if not self._run_download_tools_step(config):
            return
        
        self._run_extract_binaries_step(config)
        st.success("✅ tool_config 配置完成！")
    
    def _run_env_prep_step(self) -> bool:
        """執行環境準備步驟"""
        with st.expander("Step 1: Environment Preparation", expanded=True):
            if self.wizard.run_env_prep():
                st.session_state[SessionKeys.ENV_READY] = True
                st.success("✅ env_prep 完成")
                return True
            else:
                st.error("❌ env_prep 失敗")
                st.stop()
                return False
    
    def _run_download_tools_step(self, config: dict) -> bool:
        """執行工具下載步驟"""
        with st.expander("Step 2: Download Tools", expanded=True):
            if not st.session_state.get(SessionKeys.ENV_READY):
                return False
            
            progress_bar = st.progress(0)
            success = self.wizard.run_get_tools(
                config,
                progress_callback=lambda p: progress_bar.progress(p)
            )
            
            if success:
                st.session_state[SessionKeys.TOOLS_DOWNLOADED] = True
                st.success("✅ get_tools 完成")
            else:
                st.error("❌ get_tools 失敗")
                st.stop()
            
            return success
    
    def _run_extract_binaries_step(self, config: dict) -> None:
        """執行二進位檔解壓步驟"""
        with st.expander("Step 3: Extract binary", expanded=True):
            if not st.session_state.get(SessionKeys.TOOLS_DOWNLOADED):
                return
            
            if self.wizard.run_untar_oc_mirror(config):
                st.success("✅ untar_oc_mirror 完成")
            else:
                st.error("❌ untar_oc_mirror 失敗")
            
            if self.wizard.run_untar_grpcurl(config):
                st.success("✅ untar_grpcurl 完成")
            else:
                st.error("❌ untar_grpcurl 失敗")
    
    # === Operator Catalog 區塊 ===
    
    def _render_operator_catalog_section(self, config: dict) -> None:
        """渲染 Operator Catalog 獲取區塊"""
        if not self._is_grpcurl_available():
            return
        
        with st.expander("Step 4: Operator Registry & Index", expanded=True):
            self._render_container_status()
            st.markdown("---")
            self._render_index_management(config)
    
    def _is_grpcurl_available(self) -> bool:
        """檢查 grpcurl 是否可用"""
        if not st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
            return False
        
        for path in [
            os.path.join(os.path.expanduser("~"), ".local/bin/grpcurl"),
            os.path.join(self.current_dir, "usr/bin/grpcurl")
        ]:
            if os.path.exists(path):
                return True
        
        st.warning("⚠️ grpcurl 未找到")
        return False
    
    def _render_container_status(self) -> None:
        """渲染容器狀態區塊"""
        st.subheader("🐳 Operator Registry 容器狀態")
        
        container_name = self._get_container_name()
        registry = self.wizard.registry
        is_running = registry.check_container_running(container_name)
        exists = registry.check_container_exists(container_name)
        
        col_status, col_action = st.columns([2, 1])
        
        with col_status:
            self._render_container_status_info(container_name, is_running, exists, registry)
        
        with col_action:
            self._render_container_action_button(container_name, is_running, registry)
    
    def _render_container_status_info(
        self, 
        name: str, 
        is_running: bool, 
        exists: bool, 
        registry: RegistryManager
    ) -> None:
        """渲染容器狀態資訊"""
        if is_running:
            st.success(f"✅ 容器運行中: `{name}`")
            with st.expander("📋 容器詳細資訊", expanded=False):
                details = registry.get_container_details(name)
                if details:
                    st.code(details, language="text")
                
                st.markdown("**最近日誌:**")
                logs = registry.get_container_logs(name)
                if logs:
                    st.code(logs[-1000:], language="text")
                else:
                    st.caption("(無日誌輸出)")
        elif exists:
            st.warning(f"⚠️ 容器已停止: `{name}`")
        else:
            st.info(f"📦 尚未啟動容器: `{name}`")
    
    def _render_container_action_button(
        self, 
        container_name: str, 
        is_running: bool, 
        registry: RegistryManager
    ) -> None:
        """渲染容器操作按鈕"""
        if is_running:
            if st.button("🛑 停止容器", key="stop_container_btn", type="secondary", use_container_width=True):
                with st.spinner("正在停止容器..."):
                    if registry.stop_operator_registry(container_name):
                        st.success(f"容器 {container_name} 已停止")
                    else:
                        st.error("停止容器失敗")
                    time.sleep(1)
                    st.rerun()
        else:
            if st.button("🚀 啟動容器", key="start_container_btn", type="primary", use_container_width=True):
                with st.spinner("正在啟動容器..."):
                    config = self.config_manager.get_config()
                    success, name, port = registry.start_operator_registry(config)
                    if success:
                        st.success(f"✅ 容器已啟動: `{name}` (port: {port})")
                    else:
                        st.error("❌ 容器啟動失敗")
                    time.sleep(1)
                    st.rerun()
    
    def _render_index_management(self, config: dict) -> None:
        """渲染 Operator Index 管理"""
        index_file = os.path.join(self.config_dir, self.INDEX_FILE)
        
        if os.path.exists(index_file):
            self._render_existing_index(index_file, config)
        else:
            self._render_fetch_new_index(config)
    
    def _render_existing_index(self, index_file: str, config: dict) -> None:
        """渲染已存在的索引"""
        try:
            with open(index_file, 'r') as f:
                index_data = json.load(f)
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.success(f"✅ Operator Index 就緒 ({len(index_data)} packages)")
            with col2:
                mtime = os.path.getmtime(index_file)
                st.caption(f"🕐 {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            with col3:
                if st.button("🔄 刷新", key="refresh_grpc_btn", use_container_width=True):
                    self._run_fetch_with_progress(config, "🔄 正在刷新 Operator Index...")
        except Exception as e:
            st.error(f"讀取快取失敗: {e}")
    
    def _render_fetch_new_index(self, config: dict) -> None:
        """渲染首次獲取索引"""
        st.info("📡 尚未獲取 Operator Index")
        st.markdown("""
        ### 🔄 獲取流程：
        1. 📦 確認 Local Registry 容器已啟動
        2. 📡 透過 gRPC 查詢 Operator 目錄
        3. 💾 儲存為 operator_index.json
        
        ⚠️ **注意：獲取完成後容器不會自動關閉，請手動關閉。**
        """)
        
        if st.button("🚀 開始獲取 Operator Index (gRPC)", type="primary", use_container_width=True):
            self._run_fetch_with_progress(config, "📡 正在獲取 Operator Index...")
    
    def _run_fetch_with_progress(self, config: dict, title: str) -> None:
        """執行查詢並顯示進度"""
        with st.status(title, expanded=True) as status_container:
            progress_bar = st.progress(0, "準備開始...")
            status_text = st.empty()
            log_container = st.container()
            all_logs = []
            
            def update_status(msg: str) -> None:
                all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                with log_container:
                    st.write(f"➤ {msg}")
                self._update_progress(msg, progress_bar, status_text)
            
            success = self.wizard.run_get_operator_catalog_via_grpc(
                config, status_callback=update_status
            )
            
            if success:
                self._handle_fetch_success(status_container, progress_bar, status_text, all_logs)
            else:
                self._handle_fetch_failure(status_container, progress_bar, status_text, all_logs)
    
    def _handle_fetch_success(
        self, 
        container: Any, 
        progress_bar: Any, 
        status_text: Any, 
        logs: list
    ) -> None:
        """處理查詢成功"""
        progress_bar.progress(100, "完成!")
        status_text.success("🎉 Operator Index 獲取完成!")
        container.update(label="✅ 完成!", state="complete", expanded=False)
        st.balloons()
        
        with st.expander("📋 執行日誌", expanded=False):
            st.code("\n".join(logs), language="text")
        
        time.sleep(2)
        st.rerun()
    
    def _handle_fetch_failure(
        self, 
        container: Any, 
        progress_bar: Any, 
        status_text: Any, 
        logs: list
    ) -> None:
        """處理查詢失敗"""
        progress_bar.empty()
        status_text.empty()
        container.update(label="❌ 失敗", state="error", expanded=True)
        st.error("❌ Operator Index 獲取失敗")
        
        with st.expander("📋 完整執行日誌 (用於除錯)", expanded=True):
            st.code("\n".join(logs), language="text")
        
        st.warning("""
        ### 💡 除錯建議：
        1. 確認容器是否正常運行
        2. 檢查 gRPC 埠：`grpcurl -plaintext 127.0.0.1:50051 list`
        3. 檢查容器日誌：`podman logs operator-registry-4.20`
        4. 確認 SELinux：`getenforce`（應為 Permissive）
        """)
    
    def _update_progress(self, msg: str, progress_bar: Any, status_text: Any) -> None:
        """更新進度條"""
        progress_rules = [
            ("初始化", 5, "初始化任務..."),
            ("grpcurl" in msg and "找到" in msg, 10, "工具就緒"),
            ("檢查鏡像", 15, "檢查鏡像..."),
            ("鏡像已存在" in msg or "鏡像就緒" in msg, 20, "鏡像就緒"),
            ("鏡像不存在" in msg or "開始拉取" in msg, 20, "拉取鏡像..."),
            ("鏡像拉取完成", 35, "鏡像拉取完成"),
            ("啟動" in msg and "容器" in msg, 40, "啟動容器..."),
            ("容器已啟動" in msg or "容器已在運行" in msg, 45, "容器已啟動"),
            ("查詢" in msg and "Packages" in msg, 60, "查詢 Packages..."),
            ("找到" in msg and "packages" in msg, 70, "獲取詳細資訊..."),
            ("operator_index.json" in msg or "已創建" in msg, 95, "儲存中..."),
            ("完成" in msg, 100, "完成!"),
        ]
        
        for rule in progress_rules:
            if isinstance(rule[0], bool):
                condition = rule[0]
            else:
                condition = rule[0] in msg
            
            if condition:
                progress_bar.progress(rule[1], rule[2])
                if "拉取鏡像" in msg:
                    status_text.info("📥 鏡像不存在，正在拉取... (可能需要 3-10 分鐘)")
                break
        
        # 特殊處理：百分比進度
        if "處理中" in msg:
            match = re.search(r'(\d+)/(\d+)', msg)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                pct = 70 + int((current / total) * 20)
                progress_bar.progress(pct, f"處理中... ({current}/{total})")
    
    # === Container Images 區塊 ===

    def _render_container_images_section(self, config: dict) -> None:
        """渲染離線容器映像檔準備區塊"""
        if not st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
            return

        with st.expander("📦 Container Images for Offline Use", expanded=True):
            arch = config.get('version_info', {}).get('ARCHITECTURE', 'amd64')

            # 掃描需要的映像檔
            if st.button("🔍 掃描 Mirror Registry 需要的映像檔", key="btn_scan_images"):
                with st.spinner("正在掃描 mirror-registry 二進位檔..."):
                    images = self.wizard.scan_mirror_registry_images(arch)
                    st.session_state['required_images'] = images
                    if images:
                        st.success(f"掃描到 {len(images)} 個映像檔")
                    else:
                        st.warning("未掃描到映像檔，請確認 mirror-registry tar 已下載")

            images = st.session_state.get('required_images', [])
            if not images:
                st.info("點擊上方按鈕掃描需要的容器映像檔")
                return

            # 顯示映像檔清單
            st.markdown("**需要的容器映像檔：**")
            for img in images:
                st.code(img, language="text")

            # 檢查已打包的 tar
            saved_tars = []
            for img in images:
                short_name = img.split('/')[-1].replace(':', '-')
                tar_path = os.path.join(self.wizard.install_source_dir, f"{short_name}.tar")
                if os.path.exists(tar_path) and os.path.getsize(tar_path) > 0:
                    size_mb = os.path.getsize(tar_path) / (1024 * 1024)
                    saved_tars.append((img, tar_path, f"{size_mb:.1f} MB"))

            if saved_tars:
                st.success(f"✅ 已打包 {len(saved_tars)}/{len(images)} 個映像檔")
                for img, path, size in saved_tars:
                    st.caption(f"  {img} → `{path}` ({size})")

            # 下載並打包缺失的映像檔
            saved_imgs = [t[0] for t in saved_tars]
            missing = [img for img in images if img not in saved_imgs]

            if missing:
                if st.button(f"📥 下載並打包 {len(missing)} 個映像檔", type="primary", key="btn_pull_images"):
                    all_success = True
                    for img in missing:
                        with st.spinner(f"下載 {img}..."):
                            success, msg = self.wizard.pull_and_save_image(img)
                        if success:
                            st.success(f"✅ {img}")
                        else:
                            st.error(f"❌ {msg}")
                            all_success = False
                    if all_success:
                        st.session_state[SessionKeys.IMAGES_PREPARED] = True
                    st.rerun()
            else:
                st.session_state[SessionKeys.IMAGES_PREPARED] = True
                st.success("🎉 所有映像檔已就緒！")

    def _render_next_button(self) -> None:
        """渲染下一步按鈕"""
        if st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
            st.divider()
            if st.button("➡️ Next: Cluster Config", use_container_width=True):
                st.session_state[SessionKeys.CURRENT_VIEW] = 'cluster_config'
                st.rerun()
    
    def _get_container_name(self) -> str:
        """取得容器名稱"""
        config = self.config_manager.get_config()
        v_info = config.get('version_info', {})
        ocp_release = v_info.get('OCP_RELEASE', RegistryManager.DEFAULT_OCP_RELEASE)
        match = re.match(r'(\d+\.\d+)', ocp_release)
        ocp_version = match.group(1) if match else RegistryManager.DEFAULT_OCP_VERSION
        return RegistryManager.CONTAINER_NAME_TEMPLATE.format(version=ocp_version)


# === 模組級函數（向後相容） ===

def show_tool_config_page():
    """渲染工具配置頁面（向後相容的入口函數）"""
    ui = ToolConfigUI()
    ui.render()


def render_next_button():
    """渲染下一步按鈕（向後相容）"""
    if st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
        st.divider()
        if st.button("➡️ Next: Cluster Config", use_container_width=True):
            st.session_state[SessionKeys.CURRENT_VIEW] = 'cluster_config'
            st.rerun()