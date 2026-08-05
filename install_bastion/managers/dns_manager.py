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
        
        bastion_ip = bastion.get('ip', '')
        bastion_name = bastion.get('name', 'bastion')
        bootstrap_ip = bootstrap.get('ip', '')
        bootstrap_name = bootstrap.get('name', 'bootstrap')
        
        dns_config = f"""domain={cluster_name}.{base_domain},{bastion_ip}/24,local

host-record={bastion_name}.{cluster_name}.{base_domain},{bastion_ip}
"""
        # bootstrap IP 為空時跳過 DNS record
        if bootstrap_ip:
            dns_config += f"host-record={bootstrap_name}.{cluster_name}.{base_domain},{bootstrap_ip}\n"
        
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

        # 1. 檢查 dnsmasq 服務是否已在運行，已運行則跳過安裝
        if self._check_service_status("dnsmasq"):
            self._log("dnsmasq 服務已運行，跳過安裝")
        else:
            success, _, err = self._run_command("yum install -y dnsmasq bind-utils")
            if not success:
                return False, f"dnsmasq 安裝失敗: {err}"
        
        # 2. 取得並驗證網路介面
        interface = self._get_valid_interface()
        if not interface:
            return False, "找不到有效的網路介面，請檢查網路配置"
        
        self._log(f"使用網路介面: {interface}")

        # 3. 檢查 port 53 是否被佔用
        if self._is_port_in_use(53):
            self._log("Port 53 已被佔用，嘗試釋放...")
            self._run_command("systemctl stop systemd-resolved 2>/dev/null || true")
            self._run_command("systemctl disable systemd-resolved 2>/dev/null || true")
            time.sleep(1)
        
        # 4. 備份原始配置
        self._backup_file('/etc/dnsmasq.conf')

        # 5. 設定 dnsmasq 主配置
        # 先註解掉所有現有的 interface 行
        self._run_command("sed -i 's/^interface=/#interface=/' /etc/dnsmasq.conf")
        self._run_command("sed -i 's/^bind-interfaces/#bind-interfaces/' /etc/dnsmasq.conf")

        # 添加正確的 interface 設定
        dnsmasq_conf = '/etc/dnsmasq.conf'
        with open(dnsmasq_conf, 'a') as f:
            f.write(f"\n# Added by Bastion Install Wizard\n")
            f.write(f"interface={interface}\n")
            f.write(f"bind-interfaces\n")
            f.write(f"no-hosts\n")
            f.write(f"addn-hosts=/etc/dnsmasq.d/dns.conf\n")

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

        # 8. 啟動 dnsmasq
        success, _, err = self._run_command("systemctl restart dnsmasq")
        if not success:
            # 取得詳細錯誤
            _, journal_log, _ = self._run_command(
                "journalctl -xeu dnsmasq.service --no-pager -n 20 2>&1"
            )
            self._log(f"dnsmasq 啟動失敗，日誌: {journal_log}", "ERROR")
            return False, f"dnsmasq 啟動失敗，請確認網路介面 '{interface}' 存在且已啟用"
        
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
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')

        # 測試 DNS 解析
        test_records = [
            f"api.{cluster_name}.{base_domain}",
            f"api-int.{cluster_name}.{base_domain}",
            f"{bastion_name}.{cluster_name}.{base_domain}",
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

    def _get_valid_interface(self) -> str:
        """
        取得有效的網路介面
        優先使用 config 中的設定，如果無效則自動檢測
        """
        # 從 config 取得設定的介面
        configured_interface = self.config.get('interface', '')
        
        # 驗證 config 中的介面是否存在
        if configured_interface and self._interface_exists(configured_interface):
            return configured_interface
        
        # 如果 config 中的介面無效，記錄警告並自動檢測
        if configured_interface:
            self._log(f"設定的網路介面 '{configured_interface}' 不存在，自動檢測中...", "WARNING")
        
        # 自動檢測
        detected = self._detect_primary_interface()
        if detected:
            self._log(f"自動檢測到網路介面: {detected}")
            return detected
        
        return None

    def _interface_exists(self, interface: str) -> bool:
        """檢查網路介面是否存在"""
        success, stdout, _ = self._run_command(
            f"ip link show {interface} 2>/dev/null"
        )
        return success and stdout.strip() != ""

    def _detect_primary_interface(self) -> str:
        """自動檢測主要網路介面"""
        # 方法1: 透過預設路由檢測（最可靠）
        success, stdout, _ = self._run_command(
            "ip route | grep default | awk '{print $5}' | head -1"
        )
        if success and stdout.strip():
            return stdout.strip()
        
        # 方法2: 找出有 IPv4 地址的非 lo 介面
        success, stdout, _ = self._run_command(
            "ip -4 addr show | grep -E '^[0-9]+:' | grep -v 'lo:' | awk -F': ' '{print $2}' | head -1"
        )
        if success and stdout.strip():
            return stdout.strip()
        
        # 方法3: 檢查 bastion IP 綁定在哪個介面
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        if bastion_ip:
            success, stdout, _ = self._run_command(
                f"ip addr | grep -B2 '{bastion_ip}' | grep -oP '(?<=: )\\w+(?=:)' | head -1"
            )
            if success and stdout.strip():
                return stdout.strip()
        
        # 方法4: 嘗試常見的 EC2 介面名稱
        for iface in ['eth0', 'ens5', 'ens3', 'enp0s5']:
            if self._interface_exists(iface):
                return iface
        
        return None
    
    def _is_port_in_use(self, port: int) -> bool:
        """檢查埠號是否被佔用"""
        success, stdout, _ = self._run_command(f"ss -tuln | grep ':{port} '")
        return success and stdout.strip() != ""