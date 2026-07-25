import os
import time
import shutil
from typing import Tuple, Optional
from .base_manager import BaseManager


class MirrorRegistryManager(BaseManager):
    """Mirror Registry 管理類別"""

    def __init__(self, config: dict, config_dir: str = "/tmp/ocp-install-config"):
        super().__init__(config, config_dir)

    def check_installed(self) -> Tuple[bool, str]:
        """檢查 Mirror Registry 是否已安裝運行"""
        success, stdout, _ = self._run_command(
            "podman ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null || "
            "docker ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null"
        )
        running_containers = [n.strip() for n in stdout.split('\n') if n.strip()] if success and stdout.strip() else []

        if running_containers:
            self._log(f"Quay 容器運行中: {', '.join(running_containers)}")
            return True, f"Quay 容器運行中: {', '.join(running_containers)}"
        else:
            return False, "Quay 容器未運行"

    def _check_port_8443(self) -> bool:
        """檢查 port 8443 是否有服務監聽"""
        success, stdout, _ = self._run_command(
            "ss -tlnp 2>/dev/null | grep ':8443' || netstat -tlnp 2>/dev/null | grep ':8443'"
        )
        return success and bool(stdout.strip())

    def _was_installed(self) -> bool:
        """檢查 mirror-registry 是否曾安裝過（podman 容器存在即視為已安裝）"""
        success, stdout, _ = self._run_command(
            "podman ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null"
        )
        if success and stdout.strip():
            return True
        return os.path.exists(os.path.expanduser("~/mirror-registry"))

    def install(self) -> Tuple[bool, str]:
        """安裝 Mirror Registry"""

        # 1. 檢查是否已運行
        installed, msg = self.check_installed()
        if installed:
            self._log(f"Mirror Registry 已運行: {msg}")

            # 驗證連線
            connected, connect_msg = self.verify_connection()
            if not connected:
                self._log(f"連線驗證失敗，重新安裝...")
                return self._fresh_install()

            self._log("Mirror Registry 已運行且連線正常，跳過安裝")
            return True, "Mirror Registry 已安裝並運行"

        # 2. 取得配置
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        registry_password = self.config.get('registryPassword', 'password')
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"

        # 3. 確保 /etc/hosts 有 Bastion FQDN 記錄
        self._ensure_hosts_entry(bastion_ip, bastion_fqdn)

        # 4. Quay 未運行 — 僅在曾安裝過時清理
        if self._was_installed():
            self._log("Quay 未運行，清理舊安裝...")
            self._cleanup_installation(quay_root, quay_storage)
        else:
            self._log("全新安裝，跳過清理")

        return self._fresh_install()

    def _fresh_install(self) -> Tuple[bool, str]:
        """執行全新安裝"""
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        registry_password = self.config.get('registryPassword', 'password')
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"

        # 1. 尋找 mirror-registry 安裝包
        tar_path = self._find_mirror_registry_tar()
        if not tar_path:
            return False, "找不到 mirror-registry 安裝包"

        self._log(f"mirror-registry tar: {tar_path}")

        # 2. 解壓到 ~/
        home_dir = os.path.expanduser("~")
        self._log(f"解壓 mirror-registry 到 {home_dir} ...")
        success, _, err = self._run_command(f"tar -xzf {tar_path} -C {home_dir}/")
        if not success:
            return False, f"解壓 mirror-registry 失敗: {err}"
        self._log("解壓完成")

        # 3. 確認解壓後的必要檔案
        for fname in ['mirror-registry', 'image-archive.tar', 'execution-environment.tar']:
            fpath = os.path.join(home_dir, fname)
            if os.path.exists(fpath):
                self._log(f"已找到: {fname}")
            else:
                self._log(f"warning: 未找到 {fname}", "WARNING")
        self._log("解壓檔案確認完成")

        # 4. 確保 root 免密碼 SSH 到 localhost（mirror-registry 的 Ansible playbook 需要）
        self._log("設定 root SSH 免密碼...")
        ssh_ok, _, ssh_err = self._run_command(
            "sudo mkdir -p /root/.ssh && "
            "sudo chmod 700 /root/.ssh && "
            "sudo ssh-keygen -t rsa -f /root/.ssh/id_rsa -N '' -q; "
            "sudo sh -c 'cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys' && "
            "sudo sort -u /root/.ssh/authorized_keys -o /root/.ssh/authorized_keys && "
            "sudo chmod 600 /root/.ssh/authorized_keys && "
            "sudo ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@localhost echo ok"
        )
        if not ssh_ok:
            return False, f"root SSH 設定失敗: {ssh_err}"

        # 5. 執行 mirror-registry install
        self._log("執行 mirror-registry install...")
        install_cmd = (
            f"cd {home_dir} && script -qc "
            f"'./mirror-registry install "
            f"--quayHostname {bastion_fqdn}:8443 "
            f"--quayRoot {quay_root} "
            f"--quayStorage {quay_storage} "
            f"--initPassword {registry_password}'"
            f" /dev/null"
        )

        log_path = os.path.join(self.config_dir, "mirror_registry_install.log")
        full_cmd = f"{install_cmd} > {log_path} 2>&1"
        self._log(f"安裝日誌: {log_path}")

        success, _, err = self._run_command(full_cmd, timeout=600)
        if not success:
            return False, f"mirror-registry install 失敗: {err}"

        self._log("mirror-registry install 完成")

        # 6. 信任 CA 憑證
        self._trust_ca(quay_root)

        # 7. 健康檢查
        self._log("等待 Quay 就緒...")
        for i in range(10):
            success, stdout, _ = self._run_command(
                f"curl -sk -o /dev/null -w '%{{http_code}}' "
                f"--connect-timeout 5 https://{bastion_fqdn}:8443/v2/"
            )
            if success and "200" in stdout:
                self._log("Quay 健康檢查通過！")
                break
            self._log(f"等待 Quay 就緒... ({i+1}/10)")
            time.sleep(30)
        else:
            return False, (
                f"安裝完成但 Quay 健康檢查未通過\n\n"
                f"📄 完整日誌: {log_path}"
            )

        # 8. 執行 podman login 驗證
        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "✅ Mirror Registry 安裝成功，健康檢查與連線驗證通過"
        else:
            return False, f"安裝完成且健康檢查通過，但連線驗證失敗: {verify_msg}"

    def _cleanup_installation(self, quay_root: str, quay_storage: str) -> None:
        """清理舊的 Mirror Registry 安裝

        優先使用 mirror-registry uninstall，失敗時手動清理 podman 資源。
        不使用 systemctl — mirror-registry 透過 podman 管理一切。
        """
        self._log("開始清理舊的 Mirror Registry 安裝...")

        home_dir = os.path.expanduser("~")

        # 1. mirror-registry uninstall
        uninstall_cmd = (
            f"cd {home_dir} && ./mirror-registry uninstall "
            f"--quayRoot {quay_root} -y 2>/dev/null"
        )
        success, _, _ = self._run_command(uninstall_cmd, timeout=120)
        if success:
            self._log("mirror-registry uninstall 完成")
        else:
            self._log("mirror-registry uninstall 失敗，手動清理 podman 資源", "WARNING")

            # 2. 手動移除 quay 容器
            self._run_command(
                "podman ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
                "xargs -r podman rm -f 2>/dev/null"
            )
            self._log("已移除 quay 容器")

            # 3. 移除 pod
            self._run_command("podman pod rm -f quay-pod 2>/dev/null")

            # 4. 移除 volumes
            self._run_command(
                "podman volume ls -q 2>/dev/null | "
                "grep -iE 'quay|sqlite|redis' | "
                "xargs -r podman volume rm -f 2>/dev/null"
            )

        # 5. 清除 quay 目錄
        for dir_path in [quay_root, quay_storage]:
            if os.path.exists(dir_path):
                try:
                    shutil.rmtree(dir_path)
                    self._log(f"已移除目錄: {dir_path}")
                except Exception as e:
                    self._log(f"移除目錄失敗 {dir_path}: {e}", "WARNING")

        self._log("清理完成")

    def _find_mirror_registry_tar(self) -> Optional[str]:
        """尋找 mirror-registry 安裝包"""
        configured_path = self.config.get('mirrorRegistryDir', '')
        if configured_path and os.path.exists(configured_path):
            return configured_path

        install_source_dir = self._get_install_source_dir()

        if os.path.exists(install_source_dir):
            for filename in os.listdir(install_source_dir):
                if 'mirror-registry' in filename and filename.endswith('.tar.gz'):
                    return os.path.join(install_source_dir, filename)

        return None

    def _ensure_hosts_entry(self, bastion_ip: str, bastion_fqdn: str) -> None:
        """確保 /etc/hosts 中有 Bastion FQDN 的記錄"""
        if not bastion_ip or not bastion_fqdn:
            self._log("Bastion IP 或 FQDN 為空，跳過 /etc/hosts 設定")
            return

        self._log(f"設定 /etc/hosts: {bastion_ip} {bastion_fqdn}")
        self._run_command(f"sed -i '/{bastion_fqdn}/d' /etc/hosts")
        self._run_command(f"echo '{bastion_ip} {bastion_fqdn}' >> /etc/hosts")

        success, stdout, _ = self._run_command(f"grep '{bastion_fqdn}' /etc/hosts")
        if success:
            self._log(f"/etc/hosts 已更新: {stdout.strip()}")
        else:
            self._log("警告: /etc/hosts 寫入可能失敗", "WARNING")

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
        """驗證 Mirror Registry 連線（使用 FQDN，與安裝時一致）"""
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        registry_password = self.config.get('registryPassword', 'password')

        login_cmd = (
            f"podman login {bastion_fqdn}:8443 "
            f"-u init -p {registry_password} "
            f"--tls-verify=false"
        )
        success, stdout, stderr = self._run_command(login_cmd, timeout=30)

        if success:
            return True, "Registry 連線驗證通過"
        else:
            return False, f"Registry 連線失敗: {stderr[:200]}"
