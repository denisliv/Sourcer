/* AlfaHRService — Account page logic */
document.addEventListener("DOMContentLoaded", () => {

    async function apiPost(url, data) {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        return { resp, data: await resp.json() };
    }
    async function apiDelete(url) {
        const resp = await fetch(url, { method: "DELETE" });
        return { resp, data: await resp.json() };
    }

    // --- Password change ---
    document.getElementById("passwordForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const s = document.getElementById("pwdSuccess");
        const err = document.getElementById("pwdError");
        hideMsg(s); hideMsg(err);

        const newPwd = document.getElementById("newPassword").value;
        const confirmPwd = document.getElementById("confirmPassword").value;
        if (newPwd !== confirmPwd) {
            showMsg(err, "Пароли не совпадают");
            return;
        }

        const result = await apiPost("/api/account/password", {
            current_password: document.getElementById("currentPassword").value,
            new_password: newPwd,
        });
        if (!result.resp.ok) {
            showMsg(err, result.data.detail || "Ошибка");
        } else {
            showMsg(s, result.data.message || "Пароль изменён");
            e.target.reset();
        }
    });

    // --- LinkedIn credentials ---
    document.getElementById("liForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const s = document.getElementById("liSuccess");
        const err = document.getElementById("liError");
        hideMsg(s); hideMsg(err);

        const username = document.getElementById("liUsername").value.trim();
        const password = document.getElementById("liPassword").value;
        if (!username || !password) { showMsg(err, "Заполните все поля"); return; }

        const submitBtn = e.target.querySelector('button[type="submit"]');
        const origLabel = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = "Авторизация…";

        try {
            const controller = new AbortController();
            const tid = setTimeout(() => controller.abort(), 360_000);
            const resp = await fetch("/api/account/credentials/linkedin", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
                signal: controller.signal,
            });
            clearTimeout(tid);
            const data = await resp.json();
            if (!resp.ok) {
                showMsg(err, data.detail || "Ошибка");
            } else if (data.cookies_failed) {
                showMsg(err, data.message);
            } else {
                showMsg(s, data.message || "Сохранено");
                document.getElementById("liPassword").value = "";
                setTimeout(() => location.reload(), 1200);
            }
        } catch (fetchErr) {
            if (fetchErr.name === "AbortError") {
                showMsg(err, "Превышено время ожидания. Попробуйте ещё раз.");
            } else {
                showMsg(err, "Ошибка сети: " + fetchErr.message);
            }
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = origLabel;
        }
    });

    document.getElementById("btnDeleteLI").addEventListener("click", async () => {
        if (!confirm("Отключить LinkedIn?")) return;
        const result = await apiDelete("/api/account/credentials/linkedin");
        if (result.resp.ok) location.reload();
    });

    // --- Logs ---
    const ACTION_LABELS = {
        login: "Вход",
        logout: "Выход",
        search: "Поиск",
        export_csv: "Экспорт CSV",
        password_change: "Смена пароля",
        credential_update: "Обн. credentials",
        credential_delete: "Удал. credentials",
        admin_create_user: "Создание пользователя",
        admin_delete_user: "Удаление пользователя",
        benchmark_search: "Benchmark: поиск",
        benchmark_open: "Benchmark: открытие",
        benchmark_export: "Benchmark: экспорт",
    };

    let logsPage = 1;
    let logsViewerIsAdmin = false;

    async function loadLogs(page = 1) {
        const filter = document.getElementById("logFilter").value;
        let url = `/api/account/logs?page=${page}&per_page=15`;
        if (filter) url += `&action=${filter}`;

        const resp = await fetch(url);
        const data = await resp.json();

        if (data.viewer_is_admin !== undefined) logsViewerIsAdmin = data.viewer_is_admin;

        const thUser = document.getElementById("logsUserTh");
        thUser.style.display = logsViewerIsAdmin ? "" : "none";

        const tbody = document.getElementById("logsBody");
        tbody.innerHTML = "";

        const colspan = logsViewerIsAdmin ? 5 : 4;
        if (!data.logs || data.logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center;color:var(--gray-400);padding:1.5rem;">Нет записей</td></tr>`;
        } else {
            data.logs.forEach(log => {
                const tr = document.createElement("tr");
                const dt = log.created_at ? new Date(log.created_at) : null;
                const dtStr = dt ? dt.toLocaleString("ru-RU", { day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit" }) : "—";

                let details = "";
                if (log.details) {
                    if (log.details.query) details = `Запрос: "${log.details.query}"`;
                    else if (log.details.message) details = log.details.message;
                    else details = JSON.stringify(log.details).substring(0, 80);
                }

                const userCell = logsViewerIsAdmin ? `<td style="white-space:nowrap;">${log.user_email || "—"}</td>` : "";
                tr.innerHTML = `
                    <td style="white-space:nowrap;">${dtStr}</td>
                    ${userCell}
                    <td>${ACTION_LABELS[log.action] || log.action}</td>
                    <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${details || "—"}</td>
                    <td style="white-space:nowrap;">${log.ip_address || "—"}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        logsPage = page;
        const totalPages = Math.ceil(data.total / data.per_page) || 1;
        document.getElementById("logsMeta").textContent = `Стр. ${page} из ${totalPages} (всего ${data.total})`;
        document.getElementById("logsPrev").disabled = page <= 1;
        document.getElementById("logsNext").disabled = page >= totalPages;
    }

    document.getElementById("logFilter").addEventListener("change", () => loadLogs(1));
    document.getElementById("logsPrev").addEventListener("click", () => loadLogs(logsPage - 1));
    document.getElementById("logsNext").addEventListener("click", () => loadLogs(logsPage + 1));

    loadLogs(1);

    // --- Load account status ---
    (async function loadAccountStatus() {
        try {
            const resp = await fetch("/api/account/status", { credentials: "include" });
            if (!resp.ok) { window.location.href = "/login"; return; }
            const data = await resp.json();
            const u = data.user;

            document.getElementById("profileName").textContent = u.full_name || "—";
            document.getElementById("profileEmail").textContent = u.email;
            document.getElementById("profileRole").textContent = u.is_admin ? "Администратор" : "Пользователь";
            if (u.is_admin) { const el = document.getElementById("adminLink"); if (el) el.style.display = ""; }
            if (u.must_change_password) document.getElementById("mustChangeBanner").style.display = "";

            // HH status
            const hhBadge = document.getElementById("hhStatusBadge");
            const hhLabels = { active: "Подключён", error: "Ошибка", expired: "Токен истёк", not_configured: "Не подключён" };
            hhBadge.textContent = hhLabels[data.hh_status] || "Не подключён";
            hhBadge.className = "status-badge status-" + data.hh_status;

            if (data.hh_expires_at) {
                document.getElementById("hhExpiresRow").style.display = "";
                document.getElementById("hhExpiresAt").textContent = data.hh_expires_at;
            }

            const hhDescs = {
                not_configured: "Для работы с HH необходимо авторизовать ваш аккаунт. Нажмите кнопку ниже — вы будете перенаправлены на страницу авторизации HeadHunter.",
                expired: "Срок действия токена истёк. Переподключите аккаунт для продолжения работы.",
                active: "Аккаунт подключён. Токен обновляется автоматически.",
            };
            document.getElementById("hhDescription").textContent = hhDescs[data.hh_status] || "Произошла ошибка. Попробуйте переподключить аккаунт.";

            const hhActions = document.getElementById("hhActions");
            const needConnect = ["not_configured", "expired", "error"].includes(data.hh_status);
            let actionsHtml = "";

            if (!data.is_production) {
                actionsHtml += '<button type="button" id="btnHHDevAuth" class="btn-primary btn-sm">'
                    + (needConnect ? 'Подключить HH (dev)' : 'Переподключить (dev)') + '</button>';
                actionsHtml += '<div id="hhDevCodeBlock" style="margin-top:0.75rem;display:none;">'
                    + '<p style="font-size:0.82rem;color:var(--gray-600);margin-bottom:0.5rem;">'
                    + 'После авторизации на HH скопируйте параметр <code>code</code> из адресной строки и вставьте сюда:'
                    + '</p>'
                    + '<div style="display:flex;gap:0.5rem;align-items:center;">'
                    + '<input type="text" id="hhDevCodeInput" placeholder="Вставьте code" style="flex:1;padding:0.5rem 0.75rem;border:1.5px solid var(--blue-200);border-radius:8px;font-size:0.9rem;">'
                    + '<button type="button" id="btnHHDevSubmit" class="btn-primary btn-sm">Обменять код</button>'
                    + '</div>'
                    + '<div id="hhDevError" class="msg msg-error" style="display:none;margin-top:0.5rem;"></div>'
                    + '</div>';
            } else {
                if (needConnect) {
                    actionsHtml += '<a href="/api/account/hh/authorize" class="btn-primary btn-sm" style="text-decoration:none;display:inline-flex;align-items:center;gap:0.35rem;">Подключить HH аккаунт</a>';
                } else {
                    actionsHtml += '<a href="/api/account/hh/authorize" class="btn-outline btn-sm" style="text-decoration:none;display:inline-flex;align-items:center;gap:0.35rem;">Переподключить</a>';
                }
            }

            if (data.hh_status !== "not_configured") {
                actionsHtml += '<button type="button" id="btnDeleteHH" class="btn-danger btn-sm">Отключить</button>';
            }
            hhActions.innerHTML = actionsHtml;

            const btnDevAuth = document.getElementById("btnHHDevAuth");
            if (btnDevAuth) {
                btnDevAuth.addEventListener("click", async () => {
                    document.getElementById("hhDevCodeBlock").style.display = "block";
                    try {
                        const r = await fetch("/api/account/hh/authorize-url", { credentials: "include" });
                        if (r.ok) { const d = await r.json(); window.open(d.url, "_blank"); }
                    } catch (e) { console.error(e); }
                });
            }
            const btnDevSubmit = document.getElementById("btnHHDevSubmit");
            if (btnDevSubmit) {
                btnDevSubmit.addEventListener("click", async () => {
                    const code = document.getElementById("hhDevCodeInput").value.trim();
                    const errEl = document.getElementById("hhDevError");
                    errEl.style.display = "none";
                    if (!code) { errEl.textContent = "Введите код"; errEl.style.display = ""; return; }
                    btnDevSubmit.disabled = true;
                    btnDevSubmit.textContent = "Обмен...";
                    try {
                        const r = await fetch("/api/account/hh/dev-code", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            credentials: "include",
                            body: JSON.stringify({ code }),
                        });
                        const d = await r.json();
                        if (r.ok && d.ok) {
                            location.href = "/account?hh_connected=1";
                        } else {
                            errEl.textContent = d.detail || d.message || "Ошибка обмена кода";
                            errEl.style.display = "";
                        }
                    } catch (e) {
                        errEl.textContent = "Сетевая ошибка: " + e.message;
                        errEl.style.display = "";
                    } finally {
                        btnDevSubmit.disabled = false;
                        btnDevSubmit.textContent = "Обменять код";
                    }
                });
            }

            const btnDelHH = document.getElementById("btnDeleteHH");
            if (btnDelHH) btnDelHH.addEventListener("click", async () => {
                if (!confirm("Отключить HH аккаунт?")) return;
                const r = await apiDelete("/api/account/credentials/hh");
                if (r.resp.ok) location.reload();
            });

            const params = new URLSearchParams(window.location.search);
            if (params.get("hh_connected")) showMsg(document.getElementById("hhSuccess"), "HH аккаунт успешно подключён!");
            if (params.get("hh_error")) showMsg(document.getElementById("hhError"), params.get("hh_error"));

            // LinkedIn status
            const liBadge = document.getElementById("liStatusBadge");
            const liLabels = { active: "Активен", error: "Ошибка", expired: "Cookies истекли", not_configured: "Не настроен" };
            liBadge.textContent = liLabels[data.li_status] || "Не настроен";
            liBadge.className = "status-badge status-" + data.li_status;

            if (data.li_username) {
                document.getElementById("liUsernameRow").style.display = "";
                document.getElementById("liUsernameVal").textContent = data.li_username;
            }
        } catch (e) {
            console.error("Failed to load account status:", e);
        }
    })();
});
