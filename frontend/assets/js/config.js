const API_BASE_URL = 'http://localhost:8000/api/admin';
const WS_BASE_URL = 'ws://localhost:8000/ws/admin';

const API_ENDPOINTS = {
    dashboard: {
        stats: '/dashboard/stats/',
        charts: '/dashboard/charts/',
        activities: '/dashboard/activities/',
    },
    users: {
        list: '/users/',
        detail: (id) => `/users/${id}/`,
        bulk: '/users/bulk/',
        auctionActivity: (id) => `/users/${id}/auction-activity/`,
    },
    products: {
        store: '/products/store/',
        storeDetail: (id) => `/products/store/${id}/`,
        auction: '/products/auction/',
        auctionDetail: (id) => `/products/auction/${id}/`,
        bulk: '/products/store/bulk/',
    },
    requests: {
        list: '/requests/',
        detail: (type, id) => `/requests/${type}/${id}/`,
        bulk: '/requests/bulk/',
        templates: '/requests/templates/',
    },
    reports: {
        activityLogs: '/reports/activity-logs/',
        errorLogs: '/reports/error-logs/',
        adminLogs: '/reports/admin-logs/',
        export: '/reports/export/',
    },
    settings: {
        main: '/settings/',
        notifications: '/settings/notifications/',
        filters: '/filters/',
    },
};

window.API_BASE_URL = API_BASE_URL;
window.WS_BASE_URL = WS_BASE_URL;
window.API_ENDPOINTS = API_ENDPOINTS;
