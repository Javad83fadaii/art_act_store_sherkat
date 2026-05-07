class Utils {
    static formatDate(date) {
        return new Date(date).toLocaleDateString('fa-IR');
    }

    static formatCurrency(amount) {
        return '$' + new Intl.NumberFormat('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 0 }).format(amount);
    }
}

window.Utils = Utils;
