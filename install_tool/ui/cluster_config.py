import streamlit as st
import os
import re

from src.config_manager import ConfigManager
from src.yaml_generator import YAMLGenerator

CURRENT_DIR = os.getcwd()
CONFIG_DIR = os.path.join(CURRENT_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)

def show_cluster_config_page():
    """渲染集群配置頁面，包含身份、網路、節點及憑證設定"""
    st.title("2. 🏗️ Cluster Configuration")
    st.markdown("配置集群網絡、節點 IP 及認證信息，用於生成 `install-config.yaml` 和 `agent-config.yaml`。")
    
    config_manager = ConfigManager('cluster_config.json')
    config = config_manager.get_config()
    
    _init_state(config)
    _render_cluster_identity(config)
    _render_ocp_version_info(config)
    _render_network_nodes(config_manager, config)
    _render_cluster_form(config_manager, config)
    _render_next_button()

def _init_state(config):
    """初始化 session state 中的節點計數與網路預設值"""
    install_env = config.get('install_env', {})

    if 'master_count' not in st.session_state:
        st.session_state.master_count = max(1, sum(
            1 for k in install_env 
            if k.startswith('MASTER') and k.endswith('_IP')))
    if 'infra_count' not in st.session_state:
        st.session_state.infra_count = sum(
            1 for k in install_env 
            if k.startswith('INFRA') and k.endswith('_IP'))
    if 'worker_count' not in st.session_state:
        st.session_state.worker_count = sum(
            1 for k in install_env 
            if k.startswith('WORKER') and k.endswith('_IP'))
    
    if st.session_state.master_count < 1:
        st.session_state.master_count = 1
    
    if 'version_info' not in config:
        config['version_info'] = {}
    
    # 網路預設值
    defaults = {
        'MACHINE_NETWORK_CIDR': '',
        'CLUSTER_NETWORK_CIDR': '10.128.0.0/14',
        'CLUSTER_NETWORK_HOST_PREFIX': 23,
        'SERVICE_NETWORK_CIDR': '172.30.0.0/16',
        'NETWORK_TYPE': 'OVNKubernetes'
    }
    for key, val in defaults.items():
        if key not in config['install_env']:
            config['install_env'][key] = val

def _is_valid_ipv4(ip):
    """驗證 IPv4 格式"""
    if not ip:
        return True
    pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    m = re.match(pattern, ip)
    return m and all(0 <= int(g) <= 255 for g in m.groups())

def _is_valid_mac(mac):
    """驗證 MAC Address 格式"""
    if not mac:
        return True
    pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return bool(re.match(pattern, mac))

def _render_cluster_identity(config):
    """渲染安裝模式、集群名稱與 Base Domain 的輸入區塊"""
    st.subheader("Cluster Identity")
    col1, col2, col3 = st.columns(3)
    with col1:
        config['install_env']['INSTALL_MODE'] = st.selectbox(
            "Install Mode",
            ["standard", "compact", "sno"],
            index=["standard", "compact", "sno"].index(config['install_env']['INSTALL_MODE']),
            key="install_mode_select"
        )
    with col2:
        config['install_env']['CLUSTER_DOMAIN'] = st.text_input(
            "Cluster Name (metadata.name)",
            value=config['install_env']['CLUSTER_DOMAIN'],
            help="例如：ocp4",
            key="cluster_domain_input"
        )
    with col3:
        config['install_env']['BASE_DOMAIN'] = st.text_input(
            "Base Domain",
            value=config['install_env']['BASE_DOMAIN'],
            help="例如：demo.lab",
            key="base_domain_input"
        )

def _render_ocp_version_info(config):
    """從 tool_config 讀取 OCP 版本並顯示，同時預覽 Registry FQDN"""
    tool_config = ConfigManager('tool_config.json').get_config()
    tool_version_info = tool_config.get('version_info', {})

    for key, value in tool_version_info.items():
        config['version_info'][key] = value

    ocp_release = config['version_info'].get('OCP_RELEASE', '4.20.8')
    match = re.match(r'(\d+\.\d+)', ocp_release)
    ocp_version = match.group(1) if match else '4.20'
    config['version_info']['OCP_VERSION'] = ocp_version
    
    st.info(f"📦 OCP Version: **{ocp_version}** (Release: {ocp_release})")

    arch = config['version_info'].get('ARCHITECTURE', 'amd64')
    rhel = config['version_info'].get('RHEL_VERSION', 'rhel9')
    st.caption(f"🔧 Architecture: `{arch}` | RHEL: `{rhel}`")

    cluster_name = config['install_env']['CLUSTER_DOMAIN'].split('.')[0] \
        if '.' in config['install_env']['CLUSTER_DOMAIN'] else config['install_env']['CLUSTER_DOMAIN']
    if cluster_name and config['install_env']['BASE_DOMAIN']:
        registry_fqdn = f"bastion.{cluster_name}.{config['install_env']['BASE_DOMAIN']}"
        st.info(f"📌 Registry URL will be: **{registry_fqdn}:8443**")

