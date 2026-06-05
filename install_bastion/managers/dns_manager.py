import os
import time
from typing import Dict, Tuple
from .base_manager import BaseManager


class DNSManager(BaseManager):
    """DNS 管理類別"""
    
    def generate_config(self) -> str:
        """
        根據配置生成 DNS 設定檔內容
        """
        config = self.config
        bastion = config.get('bastion', {})
        bootstrap = config.get('bootstrap', {})
        master_nodes = config.get('master', [])
        worker_nodes = config.get('worker', [])
        infra_nodes = config.get('infra', [])
        cluster_name = config.get('clusterName', 'ocp4')
        base_domain = config.get('baseDomain', 'example.com')
        dns_upstream = config.get('dns_upstream', '8.8.8.8')
        
        bastion_ip = bastion.get('ip', '')
        bastion_name = bastion.get('name', 'bastion')
        bootstrap_ip = bootstrap.get('ip', '')
        bootstrap_name = bootstrap.get('name', 'bootstrap')
        
        dns_config = f"""domain={cluster_name}.{base_domain},{bastion_ip}/24,local
server={dns_upstream}

host-record={bastion_name}.{cluster_name}.{base_domain},{bastion_ip}
host-record={bootstrap_name}.{cluster_name}.{base_domain},{bootstrap_ip}
"""
        
        # Master 節點記錄
        for node in master_nodes:
            node_name = node.get('name', '')
            node_ip = node.get('ip', '')
            if node_name and node_ip:
                dns_config += f"host-record={node_name}.{cluster_name}.{base_domain},{node_ip}\n"
        
        # Worker/Infra 節點記錄
        if config.get('mode') != 'compact':
            if infra_nodes:
                for node in infra_nodes:
                    node_name = node.get('name', '')
                    node_ip = node.get('ip', '')
                    if node_name and node_ip:
                        dns_config += f"host-record={node_name}.{cluster_name}.{base_domain},{node_ip}\n"
            if worker_nodes:
                for node in worker_nodes:
                    node_name = node.get('name', '')
                    node_ip = node.get('ip', '')
                    if node_name and node_ip:
                        dns_config += f"host-record={node_name}.{cluster_name}.{base_domain},{node_ip}\n"
        
        # API 和應用程式記錄
        dns_config += f"""
host-record=api.{cluster_name}.{base_domain},{bastion_ip}
host-record=api-int.{cluster_name}.{base_domain},{bastion_ip}
host-record=apps.{cluster_name}.{base_domain},{bastion_ip}
host-record=.apps.{cluster_name}.{base_domain},{bastion_ip}

address=/.apps.{cluster_name}.{base_domain}/{bastion_ip}
address=/api.{cluster_name}.{base_domain}/{bastion_ip}
address=/api-int.{cluster_name}.{base_domain}/{bastion_ip}
"""
        
        return dns_config
    
    def install(self) -> Tuple[bool, str]:
        """安裝並設定 DNS 伺服器"""
        self._log("開始設定 DNS 伺服器 (dnsmasq)...")
        
        # 1. 安裝 dnsmasq 和 bind-utils（用於 nslookup/dig）
        success, _, err = self._run_command("yum install -y dnsmasq bind-utils")
        if not success:
            return False, f"dnsmasq 安裝失敗: {err}"
        
        # 2. 取得網路介面（自動檢測如果未配置）
        interface = self.config.get('interface', '')
        if not interface:
            interface = self._detect_primary_interface()
            self._log(f"自動檢測網路介面: {interface}")

        # 3. 檢查 port 53 是否被佔用
        if self._is_port_in_use(53):
            self._log("Port 53 已被佔用，嘗試釋放...")
            self._run_command("systemctl stop systemd-resolved 2>/dev/null || true")
            self._run_command("systemctl disable systemd-resolved 2>/dev/null || true")
            time.sleep(1)

        # 5. 設定 dnsmasq 主配置
        self._run_command(
            f"sed -i 's/^#interface=/interface={interface}/' /etc/dnsmasq.conf"
        )
        self._run_command(
            f"sed -i 's/^interface=.*/interface={interface}/' /etc/dnsmasq.conf"
        )
        # 確保有 interface 行
        self._run_command(
            f"grep -q '^interface=' /etc/dnsmasq.conf || echo 'interface={interface}' >> /etc/dnsmasq.conf"
        )
        
        # 確保有 bind-interfaces 設定
        self._run_command(
            "grep -q '^bind-interfaces' /etc/dnsmasq.conf || echo 'bind-interfaces' >> /etc/dnsmasq.conf"
        )

        # 6. 生成並寫入 DNS 配置
        dns_config = self.generate_config()
        dns_conf_dir = '/etc/dnsmasq.d'
        os.makedirs(dns_conf_dir, exist_ok=True)
        
        if not self._write_file(f'{dns_conf_dir}/dns.conf', dns_config):
            return False, "寫入 DNS 配置檔失敗"

        # 7. 驗證配置
        success, stdout, stderr = self._run_command("dnsmasq --test 2>&1")
        if not success:
            self._log(f"dnsmasq 配置驗證失敗: {stderr}", "ERROR")
            # 不阻止，繼續嘗試啟動

        # 8. 啟動 dnsmasq
        success, _, err = self._run_command("systemctl restart dnsmasq")
        if not success:
            # 取得詳細錯誤
            _, journal_log, _ = self._run_command("journalctl -xeu dnsmasq.service --no-pager -n 20 2>&1")
            self._log(f"dnsmasq 啟動失敗，日誌: {journal_log}", "ERROR")
            return False, f"dnsmasq 啟動失敗，請檢查網路介面 '{interface}' 是否正確"
        
        self._run_command("systemctl enable dnsmasq")
        
        # 9. 設定 NetworkManager DNS
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        if bastion_ip and interface:
            self._run_command(f"nmcli connection modify {interface} ipv4.dns {bastion_ip}")
            self._run_command("systemctl restart NetworkManager")
        
        # 10. 驗證服務
        time.sleep(2)
        if self._check_service_status("dnsmasq"):
            return True, "DNS 伺服器已成功配置並啟動"
        else:
            return False, "DNS 伺服器啟動後驗證失敗"
    
    def check_records(self) -> Tuple[bool, str]:
        """檢查 DNS 記錄"""
        self._log("開始檢查 DNS 記錄...")
        
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        
        # 測試 DNS 解析
        test_records = [
            f"api.{cluster_name}.{base_domain}",
            f"api-int.{cluster_name}.{base_domain}",
            f"bastion.{cluster_name}.{base_domain}",
        ]
        
        all_success = True
        failed_records = []
        success_records = []
        
        for record in test_records:
            # 先嘗試 dig
            success, stdout, _ = self._run_command(f"dig +short {record} @127.0.0.1")
            if success and stdout.strip():
                success_records.append(f"{record} -> {stdout.strip()}")
            else:
                # 嘗試 nslookup
                success, stdout, _ = self._run_command(f"nslookup {record} 127.0.0.1")
                if success and 'Address:' in stdout:
                    addr = stdout.split('Address: ')[-1].split('\n')[0]
                    success_records.append(f"{record} -> {addr}")
                else:
                    all_success = False
                    failed_records.append(record)
        
        if all_success:
            return True, f"所有 DNS 記錄檢查通過: {'; '.join(success_records)}"
        else:
            return False, f"DNS 記錄檢查失敗: {', '.join(failed_records)}"
        
    def _detect_primary_interface(self) -> str:
        """自動檢測主要網路介面"""
        # 方法1: 透過預設路由檢測
        success, stdout, _ = self._run_command(
            "ip route | grep default | awk '{print $5}' | head -1"
        )
        if success and stdout.strip():
            return stdout.strip()
        
        # 方法2: 透過 IP 檢測
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        if bastion_ip:
            success, stdout, _ = self._run_command(
                f"ip addr | grep -B2 '{bastion_ip}' | grep -oP '(?<=: )\\w+(?=:)' | head -1"
            )
            if success and stdout.strip():
                return stdout.strip()
        
        # 方法3: 預設值
        return 'eth0'
    
    def _is_port_in_use(self, port: int) -> bool:
        """檢查埠號是否被佔用"""
        success, stdout, _ = self._run_command(f"ss -tuln | grep ':{port} '")
        return success and stdout.strip() != ""