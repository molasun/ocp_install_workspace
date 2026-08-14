#!/usr/bin/env python3
import os
from typing import Dict, Tuple
from .base_manager import BaseManager


class OthersManager(BaseManager):
    """其他系統設定管理類別（Firewall, SELinux）"""
    
    def disable_firewalld(self) -> Tuple[bool, str]:
        """停用防火牆 - 對應 firewalld.yml"""
        self._log("開始停用防火牆 (firewalld)...")
        
        # 先檢查 firewalld 是否已安裝
        success, _, _ = self._run_command("rpm -q firewalld")
        if not success:
            self._log("firewalld 未安裝，跳過")
            return True, "firewalld 未安裝，無需停用"
        
        # 停止 firewalld 服務
        success1, _, err1 = self._run_command("systemctl stop firewalld")
        if not success1:
            self._log(f"停止 firewalld 失敗: {err1}", "WARNING")
        
        # 停用 firewalld 開機啟動
        success2, _, err2 = self._run_command("systemctl disable firewalld")
        if not success2:
            self._log(f"停用 firewalld 開機啟動失敗: {err2}", "WARNING")
        
        # 檢查狀態
        if not self._check_service_status("firewalld"):
            return True, "防火牆已成功停用"
        else:
            # 嘗試強制停止
            self._run_command("systemctl mask firewalld")
            if not self._check_service_status("firewalld"):
                return True, "防火牆已強制停用"
            return False, "防火牆停用失敗，服務仍在運行"
    
    def disable_selinux(self) -> Tuple[bool, str]:
        """設定 SELinux 為 Permissive 模式 - 對應 selinux.yml"""
        self._log("開始設定 SELinux...")
        
        # 檢查當前狀態
        success, stdout, _ = self._run_command("getenforce")
        current_status = stdout.strip() if success else "Unknown"
        self._log(f"當前 SELinux 狀態: {current_status}")
        
        if current_status in ['Permissive', 'Disabled']:
            return True, f"SELinux 已處於 {current_status} 模式，無需變更"
        
        # 設定 SELinux 為 permissive 模式
        success, _, err = self._run_command("setenforce 0")
        if not success:
            return False, f"SELinux 設定失敗: {err}"
        
        # 修改設定檔使其永久生效
        selinux_config = '/etc/selinux/config'
        self._backup_file(selinux_config)
        
        self._run_command(
            "sed -i 's/^SELINUX=enforcing/SELINUX=permissive/g' /etc/selinux/config"
        )
        self._run_command(
            "sed -i 's/^SELINUX=disabled/SELINUX=permissive/g' /etc/selinux/config"
        )
        
        # 驗證
        _, stdout, _ = self._run_command("getenforce")
        if "permissive" in stdout.lower() or "disabled" in stdout.lower():
            return True, f"SELinux 已設定為 {stdout.strip()} 模式"
        
        return False, f"SELinux 設定失敗，當前狀態: {stdout.strip()}"
    
    def install_nmstate(self) -> Tuple[bool, str]:
        """安裝 nmstate 網路管理工具"""
        self._log("開始安裝 nmstate...")

        # 檢查是否已安裝
        success, _, _ = self._run_command("rpm -q nmstate")
        if success:
            self._log("nmstate 已安裝，跳過")
            return True, "nmstate 已安裝"

        success, _, err = self._run_command("yum install -y nmstate")
        if not success:
            return False, f"nmstate 安裝失敗: {err}"

        return True, "nmstate 已成功安裝"
    
    def setup_root_ssh_keys(self) -> Tuple[bool, str]:
        """將 install_source/.ssh 的 id_rsa / id_rsa.pub 部署到 /root/.ssh

        每次都覆寫，因為 /root/.ssh 內既有的密鑰可能與 install_source 內不同。
        """
        self._log("部署 SSH 金鑰到 /root/.ssh...")

        ssh_src_dir = os.path.join(self._get_install_source_dir(), '.ssh')
        id_rsa_src = os.path.join(ssh_src_dir, 'id_rsa')
        id_rsa_pub_src = os.path.join(ssh_src_dir, 'id_rsa.pub')

        # 前置檢查：源檔案必須存在
        missing = []
        if not os.path.exists(id_rsa_src):
            missing.append('id_rsa')
        if not os.path.exists(id_rsa_pub_src):
            missing.append('id_rsa.pub')
        if missing:
            msg = (
                f"找不到 SSH 金鑰來源檔案 ({', '.join(missing)})，"
                f"請先於 install_tool 生成: {ssh_src_dir}"
            )
            self._log(msg, "ERROR")
            return False, msg

        # 建立 /root/.ssh 並設權限
        self._run_command("sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh")

        # 每次覆寫（既有密鑰可能與 install_source 內不同）
        self._run_command(f"sudo cp -f {id_rsa_src} /root/.ssh/id_rsa")
        self._run_command(f"sudo cp -f {id_rsa_pub_src} /root/.ssh/id_rsa.pub")

        # 設定正確權限（避免 SSH 因權限過寬拒絕使用）
        self._run_command("sudo chmod 600 /root/.ssh/id_rsa")
        self._run_command("sudo chmod 644 /root/.ssh/id_rsa.pub")

        # 驗證
        success, stdout, _ = self._run_command(
            "sudo test -f /root/.ssh/id_rsa && "
            "sudo test -f /root/.ssh/id_rsa.pub && echo ok"
        )
        if success and "ok" in stdout:
            self._log("SSH 金鑰已部署至 /root/.ssh (id_rsa / id_rsa.pub)")
            return True, "SSH 金鑰已部署至 /root/.ssh (id_rsa / id_rsa.pub)"
        return False, "SSH 金鑰部署後驗證失敗"

    def check_system_requirements(self) -> Tuple[bool, str]:
        """檢查系統基本需求"""
        self._log("檢查系統基本需求...")
        
        checks = []
        all_passed = True
        
        # 檢查 RHEL 版本
        success, stdout, _ = self._run_command("cat /etc/redhat-release")
        if success:
            checks.append(f"✅ 作業系統: {stdout.strip()}")
        else:
            checks.append("❌ 無法判斷作業系統版本")
            all_passed = False
        
        # 檢查記憶體
        success, stdout, _ = self._run_command("free -g | awk '/^Mem:/{print $2}'")
        if success and stdout.strip().isdigit():
            mem_gb = int(stdout.strip())
            if mem_gb >= 16:
                checks.append(f"✅ 記憶體: {mem_gb}GB (>= 16GB)")
            else:
                checks.append(f"⚠️ 記憶體: {mem_gb}GB (建議 >= 16GB)")
        else:
            checks.append("⚠️ 無法檢查記憶體大小")
        
        # 檢查 CPU 核心數
        success, stdout, _ = self._run_command("nproc")
        if success and stdout.strip().isdigit():
            cpu_cores = int(stdout.strip())
            if cpu_cores >= 4:
                checks.append(f"✅ CPU 核心: {cpu_cores} (>= 4)")
            else:
                checks.append(f"⚠️ CPU 核心: {cpu_cores} (建議 >= 4)")
        else:
            checks.append("⚠️ 無法檢查 CPU 核心數")
        
        # 檢查磁碟空間
        success, stdout, _ = self._run_command("df -h / | awk 'NR==2{print $4}'")
        if success:
            checks.append(f"✅ 根目錄可用空間: {stdout.strip()}")
        else:
            checks.append("⚠️ 無法檢查磁碟空間")
        
        return all_passed, "\n".join(checks)