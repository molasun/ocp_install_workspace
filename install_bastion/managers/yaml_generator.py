"""YAML 生成器 — 根據 cluster_config.json 生成 install-config.yaml 和 agent-config.yaml

與 install_tool/src/yaml_generator.py 邏輯對齊，
但適配 install_bastion 的扁平 config 結構（install_env 字典）。
"""

import base64
import os
from typing import Any, Dict, List, Optional

import yaml


class BastionYAMLGenerator:
    """從 cluster_config.json 生成 OCP 安裝所需的 YAML 檔案"""

    def __init__(self, cluster_config: dict):
        """
        Args:
            cluster_config: 完整的 cluster_config.json（嵌套格式）。
                            master/worker/infra 為陣列，networkConfig 為物件。
        """
        self.raw = cluster_config

        # --- 基礎 ---
        self.cluster_name = cluster_config.get('clusterName', 'ocp4')
        self.base_domain = cluster_config.get('baseDomain', 'example.com')
        self.cluster_name_full = f"{self.cluster_name}.{self.base_domain}"
        self.install_mode = cluster_config.get('mode', 'compact')

        # --- 節點 ---
        bastion = cluster_config.get('bastion', {})
        self.bastion_ip = bastion.get('ip', '')
        self.bastion_name = bastion.get('name', 'bastion')

        bootstrap = cluster_config.get('bootstrap', {})
        self.bootstrap_ip = bootstrap.get('ip', '')
        self.bootstrap_name = bootstrap.get('name', 'bootstrap')

        # --- 安全 ---
        self.ssh_key = cluster_config.get('sshKey', '')
        self.trust_bundle = cluster_config.get('additionalTrustBundle', '')
        self.registry_password = cluster_config.get('registryPassword', 'password')

        # --- 網路 ---
        nc = cluster_config.get('networkConfig', {})
        self.network_type = nc.get('networkType', 'OVNKubernetes')
        self.cluster_cidr = nc.get('clusterNetworkCidr', '10.128.0.0/14')
        self.host_prefix = int(nc.get('clusterNetworkHostPrefix', 23) or 23)
        self.service_cidr = nc.get('serviceNetworkCidr', '172.30.0.0/16')
        self.machine_cidr = nc.get('machineNetworkCidr', '')
        self.gateway_ip = nc.get('gatewayIp', '')

        # --- 版本 ---
        version_info = cluster_config.get('versionInfo', {})
        self.ocp_version = version_info.get('ocpVersion', '4.20')
        self.architecture = version_info.get('architecture', 'amd64')

        # --- 節點列表 ---
        self._build_hosts(cluster_config)

    def _build_hosts(self, cluster_config: dict):
        """從 nested config 格式建構節點清單"""
        hosts = []
        default_device = '/dev/sda'
        default_iface = 'enp1s0'

        def _add_node(node: dict, idx: int, prefix: str):
            name = node.get('name') or f'{prefix}-{idx}'
            ip = node.get('ip', '')
            if ip:
                hosts.append({
                    'name': name,
                    'ip': ip,
                    'mac': node.get('mac', ''),
                    'interface': node.get('interface', default_iface),
                    'device': node.get('device', default_device),
                })

        for i, node in enumerate(cluster_config.get('master', [])):
            _add_node(node, i, 'master')

        if self.install_mode != 'compact':
            for i, node in enumerate(cluster_config.get('infra', [])):
                _add_node(node, i, 'infra')
            for i, node in enumerate(cluster_config.get('worker', [])):
                _add_node(node, i, 'worker')

        self.hosts = hosts

    # ------------------------------------------------------------------
    # install-config.yaml
    # ------------------------------------------------------------------

    def generate_install_config(self) -> str:
        """生成 install-config.yaml 內容"""
        config = {
            'apiVersion': 'v1',
            'baseDomain': self.base_domain,
            'metadata': {
                'name': self.cluster_name,
                'creationTimestamp': None,
            },
            'networking': self._build_networking(),
            'controlPlane': self._build_control_plane(),
            'compute': self._build_compute(),
            'platform': {'none': {}},
            'pullSecret': self._build_pull_secret(),
            'sshKey': self.ssh_key,
        }

        if self.trust_bundle:
            config['additionalTrustBundle'] = self.trust_bundle

        if self.install_mode == 'sno':
            config.pop('compute', None)

        return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _build_networking(self) -> dict:
        networking = {
            'networkType': self.network_type,
            'clusterNetwork': [{
                'cidr': self.cluster_cidr,
                'hostPrefix': self.host_prefix,
            }],
            'serviceNetwork': [self.service_cidr],
        }
        if self.machine_cidr:
            networking['machineNetwork'] = [{'cidr': self.machine_cidr}]
        return networking

    def _build_control_plane(self) -> dict:
        result = {
            'name': 'master',
            'architecture': self.architecture,
            'hyperthreading': 'Enabled',
            'replicas': 1 if self.install_mode == 'sno' else 3,
        }
        if self.install_mode == 'compact':
            result['platform'] = {'agentBareMetal': {}}
        return result

    def _build_compute(self) -> List[dict]:
        replicas = 0 if self.install_mode == 'compact' else 2
        return [{
            'name': 'worker',
            'architecture': self.architecture,
            'hyperthreading': 'Enabled',
            'replicas': replicas,
            'platform': {'agentBareMetal': {}} if self.install_mode == 'compact' else {},
        }]

    def _build_pull_secret(self) -> str:
        creds = f"init:{self.registry_password}"
        return base64.b64encode(creds.encode()).decode()

    # ------------------------------------------------------------------
    # agent-config.yaml
    # ------------------------------------------------------------------

    def generate_agent_config(self) -> str:
        """生成 agent-config.yaml 內容"""
        config = {
            'apiVersion': 'v1beta1',
            'kind': 'AgentConfig',
            'metadata': {
                'name': self.cluster_name,
                'creationTimestamp': None,
            },
            'rendezvousIP': self.hosts[0]['ip'] if self.hosts else '',
        }

        if self.bastion_ip:
            config['additionalNTPSources'] = [self.bastion_ip]

        config['hosts'] = self._build_agent_hosts()

        return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _build_agent_hosts(self) -> List[dict]:
        agent_hosts = []
        for host in self.hosts:
            h = {
                'hostname': host['name'],
                'interfaces': [{
                    'name': host['interface'],
                    'macAddress': host['mac'].lower(),
                }] if host['mac'] and host['interface'] else [],
                'networkConfig': self._build_agent_network(host),
            }
            if host['device'] and host['device'] != '/dev/sda':
                h['rootDeviceHints'] = {'deviceName': host['device']}
            agent_hosts.append(h)
        return agent_hosts

    def _build_agent_network(self, host: dict) -> dict:
        prefix = self._cidr_to_prefix(self.machine_cidr) if self.machine_cidr else 24
        dns_server = self.bastion_ip or '8.8.8.8'
        ip_config = {
            'enabled': True,
            'ipv4': {
                'enabled': True,
                'address': [{'ip': host['ip'], 'prefix-length': prefix}],
                'dhcp': False,
            },
            'ipv6': {'enabled': False},
        }

        # gateway
        if self.gateway_ip:
            ip_config['ipv4']['gateway'] = self.gateway_ip

        config = {
            'interfaces': [{
                'name': host['interface'],
                'type': 'ethernet',
                'state': 'up',
                **({'mac-address': host['mac'].lower()} if host['mac'] else {}),
                **({'ipv4': ip_config['ipv4'], 'ipv6': ip_config['ipv6']}),
            }],
            'dns-resolver': {
                'config': {
                    'server': [dns_server],
                },
            },
        }

        if self.gateway_ip:
            config['routes'] = {
                'config': [{
                    'destination': '0.0.0.0/0',
                    'next-hop-address': self.gateway_ip,
                }],
            }

        return config

    @staticmethod
    def _cidr_to_prefix(cidr: str) -> int:
        try:
            return int(cidr.split('/')[1])
        except (IndexError, ValueError):
            return 24

    # ------------------------------------------------------------------
    # 對比輔助：從當前 YAML 檔案提取關鍵值
    # ------------------------------------------------------------------

    @staticmethod
    def parse_install_config(path: str) -> Optional[dict]:
        """解析 install-config.yaml 並提取對比用欄位"""
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            return None
        if not data:
            return None

        nc = data.get('networking', {})
        cp = data.get('controlPlane', {})

        return {
            'baseDomain': data.get('baseDomain', ''),
            'clusterName': data.get('metadata', {}).get('name', ''),
            'sshKey': data.get('sshKey', ''),
            'additionalTrustBundle': data.get('additionalTrustBundle', ''),
            'networkType': nc.get('networkType', ''),
            'machineNetworkCidr': (nc.get('machineNetwork', [{}])[0].get('cidr', '') if nc.get('machineNetwork') else ''),
            'clusterNetworkCidr': (nc.get('clusterNetwork', [{}])[0].get('cidr', '') if nc.get('clusterNetwork') else ''),
            'clusterNetworkHostPrefix': (nc.get('clusterNetwork', [{}])[0].get('hostPrefix', 0) if nc.get('clusterNetwork') else 0),
            'serviceNetworkCidr': (nc.get('serviceNetwork', [''])[0] if nc.get('serviceNetwork') else ''),
            'controlPlaneReplicas': cp.get('replicas', 0),
            'controlPlaneArchitecture': cp.get('architecture', ''),
        }

    @staticmethod
    def parse_agent_config(path: str) -> Optional[dict]:
        """解析 agent-config.yaml 並提取對比用欄位"""
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            return None
        if not data:
            return None

        hosts = data.get('hosts', [])
        parsed_hosts = []
        for h in hosts:
            nc = h.get('networkConfig', {})
            ifaces = nc.get('interfaces', [{}])
            iface = ifaces[0] if ifaces else {}
            routes = nc.get('routes', {}).get('config', [{}])
            dns = nc.get('dns-resolver', {})

            parsed_hosts.append({
                'hostname': h.get('hostname', ''),
                'ip': (iface.get('ipv4', {}).get('address', [{}])[0].get('ip', '') if iface.get('ipv4', {}).get('address') else ''),
                'prefix': (iface.get('ipv4', {}).get('address', [{}])[0].get('prefix-length', 24) if iface.get('ipv4', {}).get('address') else 24),
                'mac': iface.get('mac-address', h.get('interfaces', [{}])[0].get('macAddress', '')).lower(),
                'interface': iface.get('name', (h.get('interfaces', [{}])[0].get('name', ''))),
                'device': h.get('rootDeviceHints', {}).get('deviceName', ''),
                'gateway': routes[0].get('next-hop-address', '') if routes else '',
                'dns': (dns.get('config', {}).get('server', [''])[0] if dns.get('config', {}).get('server') else ''),
            })

        return {
            'clusterName': data.get('metadata', {}).get('name', ''),
            'rendezvousIP': data.get('rendezvousIP', ''),
            'additionalNTPSources': data.get('additionalNTPSources', []),
            'hosts': parsed_hosts,
        }

    # ------------------------------------------------------------------
    # 對比：比較 cluster_config.json 預期值與實際 YAML
    # ------------------------------------------------------------------

    def compare_install_config(self, yaml_path: str) -> List[Dict[str, str]]:
        """比較 install-config.yaml 與 cluster_config.json 預期值，回傳差異列表"""
        diffs = []
        actual = self.parse_install_config(yaml_path)
        if actual is None:
            return [{'file': 'install-config.yaml', 'field': '-', 'actual': 'FILE_NOT_FOUND', 'expected': '-', 'msg': 'YAML 檔案無法讀取'}]

        # baseDomain
        if actual['baseDomain'] != self.base_domain:
            diffs.append({'file': 'install-config.yaml', 'field': 'baseDomain', 'actual': actual['baseDomain'], 'expected': self.base_domain, 'msg': f'baseDomain'})
        # clusterName
        if actual['clusterName'] != self.cluster_name:
            diffs.append({'file': 'install-config.yaml', 'field': 'metadata.name', 'actual': actual['clusterName'], 'expected': self.cluster_name, 'msg': 'clusterName'})
        # sshKey
        if self.ssh_key and actual['sshKey'] != self.ssh_key:
            diffs.append({'file': 'install-config.yaml', 'field': 'sshKey', 'actual': '[不同]', 'expected': '[不同]', 'msg': 'sshKey 不一致'})
        # additionalTrustBundle
        if self.trust_bundle and actual['additionalTrustBundle'] != self.trust_bundle:
            diffs.append({'file': 'install-config.yaml', 'field': 'additionalTrustBundle', 'actual': '[不同]', 'expected': '[不同]', 'msg': 'additionalTrustBundle 不一致'})
        # networkType
        if actual['networkType'] != self.network_type:
            diffs.append({'file': 'install-config.yaml', 'field': 'networking.networkType', 'actual': actual['networkType'], 'expected': self.network_type, 'msg': 'networkType'})
        # machineNetworkCidr
        if self.machine_cidr and actual['machineNetworkCidr'] != self.machine_cidr:
            diffs.append({'file': 'install-config.yaml', 'field': 'networking.machineNetwork[0].cidr', 'actual': actual['machineNetworkCidr'], 'expected': self.machine_cidr, 'msg': 'machineNetworkCidr'})
        # clusterNetworkCidr
        if actual['clusterNetworkCidr'] != self.cluster_cidr:
            diffs.append({'file': 'install-config.yaml', 'field': 'networking.clusterNetwork[0].cidr', 'actual': actual['clusterNetworkCidr'], 'expected': self.cluster_cidr, 'msg': 'clusterNetworkCidr'})
        # clusterNetworkHostPrefix
        if actual['clusterNetworkHostPrefix'] != self.host_prefix:
            diffs.append({'file': 'install-config.yaml', 'field': 'networking.clusterNetwork[0].hostPrefix', 'actual': str(actual['clusterNetworkHostPrefix']), 'expected': str(self.host_prefix), 'msg': 'hostPrefix'})
        # serviceNetworkCidr
        if actual['serviceNetworkCidr'] != self.service_cidr:
            diffs.append({'file': 'install-config.yaml', 'field': 'networking.serviceNetwork[0]', 'actual': actual['serviceNetworkCidr'], 'expected': self.service_cidr, 'msg': 'serviceNetworkCidr'})
        # controlPlane replicas
        expected_replicas = 1 if self.install_mode == 'sno' else 3
        if actual['controlPlaneReplicas'] != expected_replicas:
            diffs.append({'file': 'install-config.yaml', 'field': 'controlPlane.replicas', 'actual': str(actual['controlPlaneReplicas']), 'expected': str(expected_replicas), 'msg': 'controlPlane replicas'})
        # controlPlane architecture
        if actual['controlPlaneArchitecture'] != self.architecture:
            diffs.append({'file': 'install-config.yaml', 'field': 'controlPlane.architecture', 'actual': actual['controlPlaneArchitecture'], 'expected': self.architecture, 'msg': 'architecture'})
        # pullSecret 不檢查 — cluster_config 存的是明碼，YAML 存的是 base64 編碼

        return diffs

    def compare_agent_config(self, yaml_path: str) -> List[Dict[str, str]]:
        """比較 agent-config.yaml 與 cluster_config.json 預期值，回傳差異列表"""
        diffs = []
        actual = self.parse_agent_config(yaml_path)
        if actual is None:
            return [{'file': 'agent-config.yaml', 'field': '-', 'actual': 'FILE_NOT_FOUND', 'expected': '-', 'msg': 'YAML 檔案無法讀取'}]

        # clusterName
        if actual['clusterName'] != self.cluster_name:
            diffs.append({'file': 'agent-config.yaml', 'field': 'metadata.name', 'actual': actual['clusterName'], 'expected': self.cluster_name, 'msg': 'clusterName'})
        # rendezvousIP
        expected_rendezvous = self.hosts[0]['ip'] if self.hosts else ''
        if actual['rendezvousIP'] != expected_rendezvous:
            diffs.append({'file': 'agent-config.yaml', 'field': 'rendezvousIP', 'actual': actual['rendezvousIP'], 'expected': expected_rendezvous, 'msg': 'rendezvousIP (應為 master-0 IP)'})
        # additionalNTPSources
        if self.bastion_ip:
            ntp_actual = actual['additionalNTPSources']
            if not ntp_actual or ntp_actual[0] != self.bastion_ip:
                diffs.append({'file': 'agent-config.yaml', 'field': 'additionalNTPSources[0]', 'actual': str(ntp_actual), 'expected': self.bastion_ip, 'msg': 'NTP server (bastion IP)'})

        # hosts (逐節點比對)
        for i, expected_host in enumerate(self.hosts):
            if i >= len(actual['hosts']):
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}]', 'actual': 'MISSING', 'expected': expected_host['name'], 'msg': f'缺少 host[{i}]: {expected_host["name"]}'})
                continue

            ah = actual['hosts'][i]
            eh = expected_host
            prefix = self._cidr_to_prefix(self.machine_cidr) if self.machine_cidr else 24
            dns_server = self.bastion_ip or '8.8.8.8'

            # hostname
            if ah['hostname'] != eh['name']:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].hostname', 'actual': ah['hostname'], 'expected': eh['name'], 'msg': f'host[{i}] name'})
            # ip
            if ah['ip'] != eh['ip']:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].networkConfig.ipv4.address', 'actual': ah['ip'], 'expected': eh['ip'], 'msg': f'{eh["name"]} IP'})
            # prefix
            if self.machine_cidr and ah['prefix'] != prefix:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].networkConfig.ipv4.prefix-length', 'actual': str(ah['prefix']), 'expected': str(prefix), 'msg': f'{eh["name"]} prefix-length'})
            # mac
            if eh['mac'] and ah['mac'] != eh['mac'].lower():
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].macAddress', 'actual': ah['mac'], 'expected': eh['mac'].lower(), 'msg': f'{eh["name"]} MAC'})
            # interface
            if eh['interface'] and ah['interface'] != eh['interface']:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].networkConfig.interface', 'actual': ah['interface'], 'expected': eh['interface'], 'msg': f'{eh["name"]} interface'})
            # device
            if eh['device'] and eh['device'] != '/dev/sda' and ah['device'] != eh['device']:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].rootDeviceHints.deviceName', 'actual': ah['device'], 'expected': eh['device'], 'msg': f'{eh["name"]} device'})
            # gateway
            if self.gateway_ip and ah['gateway'] != self.gateway_ip:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].networkConfig.routes.next-hop', 'actual': ah['gateway'], 'expected': self.gateway_ip, 'msg': f'{eh["name"]} gateway'})
            # dns
            if ah['dns'] != dns_server:
                diffs.append({'file': 'agent-config.yaml', 'field': f'hosts[{i}].networkConfig.dns-resolver', 'actual': ah['dns'], 'expected': dns_server, 'msg': f'{eh["name"]} DNS server'})

        return diffs
