(function() {
    'use strict';

    /* ── API Layer ─────────────────────────────────────────── */

    const API = {
        async request(url, options = {}) {
            const defaults = {
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin'
            };
            const opts = { ...defaults, ...options };
            if (opts.body && typeof opts.body === 'object') {
                opts.body = JSON.stringify(opts.body);
            }
            const res = await fetch(url, opts);
            if (res.status === 401) {
                window.location.href = '/';
                return null;
            }
            try {
                return await res.json();
            } catch {
                return null;
            }
        },

        get(url) { return this.request(url); },

        async post(url, body) {
            const csrf = await this.getCsrf();
            return this.request(url, {
                method: 'POST',
                body: { ...body, csrf_token: csrf }
            });
        },

        async getCsrf() {
            try {
                const res = await fetch('/api/csrf', { credentials: 'same-origin' });
                const data = await res.json();
                return data.csrf_token || '';
            } catch {
                return '';
            }
        }
    };

    /* ── State ─────────────────────────────────────────────── */

    let currentPage = 'overview';
    let modulesData = [];
    let currentFilter = 'all';
    let terminalHistory = [];
    let historyIndex = -1;
    let setupHasApi = false;
    let setupQrInterval = null;
    let setupPhone = '';
    let setupCode = '';
    let setup2faSource = 'phone';

    /* ── Init ──────────────────────────────────────────────── */

    function init() {
        setupNavigation();
        setupTerminal();
        setupDrawer();
        setupModuleSearch();
        setupFilterPills();
        setupLogout();
        setupSetupPage();
        loadDashboard();
    }

    /* ── Navigation ────────────────────────────────────────── */

    function setupNavigation() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                navigateTo(item.dataset.page);
            });
        });
    }

    window.navigateTo = function(page) {
        if (page === currentPage) return;

        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
        if (navItem) navItem.classList.add('active');

        const currentEl = document.getElementById(`page-${currentPage}`);
        const nextEl = document.getElementById(`page-${page}`);

        if (currentEl) {
            currentEl.style.animation = 'fadeOut 0.15s ease forwards';
            setTimeout(() => {
                currentEl.classList.remove('active');
                currentEl.style.animation = '';
            }, 150);
        }

        setTimeout(() => {
            if (nextEl) {
                nextEl.classList.add('active');
                nextEl.style.animation = 'pageIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards';
            }
        }, 150);

        currentPage = page;

        if (page === 'overview') loadDashboard();
        if (page === 'modules') loadModules();
        if (page === 'accounts') loadAccounts();
        if (page === 'setup') loadSetupStatus();
    };

    /* ── Dashboard / Overview ──────────────────────────────── */

    async function loadDashboard() {
        const data = await API.get('/api/dashboard');
        if (!data) return;

        document.getElementById('s-accounts').textContent = data.accounts || 0;
        document.getElementById('s-modules').textContent = data.modules || 0;
        document.getElementById('s-uptime').textContent = formatUptime(data.uptime || 0);
        document.getElementById('s-sessions').textContent = data.sessions || 0;

        const list = document.getElementById('accounts-list');
        if (data.accounts_list && data.accounts_list.length > 0) {
            list.innerHTML = data.accounts_list.map(acc => `
                <div class="account-item">
                    <div class="account-avatar">${esc(acc.name || '?')[0].toUpperCase()}</div>
                    <div class="account-info">
                        <span class="account-name">${esc(acc.name || 'Unknown')}</span>
                        <span class="account-id">${acc.username ? '@' + esc(acc.username) : 'ID: ' + acc.id}</span>
                    </div>
                    <div class="account-status ${acc.online ? 'online' : ''}"></div>
                </div>
            `).join('');
        } else {
            list.innerHTML = '<div class="empty-placeholder">No accounts connected</div>';
        }
    }

    /* ── Modules ───────────────────────────────────────────── */

    async function loadModules() {
        const data = await API.get('/api/modules');
        if (!data) return;
        modulesData = data.modules || [];
        renderModules();
    }

    function renderModules() {
        const grid = document.getElementById('modules-grid');
        const search = document.getElementById('module-search').value.toLowerCase();

        let filtered = modulesData.filter(m => {
            const matchesSearch = m.name.toLowerCase().includes(search) ||
                (m.description || '').toLowerCase().includes(search);
            const matchesFilter = currentFilter === 'all' ||
                (currentFilter === 'core' && m.core) ||
                (currentFilter === 'external' && !m.core);
            return matchesSearch && matchesFilter;
        });

        if (filtered.length === 0) {
            grid.innerHTML = '<div class="empty-placeholder">No modules found</div>';
            return;
        }

        grid.innerHTML = filtered.map((m, i) => `
            <div class="module-card ${m.enabled ? '' : 'disabled'}" style="animation-delay: ${Math.min(i * 30, 300)}ms" data-module="${esc(m.id || m.name)}">
                <div class="module-card-header">
                    <div class="module-icon ${m.core ? 'core' : 'external'}">
                        ${m.core ? coreSvg() : extSvg()}
                    </div>
                    <label class="toggle" ${m.core ? 'title="Core modules cannot be disabled"' : ''}>
                        <input type="checkbox" ${m.enabled ? 'checked' : ''} ${m.core ? 'disabled' : ''}
                            data-module-toggle="${esc(m.id || m.name)}">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
                <div class="module-card-body" data-config="${esc(m.id || m.name)}">
                    <div class="module-name">${esc(m.name)}</div>
                    <div class="module-desc">${esc(m.description || 'No description')}</div>
                </div>
                <div class="module-card-footer">
                    <span class="module-tag ${m.core ? 'core' : 'external'}">${m.core ? 'Core' : 'External'}</span>
                    ${m.commands && m.commands.length ? `<span class="module-cmds">${m.commands.length} cmd${m.commands.length !== 1 ? 's' : ''}</span>` : ''}
                </div>
            </div>
        `).join('');

        // Bind toggle events
        grid.querySelectorAll('[data-module-toggle]').forEach(toggle => {
            toggle.addEventListener('change', (e) => {
                e.stopPropagation();
                const name = e.target.dataset.moduleToggle;
                toggleModule(name, e.target.checked);
            });
        });

        // Bind config click events
        grid.querySelectorAll('[data-config]').forEach(el => {
            el.addEventListener('click', () => {
                openModuleConfig(el.dataset.config);
            });
        });
    }

    async function toggleModule(name, enabled) {
        const result = await API.post('/api/modules/toggle', { module: name, enabled });
        if (result && result.success) {
            const mod = modulesData.find(m => (m.id || m.name) === name);
            if (mod) mod.enabled = enabled;
        } else {
            // Revert toggle on failure
            const toggle = document.querySelector(`[data-module-toggle="${name}"]`);
            if (toggle) toggle.checked = !enabled;
            if (result && result.error) showToast(result.error, 'error');
        }
    }

    /* ── Module Config Drawer ──────────────────────────────── */

    async function openModuleConfig(name) {
        const drawer = document.getElementById('module-drawer');
        const overlay = document.getElementById('drawer-overlay');
        const title = document.getElementById('drawer-title');
        const body = document.getElementById('drawer-body');

        title.textContent = name;
        body.innerHTML = '<div class="empty-placeholder">Loading...</div>';

        drawer.classList.add('open');
        overlay.classList.add('open');

        const data = await API.get(`/api/modules/config/${encodeURIComponent(name)}`);
        if (!data) {
            body.innerHTML = '<div class="empty-placeholder">Failed to load config</div>';
            return;
        }

        title.textContent = data.name || name;

        let html = '';

        if (data.config && Object.keys(data.config).length > 0) {
            html += '<div class="config-section"><h4>Configuration</h4>';
            for (const [key, val] of Object.entries(data.config)) {
                html += `
                    <div class="config-item">
                        <label>${esc(key)}</label>
                        ${renderConfigInput(name, key, val)}
                    </div>
                `;
            }
            html += '</div>';
        } else {
            html += '<div class="config-section"><p class="config-empty">No configurable options.</p></div>';
        }

        if (data.commands && data.commands.length > 0) {
            html += '<div class="config-section"><h4>Commands</h4><div class="commands-list">';
            for (const cmd of data.commands) {
                html += `
                    <div class="command-item">
                        <code>.${esc(cmd.name)}</code>
                        <span>${esc(cmd.description || '')}</span>
                    </div>
                `;
            }
            html += '</div></div>';
        }

        body.innerHTML = html;

        // Bind config input changes
        body.querySelectorAll('.config-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
                saveConfigValue(name, e.target.dataset.key, val);
            });
        });
    }

    function renderConfigInput(module, key, value) {
        if (typeof value === 'boolean') {
            return `<label class="toggle" style="display:inline-flex">
                <input type="checkbox" class="config-input" data-key="${esc(key)}" ${value ? 'checked' : ''}>
                <span class="toggle-slider"></span>
            </label>`;
        }
        return `<input type="text" class="config-input" data-key="${esc(key)}" value="${esc(String(value))}">`;
    }

    async function saveConfigValue(module, key, value) {
        const result = await API.post(`/api/modules/config/${encodeURIComponent(module)}`, { key, value });
        if (result && result.success) {
            showToast('Saved', 'success');
        } else if (result && result.error) {
            showToast(result.error, 'error');
        }
    }

    function setupDrawer() {
        document.getElementById('drawer-close').addEventListener('click', closeDrawer);
        document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
    }

    function closeDrawer() {
        document.getElementById('module-drawer').classList.remove('open');
        document.getElementById('drawer-overlay').classList.remove('open');
    }

    /* ── Accounts ──────────────────────────────────────────── */

    async function loadAccounts() {
        const data = await API.get('/api/dashboard');
        if (!data) return;

        const container = document.getElementById('accounts-detail');
        if (data.accounts_list && data.accounts_list.length > 0) {
            container.innerHTML = data.accounts_list.map((acc, i) => `
                <div class="account-detail-card" style="animation-delay: ${i * 60}ms">
                    <div class="account-detail-header">
                        <div class="account-avatar large">${esc(acc.name || '?')[0].toUpperCase()}</div>
                        <div>
                            <h3>${esc(acc.name || 'Unknown')}</h3>
                            <span class="account-id">${acc.username ? '@' + esc(acc.username) : 'ID: ' + acc.id}</span>
                        </div>
                    </div>
                    <div class="account-detail-body">
                        <div class="detail-row"><span>Phone</span><span>${esc(acc.phone || 'Hidden')}</span></div>
                        <div class="detail-row"><span>Status</span><span class="status-badge ${acc.online ? 'online' : 'offline'}">${acc.online ? 'Online' : 'Offline'}</span></div>
                        <div class="detail-row"><span>Modules</span><span>${acc.modules || 0}</span></div>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<div class="empty-placeholder">No accounts connected</div>';
        }
    }

    /* ── Terminal ──────────────────────────────────────────── */

    function setupTerminal() {
        const input = document.getElementById('terminal-input');
        const output = document.getElementById('terminal-output');

        input.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter' && input.value.trim()) {
                const cmd = input.value.trim();
                terminalHistory.push(cmd);
                historyIndex = terminalHistory.length;
                input.value = '';

                appendTerminal(`<span class="term-prompt">zenkai $</span> ${esc(cmd)}`);

                const result = await API.post('/api/terminal/exec', { command: cmd });
                if (result) {
                    if (result.error) {
                        appendTerminal(`<span class="term-error">${esc(result.error)}</span>`);
                    } else {
                        appendTerminal(`<span class="term-output">${esc(result.output || '(no output)')}</span>`);
                    }
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (historyIndex > 0) {
                    historyIndex--;
                    input.value = terminalHistory[historyIndex] || '';
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (historyIndex < terminalHistory.length - 1) {
                    historyIndex++;
                    input.value = terminalHistory[historyIndex] || '';
                } else {
                    historyIndex = terminalHistory.length;
                    input.value = '';
                }
            }
        });
    }

    function appendTerminal(html) {
        const output = document.getElementById('terminal-output');
        const line = document.createElement('div');
        line.className = 'term-line';
        line.innerHTML = html;
        output.appendChild(line);
        output.scrollTop = output.scrollHeight;
    }

    /* ── Module Search & Filter ────────────────────────────── */

    function setupModuleSearch() {
        const input = document.getElementById('module-search');
        let debounce;
        input.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(renderModules, 180);
        });
    }

    function setupFilterPills() {
        document.querySelectorAll('.filter-pills .pill').forEach(pill => {
            pill.addEventListener('click', () => {
                document.querySelectorAll('.filter-pills .pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                currentFilter = pill.dataset.filter;
                renderModules();
            });
        });
    }

    /* ── Logout ────────────────────────────────────────────── */

    function setupLogout() {
        document.getElementById('btn-logout').addEventListener('click', async () => {
            await API.post('/api/logout', {});
            window.location.href = '/login';
        });
    }

    /* ── Toast Notification ────────────────────────────────── */

    function showToast(message, type = 'info') {
        const existing = document.querySelector('.toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed; bottom: 24px; right: 24px; z-index: 200;
            padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 500;
            font-family: 'Inter', sans-serif;
            animation: toastIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            backdrop-filter: blur(8px);
        `;

        if (type === 'error') {
            toast.style.background = 'rgba(239, 68, 68, 0.15)';
            toast.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            toast.style.color = '#ef4444';
        } else if (type === 'success') {
            toast.style.background = 'rgba(61, 214, 140, 0.15)';
            toast.style.border = '1px solid rgba(61, 214, 140, 0.3)';
            toast.style.color = '#3dd68c';
        } else {
            toast.style.background = 'rgba(109, 142, 253, 0.15)';
            toast.style.border = '1px solid rgba(109, 142, 253, 0.3)';
            toast.style.color = '#6d8efd';
        }

        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'toastOut 0.2s ease forwards';
            setTimeout(() => toast.remove(), 200);
        }, 2500);
    }

    // Add toast keyframes
    const style = document.createElement('style');
    style.textContent = `
        @keyframes toastIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes toastOut { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(8px); } }
    `;
    document.head.appendChild(style);

    /* ── Helpers ───────────────────────────────────────────── */

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return '-';
        if (seconds < 60) return `${Math.floor(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
    }

    function esc(str) {
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function coreSvg() {
        return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    }

    function extSvg() {
        return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>';
    }

    /* ── Setup Page ─────────────────────────────────────────── */

    let setupLoginMode = 'qr'; // 'qr' | 'phone' | 'code' | '2fa'

    function setupSetupPage() {
        document.getElementById('btn-save-api').addEventListener('click', saveApiCreds);
        document.getElementById('btn-send-code').addEventListener('click', sendTgCode);
        document.getElementById('btn-submit-code').addEventListener('click', submitTgCode);
        document.getElementById('btn-submit-2fa').addEventListener('click', submit2fa);
        document.getElementById('btn-save-bot').addEventListener('click', saveCustomBot);
        document.getElementById('btn-skip-bot').addEventListener('click', skipCustomBot);

        document.querySelectorAll('.login-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const target = tab.dataset.tab;
                if (target === setupLoginMode) return;
                document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById('panel-qr').classList.toggle('hidden', target !== 'qr');
                document.getElementById('panel-phone').classList.toggle('hidden', target !== 'phone');
                if (target === 'qr') {
                    stopQrPoll();
                    resetSetupState().then(() => startQrLogin());
                } else if (target === 'phone') {
                    stopQrPoll();
                    resetSetupState().then(() => showPhoneStep('phone'));
                }
            });
        });

        document.getElementById('setup-code').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitTgCode();
        });
        document.getElementById('setup-2fa').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submit2fa();
        });
    }

    function stopQrPoll() {
        if (setupQrInterval) { clearInterval(setupQrInterval); setupQrInterval = null; }
    }

    async function resetSetupState() {
        try { await fetch('/api/setup/reset', { method:'POST', credentials:'include' }); } catch(e) {}
    }

    async function loadSetupStatus() {
        const data = await API.get('/api/setup/status');
        if (!data) return;
        setupHasApi = data.has_api;
        if (!data.needs_setup) {
            stopQrPoll();
            showSetupStep('success');
            return;
        }
        if (setupHasApi) {
            showSetupStep('login');
            startQrLogin();
        } else {
            showSetupStep('api');
        }
    }

    function showSetupStep(step) {
        document.querySelectorAll('.setup-step').forEach(el => {
            const s = el.dataset.step;
            el.classList.toggle('active', s === step);
            el.classList.toggle('done', (s === 'api' && (step === 'login' || step === 'bot')) ||
                                       (s === 'login' && step === 'bot'));
        });
        ['form-api', 'form-login', 'form-bot', 'form-success'].forEach(id => {
            document.getElementById(id).classList.add('hidden');
        });
        const formMap = {api:'form-api',login:'form-login',bot:'form-bot',success:'form-success'};
        if (formMap[step]) document.getElementById(formMap[step]).classList.remove('hidden');
    }

    async function saveApiCreds() {
        const apiId = document.getElementById('setup-api-id').value.trim();
        const apiHash = document.getElementById('setup-api-hash').value.trim();
        if (!apiId || !/^\d+$/.test(apiId)) { showToast('Invalid API ID','error'); return; }
        if (!apiHash || apiHash.length!==32 || !/^[0-9a-fA-F]+$/.test(apiHash)) { showToast('Invalid API Hash — 32 hex chars','error'); return; }
        const btn = document.getElementById('btn-save-api');
        btn.disabled = true; btn.textContent = 'Saving...';
        try {
            const res = await fetch('/set_api', { method:'PUT', credentials:'include', body: apiHash+apiId });
            const text = await res.text();
            if (res.ok && text==='ok') { setupHasApi=true; showToast('API credentials saved','success'); showSetupStep('login'); startQrLogin(); }
            else showToast(text||'Failed to save','error');
        } catch(e) { showToast('Error: '+e.message,'error'); }
        finally { btn.disabled=false; btn.textContent='Save & Continue'; }
    }

    async function startQrLogin() {
        stopQrPoll();
        setupLoginMode = 'qr';
        const container = document.getElementById('setup-qr-container');
        container.innerHTML = '<div class="qr-placeholder">Loading QR...</div>';
        document.getElementById('qr-status').textContent = 'Waiting for scan...';
        try {
            const res = await fetch('/init_qr_login', { method:'POST', credentials:'include' });
            const url = await res.text();
            if (!res.ok) { container.innerHTML = `<div class="qr-placeholder" style="color:var(--accent-red)">Error: ${esc(url)}</div>`; return; }
            renderQrCode(container, url);
            setupQrInterval = setInterval(async () => {
                try {
                    const pr = await fetch('/get_qr_url', { method:'POST', credentials:'include' });
                    if (pr.status === 200) {
                        const pt = await pr.text();
                        if (pt === 'SUCCESS') {
                            stopQrPoll();
                            document.getElementById('qr-status').textContent = 'Logged in!';
                            onLoginSuccess();
                            return;
                        }
                    }
                    if (pr.status === 403) {
                        stopQrPoll();
                        document.getElementById('qr-status').textContent = '2FA password required';
                        showQr2fa();
                        return;
                    }
                    if (pr.status === 201) {
                        const newUrl = await pr.text();
                        renderQrCode(container, newUrl);
                    }
                } catch(e) {}
            }, 1500);
        } catch(e) { container.innerHTML = `<div class="qr-placeholder" style="color:var(--accent-red)">Error: ${esc(e.message)}</div>`; }
    }

    function renderQrCode(container, data) {
        container.innerHTML = '';
        if (typeof QRCodeStyling !== 'undefined') {
            const qr = new QRCodeStyling({ width:220, height:220, type:'svg', data, dotsOptions:{type:'rounded'}, cornersSquareOptions:{type:'extra-rounded'}, backgroundOptions:{color:'transparent'}, qrOptions:{errorCorrectionLevel:'M'} });
            qr.append(container);
        } else { container.innerHTML = `<div class="qr-placeholder">QR lib not loaded. <a href="${esc(data)}" target="_blank">Open link</a></div>`; }
    }

    function showQr2fa() {
        setupLoginMode = '2fa';
        setup2faSource = 'qr';
        // Switch to phone panel but only show 2FA field
        document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
        document.getElementById('tab-phone').classList.add('active');
        document.getElementById('panel-qr').classList.add('hidden');
        document.getElementById('panel-phone').classList.remove('hidden');
        // Hide phone and code fields, show only 2FA
        document.getElementById('group-phone').classList.add('hidden');
        document.getElementById('btn-send-code').classList.add('hidden');
        document.getElementById('group-code').classList.add('hidden');
        document.getElementById('btn-submit-code').classList.add('hidden');
        document.getElementById('group-2fa').classList.remove('hidden');
        document.getElementById('btn-submit-2fa').classList.remove('hidden');
        document.getElementById('setup-2fa').focus();
    }

    // ── Phone step-by-step ──────────────────────────────────
    // States: 'phone' → 'code' → '2fa'

    function showPhoneStep(state) {
        setupLoginMode = state;
        // Ensure phone panel is visible
        document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
        document.getElementById('tab-phone').classList.add('active');
        document.getElementById('panel-qr').classList.add('hidden');
        document.getElementById('panel-phone').classList.remove('hidden');

        if (state === 'phone') {
            document.getElementById('group-phone').classList.remove('hidden');
            document.getElementById('btn-send-code').classList.remove('hidden');
            document.getElementById('group-code').classList.add('hidden');
            document.getElementById('btn-submit-code').classList.add('hidden');
            document.getElementById('group-2fa').classList.add('hidden');
            document.getElementById('btn-submit-2fa').classList.add('hidden');
            document.getElementById('setup-phone').focus();
        } else if (state === 'code') {
            document.getElementById('group-phone').classList.add('hidden');
            document.getElementById('btn-send-code').classList.add('hidden');
            document.getElementById('group-code').classList.remove('hidden');
            document.getElementById('btn-submit-code').classList.remove('hidden');
            document.getElementById('group-2fa').classList.add('hidden');
            document.getElementById('btn-submit-2fa').classList.add('hidden');
            document.getElementById('setup-code').value = '';
            document.getElementById('setup-code').focus();
        } else if (state === '2fa') {
            setup2faSource = 'phone';
            document.getElementById('group-phone').classList.add('hidden');
            document.getElementById('btn-send-code').classList.add('hidden');
            document.getElementById('group-code').classList.add('hidden');
            document.getElementById('btn-submit-code').classList.add('hidden');
            document.getElementById('group-2fa').classList.remove('hidden');
            document.getElementById('btn-submit-2fa').classList.remove('hidden');
            document.getElementById('setup-2fa').value = '';
            document.getElementById('setup-2fa').focus();
        }
    }

    async function sendTgCode() {
        const phone = document.getElementById('setup-phone').value.trim();
        if (!phone || !/^\+?\d{10,15}$/.test(phone)) { showToast('Invalid phone number (use +XXXXXXXXXXX)','error'); return; }
        const btn = document.getElementById('btn-send-code');
        btn.disabled=true; btn.textContent='Sending...';
        try {
            const res = await fetch('/send_tg_code', { method:'POST', credentials:'include', body:phone });
            const text = await res.text();
            if (res.ok && text==='ok') {
                setupPhone = phone;
                showToast('Code sent to Telegram','success');
                showPhoneStep('code');
            } else {
                showToast(text || 'Failed to send code','error');
            }
        } catch(e) { showToast('Error: '+e.message,'error'); }
        finally { btn.disabled=false; btn.textContent='Send Code'; }
    }

    async function submitTgCode() {
        const code = document.getElementById('setup-code').value.trim();
        if (!code || code.length<5) { showToast('Enter the 5-digit code','error'); return; }
        const btn = document.getElementById('btn-submit-code');
        btn.disabled=true; btn.textContent='Verifying...'; setupCode=code;
        try {
            const res = await fetch('/tg_code', { method:'POST', credentials:'include', body:`${code}\n${setupPhone}\n` });
            if (res.ok) {
                showToast('Logged in!','success');
                onLoginSuccess();
            } else if (res.status===401) {
                showToast('2FA password required','info');
                showPhoneStep('2fa');
            } else {
                const t=await res.text(); showToast(t||'Invalid code','error');
            }
        } catch(e) { showToast('Error: '+e.message,'error'); }
        finally { btn.disabled=false; btn.textContent='Submit Code'; }
    }

    async function submit2fa() {
        const pass = document.getElementById('setup-2fa').value.trim();
        if (!pass) { showToast('Enter 2FA password','error'); return; }
        const btn = document.getElementById('btn-submit-2fa');
        btn.disabled=true; btn.textContent='Verifying...';
        try {
            let res;
            if (setup2faSource === 'qr') {
                res = await fetch('/qr_2fa', { method:'POST', credentials:'include', body:pass });
            } else {
                res = await fetch('/tg_code', { method:'POST', credentials:'include', body:`${setupCode}\n${setupPhone}\n${pass}` });
            }
            if (res.ok) {
                showToast('Logged in!','success');
                onLoginSuccess();
            } else {
                const t=await res.text(); showToast(t||'Invalid 2FA password','error');
            }
        } catch(e) { showToast('Error: '+e.message,'error'); }
        finally { btn.disabled=false; btn.textContent='Submit 2FA'; }
    }

    async function onLoginSuccess() {
        showSetupStep('bot');
    }

    async function saveCustomBot() {
        const bot = document.getElementById('setup-bot').value.trim().replace(/^@/,'');
        if (bot && (!bot.toLowerCase().endsWith('bot') || bot.length<5)) {
            showToast('Bot username must end with "bot" and be 5+ chars','error'); return;
        }
        const btn = document.getElementById('btn-save-bot');
        btn.disabled=true; btn.textContent='Saving...';
        try {
            if (bot) {
                const res = await fetch('/custom_bot', { method:'POST', credentials:'include', body:bot });
                const t = await res.text();
                if (t==='OCCUPIED') { showToast('Username is occupied','error'); btn.disabled=false; btn.textContent='Finish Setup'; return; }
            }
            await fetch('/finish_login', { method:'POST', credentials:'include' });
            showToast('Setup complete!','success');
            showSetupStep('success');
        } catch(e) { showToast('Error: '+e.message,'error'); }
        finally { btn.disabled=false; btn.textContent='Finish Setup'; }
    }

    async function skipCustomBot() {
        try {
            await fetch('/finish_login', { method:'POST', credentials:'include' });
            showToast('Setup complete!','success');
            showSetupStep('success');
        } catch(e) { showToast('Error: '+e.message,'error'); }
    }

    /* ── Boot ──────────────────────────────────────────────── */

    document.addEventListener('DOMContentLoaded', init);
})();
