document.addEventListener("DOMContentLoaded", () => {
    const btnSearch = document.getElementById("btnSearch");
    const btnExport = document.getElementById("btnExport");
    const resultsSection = document.getElementById("resultsSection");
    const resultsBody = document.getElementById("resultsBody");
    const resultsMeta = document.getElementById("resultsMeta");
    const resultsPaginationMeta = document.getElementById("resultsPaginationMeta");
    const resultsPrev = document.getElementById("resultsPrev");
    const resultsNext = document.getElementById("resultsNext");
    const loader = document.getElementById("loader");
    const errorBox = document.getElementById("errorBox");

    const PER_PAGE = 20;
    let allCandidates = [];
    let currentPage = 1;
    let lastSearchId = null;

    // Collect form data (with fallbacks for cached HTML)
    function getFormData() {
        const searchText = (document.getElementById("searchText")?.value ?? "").trim();
        const searchInPositions = document.getElementById("searchInPositions")?.checked ?? false;
        const searchSkills = (document.getElementById("searchSkills")?.value ?? "").trim();
        const excludeTitle = (document.getElementById("excludeTitle")?.value ?? "").trim();
        const excludeCompany = (document.getElementById("excludeCompany")?.value ?? "").trim();
        const area = document.getElementById("area")?.value ?? "16";
        const period = document.getElementById("period")?.value ?? "30";
        const count = document.getElementById("count")?.value ?? "50";
        const sources = (document.querySelector('input[name="sources"]:checked')?.value ?? "both");

        const experience = [...document.querySelectorAll('input[name="experience"]:checked')]
            .map(el => el.value);

        return { searchText, searchInPositions, searchSkills, excludeTitle, excludeCompany, experience, area, period, count, sources };
    }

    // Build query string
    function buildQuery(data) {
        const params = new URLSearchParams();
        params.append("search_text", data.searchText);
        params.append("search_in_positions", data.searchInPositions ? "true" : "false");
        params.append("search_skills", data.searchSkills);
        params.append("exclude_title", data.excludeTitle);
        params.append("exclude_company", data.excludeCompany);
        data.experience.forEach(e => params.append("experience", e));
        params.append("area", data.area);
        params.append("period", data.period);
        params.append("count", data.count);
        params.append("sources", data.sources || "both");
        return params.toString();
    }

    // Format date string
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

    // Render table (with pagination - only current page slice)
    function renderTable(candidates) {
        resultsBody.innerHTML = "";
        const totalPages = Math.max(1, Math.ceil(candidates.length / PER_PAGE));
        const start = (currentPage - 1) * PER_PAGE;
        const end = Math.min(start + PER_PAGE, candidates.length);
        const pageCandidates = candidates.slice(start, end);

        pageCandidates.forEach((c) => {
            const tr = document.createElement("tr");

            // Source
            const tdSource = document.createElement("td");
            const src = c.source || "hh";
            const span = document.createElement("span");
            span.className = `source-badge ${src}`;
            span.textContent = src === "linkedin" ? "LI" : "HH";
            tdSource.appendChild(span);
            tr.appendChild(tdSource);

            // Photo
            const tdPhoto = document.createElement("td");
            if (c.photo) {
                const img = document.createElement("img");
                img.src = c.photo;
                img.alt = "Фото";
                img.className = "avatar";
                img.loading = "lazy";
                tdPhoto.appendChild(img);
            } else {
                const div = document.createElement("div");
                div.className = "no-photo";
                div.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
                tdPhoto.appendChild(div);
            }
            tr.appendChild(tdPhoto);

            // Name
            const tdName = document.createElement("td");
            tdName.textContent = c.full_name;
            tdName.style.fontWeight = "500";
            tr.appendChild(tdName);

            // Title
            const tdTitle = document.createElement("td");
            tdTitle.textContent = c.title;
            tr.appendChild(tdTitle);

            // Location
            const tdArea = document.createElement("td");
            tdArea.textContent = c.area;
            tr.appendChild(tdArea);

            // Experience
            const tdExp = document.createElement("td");
            tdExp.textContent = c.experience;
            tdExp.style.whiteSpace = "nowrap";
            tr.appendChild(tdExp);

            // Salary
            const tdSalary = document.createElement("td");
            tdSalary.textContent = c.salary;
            tdSalary.style.whiteSpace = "nowrap";
            tr.appendChild(tdSalary);

            // Link
            const tdLink = document.createElement("td");
            if (c.url) {
                const a = document.createElement("a");
                a.href = c.url;
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.textContent = "Открыть";
                tdLink.appendChild(a);
            } else {
                tdLink.textContent = "—";
            }
            tr.appendChild(tdLink);

            // Updated at
            const tdUpdated = document.createElement("td");
            tdUpdated.textContent = formatDate(c.updated_at);
            tdUpdated.style.whiteSpace = "nowrap";
            tr.appendChild(tdUpdated);

            // Fetched at
            const tdFetched = document.createElement("td");
            tdFetched.textContent = c.fetched_at;
            tdFetched.style.whiteSpace = "nowrap";
            tr.appendChild(tdFetched);

            resultsBody.appendChild(tr);
        });

        // Pagination meta & buttons
        const rangeStr = candidates.length > 0
            ? `показано ${start + 1}–${end} из ${candidates.length}`
            : "нет результатов";
        resultsPaginationMeta.textContent = `Стр. ${currentPage} из ${totalPages} (${rangeStr})`;
        resultsPrev.disabled = currentPage <= 1;
        resultsNext.disabled = currentPage >= totalPages;
    }

    function goToPage(page) {
        const totalPages = Math.max(1, Math.ceil(allCandidates.length / PER_PAGE));
        currentPage = Math.max(1, Math.min(page, totalPages));
        renderTable(allCandidates);
    }

    // Search
    btnSearch.addEventListener("click", async () => {
        const data = getFormData();

        if (!data.searchText && !data.searchSkills) {
            showError("Укажите поисковый запрос (название резюме или навыки)");
            return;
        }

        hideError();
        resultsSection.style.display = "none";
        loader.style.display = "block";
        btnSearch.disabled = true;

        try {
            const qs = buildQuery(data);
            const resp = await fetch(`/api/search?${qs}`, { credentials: "include" });
            if (!resp.ok) {
                const errText = await resp.text();
                let errMsg = `Ошибка ${resp.status}`;
                try {
                    const errJson = JSON.parse(errText);
                    errMsg = errJson.detail || errJson.message || errMsg;
                } catch {}
                showError(typeof errMsg === "string" ? errMsg : JSON.stringify(errMsg));
                return;
            }
            const json = await resp.json();

            if (json.error) {
                showError(json.message || "Ошибка при поиске");
                return;
            }

            allCandidates = json.candidates || [];
            lastSearchId = json.search_id || null;
            currentPage = 1;
            renderTable(allCandidates);
            resultsMeta.textContent = `(найдено ${json.total_found})`;
            resultsSection.style.display = "block";

            resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (err) {
            showError("Ошибка сети: " + err.message);
        } finally {
            loader.style.display = "none";
            btnSearch.disabled = false;
        }
    });

    // Export CSV
    btnExport.addEventListener("click", () => {
        if (!lastSearchId) return;
        window.open(`/api/export?search_id=${encodeURIComponent(lastSearchId)}`, "_blank");
    });

    // Helpers
    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.style.display = "block";
        loader.style.display = "none";
    }

    function hideError() {
        errorBox.style.display = "none";
    }

    // Pagination
    resultsPrev.addEventListener("click", () => goToPage(currentPage - 1));
    resultsNext.addEventListener("click", () => goToPage(currentPage + 1));

    // Enter key triggers search
    ["searchText", "searchSkills"].forEach(id => {
        document.getElementById(id)?.addEventListener("keydown", (e) => {
            if (e.key === "Enter") btnSearch.click();
        });
    });
});
