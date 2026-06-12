import streamlit as st
import os
import subprocess
from managers.base_manager import BaseManager
from managers.setup_manager import SetupManager


def _check_registry_catalog(config_params: dict) -> tuple:
    """
    檢查 Registry catalog 是否已有鏡像
    
    Returns:
        (success: bool, message: str)
    """
    bastion_ip = config_params.get('bastion', {}).get('ip', '')
    registry_password = config_params.get('registryPassword', '')
    reponame = st.session_state.get('file_paths', {}).get('reponame', 'ocp420')
    
    if not bastion_ip or not registry_password:
        return False, "缺少 Bastion IP 或 Registry Password"
    
    try:
        result = subprocess.run(
            f"curl -sk -u init:{registry_password} https://{bastion_ip}:8443/v2/_catalog",
            shell=True, capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            if reponame in result.stdout:
                return True, f"✅ 鏡像已同步完成！找到 repository: `{reponame}`"
            else:
                return False, f"⚠️ Registry 可連線，但尚未找到 `{reponame}`，請先執行上方同步指令"
        else:
            return False, f"❌ Registry 無法連線: {result.stderr[:200]}"
            
    except subprocess.TimeoutExpired:
        return False, "❌ 檢查 Registry 超時，請確認服務是否運行"
    except Exception as e:
        return False, f"❌ 檢查失敗: {str(e)}"

def render_step4_mirror():
    """步驟4: 鏡像同步"""
    st.header("🪞 步驟4: 鏡像同步")
    st.markdown("檢查必要檔案，確認無誤後在終端機中執行鏡像同步指令。")
    
    config_params = st.session_state.get('config_params', {})
    
    # 取得路徑
    install_source_dir = BaseManager._get_install_source_dir()
    mirror_dir = os.path.join(install_source_dir, "mirror")
    
    # === Registry 連線狀態檢查 ===
    st.subheader("🔗 Registry 連線狀態")
    
    manager = SetupManager(config_params)
    installed, install_msg = manager.mirror_registry_manager.check_installed()
    
    if installed:
        st.success(f"✅ {install_msg}")
        with st.spinner("正在驗證 Registry 連線..."):
            connected, connect_msg = manager.mirror_registry_manager.verify_connection()
            if connected:
                st.success(f"✅ {connect_msg}")
            else:
                st.warning(f"⚠️ {connect_msg}")
    else:
        st.warning(f"⚠️ {install_msg}")
        st.info("請返回步驟3安裝 Mirror Registry")
        col_back, _ = st.columns([1, 3])
        with col_back:
            if st.button("⬅️ 返回步驟3", type="primary"):
                st.session_state.current_step = 3
                st.rerun()
        return
    
    st.markdown("---")
    
    # === 必要檔案檢查 ===
    st.subheader("📁 必要檔案檢查")
    
    bastion_ip = config_params.get('bastion', {}).get('ip', '')
    bastion_name = config_params.get('bastion', {}).get('name', 'bastion')
    cluster_name = config_params.get('clusterName', 'ocp4')
    base_domain = config_params.get('baseDomain', 'example.com')
    reponame = st.session_state.get('file_paths', {}).get('reponame', 'ocp420')
    bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
    
    # 檢查 oc-mirror
    oc_mirror_path = '/usr/bin/oc-mirror'
    oc_mirror_ok = os.path.exists(oc_mirror_path)
    if oc_mirror_ok:
        st.success(f"✅ oc-mirror: `{oc_mirror_path}`")
    else:
        st.error(f"❌ oc-mirror 未安裝，請返回步驟3安裝")
    
    # 檢查 imageset-config.yaml
    imageset_yaml = os.path.join(mirror_dir, 'imageset-config.yaml')
    imageset_ok = os.path.exists(imageset_yaml)
    if imageset_ok:
        st.success(f"✅ imageset-config.yaml: `{imageset_yaml}`")
        with st.expander("📄 預覽 imageset-config.yaml"):
            with open(imageset_yaml, 'r') as f:
                st.code(f.read(), language="yaml")
    else:
        st.error(f"❌ imageset-config.yaml 不存在: `{imageset_yaml}`")
        st.info("💡 請先在 install_tool 的 Operators 頁面生成 imageset-config.yaml")
    
    all_ok = oc_mirror_ok and imageset_ok and installed
    
    if all_ok:
        st.success("🎉 所有必要檔案已就緒！")
    
    st.markdown("---")
    
    # === 鏡像同步指令 ===
    st.subheader("🚀 執行鏡像同步")
    st.markdown("請在**終端機**中執行以下命令來開始鏡像同步：")
    
    cache_dir = os.path.join(install_source_dir, "mirror-cache")
    registry_target = f"{bastion_ip}:8443" if bastion_ip else f"{bastion_fqdn}:8443"
    
    cmd = (
        f"mkdir -p {cache_dir}\n"
        f"oc mirror -c {imageset_yaml} \\\n"
        f"  --from file://{mirror_dir} \\\n"
        f"  docker://{registry_target}/{reponame} \\\n"
        f"  --cache-dir {cache_dir} \\\n"
        f"  --v2"
    )
    
    st.code(cmd, language="bash")
    st.info("💡 複製上方命令，在終端機中貼上執行")
    
    st.markdown("""
    ### 📋 使用說明
    1. **複製**上方命令
    2. 在 Bastion 主機上開啟**終端機**
    3. **貼上**命令並執行
    4. 鏡像同步可能需要 **10-60 分鐘**
    5. 若中斷，重新執行相同命令即可**續傳**
    """)
    
    st.markdown("---")
    
    # === 同步狀態檢查 ===
    st.subheader("🔍 檢查同步狀態")
    st.markdown("執行上方指令後，點擊下方按鈕檢查鏡像是否已同步完成：")
    
    if st.button("🔄 檢查 Mirror Registry 同步狀態", use_container_width=True):
        with st.spinner("正在檢查 Registry..."):
            success, msg = _check_registry_catalog(config_params)
            if success:
                st.success(msg)
                st.balloons()
            else:
                st.warning(msg)
    
    st.markdown("---")
    
    # === 導航按鈕 ===
    col_nav1, col_nav2 = st.columns([1, 3])
    
    with col_nav1:
        if st.button("⬅️ 返回步驟3", use_container_width=True):
            st.session_state.current_step = 3
            st.rerun()
    
    with col_nav2:
        if st.button("🏁 完成安裝", type="primary", use_container_width=True):
            st.session_state.step4_complete = True
            st.session_state.current_step = 5
            st.rerun()