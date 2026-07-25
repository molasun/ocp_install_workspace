import os
import time
import shutil
from typing import Optional, Tuple
from .base_manager import BaseManager


class MirrorRegistryManager(BaseManager):
    """Mirror Registry 管理類別"""

    def check_installed(self) -> Tuple[bool, str]:
        """檢查 Mirror Registry 是否已安裝並運行"""
        bastion_ip = self.config.get('bastion', {}).get('ip', '')
        if not bastion_ip:
            return False, "無法取得 Bastion IP"

        # 方法1: 檢查 port 8443
        success, stdout, _ = self._run_command(
            f"ss -tlnp 2>/dev/null | grep ':8443' || netstat -tlnp 2>/dev/null | grep ':8443'"
        )
        if success and stdout.strip():
            return True, "Mirror Registry 正在運行（port 8443 已監聽）"

        # 方法2: 檢查容器是否在運行
        success, stdout, _ = self._run_command(
            "podman ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null || "
            "docker ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null"
        )
        if success and stdout.strip():
            return True, f"Registry 容器運行中: {stdout.strip()}"

        # 方法3: curl 檢查
        success, stdout, _ = self._run_command(
            f"curl -sk -o /dev/null -w '%{{http_code}}' --connect-timeout 3 https://{bastion_ip}:8443/v2/",
            timeout=5
        )
        if success and stdout.strip() in ['200', '401']:
            return True, "Mirror Registry HTTP 回應正常"

        return False, "Mirror Registry 未運行"

    def _check_port_8443(self) -> bool:
        """檢查 port 8443 是否有服務監聽"""
        success, stdout, _ = self._run_command(
            "ss -tlnp 2>/dev/null | grep ':8443' || netstat -tlnp 2>/dev/null | grep ':8443'"
        )
        return success and bool(stdout.strip())

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
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        registry_password = self.config.get('registryPassword', 'password')

        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        bastion_ip = self.config.get('bastion', {}).get('ip', '')

        # 確保 /etc/hosts 有正確的 DNS 記錄
        self._ensure_hosts_entry(bastion_ip, bastion_fqdn)

        # === 檢查 Quay 是否在運行 ===
        running, msg = self.check_installed()
        if running:
            # Quay 在運行，驗證連線
            verify_success, verify_msg = self.verify_connection()
            if verify_success:
                return True, "✅ Mirror Registry 已在運行，連線驗證成功"
            else:
                # 運行中但連線失敗，清理後重裝
                self._log(f"Quay 運行中但驗證失敗: {verify_msg}，執行清理後重新安裝...", "WARNING")
                self._cleanup_installation(quay_root, quay_storage)
        else:
            # Quay 未運行，執行 uninstall + 清理
            self._log("Quay 未運行，執行清理確保乾淨環境...")
            self._cleanup_installation(quay_root, quay_storage)

        # === 執行全新安裝 ===
        return self._fresh_install(quay_root, quay_storage, bastion_fqdn, registry_password)

    def _fresh_install(self, quay_root: str, quay_storage: str, bastion_fqdn: str, registry_password: str) -> Tuple[bool, str]:
        """執行全新安裝"""
        self._log("📦 Mirror Registry 開始全新安裝...")

        # 1. 找到 mirror-registry tar 包
        mirror_registry_tar = self._find_mirror_registry_tar()
        if not mirror_registry_tar:
            return False, "找不到 Mirror Registry 安裝包"

        # 2. 解壓到 ~/ (根目錄下)
        home_dir = os.path.expanduser("~")
        self._log(f"解壓 {mirror_registry_tar} 到 {home_dir}/ ...")
        success, _, err = self._run_command(f"tar -xzf {mirror_registry_tar} -C {home_dir}/")
        if not success:
            return False, f"解壓失敗: {err}"

        # 3. 確認解壓後的檔案都存在
        binary_path = os.path.join(home_dir, "mirror-registry")
        image_archive_path = os.path.join(home_dir, "image-archive.tar")
        exec_env_path = os.path.join(home_dir, "execution-environment.tar")

        if not os.path.exists(binary_path):
            return False, f"解壓後找不到 mirror-registry 二進位檔: {binary_path}"

        if not os.path.exists(image_archive_path):
            self._log("警告: image-archive.tar 不存在，可能為線上版安裝包", "WARNING")

        if not os.path.exists(exec_env_path):
            self._log("警告: execution-environment.tar 不存在，可能為線上版安裝包", "WARNING")

        self._log("解壓檔案確認完成")

        # 3.5 確保 root 免密碼 SSH 到 localhost（mirror-registry 的 Ansible playbook 需要）
        self._log("設定 root SSH 免密碼...")
        self._run_command(
            "sudo mkdir -p /root/.ssh && "
            "sudo chmod 700 /root/.ssh && "
            "[ -f /root/.ssh/id_rsa ] || sudo ssh-keygen -t rsa -f /root/.ssh/id_rsa -N '' -q && "
            "sudo cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys && "
            "sudo sort -u /root/.ssh/authorized_keys -o /root/.ssh/authorized_keys && "
            "sudo chmod 600 /root/.ssh/authorized_keys && "
            "sudo ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@localhost echo ok"
        )

        # 4. 在根目錄下執行 mirror-registry install
        #    用 script -qc 提供偽 TTY — Streamlit headless 模式下 podman 的
        #    --tty --interactive 參數會因無 TTY 而失敗。
        install_cmd = (
            f"cd {home_dir} && script -qc "
            f"'./mirror-registry install "
            f"--quayHostname {bastion_fqdn}:8443 "
            f"--quayRoot {quay_root} "
            f"--quayStorage {quay_storage} "
            f"--initPassword {registry_password}'"
            f" /dev/null"
        )

        self._log(f"執行安裝...")
        success, stdout, stderr = self._run_command(install_cmd, timeout=600)

        # 儲存完整輸出供診斷
        log_path = os.path.join(self.config_dir, "mirror-registry-install-output.log")
        try:
            with open(log_path, 'w') as f:
                f.write(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n")
        except Exception:
            pass

        if not success:
            # 提取錯誤摘要
            raw_output = stderr if stderr else stdout
            all_lines = [l for l in raw_output.split('\n') if l.strip()]
            error_lines = [
                l for l in all_lines
                if any(kw in l.lower() for kw in ['error', 'fail', 'fatal', 'panic', 'cannot', 'unable'])
            ]
            if error_lines:
                error_detail = '\n'.join(error_lines[:10])
            else:
                error_detail = '\n'.join(all_lines[-15:]) if all_lines else raw_output[-500:]

            return False, f"安裝失敗: {error_detail}\n\n📄 完整日誌: {log_path}"

        # 5. 安裝完成，信任 CA 憑證
        self._trust_ca(quay_root)

        # 6. 等待 Quay 啟動，執行 ping 確認服務正確運行
        self._log("等待 Quay 服務啟動...")
        time.sleep(15)

        # 7. ping 健康檢查（最多等待 5 分鐘）
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        health_url = f"https://{bastion_fqdn}:8443/health/instance"

        for i in range(10):
            success, stdout, _ = self._run_command(
                f"curl -sk --connect-timeout 5 {health_url}", timeout=10
            )
            if success and "200" in stdout:
                self._log("Quay 健康檢查通過！")
                break
            self._log(f"等待 Quay 就緒... ({i+1}/10)")
            time.sleep(30)
        else:
            # 健康檢查未通過
            return False, (
                f"安裝完成但 Quay 健康檢查未通過\n\n"
                f"📄 完整日誌: {log_path}\n"
                f"💡 請檢查: journalctl -u quay-app.service --no-pager -n 30"
            )

        # 8. 執行 podman login 驗證
        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "✅ Mirror Registry 安裝成功，健康檢查與連線驗證通過"
        else:
            return False, f"安裝完成且健康檢查通過，但連線驗證失敗: {verify_msg}"

    def _cleanup_installation(self, quay_root: str, quay_storage: str) -> None:
        """清理舊的 Mirror Registry 安裝（uninstall + 清除殘留）"""
        self._log("開始清理舊的 Mirror Registry 安裝...")

        home_dir = os.path.expanduser("~")

        # 1. 停止 systemd 服務
        for svc in ['quay-app.service', 'quay-postgres.service', 'quay-redis.service']:
            self._run_command(f"systemctl stop {svc} 2>/dev/null")
        self._log("已停止 systemd 服務")

        # 2. 優先使用官方 uninstall
        uninstall_cmd = f"cd {home_dir} && ./mirror-registry uninstall --quayRoot {quay_root} -y 2>/dev/null"
        success, stdout, stderr = self._run_command(uninstall_cmd, timeout=120)
        if success:
            self._log("官方 uninstall 執行完成")
        else:
            self._log(f"官方 uninstall 失敗或不適用，改用手動清理", "WARNING")

        # 3. 手動移除所有 quay 相關容器
        self._run_command(
            "podman ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
            "xargs -r podman rm -f 2>/dev/null || "
            "docker ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
            "xargs -r docker rm -f 2>/dev/null"
        )
        self._log("已移除 quay 容器")

        # 4. 移除 pod
        self._run_command("podman pod rm -f quay-pod 2>/dev/null")
        self._log("已移除 quay-pod")

        # 5. 移除所有相關 volumes
        self._run_command(
            "podman volume ls -q 2>/dev/null | "
            "grep -iE 'quay|sqlite|redis' | "
            "xargs -r podman volume rm -f 2>/dev/null"
        )
        self._log("已移除相關 volumes")

        # 6. 移除 systemd 服務檔案
        for svc in ['quay-app.service', 'quay-postgres.service', 'quay-redis.service']:
            svc_path = f"/etc/systemd/system/{svc}"
            if os.path.exists(svc_path):
                self._run_command(f"rm -f {svc_path}")
                self._log(f"已移除 systemd 服務: {svc}")
        self._run_command("systemctl daemon-reload 2>/dev/null")

        # 8. 清除 /opt/quay 和 /opt/quay-storage
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
        # 從 config 取得路徑
        configured_path = self.config.get('mirrorRegistryDir', '')
        if configured_path and os.path.exists(configured_path):
            return configured_path

        # 在 install_source 中搜尋
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

        # 移除所有包含該 FQDN 的舊記錄
        self._run_command(f"sed -i '/{bastion_fqdn}/d' /etc/hosts")

        # 添加新記錄（IP + FQDN）
        self._run_command(f"echo '{bastion_ip} {bastion_fqdn}' >> /etc/hosts")

        # 驗證寫入
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
