(function() {
    function getCatalog() {
        return window.APP_NOTIFICATIONS || {};
    }

    function resolvePath(key) {
        return String(key || '')
            .split('.')
            .reduce(function(current, part) {
                if (!current || typeof current !== 'object') return undefined;
                return current[part];
            }, getCatalog());
    }

    function formatMessage(template, params) {
        return String(template || '').replace(/\{(\w+)\}/g, function(match, token) {
            return Object.prototype.hasOwnProperty.call(params || {}, token) ? String(params[token]) : match;
        });
    }

    function getNotificationMessage(key, params, fallback) {
        var resolved = resolvePath(key);
        var template = typeof resolved === 'string' ? resolved : (fallback || '');
        return formatMessage(template, params || {});
    }

    function ensureContainer(position) {
        var safePosition = position || 'bottom-left';
        var containerId = 'fallback-toast-' + safePosition;
        var container = document.getElementById(containerId);
        if (container) return container;

        container = document.createElement('div');
        container.id = containerId;
        container.style.position = 'fixed';
        container.style.zIndex = '99999';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '10px';
        container.style.pointerEvents = 'none';
        container.style.maxWidth = 'calc(100vw - 32px)';

        if (safePosition === 'top-right') {
            container.style.top = '20px';
            container.style.right = '20px';
        } else if (safePosition === 'top-left') {
            container.style.top = '20px';
            container.style.left = '20px';
        } else if (safePosition === 'bottom-right') {
            container.style.bottom = '20px';
            container.style.right = '20px';
        } else {
            container.style.bottom = '20px';
            container.style.left = '20px';
        }

        document.body.appendChild(container);
        return container;
    }

    function fallbackToast(message, type, position) {
        var container = ensureContainer(position);
        var toast = document.createElement('div');
        toast.textContent = String(message || '');
        toast.style.padding = '12px 16px';
        toast.style.borderRadius = '12px';
        toast.style.color = '#fff';
        toast.style.fontWeight = '700';
        toast.style.fontSize = '13px';
        toast.style.minWidth = '0';
        toast.style.maxWidth = 'calc(100vw - 32px)';
        toast.style.wordBreak = 'break-word';
        toast.style.whiteSpace = 'normal';
        toast.style.boxShadow = '0 12px 30px rgba(0, 0, 0, 0.18)';
        toast.style.pointerEvents = 'auto';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(8px)';
        toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';

        if (type === 'success') toast.style.background = '#16A34A';
        else if (type === 'error') toast.style.background = '#DC2626';
        else if (type === 'warning') toast.style.background = '#D97706';
        else toast.style.background = '#2563EB';

        container.appendChild(toast);
        requestAnimationFrame(function() {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        window.setTimeout(function() {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(8px)';
            window.setTimeout(function() {
                toast.remove();
            }, 260);
        }, 3200);
    }

    if (typeof window.showToast !== 'function') {
        window.showToast = function(message, type, position) {
            fallbackToast(message, type, position);
        };
    }

    function showNotificationText(message, options) {
        var config = options || {};
        var type = config.type || 'info';
        var position = config.position || 'bottom-left';
        var toastOptions = config.toastOptions;

        if (typeof window.showToast === 'function') {
            window.showToast(message, type, position, toastOptions);
            return;
        }

        fallbackToast(message, type, position);
    }

    function showNotificationMessage(key, options) {
        var config = options || {};
        var message = getNotificationMessage(key, config.params || {}, config.fallback || '');
        if (!message) return '';
        showNotificationText(message, config);
        return message;
    }

    window.getNotificationMessage = getNotificationMessage;
    window.showNotificationText = showNotificationText;
    window.showNotificationMessage = showNotificationMessage;

    document.addEventListener('DOMContentLoaded', function() {
        if (window.__TOAST_QUERY_HANDLED) return;
        try {
            var q = new URLSearchParams(window.location.search);
            var message = q.get('toast_message');
            if (!message) return;
            window.__TOAST_QUERY_HANDLED = true;
            var type = q.get('toast_type') || 'info';
            var position = q.get('toast_position') || 'bottom-left';
            var actionLabel = q.get('toast_action_label') || '';
            var actionHref = q.get('toast_action_href') || '';
            if (typeof window.showToast === 'function') {
                window.showToast(message, type, position, { actionLabel: actionLabel, actionHref: actionHref });
            } else if (typeof window.showNotificationText === 'function') {
                window.showNotificationText(message, { type: type, position: position, toastOptions: { actionLabel: actionLabel, actionHref: actionHref } });
            }
            q.delete('toast_message');
            q.delete('toast_type');
            q.delete('toast_position');
            q.delete('toast_action_label');
            q.delete('toast_action_href');
            var next = q.toString();
            var url = window.location.pathname + (next ? ('?' + next) : '') + window.location.hash;
            window.history.replaceState({}, document.title, url);
        } catch (e) {}
    });
})();
