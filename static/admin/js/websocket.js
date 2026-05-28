class AdminWebSocket {
    constructor() {
        this.ws = null;
        this.callbacks = {};
        this.maxItems = 20;
        this.storageKey = 'admin_notifications_items_v1';
        this.unreadKey = 'admin_notifications_unread_v1';
        this.lastSeenKey = 'admin_notifications_last_seen_v1';
        this.elements = {};
        this.uiReady = false;
        this.initUI();
        this.connect();
    }

    initUI() {
        const container = document.getElementById('admin-notifications');
        const btn = document.getElementById('admin-notifications-btn');
        const badge = document.getElementById('admin-notifications-badge');
        const menu = document.getElementById('admin-notifications-menu');
        const list = document.getElementById('admin-notifications-list');
        const clearBtn = document.getElementById('admin-notifications-clear');

        if (!container || !btn || !badge || !menu || !list || !clearBtn) {
            return;
        }

        this.elements = { container, btn, badge, menu, list, clearBtn };
        this.uiReady = true;

        const unread = this.getUnread();
        this.setUnread(unread);
        this.renderList();
        this.refreshFromServer();
        setInterval(() => this.refreshFromServer(), 30000);

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.toggleMenu();
        });

        clearBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.setUnread(0);
            this.hideMenu();
        });

        document.addEventListener('click', (e) => {
            if (!this.elements.container.contains(e.target)) {
                this.hideMenu();
            }
        });
    }

    connect() {
        const fallbackBaseUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/admin`;
        const baseUrl = window.WS_BASE_URL || fallbackBaseUrl;
        this.ws = new WebSocket(`${baseUrl}/notifications/`);
        this.ws.onmessage = (event) => this.handle(JSON.parse(event.data));
        this.ws.onclose = () => {
            setTimeout(() => this.connect(), 5000);
        };
    }

    handle(data) {
        this.pushItem(data);
        this.incrementUnread(data.timestamp);
        this.renderList();
        this.renderBadge();

        if ('Notification' in window && Notification.permission === 'granted') {
            try {
                new Notification(data.title || 'اعلان جدید', { body: data.message || '' });
            } catch (e) {}
        }

        if (this.callbacks[data.type]) {
            this.callbacks[data.type].forEach((callback) => callback(data));
        }
    }

    toggleMenu() {
        if (!this.uiReady) return;
        const isHidden = this.elements.menu.classList.contains('hidden');
        if (isHidden) {
            this.elements.menu.classList.remove('hidden');
            this.setLastSeen(Date.now());
            this.refreshFromServer();
            this.setUnread(0);
        } else {
            this.hideMenu();
        }
    }

    hideMenu() {
        if (!this.uiReady) return;
        this.elements.menu.classList.add('hidden');
    }

    on(type, callback) {
        if (!this.callbacks[type]) {
            this.callbacks[type] = [];
        }
        this.callbacks[type].push(callback);
    }

    safeParse(value, fallback) {
        try {
            return JSON.parse(value);
        } catch (e) {
            return fallback;
        }
    }

    getItems() {
        const raw = localStorage.getItem(this.storageKey);
        const items = this.safeParse(raw, []);
        return Array.isArray(items) ? items : [];
    }

    setItems(items) {
        localStorage.setItem(this.storageKey, JSON.stringify(items));
    }

    getUnread() {
        const raw = localStorage.getItem(this.unreadKey);
        const val = parseInt(raw || '0', 10);
        return Number.isFinite(val) ? Math.max(0, val) : 0;
    }

    setUnread(value) {
        const v = Math.max(0, parseInt(value || 0, 10) || 0);
        localStorage.setItem(this.unreadKey, String(v));
        this.renderBadge();
    }

    incrementUnread(timestamp) {
        if (!this.uiReady) return;
        const isMenuOpen = !this.elements.menu.classList.contains('hidden');
        if (isMenuOpen) return;
        const lastSeen = this.getLastSeen();
        const tsMs = this.parseTimestampMs(timestamp);
        if (tsMs && tsMs <= lastSeen) return;
        this.setUnread(this.getUnread() + 1);
    }

    pushItem(data) {
        const item = {
            type: data.type || 'general',
            title: data.title || '',
            message: data.message || '',
            timestamp: data.timestamp || '',
            data: data.data || {},
            href: data.href || '',
        };
        const items = this.getItems();
        items.unshift(item);
        this.setItems(items.slice(0, this.maxItems));
    }

    typeMeta(type) {
        const map = {
            purchase_request: { label: 'خرید', href: '/admin-panel/requests/?type=purchase' },
            verification_request: { label: 'تایید مزایده', href: '/admin-panel/requests/?type=verification' },
            credit_request: { label: 'افزایش اعتبار', href: '/admin-panel/requests/?type=credit' },
            admin_panel_refresh: { label: 'بروزرسانی', href: window.location.pathname + window.location.search },
        };
        return map[type] || { label: 'عمومی', href: '/admin-panel/requests/' };
    }

    formatTime(iso) {
        if (!iso) return '';
        const dt = new Date(iso);
        if (Number.isNaN(dt.getTime())) return '';
        try {
            return new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit' }).format(dt);
        } catch (e) {
            return '';
        }
    }

    renderBadge() {
        if (!this.uiReady) return;
        const unread = this.getUnread();
        if (unread <= 0) {
            this.elements.badge.classList.add('hidden');
            this.elements.badge.textContent = '';
            return;
        }
        this.elements.badge.textContent = unread > 99 ? '99+' : String(unread);
        this.elements.badge.classList.remove('hidden');
        this.elements.badge.classList.add('flex');
    }

    renderList() {
        if (!this.uiReady) return;
        const items = this.getItems();
        if (!items.length) {
            this.elements.list.innerHTML =
                '<div class="px-4 py-4 text-center text-xs font-bold text-text-muted">اعلان جدیدی وجود ندارد.</div>';
            return;
        }

        const html = items
            .map((item) => {
                const meta = this.typeMeta(item.type);
                const time = this.formatTime(item.timestamp);
                const title = this.escapeHtml(item.title);
                const message = this.escapeHtml(item.message);
                const href = item.href || meta.href;
                const label = this.escapeHtml(meta.label);
                return `
                    <a href="${href}" class="block px-4 py-3 hover:bg-primary/5 transition-colors border-b border-gray-100/80 dark:border-white/5">
                        <div class="flex items-start justify-between gap-3">
                            <div class="min-w-0">
                                <div class="flex items-center gap-2">
                                    <span class="text-[11px] font-black text-orange-600 dark:text-orange-400">${label}</span>
                                    ${time ? `<span class="text-[10px] font-bold text-text-muted">${time}</span>` : ''}
                                </div>
                                <div class="text-xs font-black text-text-main dark:text-white mt-1 truncate">${title}</div>
                                <div class="text-[11px] font-bold text-text-muted mt-1 max-h-10 overflow-hidden">${message}</div>
                            </div>
                        </div>
                    </a>
                `;
            })
            .join('');

        this.elements.list.innerHTML = html;
    }

    escapeHtml(value) {
        const str = String(value || '');
        return str
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    getLastSeen() {
        const raw = localStorage.getItem(this.lastSeenKey);
        const val = parseInt(raw || '0', 10);
        return Number.isFinite(val) ? Math.max(0, val) : 0;
    }

    setLastSeen(value) {
        const v = Math.max(0, parseInt(value || 0, 10) || 0);
        localStorage.setItem(this.lastSeenKey, String(v));
    }

    parseTimestampMs(iso) {
        if (!iso) return 0;
        const dt = new Date(iso);
        if (Number.isNaN(dt.getTime())) return 0;
        return dt.getTime();
    }

    async refreshFromServer() {
        if (!this.uiReady) return;
        if (!window.API_BASE_URL) return;
        try {
            const response = await fetch(`${window.API_BASE_URL}/notifications/?limit=${this.maxItems}`, {
                credentials: 'include',
            });
            if (!response.ok) return;
            const payload = await response.json();
            const serverItems = Array.isArray(payload.items) ? payload.items : [];
            const normalized = serverItems.map((it) => ({
                type: it.type || 'general',
                title: it.title || '',
                message: it.message || '',
                timestamp: it.timestamp || '',
                data: it.data || {},
                href: it.href || '',
            }));
            this.setItems(normalized.slice(0, this.maxItems));

            const isMenuOpen = !this.elements.menu.classList.contains('hidden');
            const lastSeen = this.getLastSeen();
            const unread = normalized.reduce((acc, it) => {
                const ms = this.parseTimestampMs(it.timestamp);
                if (!ms) return acc;
                return ms > lastSeen ? acc + 1 : acc;
            }, 0);
            this.setUnread(isMenuOpen ? 0 : unread);
            this.renderList();
        } catch (e) {}
    }
}

window.AdminWebSocket = AdminWebSocket;
window.wsClient = new AdminWebSocket();
