import streamlit as st
import json
import os

from i18n import t
from src.config_manager import ConfigManager
from src.operator_manager import OperatorManager
from src.setup_wizard import SetupWizard
from src.yaml_generator import YAMLGenerator
from src.registry_manager import RegistryManager

CURRENT_DIR = os.getcwd()
CONFIG_DIR = os.path.join(CURRENT_DIR, 'config')

def show_operators_page():
    """渲染 Operator 選擇頁面，包含 Package 勾選、版本查詢及 imageset 生成"""
    st.title(t('ops.title'))
    st.markdown(t('ops.subtitle'))
    
    _init_session_state()
    op_mgr = OperatorManager(CURRENT_DIR)
    operator_index = _load_operator_index()
    if operator_index is None:
        return
    
    _render_package_selection(operator_index)
    _render_version_fetch(op_mgr, operator_index)
    _render_version_config()
    _render_additional_images_section()
    _render_save_and_preview()
    _render_next_button()

def _init_session_state():
    """初始化已選 packages、版本資訊及 additional images 的 session state"""
    # selected_packages: [{package_name, index_type}, ...]
    if 'selected_packages' not in st.session_state:
        st.session_state.selected_packages = []
    if 'package_versions' not in st.session_state:
        st.session_state.package_versions = {}
    if 'additional_images' not in st.session_state:
        _init_additional_images()
    if 'temp_operator_configs' not in st.session_state:
        st.session_state.temp_operator_configs = {}

def _load_operator_index():
    """從 config 目錄載入 operator_index.json，回傳 dict（按 index_type 分區）"""
    index_file = os.path.join(CONFIG_DIR, "operator_index.json")
    if not os.path.exists(index_file):
        st.error(t('ops.error_no_index'))
        return None
    with open(index_file, 'r') as f:
        data = json.load(f)
    return data

