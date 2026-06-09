import json
import os
import yaml
import re
import base64

class LiteralString(str):
    """用於標記需要在 YAML 中使用 | 的字串"""
    pass

class QuotedString(str):
    """用於標記需要在 YAML 中使用引號的字串"""
    pass

def _literal_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

def _quoted_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="'")

def _str_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(LiteralString, _literal_str_representer)
yaml.add_representer(QuotedString, _quoted_str_representer)
yaml.add_representer(str, _str_representer)

def _load_json(path):
    """安全讀取 JSON 檔案"""
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return None

def _is_valid_ipv4(ip):
    """驗證 IPv4 格式"""
    if not ip:
        return False
    m = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', ip)
    return m and all(int(g) <= 255 for g in m.groups())

class YAMLGenerator:
    def __init__(self, config, current_dir):
        self.config = config
        self.current_dir = current_dir
        self.config_dir = os.path.join(current_dir, 'config')
        self.v_info = config.get('version_info', {})
        self.csi_info = config.get('csi_info', {})
        self.env = config.get('install_env', {})

    def _count_nodes(self, prefix):
        """計算指定前綴的節點數量"""
        return sum(1 for k in self.env if k.startswith(prefix) and k.endswith('_IP') and self.env[k])
    
    def _cluster_name(self):
        """提取 cluster name"""
        domain = self.env.get('CLUSTER_DOMAIN', 'ocp4')
        return domain.split('.')[0] if '.' in domain else domain
    
    def _get_env(self, key, default=''):
        """安全獲取 env 值"""
        return self.env.get(key, default)

    def validate_ips(self):
        """驗證所有 IP 欄位"""
        ip_fields = []
        for prefix, max_i in [("MASTER", 3), ("INFRA", 3), ("WORKER", 10)]:
            for i in range(1, max_i):
                key = f"{prefix}{i:02d}_IP"
                if self._get_env(key):
                    ip_fields.append((key, self.env[key]))
        
        for key in ['BASTION_IP', 'BOOTSTRAP_IP']:
            if self._get_env(key):
                ip_fields.append((key, self.env[key]))
        
        return [f"{k}: {v}" for k, v in ip_fields if not _is_valid_ipv4(v)]

    def get_ocp_version_path(self):
        """從 OCP_RELEASE 提取版本號"""
        ocp = self.v_info.get('OCP_RELEASE', '4.20.8')
        m = re.match(r'(\d+)\.(\d+)', ocp)
        return f"ocp{m.group(1)}{m.group(2)}" if m else "ocp420"
    
    def get_registry_fqdn(self):
        """生成 registry FQDN"""
        name = self._cluster_name()
        domain = self._get_env('BASE_DOMAIN', 'example.com')
        hostname = name if '.' in name else f"{name}.{domain}"
        return f"bastion.{hostname}"

    def _dump_yaml(self, data):
        """統一的 YAML dump 方法"""
        if 'additionalTrustBundle' in data:
            tb = data['additionalTrustBundle']
            if tb and '\n' in tb:
                data['additionalTrustBundle'] = LiteralString(tb)
        if 'sshKey' in data:
            data['sshKey'] = QuotedString(data['sshKey'])
        return yaml.dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)

    def generate_install_config(self):
        """生成 install-config.yaml"""
        invalid = self.validate_ips()
        if invalid:
            raise ValueError(f"Invalid IPv4:\n" + "\n".join(invalid))
        
        registry_url = f"{self.get_registry_fqdn()}:8443"
        pwd = self._get_env('REGISTRY_PASSWORD')
        auth_b64 = base64.b64encode(f"init:{pwd}".encode()).decode()
        
        config = {
            "apiVersion": "v1",
            "baseDomain": self._get_env('BASE_DOMAIN'),
            "metadata": {"name": self._cluster_name()},
            "networking": self._build_networking(),
            "platform": {"none": {}},
            "fips": False,
            "pullSecret": json.dumps({"auths": {registry_url: {"auth": auth_b64}}}),
            "sshKey": self._get_env('SSH_KEY'),
            "additionalTrustBundle": self._get_env('ADDITIONAL_TRUST_BUNDLE'),
            "imageDigestSources": self._build_image_digest_sources(registry_url),
            **self._build_control_plane()
        }
        return self._dump_yaml(config)

    def _build_networking(self):
        """構建 networking 區塊"""
        net = {
            "clusterNetwork": [{"cidr": self._get_env('CLUSTER_NETWORK_CIDR', '10.128.0.0/14'),
                                "hostPrefix": int(self._get_env('CLUSTER_NETWORK_HOST_PREFIX', '23'))}],
            "serviceNetwork": [self._get_env('SERVICE_NETWORK_CIDR', '172.30.0.0/16')],
            "networkType": self._get_env('NETWORK_TYPE', 'OVNKubernetes')
        }
        cidr = self._get_env('MACHINE_NETWORK_CIDR').strip()
        if cidr:
            net["machineNetwork"] = [{"cidr": cidr}]
        return net

    def _build_image_digest_sources(self, registry_url):
        """構建 imageDigestSources"""
        path = self.get_ocp_version_path()
        return [
            {"mirrors": [f"{registry_url}/{path}/openshift/release"], "source": "quay.io/openshift-release-dev/ocp-v4.0-art-dev"},
            {"mirrors": [f"{registry_url}/{path}/openshift/release-images"], "source": "quay.io/openshift-release-dev/ocp-release"}
        ]

    def _build_control_plane(self):
        """構建 controlPlane 和 compute"""
        arch = self.v_info.get('ARCHITECTURE', 'amd64')
        mode = self._get_env('INSTALL_MODE', 'standard')
        masters = max(self._count_nodes('MASTER'), 1)
        workers = self._count_nodes('WORKER')
        
        cp = {"architecture": arch, "hyperthreading": "Enabled", "name": "master"}
        
        if mode == "sno":
            return {"controlPlane": {**cp, "replicas": 1}, "compute": []}
        
        cp["replicas"] = masters
        compute = [{"architecture": arch, "hyperthreading": "Enabled", "name": "worker", "replicas": workers if workers > 0 else 0}]
        
        if mode == "compact":
            compute[0]["replicas"] = 0
        
        return {"controlPlane": cp, "compute": compute}

    def generate_imageset_config(self):
        """生成 imageset-config.yaml"""
        operators = _load_json(os.path.join(self.config_dir, 'operators.json')) or []
        
        # 優先讀取 additional_images.json，如果不存在則從 default_images.json 建立
        images = self._load_additional_images()
        
        ocp = self.v_info.get('OCP_RELEASE', '4.20.8')
        major_minor = ocp.rsplit('.', 1)[0]
        
        config = {
            "apiVersion": "mirror.openshift.io/v2alpha1",
            "kind": "ImageSetConfiguration",
            "archiveSize": 5,
            "mirror": {
                "platform": {
                    "channels": [{
                        "name": f"stable-{major_minor}",
                        "minVersion": ocp,
                        "maxVersion": ocp
                    }],
                    "graph": True
                },
                "operators": self._build_operator_blocks(operators),
                "additionalImages": images
            }
        }
        return yaml.dump(config, sort_keys=False, allow_unicode=True)

    def _load_additional_images(self) -> list:
        """
        載入 additional images
        
        優先順序：
        1. additional_images.json（使用者自訂）
        2. default_images.json 的 base_images + csi_images
        """
        # 嘗試讀取使用者自訂的 additional_images.json
        user_images = _load_json(os.path.join(self.config_dir, 'additional_images.json'))
        if user_images is not None:
            # 確保只保留 name 欄位
            return [{"name": img["name"]} for img in user_images if img.get("name", "").strip()]
        
        # Fallback: 從 default_images.json 建立
        data = _load_json(os.path.join(self.config_dir, "default_images.json"))
        if not data:
            return []
        
        # 合併 base_images 和 csi_images
        images = []
        seen = set()
        
        # 添加 base_images
        for img in data.get('base_images', []):
            name = img.get('name', '')
            if name and name not in seen:
                images.append({"name": name})
                seen.add(name)
        
        # 添加 CSI images
        for img in self._get_csi_images():
            name = img.get('name', '')
            if name and name not in seen:
                images.append({"name": name})
                seen.add(name)
        
        return images

    def _build_operator_blocks(self, operators):
        """構建 operators 區塊"""
        if not operators:
            return []
        catalog = f"registry.redhat.io/redhat/redhat-operator-index:v{self.v_info.get('OCP_RELEASE', '4.20').rsplit('.', 1)[0]}"
        packages = [{"name": op['name'], "channels": [{"name": op.get('channel', 'stable'), "minVersion": op.get('minVersion', ''), "maxVersion": op.get('maxVersion', '')}]} for op in operators]
        return [{"catalog": catalog, "packages": packages}]
    
    def generate_agent_config(self):
        """生成 AgentConfig YAML"""
        invalid = self.validate_ips()
        if invalid:
            raise ValueError(f"Invalid IPv4:\n" + "\n".join(invalid))
        
        rendezvous = self._get_env('MASTER01_IP')
        if not rendezvous:
            raise ValueError("MASTER01_IP is required")
        
        bastion = self._get_env('BASTION_IP')
        gateway = self._get_env('GATEWAY_IP')
        
        hosts = []
        for prefix, role, max_i in [("MASTER", "master", 3), ("INFRA", "worker", 3), ("WORKER", "worker", 10)]:
            for i in range(1, max_i):
                ip = self._get_env(f"{prefix}{i:02d}_IP")
                if ip:
                    hosts.append(self._build_host_entry(
                        hostname=f"{prefix.lower()}-{i}", role=role, ip=ip,
                        mac=self._get_env(f"{prefix}{i:02d}_MAC", 'BC:24:11:99:B8:1B'),
                        interface=self._get_env(f"{prefix}{i:02d}_INTERFACE", 'ens18'),
                        device=self._get_env(f"{prefix}{i:02d}_DEVICE", '/dev/sda'),
                        bastion_ip=bastion, gateway_ip=gateway
                    ))
        
        config = {
            "apiVersion": "v1alpha1", "kind": "AgentConfig",
            "metadata": {"name": self._cluster_name()},
            "rendezvousIP": rendezvous,
            "additionalNTPSources": [bastion] if bastion else [],
            "hosts": hosts
        }
        return self._dump_yaml(config)
    
    def _build_host_entry(self, hostname, role, ip, mac, interface, device, bastion_ip, gateway_ip):
        """構建單個 host 條目"""
        cidr = self._get_env('MACHINE_NETWORK_CIDR')
        prefix = int(cidr.split('/')[1]) if cidr and '/' in cidr else 24
        
        return {
            "hostname": hostname, "role": role,
            "interfaces": [{"name": interface, "macAddress": mac.upper()}],
            "networkConfig": {
                "interfaces": [{
                    "name": interface, "type": "ethernet", "state": "up",
                    "mac-address": mac.upper(),
                    "ipv4": {"enabled": True, "address": [{"ip": ip, "prefix-length": prefix}], "dhcp": False}
                }],
                "dns-resolver": {"config": {"server": [bastion_ip] if bastion_ip else []}},
                "routes": {"config": [{"destination": "0.0.0.0/0", "next-hop-address": gateway_ip or "", "next-hop-interface": interface, "table-id": 254}]}
            },
            "rootDeviceHints": {"deviceName": device}
        }

    def _build_host_entry(self, hostname, role, ip, mac, interface, device, bastion_ip, gateway_ip):
        """構建單個 host 條目"""
        # 計算 prefix-length (從 MACHINE_NETWORK_CIDR 或預設 24)
        machine_cidr = self.env.get('MACHINE_NETWORK_CIDR', '')
        prefix_length = 24
        if machine_cidr and '/' in machine_cidr:
            try:
                prefix_length = int(machine_cidr.split('/')[1])
            except:
                pass

        return {
            "hostname": hostname,
            "role": role,
            "interfaces": [
                {
                    "name": interface,
                    "macAddress": mac.upper()
                }
            ],
            "networkConfig": {
                "interfaces": [
                    {
                        "name": interface,
                        "type": "ethernet",
                        "state": "up",
                        "mac-address": mac.upper(),
                        "ipv4": {
                            "enabled": True,
                            "address": [
                                {
                                    "ip": ip,
                                    "prefix-length": prefix_length
                                }
                            ],
                            "dhcp": False
                        }
                    }
                ],
                "dns-resolver": {
                    "config": {
                        "server": [bastion_ip] if bastion_ip else []
                    }
                },
                "routes": {
                    "config": [
                        {
                            "destination": "0.0.0.0/0",
                            "next-hop-address": gateway_ip if gateway_ip else "",
                            "next-hop-interface": interface,
                            "table-id": 254
                        }
                    ]
                }
            },
            "rootDeviceHints": {
                "deviceName": device
            }
        }
    
    def _get_csi_images(self):
        """從 default_images.json 獲取 CSI images"""
        data = _load_json(os.path.join(self.config_dir, "default_images.json"))
        if not data:
            return []
        
        csi_type = self.csi_info.get('CSI_TYPE', 'none')
        if csi_type == 'none':
            return []
        
        csi_images = data.get('csi_images', {}).get(csi_type, [])
        
        if csi_type == 'trident':
            ver = self.csi_info.get('TRIDENT_INSTALLER', '25.02.1')
            major_minor = ver.rsplit('.', 1)[0] if '.' in ver else ver
            return [
                {"name": img['name'].replace('25.02.1', ver).replace('25.02', major_minor)}
                for img in csi_images
            ]
        
        # nfs-csi 或其他類型
        return [{"name": img['name']} for img in csi_images]