def _render_network_nodes(config_manager, config):
    """渲染 Master、Infra、Worker 三類節點的數量與網路配置區塊"""
    st.divider()
    st.subheader("Network & Nodes")
    
    _render_node_section(config_manager, config, "Master", "master_count", 1, 3,
                         "MASTER", "BC:24:11:99:B8:1B", "ens18", "/dev/sda")
    _render_node_section(config_manager, config, "Infra", "infra_count", 0, 3,
                         "INFRA", "BC:24:11:99:B8:1B", "ens18", "/dev/sda")
    _render_node_section(config_manager, config, "Worker", "worker_count", 0, 9,
                         "WORKER", "BC:24:11:99:B8:1B", "ens18", "/dev/sda")

def _render_node_section(config_manager, config, label, count_key, min_val, max_val,
                         prefix, default_mac, default_iface, default_device):
    """渲染單一節點類別的數量選擇器與動態輸入表單"""
    st.markdown(f"#### {label} Nodes")
    cols = st.columns([3, 1])
    with cols[0]:
        st.write(f"Current {label} Count: {st.session_state[count_key]}")
    with cols[1]:
        new_count = st.number_input(
            f"{label} Count", min_value=min_val, max_value=max_val,
            value=st.session_state[count_key], key=f"{count_key}_input"
        )
        if new_count != st.session_state[count_key]:
            _update_node_count(config_manager, config, count_key, new_count, prefix)
    
    # 動態生成輸入框
    for i in range(1, st.session_state[count_key] + 1):
        _render_node_inputs(config, i, prefix, default_mac, default_iface, default_device)

def _update_node_count(config_manager, config, count_key, new_count, prefix):
    """更新節點數量並清理或初始化對應的 IP 欄位"""
    old_count = st.session_state[count_key]
    st.session_state[count_key] = new_count
    
    for i in range(new_count + 1, old_count + 1):
        ip_key = f"{prefix}{i:02d}_IP"
        state_key = f"ip_{ip_key}"
        st.session_state.pop(state_key, None)
        config['install_env'].pop(ip_key, None)
    
    for i in range(old_count + 1, new_count + 1):
        ip_key = f"{prefix}{i:02d}_IP"
        state_key = f"ip_{ip_key}"
        if state_key not in st.session_state:
            st.session_state[state_key] = ""
    
    config_manager.save_config(config)
    st.rerun()

def _render_node_inputs(config, i, prefix, default_mac, default_iface, default_device):
    """渲染單個節點的 IP、MAC、Interface、Device 輸入欄位並即時驗證"""
    ip_key = f"{prefix}{i:02d}_IP"
    mac_key = f"{prefix}{i:02d}_MAC"
    iface_key = f"{prefix}{i:02d}_INTERFACE"
    device_key = f"{prefix}{i:02d}_DEVICE"
    
    # 初始化 session state
    for key, default in [
        (f"ip_{ip_key}", config['install_env'].get(ip_key, "")),
        (f"mac_{mac_key}", config['install_env'].get(mac_key, default_mac)),
        (f"iface_{iface_key}", config['install_env'].get(iface_key, default_iface)),
        (f"device_{device_key}", config['install_env'].get(device_key, default_device))
    ]:
        if key not in st.session_state:
            st.session_state[key] = default
    
    c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
    with c1:
        ip_val = st.text_input(f"{prefix} {i:02d} IP", value=st.session_state[f"ip_{ip_key}"], key=f"input_{ip_key}")
    with c2:
        mac_val = st.text_input(f"{prefix} {i:02d} MAC", value=st.session_state[f"mac_{mac_key}"], key=f"input_{mac_key}")
    with c3:
        iface_val = st.text_input(f"{prefix} {i:02d} Interface", value=st.session_state[f"iface_{iface_key}"], key=f"input_{iface_key}")
    with c4:
        device_val = st.text_input(f"{prefix} {i:02d} Device", value=st.session_state[f"device_{device_key}"], key=f"input_{device_key}")
    
    if ip_val and not _is_valid_ipv4(ip_val):
        st.error("❌ Invalid IP")
    if mac_val and not _is_valid_mac(mac_val):
        st.error("❌ Invalid MAC")
    
    st.session_state[f"ip_{ip_key}"] = ip_val
    st.session_state[f"mac_{mac_key}"] = mac_val
    st.session_state[f"iface_{iface_key}"] = iface_val
    st.session_state[f"device_{device_key}"] = device_val
    config['install_env'][ip_key] = ip_val
    config['install_env'][mac_key] = mac_val
    config['install_env'][iface_key] = iface_val
    config['install_env'][device_key] = device_val

