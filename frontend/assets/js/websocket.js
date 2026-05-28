class AdminWebSocket {
    constructor() {
        this.ws = null;
        this.callbacks = {};
        this.reconnectDelay = 5000;
        this.connect();
    }

    connect() {
        const fallbackBaseUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/admin`;
        const baseUrl = window.WS_BASE_URL || fallbackBaseUrl;
        this.ws = new WebSocket(`${baseUrl}/notifications/`);

        this.ws.onopen = () => console.log('Connected');
        this.ws.onmessage = (event) => this.handle(JSON.parse(event.data));
        this.ws.onclose = () => setTimeout(() => this.connect(), this.reconnectDelay);
    }

    handle(data) {
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(data.title, { body: data.message });
        }

        const toast = document.createElement('div');
        toast.className = 'fixed top-4 right-4 bg-white shadow-lg rounded p-4 z-50';
        toast.innerHTML = `<b>${data.title}</b><p class="text-sm">${data.message}</p>`;
        document.body.appendChild(toast);

        setTimeout(() => toast.remove(), 5000);

        const badge = document.querySelector(`[data-badge="${data.type}"]`);
        if (badge) {
            const currentValue = parseInt(badge.textContent || '0', 10) || 0;
            badge.textContent = currentValue + 1;
            badge.classList.remove('hidden');
        }

        if (this.callbacks[data.type]) {
            this.callbacks[data.type].forEach((callback) => callback(data));
        }
    }

    on(type, callback) {
        if (!this.callbacks[type]) {
            this.callbacks[type] = [];
        }
        this.callbacks[type].push(callback);
    }
}

const wsClient = new AdminWebSocket();

window.AdminWebSocket = AdminWebSocket;
window.wsClient = wsClient;
