import streamlit as st
import time
import os
import subprocess
from i18n import t
from managers.setup_manager import SetupManager
from managers.base_manager import BaseManager 

def _get_version_info():
    """從 session_state 取得完整的 version_info"""
    config_params = st.session_state.get('config_params', {})
    v_info = config_params.get('versionInfo', {})
    return {
        'arch': v_info.get('architecture', 'amd64'),
        'rhel': v_info.get('rhelVersion', 'rhel9'),
        'ocp_release': v_info.get('ocpRelease', '4.20.8'),
        'ocp_version': v_info.get('ocpVersion', '4.20'),
        'helm_version': v_info.get('helmVersion', ''),
        'mirror_registry_version': v_info.get('mirrorRegistryVersion', ''),
    }

def _build_tar_filename(tar_type: str, arch: str, rhel: str, ocp_release: str) -> str:
    """根據參數動態構建 tar 檔名"""
    filenames = {
        'openshift-install': f"openshift-install-{rhel}-{arch}.tar.gz",
        'openshift-client': f"openshift-client-linux-{arch}-{rhel}-{ocp_release}.tar.gz",
        'mirror-registry': f"mirror-registry-{arch}.tar.gz",
        'oc-mirror': f"oc-mirror.{rhel}.tar.gz",
    }
    return filenames.get(tar_type, f"{tar_type}.tar.gz")

def _check_file_exists(install_source_dir: str, filename: str) -> tuple:
    """
    檢查檔案是否存在，回傳 (exists: bool, full_path: str, size_str: str)
    """
    full_path = os.path.join(install_source_dir, filename)
    if os.path.exists(full_path):
        size_bytes = os.path.getsize(full_path)
        if size_bytes > 1024 * 1024:
            size_str = f"{size_bytes / (1024*1024):.1f} MB"
        elif size_bytes > 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes} bytes"
        return True, full_path, size_str
    return False, full_path, ""

def render_step3_cli_packages():
    """步驟3: CLI、套件與 Mirror Registry 安裝"""
    st.header(t('step3.header'))
    
    file_paths = st.session_state.get('file_paths', {})
    install_options = st.session_state.get('install_options', {})

    info = _get_version_info()
    arch = info['arch']
    rhel = info['rhel']
    ocp_release = info['ocp_release']
    ocp_version = info['ocp_version']

    install_source_dir = BaseManager._get_install_source_dir()

    st.subheader(t('step3.params_title'))
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.text_input("OCP Version", value=ocp_version, disabled=True, key="disp_ocp_ver")
    with col2:
        st.text_input("OCP Release", value=ocp_release, disabled=True, key="disp_ocp_rel")
    with col3:
        st.text_input("Architecture", value=arch, disabled=True, key="disp_arch")
    with col4:
        st.text_input("RHEL Version", value=rhel, disabled=True, key="disp_rhel")
    
    st.caption(t('step3.source_dir', dir=install_source_dir))

    st.markdown("---")
    st.subheader(t('step3.file_check'))
    
    tar_types = {
        'openshift-install': t('step3.tar_install'),
        'openshift-client': t('step3.tar_client'),
        'oc-mirror': t('step3.tar_mirror'),
        'mirror-registry': t('step3.tar_registry'),
    }

    file_status = {}  # 儲存每個檔案的狀態
    all_files_ok = True

    for tar_type, label in tar_types.items():
        # mirror-registry 只在需要時檢查
        if tar_type == 'mirror-registry' and not install_options.get('registry_configure', False):
            continue
        
        filename = _build_tar_filename(tar_type, arch, rhel, ocp_release)
        exists, full_path, size_str = _check_file_exists(install_source_dir, filename)
        
        file_status[tar_type] = {
            'filename': filename,
            'full_path': full_path,
            'exists': exists,
            'size_str': size_str,
        }
        
        if exists:
            st.success(f"✅ **{label}**: `{filename}` ({size_str})")
        else:
            st.error(f"❌ **{label}**: `{filename}` - {t('step3.file_not_found')}")
            all_files_ok = False
    
    # 如果所有檔案都存在，顯示摘要
    if all_files_ok:
        st.success(t('step3.all_ready'))

    st.markdown("---")

    # === Quay 配置 ===
    if install_options.get('registry_configure', False):
        st.subheader(t('step3.quay_config'))
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            quay_root = st.text_input(t('step3.quay_root'), value=file_paths.get('quayRoot', '/opt/quay'))
        with col_q2:
            quay_storage = st.text_input(t('step3.quay_storage'), value=file_paths.get('quayStorage', '/opt/quay-storage'))
    else:
        quay_root = file_paths.get('quayRoot', '/opt/quay')
        quay_storage = file_paths.get('quayStorage', '/opt/quay-storage')
    
    st.markdown("---")
    
    # === 任務定義 ===
    st.subheader(t('step3.tasks_title'))
    
    tasks_config = {
        'install_packages': {
            'icon': '📦', 'name': t('step3.task_packages'),
            'detail': 'net-tools, git, httpd',
            'method': 'install_packages', 'always_run': True
        },
        'install_cli': {
            'icon': '🔧', 'name': t('step3.task_cli'),
            'detail': f"openshift-install, oc client, oc-mirror",
            'method': 'install_cli', 'always_run': True
        },
        'setup_registry': {
            'icon': '🏗️', 'name': t('step3.task_registry'),
            'detail': 'Podman + Quay Registry',
            'method': 'setup_registry', 'condition': 'registry_configure'
        }
    }
    
    active_tasks = []
    for key, task_info in tasks_config.items():
        if task_info.get('always_run', False):
            active_tasks.append(task_info)
        elif install_options.get(task_info.get('condition', ''), False):
            active_tasks.append(task_info)
    
    for task in active_tasks:
        st.markdown(f"{task['icon']} **{task['name']}** - {task['detail']}")
    
    st.markdown("---")
    
    # === 步驟執行狀態追蹤 ===
    if 'step3_executed' not in st.session_state:
        st.session_state.step3_executed = False
        st.session_state.step3_results = {}

    # === 執行安裝按鈕 ===
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    
    with col_btn1:
        if not st.session_state.step3_executed:
            if not all_files_ok:
                st.warning(t('step3.confirm_files'))
            
            if st.button(t('step3.start_install'), type="primary", disabled=not all_files_ok):
                # 更新檔案路徑到 session state
                _update_file_paths(file_status, quay_root, quay_storage, install_source_dir, arch, rhel, ocp_release)
                
                manager = SetupManager(st.session_state.config_params)
                _execute_step3_tasks(manager, active_tasks)
                st.rerun()

    if st.session_state.step3_executed:
        st.markdown("---")
        st.subheader(t('step3.results'))
        
        results = st.session_state.step3_results
        success_count = sum(1 for r in results.values() if r.get('success', False))
        total_count = len(results)
        
        col_prog1, col_prog2 = st.columns([1, 3])
        with col_prog1:
            st.metric(t('step3.progress'), f"{success_count}/{total_count}")
        
        for method, result in results.items():
            task_name = method
            for task in active_tasks:
                if task['method'] == method:
                    task_name = f"{task['icon']} {task['name']}"
                    break
            if result.get('success', False):
                st.success(f"{task_name}: {result.get('message', '')}")
                # Registry 安裝成功判斷
                if method == 'setup_registry':
                    msg = result.get('message', '')
                    if '驗證通過' in msg or '驗證成功' in msg or '連線成功' in msg:
                        st.info(t('step3.registry_ready'))
                    elif '已安裝' in msg or '跳過' in msg:
                        st.info(t('step3.registry_installed'))
                    else:
                        st.warning(t('step3.registry_verify_failed'))
            else:
                st.error(f"{task_name}: {result.get('message', '')}")
        
        if success_count == total_count:
            st.success(t('step3.all_success'))
            _display_installation_verification()
            if install_options.get('mirror_enable', False):
                st.info(t('step3.mirror_enabled'))
        else:
            st.warning(t('step3.some_failed'))
 
    # === 導航按鈕 ===
    st.markdown("---")
    col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 2])
    
    with col_nav1:
        if st.button(t('step3.back_step2'), use_container_width=True):
            st.session_state.current_step = 2
            st.rerun()
    
    with col_nav2:
        if st.session_state.step3_executed:
            results = st.session_state.step3_results
            all_success = all(r.get('success', False) for r in results.values())
            if all_success:
                if st.button(t('step3.next_step4'), type="primary", use_container_width=True):
                    st.session_state.step3_complete = True
                    st.session_state.current_step = 4
                    st.rerun()
    
    if st.session_state.step3_executed:
        results = st.session_state.step3_results
        if any(not r.get('success', False) for r in results.values()):
            with col_nav3:
                if st.button(t('step3.retry_all'), use_container_width=True):
                    st.session_state.step3_executed = False
                    st.session_state.step3_results = {}
                    st.rerun()

