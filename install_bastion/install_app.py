import streamlit as st
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from steps.step1_config import render_step1_config
from steps.step2_services import render_step2_services
from steps.step3_cli_packages import render_step3_cli_packages
from steps.step4_mirror import render_step4_mirror

from managers.base_manager import BaseManager

def load_cluster_config():
    """載入 cluster_config.json 配置檔"""
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'config',
        'cluster_config.json'
    )
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except Exception as e:
            st.warning(f"載入 cluster_config.json 時發生錯誤: {str(e)}")
            return None
    else:
        st.info(f"未找到配置檔: {config_path}")
        return None


def parse_host_config(config_data: dict) -> dict:
    """
    解析 cluster_config.json 並轉換為 host 配置格式
    """
    if not config_data:
        return {}
    
    env = config_data.get('install_env', {})
    version = config_data.get('version_info', {})
    
    host_config = {}
    
    # 僅添加 config 中存在的欄位
    if 'CLUSTER_DOMAIN' in env:
        host_config['clusterName'] = env['CLUSTER_DOMAIN']
    if 'BASE_DOMAIN' in env:
        host_config['baseDomain'] = env['BASE_DOMAIN']
    if 'INSTALL_MODE' in env:
        host_config['mode'] = env['INSTALL_MODE']
    if 'MASTER01_INTERFACE' in env:
        host_config['interface'] = env['MASTER01_INTERFACE']
    if 'DNS_UPSTREAM' in env:
        host_config['dns_upstream'] = env['DNS_UPSTREAM']
    
    # Bastion
    bastion = {'name': 'bastion'}
    if 'BASTION_IP' in env:
        bastion['ip'] = env['BASTION_IP']
    host_config['bastion'] = bastion
    
    # Bootstrap
    bootstrap = {'name': 'bootstrap'}
    if 'BOOTSTRAP_IP' in env and env['BOOTSTRAP_IP']:
        bootstrap['ip'] = env['BOOTSTRAP_IP']
    else:
        bootstrap['ip'] = _auto_assign_bootstrap_ip(env, host_config)
    host_config['bootstrap'] = bootstrap
    
    # Registry Password
    if 'REGISTRY_PASSWORD' in env:
        host_config['registryPassword'] = env['REGISTRY_PASSWORD']
    if 'SSH_KEY' in env:
        host_config['sshKey'] = env['SSH_KEY']
    if 'ADDITIONAL_TRUST_BUNDLE' in env:
        host_config['additionalTrustBundle'] = env['ADDITIONAL_TRUST_BUNDLE']
    
    # 網路配置 - 僅添加存在的欄位
    network_config = {}
    network_fields = {
        'MACHINE_NETWORK_CIDR': 'machineNetworkCidr',
        'CLUSTER_NETWORK_CIDR': 'clusterNetworkCidr',
        'CLUSTER_NETWORK_HOST_PREFIX': 'clusterNetworkHostPrefix',
        'SERVICE_NETWORK_CIDR': 'serviceNetworkCidr',
        'NETWORK_TYPE': 'networkType',
        'GATEWAY_IP': 'gatewayIp'
    }
    for env_key, config_key in network_fields.items():
        if env_key in env:
            network_config[config_key] = env[env_key]
    if network_config:
        host_config['networkConfig'] = network_config
    
    # 版本資訊
    version_info = {}
    if 'OCP_VERSION' in version:
        version_info['ocpVersion'] = version['OCP_VERSION']
    if 'OCP_RELEASE' in version:
        version_info['ocpRelease'] = version['OCP_RELEASE']
    if version_info:
        host_config['versionInfo'] = version_info
    
    # 解析節點 - 僅添加 config 中有的
    host_config['master'] = _parse_nodes(env, 'MASTER', default_interface='enp1s0', default_device='/dev/vda')
    host_config['worker'] = _parse_nodes(env, 'WORKER', default_interface='enp1s0', default_device='/dev/vda')
    host_config['infra'] = _parse_nodes(env, 'INFRA', default_interface='ens18', default_device='/dev/sda')
    
    return host_config

def _parse_nodes(env: dict, prefix: str, default_interface: str, default_device: str) -> list:
    """解析節點配置"""
    nodes = []
    i = 1
    while True:
        ip_key = f'{prefix}{i:02d}_IP'
        if ip_key in env and env[ip_key]:
            node = {
                'name': f'{prefix.lower()}-{i-1}',
                'ip': env[ip_key],
                'mac': env.get(f'{prefix}{i:02d}_MAC', ''),
                'interface': env.get(f'{prefix}{i:02d}_INTERFACE', default_interface),
                'device': env.get(f'{prefix}{i:02d}_DEVICE', default_device)
            }
            nodes.append(node)
            i += 1
        else:
            break
    return nodes

def _auto_assign_bootstrap_ip(env: dict, host_config: dict) -> str:
    """自動分配 Bootstrap IP"""
    masters = host_config.get('master', [])
    if masters:
        master_ip = masters[0]['ip']
        ip_parts = master_ip.rsplit('.', 1)
        if len(ip_parts) == 2:
            try:
                last_octet = int(ip_parts[1])
                bootstrap_octet = max(1, last_octet - 10)
                return f"{ip_parts[0]}.{bootstrap_octet}"
            except ValueError:
                pass
    return ''

