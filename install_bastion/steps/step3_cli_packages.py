import streamlit as st
import time
import os
import subprocess
from setup_manager import SetupManager
from managers.base_manager import BaseManager 


def render_step3_cli_packages():
    """步驟3: CLI、套件與 Mirror Registry 安裝"""
    st.header("📦 步驟3: CLI 工具、基礎套件與 Mirror Registry 安裝")
    
    # 直接從 session_state 取得所需資料（避免宣告未使用的變數）
    file_paths = st.session_state.get('file_paths', {})
    install_options = st.session_state.get('install_options', {})

    # 取得 home 目錄和 install_source 路徑
    home_dir = BaseManager._get_real_home()
    install_source_dir = BaseManager._get_install_source_dir()
    
    # === 檔案路徑配置 ===
    st.caption(f"📁 安裝來源目錄: `{install_source_dir}`")
    st.subheader("📁 安裝包路徑確認")
    st.markdown("請確認以下安裝包的路徑是否正確，必要時可修改：")
    
    col_path1, col_path2 = st.columns(2)
    
    with col_path1:
        ocp_install_dir = st.text_input(
            "OCP 安裝 CLI 路徑 (openshift-install)",
            value=file_paths.get('ocpInstallDir', os.path.join(install_source_dir, 'openshift-install-linux.tar.gz')),
            help="openshift-install 安裝包的 tar.gz 檔案路徑"
        )
        ocp_client_dir = st.text_input(
            "OCP 客戶端 CLI 路徑 (oc)",
            value=file_paths.get('ocpClientDir', os.path.join(install_source_dir, 'openshift-client-linux.tar.gz')),
            help="oc 客戶端的 tar.gz 檔案路徑"
        )
        
    with col_path2:
        mirror_registry_dir = st.text_input(
            "Mirror Registry 安裝包路徑",
            value=file_paths.get('mirrorRegistryDir', os.path.join(install_source_dir, 'mirror-registry.tar.gz')),
            help="mirror-registry 安裝包的 tar.gz 檔案路徑"
        )
    
    # Quay 配置（僅在需要安裝 Registry 時顯示）
    if install_options.get('registry_configure', False):
        st.markdown("**Quay Registry 配置**")
        col_quay1, col_quay2 = st.columns(2)
        with col_quay1:
            quay_root = st.text_input(
                "Quay 根目錄",
                value=file_paths.get('quayRoot', '/opt/quay')
            )
        with col_quay2:
            quay_storage = st.text_input(
                "Quay 儲存目錄",
                value=file_paths.get('quayStorage', '/opt/quay-storage')
            )
    else:
        quay_root = file_paths.get('quayRoot', '/opt/quay')
        quay_storage = file_paths.get('quayStorage', '/opt/quay-storage')
    
    st.markdown("---")
    
    # === 任務定義（結構化） ===
    st.subheader("📋 本步驟將執行的操作")
    
    # 定義所有可能的任務
    tasks_config = {
        'install_packages': {
            'icon': '📦',
            'name': '安裝基礎套件',
            'detail': 'net-tools, git, httpd',
            'method': 'install_packages',
            'always_run': True
        },
        'install_cli': {
            'icon': '🔧',
            'name': '安裝 CLI 工具',
            'detail': 'openshift-install, oc client',
            'method': 'install_cli',
            'always_run': True
        },
        'setup_registry': {
            'icon': '🏗️',
            'name': '安裝 Mirror Registry',
            'detail': 'Podman + Quay Registry',
            'method': 'setup_registry',
            'condition': 'registry_configure'
        }
    }
    
    # 收集需要執行的任務
    active_tasks = []
    for key, task_info in tasks_config.items():
        if task_info.get('always_run', False):
            active_tasks.append(task_info)
        elif install_options.get(task_info.get('condition', ''), False):
            active_tasks.append(task_info)
    
    # 顯示任務列表
    for task in active_tasks:
        st.markdown(f"{task['icon']} **{task['name']}** - {task['detail']}")
    
    # 檢查安裝包是否存在
    st.markdown("---")
    _check_installation_files(ocp_install_dir, ocp_client_dir, mirror_registry_dir, install_options)
    
    st.markdown("---")
    
    # === 步驟執行狀態追蹤 ===
    if 'step3_executed' not in st.session_state:
        st.session_state.step3_executed = False
        st.session_state.step3_results = {}
    
    # === 執行安裝 ===
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    
    with col_btn1:
        if not st.session_state.step3_executed:
            if st.button("🚀 開始安裝", type="primary"):
                # 更新檔案路徑到 session state
                _update_file_paths(ocp_install_dir, ocp_client_dir, mirror_registry_dir, quay_root, quay_storage)
                
                # 使用更新後的 config_params 初始化 manager
                manager = SetupManager(st.session_state.config_params)
                _execute_step3_tasks(manager, active_tasks)
                st.rerun()
    
    # === 顯示執行結果 ===
    if st.session_state.step3_executed:
        st.markdown("---")
        st.subheader("📊 執行結果")
        
        results = st.session_state.step3_results
        success_count = sum(1 for r in results.values() if r.get('success', False))
        total_count = len(results)
        
        # 顯示進度摘要
        col_prog1, col_prog2 = st.columns([1, 3])
        with col_prog1:
            st.metric("完成進度", f"{success_count}/{total_count}")
        
        all_success = success_count == total_count
        
        # 顯示每個步驟的詳細結果
        for method, result in results.items():
            task_name = method
            for task in active_tasks:
                if task['method'] == method:
                    task_name = f"{task['icon']} {task['name']}"
                    break
            
            if result.get('success', False):
                st.success(f"{task_name}: {result.get('message', '')}")
            else:
                st.error(f"{task_name}: {result.get('message', '')}")
        
        if all_success:
            st.success("🎉 所有套件和工具安裝成功！")
            
            # 顯示版本驗證
            _display_installation_verification()
            
            # 檢查是否需要鏡像同步
            if install_options.get('mirror_enable', False):
                st.info("💡 鏡像同步選項已啟用，將在步驟4進行鏡像同步。")
            elif install_options.get('registry_configure', False):
                st.info("💡 Mirror Registry 已安裝，可在步驟4選擇進行鏡像同步。")
        else:
            st.warning("⚠️ 部分安裝失敗，請檢查上方錯誤訊息。")
    
    # === 導航按鈕 ===
    st.markdown("---")
    col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 2])
    
    with col_nav1:
        if st.button("⬅️ 返回步驟2", use_container_width=True):
            st.session_state.current_step = 2
            st.rerun()
    
    with col_nav2:
        if st.session_state.step3_executed:
            results = st.session_state.step3_results
            all_success = all(r.get('success', False) for r in results.values())
            
            if all_success:
                btn_label = "➡️ 進入步驟4"
                btn_type = "primary"
            else:
                btn_label = "➡️ 跳過失敗，進入步驟4"
                btn_type = "secondary"
            
            if st.button(btn_label, type=btn_type, use_container_width=True):
                st.session_state.step3_complete = True
                st.session_state.current_step = 4
                st.rerun()
    
    # === 重試按鈕 ===
    if st.session_state.step3_executed:
        results = st.session_state.step3_results
        has_failures = any(not r.get('success', False) for r in results.values())
        
        if has_failures:
            with col_nav3:
                if st.button("🔄 重新執行所有步驟", use_container_width=True):
                    st.session_state.step3_executed = False
                    st.session_state.step3_results = {}
                    st.rerun()


