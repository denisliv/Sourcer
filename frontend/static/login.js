/* AlfaHRService — Login page logic */
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("loginForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const errBox = document.getElementById("loginError");
        errBox.style.display = "none";

        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;
        const btn = document.getElementById("btnLogin");
        btn.disabled = true;

        try {
            const resp = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });
            const data = await resp.json();

            if (!resp.ok) {
                errBox.textContent = data.detail || "Ошибка авторизации";
                errBox.style.display = "block";
                return;
            }

            window.location.href = data.redirect || "/";
        } catch (err) {
            errBox.textContent = "Ошибка сети: " + err.message;
            errBox.style.display = "block";
        } finally {
            btn.disabled = false;
        }
    });
});
