import streamlit as st
import os
import re

from i18n import t
from src.config_manager import ConfigManager
from src.yaml_generator import YAMLGenerator

CURRENT_DIR = os.getcwd()
CONFIG_DIR = os.path.join(CURRENT_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)

def show_cluster_config_page():
    """渲染集群配置頁面，包含身份、網路、節點及憑證設定"""
    st.title(t('cluster.title'))
    st.markdown(t('cluster.subtitle'))
    
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

    # 首次載入：確保節點數量與 INSTALL_MODE 一致（處理外部修改 config 的情況）
    if 'prev_install_mode' not in st.session_state:
        mode = install_env.get('INSTALL_MODE', 'standard')
        st.session_state.prev_install_mode = mode
        rules = _MODE_RULES.get(mode, _MODE_RULES['standard'])
        for prefix, count_key, target in [
            ("MASTER", "master_count", rules['master']),
            ("INFRA", "infra_count", rules['infra']),
            ("WORKER", "worker_count", rules['worker']),
        ]:
            current = st.session_state.get(count_key, 0)

            # STANDARD 模式下的 worker: target 是最小值（1），不是精確值
            # 若 config 已有 3 個 worker，不應裁減到 1
            if mode == 'standard' and prefix == 'WORKER':
                if current < target:
                    st.session_state[count_key] = target
            else:
                # target 是精確值
                if current > target:
                    # 超出模式允許的數量，清除多餘節點
                    for i in range(target + 1, current + 1):
                        for suffix in ["IP", "NAME", "MAC", "INTERFACE", "DEVICE"]:
                            key = f"{prefix}{i:02d}_{suffix}"
                            install_env.pop(key, None)
                    st.session_state[count_key] = target
                elif current < target:
                    # 不足模式要求的最低數量
                    st.session_state[count_key] = target

# 各模式對應的節點數量規則
_MODE_RULES = {
    'sno':      {'master': 1, 'infra': 0, 'worker': 0},
    'compact':  {'master': 3, 'infra': 0, 'worker': 0},
    'standard': {'master': 3, 'infra': 0, 'worker': 1},
}

def _apply_mode_rules(config, new_mode):
    """INSTALL_MODE 變更時自動調整節點數量並清理不適用的節點資料

    注意：不調用 st.rerun()，由呼叫方所在的 Streamlit 自然 rerun 機制處理。
    """
    rules = _MODE_RULES.get(new_mode, _MODE_RULES['standard'])
    env = config['install_env']
    env['INSTALL_MODE'] = new_mode

    for prefix, count_key, target_count in [
        ("MASTER", "master_count", rules['master']),
        ("INFRA", "infra_count", rules['infra']),
        ("WORKER", "worker_count", rules['worker']),
    ]:
        old_count = st.session_state.get(count_key, 0)
        st.session_state[count_key] = target_count
        # 刪除舊 widget key，讓 widget 改用 value= 參數讀取新的 count 值
        # （避免 Streamlit 報 "widget was created with a default value but also
        #   had its value set via the Session State API" 的 warn）
        st.session_state.pop(f"{count_key}_input", None)

        # 清理超出目標數量的節點 session_state 與 config 資料
        for i in range(target_count + 1, old_count + 1):
            for suffix in ["IP", "NAME", "MAC", "INTERFACE", "DEVICE"]:
                key = f"{prefix}{i:02d}_{suffix}"
                state_prefix = 'name' if suffix == 'NAME' else 'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'
                state_key = f"{state_prefix}_{key}"
                st.session_state.pop(state_key, None)
                env.pop(key, None)

        # 初始化新增節點的預設值
        for i in range(old_count + 1, target_count + 1):
            for suffix in ["IP", "NAME", "MAC", "INTERFACE", "DEVICE"]:
                key = f"{prefix}{i:02d}_{suffix}"
                state_prefix = 'name' if suffix == 'NAME' else 'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'
                state_key = f"{state_prefix}_{key}"
                if state_key not in st.session_state:
                    if suffix == "NAME":
                        st.session_state[state_key] = f"{prefix.lower()}-{i-1}"
                    else:
                        st.session_state[state_key] = ""

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

def _is_valid_hostname(name):
    """驗證主機名稱格式（RFC 1123）"""
    if not name:
        return False
    # 長度 <= 63，僅小寫字母/數字/連字號，不以連字號開頭或結尾
    pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
    return bool(re.match(pattern, name))