def _check_installation_files(ocp_install_dir: str, ocp_client_dir: str, mirror_registry_dir: str, install_options: dict):
    """檢查安裝包檔案是否存在"""
    st.subheader("🔍 安裝包檔案檢查")
    
    files_to_check = [
        ("openshift-install", ocp_install_dir),
        ("oc client", ocp_client_dir),
    ]
    
    if install_options.get('registry_configure', False):
        files_to_check.append(("mirror-registry", mirror_registry_dir))
    
    for name, path in files_to_check:
        if os.path.exists(path):
            size_bytes = os.path.getsize(path)
            if size_bytes > 1024 * 1024:
                size_str = f"{size_bytes / (1024*1024):.1f} MB"
            elif size_bytes > 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} bytes"
            st.success(f"✅ {name}: {path} ({size_str})")
        else:
            st.warning(f"⚠️ {name}: {path} - 檔案不存在，請確認路徑")


def _update_file_paths(ocp_install_dir: str, ocp_client_dir: str, mirror_registry_dir: str, quay_root: str, quay_storage: str):
    """更新檔案路徑到 session state"""
    new_paths = {
        'ocpInstallDir': ocp_install_dir,
        'ocpClientDir': ocp_client_dir,
        'mirrorRegistryDir': mirror_registry_dir,
        'quayRoot': quay_root,
        'quayStorage': quay_storage,
    }
    st.session_state.file_paths.update(new_paths)
    st.session_state.config_params.update(new_paths)


