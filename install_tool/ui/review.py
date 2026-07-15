import streamlit as st
import os
import yaml

from i18n import t

CURRENT_DIR = os.getcwd()

def show_review_page():
    st.title(t('review.title'))
    st.markdown(t('review.subtitle'))
    
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
        st.success(t('review.all_done'))
        _render_mirror_guide()
    else:
        st.warning(t('review.some_issues'))

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
        st.warning(t('review.file_not_found'))
    
    st.divider()
    return is_valid

def _lint_yaml(file_path):
    """檢查 YAML 檔案語法，返回 (is_valid, message)"""
    if not os.path.exists(file_path):
        return False, t('review.file_not_found')
    try:
        with open(file_path, 'r') as f:
            yaml.safe_load(f)
        return True, t('review.yaml_valid')
    except yaml.YAMLError as e:
        return False, t('review.yaml_error', error=str(e))
    except Exception as e:
        return False, t('review.yaml_exception', error=str(e))

def _render_mirror_guide():
    """渲染 oc-mirror 執行指引"""
    st.markdown("---")
    st.subheader(t('review.mirror.title'))
    st.markdown(t('review.mirror.desc'))
    
    mirror_dir = os.path.join(CURRENT_DIR, "install_source", "mirror")
    cache_dir = os.path.join(CURRENT_DIR, "install_source", "mirror-cache")
    imageset_path = os.path.join(mirror_dir, "imageset-config.yaml")
    
    cmd_v2 = f"mkdir -p {cache_dir}\noc-mirror -c {imageset_path} file://{mirror_dir} --cache-dir {cache_dir} --v2"
    cmd_v1 = f"mkdir -p {cache_dir}\noc-mirror -c {imageset_path} file://{mirror_dir} --cache-dir {cache_dir}"
    
    tab1, tab2 = st.tabs([t('review.mirror.v2_tab'), t('review.mirror.v1_tab')])
    
    with tab1:
        st.code(cmd_v2, language="bash")
        st.info(t('review.mirror.v2_tip'))
    
    with tab2:
        st.code(cmd_v1, language="bash")
    
    st.markdown("---")
    st.markdown(t('review.mirror.instructions'))
