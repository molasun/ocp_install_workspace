import streamlit as st
import time
from i18n import t


def render_step1_config():
    """步驟1: 確認環境配置"""
    st.header(t('step1.header'))
    st.markdown(t('step1.subtitle'))
    
    config = st.session_state.get('config_params', {})
    
    # === 基本環境資訊（唯讀） ===
    st.subheader(t('step1.env_info'))
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.text_input(
            t('step1.cluster_name'), 
            value=config.get('clusterName', 'N/A'), 
            disabled=True, 
            key="cfg_cluster_name"
        )
        st.text_input(
            t('step1.base_domain'), 
            value=config.get('baseDomain', 'N/A'), 
            disabled=True, 
            key="cfg_base_domain"
        )
        st.text_input(
            t('step1.interface'), 
            value=config.get('interface', 'N/A'), 
            disabled=True, 
            key="cfg_interface"
        )
        
    with col2:
        st.text_input(
            t('step1.bastion_ip'), 
            value=config.get('bastion', {}).get('ip', 'N/A'), 
            disabled=True, 
            key="cfg_bastion_ip"
        )
        st.text_input(
            t('step1.mode'), 
            value=config.get('mode', 'N/A'), 
            disabled=True, 
            key="cfg_mode"
        )
        st.text_input(
            t('step1.dns_upstream'), 
            value=config.get('dns_upstream', 'N/A'), 
            disabled=True, 
            key="cfg_dns_upstream"
        )
    
    # === 版本資訊（唯讀） ===
    version_info = config.get('versionInfo', {})
    if version_info:
        st.subheader(t('step1.version_info'))
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            st.text_input(
                "OCP Version", 
                value=version_info.get('ocpVersion', 'N/A'), 
                disabled=True, 
                key="cfg_ocp_version"
            )
        with col_v2:
            st.text_input(
                "OCP Release", 
                value=version_info.get('ocpRelease', 'N/A'), 
                disabled=True, 
                key="cfg_ocp_release"
            )
    
    # === 節點配置（唯讀） ===
    st.subheader(t('step1.node_config'))
    
    # 輔助函數：渲染節點表格
    def render_node_group(title: str, nodes: list, prefix: str):
        if not nodes:
            return
        st.markdown(f"**{title}**")
        for idx, node in enumerate(nodes):
            cols = st.columns(4)
            with cols[0]:
                st.text_input(
                    t('step1.node_name'), 
                    value=node.get('name', 'N/A'), 
                    disabled=True, 
                    key=f"cfg_{prefix}_{idx}_name"
                )
            with cols[1]:
                st.text_input(
                    t('step1.node_ip'), 
                    value=node.get('ip', 'N/A'), 
                    disabled=True, 
                    key=f"cfg_{prefix}_{idx}_ip"
                )
            with cols[2]:
                st.text_input(
                    t('step1.node_mac'), 
                    value=node.get('mac', 'N/A'), 
                    disabled=True, 
                    key=f"cfg_{prefix}_{idx}_mac"
                )
            with cols[3]:
                st.text_input(
                    t('step1.node_device'), 
                    value=node.get('device', 'N/A'), 
                    disabled=True, 
                    key=f"cfg_{prefix}_{idx}_device"
                )
    
    # Master 節點
    render_node_group(t('step1.master_nodes'), config.get('master', []), "master")
    
    # Bootstrap 節點
    bootstrap = config.get('bootstrap', {})
    st.markdown(f"**{t('step1.bootstrap_node')}**")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.text_input(
            t('step1.bootstrap_name'), 
            value=bootstrap.get('name', 'N/A'), 
            disabled=True, 
            key="cfg_bootstrap_name"
        )
    with col_b2:
        st.text_input(
            t('step1.bootstrap_ip'), 
            value=bootstrap.get('ip', 'N/A'), 
            disabled=True, 
            key="cfg_bootstrap_ip"
        )
    
    # Worker 節點
    render_node_group(t('step1.worker_nodes'), config.get('worker', []), "worker")
    
    # Infra 節點
    render_node_group(t('step1.infra_nodes'), config.get('infra', []), "infra")
    
    # === 網路配置 ===
    net_config = config.get('networkConfig', {})
    if net_config:
        st.subheader(t('step1.network_config'))
        col_n1, col_n2 = st.columns(2)
        with col_n1:
            if 'machineNetworkCidr' in net_config:
                st.text_input(
                    "Machine Network CIDR", 
                    value=net_config['machineNetworkCidr'], 
                    disabled=True, 
                    key="cfg_machine_cidr"
                )
            if 'clusterNetworkCidr' in net_config:
                st.text_input(
                    "Cluster Network CIDR", 
                    value=net_config['clusterNetworkCidr'], 
                    disabled=True, 
                    key="cfg_cluster_cidr"
                )
            if 'serviceNetworkCidr' in net_config:
                st.text_input(
                    "Service Network CIDR", 
                    value=net_config['serviceNetworkCidr'], 
                    disabled=True, 
                    key="cfg_service_cidr"
                )
        with col_n2:
            if 'networkType' in net_config:
                st.text_input(
                    "Network Type", 
                    value=net_config['networkType'], 
                    disabled=True, 
                    key="cfg_network_type"
                )
            if 'clusterNetworkHostPrefix' in net_config:
                st.text_input(
                    "Host Prefix", 
                    value=str(net_config['clusterNetworkHostPrefix']), 
                    disabled=True, 
                    key="cfg_host_prefix"
                )
            if 'gatewayIp' in net_config:
                st.text_input(
                    "Gateway IP", 
                    value=net_config['gatewayIp'], 
                    disabled=True, 
                    key="cfg_gateway_ip"
                )
    
    st.markdown("---")
    
    # === 安裝選項（可修改的勾選） ===
    st.subheader(t('step1.install_tools'))
    
    install_options = st.session_state.get('install_options', {})
    
    col_opt1, col_opt2, col_opt3 = st.columns(3)
    
    with col_opt1:
        firewalld_disable = st.checkbox(
            t('step1.opt_firewalld'), 
            value=install_options.get('firewalld_disable', True),
            key="opt_firewalld"
        )
        selinux_disable = st.checkbox(
            t('step1.opt_selinux'), 
            value=install_options.get('selinux_disable', True),
            key="opt_selinux"
        )
        dns_configure = st.checkbox(
            t('step1.opt_dns'), 
            value=install_options.get('dns_configure', True),
            key="opt_dns"
        )
        
    with col_opt2:
        dns_check = st.checkbox(
            t('step1.opt_dns_check'), 
            value=install_options.get('dns_check', True),
            key="opt_dns_check"
        )
        haproxy_configure = st.checkbox(
            t('step1.opt_haproxy'), 
            value=install_options.get('haproxy_configure', True),
            key="opt_haproxy"
        )
        ntp_server_configure = st.checkbox(
            t('step1.opt_ntp'), 
            value=install_options.get('ntp_server_configure', True),
            key="opt_ntp"
        )
        
    with col_opt3:
        registry_configure = st.checkbox(
            t('step1.opt_registry'), 
            value=install_options.get('registry_configure', True),
            key="opt_registry"
        )
    
    st.markdown("---")
    
    # === 確認按鈕 ===
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    
    with col_btn1:
        if st.button(t('step1.confirm'), type="primary", key="btn_confirm_step1"):
            # 保存安裝選項
            st.session_state.install_options = {
                'firewalld_disable': firewalld_disable,
                'selinux_disable': selinux_disable,
                'dns_configure': dns_configure,
                'dns_check': dns_check,
                'haproxy_configure': haproxy_configure,
                'ntp_server_configure': ntp_server_configure,
                'registry_configure': registry_configure,
            }
            
            # 合併到 config_params
            st.session_state.config_params.update(st.session_state.install_options)            
            st.session_state.step1_complete = True
            st.session_state.current_step = 2
            st.success(t('step1.confirm_success'))
            time.sleep(1)
            st.rerun()
    
    with col_btn2:
        if st.button(t('step1.reset'), key="btn_reset_step1"):
            st.session_state.install_options = {
                'firewalld_disable': True,
                'selinux_disable': True,
                'dns_configure': True,
                'dns_check': True,
                'haproxy_configure': True,
                'ntp_server_configure': True,
                'registry_configure': True,
            }
            st.rerun()
