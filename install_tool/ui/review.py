import streamlit as st
import os
import yaml

CURRENT_DIR = os.getcwd()

def show_review_page():
    st.title("4. ✅ Final Review")
    st.markdown("檢查所有生成的配置文件。")
    
    yaml_files = [
        {
            "title": "install-config.yaml", 
            "path": os.path.join(CURRENT_DIR, "install_source", "ocp", "install-config.yaml")
        },
        {
            "title": "agent-config.yaml", 
            "path": os.path.join(CURRENT_DIR, "install_source", "ocp", "agent-config.yaml")
        },
        {
            "title": "imageset-config.yaml", 
            "path": os.path.join(CURRENT_DIR, "install_source", "mirror", "imageset-config.yaml")
        },
    ]
    
    all_valid = True
    for yf in yaml_files:
        if not _render_yaml_review(yf):
            all_valid = False
    
    if all_valid:
        st.success("🎉 所有步驟已完成！配置文件已準備就緒。")
        _render_mirror_guide()
    else:
        st.warning("⚠️ 部分檔案有問題，請檢查上方錯誤訊息")

def _render_yaml_review(yf):
    """渲染單個 YAML 檔案的審查區塊，返回是否有效"""
    st.subheader(yf["title"])
    
    is_valid, msg = _lint_yaml(yf["path"])
    if is_valid:
        st.success(msg)
    else:
        st.error(msg)
    
    if os.path.exists(yf["path"]):
        with open(yf["path"], 'r') as f:
            st.code(f.read(), language="yaml")
    else:
        st.warning("File not found.")
    
    st.divider()
    return is_valid

def _lint_yaml(file_path):
    """檢查 YAML 檔案語法，返回 (is_valid, message)"""
    if not os.path.exists(file_path):
        return False, "File not found"
    try:
        with open(file_path, 'r') as f:
            yaml.safe_load(f)
        return True, "✅ YAML syntax is valid"
    except yaml.YAMLError as e:
        return False, f"❌ YAML syntax error: {str(e)}"
    except Exception as e:
        return False, f"❌ Error: {str(e)}"

def _render_mirror_guide():
    """渲染 oc-mirror 執行指引"""
    st.markdown("---")
    st.subheader("🚀 執行 oc-mirror")
    st.markdown("所有配置文件已就緒。請在**終端機**中執行以下命令來開始鏡像同步：")
    
    mirror_dir = os.path.join(CURRENT_DIR, "install_source", "mirror")
    cache_dir = os.path.join(CURRENT_DIR, "install_source", "mirror-cache")
    imageset_path = os.path.join(mirror_dir, "imageset-config.yaml")
    
    cmd_v2 = f"mkdir -p {cache_dir}\noc-mirror -c {imageset_path} file://{mirror_dir} --cache-dir {cache_dir} --v2"
    cmd_v1 = f"mkdir -p {cache_dir}\noc-mirror -c {imageset_path} file://{mirror_dir} --cache-dir {cache_dir}"
    
    tab1, tab2 = st.tabs(["v2 (推薦)", "v1"])
    
    with tab1:
        st.code(cmd_v2, language="bash")
        st.info("💡 `--v2` 模式支援 blob 層級快取，續傳更高效")
    
    with tab2:
        st.code(cmd_v1, language="bash")
    
    st.markdown("---")
    st.markdown("""
    ### 📋 使用說明
    1. 複製上方命令
    2. 在專案根目錄開啟終端機
    3. 貼上命令並執行
    4. 若下載中斷，重新執行相同命令即可續傳（快取已保留）
    """)