def _execute_step3_tasks(manager: SetupManager, active_tasks: list):
    """執行步驟3的所有任務"""
    st.session_state.step3_executed = True
    st.session_state.step3_results = {}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(active_tasks)
    
    for i, task in enumerate(active_tasks):
        task_name = f"{task['icon']} {task['name']}"
        method = task['method']
        
        status_text.text(f"正在執行: {task_name}...")
        
        with st.expander(f"{task_name} - {task['detail']}", expanded=True):
            st.info(f"⏳ 執行中...")
            
            # 執行步驟
            success, message = manager.execute_step(method)
            
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
                
                # 提供重試和跳過選項
                col_r, col_s = st.columns(2)
                with col_r:
                    if st.button("🔄 重試此步驟", key=f"retry_{method}"):
                        retry_success, retry_message = manager.execute_step(method)
                        if retry_success:
                            st.success(f"✅ {retry_message}")
                            success = True
                            message = retry_message
                        else:
                            st.error(f"❌ 重試仍失敗: {retry_message}")
                        st.rerun()
                with col_s:
                    if st.button("⏭️ 跳過此步驟", key=f"skip_{method}"):
                        st.warning(f"⏭️ 已跳過: {task_name}")
                        st.session_state.step3_results[method] = {
                            'success': False,
                            'message': f'已跳過: {message}',
                            'skipped': True
                        }
                        continue
            
            # 記錄結果
            st.session_state.step3_results[method] = {
                'success': success,
                'message': message
            }
        
        progress_bar.progress((i + 1) / total)
        time.sleep(0.3)
    
    status_text.text("✅ CLI 與套件安裝程序完成！")


def _display_installation_verification():
    """顯示安裝後的版本驗證"""
    st.markdown("---")
    st.subheader("🔍 安裝驗證")
    
    checks = []
    
    # 檢查 openshift-install
    try:
        result = subprocess.run(
            ['openshift-install', 'version'], 
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            checks.append(f"✅ openshift-install: {result.stdout.strip()}")
        else:
            checks.append("⚠️ openshift-install: 無法取得版本")
    except FileNotFoundError:
        checks.append("❌ openshift-install: 未安裝")
    except Exception:
        checks.append("⚠️ openshift-install: 檢查失敗")
    
    # 檢查 oc
    try:
        result = subprocess.run(
            ['oc', 'version', '--client'], 
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split('\n')[0] if result.stdout else "unknown"
            checks.append(f"✅ oc client: {version_line}")
        else:
            checks.append("⚠️ oc client: 無法取得版本")
    except FileNotFoundError:
        checks.append("❌ oc client: 未安裝")
    except Exception:
        checks.append("⚠️ oc client: 檢查失敗")
    
    # 檢查 podman
    try:
        result = subprocess.run(
            ['podman', '--version'], 
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            checks.append(f"✅ podman: {result.stdout.strip()}")
        else:
            checks.append("⚠️ podman: 無法取得版本")
    except FileNotFoundError:
        checks.append("⚠️ podman: 未安裝（如未選擇安裝 Registry 則正常）")
    except Exception:
        checks.append("⚠️ podman: 檢查失敗")
    
    for check in checks:
        st.text(check)