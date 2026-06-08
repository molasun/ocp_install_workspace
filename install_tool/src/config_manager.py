import copy
import json
import os

class ConfigManager:
    
    _DEFAULTS = {
        'tool': {
            "version_info": {
                "OCP_RELEASE": "4.20.22",
                "RHEL_VERSION": "rhel9",
                "ARCHITECTURE": "amd64",
                "HELM_VERSION": "3.17.1",
                "MIRROR_REGISTRY_VERSION": "latest"
            }
        },
        'cluster': {
            "version_info": {"OCP_VERSION": "4.20"},
            "install_env": {
                "INSTALL_MODE": "standard",
                "CLUSTER_DOMAIN": "ocp4",
                "BASE_DOMAIN": "example.com",
                "BASTION_IP": "",
                "BOOTSTRAP_IP": "",
                "REGISTRY_PASSWORD": "P@ssw0rd",
                "SSH_KEY": "",
                "ADDITIONAL_TRUST_BUNDLE": "",
                "MACHINE_NETWORK_CIDR": "",
                "CLUSTER_NETWORK_CIDR": "10.128.0.0/14",
                "CLUSTER_NETWORK_HOST_PREFIX": 23,
                "SERVICE_NETWORK_CIDR": "172.30.0.0/16",
                "NETWORK_TYPE": "OVNKubernetes"
            }
        }
    }

    def __init__(self, config_file='tool_config.json', config_dir=None):
        """初始化 config 目錄與檔案路徑，若檔案不存在則建立預設配置"""
        self.config_dir = config_dir or os.path.join(os.getcwd(), 'config')
        self.config_file = os.path.join(self.config_dir, os.path.basename(config_file))
        os.makedirs(self.config_dir, exist_ok=True)
        
        if not os.path.exists(self.config_file):
            self._create_default()
        
    def _create_default(self):
        """根據檔名中的 tool 或 cluster 關鍵字建立對應的預設配置"""
        basename = os.path.basename(self.config_file)
        for key in ['tool', 'cluster']:
            if key in basename:
                self.save_config(copy.deepcopy(self._DEFAULTS[key]))
                return
        self.save_config({})

    def get_config(self):
        """
        讀取配置，如果缺少必要鍵則自動補全
        """
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"讀取配置失敗: {e}，重新建立預設配置")
            self._create_default()
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        # 確保必要結構存在
        return self._ensure_required_keys(config)
    
    def _ensure_required_keys(self, config):
        """確保 config 包含所有必要的頂層鍵"""
        basename = os.path.basename(self.config_file)
        
        for key in ['tool', 'cluster']:
            if key in basename:
                default = self._DEFAULTS[key]
                # 確保所有頂層鍵存在
                for top_key in default:
                    if top_key not in config:
                        config[top_key] = copy.deepcopy(default[top_key])
                break
        
        return config
    
    def save_config(self, config):
        """將配置字典寫入 JSON 檔案"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)