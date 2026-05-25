document.addEventListener("DOMContentLoaded", function () {

    fetch("/performance/data")
        .then(response => response.json())
        .then(data => {

            if (!data || !data.overall_performance) {
                console.log("No performance data found");
                return;
            }

            // ---------------- OVERALL STATS ----------------
            document.getElementById("totalAttempts").innerText = data.total_attempts;
            document.getElementById("overallAccuracy").innerText =
                data.overall_performance.overall_accuracy + "%";
            document.getElementById("totalCorrect").innerText =
                data.overall_performance.total_correct;
            document.getElementById("totalWrong").innerText =
                data.overall_performance.total_wrong;

            // ---------------- ACCURACY HISTORY CHART ----------------
            const attemptHistory = data.attempt_history;

            const labels = attemptHistory.map((item, index) =>
                "Test " + (index + 1)
            );

            const accuracies = attemptHistory.map(item =>
                item.accuracy
            );

            const ctx1 = document.getElementById("accuracyChart").getContext("2d");

            new Chart(ctx1, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [{
                        label: "Accuracy %",
                        data: accuracies,
                        borderColor: "#c77dff",
                        backgroundColor: "rgba(199,125,255,0.2)",
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { labels: { color: "white" } }
                    },
                    scales: {
                        x: { ticks: { color: "white" } },
                        y: {
                            ticks: { color: "white" },
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });

            // ---------------- STAGE PERFORMANCE CHART ----------------
            const stageSummary = data.stage_summary;

            const stageLabels = [];
            const stageAccuracy = [];

            for (let stage in stageSummary) {
                stageLabels.push(stage);
                stageAccuracy.push(stageSummary[stage].average_accuracy);
            }

            const ctx2 = document.getElementById("stageChart").getContext("2d");

            new Chart(ctx2, {
                type: "bar",
                data: {
                    labels: stageLabels,
                    datasets: [{
                        label: "Average Accuracy %",
                        data: stageAccuracy,
                        backgroundColor: "#8a00ff"
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { labels: { color: "white" } }
                    },
                    scales: {
                        x: { ticks: { color: "white" } },
                        y: {
                            ticks: { color: "white" },
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });

        })
        .catch(error => {
            console.error("Error fetching performance data:", error);
        });

});
