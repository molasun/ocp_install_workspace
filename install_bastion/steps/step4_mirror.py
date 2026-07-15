import streamlit as st
import os
import subprocess
from i18n import t
from managers.base_manager import BaseManager
from managers.setup_manager import SetupManager
from managers.agent_create_manager import AgentCreateManager


def _check_registry_catalog(config_params: dict) -> tuple:
    """
    檢查 Registry catalog 是否已有鏡像

    Returns:
        (success: bool, message: str)
    """
    bastion_ip = config_params.get('bastion', {}).get('ip', '')
    registry_password = config_params.get('registryPassword', '')
    reponame = st.session_state.get('file_paths', {}).get('reponame', 'ocp420')

    if not bastion_ip or not registry_password:
        return False, t('step4.missing_bastion')

    try:
        result = subprocess.run(
            f"curl -sk -u init:{registry_password} https://{bastion_ip}:8443/v2/_catalog",
            shell=True, capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            if reponame in result.stdout:
                return True, t('step4.sync_complete', repo=reponame)
            else:
                return False, t('step4.sync_not_found', repo=reponame)
        else:
            return False, t('step4.registry_unreachable', error=result.stderr[:200])

    except subprocess.TimeoutExpired:
        return False, t('step4.check_timeout')
    except Exception as e:
        return False, t('step4.check_failed', error=str(e))

def _render_agent_image_section(config_params: dict):
    """渲染 Agent Image 生成區塊"""
    st.subheader(t('step4.agent.title'))
    st.markdown(t('step4.agent.desc'))

    manager = AgentCreateManager(config_params)

    prereq_ok, prereq_msg = manager.check_prerequisites()

    if not prereq_ok:
        st.warning(t('step4.agent.prereq_failed', msg=prereq_msg))
        st.info(t('step4.agent.prereq_hint'))
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

    _render_agent_image_section(config_params)

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

    st.subheader(t('step4.check_status'))
    st.markdown(t('step4.check_desc'))

    if st.button(t('step4.check_button'), use_container_width=True):
        with st.spinner(t('step4.checking')):
            success, msg = _check_registry_catalog(config_params)
            if success:
                st.success(msg)
                st.balloons()
            else:
                st.warning(msg)

    st.markdown("---")

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