def init_session_state(cluster_config=None):
    """初始化 Session State"""
    install_source_dir = BaseManager._get_install_source_dir()

    reponame = 'ocp4'
    if cluster_config:
        ocp_version = cluster_config.get('version_info', {}).get('OCP_VERSION', '')
        if ocp_version:
            reponame = f"ocp{ocp_version.replace('.', '')}"

    defaults = {
        'current_step': 1,
        'installation_started': False,
        'installation_complete': False,
        'step1_complete': False,
        'step2_complete': False,
        'step3_complete': False,
        'step4_complete': False,
        'config_params': cluster_config or {},
        'original_config': cluster_config or {},
        # 安裝選項
        'install_options': {
            'firewalld_disable': True,
            'selinux_disable': True,
            'dns_configure': True,
            'dns_check': True,
            'haproxy_configure': True,
            'ntp_server_configure': True,
            'registry_configure': True,
        },
        # 檔案路徑
        'file_paths': {
            'mirrorRegistryDir': os.path.join(install_source_dir, 'mirror-registry.tar.gz'),
            'ocpInstallDir': os.path.join(install_source_dir, 'openshift-install-linux.tar.gz'),
            'ocpClientDir': os.path.join(install_source_dir, 'openshift-client-linux.tar.gz'),
            'quayRoot': '/opt/quay',
            'quayStorage': '/opt/quay-storage',
            'ocmirrorSource': os.path.join(install_source_dir, 'oc-mirror.tar.gz'),
            'imageSetFile': os.path.join(install_source_dir, 'oc-mirror-workspace'),
            'reponame': reponame,
        },
        # 步驟執行結果
        'step_results': {},
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def display_sidebar_progress():
    """側邊欄顯示進度"""
    with st.sidebar:
        st.markdown("---")
        st.header("📋 安裝進度")
        
        steps = [
            ("步驟1: 環境配置確認", "step1_complete"),
            ("步驟2: 基礎服務安裝", "step2_complete"),
            ("步驟3: CLI與套件安裝", "step3_complete"),
            ("步驟4: 鏡像同步", "step4_complete"),
        ]
        
        current = st.session_state.current_step
        
        for i, (step_name, step_key) in enumerate(steps, 1):
            if st.session_state.get(step_key, False):
                st.success(f"✅ {step_name}")
            elif i == current:
                st.info(f"🔄 {step_name}")
            else:
                st.text(f"⬜ {step_name}")

def display_config_summary():
    """顯示載入的配置摘要"""
    config = st.session_state.get('original_config', {})
    
    if config:
        with st.sidebar:
            with st.expander("📄 已載入配置", expanded=False):
                version = config.get('versionInfo', {})
                if version:
                    st.markdown("**版本資訊**")
                    st.text(f"OCP: {version.get('ocpVersion', 'N/A')}")
                    st.text(f"Release: {version.get('ocpRelease', 'N/A')}")
                
                st.markdown("**叢集資訊**")
                st.text(f"模式: {config.get('mode', 'N/A')}")
                st.text(f"網域: {config.get('clusterName', 'N/A')}.{config.get('baseDomain', 'N/A')}")
                
                st.markdown("**節點摘要**")
                st.text(f"Master: {len(config.get('master', []))} 個")
                st.text(f"Worker: {len(config.get('worker', []))} 個")
                st.text(f"Infra: {len(config.get('infra', []))} 個")
                
                net = config.get('networkConfig', {})
                if net:
                    st.markdown("**網路配置**")
                    if 'networkType' in net:
                        st.text(f"類型: {net['networkType']}")

def main():
    """主入口函數"""
    st.set_page_config(
        page_title="Bastion 安裝引導工具",
        page_icon="🔄",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.markdown(
        """
        <script>
            window.scrollTo({top: 0, behavior: 'instant'});
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
        </script>
        """,
        unsafe_allow_html=True,
    )

    # 載入 cluster_config.json
    cluster_config = load_cluster_config()
    if cluster_config:
        host_config = parse_host_config(cluster_config)
        st.sidebar.success("✅ 已載入 cluster_config.json")
    else:
        host_config = None
    
    # 初始化 session state
    init_session_state(host_config)
    
    # 顯示主標題
    st.title("🔄 Bastion 安裝引導工具")
    st.markdown("---")
    
    # 側邊欄
    display_config_summary()
    display_sidebar_progress()
    
    # 根據當前步驟渲染對應頁面
    current_step = st.session_state.current_step
    
    if current_step == 1:
        render_step1_config()
    elif current_step == 2:
        render_step2_services()
    elif current_step == 3:
        render_step3_cli_packages()
    elif current_step == 4:
        render_step4_mirror()
    elif current_step >= 5:
        st.header("🎉 安裝完成")
        st.success("所有步驟已完成！")
        
        if st.button("🔄 重新開始"):
            original_config = st.session_state.get('original_config', {})
            st.session_state.clear()
            st.session_state.original_config = original_config
            st.session_state.config_params = original_config
            st.rerun()

if __name__ == "__main__":
    main()