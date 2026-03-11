/* AlfaHRService — Admin users page logic */
document.addEventListener("DOMContentLoaded", () => {
    let currentUserId = "";

    async function loadUsers() {
        const resp = await fetch("/api/admin/users");
        if (!resp.ok) {
            document.getElementById("usersBody").innerHTML =
                '<tr><td colspan="6" class="empty-state">Ошибка загрузки</td></tr>';
            return;
        }
        const users = await resp.json();
        const tbody = document.getElementById("usersBody");
        tbody.innerHTML = "";

        if (users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Нет пользователей</td></tr>';
            return;
        }

        users.forEach(u => {
            const tr = document.createElement("tr");
            const dt = u.created_at ? new Date(u.created_at) : null;
            const dtStr = dt ? dt.toLocaleDateString("ru-RU", { day:"2-digit", month:"2-digit", year:"numeric" }) : "—";
            const roleClass = u.is_admin ? "role-admin" : "role-user";
            const roleLabel = u.is_admin ? "Админ" : "Пользователь";
            const pwdStatus = u.must_change_password
                ? '<span style="color:#b45309;font-size:0.82rem;">По умолчанию</span>'
                : '<span style="color:#166534;font-size:0.82rem;">Изменён</span>';
            const isSelf = u.id === currentUserId;
            const deleteBtn = isSelf
                ? '<span style="font-size:0.78rem;color:var(--gray-400);">Вы</span>'
                : `<button class="btn-delete" data-uid="${u.id}" data-email="${escapeHtml(u.email)}">Удалить</button>`;

            tr.innerHTML = `
                <td style="font-weight:500;">${escapeHtml(u.email)}</td>
                <td>${escapeHtml(u.full_name || "—")}</td>
                <td><span class="role-badge ${roleClass}">${roleLabel}</span></td>
                <td>${pwdStatus}</td>
                <td style="white-space:nowrap;">${dtStr}</td>
                <td>${deleteBtn}</td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll(".btn-delete[data-uid]").forEach(btn => {
            btn.addEventListener("click", () => deleteUser(btn.dataset.uid, btn.dataset.email));
        });
    }

    document.getElementById("createUserForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const s = document.getElementById("createSuccess");
        const err = document.getElementById("createError");
        hideMsg(s); hideMsg(err);

        const email = document.getElementById("newEmail").value.trim();
        const fullName = document.getElementById("newFullName").value.trim();
        const password = document.getElementById("newPassword").value;
        const isAdmin = document.getElementById("newIsAdmin").checked;

        if (!email || !password) { showMsg(err, "Заполните email и пароль"); return; }

        const btn = document.getElementById("btnCreate");
        btn.disabled = true;

        try {
            const resp = await fetch("/api/admin/users", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email,
                    password,
                    full_name: fullName || null,
                    is_admin: isAdmin,
                }),
            });
            const data = await resp.json();

            if (!resp.ok) {
                showMsg(err, data.detail || "Ошибка создания");
                return;
            }

            showMsg(s, `Пользователь ${data.email} создан`);
            e.target.reset();
            loadUsers();
        } catch (ex) {
            showMsg(err, "Ошибка сети: " + ex.message);
        } finally {
            btn.disabled = false;
        }
    });

    async function deleteUser(id, email) {
        if (!confirm(`Удалить пользователя ${email}?`)) return;
        const resp = await fetch(`/api/admin/users/${id}`, { method: "DELETE" });
        if (resp.ok || resp.status === 204) {
            loadUsers();
        } else {
            const data = await resp.json().catch(() => ({}));
            alert(data.detail || "Ошибка удаления");
        }
    }

    document.addEventListener("alfahr:auth", (e) => {
        currentUserId = e.detail.id;
        loadUsers();
    });
});
