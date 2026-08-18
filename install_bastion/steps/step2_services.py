#!/usr/bin/env python3
import streamlit as st
import time
from i18n import t
from managers.setup_manager import SetupManager


def render_step2_services():
    """步驟2: 基礎服務安裝"""
    st.header(t('step2.header'))
    st.markdown(t('step2.subtitle'))
    
    config = st.session_state.get('config_params', {})
    manager = SetupManager(config)
    
    # === DNS 配置預覽 ===
    st.subheader(t('step2.dns_title'))
    with st.expander(t('step2.dns_preview'), expanded=False):
        dns_config = manager.dns_manager.generate_config()
        st.code(dns_config, language="text")
        st.caption(t('step2.config_path', path='/etc/dnsmasq.d/dns.conf'))
    
    # === HAProxy 配置預覽 ===
    st.subheader(t('step2.haproxy_title'))
    with st.expander(t('step2.haproxy_preview'), expanded=False):
        haproxy_config = manager.haproxy_manager.generate_config()
        st.code(haproxy_config, language="text")
        st.caption(t('step2.config_path', path='/etc/haproxy/haproxy.cfg'))
    
    # === NTP 配置預覽 ===
    st.subheader(t('step2.ntp_title'))
    with st.expander(t('step2.ntp_preview'), expanded=False):
        ntp_config = manager.ntp_manager.generate_config()
        st.code(ntp_config, language="text")
        st.caption(t('step2.config_path', path='/etc/chrony.conf'))
    
    st.markdown("---")
    
    # === 安裝選項確認 ===
    st.subheader(t('step2.tasks_title'))
    
    install_options = st.session_state.get('install_options', {})
    
   # 使用字典定義任務與對應的 manager 方法
    tasks_config = {
        'firewalld_disable': {
            'icon': '🚫',
            'name': t('step2.task_firewalld'),
            'method': 'disable_firewalld',
            'manager': 'others_manager'
        },
        'selinux_disable': {
            'icon': '🛡️',
            'name': t('step2.task_selinux'),
            'method': 'disable_selinux',
            'manager': 'others_manager'
        },
        'dns_configure': {
            'icon': '📡',
            'name': t('step2.task_dns'),
            'method': 'setup_dns',
            'manager': 'dns_manager'
        },
        'dns_check': {
            'icon': '🔍',
            'name': t('step2.task_dns_check'),
            'method': 'check_dns',
            'manager': 'dns_manager'
        },
        'haproxy_configure': {
            'icon': '⚖️',
            'name': t('step2.task_haproxy'),
            'method': 'setup_haproxy',
            'manager': 'haproxy_manager'
        },
        'ntp_server_configure': {
            'icon': '🕐',
            'name': t('step2.task_ntp'),
            'method': 'setup_ntp',
            'manager': 'ntp_manager'
        },
        'nmstate_install': {
            'icon': '🌐',
            'name': t('step2.task_nmstate'),
            'method': 'install_nmstate',
            'manager': 'others_manager',
            'always_run': True
        },
        'setup_root_ssh_keys': {
            'icon': '🔑',
            'name': t('step2.task_ssh_keys'),
            'method': 'setup_root_ssh_keys',
            'manager': 'others_manager',
            'always_run': True
        }
    }

    # 收集需要執行的任務
    active_tasks = []
    for key, task_info in tasks_config.items():
        if task_info.get('always_run', False):
            active_tasks.append(task_info)
        elif install_options.get(key, False):
            active_tasks.append(task_info)
    
    if not active_tasks:
        st.warning(t('step2.no_tasks'))
        col_back, _ = st.columns([1, 3])
        with col_back:
            if st.button(t('step2.back_step1'), type="primary"):
                st.session_state.current_step = 1
                st.rerun()
        return    

    # 顯示任務列表
    for task in active_tasks:
        st.markdown(f"{task['icon']} {task['name']}")
    
    st.markdown("---")

    # === 步驟執行狀態追蹤 ===
    if 'step2_executed' not in st.session_state:
        st.session_state.step2_executed = False
        st.session_state.step2_results = {}
    
    # === 執行安裝 ===
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    
    with col_btn1:
        if not st.session_state.step2_executed:
            if st.button(t('step2.start_install'), type="primary"):
                _execute_step2_tasks(manager, active_tasks)
                st.rerun()
    
    # === 顯示執行結果 ===
    if st.session_state.step2_executed:
        st.markdown("---")
        st.subheader(t('step2.results'))
        
        results = st.session_state.step2_results
        success_count = sum(1 for r in results.values() if r.get('success', False))
        total_count = len(results)
        
        # 顯示進度摘要
        col_prog1, col_prog2 = st.columns([1, 3])
        with col_prog1:
            st.metric(t('step2.progress'), f"{success_count}/{total_count}")
        
        all_success = success_count == total_count
        
        # 顯示每個步驟的詳細結果（失敗任務附帶可用的重試按鈕）
        for method, result in results.items():
            # 找到對應的任務名稱
            task_name = method
            for task in active_tasks:
                if task['method'] == method:
                    task_name = f"{task['icon']} {task['name']}"
                    break
            
            if result.get('success', False):
                st.success(f"{task_name}: {result.get('message', '')}")
            else:
                st.error(f"{task_name}: {result.get('message', '')}")
                # 活的重試按鈕：在穩定渲染區提供單任務重試
                if st.button(t('step2.retry_step'), key=f"retry_{method}"):
                    with st.spinner(t('step2.executing', task=task_name)):
                        retry_success, retry_message = manager.execute_step(method)
                    st.session_state.step2_results[method] = {
                        'success': retry_success,
                        'message': retry_message
                    }
                    st.rerun()
        
        if all_success:
            st.success(t('step2.all_success'))
            
            # 顯示服務狀態摘要
            _display_service_status(manager, install_options)
        else:
            st.warning(t('step2.some_failed'))
            st.info(t('step2.retry_hint'))
    
    # === 導航按鈕 ===
    st.markdown("---")
    col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 2])
    
    with col_nav1:
        if st.button(t('step2.back_step1'), use_container_width=True):
            st.session_state.current_step = 1
            st.rerun()
    
    with col_nav2:
        if st.session_state.step2_executed:
            results = st.session_state.step2_results
            all_success = all(r.get('success', False) for r in results.values())
            
            if all_success:
                if st.button(t('step2.next_step3'), type="primary", use_container_width=True):
                    st.session_state.step2_complete = True
                    st.session_state.current_step = 3
                    st.rerun()

    # === 重試按鈕（如果已執行但有失敗） ===
    if st.session_state.step2_executed:
        results = st.session_state.step2_results
        has_failures = any(not r.get('success', False) for r in results.values())
        
        if has_failures:
            with col_nav3:
                if st.button(t('step2.retry_all'), use_container_width=True):
                    st.session_state.step2_executed = False
                    st.session_state.step2_results = {}
                    st.rerun()

