class API {
    static async request(url, options = {}) {
        const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': token || '',
            ...(options.headers || {}),
        };
        const response = await fetch(`${window.API_BASE_URL}${url}`, {
            credentials: 'include',
            ...options,
            headers,
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return response.json();
        }

        return response.text();
    }

    static get(url) {
        return this.request(url);
    }

    static post(url, data) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    static put(url, data) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    static delete(url) {
        return this.request(url, {
            method: 'DELETE',
        });
    }

    get(url) {
        return API.get(url);
    }

    post(url, data) {
        return API.post(url, data);
    }

    put(url, data) {
        return API.put(url, data);
    }

    delete(url) {
        return API.delete(url);
    }
}

window.API = API;
