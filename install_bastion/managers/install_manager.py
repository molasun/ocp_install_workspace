import os
from typing import Dict, Tuple, List
from .base_manager import BaseManager


class InstallManager(BaseManager):
    """安裝管理類別（CLI 工具、基礎套件）"""
    
    # 基礎套件列表
    BASE_PACKAGES = ['net-tools', 'git', 'httpd']

    @property
    def _install_source_dir(self) -> str:
        """取得 install_source 目錄路徑"""
        return self._get_install_source_dir() 
    
    def install_packages(self, packages: List[str] = None) -> Tuple[bool, str]:
        """安裝基礎套件 - 對應 packages.yml"""
        if packages is None:
            packages = self.BASE_PACKAGES
        
        self._log(f"開始安裝基礎套件: {', '.join(packages)}...")
        
        failed_packages = []
        installed_packages = []
        
        for package in packages:
            self._log(f"安裝 {package}...")
            success, _, err = self._run_command(f"yum install -y {package}")
            if success:
                installed_packages.append(package)
            else:
                failed_packages.append(package)
                self._log(f"{package} 安裝失敗: {err}", "ERROR")
        
        # 設定 httpd 監聽埠（如果安裝了 httpd）
        if 'httpd' in installed_packages:
            self._configure_httpd()
        
        if failed_packages:
            return False, f"部分套件安裝失敗: {', '.join(failed_packages)}"
        
        return True, f"基礎套件安裝完成: {', '.join(installed_packages)}"
    
    def _configure_httpd(self) -> None:
        """設定 httpd 監聽埠為 8080"""
        self._log("設定 httpd 監聽埠為 8080...")
        httpd_conf = '/etc/httpd/conf/httpd.conf'
        
        self._backup_file(httpd_conf)
        self._run_command(
            "sed -i 's/^Listen 80$/Listen 8080/' /etc/httpd/conf/httpd.conf"
        )
        self._run_command("systemctl restart httpd")
        self._run_command("systemctl enable httpd")

    def _get_tar_path(self, config_key: str, default_filename: str) -> str:
        """
        取得 tar 包的完整路徑
        優先使用 config 中的路徑，如果不存在則使用 ~/install_source/ 下的預設路徑
        """
        configured_path = self.config.get(config_key, '')
        if configured_path and os.path.exists(configured_path):
            return configured_path
        
        # 使用 ~/install_source 下的預設路徑
        default_path = os.path.join(self._install_source_dir, default_filename)
        if os.path.exists(default_path):
            return default_path
        
        # 如果都不存在，返回 config 中的路徑（讓後續邏輯報錯）
        return configured_path or default_path

    def install_openshift_install_cli(self) -> Tuple[bool, str]:
        """安裝 openshift-install CLI"""
        self._log("安裝 openshift-install CLI...")
        
        ocp_install_dir = self._get_tar_path('ocpInstallDir', 'openshift-install-linux.tar.gz')
        self._log(f"使用安裝包: {ocp_install_dir}")
        
        target_path = '/usr/bin/openshift-install'
        
        # 檢查是否已安裝
        if os.path.exists(target_path):
            success, stdout, _ = self._run_command(f"{target_path} version")
            version = stdout.strip() if success else "unknown"
            return True, f"openshift-install 已安裝 (版本: {version})"
        
        # 檢查安裝包
        if not os.path.exists(ocp_install_dir):
            # 嘗試在 install_source 目錄中搜尋
            found = self._search_tar_in_install_source('openshift-install')
            if found:
                ocp_install_dir = found
                self._log(f"在 install_source 中找到: {ocp_install_dir}")
            else:
                return False, f"找不到 openshift-install 安裝包: {ocp_install_dir}"

        # === 先列出 tar 內容，確認解壓後會有哪些檔案 ===
        success, tar_content, _ = self._run_command(f"tar -tzf {ocp_install_dir}")
        if not success:
            return False, f"無法讀取 tar 檔案內容: {ocp_install_dir}"
        
        # 解析 tar 中的檔案列表
        tar_files = [f.strip() for f in tar_content.split('\n') if f.strip() and not f.strip().endswith('/')]
        self._log(f"tar 包含 {len(tar_files)} 個檔案")

        # 解壓安裝
        success, _, err = self._run_command(f"tar -xzf {ocp_install_dir} -C /usr/bin/")
        if not success:
            return False, f"解壓 openshift-install 失敗: {err}"

        # === 檢查解壓結果 ===
        if os.path.exists(target_path):
            self._run_command(f"chmod +x {target_path}")
            return True, "openshift-install 安裝成功"

        # 檢查解壓後是否有 openshift-install，如果名稱不同則重新命名
        for f in tar_files:
            extracted_file = f"/usr/bin/{f}"
            if os.path.exists(extracted_file):
                self._log(f"重新命名 {extracted_file} -> {target_path}")
                self._run_command(f"mv {extracted_file} {target_path}")
                self._run_command(f"chmod +x {target_path}")
                
                if os.path.exists(target_path):
                    return True, "openshift-install 安裝成功"
        
        return False, f"openshift-install 安裝後無法找到執行檔，tar 內容: {tar_files}"
   
    def install_oc_client(self) -> Tuple[bool, str]:
        """安裝 oc 客戶端 CLI"""
        self._log("安裝 oc 客戶端 CLI...")
        
        ocp_client_dir = self._get_tar_path('ocpClientDir', 'openshift-client-linux.tar.gz')
        self._log(f"使用安裝包: {ocp_client_dir}")
        
        target_path = '/usr/bin/oc'
        kubectl_path = '/usr/bin/kubectl'
        
        # 檢查是否已安裝
        if os.path.exists(target_path):
            success, stdout, _ = self._run_command(f"{target_path} version --client")
            version = stdout.strip().split('\n')[0] if success else "unknown"
            return True, f"oc client 已安裝 (版本: {version})"
        
        # 檢查安裝包
        if not os.path.exists(ocp_client_dir):
            found = self._search_tar_in_install_source('openshift-client')
            if found:
                ocp_client_dir = found
                self._log(f"在 install_source 中找到: {ocp_client_dir}")
            else:
                return False, f"找不到 oc client 安裝包: {ocp_client_dir}"
        
        # === 先列出 tar 內容 ===
        success, tar_content, _ = self._run_command(f"tar -tzf {ocp_client_dir}")
        if not success:
            return False, f"無法讀取 tar 檔案內容"
        
        # === 解壓安裝 ===
        success, _, err = self._run_command(f"tar -xzf {ocp_client_dir} -C /usr/bin/")
        if not success:
            return False, f"解壓 oc client 失敗: {err}"
        
        # === 檢查並設定權限 ===
        installed = []
        if os.path.exists(target_path):
            self._run_command(f"chmod +x {target_path}")
            installed.append("oc")
        if os.path.exists(kubectl_path):
            self._run_command(f"chmod +x {kubectl_path}")
            installed.append("kubectl")
        
        if not installed:
            return False, "oc client 安裝後無法找到執行檔"
        
        # 設定 bash completion
        self._setup_bash_completion()
        
        return True, f"oc client 安裝成功 ({', '.join(installed)})"

    def _search_tar_in_install_source(self, pattern: str) -> str:
        """在 install_source 目錄中搜尋匹配的 tar 檔案，優先選擇版本號匹配的"""
        if not os.path.exists(self._install_source_dir):
            return None

        # 從 config 取得 OCP_RELEASE 用於版本優先匹配
        version_info = self.config.get('versionInfo', {})
        ocp_release = version_info.get('ocpRelease', '')

        matching_files = []
        for filename in os.listdir(self._install_source_dir):
            if pattern in filename and filename.endswith('.tar.gz'):
                matching_files.append(filename)

        if not matching_files:
            return None

        # 若只有一個匹配檔案，直接回傳
        if len(matching_files) == 1:
            return os.path.join(self._install_source_dir, matching_files[0])

        # 若有多個匹配檔案，優先選擇包含正確版本號的
        if ocp_release:
            for filename in matching_files:
                if ocp_release in filename:
                    return os.path.join(self._install_source_dir, filename)

        # Fallback：回傳第一個匹配檔案
        return os.path.join(self._install_source_dir, matching_files[0])

    def _setup_bash_completion(self) -> None:
        """設定 oc 命令的 bash completion"""
        target_path = '/usr/bin/oc'
        completion_dir = '/etc/bash_completion.d'
        
        if os.path.exists(target_path):
            os.makedirs(completion_dir, exist_ok=True)
            self._run_command(
                f"{target_path} completion bash > {completion_dir}/oc_bash_completion"
            )
            self._log("已設定 oc bash completion")
    
    def install_all_cli(self) -> Tuple[bool, str]:
        """安裝所有 CLI 工具"""
        self._log("開始安裝所有 CLI 工具...")
        
        results = []
        
        # 安裝 openshift-install
        success, msg = self.install_openshift_install_cli()
        results.append(("openshift-install", success, msg))
        
        # 安裝 oc client
        success, msg = self.install_oc_client()
        results.append(("oc client", success, msg))
        
        # 彙總結果
        failed = [(name, msg) for name, success, msg in results if not success]
        success_list = [(name, msg) for name, success, msg in results if success]
        
        if failed:
            fail_msgs = [f"{name}: {msg}" for name, msg in failed]
            return False, f"部分 CLI 安裝失敗: {'; '.join(fail_msgs)}"
        
        success_msgs = [f"{name}: {msg}" for name, msg in success_list]
        return True, f"所有 CLI 工具安裝完成\n" + "\n".join(success_msgs)
    
    def verify_installations(self) -> Tuple[bool, str]:
        """驗證所有安裝"""
        self._log("驗證安裝...")
        
        checks = []
        
        # 檢查 openshift-install
        if os.path.exists('/usr/bin/openshift-install'):
            _, version, _ = self._run_command('/usr/bin/openshift-install version')
            checks.append(f"✅ openshift-install: {version.strip()}")
        else:
            checks.append("⚠️ openshift-install 未安裝")
        
        # 檢查 oc
        if os.path.exists('/usr/bin/oc'):
            _, version, _ = self._run_command('/usr/bin/oc version --client')
            checks.append(f"✅ oc client: {version.strip().split(chr(10))[0]}")
        else:
            checks.append("⚠️ oc client 未安裝")
        
        # 檢查 podman
        if os.path.exists('/usr/bin/podman'):
            _, version, _ = self._run_command('podman --version')
            checks.append(f"✅ podman: {version.strip()}")
        else:
            checks.append("⚠️ podman 未安裝")
        
        return True, "\n".join(checks)