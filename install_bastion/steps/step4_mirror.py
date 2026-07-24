import streamlit as st
import os
import subprocess
import json
from datetime import datetime
from i18n import t
from managers.base_manager import BaseManager
from managers.setup_manager import SetupManager
from managers.agent_create_manager import AgentCreateManager


def _check_registry_catalog(config_params: dict) -> dict:
    """
    三層級檢查 Registry 鏡像推送狀態

    Level 1: Catalog — repo 是否存在（最快）
    Level 2: Tags — tag 數量 >= 3（有實際鏡像）
    Level 3: Release — release image manifest 是否存在（最可信）

    Returns:
        dict: verified / passed / failed / tag_count / reponame / release_tag / checked_at
    """
    bastion_ip = config_params.get('bastion', {}).get('ip', '')
    registry_password = config_params.get('registryPassword', '')
    reponame = st.session_state.get('file_paths', {}).get('reponame', 'ocp420')

    # 推導 release tag：ocp_release-arch (e.g. 4.20.8-x86_64)
    version_info = config_params.get('versionInfo', {})
    ocp_release = version_info.get('ocpRelease', '4.20.8')
    arch = version_info.get('architecture', 'amd64')
    arch_map = {'amd64': 'x86_64', 'arm64': 'aarch64'}
    release_tag = f"{ocp_release}-{arch_map.get(arch, arch)}"

    result = {
        'verified': False,
        'passed': [],
        'failed': [],
        'tag_count': 0,
        'reponame': reponame,
        'release_tag': release_tag,
        'checked_at': datetime.now().strftime('%H:%M:%S'),
    }

    if not bastion_ip or not registry_password:
        result['failed'].append('connection')
        return result

    auth = f"init:{registry_password}"
    base_url = f"https://{bastion_ip}:8443/v2"

    # Level 1: Catalog 檢查
    try:
        r = subprocess.run(
            f"curl -sk -u {auth} {base_url}/_catalog",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and reponame in r.stdout:
            result['passed'].append('catalog')
        else:
            result['failed'].append('catalog')
            return result  # Level 1 未通過，後面不查
    except Exception:
        result['failed'].append('catalog')
        return result

    # Level 2: Tags 數量檢查
    try:
        r = subprocess.run(
            f"curl -sk -u {auth} {base_url}/{reponame}/tags/list",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            tags = data.get('tags', [])
            result['tag_count'] = len(tags)
            if len(tags) >= 3:
                result['passed'].append('tags')
            else:
                result['failed'].append('tags')
        else:
            result['failed'].append('tags')
    except Exception:
        result['failed'].append('tags')

    # Level 3: Release Image 確認
    try:
        r = subprocess.run(
            f"curl -sk -o /dev/null -w '%{{http_code}}' -u {auth} -I {base_url}/{reponame}/manifests/{release_tag}",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and '200' in r.stdout:
            result['passed'].append('release')
        else:
            result['failed'].append('release')
    except Exception:
        result['failed'].append('release')

    # Level 1 + Level 2 通過即視為驗證通過
    result['verified'] = 'catalog' in result['passed'] and 'tags' in result['passed']

    return result


def _render_sync_check_section(config_params: dict):
    """渲染同步狀態檢查區塊（三層級檢查 + 結果快取）"""
    st.subheader(t('step4.check_status'))
    st.markdown(t('step4.check_desc'))

    if st.button(t('step4.check_button'), use_container_width=True):
        with st.spinner(t('step4.checking')):
            sync_result = _check_registry_catalog(config_params)
            st.session_state['mirror_sync_result'] = sync_result

    # 顯示檢查結果（從 session_state 讀取，避免頁面刷新重複 curl）
    sync_result = st.session_state.get('mirror_sync_result')
    if sync_result:
        st.caption(f"🕐 {sync_result.get('checked_at', '')}")

        levels = [
            ('catalog', t('step4.check_level_catalog')),
            ('tags', t('step4.check_level_tags', count=sync_result.get('tag_count', 0))),
            ('release', t('step4.check_level_release', tag=sync_result.get('release_tag', ''))),
        ]

        for level_key, level_label in levels:
            if level_key in sync_result['passed']:
                st.markdown(f"✅ {level_label}")
            else:
                st.markdown(f"❌ {level_label}")

        if sync_result['verified']:
            st.success(t('step4.sync_verified'))
        else:
            passed_str = ', '.join(sync_result.get('passed', []))
            failed_str = ', '.join(sync_result.get('failed', []))
            st.warning(t('step4.sync_partial', passed=passed_str, failed=failed_str))

    st.markdown("---")


def _render_agent_image_section(config_params: dict):
    """渲染 Agent Image 生成區塊（根據同步狀態條件啟用）"""
    st.subheader(t('step4.agent.title'))
    st.markdown(t('step4.agent.desc'))

    sync_result = st.session_state.get('mirror_sync_result')

    # 狀態 1：尚未檢查
    if not sync_result:
        st.info(t('step4.sync_not_checked'))
        st.button(t('step4.agent.generate'), type="primary", use_container_width=True,
                  key="btn_agent_create", disabled=True)
        st.markdown("---")
        return

    # 狀態 2：檢查未通過
    if not sync_result['verified']:
        st.warning(t('step4.agent.gated'))
        st.button(t('step4.agent.generate'), type="primary", use_container_width=True,
                  key="btn_agent_create", disabled=True)
        st.markdown("---")
        return

    # 狀態 3：同步驗證通過
    st.success(t('step4.sync_verified'))

    manager = AgentCreateManager(config_params)

    prereq_ok, prereq_msg = manager.check_prerequisites()

    if not prereq_ok:
        st.warning(t('step4.agent.prereq_failed', msg=prereq_msg))
        st.info(t('step4.agent.prereq_hint'))
        st.markdown("---")
        return

    st.success(t('step4.agent.ready'))

    work_dir = manager.work_dir
    st.caption(t('step4.agent.work_dir', dir=work_dir))

    iso_exists, iso_path = manager.check_image_exists()

    if iso_exists:
        st.info(t('step4.agent.iso_exists', path=iso_path))

    col_gen, col_skip = st.columns([1, 2])

    with col_gen:
        button_label = t('step4.agent.regenerate') if iso_exists else t('step4.agent.generate')
        if st.button(button_label, type="primary", use_container_width=True, key="btn_agent_create"):
            with st.spinner(t('step4.agent.generating')):
                success, msg = manager.create_image()
            if success:
                st.success(f"✅ {msg}")
                st.balloons()
            else:
                st.error(f"❌ {msg}")

    with col_skip:
        if st.button(t('step4.agent.skip'), use_container_width=True, key="btn_agent_skip"):
            st.session_state.agent_image_skipped = True
            st.rerun()

    st.markdown("---")


def render_step4_mirror():
    """步驟4: 鏡像同步"""
    st.header(t('step4.header'))
    st.markdown(t('step4.subtitle'))

    config_params = st.session_state.get('config_params', {})

    # === 1. Registry 狀態檢查 ===
    install_source_dir = BaseManager._get_install_source_dir()
    mirror_dir = os.path.join(install_source_dir, "mirror")

    st.subheader(t('step4.registry_status'))

    manager = SetupManager(config_params)
    installed, install_msg = manager.mirror_registry_manager.check_installed()

    if installed:
        st.success(f"✅ {install_msg}")
        with st.spinner(t('step4.verifying_registry')):
            connected, connect_msg = manager.mirror_registry_manager.verify_connection()
            if connected:
                st.success(f"✅ {connect_msg}")
            else:
                st.warning(f"⚠️ {connect_msg}")
    else:
        st.warning(f"⚠️ {install_msg}")
        st.info(t('step4.registry_not_installed'))
        col_back, _ = st.columns([1, 3])
        with col_back:
            if st.button(t('step4.back_step3'), type="primary"):
                st.session_state.current_step = 3
                st.rerun()
        return

    st.markdown("---")

    # === 2. 檔案檢查 ===
    st.subheader(t('step4.file_check'))

    bastion_ip = config_params.get('bastion', {}).get('ip', '')
    bastion_name = config_params.get('bastion', {}).get('name', 'bastion')
    cluster_name = config_params.get('clusterName', 'ocp4')
    base_domain = config_params.get('baseDomain', 'example.com')
    reponame = st.session_state.get('file_paths', {}).get('reponame', 'ocp420')
    bastion_fqdn = f"{bastion_name}.{cluster_name}.{base_domain}"

    oc_mirror_path = '/usr/bin/oc-mirror'
    oc_mirror_ok = os.path.exists(oc_mirror_path)
    if oc_mirror_ok:
        st.success(f"✅ oc-mirror: `{oc_mirror_path}`")
    else:
        st.error(t('step4.oc_mirror_not_found'))

    imageset_yaml = os.path.join(mirror_dir, 'imageset-config.yaml')
    imageset_ok = os.path.exists(imageset_yaml)
    if imageset_ok:
        st.success(f"✅ imageset-config.yaml: `{imageset_yaml}`")
        with st.expander(t('step4.preview_imageset')):
            with open(imageset_yaml, 'r') as f:
                st.code(f.read(), language="yaml")
    else:
        st.error(t('step4.imageset_not_found', path=imageset_yaml))
        st.info(t('step4.imageset_hint'))

    all_ok = oc_mirror_ok and imageset_ok and installed

    if all_ok:
        st.success(t('step4.all_ready'))

    st.markdown("---")

    # === 3. 同步指令 ===
    st.subheader(t('step4.sync_title'))
    st.markdown(t('step4.sync_desc'))

    cache_dir = os.path.join(install_source_dir, "mirror-cache")
    registry_target = f"{bastion_ip}:8443" if bastion_ip else f"{bastion_fqdn}:8443"

    cmd = (
        f"mkdir -p {cache_dir}\n"
        f"oc mirror -c {imageset_yaml} \\\n"
        f"  --from file://{mirror_dir} \\\n"
        f"  docker://{registry_target}/{reponame} \\\n"
        f"  --cache-dir {cache_dir} \\\n"
        f"  --v2"
    )

    st.code(cmd, language="bash")
    st.info(t('step4.copy_hint'))

    st.markdown(t('step4.instructions'))

    st.markdown("---")

    # === 4. 同步狀態檢查（三層級，結果存入 session_state） ===
    _render_sync_check_section(config_params)

    # === 5. Agent Image 生成（移到底部，根據同步狀態條件啟用） ===
    _render_agent_image_section(config_params)

    # === 6. 導航按鈕 ===
    col_nav1, col_nav2 = st.columns([1, 3])

    with col_nav1:
        if st.button(t('step4.back_step3'), use_container_width=True):
            st.session_state.current_step = 3
            st.rerun()

    with col_nav2:
        if st.button(t('step4.finish'), type="primary", use_container_width=True):
            st.session_state.step4_complete = True
            st.session_state.current_step = 5
            st.rerun()
