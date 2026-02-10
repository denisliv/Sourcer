document.addEventListener("DOMContentLoaded", () => {
    const btnSearch = document.getElementById("btnSearch");
    const btnExport = document.getElementById("btnExport");
    const resultsSection = document.getElementById("resultsSection");
    const resultsBody = document.getElementById("resultsBody");
    const resultsMeta = document.getElementById("resultsMeta");
    const loader = document.getElementById("loader");
    const errorBox = document.getElementById("errorBox");

    // Collect form data
    function getFormData() {
        const searchText = document.getElementById("searchText").value.trim();
        const excludeText = document.getElementById("excludeText").value.trim();
        const period = document.getElementById("period").value;
        const count = document.getElementById("count").value;

        const searchFields = [...document.querySelectorAll('input[name="searchField"]:checked')]
            .map(el => el.value);
        const excludeFields = [...document.querySelectorAll('input[name="excludeField"]:checked')]
            .map(el => el.value);
        const experience = [...document.querySelectorAll('input[name="experience"]:checked')]
            .map(el => el.value);

        return { searchText, searchFields, excludeText, excludeFields, experience, period, count };
    }

    // Build query string supporting repeated params
    function buildQuery(data) {
        const params = new URLSearchParams();
        params.append("search_text", data.searchText);
        data.searchFields.forEach(f => params.append("search_fields", f));
        params.append("exclude_text", data.excludeText);
        data.excludeFields.forEach(f => params.append("exclude_fields", f));
        data.experience.forEach(e => params.append("experience", e));
        params.append("period", data.period);
        params.append("count", data.count);
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

    // Render table
    function renderTable(candidates) {
        resultsBody.innerHTML = "";
        candidates.forEach((c, idx) => {
            const tr = document.createElement("tr");

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
    }

    // Search
    btnSearch.addEventListener("click", async () => {
        const data = getFormData();

        if (!data.searchText) {
            showError("Введите название позиции");
            return;
        }
        if (data.searchFields.length === 0) {
            showError("Выберите хотя бы одну область поиска");
            return;
        }

        hideError();
        resultsSection.style.display = "none";
        loader.style.display = "block";
        btnSearch.disabled = true;

        try {
            const qs = buildQuery(data);
            const resp = await fetch(`/api/search?${qs}`);
            const json = await resp.json();

            if (json.error) {
                showError(json.message || "Ошибка при поиске");
                return;
            }

            renderTable(json.candidates);
            resultsMeta.textContent = `(найдено ${json.total_found}, показано ${json.returned})`;
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
        const data = getFormData();
        if (!data.searchText) return;
        const qs = buildQuery(data);
        window.open(`/api/export?${qs}`, "_blank");
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

    // Enter key triggers search
    document.getElementById("searchText").addEventListener("keydown", (e) => {
        if (e.key === "Enter") btnSearch.click();
    });
});
