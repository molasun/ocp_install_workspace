import os
import json
from typing import Dict, Tuple, Any
from datetime import datetime

from managers.base_manager import BaseManager
from managers.dns_manager import DNSManager
from managers.haproxy_manager import HAProxyManager
from managers.ntp_manager import NTPManager
from managers.others_manager import OthersManager
from managers.mirror_registry_manager import MirrorRegistryManager
from managers.install_manager import InstallManager
from managers.agent_create_manager import AgentCreateManager


class SetupManager:
    """安裝管理類別，封裝所有安裝步驟"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化安裝管理器
        
        Args:
            config: 配置參數字典
        """
        self.config = config
        self.config_dir = "/tmp/ocp-install-config"
        self.step_status = {}
        
        # 建立配置目錄
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 初始化所有子 Manager
        base = BaseManager(config, self.config_dir)
        self.logs = base.logs
        self.log_file = base.log_file
        
        # 初始化各模組 Manager（共用同一個 base 的 logs）
        self.dns_manager = DNSManager(config, self.config_dir)
        self.dns_manager.logs = self.logs
        self.dns_manager.log_file = self.log_file
        
        self.haproxy_manager = HAProxyManager(config, self.config_dir)
        self.haproxy_manager.logs = self.logs
        self.haproxy_manager.log_file = self.log_file
        
        self.ntp_manager = NTPManager(config, self.config_dir)
        self.ntp_manager.logs = self.logs
        self.ntp_manager.log_file = self.log_file
        
        self.others_manager = OthersManager(config, self.config_dir)
        self.others_manager.logs = self.logs
        self.others_manager.log_file = self.log_file
        
        self.mirror_registry_manager = MirrorRegistryManager(config, self.config_dir)
        self.mirror_registry_manager.logs = self.logs
        self.mirror_registry_manager.log_file = self.log_file
        
        self.install_manager = InstallManager(config, self.config_dir)
        self.install_manager.logs = self.logs
        self.install_manager.log_file = self.log_file
        
        self.agent_create_manager = AgentCreateManager(config, self.config_dir)
        self.agent_create_manager.logs = self.logs
        self.agent_create_manager.log_file = self.log_file
   
    def _log(self, message: str, level: str = "INFO"):
        """記錄日誌（委派給第一個 manager 的 logger）"""
        self.dns_manager._log(message, level)
    
    def execute_step(self, method_name: str) -> Tuple[bool, str]:
        """
        執行指定的安裝步驟
        
        Args:
            method_name: 要執行的方法名稱
            
        Returns:
            (success, message)
        """
        # 方法名稱到 Manager 方法的映射
        method_map = {
            # Others Manager
            'disable_firewalld': self.others_manager.disable_firewalld,
            'disable_selinux': self.others_manager.disable_selinux,
            'install_nmstate': self.others_manager.install_nmstate,
            'check_system_requirements': self.others_manager.check_system_requirements,
            
            # DNS Manager
            'setup_dns': self.dns_manager.install,
            'check_dns': self.dns_manager.check_records,
            'generate_dns_config': self.dns_manager.generate_config,
            
            # HAProxy Manager
            'setup_haproxy': self.haproxy_manager.install,
            'generate_haproxy_config': self.haproxy_manager.generate_config,
            
            # NTP Manager
            'setup_ntp': self.ntp_manager.install,
            'generate_ntp_config': self.ntp_manager.generate_config,
            
            # Mirror Registry Manager
            'setup_registry': self.mirror_registry_manager.install,
            'check_registry_installed': self.mirror_registry_manager.check_installed,
            'verify_registry_connection': self.mirror_registry_manager.verify_connection,
            
            # Install Manager
            'install_packages': self.install_manager.install_packages,
            'install_cli': self.install_manager.install_all_cli,
            'install_openshift_install': self.install_manager.install_openshift_install_cli,
            'install_oc_client': self.install_manager.install_oc_client,
            'verify_installations': self.install_manager.verify_installations,
        }
        
        method = method_map.get(method_name)
        if method is None:
            return False, f"未知的安裝步驟: {method_name}"
        
        try:
            self._log(f"開始執行步驟: {method_name}")
            success, message = method()
            
            # 記錄步驟狀態
            self.step_status[method_name] = {
                'success': success,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
            
            return success, message
            
        except Exception as e:
            error_msg = f"步驟執行異常: {str(e)}"
            self._log(error_msg, "ERROR")
            return False, error_msg
    
    def generate_summary(self):
        """生成安裝摘要"""
        self._log("生成安裝摘要...")
        
        summary = {
            'installation_time': datetime.now().isoformat(),
            'config': self.config,
            'steps': self.step_status
        }
        
        summary_file = f"{self.config_dir}/installation_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        self._log(f"安裝摘要已保存至: {summary_file}")
        return summary_file
    
    # === 向後相容的方法（委派給各 Manager） ===
    
    def _generate_dns_config(self) -> str:
        """生成 DNS 配置（向後相容）"""
        return self.dns_manager.generate_config()
    
    def _generate_haproxy_config(self) -> str:
        """生成 HAProxy 配置（向後相容）"""
        return self.haproxy_manager.generate_config()
    
    def _generate_ntp_config(self) -> str:
        """生成 NTP 配置（向後相容）"""
        return self.ntp_manager.generate_config()


# 使用範例
if __name__ == "__main__":
    test_config = {
        "clusterName": "ocp",
        "baseDomain": "example.com",
        "interface": "eth0",
        "dns_upstream": "8.8.8.8",
        "bastion": {"ip": "192.168.1.100", "name": "bastion"},
        "bootstrap": {"ip": "192.168.1.50", "name": "bootstrap"},
        "master": [
            {"name": "master-0", "ip": "192.168.1.11", "mac": ""},
            {"name": "master-1", "ip": "192.168.1.12", "mac": ""},
            {"name": "master-2", "ip": "192.168.1.13", "mac": ""}
        ],
        "worker": [],
        "infra": [],
        "mode": "compact",
        "registryPassword": "password"
    }
    
    manager = SetupManager(test_config)
    
    print("=== DNS Configuration ===")
    print(manager._generate_dns_config())
    
    print("\n=== HAProxy Configuration ===")
    print(manager._generate_haproxy_config())
    
    print("\n=== NTP Configuration ===")
    print(manager._generate_ntp_config())