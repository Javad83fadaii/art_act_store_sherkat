class Charts {
    static createLineChart(id, data, label) {
        const canvas = document.getElementById(id);
        if (!canvas || typeof Chart === 'undefined') {
            return null;
        }

        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: data.map((item) => item.label),
                datasets: [
                    {
                        label,
                        data: data.map((item) => item.value),
                        borderColor: 'rgb(59, 130, 246)',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
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
}

window.Charts = Charts;