def _render_cluster_form(config_manager, config):
    """渲染包含 Other IPs、網路配置與憑證的提交表單"""
    st.divider()
    with st.form("cluster_config_form"):
        _render_other_ips(config)
        _render_network_config(config)
        _render_credentials(config)
        
        if st.form_submit_button("💾 Save & Generate install-config.yaml"):
            _handle_form_submit(config_manager, config)

def _render_other_ips(config):
    """渲染 Bastion、Gateway、Bootstrap IP 的輸入欄位"""
    st.subheader("Other IPs")
    col_bast, col_gw, col_boot = st.columns(3)
    with col_bast:
        bastion_ip = st.text_input("Bastion IP", value=config['install_env'].get('BASTION_IP', ''), key="bastion_ip_input")
        if bastion_ip and not _is_valid_ipv4(bastion_ip):
            st.error("❌ Invalid IP")
        config['install_env']['BASTION_IP'] = bastion_ip
    with col_gw:
        gateway_ip = st.text_input("Gateway IP", value=config['install_env'].get('GATEWAY_IP', ''), key="gateway_ip_input")
        if gateway_ip and not _is_valid_ipv4(gateway_ip):
            st.error("❌ Invalid IP")
        config['install_env']['GATEWAY_IP'] = gateway_ip
    with col_boot:
        bootstrap_ip = st.text_input("Bootstrap IP (optional)", value=config['install_env'].get('BOOTSTRAP_IP', ''), key="bootstrap_ip_input")
        if bootstrap_ip and not _is_valid_ipv4(bootstrap_ip):
            st.error("❌ Invalid IP")
        config['install_env']['BOOTSTRAP_IP'] = bootstrap_ip

def _render_network_config(config):
    """渲染 Machine/Cluster/Service Network 及 Network Type 的配置區塊"""
    st.subheader("Network Configuration")
    col1, col2 = st.columns(2)
    with col1:
        config['install_env']['MACHINE_NETWORK_CIDR'] = st.text_input(
            "Machine Network CIDR (optional)", value=config['install_env']['MACHINE_NETWORK_CIDR'],
            help="Leave empty to auto-generate from Bastion IP", key="machine_cidr_input")
        config['install_env']['CLUSTER_NETWORK_CIDR'] = st.text_input(
            "Cluster Network CIDR", value=config['install_env']['CLUSTER_NETWORK_CIDR'], key="cluster_cidr_input")
    with col2:
        config['install_env']['CLUSTER_NETWORK_HOST_PREFIX'] = st.number_input(
            "Host Prefix", min_value=1, max_value=32,
            value=int(config['install_env'].get('CLUSTER_NETWORK_HOST_PREFIX', 23)), key="host_prefix_input")
        config['install_env']['SERVICE_NETWORK_CIDR'] = st.text_input(
            "Service Network CIDR", value=config['install_env']['SERVICE_NETWORK_CIDR'], key="service_cidr_input")
    
    config['install_env']['NETWORK_TYPE'] = st.selectbox(
        "Network Type", ["OVNKubernetes", "OpenShiftSDN"],
        index=0 if config['install_env']['NETWORK_TYPE'] == 'OVNKubernetes' else 1, key="network_type_input")

