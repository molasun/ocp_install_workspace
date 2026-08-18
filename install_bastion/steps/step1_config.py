import copy

import streamlit as st
import time
import os
from i18n import t
from managers.yaml_generator import BastionYAMLGenerator
from managers.base_manager import BaseManager
from managers.config_persist import persist_host_config


def render_step1_config():
    """步驟1: 確認環境配置"""
    st.header(t('step1.header'))
    st.markdown(t('step1.subtitle'))
    
    config = st.session_state.get('config_params', {})

    # 編輯副本：編輯只改副本，點「保存」才寫回 config_params 與磁盤
    if 'editing_config' not in st.session_state:
        st.session_state.editing_config = copy.deepcopy(config)
    editing = st.session_state.editing_config

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
    
    # 輔助函數：渲染節點表格（ip/mac/device 可編輯）
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
                node['ip'] = st.text_input(
                    t('step1.node_ip'),
                    value=node.get('ip', ''),
                    key=f"cfg_{prefix}_{idx}_ip"
                )
            with cols[2]:
                node['mac'] = st.text_input(
                    t('step1.node_mac'),
                    value=node.get('mac', ''),
                    key=f"cfg_{prefix}_{idx}_mac"
                )
            with cols[3]:
                node['device'] = st.text_input(
                    t('step1.node_device'),
                    value=node.get('device', ''),
                    key=f"cfg_{prefix}_{idx}_device"
                )
    
    # Master 節點
    render_node_group(t('step1.master_nodes'), editing.get('master', []), "master")
    
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
    render_node_group(t('step1.worker_nodes'), editing.get('worker', []), "worker")
    
    # Infra 節點
    render_node_group(t('step1.infra_nodes'), editing.get('infra', []), "infra")
    
    # === 網路配置 ===
    net_config = editing.get('networkConfig', {})
    if net_config:
        st.subheader(t('step1.network_config'))
        col_n1, col_n2 = st.columns(2)
        with col_n1:
            if 'machineNetworkCidr' in net_config:
                net_config['machineNetworkCidr'] = st.text_input(
                    "Machine Network CIDR", 
                    value=net_config['machineNetworkCidr'], 
                    key="cfg_machine_cidr"
                )
            if 'clusterNetworkCidr' in net_config:
                net_config['clusterNetworkCidr'] = st.text_input(
                    "Cluster Network CIDR", 
                    value=net_config['clusterNetworkCidr'], 
                    key="cfg_cluster_cidr"
                )
            if 'serviceNetworkCidr' in net_config:
                net_config['serviceNetworkCidr'] = st.text_input(
                    "Service Network CIDR", 
                    value=net_config['serviceNetworkCidr'], 
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

    # === 保存節點/網路配置（持久化回寫 cluster_config.json） ===
    st.subheader(t('step1.save_config'))
    st.caption(t('step1.save_config_hint'))
    if st.button(t('step1.save_config_button'), key="btn_save_config"):
        if persist_host_config(editing):
            st.session_state.config_params = copy.deepcopy(editing)
            st.session_state.original_config = copy.deepcopy(editing)
            st.success(t('step1.save_config_success'))
            time.sleep(1)
            st.rerun()
        else:
            st.error(t('step1.save_config_failed'))

    st.markdown("---")

    # === YAML 一致性檢查 ===
    _render_yaml_consistency_check(config)

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


def _render_yaml_consistency_check(config: dict):
    """檢查 install_source/ocp 下的 YAML 是否與 cluster_config.json 一致"""
    st.subheader("📄 YAML 配置文件一致性檢查")

    home_dir = BaseManager._get_real_home()
    ocp_dir = os.path.join(home_dir, "install_source", "ocp")
    install_config_path = os.path.join(ocp_dir, "install-config.yaml")
    agent_config_path = os.path.join(ocp_dir, "agent-config.yaml")

    try:
        generator = BastionYAMLGenerator(config)
    except Exception as e:
        st.error(f"無法初始化 YAML 生成器: {e}")
        return

    install_exists = os.path.exists(install_config_path)
    agent_exists = os.path.exists(agent_config_path)

    # YAML 都不存在 → 直接提供生成按鈕
    if not install_exists and not agent_exists:
        st.warning("YAML 文件尚不存在，請生成 `install-config.yaml` 和 `agent-config.yaml`")
        _render_regenerate_button(config, generator, install_config_path, agent_config_path)
        return

    # 對比差異
    all_diffs = []
    if install_exists:
        all_diffs.extend(generator.compare_install_config(install_config_path))
    else:
        all_diffs.append({'file': 'install-config.yaml', 'field': '-', 'actual': 'MISSING', 'expected': '-', 'msg': '檔案不存在'})

    if agent_exists:
        all_diffs.extend(generator.compare_agent_config(agent_config_path))
    else:
        all_diffs.append({'file': 'agent-config.yaml', 'field': '-', 'actual': 'MISSING', 'expected': '-', 'msg': '檔案不存在'})

    if not all_diffs:
        st.success("✅ YAML 文件與 `cluster_config.json` 完全一致")
        return

    # 有差異 — 展示差異表 + 重新生成按鈕
    st.warning(f"⚠️ 發現 {len(all_diffs)} 處不一致")

    # 按 file 分組展示
    for file_name in ['install-config.yaml', 'agent-config.yaml']:
        file_diffs = [d for d in all_diffs if d.get('file') == file_name]
        if not file_diffs:
            continue
        with st.expander(f"{file_name} ({len(file_diffs)} 處差異)", expanded=True):
            for d in file_diffs:
                st.markdown(
                    f"- ❌ **{d['msg']}**  \n"
                    f"  - 當前值: `{d['actual']}`  \n"
                    f"  - 預期值: `{d['expected']}`"
                )

    _render_regenerate_button(config, generator, install_config_path, agent_config_path)


def _render_regenerate_button(config, generator, install_config_path, agent_config_path):
    """渲染重新生成 YAML 的按鈕與 preview

    使用 session_state 緩存生成結果，避免 st.button 點完後 preview 消失。
    """
    if st.button("🔄 重新生成 YAML 文件", type="primary", use_container_width=True):
        try:
            st.session_state['_yaml_install'] = generator.generate_install_config()
            st.session_state['_yaml_agent'] = generator.generate_agent_config()
            st.session_state['_yaml_generated'] = True
        except Exception as e:
            st.error(f"生成 YAML 時出錯: {e}")
            st.session_state['_yaml_generated'] = False

    # 顯示 preview + 寫入按鈕（緩存存在時）
    if st.session_state.get('_yaml_generated'):
        install_yaml = st.session_state['_yaml_install']
        agent_yaml = st.session_state['_yaml_agent']

        col1, col2 = st.columns(2)
        with col1:
            with st.expander("📄 install-config.yaml (preview)", expanded=True):
                st.code(install_yaml, language="yaml")
        with col2:
            with st.expander("📄 agent-config.yaml (preview)", expanded=True):
                st.code(agent_yaml, language="yaml")

        col_w1, col_w2 = st.columns(2)
        with col_w1:
            if st.button("✅ 確認寫入 install-config.yaml", use_container_width=True):
                try:
                    os.makedirs(os.path.dirname(install_config_path), exist_ok=True)
                    with open(install_config_path, 'w') as f:
                        f.write(install_yaml)
                    st.success(f"✅ 已寫入 {install_config_path}")
                    _clear_yaml_session()
                    st.rerun()
                except Exception as e:
                    st.error(f"寫入失敗: {e}")
        with col_w2:
            if st.button("✅ 確認寫入 agent-config.yaml", use_container_width=True):
                try:
                    os.makedirs(os.path.dirname(agent_config_path), exist_ok=True)
                    with open(agent_config_path, 'w') as f:
                        f.write(agent_yaml)
                    st.success(f"✅ 已寫入 {agent_config_path}")
                    _clear_yaml_session()
                    st.rerun()
                except Exception as e:
                    st.error(f"寫入失敗: {e}")


def _clear_yaml_session():
    """清除 YAML 生成相關的 session_state"""
    st.session_state.pop('_yaml_generated', None)
    st.session_state.pop('_yaml_install', None)
    st.session_state.pop('_yaml_agent', None)
