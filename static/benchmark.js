document.addEventListener("DOMContentLoaded", () => {
    const btnSearch = document.getElementById("btnBenchSearch");
    const btnExport = document.getElementById("btnBenchExport");
    const statsSection = document.getElementById("benchStatsSection");
    const resultsSection = document.getElementById("benchResultsSection");
    const tableBody = document.getElementById("benchTableBody");
    const loader = document.getElementById("benchLoader");
    const errorBox = document.getElementById("benchError");

    const PER_PAGE = 20;

    function formatDate(dateStr) {
        if (!dateStr || dateStr === "—") return "—";
        try {
            const d = new Date(dateStr);
            const pad = n => String(n).padStart(2, "0");
            return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch {
            return dateStr;
        }
    }

    // History toggle
    const benchHistorySection = document.getElementById("benchHistorySection");
    const benchHistoryToggle = document.getElementById("benchHistoryToggle");
    if (benchHistorySection && benchHistoryToggle) {
        benchHistoryToggle.addEventListener("click", () => {
            benchHistorySection.classList.toggle("collapsed");
        });
    }

    async function loadBenchHistory() {
        try {
            const resp = await fetch("/api/benchmark/history?per_page=15", { credentials: "include" });
            if (!resp.ok) return;
            const json = await resp.json();
            const list = document.getElementById("benchHistoryList");
            const empty = document.getElementById("benchHistoryEmpty");
            list.innerHTML = "";
            list.className = "history-list";
            if (!json.items || json.items.length === 0) {
                empty.style.display = "block";
                return;
            }
            empty.style.display = "none";
            json.items.forEach((item) => {
                const div = document.createElement("div");
                div.className = "history-item";
                const dateStr = item.created_at ? formatDate(item.created_at) : "—";
                const count = item.filtered_count ?? item.total_vacancies ?? 0;
                div.innerHTML = `
                    <div class="history-item-info">
                        <div class="history-item-query">${escapeHtml(item.query_text || "(пусто)")}</div>
                        <div class="history-item-meta">${dateStr} · ${count} вакансий</div>
                    </div>
                    <div class="history-item-actions">
                        <button type="button" class="btn-outline btn-sm history-btn-open" data-id="${item.id}">Открыть</button>
                    </div>
                `;
                list.appendChild(div);
            });
            list.querySelectorAll(".history-btn-open").forEach((btn) => {
                btn.addEventListener("click", () => openHistoryBenchmark(btn.dataset.id));
            });
        } catch {}
    }

    async function openHistoryBenchmark(searchId) {
        hideError();
        loader.style.display = "block";
        try {
            const resp = await fetch(`/api/benchmark/rerun/${searchId}`, {
                method: "POST",
                credentials: "include",
            });
            const json = await resp.json();
            if (!resp.ok || json.error) {
                showError(json.error || "Не удалось загрузить результаты");
                return;
            }
            displayResults(json);
            benchHistorySection?.classList.add("collapsed");
        } catch (err) {
            showError("Ошибка: " + err.message);
        } finally {
            loader.style.display = "none";
        }
    }
    let currentTableData = [];
    let currentPage = 1;
    let salaryChart = null;

    function getFormData() {
        return {
            include: (document.getElementById("benchInclude")?.value ?? "").trim(),
            exclude: (document.getElementById("benchExclude")?.value ?? "").trim(),
            area: document.getElementById("benchArea")?.value ?? "16",
            experience: document.querySelector('input[name="benchExperience"]:checked')?.value ?? "",
            period: parseInt(document.getElementById("benchPeriod")?.value ?? "30", 10),
        };
    }

    // Search
    btnSearch.addEventListener("click", async () => {
        const data = getFormData();
        if (!data.include) {
            showError('Поле "Название вакансии" не может быть пустым');
            return;
        }

        hideError();
        statsSection.style.display = "none";
        resultsSection.style.display = "none";
        loader.style.display = "block";
        btnSearch.disabled = true;

        try {
            const resp = await fetch("/api/benchmark/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(data),
            });
            const json = await resp.json();

            if (json.error) {
                showError(json.error);
                return;
            }

            displayResults(json);
            loadBenchHistory();
        } catch (err) {
            showError("Ошибка сети: " + err.message);
        } finally {
            loader.style.display = "none";
            btnSearch.disabled = false;
        }
    });

    loadBenchHistory();

    // Export
    btnExport.addEventListener("click", async () => {
        const data = getFormData();
        if (!data.include) {
            showError("Сначала выполните поиск");
            return;
        }

        try {
            const resp = await fetch("/api/benchmark/export-excel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(data),
            });

            if (!resp.ok) {
                const err = await resp.json();
                showError(err.error || "Ошибка выгрузки");
                return;
            }

            const blob = await resp.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `vacancies_${data.include.substring(0, 30).replace(/\s/g, "_")}.xlsx`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (err) {
            showError("Ошибка при выгрузке: " + err.message);
        }
    });

    function displayResults(data) {
        currentTableData = data.table || [];
        currentPage = 1;

        updateStats(data.stats);
        updateChart(data);
        renderTablePage();
        renderPagination();

        statsSection.style.display = "block";
        if (currentTableData.length > 0) {
            resultsSection.style.display = "block";
            document.getElementById("benchResultsMeta").textContent =
                `(${currentTableData.length} вакансий)`;
        }

        statsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function updateStats(stats) {
        document.getElementById("statCount").textContent = stats.count || 0;
        document.getElementById("statMin").textContent = fmtSalary(stats.min);
        document.getElementById("statMax").textContent = fmtSalary(stats.max);
        document.getElementById("statMean").textContent = fmtSalary(stats.mean);
        document.getElementById("statMedian").textContent = fmtSalary(stats.median);
    }

    function renderTablePage() {
        tableBody.innerHTML = "";
        const start = (currentPage - 1) * PER_PAGE;
        const end = Math.min(start + PER_PAGE, currentTableData.length);
        const pageData = currentTableData.slice(start, end);

        if (pageData.length === 0) {
            const tr = document.createElement("tr");
            tr.innerHTML = '<td colspan="13" style="text-align:center;padding:2rem;">Вакансии не найдены</td>';
            tableBody.appendChild(tr);
            return;
        }

        pageData.forEach(row => {
            const tr = document.createElement("tr");
            const logoHtml = row.logo_url
                ? `<img src="${escapeHtml(row.logo_url)}" alt="" style="width:36px;height:36px;object-fit:contain;border-radius:4px" onerror="this.style.display='none'">`
                : "-";
            const safeUrl = row.url && (row.url.startsWith("http://") || row.url.startsWith("https://")) ? row.url : "#";
            const urlHtml = row.url ? `<a href="${safeUrl}" target="_blank" rel="noopener">Открыть</a>` : "-";

            tr.innerHTML = `
                <td>${logoHtml}</td>
                <td>${escapeHtml(row.name || "-")}</td>
                <td>${escapeHtml(row.employer_name || "-")}</td>
                <td>${escapeHtml(row.area_name || "-")}</td>
                <td>${escapeHtml(row.specialization || "-")}</td>
                <td>${escapeHtml(row.experience || "-")}</td>
                <td>${fmtSalary(row.salary_net_from_byn)}</td>
                <td>${fmtSalary(row.salary_net_to_byn)}</td>
                <td>${fmtSalary(row.salary_gross_from_byn)}</td>
                <td>${fmtSalary(row.salary_gross_to_byn)}</td>
                <td>${urlHtml}</td>
                <td style="white-space:nowrap">${escapeHtml(row.published_at || "-")}</td>
                <td style="white-space:nowrap">${escapeHtml(row.loaded_at || "-")}</td>
            `;
            tableBody.appendChild(tr);
        });
    }

    function renderPagination() {
        const totalPages = Math.max(1, Math.ceil(currentTableData.length / PER_PAGE));
        const start = (currentPage - 1) * PER_PAGE;
        const end = Math.min(start + PER_PAGE, currentTableData.length);
        const meta = currentTableData.length > 0
            ? `Стр. ${currentPage} из ${totalPages} (показано ${start + 1}–${end} из ${currentTableData.length})`
            : "нет результатов";
        document.getElementById("benchPaginationMeta").textContent = meta;
        document.getElementById("benchPrev").disabled = currentPage <= 1;
        document.getElementById("benchNext").disabled = currentPage >= totalPages;
    }

    document.getElementById("benchPrev").addEventListener("click", () => {
        if (currentPage > 1) { currentPage--; renderTablePage(); renderPagination(); }
    });
    document.getElementById("benchNext").addEventListener("click", () => {
        const totalPages = Math.ceil(currentTableData.length / PER_PAGE);
        if (currentPage < totalPages) { currentPage++; renderTablePage(); renderPagination(); }
    });

    // Chart
    function updateChart(data) {
        const ctx = document.getElementById("salaryChart").getContext("2d");
        if (salaryChart) salaryChart.destroy();

        const netData = (data.salary_avg_net || []).filter(v => v != null && !isNaN(v));
        if (netData.length === 0) return;

        const { bins, labels } = buildHistogramBins(netData);
        if (labels.length === 0) return;

        const netCounts = countInBins(netData, bins);

        salaryChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Net (средняя ЗП на руки)",
                    data: netCounts,
                    backgroundColor: "rgba(59, 130, 246, 0.6)",
                    borderColor: "rgba(37, 99, 235, 1)",
                    borderWidth: 1,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => ctx.dataset.label + ": " + ctx.parsed.y + " вакансий",
                        },
                    },
                },
                scales: {
                    x: { title: { display: true, text: "Диапазон ЗП (BYN)" }, ticks: { maxRotation: 45, minRotation: 45, font: { size: 11 } } },
                    y: { beginAtZero: true, ticks: { stepSize: 1 }, title: { display: true, text: "Количество вакансий" } },
                },
            },
        });
    }

    function buildHistogramBins(values, binCount = 8) {
        const all = values.filter(v => v != null && !isNaN(v));
        if (all.length === 0) return { bins: [], labels: [] };
        const min = Math.min(...all);
        const max = Math.max(...all);
        const step = (max - min) / binCount || 1;
        const bins = [];
        for (let i = 0; i < binCount; i++) {
            bins.push([min + i * step, min + (i + 1) * step]);
        }
        const labels = bins.map(([a, b]) => fmtShort(a) + " – " + fmtShort(b));
        return { bins, labels };
    }

    function countInBins(values, bins) {
        return bins.map(([lo, hi], idx) => {
            const isLast = idx === bins.length - 1;
            return values.filter(v => v >= lo && (isLast ? v <= hi : v < hi)).length;
        });
    }

    function fmtShort(value) {
        if (value == null || isNaN(value)) return "";
        if (value >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, "") + " тыс";
        return Math.round(value).toString();
    }

    function fmtSalary(value) {
        if (value == null || isNaN(value)) return "-";
        return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Math.round(value));
    }

    function escapeHtml(text) {
        if (!text) return "";
        const d = document.createElement("div");
        d.textContent = text;
        return d.innerHTML;
    }

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.style.display = "block";
        loader.style.display = "none";
    }

    function hideError() {
        errorBox.style.display = "none";
    }

    // Enter key triggers search
    ["benchInclude", "benchExclude"].forEach(id => {
        document.getElementById(id)?.addEventListener("keydown", e => {
            if (e.key === "Enter") btnSearch.click();
        });
    });
});