def _update_file_paths(file_status, quay_root, quay_storage, install_source_dir, arch, rhel, ocp_release):
    """更新檔案路徑到 session state"""
    new_paths = {
        'quayRoot': quay_root,
        'quayStorage': quay_storage,
    }
    
    # 從 file_status 取得實際路徑
    for tar_type in ['openshift-install', 'openshift-client', 'mirror-registry', 'oc-mirror']:
        if tar_type in file_status:
            key_map = {
                'openshift-install': 'ocpInstallDir',
                'openshift-client': 'ocpClientDir',
                'mirror-registry': 'mirrorRegistryDir',
                'oc-mirror': 'ocmirrorSource',
            }
            if tar_type in key_map:
                new_paths[key_map[tar_type]] = file_status[tar_type]['full_path']
    
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
        status_text.text(t('step3.executing', task=task_name))
        
        with st.expander(f"{task_name}", expanded=True):
            st.info(t('step3.executing_status'))
            success, message = manager.execute_step(method)
            
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
                col_r, col_s = st.columns(2)
                with col_r:
                    if st.button(t('step3.retry'), key=f"retry_{method}"):
                        retry_success, retry_message = manager.execute_step(method)
                        if retry_success:
                            st.success(f"✅ {retry_message}")
                            success, message = True, retry_message
                        else:
                            st.error(t('step3.retry_failed', msg=retry_message))
                        st.rerun()
                with col_s:
                    if st.button(t('step3.skip'), key=f"skip_{method}"):
                        st.warning(t('step3.skipped', task=task_name))
                        st.session_state.step3_results[method] = {
                            'success': False, 'message': t('step3.skipped', task=message), 'skipped': True
                        }
                        continue
            
            st.session_state.step3_results[method] = {'success': success, 'message': message}
        
        progress_bar.progress((i + 1) / total)
        time.sleep(0.3)
    
    status_text.text(t('step3.complete'))

def _display_installation_verification():
    """顯示安裝後的版本驗證"""
    st.markdown("---")
    st.subheader(t('step3.verification'))
    
    for cmd, label in [
        (['openshift-install', 'version'], 'openshift-install'),
        (['oc', 'version', '--client'], 'oc client'),
        (['podman', '--version'], 'podman'),
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_line = result.stdout.strip().split('\n')[0] if label == 'oc client' else result.stdout.strip()
                st.text(f"✅ {label}: {version_line}")
            else:
                st.text(t('step3.version_unavailable', label=label))
        except FileNotFoundError:
            st.text(t('step3.not_installed', label=label))
        except Exception:
            st.text(t('step3.check_failed', label=label))
