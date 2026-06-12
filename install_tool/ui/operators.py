import streamlit as st
import json
import os

from src.config_manager import ConfigManager
from src.operator_manager import OperatorManager
from src.setup_wizard import SetupWizard
from src.yaml_generator import YAMLGenerator

CURRENT_DIR = os.getcwd()
CONFIG_DIR = os.path.join(CURRENT_DIR, 'config')

def show_operators_page():
    """渲染 Operator 選擇頁面，包含 CSI 配置、Package 勾選、版本查詢及 imageset 生成"""
    st.title("3. 📦 Operator Selection & CSI Configuration")
    st.markdown("選擇 CSI 驅動程序與需要的 Operators，生成 `imageset-config.yaml`。")
    
    _init_session_state()
    op_mgr = OperatorManager(CURRENT_DIR)
    operator_index = _load_operator_index()
    if operator_index is None:
        return
    
    _render_csi_config()
    _render_package_selection(operator_index)
    _render_version_fetch(op_mgr, operator_index)
    _render_version_config()
    _render_additional_images_section()
    _render_save_and_preview()
    _render_next_button()

def _init_session_state():
    """初始化 CSI 配置、已選 packages、版本資訊及 additional images 的 session state"""
    if 'csi_config' not in st.session_state:
        st.session_state.csi_config = {"CSI_TYPE": "nfs-csi", "TRIDENT_INSTALLER": "25.02.1"}
    if 'selected_packages' not in st.session_state:
        st.session_state.selected_packages = []
    if 'package_versions' not in st.session_state:
        st.session_state.package_versions = {}
    if 'additional_images' not in st.session_state:
        _init_additional_images()
    if 'temp_operator_configs' not in st.session_state:
        st.session_state.temp_operator_configs = {}

def _load_operator_index():
    """從 config 目錄載入 operator_index.json 並按名稱排序"""
    index_file = os.path.join(CONFIG_DIR, "operator_index.json")
    if not os.path.exists(index_file):
        st.error("請先在 Tool Configuration 中獲取 Operator Index")
        return None
    with open(index_file, 'r') as f:
        data = json.load(f)
    data.sort(key=lambda x: x['package_name'].lower())
    return data

