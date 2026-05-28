class API {
    static async request(url, options = {}) {
        const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': token || '',
            ...(options.headers || {}),
        };

        try {
            const response = await fetch(`${window.API_BASE_URL}${url}`, {
                credentials: 'include',
                ...options,
                headers,
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
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
}

window.API = API;
