class Utils {
    static formatDate(date) {
        return new Date(date).toLocaleDateString('fa-IR');
    }

    static formatCurrency(amount) {
        return `${new Intl.NumberFormat('fa-IR').format(amount)} تومان`;
    }

    static showModal(title, content) {
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
        modal.innerHTML = `
            <div class="bg-white rounded-lg p-6 max-w-2xl w-full">
                <h2 class="text-xl font-bold mb-4">${title}</h2>
                <div>${content}</div>
                <button onclick="this.closest('.fixed').remove()" class="mt-4 px-4 py-2 bg-blue-500 text-white rounded">بستن</button>
            </div>
        `;
        document.body.appendChild(modal);
    }

    static confirm(message) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
            modal.innerHTML = `
                <div class="bg-white rounded-lg p-6">
                    <p class="mb-4">${message}</p>
                    <button class="px-4 py-2 bg-red-500 text-white rounded mr-2" data-confirm="true">تایید</button>
                    <button class="px-4 py-2 bg-gray-300 rounded" data-confirm="false">لغو</button>
                </div>
            `;

            modal.querySelectorAll('button').forEach((button) => {
                button.onclick = () => {
                    resolve(button.dataset.confirm === 'true');
                    modal.remove();
                };
            });

            document.body.appendChild(modal);
        });
    }

    static showLoading() {
        if (document.getElementById('loading')) {
            return;
        }

        const loading = document.createElement('div');
        loading.id = 'loading';
        loading.className = 'fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50';
        loading.innerHTML = '<div class="bg-white p-4 rounded-lg">در حال بارگذاری…</div>';
        document.body.appendChild(loading);
    }

    static hideLoading() {
        document.getElementById('loading')?.remove();
    }
}

window.Utils = Utils;