def _load_default_images():
    """從 default_images.json 載入預設的 base 與 CSI images"""
    json_path = os.path.join(CONFIG_DIR, "default_images.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"讀取 default_images.json 失敗: {e}")
    return {"base_images": [], "csi_images": {}}

def _get_default_csi_images(csi_config, default_images_data):
    """根據 CSI 類型從 JSON 資料中提取對應的預設 images，trident 需動態替換版本號"""
    csi_type = csi_config.get('CSI_TYPE', 'none')
    csi_images_data = default_images_data.get('csi_images', {})
    
    if csi_type == 'trident':
        trident_ver = csi_config.get('TRIDENT_INSTALLER', '25.02.1')
        trident_major_minor = trident_ver.rsplit('.', 1)[0] if '.' in trident_ver else trident_ver
        images = []
        for img in csi_images_data.get('trident', []):
            img_name = img['name'].replace('25.02.1', trident_ver).replace('25.02', trident_major_minor)
            images.append({"name": img_name})
        return images
    
    # nfs-csi 或其他類型：只保留 name
    raw_images = csi_images_data.get(csi_type, [])
    return [{"name": img['name']} for img in raw_images]

def _init_additional_images():
    """合併 base images 與 CSI images 為 additional_images 的初始值"""
    default_data = _load_default_images()
    csi_config = st.session_state.get('csi_config', {'CSI_TYPE': 'none'})
    
    base = default_data.get('base_images', [])
    csi = _get_default_csi_images(csi_config, default_data)
    
    # 初始化計數器（如果還沒有）
    if 'image_counter' not in st.session_state:
        st.session_state.image_counter = 0
    
    all_images = []
    seen_names = set()  # 用於去重
    
    # 處理 base images
    for img in base:
        img_name = img.get('name', '')
        if img_name and img_name not in seen_names:
            st.session_state.image_counter += 1
            all_images.append({
                "name": img_name,
                "id": f"img_{st.session_state.image_counter}"
            })
            seen_names.add(img_name)
    
    # 處理 CSI images
    for img in csi:
        img_name = img.get('name', '')
        if img_name and img_name not in seen_names:
            st.session_state.image_counter += 1
            all_images.append({
                "name": img_name,
                "id": f"img_{st.session_state.image_counter}"
            })
            seen_names.add(img_name)
    
    st.session_state.additional_images = all_images

def _render_csi_config():
    """渲染 CSI 驅動類型選擇區塊，trident 模式額外顯示版本輸入框"""
    with st.expander("🖥️ CSI Driver Configuration", expanded=True):
        csi_type = st.selectbox(
            "Select CSI Type", ["nfs-csi", "trident", "none"],
            index=0 if st.session_state.csi_config['CSI_TYPE'] == 'nfs-csi' else (
                1 if st.session_state.csi_config['CSI_TYPE'] == 'trident' else 2)
        )
        st.session_state.csi_config['CSI_TYPE'] = csi_type
        if csi_type == 'trident':
            ver = st.text_input("Trident Installer Version", value=st.session_state.csi_config['TRIDENT_INSTALLER'])
            st.session_state.csi_config['TRIDENT_INSTALLER'] = ver
        else:
            st.session_state.csi_config['TRIDENT_INSTALLER'] = ""

def _render_package_selection(operator_index):
    """以三欄 checkbox 方式渲染 Operator package 列表，支援關鍵字搜尋"""
    st.subheader("📦 Select Operators")
    search_term = st.text_input("🔎 Search packages")
    filtered = [p for p in operator_index if search_term.lower() in p['package_name'].lower()] if search_term else operator_index
    
    cols = st.columns(3)
    for i, pkg in enumerate(filtered):
        with cols[i % 3]:
            pkg_name = pkg['package_name']
            is_selected = pkg_name in st.session_state.selected_packages
            if st.checkbox(pkg_name, value=is_selected, key=f"chk_{pkg_name}"):
                if pkg_name not in st.session_state.selected_packages:
                    st.session_state.selected_packages.append(pkg_name)
            else:
                if pkg_name in st.session_state.selected_packages:
                    st.session_state.selected_packages.remove(pkg_name)

def _render_version_fetch(op_mgr, operator_index):
    """啟動 Registry 容器並逐個查詢已選 package 的 channel 版本，即時顯示結果"""
    if not st.button("🔍 Confirm & Fetch Versions", type="primary"):
        return
    if not st.session_state.selected_packages:
        st.warning("請至少選擇一個 package")
        return
    
    wizard = SetupWizard(CURRENT_DIR)
    config = ConfigManager('tool_config.json').get_config()
    
    with st.status("📡 查詢版本中...", expanded=True) as status_container:
        progress_bar = st.progress(0, "準備中...")
        results_container = st.container()
        
        def fetch_log(msg):
            with results_container:
                st.write(f"➤ {msg}")
        
        fetch_log("啟動 Registry 容器...")
        success, container_name, port = wizard.registry.start_operator_registry(config, status_callback=fetch_log)
        
        if not success:
            st.error("啟動容器失敗")
            return
        
        try:
            grpcurl_cmd = op_mgr.find_grpcurl()
            total = len(st.session_state.selected_packages)
            success_count, fail_count = 0, 0
            
            for i, pkg_name in enumerate(st.session_state.selected_packages):
                progress_bar.progress(int((i / total) * 100), f"查詢中... ({i+1}/{total})")
                
                pkg_info = next((p for p in operator_index if p['package_name'] == pkg_name), None)
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
                        fetch_log(f"⚠️ {pkg_name} / {default_ch}: 無版本資訊")

                # 查詢 stable_channel（如果與 default 不同）
                if stable_ch and stable_ch != default_ch:
                    ver = op_mgr.get_bundle_version(grpcurl_cmd, port, pkg_name, stable_ch, max_retries=3)
                    if ver:
                        versions[stable_ch] = ver
                        success_count += 1
                        fetch_log(f"✅ {pkg_name} / {stable_ch}: **{ver}**")
                    else:
                        fetch_log(f"⚠️ {pkg_name} / {stable_ch}: 無版本資訊")
                
                if not versions:
                    versions['unknown'] = '0.0.0'
                    fetch_log(f"❌ {pkg_name}: 無法獲取任何版本，設定預設值 0.0.0")
                
                st.session_state.package_versions[pkg_name] = {
                    'default_channel': default_ch,
                    'stable_channel': stable_ch,
                    'versions': versions
                }

            progress_bar.progress(100, "完成!")
            fetch_log(f"---")
            fetch_log(f"🎯 查詢完成: {success_count} 成功, {fail_count} 失敗")
        finally:
            wizard.registry.stop_operator_registry(container_name)
            fetch_log("🧹 容器已清除")

    st.rerun()

def _render_version_config():
    """為每個已選 package 渲染版本選擇的 radio 按鈕"""
    if not st.session_state.package_versions:
        return
    
    st.markdown("---")
    st.subheader("⚙️ Configure Versions")
    
    for pkg_name in st.session_state.selected_packages:
        if pkg_name not in st.session_state.package_versions:
            continue
        
        pkg_data = st.session_state.package_versions[pkg_name]
        with st.expander(f"📦 {pkg_name}", expanded=True):
            version_options = [f"{ch}: {ver}" for ch, ver in pkg_data['versions'].items()]
            if not version_options:
                st.warning("No versions found")
                continue
            
            selected = st.radio("Select Version", version_options, key=f"ver_{pkg_name}")
            selected_version = selected.split(": ")[-1] if ": " in selected else selected
            
            st.session_state.temp_operator_configs[pkg_name] = {
                "name": pkg_name,
                "channel": pkg_data['default_channel'],
                "minVersion": selected_version,
                "maxVersion": selected_version
            }

def _render_additional_images_section():
    """渲染 additional images 的編輯介面，支援新增與刪除"""
    if not st.session_state.get('package_versions'):
        return
    
    st.markdown("---")
    st.subheader("📦 Additional Images")
    st.markdown("這些鏡像將被包含在 `imageset-config.yaml` 中進行 mirror。您可以新增或刪除額外的鏡像。")
    
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
        if st.button("➕ Add Image", use_container_width=True):
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
        if not st.button("💾 Save All & Generate YAMLs", type="primary", use_container_width=True):
            return
    
    # 儲存 operators.json
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
        cluster_config['csi_info'] = st.session_state.get('csi_config', {})
        yaml_content = YAMLGenerator(cluster_config, CURRENT_DIR).generate_imageset_config()
        
        # imageset-config.yaml → install_source/mirror/
        mirror_dir = os.path.join(CURRENT_DIR, "install_source", "mirror")
        os.makedirs(mirror_dir, exist_ok=True)
        output_path = os.path.join(mirror_dir, "imageset-config.yaml")
        with open(output_path, 'w') as f:
            f.write(yaml_content)
        
        st.session_state.operators_saved = True
        st.success("✅ All configurations saved!")
    except Exception as e:
        st.error(f"Error generating imageset-config.yaml: {str(e)}")
    
    # Preview
    if st.session_state.get('operators_saved', False):
        st.markdown("---")
        st.subheader("📄 Preview: imageset-config.yaml")
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
        if st.button("➡️ Next: Final Review", use_container_width=True, type="primary"):
            st.session_state.current_view = 'review'
            st.rerun()
    else:
        st.divider()
        missing = [f for f in required_files if not os.path.exists(f)]
        if missing:
            st.warning(f"⚠️ 缺少 {len(missing)} 個必要檔案，請點擊 **Save All & Generate YAMLs**")