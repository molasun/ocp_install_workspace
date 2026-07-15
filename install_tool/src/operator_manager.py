import json
import subprocess
import shutil
import os
import re
import time

from src.logger import log_info, log_error

class OperatorManager:
    """統一的 Operator 管理類別，整合查詢和版本管理"""
    
    # 所有支援的 index 類型
    ALL_INDEX_TYPES = ['redhat', 'certified', 'community', 'marketplace']
    
    def __init__(self, current_dir=None):
        self.current_dir = current_dir or os.getcwd()
        self.config_dir = os.path.join(self.current_dir, 'config')
        os.makedirs(self.config_dir, exist_ok=True)
        
        # 快取檔案路徑
        self.index_file = os.path.join(self.config_dir, "operator_index.json")
        self.catalog_file = os.path.join(self.config_dir, "operator_catalog.json")
    
    def find_grpcurl(self):
        """尋找 grpcurl 命令"""
        local_bin = os.path.join(os.path.expanduser("~"), ".local/bin/grpcurl")
        if os.path.exists(local_bin):
            return local_bin
        if shutil.which('grpcurl'):
            return shutil.which('grpcurl')
        return None
    
    def list_packages_grpc(self, grpcurl_cmd, port):
        """透過 gRPC 列出所有 packages"""
        result = subprocess.run(
            [grpcurl_cmd, '-plaintext', f'localhost:{port}',
             'api.Registry/ListPackages'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return None
    
    def get_package_grpc(self, grpcurl_cmd, port, package_name):
        """透過 gRPC 獲取 package 資訊"""
        result = subprocess.run(
            [grpcurl_cmd, '-plaintext', '-d', json.dumps({"name": package_name}),
             f'localhost:{port}', 'api.Registry/GetPackage'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return None
    
    def get_bundle_version(self, grpcurl_cmd, port, package_name, channel_name, max_retries=3):
        """獲取 channel 的最新版本，支援重試"""
        for attempt in range(max_retries):
            try:
                request_data = json.dumps({"pkgName": package_name, "channelName": channel_name})
                result = subprocess.run(
                    [grpcurl_cmd, '-plaintext', '-d', request_data,
                     f'localhost:{port}', 'api.Registry/GetBundleForChannel'],
                    capture_output=True, text=True, timeout=30
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    bundle_data = json.loads(result.stdout)
                    csv_json = json.loads(bundle_data.get('csvJson', '{}'))
                    version = csv_json.get('spec', {}).get('version', '')
                    if version:
                        return version
                
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2)
        return None
    
    def get_package_basic_info(self, grpcurl_cmd, port, package_name):
        """獲取 package 的 default_channel 和 stable_channel"""
        pkg_data = self.get_package_grpc(grpcurl_cmd, port, package_name)
        if not pkg_data:
            return None
        
        default_channel = pkg_data.get('defaultChannelName', '')
        channels = pkg_data.get('channels', [])
        
        # 找 stable channel
        stable_channel = ""
        for ch in channels:
            ch_name = ch.get('name', '')
            if 'stable' in ch_name.lower():
                stable_channel = ch_name
                break
        if not stable_channel and any(ch.get('name') == 'stable' for ch in channels):
            stable_channel = 'stable'
        
        return {
            "package_name": package_name,
            "default_channel": default_channel,
            "stable_channel": stable_channel
        }
    
    @staticmethod
    def parse_list_output(output):
        """解析 ListPackages 輸出"""
        # 正則提取 { "name": "..." }
        pattern = r'\{\s*"name"\s*:\s*"([^"]+)"\s*\}'
        matches = re.findall(pattern, output)
        if matches:
            return matches
        
        # 備用：逐行解析
        packages = []
        for line in output.strip().split('\n'):
            try:
                item = json.loads(line.strip())
                if isinstance(item, dict) and 'name' in item:
                    packages.append(item['name'])
            except json.JSONDecodeError:
                continue
        return packages
    
    def load_operator_index(self):
        """載入 operator_index.json（dict 結構，按 index_type 分區）"""
        if os.path.exists(self.index_file):
            with open(self.index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def save_operator_index(self, packages, index_type):
        """
        儲存 operator_index.json（按 index_type 分區合併）
        
        Args:
            packages: 該 index_type 下的 package 列表
            index_type: index 類型 (redhat/certified/community/marketplace)
        """
        # 讀取現有資料
        existing = self.load_operator_index()
        if existing is None:
            existing = {}
        
        # 更新指定 index_type 的資料
        existing[index_type] = packages
        
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    
    def get_packages_by_index(self, index_type):
        """取得指定 index_type 的 package 列表"""
        index_data = self.load_operator_index()
        if not index_data:
            return []
        return index_data.get(index_type, [])
    
    def get_all_packages(self):
        """取得所有 index 的所有 package（附帶 index_type 標記）"""
        index_data = self.load_operator_index()
        if not index_data:
            return []
        
        all_packages = []
        for index_type, packages in index_data.items():
            for pkg in packages:
                pkg_with_type = dict(pkg)
                pkg_with_type['index_type'] = index_type
                all_packages.append(pkg_with_type)
        return all_packages
    
    def get_catalogs(self):
        """獲取 catalog 列表"""
        version = self._get_ocp_version()
        from src.registry_manager import RegistryManager
        catalogs = []
        for idx_type in self.ALL_INDEX_TYPES:
            info = RegistryManager.INDEX_TYPES.get(idx_type)
            if info:
                catalogs.append(info['image_template'].format(version=version))
        return catalogs
    
    def get_packages(self, catalog):
        """獲取 package 名稱列表（從 operator_index.json）"""
        return [p['package_name'] for p in self.get_all_packages()]
    
    def get_package_channels(self, catalog, package):
        """獲取 package 的 channel 資訊"""
        pkg = self.get_package_info(package)
        if pkg:
            default_ch = pkg.get('default_channel', 'stable')
            return {
                'default_channel': default_ch,
                'channels': [{'name': default_ch}]
            }
        return {'default_channel': 'stable', 'channels': []}
    
    def get_package_info(self, package_name):
        """獲取單個 package 的完整資訊（含 index_type）"""
        return self.get_all_packages_with_index(package_name)
    
    def get_all_packages_with_index(self, package_name=None):
        """
        獲取 package 資訊（含 index_type）
        
        Args:
            package_name: 若指定則只回傳該 package，否則回傳全部
            
        Returns:
            單個 package dict（含 index_type）或全部列表
        """
        all_packages = self.get_all_packages()
        if package_name:
            for pkg in all_packages:
                if pkg['package_name'] == package_name:
                    return pkg
            return None
        return all_packages
    
    def get_ocp_version(self):
        """獲取 OCP 版本"""
        return self._get_ocp_version()
    
    def _get_ocp_version(self):
        """從 tool_config.json 獲取 OCP 版本"""
        config_path = os.path.join(self.config_dir, 'tool_config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    ocp_release = config.get('version_info', {}).get('OCP_RELEASE', '4.20')
                    match = re.match(r'(\d+\.\d+)', ocp_release)
                    return match.group(1) if match else '4.20'
            except Exception:
                pass
        return '4.20'