def _load_default_images():
    """從 default_images.json 載入預設的 base images"""
    json_path = os.path.join(CONFIG_DIR, "default_images.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                return data.get('base_images', [])
        except Exception as e:
            st.warning(f"讀取 default_images.json 失敗: {e}")
    return []

def _init_additional_images():
    """從 default_images.json 載入 base images 為 additional_images 的初始值"""
    base = _load_default_images()
    
    if 'image_counter' not in st.session_state:
        st.session_state.image_counter = 0
    
    all_images = []
    seen_names = set()
    
    for img in base:
        img_name = img.get('name', '')
        if img_name and img_name not in seen_names:
            st.session_state.image_counter += 1
            all_images.append({
                "name": img_name,
                "id": f"img_{st.session_state.image_counter}"
            })
            seen_names.add(img_name)
    
    st.session_state.additional_images = all_images

def _get_selected_pkg_names():
    """取得已選 package 名稱列表"""
    return [item['package_name'] for item in st.session_state.selected_packages]

def _is_pkg_selected(pkg_name, index_type):
    """檢查 package 是否已選"""
    for item in st.session_state.selected_packages:
        if item['package_name'] == pkg_name and item['index_type'] == index_type:
            return True
    return False

def _toggle_pkg(pkg_name, index_type, checked):
    """切換 package 選取狀態"""
    if checked:
        if not _is_pkg_selected(pkg_name, index_type):
            st.session_state.selected_packages.append({
                'package_name': pkg_name,
                'index_type': index_type
            })
    else:
        st.session_state.selected_packages = [
            item for item in st.session_state.selected_packages
            if not (item['package_name'] == pkg_name and item['index_type'] == index_type)
        ]

def _render_package_selection(operator_index):
    """按 index 分 tab 渲染 Operator package 列表，支援關鍵字搜尋"""
    st.subheader(t('ops.select.title'))
    search_term = st.text_input(t('ops.select.search'))
    
    # 篩選有資料的 index
    available_indexes = []
    for idx_type, idx_info in RegistryManager.INDEX_TYPES.items():
        packages = operator_index.get(idx_type, [])
        if packages:
            available_indexes.append((idx_type, idx_info, packages))
    
    if not available_indexes:
        st.warning(t('ops.select.no_data'))
        return
    
    # 建立 tab（每個 index 一個 tab）
    tab_labels = [
        t('ops.select.section', label=idx_info['label'], count=len(packages))
        for idx_type, idx_info, packages in available_indexes
    ]
    tabs = st.tabs(tab_labels)
    
    for tab_idx, (idx_type, idx_info, packages) in enumerate(available_indexes):
        with tabs[tab_idx]:
            # 排序
            sorted_packages = sorted(packages, key=lambda x: x['package_name'].lower())
            # 搜尋過濾
            if search_term:
                sorted_packages = [p for p in sorted_packages if search_term.lower() in p['package_name'].lower()]
            
            if not sorted_packages:
                st.caption(t('ops.select.no_match'))
                continue
            
            cols = st.columns(3)
            for i, pkg in enumerate(sorted_packages):
                with cols[i % 3]:
                    pkg_name = pkg['package_name']
                    is_selected = _is_pkg_selected(pkg_name, idx_type)
                    if st.checkbox(pkg_name, value=is_selected, key=f"chk_{idx_type}_{pkg_name}"):
                        _toggle_pkg(pkg_name, idx_type, True)
                    else:
                        _toggle_pkg(pkg_name, idx_type, False)

def _render_version_fetch(op_mgr, operator_index):
    """按 index_type 分組查詢版本：為每個 index 啟動對應容器，查詢完成後停止"""
    if not st.button(t('ops.fetch.button'), type="primary"):
        return
    
    selected = st.session_state.selected_packages
    if not selected:
        st.warning(t('ops.fetch.warning_no_select'))
        return
    
    wizard = SetupWizard(CURRENT_DIR)
    config = ConfigManager('tool_config.json').get_config()
    
    # 按 index_type 分組
    index_groups = {}
    for item in selected:
        idx_type = item['index_type']
        if idx_type not in index_groups:
            index_groups[idx_type] = []
        index_groups[idx_type].append(item['package_name'])
    
    with st.status(t('ops.fetch.status'), expanded=True) as status_container:
        progress_bar = st.progress(0, t('ops.fetch.preparing'))
        results_container = st.container()
        
        def fetch_log(msg):
            with results_container:
                st.write(f"➤ {msg}")
        
        grpcurl_cmd = op_mgr.find_grpcurl()
        total_pkgs = len(selected)
        processed = 0
        success_count, fail_count = 0, 0
        
        for idx_type, pkg_names in index_groups.items():
            idx_info = RegistryManager.INDEX_TYPES.get(idx_type, {})
            idx_label = idx_info.get('label', idx_type)
            
            fetch_log(t('ops.fetch.index_header', label=idx_label, count=len(pkg_names)))
            
            # 確保該 index 的容器運行
            container_name = wizard._get_container_name(config, idx_type)
            port = wizard.registry.get_port(idx_type)
            
            if wizard.registry.check_container_running(container_name):
                fetch_log(t('ops.fetch.container_reused', name=container_name))
            else:
                fetch_log(t('ops.fetch.start_registry'))
                success, container_name, port = wizard.registry.start_operator_registry(
                    config, status_callback=fetch_log, index_type=idx_type
                )
                if not success:
                    st.error(t('ops.fetch.start_failed'))
                    continue
            
            try:
                # 查詢該 index 下所有已選 package 的版本
                for pkg_name in pkg_names:
                    processed += 1
                    progress_bar.progress(
                        int((processed / total_pkgs) * 100),
                        t('ops.fetch.querying', current=processed, total=total_pkgs)
                    )
                    
                    # 從 operator_index 中找到 package info
                    pkg_info = None
                    for p in operator_index.get(idx_type, []):
                        if p['package_name'] == pkg_name:
                            pkg_info = p
                            break
                    if not pkg_info:
                        continue
                    
                    versions = {}
                    default_ch = pkg_info.get('default_channel', '')
                    stable_ch = pkg_info.get('stable_channel', '')
                    
                    # 查詢 default_channel
                    if default_ch:
                        ver = op_mgr.get_bundle_version(grpcurl_cmd, port, pkg_name, default_ch, max_retries=3)
                        if ver:
                            versions[default_ch] = ver
                            success_count += 1
                            fetch_log(f"✅ {pkg_name} / {default_ch}: **{ver}**")
                        else:
                            fail_count += 1
                            fetch_log(f"⚠️ {pkg_name} / {default_ch}: {t('ops.fetch.no_version')}")
                    
                    # 查詢 stable_channel（如果與 default 不同）
                    if stable_ch and stable_ch != default_ch:
                        ver = op_mgr.get_bundle_version(grpcurl_cmd, port, pkg_name, stable_ch, max_retries=3)
                        if ver:
                            versions[stable_ch] = ver
                            success_count += 1
                            fetch_log(f"✅ {pkg_name} / {stable_ch}: **{ver}**")
                        else:
                            fetch_log(f"⚠️ {pkg_name} / {stable_ch}: {t('ops.fetch.no_version')}")
                    
                    if not versions:
                        versions['unknown'] = '0.0.0'
                        fetch_log(f"❌ {pkg_name}: {t('ops.fetch.no_any_version')}")
                    
                    # 用 (index_type, package_name) 作為 key
                    pkg_key = f"{idx_type}::{pkg_name}"
                    st.session_state.package_versions[pkg_key] = {
                        'default_channel': default_ch,
                        'stable_channel': stable_ch,
                        'versions': versions,
                        'index_type': idx_type,
                        'package_name': pkg_name,
                    }
            finally:
                # 不在此處停止容器，循環結束後統一關閉
                pass
        
        # 所有 index 查詢完成後，統一關閉所有相關容器
        fetch_log(t('ops.fetch.cleaning_all'))
        for idx_type in index_groups.keys():
            container_name = wizard._get_container_name(config, idx_type)
            if wizard.registry.check_container_running(container_name):
                wizard.registry.stop_operator_registry(container_name)
                fetch_log(t('ops.fetch.container_cleaned_name', name=container_name))
        
        progress_bar.progress(100, t('ops.fetch.complete'))
        fetch_log(f"---")
        fetch_log(t('ops.fetch.summary', success=success_count, fail=fail_count))
    
    st.rerun()

def _render_version_config():
    """為每個已選 package 渲染版本選擇的 radio 按鈕（按 index 分區）"""
    if not st.session_state.package_versions:
        return
    
    st.markdown("---")
    st.subheader(t('ops.config.title'))
    
    # 按 index_type 分組顯示
    grouped = {}
    for pkg_key, pkg_data in st.session_state.package_versions.items():
        idx_type = pkg_data.get('index_type', 'redhat')
        if idx_type not in grouped:
            grouped[idx_type] = []
        grouped[idx_type].append((pkg_key, pkg_data))
    
    for idx_type, items in grouped.items():
        idx_info = RegistryManager.INDEX_TYPES.get(idx_type, {})
        idx_label = idx_info.get('label', idx_type)
        
        st.markdown(f"#### {idx_label}")
        
        for pkg_key, pkg_data in items:
            pkg_name = pkg_data['package_name']
            with st.expander(f"📦 {pkg_name}", expanded=True):
                version_options = [f"{ch}: {ver}" for ch, ver in pkg_data['versions'].items()]
                if not version_options:
                    st.warning(t('ops.config.no_versions'))
                    continue
                
                selected = st.radio(t('ops.config.select_version'), version_options, key=f"ver_{pkg_key}")
                selected_version = selected.split(": ")[-1] if ": " in selected else selected
                
                st.session_state.temp_operator_configs[pkg_key] = {
                    "name": pkg_name,
                    "catalog": idx_type,
                    "channel": pkg_data['default_channel'],
                    "minVersion": selected_version,
                    "maxVersion": selected_version
                }

def _render_additional_images_section():
    """渲染 additional images 的編輯介面，支援新增與刪除"""
    if not st.session_state.get('package_versions'):
        return
    
    st.markdown("---")
    st.subheader(t('ops.images.title'))
    st.markdown(t('ops.images.desc'))
    
    # 初始化計數器
    if 'image_counter' not in st.session_state:
        st.session_state.image_counter = 0
    
    # 為沒有 ID 的 image 分配 ID
    for img in st.session_state.additional_images:
        if 'id' not in img:
            st.session_state.image_counter += 1
            img['id'] = f"img_{st.session_state.image_counter}"
    
    # 顯示現有 images
    for i, img in enumerate(st.session_state.additional_images):
        img_id = img.get('id', f'img_{i}')
        c1, c2, c3 = st.columns([5, 1, 1])
        with c1:
            new_name = st.text_input(
                f"Image {i+1}", 
                value=img.get('name', ''), 
                key=f"add_img_{img_id}",
                label_visibility="collapsed"
            )
            img['name'] = new_name
        with c2:
            st.caption(f"#{i+1}")
        with c3:
            if st.button("🗑️", key=f"del_img_{img_id}"):
                st.session_state.additional_images = [
                    item for item in st.session_state.additional_images 
                    if item.get('id') != img_id
                ]
                st.rerun()
    
    # 新增按鈕
    col_add, _ = st.columns([1, 4])
    with col_add:
        if st.button(t('ops.images.add'), use_container_width=True):
            st.session_state.image_counter += 1
            st.session_state.additional_images.append({
                "name": "", 
                "id": f"img_{st.session_state.image_counter}"
            })
            st.rerun()

def _render_save_and_preview():
    """儲存 operators 與 additional images 配置，生成 imageset-config.yaml 並顯示預覽"""
    if not st.session_state.get('package_versions'):
        return
    
    st.markdown("---")
    col_save, _ = st.columns([1, 4])
    with col_save:
        if not st.button(t('ops.save.button'), type="primary", use_container_width=True):
            return
    
    # 儲存 operators.json（含 catalog 欄位）
    if st.session_state.temp_operator_configs:
        ops_path = os.path.join(CONFIG_DIR, 'operators.json')
        with open(ops_path, 'w') as f:
            json.dump(list(st.session_state.temp_operator_configs.values()), f, indent=2)
    
    # 儲存 additional_images.json - 過濾掉 id 欄位
    add_img_path = os.path.join(CONFIG_DIR, 'additional_images.json')
    clean_images = [{"name": img["name"]} for img in st.session_state.additional_images if img.get("name", "").strip()]
    with open(add_img_path, 'w') as f:
        json.dump(clean_images, f, indent=2)
    
    # 生成 imageset-config.yaml
    try:
        cluster_config = ConfigManager('cluster_config.json').get_config()
        yaml_content = YAMLGenerator(cluster_config, CURRENT_DIR).generate_imageset_config()
        
        # imageset-config.yaml → install_source/mirror/
        mirror_dir = os.path.join(CURRENT_DIR, "install_source", "mirror")
        os.makedirs(mirror_dir, exist_ok=True)
        output_path = os.path.join(mirror_dir, "imageset-config.yaml")
        with open(output_path, 'w') as f:
            f.write(yaml_content)
        
        st.session_state.operators_saved = True
        st.success(t('ops.save.success'))
    except Exception as e:
        st.error(t('ops.save.error', error=str(e)))
    
    # Preview
    if st.session_state.get('operators_saved', False):
        st.markdown("---")
        st.subheader(t('ops.preview.title'))
        imageset_path = os.path.join(CURRENT_DIR, "install_source", "mirror", "imageset-config.yaml")
        if os.path.exists(imageset_path):
            with open(imageset_path, 'r') as f:
                st.code(f.read(), language="yaml")

def _render_next_button():
    """當所有必要檔案存在時渲染前往 Final Review 的按鈕"""
    required_files = [
        os.path.join(CONFIG_DIR, 'operators.json'),
        os.path.join(CONFIG_DIR, 'additional_images.json'),
        os.path.join(CURRENT_DIR, "install_source", "mirror", "imageset-config.yaml")
    ]
    all_exist = all(os.path.exists(f) for f in required_files)
    
    if all_exist and st.session_state.get('operators_saved', False):
        st.divider()
        if st.button(t('ops.next_review'), use_container_width=True, type="primary"):
            st.session_state.current_view = 'review'
            st.rerun()
    else:
        st.divider()
        missing = [f for f in required_files if not os.path.exists(f)]
        if missing:
            st.warning(t('ops.missing_files', count=len(missing)))
