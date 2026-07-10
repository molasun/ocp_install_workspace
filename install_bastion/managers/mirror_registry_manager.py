import os
import re
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
        """檢查 Quay 主服務是否實際在運行（port 8443 是否有服務監聽）"""
        success, stdout, _ = self._run_command(
            "ss -tlnp 2>/dev/null | grep ':8443' || netstat -tlnp 2>/dev/null | grep ':8443'"
        )
        return success and bool(stdout.strip())
    
    def _ensure_images_loaded(self) -> None:
        """安全網：確保離線容器映像檔已載入 podman 本地存儲"""
        install_source_dir = self._get_install_source_dir()
        if not os.path.exists(install_source_dir):
            return

        for filename in os.listdir(install_source_dir):
            if filename.endswith('.tar') and any(
                kw in filename.lower() for kw in ['quay', 'redis', 'postgres']
            ):
                tar_path = os.path.join(install_source_dir, filename)
                self._log(f"確保映像檔已載入: {tar_path}")
                self._run_command(f"podman load -i {tar_path}", timeout=300)

    
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
        
        # 安全網：確保離線容器映像檔已載入（即使 step3 已載入也不重複）
        self._ensure_images_loaded()
        
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

        # 儲存完整輸出供診斷（無論成功或失敗）
        log_path = os.path.join(self.config_dir, "mirror-registry-install-output.log")
        try:
            with open(log_path, 'w') as f:
                f.write(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n")
        except Exception:
            pass

        # 安裝程式成功或失敗，都先嘗試驗證
        self._trust_ca(quay_root)

        # 等待啟動
        time.sleep(10)

        # 先嘗試直接驗證
        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "✅ Mirror Registry 安裝成功，連線驗證通過"

        # 直接驗證失敗，嘗試修復（Redis 密碼同步 + SQLite 重置）
        self._log("初次驗證失敗，嘗試安裝後修復...", "WARNING")
        self._post_install_recovery(quay_root)

        # 修復後重試驗證（最多 5 分鐘）
        for i in range(10):
            time.sleep(30)
            verify_success, verify_msg = self.verify_connection()
            if verify_success:
                self._log("修復後 Quay 就緒！")
                return True, "✅ Mirror Registry 安裝成功（修復 Redis 密碼與 SQLite 後就緒），連線驗證通過"
            self._log(f"修復後等待 Quay 就緒... ({i+1}/10)")

        # 修復後仍未就緒
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

        return False, (
            f"安裝與修復後仍無法連線: {verify_msg}\n"
            f"安裝輸出摘要: {error_detail}\n\n"
            f"📄 完整日誌: {log_path}\n"
            f"💡 請檢查容器日誌: journalctl -u quay-app.service --no-pager -n 30"
        )
    
    def _sync_redis_password(self, quay_root: str) -> bool:
        """
        從 Redis 容器取得實際密碼並同步到 Quay config.yaml

        Redis 映像檔的 entrypoint 可能生成自己的隨機密碼，
        導致與 Quay config 中的密碼不匹配。
        """
        # 1. 從 Redis 容器 env 取得實際的 REDIS_PASSWORD
        success, stdout, _ = self._run_command(
            "podman exec quay-redis env 2>/dev/null | grep REDIS_PASSWORD | cut -d= -f2"
        )
        if not success or not stdout.strip():
            self._log("quay-redis 容器未運行或無法取得 REDIS_PASSWORD", "WARNING")
            return False

        actual_password = stdout.strip()

        # 2. 讀取 Quay config.yaml
        config_path = os.path.join(quay_root, 'quay-config', 'config.yaml')
        if not os.path.exists(config_path):
            self._log(f"Quay config 不存在: {config_path}", "WARNING")
            return False

        try:
            with open(config_path, 'r') as f:
                config_content = f.read()
        except Exception as e:
            self._log(f"讀取 config.yaml 失敗: {e}", "WARNING")
            return False

        # 3. 從 config 中找出 BUILDLOGS_REDIS 下的密碼
        match = re.search(r'BUILDLOGS_REDIS:\s*\n\s*host:.*?\n\s*password:\s*(\S+)', config_content)
        if not match:
            self._log("config.yaml 中未找到 BUILDLOGS_REDIS 密碼", "WARNING")
            return False

        config_password = match.group(1)

        if config_password == actual_password:
            self._log("Redis 密碼已一致，無需同步")
            return True

        # 4. 用 sed 替換所有舊密碼為新密碼
        self._log(f"同步 Redis 密碼到 config.yaml")
        self._run_command(
            f"sed -i 's/{config_password}/{actual_password}/g' {config_path}"
        )
        self._log("Redis 密碼同步完成")
        return True

    def _reset_sqlite_volume(self) -> bool:
        """
        重置 SQLite volume（清除部分初始化的資料庫）

        Quay 首次啟動可能因 Redis 密碼不匹配而崩潰，
        留下部分初始化的 SQLite 資料庫，導致重啟時 "table already exists" 錯誤。
        """
        self._log("重置 SQLite volume...")

        # 1. 停止 Quay
        self._run_command("systemctl stop quay-app 2>/dev/null")
        time.sleep(2)

        # 2. 移除 quay-app 容器（釋放 volume 佔用）
        self._run_command("podman rm -f quay-app 2>/dev/null")

        # 3. 移除 sqlite-storage volume
        self._run_command("podman volume rm -f sqlite-storage 2>/dev/null")
        self._log("已移除 sqlite-storage volume")

        # 4. 重啟 Quay（systemd 會重新建立容器和 volume）
        self._run_command("systemctl start quay-app")
        self._log("已重啟 quay-app")

        return True

    def _post_install_recovery(self, quay_root: str) -> None:
        """
        安裝後修復：同步 Redis 密碼 + 重置 SQLite volume

        處理 Redis 映像檔密碼不匹配及 SQLite 部分初始化的問題。
        """
        self._log("執行安裝後修復（Redis 密碼同步 + SQLite 重置）...")

        # 1. 同步 Redis 密碼
        self._sync_redis_password(quay_root)

        # 2. 重置 SQLite volume
        self._reset_sqlite_volume()

        # 3. 等待 Quay 重新啟動並初始化
        time.sleep(15)

    def _cleanup_installation(self, quay_root: str, quay_storage: str) -> None:
        """清理舊的 Mirror Registry 安裝（確保完全清除所有殘留）"""
        self._log("開始清理舊的 Mirror Registry 安裝...")

        # 1. 停止 systemd 服務（防止容器自動重啟）
        for svc in ['quay-app.service', 'quay-postgres.service', 'quay-redis.service']:
            self._run_command(f"systemctl stop {svc} 2>/dev/null")
        self._log("已停止 systemd 服務")

        # 2. 優先使用官方 uninstall
        uninstall_cmd = f"cd /tmp && ./mirror-registry uninstall --quayRoot {quay_root} -y"
        success, stdout, stderr = self._run_command(uninstall_cmd, timeout=120)
        if success:
            self._log("官方 uninstall 執行完成")
        else:
            self._log(f"官方 uninstall 失敗或不適用，改用手動清理: {(stderr or stdout)[:200]}", "WARNING")

        # 3. 手動移除所有 quay 相關容器（無論官方 uninstall 是否成功，確保清除乾淨）
        self._run_command(
            "podman ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
            "xargs -r podman rm -f 2>/dev/null || "
            "docker ps -a --filter 'name=quay' --format '{{.Names}}' 2>/dev/null | "
            "xargs -r docker rm -f 2>/dev/null"
        )
        self._log("已移除 quay 容器")

        # 4. 移除 pod（關鍵：pod 殘留會導致網路/密碼不匹配）
        self._run_command("podman pod rm -f quay-pod 2>/dev/null")
        self._log("已移除 quay-pod")

        # 5. 移除所有相關 volumes（含 sqlite-storage、quay 相關）
        self._run_command(
            "podman volume ls -q 2>/dev/null | "
            "grep -iE 'quay|sqlite|redis' | "
            "xargs -r podman volume rm -f 2>/dev/null"
        )
        self._log("已移除相關 volumes（含 sqlite-storage）")

        # 6. 移除 systemd 服務檔案
        for svc in ['quay-app.service', 'quay-postgres.service', 'quay-redis.service']:
            svc_path = f"/etc/systemd/system/{svc}"
            if os.path.exists(svc_path):
                self._run_command(f"rm -f {svc_path}")
                self._log(f"已移除 systemd 服務: {svc}")
        self._run_command("systemctl daemon-reload 2>/dev/null")

        # 7. 移除目錄
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
