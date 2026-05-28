class Charts {
    static createLineChart(id, data, label) {
        const canvas = document.getElementById(id);
        if (!canvas || typeof Chart === 'undefined') {
            return null;
        }

        const ctx = canvas.getContext('2d');
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map((item) => item.label),
                datasets: [
                    {
                        label,
                        data: data.map((item) => item.value),
                        borderColor: 'rgb(59,130,246)',
                        backgroundColor: 'rgba(59,130,246,0.1)',
                        tension: 0.4,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false,
                    },
                },
            },
        });
    }

    static createBarChart(id, data, label) {
        const canvas = document.getElementById(id);
        if (!canvas || typeof Chart === 'undefined') {
            return null;
        }

        const ctx = canvas.getContext('2d');
        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.map((item) => item.label),
                datasets: [
                    {
                        label,
                        data: data.map((item) => item.value),
                        backgroundColor: 'rgb(16,185,129)',
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false,
                    },
                },
            },
        });
    }

    static createDoughnutChart(id, data) {
        const canvas = document.getElementById(id);
        if (!canvas || typeof Chart === 'undefined') {
            return null;
        }

        const ctx = canvas.getContext('2d');
        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.map((item) => item.label),
                datasets: [
                    {
                        data: data.map((item) => item.value),
                        backgroundColor: [
                            'rgb(59,130,246)',
                            'rgb(16,185,129)',
                            'rgb(245,158,11)',
                            'rgb(239,68,68)',
                            'rgb(139,92,246)',
                        ],
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'right',
                    },
                },
            },
        });
    }
}

window.Charts = Charts;
