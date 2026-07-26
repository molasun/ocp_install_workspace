import os
import time
from typing import Tuple, Optional
from .base_manager import BaseManager


class MirrorRegistryManager(BaseManager):
    """Mirror Registry 管理類別

    安裝流程:
      1. 連線測試 → 若已運行則直接返回
      2. 徹底清理 → 移除所有舊安裝殘留並驗證清理完畢
      3. 準備環境 → /etc/hosts、root SSH
      4. 解壓安裝包
      5. 執行 mirror-registry install
      6. 修正 Redis 密碼不一致
      7. 信任 CA 憑證
      8. 健康檢查 + 連線驗證
    """

    # 清理重試次數上限
    _CLEANUP_MAX_RETRIES = 3

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------

    def check_installed(self) -> Tuple[bool, str]:
        """檢查 Mirror Registry 容器是否正在運行

        mirror-registry 容器由 root 管理，需用 sudo podman 檢查。
        用 grep 而非 --filter 因為 ansible_runner_instance 不含 'quay'。
        """
        success, stdout, _ = self._run_command(
            "sudo podman ps --format '{{.Names}}' 2>/dev/null | "
            "grep -iE 'quay|ansible_runner'"
        )
        running = [n.strip() for n in stdout.split('\n') if n.strip()] if success and stdout.strip() else []

        if running:
            self._log(f"Quay 容器運行中: {', '.join(running)}")
            return True, f"Quay 容器運行中: {', '.join(running)}"
        return False, "Quay 容器未運行"

    def install(self) -> Tuple[bool, str]:
        """安裝 Mirror Registry

        完整流程：連線檢測 → 徹底清理 → 準備環境 → 解壓 → 安裝 → 修復 → 驗證
        """
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        bastion_fqdn = self._resolve_bastion_fqdn()

        # ── Step 1: 連線測試 ──
        connected, connect_msg = self.verify_connection()
        if connected:
            self._log("Mirror Registry 已運行且連線正常，跳過安裝")
            return True, "Mirror Registry 已安裝並運行"

        self._log(f"連線驗證失敗 ({connect_msg})，開始安裝流程...")

        # ── Step 2: 徹底清理舊安裝 ──
        self._thorough_cleanup(quay_root, quay_storage)

        # ── Step 3: 準備環境 ──
        self._ensure_hosts_entry(
            self.config.get('bastion', {}).get('ip', ''),
            bastion_fqdn
        )
        if not self._setup_root_ssh():
            return False, "root SSH 免密碼設定失敗"

        # ── Step 4: 解壓安裝包 ──
        home_dir = os.path.expanduser("~")
        tar_path = self._find_mirror_registry_tar()
        if not tar_path:
            return False, "找不到 mirror-registry 安裝包"
        self._log(f"mirror-registry tar: {tar_path}")

        if not self._extract_installer(tar_path, home_dir):
            return False, "解壓 mirror-registry 失敗"

        # ── Step 5: 執行安裝 ──
        log_path = self._run_mirror_registry_install(
            home_dir, bastion_fqdn, quay_root, quay_storage
        )

        # ── Step 6: 修正 Redis 密碼不一致（Ansible bug workaround） ──
        self._fix_redis_password(quay_root)

        # ── Step 7: 信任 CA ──
        self._trust_ca(quay_root)

        # ── Step 8: 健康檢查 + 連線驗證 ──
        if not self._health_check(bastion_fqdn):
            return False, (
                f"安裝完成但 Quay 健康檢查未通過\n\n"
                f"📄 完整日誌: {log_path}"
            )

        verify_success, verify_msg = self.verify_connection()
        if verify_success:
            return True, "✅ Mirror Registry 安裝成功，健康檢查與連線驗證通過"
        return False, f"安裝完成且健康檢查通過，但連線驗證失敗: {verify_msg}"

    def verify_connection(self) -> Tuple[bool, str]:
        """驗證 Mirror Registry 連線（使用 FQDN，與安裝時一致）"""
        bastion_fqdn = self._resolve_bastion_fqdn()
        registry_password = self.config.get('registryPassword', 'password')

        success, stdout, stderr = self._run_command(
            f"podman login {bastion_fqdn}:8443 "
            f"-u init -p {registry_password} "
            f"--tls-verify=false",
            timeout=30
        )
        if success:
            return True, "Registry 連線驗證通過"
        return False, f"Registry 連線失敗: {stderr[:200]}"

    # ------------------------------------------------------------------
    # Step 2: 徹底清理
    # ------------------------------------------------------------------

    def _thorough_cleanup(self, quay_root: str, quay_storage: str) -> None:
        """徹底清理所有 Mirror Registry 殘留，確認清理完畢後才返回

        清理範圍:
          - podman pod / 容器 / volume / image
          - mirror-registry 官方 uninstall
          - 檔案目錄: quayRoot, quayStorage, ~/mirror-registry, ~/.quay, /root/.quay
          - systemd service 檔案
          - CA 憑證

        清理完畢後呼叫 _verify_cleanup() 確認，不乾淨則重試。
        """
        self._log("=" * 50)
        self._log("開始徹底清理 Mirror Registry 殘留...")
        self._log("=" * 50)

        home_dir = os.path.expanduser("~")

        for attempt in range(1, self._CLEANUP_MAX_RETRIES + 1):
            self._log(f"--- 清理第 {attempt}/{self._CLEANUP_MAX_RETRIES} 次 ---")

            # 1. podman 容器 / pod
            self._cleanup_podman_containers()

            # 2. podman volume（prune 只清無主 volume，不影響其他應用）
            self._cleanup_podman_volumes()

            # 3. podman image（mirror-registry 相關）
            self._cleanup_podman_images()

            # 4. mirror-registry 官方 uninstall
            self._run_official_uninstall(home_dir, quay_root)

            # 5. 檔案目錄清理
            self._cleanup_directories(quay_root, quay_storage, home_dir)

            # 6. systemd service
            self._cleanup_systemd()

            # 7. CA 憑證
            self._cleanup_ca_cert()

            # 驗證清理完畢
            if self._verify_cleanup(quay_root, quay_storage, home_dir):
                self._log("✅ 徹底清理完畢，環境乾淨")
                return

            self._log(f"⚠ 清理未完全成功，準備重試...", "WARNING")
            time.sleep(2)

        self._log("警告: 達到最大重試次數，強制繼續", "WARNING")

    # ── 清理子步驟 ──

    def _cleanup_podman_containers(self) -> None:
        """移除所有 quay 相關容器與 pod"""
        # 先移除整個 pod（會連帶移除 pod 內所有容器）
        self._run_command("sudo podman pod rm -f quay-pod 2>/dev/null")

        # 清除 pod 外殘留的 quay / ansible_runner 容器
        self._run_command(
            "sudo podman ps -a --format '{{.Names}}' 2>/dev/null | "
            "grep -iE 'quay|ansible_runner' | "
            "xargs -r sudo podman rm -f 2>/dev/null"
        )
        self._log("已移除 quay-pod 及所有 quay 容器")

    def _cleanup_podman_volumes(self) -> None:
        """清理無主 podman volume（只刪除未被任何容器使用的）"""
        self._run_command("sudo podman volume prune -f 2>/dev/null")
        self._log("已清理無主 podman volumes")

    def _cleanup_podman_images(self) -> None:
        """移除 mirror-registry 相關的 podman image"""
        image_patterns = [
            'quay.io/quay/mirror-registry-ee',
            'registry.redhat.io/quay/quay-rhel8',
            'registry.redhat.io/rhel8/redis',
            'registry.redhat.io/rhel8/postgresql',
            'registry.access.redhat.com/ubi8/pause',
        ]
        for pattern in image_patterns:
            self._run_command(
                f"sudo podman images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' 2>/dev/null | "
                f"grep '{pattern}' | "
                f"xargs -r sudo podman rmi -f 2>/dev/null"
            )
        self._log("已移除 mirror-registry 相關 podman images")

    def _run_official_uninstall(self, home_dir: str, quay_root: str) -> None:
        """執行 mirror-registry 官方 uninstall 腳本"""
        script_path = os.path.join(home_dir, "mirror-registry")
        if os.path.exists(script_path):
            self._log("執行 mirror-registry 官方 uninstall...")
            self._run_command(
                f"cd {home_dir} && "
                f"./mirror-registry uninstall --quayRoot {quay_root} -y 2>/dev/null",
                timeout=120
            )
            self._log("mirror-registry 官方 uninstall 完成")
        else:
            self._log(f"mirror-registry 腳本不存在 ({script_path})，跳過 uninstall")

    def _cleanup_directories(self, quay_root: str, quay_storage: str, home_dir: str) -> None:
        """移除所有 mirror-registry 相關目錄"""
        dirs_to_remove = [
            quay_root,                    # Quay 配置目錄
            quay_storage,                 # Quay 儲存目錄
            f"{home_dir}/mirror-registry", # 解壓後的安裝包目錄
            f"{home_dir}/.quay",           # 用戶 quay 狀態目錄
            "/root/.quay",                 # root quay 狀態目錄
        ]
        for d in dirs_to_remove:
            self._run_command(f"sudo rm -rf {d} 2>/dev/null")
        self._log(f"已移除目錄: {', '.join(dirs_to_remove)}")

    def _cleanup_systemd(self) -> None:
        """移除 mirror-registry 建立的 systemd service"""
        self._run_command("sudo rm -f /etc/systemd/system/quay-*.service 2>/dev/null")
        self._run_command("sudo systemctl daemon-reload 2>/dev/null")
        self._log("已移除 quay systemd service")

    def _cleanup_ca_cert(self) -> None:
        """移除 mirror-registry 新增的 CA 憑證"""
        ca_file = "/etc/pki/ca-trust/source/anchors/rootCA.pem"
        self._run_command(f"sudo rm -f {ca_file} 2>/dev/null")
        self._run_command("sudo update-ca-trust 2>/dev/null")
        self._log("已移除 mirror-registry CA 憑證")

    def _verify_cleanup(self, quay_root: str, quay_storage: str, home_dir: str) -> bool:
        """驗證清理完畢，確認沒有殘留

        檢查項目:
          1. 沒有運行中或已停止的 quay 容器
          2. 沒有 quay-pod
          3. port 8443 未被佔用
          4. quayRoot / quayStorage 目錄不存在
          5. ~/mirror-registry 目錄不存在
        """
        checks = []

        # 1. 容器檢查
        success, stdout, _ = self._run_command(
            "sudo podman ps -a --format '{{.Names}}' 2>/dev/null | "
            "grep -iE 'quay|ansible_runner' || true"
        )
        containers_clean = not (success and stdout.strip())
        checks.append(("無殘留 quay 容器", containers_clean))
        if not containers_clean:
            self._log(f"  仍有殘留容器: {stdout.strip()}", "WARNING")

        # 2. Pod 檢查
        success, stdout, _ = self._run_command(
            "sudo podman pod ps --format '{{.Name}}' 2>/dev/null | "
            "grep -i 'quay' || true"
        )
        pod_clean = not (success and stdout.strip())
        checks.append(("無殘留 quay pod", pod_clean))
        if not pod_clean:
            self._log(f"  仍有殘留 pod: {stdout.strip()}", "WARNING")

        # 3. Port 檢查
        success, stdout, _ = self._run_command(
            "ss -tlnp 2>/dev/null | grep ':8443' || "
            "netstat -tlnp 2>/dev/null | grep ':8443' || true"
        )
        port_clean = not (success and stdout.strip())
        checks.append(("port 8443 未被佔用", port_clean))
        if not port_clean:
            self._log(f"  port 8443 仍有監聽: {stdout.strip()}", "WARNING")

        # 4. 目錄檢查
        for label, path in [
            ("quayRoot 不存在", quay_root),
            ("quayStorage 不存在", quay_storage),
            ("~/mirror-registry 不存在", os.path.join(home_dir, "mirror-registry")),
        ]:
            clean = not os.path.exists(path)
            checks.append((label, clean))
            if not clean:
                self._log(f"  目錄仍存在: {path}", "WARNING")

        # 匯總結果
        all_clean = all(passed for _, passed in checks)
        for label, passed in checks:
            status = "✓" if passed else "✗"
            self._log(f"  {status} {label}")

        return all_clean

    # ------------------------------------------------------------------
    # Step 3: 環境準備
    # ------------------------------------------------------------------

    def _setup_root_ssh(self) -> bool:
        """確保 root 免密碼 SSH 到自身

        mirror-registry 的 Ansible execution environment 容器硬編碼使用
        /root/.ssh/id_rsa 作為 SSH 私鑰，因此必須生成 RSA 金鑰（非 ed25519）。
        這是 Red Hat mirror-registry 工具的約束，不可更改金鑰類型。
        """
        self._log("設定 root SSH 免密碼 (id_rsa)...")

        key_path = "/root/.ssh/id_rsa"

        # 1. 建立目錄並修復權限
        self._run_command("sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh")

        # 2. 若 id_rsa 不存在則生成（mirror-registry 要求 id_rsa）
        _, stdout, _ = self._run_command(
            f"sudo test -f {key_path} && echo yes || echo no"
        )
        if "yes" not in stdout:
            self._log("產生新的 root SSH key pair (RSA)...")
            gen_ok, _, gen_err = self._run_command(
                f"sudo ssh-keygen -t rsa -f {key_path} -N '' -q"
            )
            if not gen_ok:
                self._log(f"ssh-keygen 失敗: {gen_err}", "ERROR")
                return False

        # 3. 將 public key 追加到 authorized_keys（不覆蓋既有條目）
        #    保留 mirror-registry 可能已加入的 quay_installer 等其他 key
        self._run_command(
            f"sudo sh -c 'cat {key_path}.pub >> /root/.ssh/authorized_keys' && "
            "sudo sort -u /root/.ssh/authorized_keys -o /root/.ssh/authorized_keys && "
            "sudo chmod 600 /root/.ssh/authorized_keys && "
            f"sudo chmod 644 {key_path}.pub"
        )

        # 4. 驗證 SSH 連線（與 mirror-registry 相同的方式：localhost）
        success, _, err = self._run_command(
            "sudo ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
            "root@localhost echo ok"
        )
        if success:
            self._log("root SSH 設定成功 (已驗證 root@localhost)")
            return True

        self._log(f"root SSH 設定失敗: {err[:200]}", "ERROR")
        return False

    # ------------------------------------------------------------------
    # Step 4: 解壓安裝包
    # ------------------------------------------------------------------

    def _extract_installer(self, tar_path: str, dest_dir: str) -> bool:
        """解壓 mirror-registry 安裝包並確認必要檔案"""
        self._log(f"解壓 mirror-registry 到 {dest_dir} ...")
        success, _, err = self._run_command(f"tar -xzf {tar_path} -C {dest_dir}/")
        if not success:
            self._log(f"解壓失敗: {err}", "ERROR")
            return False

        self._log("解壓完成，確認必要檔案...")
        all_found = True
        for fname in ['mirror-registry', 'image-archive.tar', 'execution-environment.tar']:
            fpath = os.path.join(dest_dir, fname)
            if os.path.exists(fpath):
                self._log(f"  ✓ {fname}")
            else:
                self._log(f"  ✗ 未找到 {fname}", "WARNING")
                all_found = False
        return all_found

    # ------------------------------------------------------------------
    # Step 5: 執行 mirror-registry install
    # ------------------------------------------------------------------

    def _run_mirror_registry_install(
        self, home_dir: str, bastion_fqdn: str,
        quay_root: str, quay_storage: str
    ) -> str:
        """執行 mirror-registry install 並返回日誌路徑

        注意：Ansible playbook 可能因 Wait-for-Quay 超時而返回非零退出碼，
        但這不一定是真正的失敗（可能是 Redis 密碼不一致導致），
        後續 _fix_redis_password 會處理。
        """
        registry_password = self.config.get('registryPassword', 'password')

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
            self._log(
                f"mirror-registry install 回報失敗: {err}，"
                f"繼續執行後續修復..."
            )
        else:
            self._log("mirror-registry install 完成")

        return log_path

    # ------------------------------------------------------------------
    # Step 6: 修正 Redis 密碼不一致
    # ------------------------------------------------------------------

    def _fix_redis_password(self, quay_root: str) -> None:
        """修正 mirror-registry Ansible 造成的 Redis 密碼不一致

        Ansible playbook 可能給 Quay config.yaml 和 Redis 容器產生不同的隨機密碼，
        導致 quay-app 啟動時報 WRONGPASS 無法連接 Redis。

        此方法從 Redis 容器內讀取真實 requirepass，
        回寫到 Quay config 後重啟 quay-app。
        """
        config_yaml = f"{quay_root}/quay-config/config.yaml"
        if not os.path.exists(config_yaml):
            self._log(f"config.yaml 不存在 ({config_yaml})，跳過 Redis 密碼修正", "WARNING")
            return

        # 1. 從 Redis 容器內取得實際 requirepass
        success, stdout, _ = self._run_command(
            "sudo podman exec quay-redis grep '^requirepass' /etc/redis.conf 2>/dev/null | "
            "head -1 | sed 's/.*\"\\(.*\\)\".*/\\1/'"
        )
        if not success or not stdout.strip():
            self._log("無法讀取 Redis requirepass，跳過密碼修正", "WARNING")
            return
        redis_password = stdout.strip()

        # 2. 比對 Quay config 中的 Redis 密碼
        success, stdout, _ = self._run_command(
            f"sudo grep -A3 'USER_EVENTS_REDIS:' {config_yaml} 2>/dev/null | "
            "grep 'password:' | awk '{print $2}'"
        )
        if success and stdout.strip() == redis_password:
            self._log("Redis 密碼一致，無需修正")
            return

        # 3. 密碼不一致 ── 將 Redis 真實密碼寫回 Quay config
        self._log("偵測到 Redis 密碼不一致，修正 Quay config...")
        self._run_command(
            f"sudo sed -i '/BUILDLOGS_REDIS:/,/password:/"
            f"s/password:.*/password: {redis_password}/' {config_yaml}"
        )
        self._run_command(
            f"sudo sed -i '/USER_EVENTS_REDIS:/,/password:/"
            f"s/password:.*/password: {redis_password}/' {config_yaml}"
        )
        self._log(f"已修正 Quay config Redis 密碼")

        # 4. 寫入後再次確認 config.yaml 密碼確實更新
        _, updated_pw, _ = self._run_command(
            f"sudo grep -A3 'USER_EVENTS_REDIS:' {config_yaml} 2>/dev/null | "
            "grep 'password:' | awk '{print $2}'"
        )
        if updated_pw.strip() != redis_password:
            self._log("警告: config.yaml 密碼寫入後驗證不一致", "WARNING")

        # 5. 重啟 quay-app 讓新密碼生效
        self._run_command("sudo podman restart quay-app 2>/dev/null")
        self._run_command("sudo systemctl restart quay-app.service 2>/dev/null")
        self._log("已重啟 quay-app")

    # ------------------------------------------------------------------
    # Step 7: 信任 CA 憑證
    # ------------------------------------------------------------------

    def _trust_ca(self, quay_root: str) -> None:
        """信任 Mirror Registry 的 CA 憑證"""
        ca_path = f"{quay_root}/quay-rootCA/rootCA.pem"
        ca_target_dir = "/etc/pki/ca-trust/source/anchors/"

        if not os.path.exists(ca_path):
            self._log(f"找不到 CA 憑證: {ca_path}", "WARNING")
            return

        self._log("信任 Mirror Registry CA 憑證...")
        self._run_command(f"sudo cp {ca_path} {ca_target_dir}")
        self._run_command("sudo update-ca-trust")
        self._log("CA 憑證信任完成")

    # ------------------------------------------------------------------
    # Step 8: 健康檢查
    # ------------------------------------------------------------------

    def _health_check(self, bastion_fqdn: str, max_retries: int = 10, interval: int = 30) -> bool:
        """等待 Quay 就緒，輪詢 /v2/ endpoint"""
        self._log("等待 Quay 就緒...")
        for i in range(max_retries):
            success, stdout, _ = self._run_command(
                f"curl -sk -o /dev/null -w '%{{http_code}}' "
                f"--connect-timeout 5 https://{bastion_fqdn}:8443/v2/"
            )
            if success and "200" in stdout:
                self._log("Quay 健康檢查通過！")
                return True
            self._log(f"等待 Quay 就緒... ({i + 1}/{max_retries})")
            time.sleep(interval)

        self._log("Quay 健康檢查逾時", "ERROR")
        return False

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _resolve_bastion_fqdn(self) -> str:
        """根據 config 計算 Bastion FQDN"""
        bastion_name = self.config.get('bastion', {}).get('name', 'bastion')
        cluster_name = self.config.get('clusterName', 'ocp4')
        base_domain = self.config.get('baseDomain', 'example.com')
        return f"{bastion_name}.{cluster_name}.{base_domain}"

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
        self._run_command(f"sudo sed -i '/{bastion_fqdn}/d' /etc/hosts")
        self._run_command(f"sudo echo '{bastion_ip} {bastion_fqdn}' | sudo tee -a /etc/hosts > /dev/null")

        success, stdout, _ = self._run_command(f"grep '{bastion_fqdn}' /etc/hosts")
        if success:
            self._log(f"/etc/hosts 已更新: {stdout.strip()}")
        else:
            self._log("警告: /etc/hosts 寫入可能失敗", "WARNING")
