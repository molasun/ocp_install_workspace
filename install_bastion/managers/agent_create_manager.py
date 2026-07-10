import os
import shutil
from typing import Tuple
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

        # 準備工作目錄
        ok, msg = self.prepare_work_dir()
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
