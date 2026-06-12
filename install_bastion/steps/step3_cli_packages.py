import streamlit as st
import time
import os
import subprocess
from setup_manager import SetupManager
from managers.base_manager import BaseManager 

def _get_cluster_version_info():
    """從 session_state 取得 OCP_RELEASE"""
    config_params = st.session_state.get('config_params', {})
    v_info = config_params.get('version_info', {})
    return v_info.get('OCP_RELEASE', '4.20.8')

def _build_tar_filename(tar_type: str, arch: str, rhel: str, ocp_release: str) -> str:
    """
    根據使用者輸入的參數動態構建 tar 檔名
    
    Args:
        tar_type: 'openshift-install', 'openshift-client', 'mirror-registry', 'oc-mirror'
        arch: 架構 (amd64, arm64)
        rhel: RHEL 版本 (rhel9, rhel10)
        ocp_release: OCP 版本 (4.20.8)
    
    Returns:
        完整的 tar 檔名
    """
    filenames = {
        'openshift-install': f"openshift-install-{rhel}-{arch}.tar.gz",
        'openshift-client': f"openshift-client-linux-{arch}-{rhel}-{ocp_release}.tar.gz",
        'mirror-registry': f"mirror-registry-{arch}.tar.gz",
        'oc-mirror': f"oc-mirror.{rhel}.tar.gz",
    }
    return filenames.get(tar_type, f"{tar_type}.tar.gz")

