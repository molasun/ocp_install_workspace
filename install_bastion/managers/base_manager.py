import subprocess
import os
import json
from typing import Dict, Tuple, Any
from datetime import datetime


class BaseManager:
    """基礎管理類別，提供共用功能"""

    _ROOT_REQUIRED_PREFIXES = [
        'yum', 'dnf', 'rpm',
        'systemctl', 'service',
        'setenforce', 'semanage',
        'firewall-cmd', 'iptables',
        'nmcli',
    ]
    
    def __init__(self, config: dict, config_dir: str = "/tmp/ocp-install-config"):
        self.config = config
        self.config_dir = config_dir
        self.logs = []
        os.makedirs(self.config_dir, exist_ok=True)
        self._init_logger()

    @staticmethod
    def _get_real_home() -> str:
        """
        取得實際使用者的家目錄
        
        即使以 sudo/root 執行，也返回原始使用者的家目錄
        """
        # 方法1: 透過 SUDO_USER 環境變數
        sudo_user = os.environ.get('SUDO_USER', '')
        if sudo_user:
            return os.path.join('/home', sudo_user)
        
        # 方法2: 如果目前使用者不是 root，直接使用 ~
        if os.geteuid() != 0:
            return os.path.expanduser("~")
        
        # 方法3: root 但沒有 SUDO_USER（少見情況），使用 /root
        return os.path.expanduser("~")

    @staticmethod
    def _get_install_source_dir() -> str:
        """取得 install_source 目錄路徑"""
        return os.path.join(BaseManager._get_real_home(), "install_source")

    def _init_logger(self):
        """初始化日誌"""
        self.log_file = os.path.join(
            self.config_dir,
            f"install_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
    
    def _log(self, message: str, level: str = "INFO"):
        """記錄日誌"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.logs.append(log_entry)
        
        # 寫入日誌檔案
        try:
            with open(self.log_file, 'a') as f:
                f.write(log_entry + '\n')
        except Exception:
            pass
        
        print(log_entry)
    
    def _run_command(
        self, 
        command: str, 
        shell: bool = True, 
        timeout: int = 300
    ) -> Tuple[bool, str, str]:
        """執行系統命令"""
        try:
            self._log(f"執行命令: {command}")
            
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                if result.stdout.strip():
                    self._log(f"命令成功: {result.stdout.strip()[:200]}")
                return True, result.stdout.strip(), result.stderr.strip()
            else:
                self._log(f"命令失敗 (rc={result.returncode}): {result.stderr.strip()[:200]}", "ERROR")
                return False, result.stdout.strip(), result.stderr.strip()
                
        except subprocess.TimeoutExpired:
            self._log(f"命令超時: {command}", "ERROR")
            return False, "", "Command timeout"
        except Exception as e:
            self._log(f"命令執行異常: {str(e)}", "ERROR")
            return False, "", str(e)
    
    def _check_service_status(self, service_name: str) -> bool:
        """檢查服務是否運行中"""
        success, stdout, _ = self._run_command(f"systemctl is-active {service_name}")
        return success and "active" in stdout
    
    def _backup_file(self, file_path: str) -> bool:
        """備份檔案"""
        if os.path.exists(file_path):
            backup_path = f"{file_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try:
                import shutil
                shutil.copy(file_path, backup_path)
                self._log(f"已備份 {file_path} -> {backup_path}")
                return True
            except Exception as e:
                self._log(f"備份失敗: {str(e)}", "WARNING")
                return False
        return False
    
    def _write_file(self, file_path: str, content: str) -> bool:
        """寫入檔案"""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as f:
                f.write(content)
            self._log(f"已寫入檔案: {file_path}")
            return True
        except Exception as e:
            self._log(f"寫入檔案失敗 {file_path}: {str(e)}", "ERROR")
            return False
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """安全取得配置值"""
        return self.config.get(key, default)