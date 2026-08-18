"""將內存 host_config 持久化回寫 cluster_config.json

獨立成模組以打破 install_app ↔ steps.step1_config 的循環依賴。
"""
import os
import json

import streamlit as st


def persist_host_config(host_config: dict) -> bool:
    """將內存中的 host_config（camelCase 嵌套結構）寫回磁盤 cluster_config.json

    這是 parse_host_config 的逆操作：僅更新允許編輯的欄位
    （節點 ip/mac/device、networkConfig 的 CIDR），其餘欄位保持磁盤原值不動。

    Args:
        host_config: 內存態配置（st.session_state.config_params）

    Returns:
        是否寫入成功
    """
    # install_bastion 根目錄（本檔案位於 managers/ 下，需向上兩層）
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config', 'cluster_config.json')

    # 讀取磁盤原始內容，保留 install_env 的其餘欄位
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            disk_config = json.load(f)
    except Exception as e:
        st.error(f"讀取 cluster_config.json 失敗: {e}")
        return False

    env = disk_config.setdefault('install_env', {})

    # ── 1. 寫回節點 ip / mac / device ──
    node_groups = [
        ('master', 'MASTER'),
        ('worker', 'WORKER'),
        ('infra', 'INFRA'),
    ]
    for group_key, prefix in node_groups:
        nodes = host_config.get(group_key, [])
        for idx, node in enumerate(nodes, start=1):
            key = f"{prefix}{idx:02d}"
            if node.get('name') is not None:
                env[f"{key}_NAME"] = node.get('name', '')
            env[f"{key}_IP"] = node.get('ip', '')
            env[f"{key}_MAC"] = node.get('mac', '')
            env[f"{key}_DEVICE"] = node.get('device', '')

    # ── 2. 寫回 CIDR（machine / cluster / service）──
    net = host_config.get('networkConfig', {})
    net_field_map = {
        'machineNetworkCidr': 'MACHINE_NETWORK_CIDR',
        'clusterNetworkCidr': 'CLUSTER_NETWORK_CIDR',
        'serviceNetworkCidr': 'SERVICE_NETWORK_CIDR',
    }
    for config_key, env_key in net_field_map.items():
        if config_key in net:
            env[env_key] = net[config_key]

    # ── 3. 寫回磁盤 ──
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(disk_config, f, indent=2, ensure_ascii=False)
            f.write('\n')
        return True
    except Exception as e:
        st.error(f"寫入 cluster_config.json 失敗: {e}")
        return False
