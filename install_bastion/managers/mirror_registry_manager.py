import os
import time
from typing import Dict, Tuple
from .base_manager import BaseManager


class MirrorRegistryManager(BaseManager):
    """Mirror Registry 管理類別"""
    
    def check_installed(self) -> Tuple[bool, str]:
        """檢查 Mirror Registry 是否已安裝"""
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        if not bastion_ip:
            return False, "無法取得 Bastion IP"
        
        # 檢查 port 8443 是否已被使用
        success, _, err = self._run_command(
            f"timeout 5 bash -c 'echo >/dev/tcp/{bastion_ip}/8443' 2>&1"
        )
        
        if success or not err:
            return True, "Mirror Registry 已安裝（連接埠 8443 已使用）"
        return False, "Mirror Registry 尚未安裝"
    
    def install_podman(self) -> Tuple[bool, str]:
        """安裝 Podman"""
        self._log("安裝 Podman...")
        
        success, _, err = self._run_command("yum install -y podman")
        if not success:
            return False, f"Podman 安裝失敗: {err}"
        
        # 驗證安裝
        success, stdout, _ = self._run_command("podman --version")
        if success:
            return True, f"Podman 安裝成功: {stdout.strip()}"
        return False, "Podman 安裝後無法驗證版本"
    
    def install(self) -> Tuple[bool, str]:
        """安裝 Mirror Registry"""
        self._log("開始安裝 Mirror Registry...")
        
        # 安裝 podman
        podman_success, podman_msg = self.install_podman()
        if not podman_success:
            return False, podman_msg
        
        self._log(podman_msg)

        # 取得安裝參數
        mirror_registry_dir = self.config.get('mirrorRegistryDir', '')
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        registry_password = self.config.get('registryPassword', 'password')
        
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        
        # === 確保 /etc/hosts 有正確的 DNS 記錄 ===
        self._ensure_hosts_entry(bastion_ip, bastion_fqdn)

        # 檢查是否已安裝
        installed, _ = self.check_installed()
        if installed:
            self._log("Mirror Registry 已安裝，跳過安裝步驟")
            # 驗證連線
            verify_success, verify_msg = self.verify_connection()
            if verify_success:
                return True, "Mirror Registry 已安裝且連線驗證成功"
            else:
                return False, f"Mirror Registry 已安裝但連線驗證失敗: {verify_msg}"

        # 搜尋安裝包
        if not mirror_registry_dir or not os.path.exists(mirror_registry_dir):
            home_dir = os.path.expanduser("~")
            install_source_dir = os.path.join(home_dir, "install_source")
            mirror_registry_dir = os.path.join(install_source_dir, 'mirror-registry.tar.gz')
        
        if not os.path.exists(mirror_registry_dir):
            found = self._search_in_install_source('mirror-registry')
            if found:
                mirror_registry_dir = found
            else:
                return False, f"找不到 Mirror Registry 安裝包: {mirror_registry_dir}"

        # 解壓安裝包
        self._log(f"解壓 {mirror_registry_dir}...")
        success, _, err = self._run_command(f"tar -xzf {mirror_registry_dir} -C /tmp/")
        if not success:
            return False, f"解壓 Mirror Registry 失敗: {err}"

         # 執行安裝
        install_cmd = (
            f"cd /tmp && ./mirror-registry install "
            f"--quayHostname {bastion_fqdn}:8443 "
            f"--quayRoot {quay_root} "
            f"--quayStorage {quay_storage} "
            f"--initPassword {registry_password}"
        )
        
        self._log(f"執行安裝命令: {install_cmd}")
        success, stdout, stderr = self._run_command(install_cmd, timeout=600)
        
        if not success:
            return False, f"Mirror Registry 安裝失敗: {stderr}"
        
        # 信任 CA 憑證
        self._trust_ca(quay_root)
        
        # 等待服務完全啟動
        time.sleep(5)
        
        # 安裝後驗證連線
        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "Mirror Registry 安裝成功且連線驗證通過"
        else:
            return False, f"Mirror Registry 安裝完成但連線驗證失敗: {verify_msg}"

    def _ensure_hosts_entry(self, bastion_ip: str, bastion_fqdn: str) -> None:
        """
        確保 /etc/hosts 中有 Bastion FQDN 的記錄
        這樣容器和主機才能解析 Registry 的域名
        """
        if not bastion_ip or not bastion_fqdn:
            return
        
        self._log(f"檢查 /etc/hosts 中的 DNS 記錄: {bastion_fqdn} -> {bastion_ip}")
        
        # 檢查是否已存在
        success, stdout, _ = self._run_command(f"grep '{bastion_fqdn}' /etc/hosts")
        if success and bastion_ip in stdout:
            self._log(f"/etc/hosts 已有記錄: {stdout.strip()}")
            return
        
        # 移除舊記錄（如果有的話）
        self._run_command(f"sed -i '/{bastion_fqdn}/d' /etc/hosts")
        
        # 添加新記錄
        self._run_command(f"echo '{bastion_ip} {bastion_fqdn}' >> /etc/hosts")
        self._log(f"已添加 /etc/hosts 記錄: {bastion_ip} {bastion_fqdn}")

    def _search_in_install_source(self, pattern: str) -> str:
        """在 install_source 目錄中搜尋匹配的檔案"""
        home_dir = os.path.expanduser("~")
        install_source_dir = os.path.join(home_dir, "install_source")
        
        if not os.path.exists(install_source_dir):
            return None
        
        for filename in os.listdir(install_source_dir):
            if pattern in filename and filename.endswith('.tar.gz'):
                return os.path.join(install_source_dir, filename)
        
        return None

    def _trust_ca(self, quay_root: str) -> bool:
        """信任 Mirror Registry 的 CA 憑證"""
        ca_path = f"{quay_root}/quay-rootCA/rootCA.pem"
        ca_target = "/etc/pki/ca-trust/source/anchors/"
        
        if os.path.exists(ca_path):
            self._log("信任 Mirror Registry CA 憑證...")
            success, _, err = self._run_command(f"cp {ca_path} {ca_target}")
            if success:
                self._run_command("update-ca-trust")
                return True
            else:
                self._log(f"複製 CA 憑證失敗: {err}", "WARNING")
        else:
            self._log(f"找不到 CA 憑證: {ca_path}", "WARNING")
        
        return False
    
    def verify_connection(self) -> Tuple[bool, str]:
        """驗證 Mirror Registry 連線"""
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        registry_password = self.config.get('registryPassword', 'password')
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        
        # 方法1: 使用 IP 直接連線（避免 DNS 問題）
        if bastion_ip:
            login_cmd = (
                f"podman login {bastion_ip}:8443 "
                f"-u init -p {registry_password} "
                f"--tls-verify=false"
            )
            success, stdout, stderr = self._run_command(login_cmd)
            if success:
                return True, f"Mirror Registry 連線成功 (IP: {bastion_ip}:8443)"
        
        # 方法2: 使用 FQDN 連線
        login_cmd = (
            f"podman login {bastion_fqdn}:8443 "
            f"-u init -p {registry_password} "
            f"--tls-verify=false"
        )
        success, stdout, stderr = self._run_command(login_cmd)
        
        if success:
            return True, f"Mirror Registry 連線成功 (FQDN: {bastion_fqdn}:8443)"
        else:
            return False, f"Registry 連線失敗，請確認 Registry 服務已啟動。錯誤: {stderr[:200]}"