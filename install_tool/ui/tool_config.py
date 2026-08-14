import streamlit as st
import json
import os
from datetime import datetime
import time
import re
from typing import Optional, Callable, Any

from i18n import t
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
    SELECTED_INDEXES = 'selected_indexes'


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
        st.title(t('tool.title'))
        st.markdown(t('tool.subtitle'))
        
        config = self.config_manager.get_config()
        
        self._render_pull_secret_section()
        st.divider()
        self._render_ssh_keygen_section()
        st.divider()
        self._render_tool_config_section(config)
        self._render_operator_catalog_section(config)
        st.divider()
        self._render_next_button()
    
    # === Pull Secret 區塊 ===
    
    def _render_pull_secret_section(self) -> None:
        """渲染 Pull Secret 上傳區塊"""
        with st.expander(t('tool.pull_secret.title'), expanded=True):
            if st.session_state.get(SessionKeys.PULL_SECRET_MERGED, False):
                self._render_pull_secret_success()
                return
            
            self._render_pull_secret_instructions()
            pull_secret_json = self._get_pull_secret_input()
            
            if pull_secret_json:
                self._validate_and_apply_pull_secret(pull_secret_json)
    
    def _render_pull_secret_success(self) -> None:
        """渲染 Pull Secret 已配置狀態"""
        st.success(t('tool.pull_secret.success'))
        if st.button(t('tool.pull_secret.reupload')):
            st.session_state[SessionKeys.PULL_SECRET_MERGED] = False
            st.rerun()
    
    def _render_pull_secret_instructions(self) -> None:
        """渲染 Pull Secret 說明"""
        st.markdown(t('tool.pull_secret.instructions'))
    
    def _get_pull_secret_input(self) -> Optional[dict]:
        """取得 Pull Secret 輸入"""
        paste_label = t('tool.pull_secret.paste_json')
        upload_label = t('tool.pull_secret.upload_file')
        upload_method = st.radio(
            t('tool.pull_secret.upload_method'),
            [paste_label, upload_label],
            horizontal=True
        )
        
        if upload_method == paste_label:
            return self._get_pull_secret_from_text()
        else:
            return self._get_pull_secret_from_file()
    
    def _get_pull_secret_from_text(self) -> Optional[dict]:
        """從文字框取得 Pull Secret"""
        pull_secret_text = st.text_area(
            t('tool.pull_secret.json_label'), height=200,
            placeholder='{"auths":{"cloud.openshift.com":{...},...}}',
            key="pull_secret_text"
        )
        if pull_secret_text:
            try:
                return json.loads(pull_secret_text)
            except json.JSONDecodeError:
                st.error(t('tool.pull_secret.invalid_json'))
        return None
    
    def _get_pull_secret_from_file(self) -> Optional[dict]:
        """從上傳檔案取得 Pull Secret"""
        uploaded_file = st.file_uploader(
            t('tool.pull_secret.file_label'),
            type=["txt", "json"],
            key="pull_secret_file"
        )
        if uploaded_file:
            try:
                data = json.loads(uploaded_file.read().decode('utf-8'))
                st.success(t('tool.pull_secret.file_read', name=uploaded_file.name))
                return data
            except json.JSONDecodeError:
                st.error(t('tool.pull_secret.invalid_json'))
        return None
    
    def _validate_and_apply_pull_secret(self, pull_secret_json: dict) -> None:
        """驗證並套用 Pull Secret"""
        if 'auths' not in pull_secret_json:
            st.error(t('tool.pull_secret.missing_auths'))
            return
        
        registries = list(pull_secret_json['auths'].keys())
        required = ['quay.io', 'registry.redhat.io']
        missing = [r for r in required if r not in registries]
        
        st.info(t('tool.pull_secret.registry_count', count=len(registries)))
        
        if missing:
            st.error(t('tool.pull_secret.missing_creds', missing=', '.join(missing)))
            return
        
        st.success(t('tool.pull_secret.has_creds'))
        
        if st.button(t('tool.pull_secret.apply'), type="primary"):
            if self.wizard.apply_pull_secret(pull_secret_json):
                st.session_state[SessionKeys.PULL_SECRET_MERGED] = True
                st.session_state[SessionKeys.REGISTRY_LOGGED_IN] = True
                st.rerun()
            else:
                st.error(t('tool.pull_secret.write_failed'))
    
    # === SSH Key Generation 區塊 ===

    def _render_ssh_keygen_section(self) -> None:
        """渲染 SSH 金鑰生成區塊"""
        with st.expander(t('tool.ssh.title'), expanded=True):
            existing_pubkey = self.wizard.get_ssh_pubkey()

            if existing_pubkey:
                st.session_state[SessionKeys.SSH_KEYGEN_DONE] = True
                st.session_state[SessionKeys.SSH_PUBKEY] = existing_pubkey

            if st.session_state.get(SessionKeys.SSH_KEYGEN_DONE, False):
                self._render_ssh_keygen_success(existing_pubkey)
                return

            self._render_ssh_keygen_instructions()

            if st.button(t('tool.ssh.generate'), type="primary"):
                self._execute_ssh_keygen()

    def _render_ssh_keygen_success(self, pubkey_content: Optional[str]) -> None:
        """渲染 SSH 金鑰已存在的成功狀態"""
        st.success(t('tool.ssh.ready'))

        key_path = os.path.join(self.wizard.install_source_dir, '.ssh', 'id_rsa')
        st.caption(t('tool.ssh.private_key', path=key_path))

        if pubkey_content:
            with st.expander(t('tool.ssh.pubkey_preview')):
                st.code(pubkey_content, language="text")

        if st.button(t('tool.ssh.regenerate')):
            self._execute_ssh_keygen(force=True)

    def _render_ssh_keygen_instructions(self) -> None:
        """渲染 SSH 金鑰生成說明"""
        st.markdown(t('tool.ssh.instructions'))

    def _execute_ssh_keygen(self, force: bool = False) -> None:
        """執行 SSH 金鑰生成"""
        if force:
            ssh_dir = os.path.join(self.wizard.install_source_dir, '.ssh')
            for fname in ['id_rsa', 'id_rsa.pub']:
                fpath = os.path.join(ssh_dir, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)

        with st.spinner(t('tool.ssh.generating')):
            success, _ = self.wizard.run_ssh_keygen()

        if success:
            pubkey = self.wizard.get_ssh_pubkey()
            st.session_state[SessionKeys.SSH_KEYGEN_DONE] = True
            st.session_state[SessionKeys.SSH_PUBKEY] = pubkey
            st.success(t('tool.ssh.generated'))
            time.sleep(1)
            st.rerun()
        else:
            st.error(t('tool.ssh.generate_failed'))

    # === 工具配置表單 ===
    
    def _render_tool_config_section(self, config: dict) -> None:
        """渲染工具版本配置表單"""
        with st.form("tool_config_form"):
            st.subheader(t('tool.version.title'))
            
            updated_config = self._render_version_form_fields(config)
            
            if st.form_submit_button(t('tool.version.save_run')):
                self._execute_environment_setup(updated_config)
    
    def _render_version_form_fields(self, config: dict) -> dict:
        """渲染版本配置欄位"""
        col1, col2 = st.columns(2)
        
        with col1:
            config['version_info']['OCP_RELEASE'] = st.text_input(
                t('tool.version.ocp_release'),
                value=config['version_info']['OCP_RELEASE']
            )
            config['version_info']['RHEL_VERSION'] = st.selectbox(
                t('tool.version.rhel'), ["rhel9", "rhel10"],
                index=0 if config['version_info']['RHEL_VERSION'] == 'rhel9' else 1
            )
        
        with col2:
            config['version_info']['ARCHITECTURE'] = st.selectbox(
                t('tool.version.arch'), ["amd64", "arm64"],
                index=0 if config['version_info']['ARCHITECTURE'] == 'amd64' else 1
            )
            config['version_info']['HELM_VERSION'] = st.text_input(
                t('tool.version.helm'),
                value=config['version_info']['HELM_VERSION']
            )
            config['version_info']['MIRROR_REGISTRY_VERSION'] = st.text_input(
                t('tool.version.mirror_registry'),
                value=config['version_info']['MIRROR_REGISTRY_VERSION']
            )
        
        return config
    
    def _execute_environment_setup(self, config: dict) -> None:
        """執行環境初始化流程"""
        self.config_manager.save_config(config)
        st.success(t('tool.env.config_saved'))
        
        # release 變更提示：將清理並重新下載 openshift-install / openshift-client / oc-mirror
        new_release = config.get('version_info', {}).get('OCP_RELEASE', '')
        old_release = self.wizard.check_release_changed(new_release)
        if old_release:
            st.warning(t('tool.env.release_changed', old=old_release, new=new_release))
        
        if not self._run_env_prep_step():
            return
        
        if not self._run_download_tools_step(config):
            return
        
        self._run_extract_binaries_step(config)
        st.success(t('tool.env.complete'))
    
    def _run_env_prep_step(self) -> bool:
        """執行環境準備步驟"""
        with st.expander(t('tool.env.step1_title'), expanded=True):
            if self.wizard.run_env_prep():
                st.session_state[SessionKeys.ENV_READY] = True
                st.success(t('tool.env.step1_success'))
                return True
            else:
                st.error(t('tool.env.step1_failed'))
                st.stop()
                return False
    
    def _run_download_tools_step(self, config: dict) -> bool:
        """執行工具下載步驟"""
        with st.expander(t('tool.env.step2_title'), expanded=True):
            if not st.session_state.get(SessionKeys.ENV_READY):
                return False
            
            progress_bar = st.progress(0)
            success = self.wizard.run_get_tools(
                config,
                progress_callback=lambda p: progress_bar.progress(p)
            )
            
            if success:
                st.session_state[SessionKeys.TOOLS_DOWNLOADED] = True
                st.success(t('tool.env.step2_success'))
            else:
                st.error(t('tool.env.step2_failed'))
                st.stop()
            
            return success
    
    def _run_extract_binaries_step(self, config: dict) -> None:
        """執行二進位檔解壓步驟"""
        with st.expander(t('tool.env.step3_title'), expanded=True):
            if not st.session_state.get(SessionKeys.TOOLS_DOWNLOADED):
                return
            
            if self.wizard.run_untar_oc_mirror(config):
                st.success(t('tool.env.untar_mirror_success'))
            else:
                st.error(t('tool.env.untar_mirror_failed'))
            
            if self.wizard.run_untar_grpcurl(config):
                st.success(t('tool.env.untar_grpcurl_success'))
            else:
                st.error(t('tool.env.untar_grpcurl_failed'))
    
    # === Operator Catalog 區塊 ===
    
    def _render_operator_catalog_section(self, config: dict) -> None:
        """渲染 Operator Catalog 獲取區塊"""
        if not self._is_grpcurl_available():
            return
        
        with st.expander(t('tool.catalog.title'), expanded=True):
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
        
        st.warning(t('tool.catalog.grpcurl_not_found'))
        return False
    
    def _render_container_status(self) -> None:
        """渲染容器狀態區塊（遍歷所有 index type）"""
        st.subheader(t('tool.catalog.container_status'))
        
        config = self.config_manager.get_config()
        registry = self.wizard.registry
        
        for index_type, index_info in RegistryManager.INDEX_TYPES.items():
            container_name = self._get_container_name(index_type)
            is_running = registry.check_container_running(container_name)
            exists = registry.check_container_exists(container_name)
            
            with st.expander(f"{index_info['label']} (`{container_name}`)", expanded=False):
                col_status, col_action = st.columns([2, 1])
                with col_status:
                    self._render_container_status_info(container_name, is_running, exists, registry)
                with col_action:
                    self._render_container_action_button(container_name, is_running, registry, index_type, config)
    
    def _render_container_status_info(
        self, 
        name: str, 
        is_running: bool, 
        exists: bool, 
        registry: RegistryManager
    ) -> None:
        """渲染容器狀態資訊"""
        if is_running:
            st.success(t('tool.catalog.container_running', name=name))
            with st.expander(t('tool.catalog.container_details'), expanded=False):
                details = registry.get_container_details(name)
                if details:
                    st.code(details, language="text")
                
                st.markdown(t('tool.catalog.recent_logs'))
                logs = registry.get_container_logs(name)
                if logs:
                    st.code(logs[-1000:], language="text")
                else:
                    st.caption(t('tool.catalog.no_logs'))
        elif exists:
            st.warning(t('tool.catalog.container_stopped', name=name))
        else:
            st.info(t('tool.catalog.container_not_started', name=name))
    
    def _render_container_action_button(
        self, 
        container_name: str, 
        is_running: bool, 
        registry: RegistryManager,
        index_type: str = 'redhat',
        config: dict = None
    ) -> None:
        """渲染容器操作按鈕"""
        if is_running:
            if st.button(t('tool.catalog.stop'), key=f"stop_container_btn_{index_type}", type="secondary", use_container_width=True):
                with st.spinner(t('tool.catalog.stopping')):
                    if registry.stop_operator_registry(container_name):
                        st.success(t('tool.catalog.stopped', name=container_name))
                    else:
                        st.error(t('tool.catalog.stop_failed'))
                    time.sleep(1)
                    st.rerun()
        else:
            # marketplace 自 OCP 4.22 停止發布：禁用啟動按鈕
            deprecated = (
                index_type == 'marketplace'
                and RegistryManager.is_marketplace_deprecated(
                    config if config is not None else self.config_manager.get_config()
                )
            )
            if deprecated:
                st.warning(t('tool.catalog.marketplace_deprecated'))
                st.button(
                    t('tool.catalog.start'),
                    key=f"start_container_btn_{index_type}",
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                )
                return
            
            if st.button(t('tool.catalog.start'), key=f"start_container_btn_{index_type}", type="primary", use_container_width=True):
                with st.spinner(t('tool.catalog.starting')):
                    if config is None:
                        config = self.config_manager.get_config()
                    
                    # 捕獲啟動過程中的所有狀態訊息（含錯誤）
                    status_messages = []
                    def capture_status(msg):
                        status_messages.append(msg)
                    
                    success, name, port = registry.start_operator_registry(
                        config, status_callback=capture_status, index_type=index_type
                    )
                    if success:
                        st.success(t('tool.catalog.started', name=name, port=port))
                    else:
                        # 顯示最後幾條狀態訊息作為錯誤診斷
                        st.error(t('tool.catalog.start_failed'))
                        if status_messages:
                            with st.expander(t('tool.catalog.start_error_detail'), expanded=True):
                                for msg in status_messages[-10:]:
                                    st.text(msg)
                    time.sleep(1)
                    st.rerun()
    
    def _render_index_management(self, config: dict) -> None:
        """渲染 Operator Index 管理"""
        # 顯示 index 勾選區塊
        selected_indexes = self._render_index_selection()
        
        index_file = os.path.join(self.config_dir, self.INDEX_FILE)
        
        if os.path.exists(index_file):
            self._render_existing_index(index_file, config, selected_indexes)
        else:
            self._render_fetch_new_index(config, selected_indexes)
    
    def _render_index_selection(self) -> list:
        """渲染 Operator Index 勾選區塊"""
        # 初始化 session state
        if SessionKeys.SELECTED_INDEXES not in st.session_state:
            st.session_state[SessionKeys.SELECTED_INDEXES] = ['redhat']
        
        config = self.config_manager.get_config()
        st.markdown(f"**{t('tool.catalog.select_indexes')}**")
        
        cols = st.columns(4)
        index_keys = list(RegistryManager.INDEX_TYPES.keys())
        
        for i, idx_type in enumerate(index_keys):
            idx_info = RegistryManager.INDEX_TYPES[idx_type]
            deprecated = (
                idx_type == 'marketplace'
                and RegistryManager.is_marketplace_deprecated(config)
            )
            with cols[i]:
                # marketplace 自 OCP 4.22 停止發布：強制取消勾選並禁用
                if deprecated:
                    if idx_type in st.session_state[SessionKeys.SELECTED_INDEXES]:
                        st.session_state[SessionKeys.SELECTED_INDEXES].remove(idx_type)
                    st.checkbox(
                        idx_info['label'],
                        value=False,
                        key=f"idx_chk_{idx_type}",
                        disabled=True,
                    )
                    st.caption(t('tool.catalog.marketplace_deprecated'))
                    continue
                
                is_checked = idx_type in st.session_state[SessionKeys.SELECTED_INDEXES]
                if st.checkbox(
                    idx_info['label'],
                    value=is_checked,
                    key=f"idx_chk_{idx_type}"
                ):
                    if idx_type not in st.session_state[SessionKeys.SELECTED_INDEXES]:
                        st.session_state[SessionKeys.SELECTED_INDEXES].append(idx_type)
                else:
                    if idx_type in st.session_state[SessionKeys.SELECTED_INDEXES]:
                        st.session_state[SessionKeys.SELECTED_INDEXES].remove(idx_type)
        
        return st.session_state[SessionKeys.SELECTED_INDEXES]
    
    def _render_existing_index(self, index_file: str, config: dict, selected_indexes: list) -> None:
        """渲染已存在的索引"""
        try:
            with open(index_file, 'r') as f:
                index_data = json.load(f)
            
            # 統計各 index 的 package 數量
            total_count = 0
            index_details = []
            for idx_type, idx_info in RegistryManager.INDEX_TYPES.items():
                packages = index_data.get(idx_type, [])
                count = len(packages)
                total_count += count
                has_data = count > 0
                is_selected = idx_type in selected_indexes
                status_icon = "✅" if has_data else "⬜"
                sel_icon = "🔹" if is_selected else ""
                index_details.append(f"{status_icon} {sel_icon} {idx_info['label']}: {count}")
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.success(t('tool.catalog.index_ready', count=total_count))
                for detail in index_details:
                    st.caption(detail)
            with col2:
                mtime = os.path.getmtime(index_file)
                st.caption(f"🕐 {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            with col3:
                if st.button(t('tool.catalog.refresh'), key="refresh_grpc_btn", use_container_width=True):
                    if not selected_indexes:
                        st.warning(t('tool.catalog.no_index_selected'))
                        return
                    self._run_fetch_with_progress(config, t('tool.catalog.refreshing'), selected_indexes)
        except Exception as e:
            st.error(t('tool.catalog.read_cache_failed', error=e))
    
    def _render_fetch_new_index(self, config: dict, selected_indexes: list) -> None:
        """渲染首次獲取索引"""
        st.info(t('tool.catalog.not_fetched'))
        st.markdown(t('tool.catalog.fetch_flow'))
        
        if st.button(t('tool.catalog.fetch_start'), type="primary", use_container_width=True):
            if not selected_indexes:
                st.warning(t('tool.catalog.no_index_selected'))
                return
            self._run_fetch_with_progress(config, t('tool.catalog.fetching'), selected_indexes)
    
    def _run_fetch_with_progress(self, config: dict, title: str, selected_indexes: list) -> None:
        """執行查詢並顯示進度"""
        with st.status(title, expanded=True) as status_container:
            progress_bar = st.progress(0, t('tool.catalog.preparing'))
            status_text = st.empty()
            log_container = st.container()
            all_logs = []
            
            def update_status(msg: str) -> None:
                all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                with log_container:
                    st.write(f"➤ {msg}")
                self._update_progress(msg, progress_bar, status_text)
            
            success = self.wizard.run_get_operator_catalog_via_grpc(
                config, status_callback=update_status, selected_indexes=selected_indexes
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
        progress_bar.progress(100, t('tool.catalog.done'))
        status_text.success(t('tool.catalog.fetch_complete'))
        container.update(label=t('tool.catalog.done'), state="complete", expanded=False)
        st.balloons()
        
        with st.expander(t('tool.catalog.execution_log'), expanded=False):
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
        container.update(label=t('tool.catalog.failed'), state="error", expanded=True)
        st.error(t('tool.catalog.fetch_failed'))
        
        with st.expander(t('tool.catalog.debug_log'), expanded=True):
            st.code("\n".join(logs), language="text")
        
        st.warning(t('tool.catalog.debug_tips'))
    
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
                    status_text.info(t('tool.catalog.pulling_image'))
                break
        
        # 特殊處理：百分比進度
        if "處理中" in msg:
            match = re.search(r'(\d+)/(\d+)', msg)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                pct = 70 + int((current / total) * 20)
                progress_bar.progress(pct, t('tool.catalog.processing', current=current, total=total))
    
    def _render_next_button(self) -> None:
        """渲染下一步按鈕"""
        if st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
            st.divider()
            if st.button(t('tool.next_cluster'), use_container_width=True):
                st.session_state[SessionKeys.CURRENT_VIEW] = 'cluster_config'
                st.rerun()
    
    def _get_container_name(self, index_type: str = 'redhat') -> str:
        """取得容器名稱"""
        config = self.config_manager.get_config()
        v_info = config.get('version_info', {})
        ocp_release = v_info.get('OCP_RELEASE', RegistryManager.DEFAULT_OCP_RELEASE)
        match = re.match(r'(\d+\.\d+)', ocp_release)
        ocp_version = match.group(1) if match else RegistryManager.DEFAULT_OCP_VERSION
        return RegistryManager.CONTAINER_NAME_TEMPLATE.format(index_type=index_type, version=ocp_version)


# === 模組級函數（向後相容） ===

def show_tool_config_page():
    """渲染工具配置頁面（向後相容的入口函數）"""
    ui = ToolConfigUI()
    ui.render()


def render_next_button():
    """渲染下一步按鈕（向後相容）"""
    if st.session_state.get(SessionKeys.TOOLS_DOWNLOADED, False):
        st.divider()
        if st.button(t('tool.next_cluster'), use_container_width=True):
            st.session_state[SessionKeys.CURRENT_VIEW] = 'cluster_config'
            st.rerun()
