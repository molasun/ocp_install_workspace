import os
import time
import shutil
from typing import Dict, Optional, Tuple
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
        
        # 方法3: 檢查是否有已安裝但停止的容器（目錄 + 容器同時存在才算已安裝）
        quay_root = self.config.get('quayRoot', '/opt/quay')
        if os.path.exists(quay_root) and os.path.exists(f"{quay_root}/config"):
            success, stdout, _ = self._run_command(
                "podman ps -a --filter 'name=quay' --format '{{.Names}} {{.Status}}' 2>/dev/null || "
                "docker ps -a --filter 'name=quay' --format '{{.Names}} {{.Status}}' 2>/dev/null"
            )
            if success and stdout.strip():
                return True, f"Registry 已安裝但未運行: {stdout.strip()}"
            # 目錄存在但無容器 → 視為未安裝（殘留目錄）
            return False, "Mirror Registry 未安裝（發現殘留目錄但無容器）"
        
        # 方法4: curl 檢查
        success, stdout, _ = self._run_command(
            f"curl -sk -o /dev/null -w '%{{http_code}}' --connect-timeout 3 https://{bastion_ip}:8443/v2/",
            timeout=5
        )
        if success and stdout.strip() in ['200', '401']:
            return True, "Mirror Registry HTTP 回應正常"
        
        return False, "Mirror Registry 未安裝"
    
    def _check_containers_running(self) -> bool:
        """檢查 quay 相關容器是否實際在運行"""
        success, stdout, _ = self._run_command(
            "podman ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null || "
            "docker ps --filter 'name=quay' --format '{{.Names}}' 2>/dev/null"
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
        
        # === 確保 /etc/hosts 有正確的 DNS 記錄 ===
        self._ensure_hosts_entry(bastion_ip, bastion_fqdn)
        
        # === 檢查是否已安裝並運行 ===
        installed, msg = self.check_installed()
        
        if installed:
            # 已安裝：嘗試啟動（如果未運行）並驗證
            self._log(f"Mirror Registry 已安裝: {msg}")
            
            if "未運行" in msg:
                self._log("嘗試啟動現有 Registry...")
                self._run_command(
                    "podman start $(podman ps -a --filter 'name=quay' --format '{{.Names}}' | head -1) 2>/dev/null || "
                    "docker start $(docker ps -a --filter 'name=quay' --format '{{.Names}}' | head -1) 2>/dev/null"
                )
                time.sleep(5)
            
            # 驗證連線
            verify_success, verify_msg = self.verify_connection()
            if verify_success:
                return True, "✅ Mirror Registry 已安裝，跳過安裝步驟。連線驗證成功"
            else:
                # 驗證失敗：清理舊安裝並重新安裝
                self._log(f"已安裝的 Registry 驗證失敗: {verify_msg}，開始清理並重新安裝...", "WARNING")
                self._cleanup_installation(quay_root, quay_storage)
        
        # === 執行全新安裝 ===
        return self._fresh_install(quay_root, quay_storage, bastion_fqdn, registry_password)
    
    def _fresh_install(self, quay_root: str, quay_storage: str, bastion_fqdn: str, registry_password: str) -> Tuple[bool, str]:
        """執行全新安裝"""
        self._log("📦 Mirror Registry 開始全新安裝...")
        
        mirror_registry_dir = self._find_mirror_registry_tar()
        if not mirror_registry_dir:
            return False, "找不到 Mirror Registry 安裝包"
        
        self._log(f"解壓 {mirror_registry_dir}...")
        success, _, err = self._run_command(f"tar -xzf {mirror_registry_dir} -C /tmp/")
        if not success:
            return False, f"解壓失敗: {err}"
        
        install_cmd = (
            f"cd /tmp && ./mirror-registry install "
            f"--quayHostname {bastion_fqdn}:8443 "
            f"--quayRoot {quay_root} "
            f"--quayStorage {quay_storage} "
            f"--initPassword {registry_password}"
        )
        
        self._log(f"執行安裝...")
        success, stdout, stderr = self._run_command(install_cmd, timeout=600)

        if not success:
            # 將完整輸出存到檔案供診斷
            log_path = os.path.join(self.config_dir, "mirror-registry-install-output.log")
            try:
                with open(log_path, 'w') as f:
                    f.write(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n")
            except Exception:
                pass
            self._log(f"完整安裝輸出已儲存至: {log_path}", "INFO")

            # 安裝程式可能因健康檢查超時而返回 rc=1，但容器實際已部署
            # 檢查容器是否在運行，若是則額外等待 Quay 就緒
            self._log("安裝程式返回失敗，檢查容器是否實際已部署...", "WARNING")
            container_running = self._check_containers_running()

            if container_running:
                # 容器已運行，Quay 可能只是需要更多時間初始化
                self._log("容器已運行，額外等待 Quay 就緒（最多 5 分鐘）...")
                self._trust_ca(quay_root)

                for i in range(10):
                    time.sleep(30)
                    verify_success, verify_msg = self.verify_connection()
                    if verify_success:
                        self._log("Quay 在安裝程式超時後最終就緒！")
                        return True, "✅ Mirror Registry 安裝成功（安裝程式超時但 Quay 最終就緒），連線驗證通過"
                    self._log(f"等待 Quay 就緒... ({i+1}/10)")

                # 5 分鐘後仍未就緒
                return False, (
                    f"安裝程式超時且 Quay 在額外等待後仍未就緒。\n"
                    f"最後驗證結果: {verify_msg}\n\n"
                    f"📄 完整日誌: {log_path}\n"
                    f"💡 請檢查容器日誌: podman logs $(podman ps --filter name=quay --format '{{{{.Names}}}}' | head -1)"
                )
            else:
                # 容器未運行，安裝確實失敗
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

        # 安裝程式成功返回
        self._trust_ca(quay_root)

        # 等待啟動
        time.sleep(10)
        for i in range(6):
            installed, msg = self.check_installed()
            if installed and "運行" in msg:
                break
            time.sleep(5)

        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "✅ Mirror Registry 安裝成功，連線驗證通過"
        else:
            return False, f"安裝完成但連線失敗: {verify_msg}"
    
    def _cleanup_installation(self, quay_root: str, quay_storage: str) -> None:
        """清理舊的 Mirror Registry 安裝"""
        self._log("開始清理舊的 Mirror Registry 安裝...")

        # 1. 優先使用官方 uninstall（正確停止容器、移除 volumes、清理 systemd）
        uninstall_cmd = f"cd /tmp && ./mirror-registry uninstall --quayRoot {quay_root} -y"
        success, stdout, stderr = self._run_command(uninstall_cmd, timeout=120)
        if success:
            self._log("官方 uninstall 執行完成")
        else:
            self._log(f"官方 uninstall 失敗或不適用，改用手動清理: {(stderr or stdout)[:200]}", "WARNING")

            # 2. 手動停止並移除所有 quay 相關容器
            self._run_command(
                "podman ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
                "xargs -r podman rm -f 2>/dev/null || "
                "docker ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
                "xargs -r docker rm -f 2>/dev/null"
            )
            self._log("已停止並移除 quay 容器")

        # 3. 移除 podman volumes（PostgreSQL/Redis 持久化資料）
        self._run_command(
            "podman volume ls -q --filter name=quay 2>/dev/null | "
            "xargs -r podman volume rm -f 2>/dev/null"
        )
        self._log("已移除 quay 相關 volumes")

        # 4. 移除 systemd 服務檔案
        for svc in ['quay-app.service', 'quay-postgres.service', 'quay-redis.service']:
            svc_path = f"/etc/systemd/system/{svc}"
            if os.path.exists(svc_path):
                self._run_command(f"systemctl stop {svc} 2>/dev/null; rm -f {svc_path}")
                self._log(f"已移除 systemd 服務: {svc}")
        self._run_command("systemctl daemon-reload 2>/dev/null")

        # 5. 移除 quay 目錄
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
        home_dir = BaseManager._get_real_home() if hasattr(BaseManager, '_get_real_home') else os.path.expanduser("~")
        install_source_dir = os.path.join(home_dir, "install_source")
        
        if os.path.exists(install_source_dir):
            for filename in os.listdir(install_source_dir):
                if 'mirror-registry' in filename and filename.endswith('.tar.gz'):
                    return os.path.join(install_source_dir, filename)
        
        return None

    def _ensure_hosts_entry(self, bastion_ip: str, bastion_fqdn: str) -> None:
        """
        確保 /etc/hosts 中有 Bastion FQDN 的記錄
        這樣容器和主機才能解析 Registry 的域名
        """
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
        """驗證 Mirror Registry 連線（使用 FQDN，與安裝時一致）"""
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"
        registry_password = self.config.get('registryPassword', 'password')
        
        # 使用 FQDN 連線（與安裝時的 --quayHostname 一致）
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