def _collect_all_node_names(config, exclude_prefix=None, exclude_index=None):
    """收集所有節點名稱（用於重複檢查），可排除指定節點

    exclude_prefix 支援 'BASTION'、'BOOTSTRAP' 以及 'MASTER'/'INFRA'/'WORKER'。
    對 BASTION/BOOTSTRAP，exclude_index 不適用（單一節點）。
    """
    env = config.get('install_env', {})
    names = []

    # Bastion / Bootstrap（單一節點，用 prefix 排除）
    for prefix in ['BASTION', 'BOOTSTRAP']:
        if prefix == exclude_prefix:
            continue
        val = env.get(f'{prefix}_NAME', '')
        if val:
            names.append(val)

    # Master / Infra / Worker（多節點，用 prefix + index 排除）
    for prefix in ['MASTER', 'INFRA', 'WORKER']:
        i = 1
        while True:
            ip_key = f"{prefix}{i:02d}_IP"
            if ip_key not in env or not env[ip_key]:
                break
            name_key = f"{prefix}{i:02d}_NAME"
            val = env.get(name_key, '')
            if val and not (prefix == exclude_prefix and i == exclude_index):
                names.append(val)
            i += 1
    return names

def _render_cluster_identity(config):
    """渲染安裝模式、集群名稱與 Base Domain 的輸入區塊"""
    st.subheader(t('cluster.identity'))
    col1, col2, col3 = st.columns(3)
    with col1:
        new_mode = st.selectbox(
            t('cluster.install_mode'),
            ["standard", "compact", "sno"],
            index=["standard", "compact", "sno"].index(config['install_env']['INSTALL_MODE']),
            key="install_mode_select"
        )
        # 檢測模式變更 → 調整節點數量（不調用 st.rerun，讓腳本自然繼續）
        prev_mode = st.session_state.get('prev_install_mode', new_mode)
        if new_mode != prev_mode:
            _apply_mode_rules(config, new_mode)
            st.session_state.prev_install_mode = new_mode
        config['install_env']['INSTALL_MODE'] = new_mode
    with col2:
        config['install_env']['CLUSTER_DOMAIN'] = st.text_input(
            t('cluster.cluster_name'),
            value=config['install_env']['CLUSTER_DOMAIN'],
            help=t('cluster.cluster_name_help'),
            key="cluster_domain_input"
        )
    with col3:
        config['install_env']['BASE_DOMAIN'] = st.text_input(
            t('cluster.base_domain'),
            value=config['install_env']['BASE_DOMAIN'],
            help=t('cluster.base_domain_help'),
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
    
    st.info(t('cluster.ocp_version', version=ocp_version, release=ocp_release))

    arch = config['version_info'].get('ARCHITECTURE', 'amd64')
    rhel = config['version_info'].get('RHEL_VERSION', 'rhel9')
    st.caption(t('cluster.arch_info', arch=arch, rhel=rhel))

    cluster_name = config['install_env']['CLUSTER_DOMAIN'].split('.')[0] \
        if '.' in config['install_env']['CLUSTER_DOMAIN'] else config['install_env']['CLUSTER_DOMAIN']
    if cluster_name and config['install_env']['BASE_DOMAIN']:
        registry_fqdn = f"bastion.{cluster_name}.{config['install_env']['BASE_DOMAIN']}"
        st.info(t('cluster.registry_url', fqdn=registry_fqdn))

def _render_network_nodes(config_manager, config):
    """渲染 Master、Infra、Worker 三類節點的數量與網路配置區塊

    根據 INSTALL_MODE 控制顯示哪些節點區塊：
    - SNO: 僅 Master（鎖定 1）
    - COMPACT: 僅 Master（鎖定 3）
    - STANDARD: Master（鎖定 3）+ Infra（0~3）+ Worker（1~不限）
    """
    st.divider()
    st.subheader(t('cluster.network_nodes'))

    mode = config['install_env'].get('INSTALL_MODE', 'standard')

    # Master 始終顯示，所有模式都鎖定數量
    _render_node_section(config_manager, config, "Master", "master_count", 1, 3,
                         "MASTER", "BC:24:11:99:B8:1B", "ens18", "/dev/sda",
                         disabled=True)

    # Infra 和 Worker 僅在 STANDARD 模式下顯示
    if mode == 'standard':
        _render_node_section(config_manager, config, "Infra", "infra_count", 0, 3,
                             "INFRA", "BC:24:11:99:B8:1B", "ens18", "/dev/sda")
        _render_node_section(config_manager, config, "Worker", "worker_count", 1, 99,
                             "WORKER", "BC:24:11:99:B8:1B", "ens18", "/dev/sda")

def _render_node_section(config_manager, config, label, count_key, min_val, max_val,
                         prefix, default_mac, default_iface, default_device, disabled=False):
    """渲染單一節點類別的數量選擇器與動態輸入表單"""
    st.markdown(f"#### {t('cluster.nodes_label', label=label)}")
    cols = st.columns([3, 1])
    with cols[0]:
        st.write(t('cluster.current_count', label=label, count=st.session_state[count_key]))
    with cols[1]:
        new_count = st.number_input(
            t('cluster.count_input', label=label), min_value=min_val, max_value=max_val,
            value=st.session_state[count_key], key=f"{count_key}_input",
            disabled=disabled
        )
        if not disabled and new_count != st.session_state[count_key]:
            _update_node_count(config_manager, config, count_key, new_count, prefix)
    
    # 動態生成輸入框
    for i in range(1, st.session_state[count_key] + 1):
        _render_node_inputs(config, i, prefix, default_mac, default_iface, default_device)

def _update_node_count(config_manager, config, count_key, new_count, prefix):
    """更新節點數量並清理或初始化對應的 IP/NAME 欄位"""
    old_count = st.session_state[count_key]
    st.session_state[count_key] = new_count
    
    for i in range(new_count + 1, old_count + 1):
        for suffix in ["IP", "NAME", "MAC", "INTERFACE", "DEVICE"]:
            key = f"{prefix}{i:02d}_{suffix}"
            state_prefix = 'name' if suffix == 'NAME' else 'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'
            state_key = f"{state_prefix}_{key}"
            st.session_state.pop(state_key, None)
            config['install_env'].pop(key, None)
    
    for i in range(old_count + 1, new_count + 1):
        for suffix in ["IP", "NAME", "MAC", "INTERFACE", "DEVICE"]:
            key = f"{prefix}{i:02d}_{suffix}"
            state_prefix = 'name' if suffix == 'NAME' else 'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'
            state_key = f"{state_prefix}_{key}"
            if state_key not in st.session_state:
                if suffix == "NAME":
                    st.session_state[state_key] = f"{prefix.lower()}-{i-1}"
                else:
                    st.session_state[state_key] = ""
    
    config_manager.save_config(config)
    st.rerun()

def _render_node_inputs(config, i, prefix, default_mac, default_iface, default_device):
    """渲染單個節點的 Name、IP、MAC、Interface、Device 輸入欄位並即時驗證"""
    ip_key = f"{prefix}{i:02d}_IP"
    mac_key = f"{prefix}{i:02d}_MAC"
    iface_key = f"{prefix}{i:02d}_INTERFACE"
    device_key = f"{prefix}{i:02d}_DEVICE"
    name_key = f"{prefix}{i:02d}_NAME"
    default_name = f"{prefix.lower()}-{i-1}"
    
    # 初始化 session state
    for key, default in [
        (f"name_{name_key}", config['install_env'].get(name_key, default_name)),
        (f"ip_{ip_key}", config['install_env'].get(ip_key, "")),
        (f"mac_{mac_key}", config['install_env'].get(mac_key, default_mac)),
        (f"iface_{iface_key}", config['install_env'].get(iface_key, default_iface)),
        (f"device_{device_key}", config['install_env'].get(device_key, default_device))
    ]:
        if key not in st.session_state:
            st.session_state[key] = default
    
    c0, c1, c2, c3, c4 = st.columns([2, 3, 3, 2, 2])
    with c0:
        name_val = st.text_input(t('cluster.node_name', prefix=prefix, index=i), value=st.session_state[f"name_{name_key}"], key=f"input_{name_key}")
    with c1:
        ip_val = st.text_input(t('cluster.node_ip', prefix=prefix, index=i), value=st.session_state[f"ip_{ip_key}"], key=f"input_{ip_key}")
    with c2:
        mac_val = st.text_input(t('cluster.node_mac', prefix=prefix, index=i), value=st.session_state[f"mac_{mac_key}"], key=f"input_{mac_key}")
    with c3:
        iface_val = st.text_input(t('cluster.node_iface', prefix=prefix, index=i), value=st.session_state[f"iface_{iface_key}"], key=f"input_{iface_key}")
    with c4:
        device_val = st.text_input(t('cluster.node_device', prefix=prefix, index=i), value=st.session_state[f"device_{device_key}"], key=f"input_{device_key}")
    
    if name_val and not _is_valid_hostname(name_val):
        st.error(t('cluster.error_hostname'))
    elif name_val and name_val in _collect_all_node_names(config, exclude_prefix=prefix, exclude_index=i):
        st.error(t('cluster.error_dup_hostname'))
    if ip_val and not _is_valid_ipv4(ip_val):
        st.error(t('cluster.error_ip'))
    if mac_val and not _is_valid_mac(mac_val):
        st.error(t('cluster.error_mac'))
    
    st.session_state[f"name_{name_key}"] = name_val
    st.session_state[f"ip_{ip_key}"] = ip_val
    st.session_state[f"mac_{mac_key}"] = mac_val
    st.session_state[f"iface_{iface_key}"] = iface_val
    st.session_state[f"device_{device_key}"] = device_val
    config['install_env'][name_key] = name_val
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
        
        if st.form_submit_button(t('cluster.save_generate')):
            _handle_form_submit(config_manager, config)

def _render_other_ips(config):
    """渲染 Bastion、Gateway、Bootstrap 的名稱與 IP 輸入欄位"""
    st.subheader(t('cluster.other_nodes'))
    
    # Bastion Name + IP
    st.markdown(t('cluster.bastion'))
    col_bast_name, col_bast_ip = st.columns([1, 2])
    with col_bast_name:
        bastion_name = st.text_input(
            t('cluster.bastion_name'), value=config['install_env'].get('BASTION_NAME', 'bastion'), key="bastion_name_input")
        if bastion_name and not _is_valid_hostname(bastion_name):
            st.error(t('cluster.error_hostname'))
        elif bastion_name and bastion_name in _collect_all_node_names(config, exclude_prefix='BASTION'):
            st.error(t('cluster.error_dup_hostname'))
        config['install_env']['BASTION_NAME'] = bastion_name
    with col_bast_ip:
        bastion_ip = st.text_input(t('cluster.bastion_ip'), value=config['install_env'].get('BASTION_IP', ''), key="bastion_ip_input")
        if bastion_ip and not _is_valid_ipv4(bastion_ip):
            st.error(t('cluster.error_ip'))
        config['install_env']['BASTION_IP'] = bastion_ip
    
    # Bootstrap Name + IP
    st.markdown(t('cluster.bootstrap'))
    col_boot_name, col_boot_ip = st.columns([1, 2])
    with col_boot_name:
        bootstrap_name = st.text_input(
            t('cluster.bootstrap_name'), value=config['install_env'].get('BOOTSTRAP_NAME', 'bootstrap'), key="bootstrap_name_input")
        if bootstrap_name and not _is_valid_hostname(bootstrap_name):
            st.error(t('cluster.error_hostname'))
        elif bootstrap_name and bootstrap_name in _collect_all_node_names(config, exclude_prefix='BOOTSTRAP'):
            st.error(t('cluster.error_dup_hostname'))
        config['install_env']['BOOTSTRAP_NAME'] = bootstrap_name
    with col_boot_ip:
        bootstrap_ip = st.text_input(t('cluster.bootstrap_ip'), value=config['install_env'].get('BOOTSTRAP_IP', ''), key="bootstrap_ip_input")
        if bootstrap_ip and not _is_valid_ipv4(bootstrap_ip):
            st.error(t('cluster.error_ip'))
        config['install_env']['BOOTSTRAP_IP'] = bootstrap_ip
    
    # Gateway IP
    st.markdown(t('cluster.gateway'))
    gateway_ip = st.text_input(t('cluster.gateway_ip'), value=config['install_env'].get('GATEWAY_IP', ''), key="gateway_ip_input")
    if gateway_ip and not _is_valid_ipv4(gateway_ip):
        st.error(t('cluster.error_ip'))
    config['install_env']['GATEWAY_IP'] = gateway_ip

def _render_network_config(config):
    """渲染 Machine/Cluster/Service Network 及 Network Type 的配置區塊"""
    st.subheader(t('cluster.network_config'))
    col1, col2 = st.columns(2)
    with col1:
        config['install_env']['MACHINE_NETWORK_CIDR'] = st.text_input(
            t('cluster.machine_cidr'), value=config['install_env']['MACHINE_NETWORK_CIDR'],
            help=t('cluster.machine_cidr_help'), key="machine_cidr_input")
        config['install_env']['CLUSTER_NETWORK_CIDR'] = st.text_input(
            t('cluster.cluster_cidr'), value=config['install_env']['CLUSTER_NETWORK_CIDR'], key="cluster_cidr_input")
    with col2:
        config['install_env']['CLUSTER_NETWORK_HOST_PREFIX'] = st.number_input(
            t('cluster.host_prefix'), min_value=1, max_value=32,
            value=int(config['install_env'].get('CLUSTER_NETWORK_HOST_PREFIX', 23)), key="host_prefix_input")
        config['install_env']['SERVICE_NETWORK_CIDR'] = st.text_input(
            t('cluster.service_cidr'), value=config['install_env']['SERVICE_NETWORK_CIDR'], key="service_cidr_input")
    
    config['install_env']['NETWORK_TYPE'] = st.selectbox(
        t('cluster.network_type'), ["OVNKubernetes", "OpenShiftSDN"],
        index=0 if config['install_env']['NETWORK_TYPE'] == 'OVNKubernetes' else 1, key="network_type_input")

def _render_credentials(config):
    """渲染 Registry Password、SSH Key 及 Trust Bundle 的輸入區塊"""
    st.subheader(t('cluster.credentials'))
    config['install_env']['REGISTRY_PASSWORD'] = st.text_input(
        t('cluster.registry_password'), value=config['install_env']['REGISTRY_PASSWORD'], type="password", key="registry_pwd_input")
    
    # 每次都從 install_source/.ssh/id_rsa.pub 讀取公鑰並覆蓋 UI
    pubkey_path = os.path.join(CURRENT_DIR, 'install_source', '.ssh', 'id_rsa.pub')
    ssh_default = ''
    if os.path.exists(pubkey_path):
        try:
            with open(pubkey_path, 'r') as f:
                ssh_default = f.read().strip()
        except Exception:
            ssh_default = ''
    
    if ssh_default:
        config['install_env']['SSH_KEY'] = ssh_default
    # 透過 session_state 覆蓋 widget 值（不可同時傳 value= 參數）
    st.session_state['ssh_key_input'] = ssh_default
    
    col1, col2 = st.columns(2)
    with col1:
        ssh_input = st.text_area(t('cluster.ssh_key'),
                                  height=100, help=t('cluster.ssh_key_help'), key="ssh_key_input")
        if "ssh-" in ssh_input or "\n" in ssh_input:
            config['install_env']['SSH_KEY'] = ssh_input
        elif os.path.exists(ssh_input):
            with open(ssh_input, 'r') as f:
                config['install_env']['SSH_KEY'] = f.read().strip()
        else:
            config['install_env']['SSH_KEY'] = ssh_input
    
    with col2:
        trust_input = st.text_area(t('cluster.trust_bundle'), value=config['install_env']['ADDITIONAL_TRUST_BUNDLE'],
                                    height=150, help=t('cluster.trust_bundle_help'), key="trust_bundle_input")
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
        st.error(t('cluster.error_empty_name'))
    elif not env.get('SSH_KEY'):
        st.error(t('cluster.error_empty_ssh'))
    elif not env.get('REGISTRY_PASSWORD'):
        st.error(t('cluster.error_empty_password'))
    else:
        # 驗證模式相關的節點數量
        mode = env.get('INSTALL_MODE', 'standard')
        master_count = st.session_state.master_count
        worker_count = st.session_state.worker_count

        if mode == 'sno' and master_count != 1:
            st.error(t('cluster.error_sno_master'))
            return
        elif mode == 'compact' and master_count != 3:
            st.error(t('cluster.error_compact_master'))
            return
        elif mode == 'standard':
            if master_count != 3:
                st.error(t('cluster.error_standard_master'))
                return
            if worker_count < 1:
                st.error(t('cluster.error_standard_worker'))
                return

        # 驗證所有節點名稱
        all_names = _collect_all_node_names(config)
        if len(all_names) != len(set(all_names)):
            st.error(t('cluster.error_dup_names'))
            return
        
        # 驗證名稱格式
        invalid_names = [n for n in all_names if not _is_valid_hostname(n)]
        if invalid_names:
            st.error(t('cluster.error_invalid_names', names=', '.join(invalid_names)))
            return
        
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
            for suffix in ["NAME", "IP", "MAC", "INTERFACE", "DEVICE"]:
                key = f"{prefix}{i:02d}_{suffix}"
                state_prefix = 'name' if suffix == 'NAME' else 'ip' if suffix == 'IP' else 'mac' if suffix == 'MAC' else 'iface' if suffix == 'INTERFACE' else 'device'
                state_key = f"{state_prefix}_{key}"
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
    
    st.success(t('cluster.config_saved'))
    st.success(t('cluster.agent_config_saved'))
    
    with st.expander(t('cluster.preview_install')):
        st.code(yaml_content, language="yaml")
    with st.expander(t('cluster.preview_agent')):
        st.code(agent_yaml, language="yaml")

def _render_next_button():
    """當集群配置完成時渲染前往 Operators 頁面的按鈕"""
    if st.session_state.cluster_configured:
        st.divider()
        if st.button(t('cluster.next_operators'), use_container_width=True):
            st.session_state.current_view = 'operators'
            st.rerun()