def _render_credentials(config):
    """渲染 Registry Password、SSH Key 及 Trust Bundle 的輸入區塊"""
    st.subheader("Credentials & Keys")
    config['install_env']['REGISTRY_PASSWORD'] = st.text_input(
        "Registry Password", value=config['install_env']['REGISTRY_PASSWORD'], type="password", key="registry_pwd_input")
    
    col1, col2 = st.columns(2)
    with col1:
        ssh_input = st.text_area("SSH Public Key", value=config['install_env']['SSH_KEY'],
                                  height=100, help="貼上 id_rsa.pub 內容或填寫路徑", key="ssh_key_input")
        if "ssh-" in ssh_input or "\n" in ssh_input:
            config['install_env']['SSH_KEY'] = ssh_input
        elif os.path.exists(ssh_input):
            with open(ssh_input, 'r') as f:
                config['install_env']['SSH_KEY'] = f.read().strip()
        else:
            config['install_env']['SSH_KEY'] = ssh_input
    
    with col2:
        trust_input = st.text_area("Additional Trust Bundle (CA Cert)", value=config['install_env']['ADDITIONAL_TRUST_BUNDLE'],
                                    height=150, help="貼上 CA Certificate 內容", key="trust_bundle_input")
        if "BEGIN CERTIFICATE" in trust_input or os.path.exists(trust_input):
            if os.path.exists(trust_input):
                with open(trust_input, 'r') as f:
                    config['install_env']['ADDITIONAL_TRUST_BUNDLE'] = f.read()
            else:
                config['install_env']['ADDITIONAL_TRUST_BUNDLE'] = trust_input
        else:
            config['install_env']['ADDITIONAL_TRUST_BUNDLE'] = trust_input

def _handle_form_submit(config_manager, config):
    """驗證必填欄位後同步節點資料並生成 YAML 配置檔"""
    env = config['install_env']
    if not env['CLUSTER_DOMAIN'] or not env['BASE_DOMAIN']:
        st.error("Cluster Name 和 Base Domain 不能為空")
    elif not env.get('SSH_KEY'):
        st.error("SSH Key 不能為空")
    elif not env.get('REGISTRY_PASSWORD'):
        st.error("Registry Password 不能為空")
    else:
        tool_config = ConfigManager('tool_config.json').get_config()
        tool_version_info = tool_config.get('version_info', {})
        for key, value in tool_version_info.items():
            if key not in config['version_info']:
                config['version_info'][key] = value
        
        _sync_node_data(config)
        config_manager.save_config(config)
        _generate_yamls(config)
        st.session_state.cluster_configured = True

def _sync_node_data(config):
    """將 session state 中的節點資料同步回 config 字典"""
    for prefix, count_key in [("MASTER", "master_count"), ("INFRA", "infra_count"), ("WORKER", "worker_count")]:
        for i in range(1, st.session_state[count_key] + 1):
            for suffix in ["IP", "MAC", "INTERFACE", "DEVICE"]:
                key = f"{prefix}{i:02d}_{suffix}"
                state_key = f"{'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'}_{key}"
                config['install_env'][key] = st.session_state.get(state_key, "")

def _generate_yamls(config):
    """產生 install-config.yaml 與 agent-config.yaml 並顯示預覽"""
    generator = YAMLGenerator(config, CURRENT_DIR)
    
    # 確保目錄存在
    install_source_ocp_dir = os.path.join(CURRENT_DIR, "install_source", "ocp")
    os.makedirs(install_source_ocp_dir, exist_ok=True)
    
    # install-config.yaml
    yaml_content = generator.generate_install_config()
    output_path = os.path.join(install_source_ocp_dir, "install-config.yaml")
    with open(output_path, 'w') as f:
        f.write(yaml_content)
    
    # agent-config.yaml
    agent_yaml = generator.generate_agent_config()
    agent_path = os.path.join(install_source_ocp_dir, "agent-config.yaml")
    with open(agent_path, 'w') as f:
        f.write(agent_yaml)
    
    st.success("✅ Configuration saved & `install-config.yaml` generated!")
    st.success("✅ `agent-config.yaml` generated!")
    
    with st.expander("Preview install-config.yaml"):
        st.code(yaml_content, language="yaml")
    with st.expander("Preview agent-config.yaml"):
        st.code(agent_yaml, language="yaml")

def _render_next_button():
    """當集群配置完成時渲染前往 Operators 頁面的按鈕"""
    if st.session_state.cluster_configured:
        st.divider()
        if st.button("➡️ Next: Operators & CSI", use_container_width=True):
            st.session_state.current_view = 'operators'
            st.rerun()