def _execute_step2_tasks(manager: SetupManager, active_tasks: list):
    """執行步驟2的所有任務（同步執行，結果存入 session_state，由結果區統一呈現）"""
    st.session_state.step2_executed = True
    st.session_state.step2_results = {}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(active_tasks)
    
    for i, task in enumerate(active_tasks):
        task_name = f"{task['icon']} {task['name']}"
        method = task['method']
        
        status_text.text(t('step2.executing', task=task_name))
        success, message = manager.execute_step(method)
        
        st.session_state.step2_results[method] = {
            'success': success,
            'message': message
        }
        
        progress_bar.progress((i + 1) / total)
        time.sleep(0.3)
    
    status_text.text(t('step2.complete'))

def _display_service_status(manager: SetupManager, install_options: dict):
    """顯示服務狀態摘要"""
    st.markdown("---")
    st.subheader(t('step2.service_status'))
    
    # 檢查各服務狀態
    services_to_check = []
    
    if install_options.get('dns_configure', False):
        services_to_check.append(("DNS (dnsmasq)", "dnsmasq"))
    if install_options.get('haproxy_configure', False):
        services_to_check.append(("HAProxy", "haproxy"))
    if install_options.get('ntp_server_configure', False):
        services_to_check.append(("NTP (chronyd)", "chronyd"))
    if install_options.get('firewalld_disable', False):
        services_to_check.append(("Firewalld", "firewalld"))
    
    if services_to_check:
        num_cols = min(len(services_to_check), 2)
        cols = st.columns(num_cols)
        
        for i, (name, service) in enumerate(services_to_check):
            with cols[i % num_cols]:
                # 對於 firewalld，期望是 stopped
                if service == "firewalld":
                    is_active = manager.dns_manager._check_service_status(service)
                    if is_active:
                        st.metric(name, "Running", delta=t('step2.should_be_stopped'))
                    else:
                        st.metric(name, "Stopped", delta="✅")
                else:
                    is_active = manager.dns_manager._check_service_status(service)
                    if is_active:
                        st.metric(name, "Running", delta="✅")
                    else:
                        st.metric(name, "Stopped", delta="❌")
    
    # 檢查 SELinux 狀態
    if install_options.get('selinux_disable', False):
        success, stdout, _ = manager.dns_manager._run_command("getenforce")
        if success:
            selinux_status = stdout.strip()
            st.info(t('step2.selinux_status', status=selinux_status))
