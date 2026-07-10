import streamlit as st
import os

from ui.tool_config import show_tool_config_page
from ui.cluster_config import show_cluster_config_page
from ui.operators import show_operators_page
from ui.review import show_review_page

CURRENT_DIR = os.getcwd()
CONFIG_DIR = os.path.join(CURRENT_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)

# 頁面配置
st.set_page_config(
    page_title="OpenShift Prep Tool",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化會話狀態
if 'current_view' not in st.session_state:
    st.session_state.current_view = 'tool_config'
if 'env_ready' not in st.session_state:
    st.session_state.env_ready = False
if 'tools_downloaded' not in st.session_state:
    st.session_state.tools_downloaded = False
if 'ssh_keygen_done' not in st.session_state:
    st.session_state.ssh_keygen_done = False
if 'generated_ssh_pubkey' not in st.session_state:
    st.session_state.generated_ssh_pubkey = None
if 'cluster_configured' not in st.session_state:
    st.session_state.cluster_configured = False
if 'operators_saved' not in st.session_state:
    st.session_state.operators_saved = False


def main():
    # 側邊欄導航
    with st.sidebar:
        st.title("🛠️ OpenShift Prep")
        st.markdown("---")
        
        st.button("1. 🔧 Tool Config & Setup", use_container_width=True,
                  key="nav_step1", disabled=False)
        st.button("2. 🏗️ Cluster Config", use_container_width=True,
                  key="nav_step2", disabled=not st.session_state.tools_downloaded)
        st.button("3. 📦 Operators & CSI", use_container_width=True,
                  key="nav_step3", disabled=not st.session_state.cluster_configured)
        st.button("4. ✅ Final Review", use_container_width=True,
                  key="nav_step4",
                  disabled=not os.path.exists(os.path.join(CONFIG_DIR, 'operators.json')))

        st.markdown("---")
        st.write(f"**Current Step:** {st.session_state.current_view.replace('_', ' ').title()}")

    # 視圖路由
    if st.session_state.current_view == 'tool_config':
        show_tool_config_page()
    elif st.session_state.current_view == 'cluster_config':
        show_cluster_config_page()
    elif st.session_state.current_view == 'operators':
        show_operators_page()
    elif st.session_state.current_view == 'review':
        show_review_page()


if __name__ == "__main__":
    main()