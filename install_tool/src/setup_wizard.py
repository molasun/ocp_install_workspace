import os
import subprocess
import json
import re
from typing import Optional, Callable, List, Dict, Any, Tuple

from src.logger import log_info, log_error, log_success
from src.operator_manager import OperatorManager
from src.registry_manager import RegistryManager

class ProgressTracker:
    """進度追蹤輔助類別"""
    
    def __init__(self, total_steps: int, callback: Optional[Callable[[float], None]] = None):
        self.total = total_steps
        self.current = 0
        self.callback = callback
    
    def step(self) -> None:
        """完成一個步驟"""
        self.current += 1
        if self.callback:
            self.callback(self.current / self.total)

class SetupWizard:

    # === URL 模板 ===
    URL_OCP_CLIENT = (
        "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/{release}/"
        "openshift-client-linux-{arch}-{rhel}-{release}.tar.gz"
    )
    URL_OCP_INSTALL = (
        "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/{release}/"
        "openshift-install-{rhel}-{arch}.tar.gz"
    )
    URL_OC_MIRROR = (
        "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/{release}/"
        "oc-mirror.{rhel}.tar.gz"
    )
    URL_BUTANE = "https://mirror.openshift.com/pub/openshift-v4/clients/butane/latest/butane-{arch}"
    URL_HELM = (
        "https://developers.redhat.com/content-gateway/file/pub/openshift-v4/clients/helm/"
        "{helm_ver}/helm-linux-{arch}.tar.gz"
    )
    URL_MIRROR_REGISTRY = (
        "https://mirror.openshift.com/pub/cgw/mirror-registry/{mirror_ver}/"
        "mirror-registry-{arch}.tar.gz"
    )
    URL_GRPCURL = "https://github.com/fullstorydev/grpcurl/releases/download/v1.9.3/grpcurl_1.9.3_linux_x86_64.tar.gz"
    URL_TRIDENT = "https://github.com/NetApp/trident/releases/download/v{ver}/trident-installer-{ver}.tar.gz"

    URL_COREOS_ISO_BASE = (
        "https://mirror.openshift.com/pub/openshift-v4/x86_64/dependencies/rhcos/"
        "{version}/latest/"
    )
    COREOS_ISO_FILENAME_TEMPLATE = "rhcos-{version}-x86_64-live-iso.x86_64.iso"

    DEFAULT_GRPCURL_VERSION = "1.9.3" 
    DIR_INSTALL_SOURCE = "install_source"
    DIR_INSTALL_OCP = "install/ocp"
    DIR_DOCKER = ".docker"
    DIR_MIRROR = "mirror"
    DIR_COREOS_ISO = "install_source/coreos"

    def __init__(self, current_dir: Optional[str] = None):
        """初始化基礎目錄結構與子模組"""
        self.current_dir = current_dir or os.getcwd()
        
        # 初始化目錄結構
        self.config_dir = os.path.join(self.current_dir, 'config')
        self.install_source_dir = os.path.join(self.current_dir, self.DIR_INSTALL_SOURCE)
        self.install_ocp_dir = os.path.join(self.current_dir, *self.DIR_INSTALL_OCP.split('/'))
        self.docker_config_dir = os.path.join(self.current_dir, self.DIR_DOCKER)
        
        # 確保必要目錄存在
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 依賴注入：初始化子模組
        self.op_mgr = OperatorManager(current_dir)
        self.registry = RegistryManager(current_dir)

    def apply_pull_secret(self, pull_secret_json: dict) -> bool:
        """
        合併 Pull Secret 到 Docker 認證配置
        
        Args:
            pull_secret_json: Pull Secret JSON 物件
            
        Returns:
            是否成功
        """
        docker_config_path = os.path.join(os.path.expanduser("~"), ".docker", "config.json")
        
        # 讀取現有配置
        existing = self._read_json_file(docker_config_path, {})
        
        # 合併 auths
        existing_auths = existing.get('auths', {})
        for registry, auth in pull_secret_json.get('auths', {}).items():
            existing_auths[registry] = auth
        existing['auths'] = existing_auths
        
        # 寫入多個位置
        return self._write_pull_secret_to_all_locations(existing, docker_config_path)

    def _read_json_file(self, path: str, default: Any = None) -> Any:
        """安全讀取 JSON 檔案"""
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return default if default is not None else {}

    def _write_pull_secret_to_all_locations(self, data: dict, docker_config_path: str) -> bool:
        """將 Pull Secret 寫入所有必要位置"""
        try:
            # 主要位置
            os.makedirs(os.path.dirname(docker_config_path), exist_ok=True)
            self._write_json_file(docker_config_path, data)
            
            # 備份到 config 目錄
            config_path = os.path.join(self.config_dir, 'pull-secret.json')
            self._write_json_file(config_path, data)
            
            # 工作目錄
            work_dir = os.path.join(self.current_dir, self.DIR_DOCKER)
            os.makedirs(work_dir, exist_ok=True)
            self._write_json_file(os.path.join(work_dir, "config.json"), data)
            
            log_success("Pull secret 已合併到 Docker 認證")
            return True
        except Exception as e:
            log_error(f"合併 pull secret 失敗: {e}")
            return False

    def _write_json_file(self, path: str, data: dict) -> None:
        """寫入 JSON 檔案"""
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def run_env_prep(self) -> bool:
        """建立必要的工作目錄"""
        log_info("開始執行 env_prep...")
        
        dirs_to_create = [
            self.install_source_dir,
            self.docker_config_dir,
            self.install_ocp_dir,
            os.path.join(self.install_source_dir, self.DIR_MIRROR),
            os.path.join(self.current_dir, self.DIR_COREOS_ISO),
        ]
        
        for dir_path in dirs_to_create:
            if not self._create_directory(dir_path):
                return False
        
        log_success("env_prep 執行完成")
        return True

    def _create_directory(self, path: str) -> bool:
        """安全建立目錄"""
        if os.path.isdir(path):
            return True
        
        try:
            os.makedirs(path, exist_ok=True)
            log_success(f"創建成功: {path}")
            return True
        except Exception as e:
            log_error(f"創建失敗：{e}")
            return False

    def run_get_tools(self, config: dict, progress_callback: Optional[Callable[[float], None]] = None) -> bool:
        """下載必要工具"""
        log_info("開始執行 get_tools...")
        
        downloads = self._build_download_list(config)
        tracker = ProgressTracker(len(downloads), progress_callback)
        
        for item in downloads:
            if len(item) == 3:
                url, filename, dest_dir = item
            else:
                url, filename = item
                dest_dir = self.install_source_dir
            
            os.makedirs(dest_dir, exist_ok=True)
            
            if not self._download_if_not_exists(url, filename, dest_dir):
                return False
            tracker.step()
        
        log_info("get_tools 執行完成")
        return True

    def _build_download_list(self, config: dict) -> List[tuple]:
        """構建下載列表"""
        v_info = config.get('version_info', {})
        csi_info = config.get('csi_info', {})
        
        params = {
            'release': v_info.get('OCP_RELEASE', ''),
            'arch': v_info.get('ARCHITECTURE', ''),
            'rhel': v_info.get('RHEL_VERSION', ''),
            'helm_ver': v_info.get('HELM_VERSION', ''),
            'mirror_ver': v_info.get('MIRROR_REGISTRY_VERSION', ''),
        }
        
        downloads = [
            (self.URL_OCP_CLIENT.format(**params), f"openshift-client-linux-{params['arch']}-{params['rhel']}-{params['release']}.tar.gz"),
            (self.URL_OCP_INSTALL.format(**params), f"openshift-install-{params['rhel']}-{params['arch']}.tar.gz"),
            (self.URL_OC_MIRROR.format(**params), f"oc-mirror.{params['rhel']}.tar.gz"),
            (self.URL_BUTANE.format(**params), f"butane-{params['arch']}"),
            (self.URL_HELM.format(**params), f"helm-linux-{params['arch']}.tar.gz"),
            (self.URL_MIRROR_REGISTRY.format(**params), f"mirror-registry-{params['arch']}.tar.gz"),
            (self.URL_GRPCURL, f"grpcurl_{self.DEFAULT_GRPCURL_VERSION}_linux_x86_64.tar.gz"),
        ]

        coreos_download = self._build_coreos_download(v_info)
        if coreos_download:
            downloads.append(coreos_download)
        
        # 條件性添加 Trident
        if csi_info.get('CSI_TYPE') == "trident":
            trident_ver = csi_info.get('TRIDENT_INSTALLER', '')
            if trident_ver:
                downloads.append(
                    (self.URL_TRIDENT.format(ver=trident_ver), f"trident-installer-{trident_ver}.tar.gz")
                )
        
        return downloads
    
    def _download_if_not_exists(self, url: str, filename: str, dest_dir: str = None) -> bool:
        """如果檔案不存在則下載"""
        if dest_dir is None:
            dest_dir = self.install_source_dir
        
        dest_path = os.path.join(dest_dir, filename)
        
        if os.path.exists(dest_path):
            file_size = os.path.getsize(dest_path)
            if file_size > 0:
                log_info(f"文件已存在，跳過下載：{filename} ({file_size / (1024*1024):.1f} MB)")
                return True
            else:
                log_info(f"文件存在但為空，重新下載：{filename}")
        
        return self.download_file(url, dest_dir)

    def _build_coreos_download(self, v_info: dict) -> Optional[tuple]:
        """
        構建 CoreOS ISO 下載資訊
        
        從 OCP_RELEASE 解析主版本號（如 4.21.8 -> 4.21），
        並從 mirror 頁面查找最新的 CoreOS 版本號
        
        Returns:
            (url, filename, destination_dir) 或 None
        """
        ocp_release = v_info.get('OCP_RELEASE', '')
        
        # 解析 OCP 主版本號
        match = re.match(r'(\d+\.\d+)', ocp_release)
        if not match:
            log_info(f"無法解析 OCP 版本以獲取 CoreOS ISO: {ocp_release}")
            return None
        
        ocp_major_version = match.group(1)
        
        # 構建 CoreOS mirror URL
        base_url = self.URL_COREOS_ISO_BASE.format(version=ocp_major_version)
        
        # 取得最新的 CoreOS 版本號
        coreos_version = self._get_latest_coreos_version(base_url, ocp_major_version)
        if not coreos_version:
            log_error(f"無法取得 CoreOS {ocp_major_version} 的版本資訊")
            return None
        
        # 構建完整下載 URL 和檔名
        iso_url = base_url + self.COREOS_ISO_FILENAME_TEMPLATE.format(version=coreos_version)
        iso_filename = self.COREOS_ISO_FILENAME_TEMPLATE.format(version=coreos_version)
        
        # CoreOS ISO 存放到專用目錄
        dest_dir = os.path.join(self.current_dir, self.DIR_COREOS_ISO)
        
        log_info(f"CoreOS ISO: {iso_filename}")
        return (iso_url, iso_filename, dest_dir)

    def _get_latest_coreos_version(self, base_url: str, ocp_major_version: str) -> Optional[str]:
        """
        從 mirror 頁面取得最新的 CoreOS 版本號
        
        Args:
            base_url: CoreOS ISO 基礎 URL
            ocp_major_version: OCP 主版本號（如 '4.21'），用於備用
            
        Returns:
            版本號字串（如 '4.21.0'）或 None
        """
        try:
            # 使用 curl 取得目錄列表
            result = subprocess.run(
                ['curl', '-s', '-L', '--connect-timeout', '15', '--max-time', '30', base_url],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode != 0:
                # 嘗試使用 wget
                result = subprocess.run(
                    ['wget', '-q', '-O', '-', '--timeout=30', base_url],
                    capture_output=True, text=True, timeout=30
                )
            
            if result.returncode != 0 or not result.stdout.strip():
                log_error(f"無法存取 CoreOS mirror: {base_url}")
                # 使用備用版本號
                fallback = f"{ocp_major_version}.0"
                log_info(f"使用備用 CoreOS 版本: {fallback}")
                return fallback
            
            html_content = result.stdout
            
            # 從 HTML 中提取 ISO 檔名中的版本號
            # 匹配格式: rhcos-4.21.0-x86_64-live-iso.x86_64.iso
            pattern = r'rhcos-(\d+\.\d+\.\d+)-x86_64-live-iso\.x86_64\.iso'
            match = re.search(pattern, html_content)
            
            if match:
                version = match.group(1)
                log_info(f"找到 CoreOS 版本: {version}")
                return version
            
            # 備用方案：使用 OCP 主版本號 + .0
            fallback = f"{ocp_major_version}.0"
            log_info(f"無法從 mirror 解析版本，使用備用: {fallback}")
            return fallback
            
        except subprocess.TimeoutExpired:
            log_error(f"取得 CoreOS 版本資訊超時: {base_url}")
            return f"{ocp_major_version}.0"
        except Exception as e:
            log_error(f"取得 CoreOS 版本資訊失敗: {e}")
            return f"{ocp_major_version}.0"

    def download_file(self, url: str, destination_dir: str) -> bool:
        """使用 wget 下載檔案"""
        url = url.strip().replace(" ", "")
        filename = os.path.basename(url.split('?')[0])
        
        log_info(f"正在下載：{filename}...")
        
        try:
            subprocess.run(
                ['wget', '-q', '--show-progress', url, '-P', destination_dir],
                check=True
            )
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"下載失敗：{filename}, 錯誤：{e}")
            return False
        except FileNotFoundError:
            log_error("未找到 wget 命令")
            return False

    def run_get_operator_catalog_via_grpc(
        self, 
        config: dict, 
        status_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """使用 gRPC 獲取 Operator Catalog"""
        # 步驟1: 檢查 grpcurl
        grpcurl_cmd = self._ensure_grpcurl_available(status_callback)
        if not grpcurl_cmd:
            return False
        
        # 步驟2: 確保容器運行
        container_name, port = self._ensure_container_running(config, status_callback)
        if not container_name:
            return False
        
        # 步驟3: 查詢並儲存
        return self._fetch_and_save_catalog(grpcurl_cmd, port, container_name, status_callback)

    def _ensure_grpcurl_available(self, status_callback: Optional[Callable] = None) -> Optional[str]:
        """確保 grpcurl 可用"""
        self._notify(status_callback, "🔍 初始化 Operator Catalog 獲取任務...")
        self._notify(status_callback, "🔧 尋找 grpcurl 命令...")
        
        grpcurl_cmd = self.op_mgr.find_grpcurl()
        
        if grpcurl_cmd:
            self._notify(status_callback, f"✅ 找到 grpcurl: {grpcurl_cmd}")
        else:
            self._notify(status_callback, "❌ 找不到 grpcurl 命令")
        
        return grpcurl_cmd
    
    def _ensure_container_running(
        self, 
        config: dict, 
        status_callback: Optional[Callable] = None
    ) -> tuple:
        """確保容器正在運行"""
        self._notify(status_callback, "📦 檢查容器狀態...")
        
        container_name = self._get_container_name(config)
        
        if self._check_container_running(container_name):
            self._notify(status_callback, f"✅ 容器已在運行: {container_name}")
            return container_name, RegistryManager.DEFAULT_PORT
        
        self._notify(status_callback, "📦 容器未運行，正在啟動...")
        success, name, port = self.registry.start_operator_registry(config, status_callback)
        
        if not success:
            self._notify(status_callback, "❌ 啟動 Registry 容器失敗")
            return None, None
        
        return name, port

    def _fetch_and_save_catalog(
        self,
        grpcurl_cmd: str,
        port: int,
        container_name: str,
        status_callback: Optional[Callable] = None
    ) -> bool:
        """查詢並儲存 Operator Catalog"""
        try:
            # 查詢 packages
            self._notify(status_callback, "📡 查詢所有 Packages...")
            output = self.op_mgr.list_packages_grpc(grpcurl_cmd, port)
            
            if not output:
                self._notify(status_callback, "❌ gRPC 查詢失敗")
                return False
            
            # 解析
            package_names = self.op_mgr.parse_list_output(output)
            if not package_names:
                self._notify(status_callback, f"❌ 解析失敗，原始輸出: {output[:500]}")
                return False
            
            self._notify(status_callback, f"📦 找到 {len(package_names)} 個 packages，正在獲取詳細資訊...")
            
            # 獲取詳細資訊
            packages, error_count = self._fetch_package_details(
                grpcurl_cmd, port, package_names, status_callback
            )
            
            # 儲存
            self._notify(status_callback, f"💾 儲存 operator_index.json ({len(packages)} packages, {error_count} 錯誤)...")
            self.op_mgr.save_operator_index(packages)
            
            self._notify(status_callback, f"✅ operator_index.json 已創建 ({len(packages)} packages)")
            self._notify(status_callback, "💡 容器保持運行，可手動關閉")
            
            return True
            
        except Exception as e:
            self._notify(status_callback, f"❌ 發生錯誤: {str(e)}")
            return False

    def _fetch_package_details(
        self,
        grpcurl_cmd: str,
        port: int,
        package_names: List[str],
        status_callback: Optional[Callable] = None
    ) -> tuple:
        """獲取所有 package 的詳細資訊"""
        packages = []
        error_count = 0
        max_errors_to_show = 5
        
        for i, pkg_name in enumerate(package_names):
            if status_callback and i % 20 == 0:
                status_callback(f"⏳ 處理中... ({i+1}/{len(package_names)})")
            
            try:
                pkg_info = self.op_mgr.get_package_basic_info(grpcurl_cmd, port, pkg_name)
                if pkg_info:
                    packages.append(pkg_info)
            except Exception as e:
                error_count += 1
                if error_count <= max_errors_to_show and status_callback:
                    status_callback(f"⚠️ 獲取 {pkg_name} 失敗: {str(e)}")
        
        return packages, error_count

    def run_untar_oc_mirror(self, config: dict) -> bool:
        """解壓 oc-mirror"""
        v_info = config.get('version_info', {})
        rhel_version = v_info.get('RHEL_VERSION', 'rhel9')
        tar_filename = f"oc-mirror.{rhel_version}.tar.gz"
        tar_path = os.path.join(self.install_source_dir, tar_filename)
        
        result = self._extract_tar(tar_path, os.path.expanduser("~/.local/bin"), "oc-mirror")
        return result is not None
    
    def run_untar_grpcurl(self, config: dict) -> bool:
        """解壓 grpcurl"""
        tar_filename = f"grpcurl_{self.DEFAULT_GRPCURL_VERSION}_linux_x86_64.tar.gz"
        tar_path = os.path.join(self.install_source_dir, tar_filename)
        
        result = self._extract_tar(tar_path, os.path.expanduser("~/.local/bin"), "grpcurl")
        return result is not None
    
    def _extract_tar(self, tar_path: str, target_dir: str, binary_name: str) -> Optional[str]:
        """解壓 tar 檔案並設定執行權限"""
        if not os.path.exists(tar_path):
            log_error(f"找不到 tar 包：{tar_path}")
            return None
        
        os.makedirs(target_dir, exist_ok=True)
        
        try:
            subprocess.run(
                ["tar", "-zxvf", tar_path, "-C", target_dir],
                check=True, capture_output=True, text=True
            )
            
            target_binary = os.path.join(target_dir, binary_name)
            if os.path.isfile(target_binary):
                os.chmod(target_binary, 0o755)
                log_success(f"已設置執行權限：{target_binary}")
                return target_binary
            
            return None
        except subprocess.CalledProcessError as e:
            log_error(f"解壓失敗：{e}")
            return None
        
    def _get_container_name(self, config: dict) -> str:
        """從配置取得容器名稱"""
        v_info = config.get('version_info', {})
        ocp_release = v_info.get('OCP_RELEASE', RegistryManager.DEFAULT_OCP_RELEASE)
        match = re.match(r'(\d+\.\d+)', ocp_release)
        ocp_version = match.group(1) if match else RegistryManager.DEFAULT_OCP_VERSION
        return RegistryManager.CONTAINER_NAME_TEMPLATE.format(version=ocp_version)
    
    def _check_container_running(self, container_name: str) -> bool:
        """檢查容器是否運行"""
        return self.registry.check_container_running(container_name)
    
    def _notify(self, callback: Optional[Callable], message: str) -> None:
        """發送通知"""
        if callback:
            callback(message)

    def _find_grpcurl(self) -> Optional[str]:
        return self.op_mgr.find_grpcurl()
    
    def get_package_version_grpc(self, grpcurl_cmd, port, package_name, channel_name, max_retries=3):
        return self.op_mgr.get_bundle_version(grpcurl_cmd, port, package_name, channel_name, max_retries)