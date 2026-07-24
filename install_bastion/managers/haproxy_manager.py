import os
import shutil
from typing import Dict, Tuple
from .base_manager import BaseManager


class HAProxyManager(BaseManager):
    """HAProxy 管理類別"""
    
    def generate_config(self) -> str:
        """
        根據配置生成 HAProxy 設定檔內容
        """
        config = self.config
        bastion = config.get('bastion', {})
        bootstrap = config.get('bootstrap', {})
        master_nodes = config.get('master', [])
        worker_nodes = config.get('worker', [])
        infra_nodes = config.get('infra', [])
        mode = config.get('mode', 'compact')
        
        bootstrap_name = bootstrap.get('name', 'bootstrap')
        bootstrap_ip = bootstrap.get('ip', '')
        
        haproxy_config = """global
  log         127.0.0.1 local2
  pidfile     /var/run/haproxy.pid
  maxconn     4000
  daemon

defaults
  mode                    http
  log                     global
  option                  dontlognull
  option http-server-close
  option                  redispatch
  retries                 3
  timeout http-request    10s
  timeout queue           1m
  timeout connect         10s
  timeout client          1m
  timeout server          1m
  timeout http-keep-alive 10s
  timeout check           10s
  maxconn                 3000

listen api-server-6443 
  bind *:6443
  mode tcp
  option  httpchk GET /readyz HTTP/1.0
  option  log-health-checks
  balance roundrobin
"""
        
        # Bootstrap 伺服器（備份）
        if bootstrap_name and bootstrap_ip:
            haproxy_config += f"  server {bootstrap_name} {bootstrap_ip}:6443 verify none check check-ssl inter 10s fall 2 rise 3 backup\n"
        
        # Master 伺服器
        for node in master_nodes:
            node_name = node.get('name', '')
            node_ip = node.get('ip', '')
            if node_name and node_ip:
                haproxy_config += f"  server {node_name} {node_ip}:6443 weight 1 verify none check check-ssl inter 10s fall 2 rise 3\n"
        
        # Machine Config Server
        haproxy_config += """
listen machine-config-server-22623 
  bind *:22623
  mode tcp
"""
        if bootstrap_name and bootstrap_ip:
            haproxy_config += f"  server {bootstrap_name} {bootstrap_ip}:22623 check inter 1s backup\n"
        
        for node in master_nodes:
            node_name = node.get('name', '')
            node_ip = node.get('ip', '')
            if node_name and node_ip:
                haproxy_config += f"  server {node_name} {node_ip}:22623 check inter 1s\n"
        
        # Ingress Router - 決定使用哪些節點
        if mode == 'compact':
            ingress_nodes = master_nodes
        elif infra_nodes:
            ingress_nodes = infra_nodes
        else:
            ingress_nodes = worker_nodes
        
        if ingress_nodes:
            haproxy_config += """
listen ingress-router-443
  bind *:443
  mode tcp
  balance source
"""
            for node in ingress_nodes:
                node_name = node.get('name', '')
                node_ip = node.get('ip', '')
                if node_name and node_ip:
                    haproxy_config += f"  server {node_name} {node_ip}:443 check inter 1s\n"
            
            haproxy_config += """
listen ingress-router-80
  bind *:80
  mode tcp
  balance source
"""
            for node in ingress_nodes:
                node_name = node.get('name', '')
                node_ip = node.get('ip', '')
                if node_name and node_ip:
                    haproxy_config += f"  server {node_name} {node_ip}:80 check inter 1s\n"
        
        return haproxy_config
    
    def install(self) -> Tuple[bool, str]:
        """安裝並設定 HAProxy"""
        self._log("開始設定 HAProxy...")

        # 檢查 haproxy 服務是否已在運行，已運行則跳過安裝
        if self._check_service_status("haproxy"):
            self._log("haproxy 服務已運行，跳過安裝")
        else:
            success, _, err = self._run_command("yum install -y haproxy")
            if not success:
                return False, f"HAProxy 安裝失敗: {err}"
        
        # 備份原始配置
        haproxy_cfg = '/etc/haproxy/haproxy.cfg'
        self._backup_file(haproxy_cfg)
        
        # 生成並寫入 HAProxy 配置
        haproxy_config = self.generate_config()
        if not self._write_file(haproxy_cfg, haproxy_config):
            return False, "寫入 HAProxy 配置檔失敗"
        
        # 驗證配置
        success, stdout, stderr = self._run_command("haproxy -c -f /etc/haproxy/haproxy.cfg")
        if not success:
            return False, f"HAProxy 配置驗證失敗: {stderr}"
        
        # 啟動 haproxy
        success, _, err = self._run_command("systemctl restart haproxy")
        if not success:
            return False, f"HAProxy 啟動失敗: {err}"
        
        self._run_command("systemctl enable haproxy")
        
        if self._check_service_status("haproxy"):
            return True, "HAProxy 已成功配置並啟動"
        else:
            return False, "HAProxy 啟動失敗，請檢查日誌"