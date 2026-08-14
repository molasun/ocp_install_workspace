import os
import time
from typing import Tuple, Optional

import yaml

from .base_manager import BaseManager


class _LiteralString(str):
    """標記需以 | 區塊標量輸出的 YAML 字串（用於多行 PEM 憑證）"""
    pass


def _literal_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


yaml.add_representer(_LiteralString, _literal_representer)


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

        完整流程：
          1. 連線測試 → 若已運行則直接返回
          2. 快速修復 → 若容器已存在但密碼不對，先嘗試修復（不重裝）
          3. 徹底清理 → 移除所有舊安裝殘留
          4. 準備環境 → /etc/hosts、SSH
          5. 解壓安裝包
          6. 執行 mirror-registry install
          7. 修正 Redis 密碼不一致
          8. 信任 CA 憑證
          9. 健康檢查 + 連線驗證
        """
        quay_root = self.config.get('quayRoot', '/opt/quay')
        quay_storage = self.config.get('quayStorage', '/opt/quay-storage')
        bastion_fqdn = self._resolve_bastion_fqdn()

        # ── Step 1: 連線測試 ──
        connected, connect_msg = self.verify_connection()
        if connected:
            self._log("Mirror Registry 已運行且連線正常，跳過安裝")
            return True, "Mirror Registry 已安裝並運行"

        self._log(f"連線驗證失敗 ({connect_msg})")

        # ── Step 2: 快速修復（若容器已存在，先嘗試修復密碼，不重裝） ──
        if self._try_quick_fix(quay_root, bastion_fqdn):
            return True, "✅ Mirror Registry 快速修復成功（Redis 密碼已修正）"

        # ── Step 3: 徹底清理舊安裝 ──
        self._thorough_cleanup(quay_root, quay_storage)

        # ── Step 4: 準備環境 ──
        self._ensure_hosts_entry(
            self.config.get('bastion', {}).get('ip', ''),
            bastion_fqdn
        )
        if not self._setup_root_ssh():
            return False, "root SSH 免密碼設定失敗"

        # ── Step 5: 解壓安裝包 ──
        home_dir = os.path.expanduser("~")
        tar_path = self._find_mirror_registry_tar()
        if not tar_path:
            return False, "找不到 mirror-registry 安裝包"
        self._log(f"mirror-registry tar: {tar_path}")

        if not self._extract_installer(tar_path, home_dir):
            return False, "解壓 mirror-registry 失敗"

        # ── Step 6: 執行安裝 ──
        log_path = self._run_mirror_registry_install(
            home_dir, bastion_fqdn, quay_root, quay_storage
        )

        # ── Step 7: 修正 Redis 密碼不一致（Ansible bug workaround） ──
        self._fix_redis_password(quay_root)

        # ── Step 8: 信任 CA ──
        self._trust_ca(quay_root)

        # ── Step 9: 健康檢查 + 連線驗證 ──
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
    # Step 2: 快速修復（不重裝，只修 Redis 密碼）
    # ------------------------------------------------------------------

    def _try_quick_fix(self, quay_root: str, bastion_fqdn: str) -> bool:
        """嘗試快速修復：若 Quay 容器已存在但 Redis 密碼不一致，直接修正

        適用場景：mirror-registry install 已跑完，但 quay-app 因 Redis
        密碼不一致而 Degraded。此時不需要整個重裝，只需修密碼後重啟。

        Returns:
            True = 修復成功，Quay 已恢復正常
            False = 不適用快速修復（容器不存在 / 修復無效），需完整重裝
        """
        # 1. 檢查 quay-redis 容器是否在運行（快速修復的前提）
        redis_ok, _, _ = self._run_command(
            "sudo podman ps --format '{{.Names}}' 2>/dev/null | "
            "grep -w 'quay-redis'"
        )
        if not redis_ok:
            self._log("quay-redis 未運行，不適用快速修復，需完整重裝")
            return False

        # 2. 檢查 config.yaml 是否存在
        config_yaml = f"{quay_root}/quay-config/config.yaml"
        if not os.path.exists(config_yaml):
            self._log("config.yaml 不存在，不適用快速修復")
            return False

        self._log("偵測到 Quay 容器已存在，嘗試快速修復 Redis 密碼...")

        # 3. 修正 Redis 密碼
        self._fix_redis_password(quay_root)

        # 4. 確保 CA 憑證已信任（可能上次安裝中斷未完成）
        self._trust_ca(quay_root)

        # 5. 健康檢查 — 等待 quay-app 用新密碼啟動
        if self._health_check(bastion_fqdn):
            # 6. 連線驗證
            connected, _ = self.verify_connection()
            if connected:
                self._log("✅ 快速修復成功！Redis 密碼已修正，Quay 恢復正常")
                return True
            self._log("快速修復後健康檢查通過，但連線驗證失敗", "WARNING")
        else:
            self._log("快速修復後健康檢查未通過", "WARNING")

        self._log("快速修復無效，將執行完整重裝...")
        return False

    # ------------------------------------------------------------------
    # Step 3: 徹底清理
    # ------------------------------------------------------------------

    def _thorough_cleanup(self, quay_root: str, quay_storage: str) -> None:
        """徹底清理所有 Mirror Registry 殘留，確認清理完畢後才返回

        清理順序（重要）:
          1. 停止 systemd service — 避免 systemd 重啟容器導致 volume 無法刪除
          2. 移除 podman pod / 容器
          3. mirror-registry 官方 uninstall
          4. 移除檔案目錄
          5. 移除 podman image
          6. 清理 podman volume — 必須在所有容器移除後才有效
          7. 移除 CA 憑證

        清理完畢後呼叫 _verify_cleanup() 確認，不乾淨則重試。
        """
        self._log("=" * 50)
        self._log("開始徹底清理 Mirror Registry 殘留...")
        self._log("=" * 50)

        home_dir = os.path.expanduser("~")

        for attempt in range(1, self._CLEANUP_MAX_RETRIES + 1):
            self._log(f"--- 清理第 {attempt}/{self._CLEANUP_MAX_RETRIES} 次 ---")

            # 1. 先停 systemd service（避免重啟容器導致 volume 被佔用）
            self._cleanup_systemd()

            # 2. 移除 podman pod / 容器
            self._cleanup_podman_containers()

            # 3. mirror-registry 官方 uninstall
            self._run_official_uninstall(home_dir, quay_root)

            # 4. 移除檔案目錄
            self._cleanup_directories(quay_root, quay_storage, home_dir)

            # 5. 移除 podman image
            self._cleanup_podman_images()

            # 6. 移除 podman secrets（Redis 密碼等，避免重裝時複用舊密碼）
            self._cleanup_podman_secrets()

            # 7. 清理 podman volume（必須在所有容器移除後執行）
            self._cleanup_podman_volumes()

            # 8. 移除 CA 憑證
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

    def _cleanup_podman_secrets(self) -> None:
        """移除 mirror-registry 建立的 podman secrets

        mirror-registry 的 Ansible 會用 podman secret 儲存 Redis 密碼，
        如果不清理，重裝時 Ansible 會複用舊的 secret（舊密碼），
        但同時給 config.yaml 生成新密碼，導致密碼不一致。
        """
        self._run_command(
            "sudo podman secret ls --format '{{.Name}}' 2>/dev/null | "
            "xargs -r sudo podman secret rm 2>/dev/null"
        )
        self._log("已移除所有 podman secrets")

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
        """停止並移除 mirror-registry 建立的 systemd service

        必須先 stop 再刪檔案，否則 systemd 會在容器被刪後重啟它們，
        導致 podman volume 持續被佔用無法清理。
        """
        # 先停止所有 quay 相關 service
        self._run_command(
            "sudo systemctl stop quay-app.service quay-redis.service "
            "quay-pod.service 2>/dev/null || true"
        )
        self._log("已停止 quay systemd services")

        # 再移除 service 檔案
        self._run_command("sudo rm -f /etc/systemd/system/quay-*.service 2>/dev/null")
        self._run_command("sudo systemctl daemon-reload 2>/dev/null")
        self._log("已移除 quay systemd service 檔案")

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
        """確保 mirror-registry 的 SSH 連線環境就緒

        mirror-registry 使用自己生成的 /root/.ssh/quay_installer 金鑰，
        透過 podman -v 掛載到容器內作為 --private-key 使用。
        本方法不生成任何金鑰，只確保：
          1. /root/.ssh 目錄存在且權限正確
          2. 若 quay_installer 已存在，其 public key 在 authorized_keys 中
          3. 若 quay_installer 不存在（首次安裝），mirror-registry 會自行生成
        """
        self._log("檢查 mirror-registry SSH 環境...")

        # 1. 確保 /root/.ssh 目錄存在且權限正確
        self._run_command("sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh")

        quay_key = "/root/.ssh/quay_installer"

        # 2. 檢查 quay_installer 是否存在
        _, stdout, _ = self._run_command(
            f"sudo test -f {quay_key} && echo yes || echo no"
        )
        if "yes" not in stdout:
            self._log(
                "quay_installer 金鑰不存在，mirror-registry 將在安裝時自動生成"
            )
            return True

        # 3. quay_installer 已存在 — 確保其 public key 在 authorized_keys 中
        self._log("quay_installer 金鑰已存在，確保 public key 在 authorized_keys 中")
        self._run_command(
            f"sudo sh -c 'cat {quay_key}.pub >> /root/.ssh/authorized_keys' && "
            "sudo sort -u /root/.ssh/authorized_keys -o /root/.ssh/authorized_keys && "
            "sudo chmod 600 /root/.ssh/authorized_keys"
        )

        # 4. 驗證 SSH 連線（使用 quay_installer，與 mirror-registry 相同）
        success, _, err = self._run_command(
            f"sudo ssh -i {quay_key} "
            "-o StrictHostKeyChecking=no -o ConnectTimeout=5 "
            "root@localhost echo ok"
        )
        if success:
            self._log("mirror-registry SSH 環境就緒 (quay_installer)")
            return True

        self._log(f"SSH 驗證失敗: {err[:200]}", "WARNING")
        return True  # 不阻斷流程，讓 mirror-registry 自行處理

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

    def inject_ca_to_install_config(self) -> Tuple[bool, str]:
        """將 Quay CA 憑證內容注入 install-config.yaml 的 additionalTrustBundle

        與安裝流程解耦：需在 mirror-registry 安裝確認成功後才呼叫。

        OpenShift 節點需要信任 Quay 的自簽 CA 才能拉取鏡像，
        否則會出現 x509: certificate signed by unknown authority。

        Returns:
            (是否成功, 訊息)
        """
        quay_root = self.config.get('quayRoot', '/opt/quay')
        ca_path = os.path.join(quay_root, 'quay-rootCA', 'rootCA.pem')

        install_config_path = os.path.join(
            self._get_install_source_dir(), 'ocp', 'install-config.yaml'
        )

        if not os.path.exists(ca_path):
            msg = f"找不到 CA 憑證: {ca_path}"
            self._log(msg, "ERROR")
            return False, msg

        if not os.path.exists(install_config_path):
            msg = f"install-config.yaml 不存在: {install_config_path}"
            self._log(msg, "ERROR")
            return False, msg

        try:
            with open(ca_path, 'r') as f:
                ca_content = f.read().strip()
        except Exception as e:
            msg = f"讀取 CA 憑證失敗: {e}"
            self._log(msg, "ERROR")
            return False, msg

        if not ca_content:
            msg = "CA 憑證內容為空"
            self._log(msg, "ERROR")
            return False, msg

        try:
            with open(install_config_path, 'r') as f:
                config = yaml.safe_load(f) or {}

            # PEM 憑證為多行，用 | 區塊標量輸出以保留換行
            config['additionalTrustBundle'] = _LiteralString(ca_content)

            with open(install_config_path, 'w') as f:
                yaml.dump(
                    config, f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            msg = "已將 CA 憑證注入 install-config.yaml 的 additionalTrustBundle"
            self._log(msg)
            return True, msg
        except Exception as e:
            msg = f"注入 CA 憑證失敗: {e}"
            self._log(msg, "ERROR")
            return False, msg

    # ------------------------------------------------------------------
    # Step 8: 健康檢查
    # ------------------------------------------------------------------

    def _health_check(self, bastion_fqdn: str, max_retries: int = 10, interval: int = 30) -> bool:
        """等待 Quay 就緒，輪詢 /v2/ endpoint

        Quay 的 /v2/ 端點在正常運作時可能返回：
          - 200：無需認證即可存取
          - 401：需要認證（表示 Quay 已啟動並正常回應）
        兩者都代表 Quay 健康。
        """
        self._log("等待 Quay 就緒...")
        for i in range(max_retries):
            success, stdout, _ = self._run_command(
                f"curl -sk -o /dev/null -w '%{{http_code}}' "
                f"--connect-timeout 5 https://{bastion_fqdn}:8443/v2/"
            )
            if success and stdout.strip() in ("200", "401"):
                self._log(f"Quay 健康檢查通過！ (HTTP {stdout.strip()})")
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