def render_step3_cli_packages():
    """步驟3: CLI、套件與 Mirror Registry 安裝"""
    st.header("📦 步驟3: CLI 工具、基礎套件與 Mirror Registry 安裝")
    
    file_paths = st.session_state.get('file_paths', {})
    install_options = st.session_state.get('install_options', {})

    ocp_release = _get_cluster_version_info()

    install_source_dir = BaseManager._get_install_source_dir()

    # 如果 file_paths 中的路徑指向 /root，更新為正確路徑
    for key in ['ocpInstallDir', 'ocpClientDir', 'mirrorRegistryDir', 'ocmirrorSource']:
        old_path = file_paths.get(key, '')
        if '/root/install_source' in old_path:
            filename = os.path.basename(old_path)
            file_paths[key] = os.path.join(install_source_dir, filename)

    # === 架構與 RHEL 版本選擇 ===
    st.subheader("🔧 安裝參數設定")
    st.markdown("請選擇架構和 RHEL 版本，將用於匹配正確的安裝包檔名。")
    
    # 從 session_state 取得已儲存的選擇，或使用預設值
    if 'step3_arch' not in st.session_state:
        st.session_state.step3_arch = 'amd64'
    if 'step3_rhel' not in st.session_state:
        st.session_state.step3_rhel = 'rhel9'
    
    col_arch, col_rhel, col_ocp = st.columns(3)
    with col_arch:
        arch = st.selectbox(
            "Architecture",
            ["amd64", "arm64"],
            index=0 if st.session_state.step3_arch == 'amd64' else 1,
            key="step3_arch_select"
        )
        st.session_state.step3_arch = arch
    with col_rhel:
        rhel = st.selectbox(
            "RHEL Version",
            ["rhel9", "rhel10"],
            index=0 if st.session_state.step3_rhel == 'rhel9' else 1,
            key="step3_rhel_select"
        )
        st.session_state.step3_rhel = rhel
    with col_ocp:
        st.text_input("OCP Release", value=ocp_release, disabled=True, key="step3_ocp_display")

    # === 檔案路徑配置 ===
    st.caption(f"📁 安裝來源目錄: `{install_source_dir}`")
    st.subheader("📁 安裝包路徑確認")
    st.markdown("請確認以下安裝包的路徑是否正確，必要時可修改：")

    default_install_tar = _build_tar_filename('openshift-install', arch, rhel, ocp_release)
    default_client_tar = _build_tar_filename('openshift-client', arch, rhel, ocp_release)
    default_mirror_tar = _build_tar_filename('mirror-registry', arch, rhel, ocp_release)

    col_path1, col_path2 = st.columns(2)
    
    with col_path1:
        ocp_install_dir = st.text_input(
            "OCP 安裝 CLI 路徑 (openshift-install)",
            value=file_paths.get('ocpInstallDir', os.path.join(install_source_dir, default_install_tar)),
            help=f"預設檔名: {default_install_tar}"
        )
        ocp_client_dir = st.text_input(
            "OCP 客戶端 CLI 路徑 (oc)",
            value=file_paths.get('ocpClientDir', os.path.join(install_source_dir, default_client_tar)),
            help=f"預設檔名: {default_client_tar}"
        )
        
    with col_path2:
        mirror_registry_dir = st.text_input(
            "Mirror Registry 安裝包路徑",
            value=file_paths.get('mirrorRegistryDir', os.path.join(install_source_dir, default_mirror_tar)),
            help=f"預設檔名: {default_mirror_tar}"
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
    
    # === 任務定義 ===
    st.subheader("📋 本步驟將執行的操作")
    
    # 定義所有可能的任務
    tasks_config = {
        'install_packages': {
            'icon': '📦', 'name': '安裝基礎套件',
            'detail': 'net-tools, git, httpd',
            'method': 'install_packages', 'always_run': True
        },
        'install_cli': {
            'icon': '🔧', 'name': '安裝 CLI 工具',
            'detail': 'openshift-install, oc client',
            'method': 'install_cli', 'always_run': True
        },
        'setup_registry': {
            'icon': '🏗️', 'name': '安裝 Mirror Registry',
            'detail': 'Podman + Quay Registry',
            'method': 'setup_registry', 'condition': 'registry_configure'
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
                # 保存 arch 和 rhel 到 config_params
                st.session_state.config_params['ARCHITECTURE'] = arch
                st.session_state.config_params['RHEL_VERSION'] = rhel
                
                _update_file_paths(ocp_install_dir, ocp_client_dir, mirror_registry_dir, quay_root, quay_storage)
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
        
        col_prog1, col_prog2 = st.columns([1, 3])
        with col_prog1:
            st.metric("完成進度", f"{success_count}/{total_count}")
        
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
        
        if success_count == total_count:
            st.success("🎉 所有套件和工具安裝成功！")
            _display_installation_verification()
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
            btn_label = "➡️ 進入步驟4" if all_success else "➡️ 跳過失敗，進入步驟4"
            btn_type = "primary" if all_success else "secondary"
            if st.button(btn_label, type=btn_type, use_container_width=True):
                st.session_state.step3_complete = True
                st.session_state.current_step = 4
                st.rerun()
    
    if st.session_state.step3_executed:
        results = st.session_state.step3_results
        if any(not r.get('success', False) for r in results.values()):
            with col_nav3:
                if st.button("🔄 重新執行所有步驟", use_container_width=True):
                    st.session_state.step3_executed = False
                    st.session_state.step3_results = {}
                    st.rerun()


def _check_installation_files(ocp_install_dir, ocp_client_dir, mirror_registry_dir, install_options):
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
            size_str = f"{size_bytes / (1024*1024):.1f} MB" if size_bytes > 1024*1024 else f"{size_bytes / 1024:.1f} KB"
            st.success(f"✅ {name}: {path} ({size_str})")
        else:
            st.warning(f"⚠️ {name}: {path} - 檔案不存在，請確認路徑")


def _update_file_paths(ocp_install_dir, ocp_client_dir, mirror_registry_dir, quay_root, quay_storage):
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


def _execute_step3_tasks(manager, active_tasks):
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
            st.info("⏳ 執行中...")
            success, message = manager.execute_step(method)
            
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
                col_r, col_s = st.columns(2)
                with col_r:
                    if st.button("🔄 重試此步驟", key=f"retry_{method}"):
                        retry_success, retry_message = manager.execute_step(method)
                        if retry_success:
                            st.success(f"✅ {retry_message}")
                            success, message = True, retry_message
                        else:
                            st.error(f"❌ 重試仍失敗: {retry_message}")
                        st.rerun()
                with col_s:
                    if st.button("⏭️ 跳過此步驟", key=f"skip_{method}"):
                        st.warning(f"⏭️ 已跳過: {task_name}")
                        st.session_state.step3_results[method] = {
                            'success': False, 'message': f'已跳過: {message}', 'skipped': True
                        }
                        continue
            
            st.session_state.step3_results[method] = {'success': success, 'message': message}
        
        progress_bar.progress((i + 1) / total)
        time.sleep(0.3)
    
    status_text.text("✅ CLI 與套件安裝程序完成！")


def _display_installation_verification():
    """顯示安裝後的版本驗證"""
    st.markdown("---")
    st.subheader("🔍 安裝驗證")
    
    checks = []
    for cmd, label in [
        (['openshift-install', 'version'], 'openshift-install'),
        (['oc', 'version', '--client'], 'oc client'),
        (['podman', '--version'], 'podman'),
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_line = result.stdout.strip().split('\n')[0] if label == 'oc client' else result.stdout.strip()
                checks.append(f"✅ {label}: {version_line}")
            else:
                checks.append(f"⚠️ {label}: 無法取得版本")
        except FileNotFoundError:
            checks.append(f"❌ {label}: 未安裝")
        except Exception:
            checks.append(f"⚠️ {label}: 檢查失敗")
    
    for check in checks:
        st.text(check)