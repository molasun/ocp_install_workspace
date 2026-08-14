import os
import shutil
from typing import Tuple

import yaml

from .base_manager import BaseManager


class AgentCreateManager(BaseManager):
    """Agent Image 生成管理類別"""

    OPENSHIFT_INSTALL_BIN = '/usr/bin/openshift-install'

    def __init__(self, config: dict, config_dir: str = "/tmp/ocp-install-config"):
        super().__init__(config, config_dir)
        self._install_source_dir = self._get_install_source_dir()
        self._ocp_yaml_dir = os.path.join(self._install_source_dir, 'ocp')

    @property
    def work_dir(self) -> str:
        """agent create image 的工作目錄（~/{clusterName}）"""
        cluster_name = self.config.get('clusterName', 'ocp4')
        return os.path.join(os.path.expanduser('~'), cluster_name)

    @property
    def install_mode(self) -> str:
        """安裝模式：standard / sno / compact"""
        return self.config.get('mode', 'standard')

    def _is_standard(self) -> bool:
        """是否為 standard 模式（需 mastersSchedulable=false）"""
        return self.install_mode == 'standard'

    # === 前置檢查 ===

    def check_prerequisites(self) -> Tuple[bool, str]:
        """
        檢查生成 Agent Image 的必要條件

        Returns:
            (是否通過, 訊息)
        """
        issues = []

        # 1. openshift-install 二進位檔
        if not os.path.exists(self.OPENSHIFT_INSTALL_BIN):
            issues.append(f"openshift-install 未安裝: {self.OPENSHIFT_INSTALL_BIN}")

        # 2. install-config.yaml
        install_config = os.path.join(self._ocp_yaml_dir, 'install-config.yaml')
        if not os.path.exists(install_config):
            issues.append(f"install-config.yaml 不存在: {install_config}")

        # 3. agent-config.yaml
        agent_config = os.path.join(self._ocp_yaml_dir, 'agent-config.yaml')
        if not os.path.exists(agent_config):
            issues.append(f"agent-config.yaml 不存在: {agent_config}")

        if issues:
            return False, "\n".join(issues)

        return True, "所有必要檔案已就緒"

    # === 目錄準備 ===

    def prepare_work_dir(self) -> Tuple[bool, str]:
        """
        建立工作目錄並複製 YAML 檔案

        Returns:
            (是否成功, 訊息)
        """
        work_dir = self.work_dir

        # 建立工作目錄
        os.makedirs(work_dir, exist_ok=True)

        # 複製 YAML 檔案
        for filename in ['install-config.yaml', 'agent-config.yaml']:
            src = os.path.join(self._ocp_yaml_dir, filename)
            dst = os.path.join(work_dir, filename)

            if not os.path.exists(src):
                return False, f"來源檔案不存在: {src}"

            try:
                shutil.copy2(src, dst)
                self._log(f"已複製 {src} -> {dst}")
            except Exception as e:
                return False, f"複製 {filename} 失敗: {e}"

        self._log(f"工作目錄準備完成: {work_dir}")
        return True, f"工作目錄已就緒: {work_dir}"

    # === 清空工作目錄 ===

    def _clean_work_dir(self) -> Tuple[bool, str]:
        """清空 work_dir 內所有檔案內容，確保每次創建都是乾淨目錄"""
        work_dir = self.work_dir
        home = os.path.expanduser('~')

        # 安全保護：拒絕清空根目錄、家目錄本身或非家目錄下的路徑
        if not work_dir or work_dir in ('/', home) or os.path.dirname(work_dir) != home:
            return False, f"拒絕清空不安全路徑: {work_dir}"

        if os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
                self._log(f"已清空工作目錄: {work_dir}")
            except Exception as e:
                return False, f"清空工作目錄失敗: {e}"

        os.makedirs(work_dir, exist_ok=True)
        return True, f"工作目錄已清空: {work_dir}"

    # === standard 模式：cluster-manifests ===

    def _prepare_standard_manifests(self) -> Tuple[bool, str]:
        """建立 cluster-manifests 並將 mastersSchedulable 設為 false

        僅 standard 模式需要：worker 獨立成節點時，master 不應調度 workload。
        sno / compact 由 master 兼任 workload，跳過此步驟。
        """
        work_dir = self.work_dir
        manifests_dir = os.path.join(work_dir, 'manifests')

        # 1. 建立 cluster-manifests
        cmd = (
            f"{self.OPENSHIFT_INSTALL_BIN} agent create cluster-manifests "
            f"--dir {work_dir} --log-level=info"
        )
        self._log(f"執行: {cmd}")
        success, stdout, stderr = self._run_command(cmd, timeout=600)
        if not success:
            detail = (stderr or stdout).strip()[:500]
            return False, f"create cluster-manifests 失敗:\n{detail}"

        # 2. 修改 scheduler 設定
        scheduler_file = os.path.join(manifests_dir, 'cluster-scheduler-02-config.yml')
        if not os.path.exists(scheduler_file):
            return False, f"找不到 scheduler 設定檔: {scheduler_file}"

        try:
            with open(scheduler_file, 'r') as f:
                data = yaml.safe_load(f) or {}
            data.setdefault('spec', {})['mastersSchedulable'] = False
            with open(scheduler_file, 'w') as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            return False, f"修改 scheduler 設定失敗: {e}"

        self._log("已設定 mastersSchedulable: false")
        return True, "cluster-manifests 已建立並設定 mastersSchedulable=false"

    # === 生成 Agent Image ===

    def create_image(self) -> Tuple[bool, str]:
        """
        執行 openshift-install agent create image

        Returns:
            (是否成功, 訊息)
        """
        work_dir = self.work_dir

        # 前置檢查
        ok, msg = self.check_prerequisites()
        if not ok:
            return False, f"前置檢查失敗:\n{msg}"

        # 每次創建都從乾淨目錄開始
        ok, msg = self._clean_work_dir()
        if not ok:
            return False, msg

        # 準備工作目錄
        ok, msg = self.prepare_work_dir()
        if not ok:
            return False, msg

        # standard 模式：先建立 cluster-manifests 並設定 mastersSchedulable=false
        if self._is_standard():
            ok, msg = self._prepare_standard_manifests()
            if not ok:
                return False, msg

        # 執行指令
        cmd = f"{self.OPENSHIFT_INSTALL_BIN} agent create image --dir {work_dir} --log-level=info"
        self._log(f"執行: {cmd}")

        success, stdout, stderr = self._run_command(cmd, timeout=600)

        if not success:
            error_detail = stderr.strip()[:500] if stderr else stdout.strip()[:500]
            return False, f"agent create image 失敗:\n{error_detail}"

        # 檢查產出
        iso_path = self._find_generated_iso(work_dir)
        if iso_path:
            self._log(f"Agent ISO 已生成: {iso_path}")
            return True, f"Agent Image 生成成功:\n{iso_path}"

        return True, f"指令執行完成，但未找到 ISO 檔案，請檢查目錄: {work_dir}"

    # === 狀態檢查 ===

    def check_image_exists(self) -> Tuple[bool, str]:
        """
        檢查 Agent ISO 是否已存在

        Returns:
            (是否存在, ISO 路徑或訊息)
        """
        iso_path = self._find_generated_iso(self.work_dir)
        if iso_path:
            return True, iso_path
        return False, f"未找到 Agent ISO，工作目錄: {self.work_dir}"

    def _find_generated_iso(self, work_dir: str) -> str:
        """在工作目錄中尋找生成的 ISO 檔案"""
        if not os.path.exists(work_dir):
            return None

        for filename in os.listdir(work_dir):
            if filename.endswith('.iso'):
                return os.path.join(work_dir, filename)

        return None
