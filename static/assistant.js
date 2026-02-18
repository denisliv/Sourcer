/* AlfaHRAssistent — chat frontend */
(function () {
    "use strict";

    const chatList = document.getElementById("chatList");
    const chatWelcome = document.getElementById("chatWelcome");
    const chatConversation = document.getElementById("chatConversation");
    const chatMessages = document.getElementById("chatMessages");
    const chatTitle = document.getElementById("chatTitle");
    const chatForm = document.getElementById("chatForm");
    const chatInput = document.getElementById("chatInput");
    const btnSend = document.getElementById("btnSend");
    const btnNewChat = document.getElementById("btnNewChat");
    const btnNewChatWelcome = document.getElementById("btnNewChatWelcome");
    const btnDeleteChat = document.getElementById("btnDeleteChat");
    const btnSidebarToggle = document.getElementById("btnSidebarToggle");
    const sidebar = document.getElementById("chatSidebar");

    let activeChatId = null;
    let isStreaming = false;

    /* ── Auth check ─────────────────────────────────────────────── */
    fetch("/api/auth/me", { credentials: "include" })
        .then(r => { if (!r.ok) { window.location.href = "/login"; throw new Error("unauth"); } return r.json(); })
        .then(u => {
            if (u.is_admin) {
                const el = document.getElementById("adminLink");
                if (el) el.style.display = "";
            }
        })
        .catch(() => {});

    /* ── Logout ─────────────────────────────────────────────────── */
    document.getElementById("btnLogout").addEventListener("click", async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        window.location.href = "/login";
    });

    /* ── Services dropdown (from header) ────────────────────────── */
    (function () {
        const btn = document.getElementById("servicesMenuBtn");
        const menu = document.getElementById("servicesMenu");
        if (btn && menu) {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const open = menu.classList.toggle("dropdown-open");
                btn.setAttribute("aria-expanded", open);
            });
            document.addEventListener("click", () => {
                menu.classList.remove("dropdown-open");
                btn.setAttribute("aria-expanded", "false");
            });
        }
        document.querySelectorAll(".dropdown-item-disabled").forEach(el => {
            el.addEventListener("click", (e) => { e.preventDefault(); });
        });
    })();

    /* ── Sidebar toggle (mobile) ────────────────────────────────── */
    btnSidebarToggle.addEventListener("click", () => {
        sidebar.classList.toggle("sidebar-open");
    });

    /* ── Auto-resize textarea ───────────────────────────────────── */
    chatInput.addEventListener("input", () => {
        chatInput.style.height = "auto";
        chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + "px";
        btnSend.disabled = !chatInput.value.trim() || isStreaming;
    });

    /* ── Enter = send, Shift+Enter = newline ────────────────────── */
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!btnSend.disabled) chatForm.requestSubmit();
        }
    });

    /* ── Load chats ─────────────────────────────────────────────── */
    async function loadChats() {
        try {
            const r = await fetch("/api/assistant/chats", { credentials: "include" });
            if (!r.ok) return;
            const data = await r.json();
            renderChatList(data.items);
        } catch (e) { console.error("loadChats", e); }
    }

    function renderChatList(items) {
        if (!items.length) {
            chatList.innerHTML = '<div class="chat-list-empty">Нет чатов</div>';
            return;
        }
        chatList.innerHTML = items.map(c => {
            const active = c.id === activeChatId ? " active" : "";
            const d = c.updated_at ? new Date(c.updated_at) : null;
            const dateStr = d ? d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "";
            return `
                <div class="chat-list-item${active}" data-id="${c.id}">
                    <span class="chat-list-item-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    </span>
                    <span class="chat-list-item-text">${escapeHtml(c.title)}</span>
                    <span class="chat-list-item-date">${dateStr}</span>
                    <button class="chat-list-item-delete" data-id="${c.id}" title="Удалить чат">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>`;
        }).join("");

        chatList.querySelectorAll(".chat-list-item").forEach(el => {
            el.addEventListener("click", (e) => {
                if (e.target.closest(".chat-list-item-delete")) return;
                openChat(el.dataset.id);
            });
        });

        chatList.querySelectorAll(".chat-list-item-delete").forEach(el => {
            el.addEventListener("click", (e) => {
                e.stopPropagation();
                deleteChat(el.dataset.id);
            });
        });
    }

    /* ── Create new chat ────────────────────────────────────────── */
    async function createChat() {
        try {
            const r = await fetch("/api/assistant/chats", {
                method: "POST", credentials: "include",
            });
            if (!r.ok) return;
            const data = await r.json();
            await loadChats();
            openChat(data.id);
        } catch (e) { console.error("createChat", e); }
    }

    btnNewChat.addEventListener("click", createChat);
    btnNewChatWelcome.addEventListener("click", createChat);

    /* ── Open chat ──────────────────────────────────────────────── */
    async function openChat(chatId) {
        activeChatId = chatId;
        chatWelcome.style.display = "none";
        chatConversation.style.display = "flex";
        sidebar.classList.remove("sidebar-open");

        chatList.querySelectorAll(".chat-list-item").forEach(el => {
            el.classList.toggle("active", el.dataset.id === chatId);
        });

        chatMessages.innerHTML = "";
        chatTitle.textContent = "Загрузка...";

        try {
            const r = await fetch(`/api/assistant/chats/${chatId}/messages`, { credentials: "include" });
            if (!r.ok) return;
            const data = await r.json();
            chatTitle.textContent = data.title || "Новый чат";
            data.messages.forEach(m => appendMessage(m.role, m.content));
            scrollToBottom();
        } catch (e) { console.error("openChat", e); }

        chatInput.focus();
    }

    /* ── Delete chat ────────────────────────────────────────────── */
    async function deleteChat(chatId) {
        if (!chatId) return;
        if (!confirm("Удалить этот чат?")) return;
        try {
            const r = await fetch(`/api/assistant/chats/${chatId}`, {
                method: "DELETE", credentials: "include",
            });
            if (!r.ok) return;
            if (activeChatId === chatId) {
                activeChatId = null;
                chatConversation.style.display = "none";
                chatWelcome.style.display = "flex";
            }
            await loadChats();
        } catch (e) { console.error("deleteChat", e); }
    }

    btnDeleteChat.addEventListener("click", () => deleteChat(activeChatId));

    /* ── Send message ───────────────────────────────────────────── */
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text || !activeChatId || isStreaming) return;

        chatInput.value = "";
        chatInput.style.height = "auto";
        btnSend.disabled = true;
        isStreaming = true;

        appendMessage("user", text);
        scrollToBottom();

        const assistantEl = appendMessage("assistant", "");
        const bubble = assistantEl.querySelector(".msg-bubble");
        bubble.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
        scrollToBottom();

        try {
            const resp = await fetch(`/api/assistant/chats/${activeChatId}/messages`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: text }),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                bubble.innerHTML = `<p style="color:#b91c1c;">${escapeHtml(err.error || "Ошибка сервера")}</p>`;
                isStreaming = false;
                btnSend.disabled = false;
                return;
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let fullText = "";
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const payload = line.slice(6).trim();
                    if (payload === "[DONE]") continue;

                    try {
                        const msg = JSON.parse(payload);
                        if (msg.token) {
                            fullText += msg.token;
                            bubble.innerHTML = renderMarkdown(fullText);
                            scrollToBottom();
                        }
                        if (msg.title) {
                            chatTitle.textContent = msg.title;
                            loadChats();
                        }
                        if (msg.error) {
                            bubble.innerHTML += `<p style="color:#b91c1c;">${escapeHtml(msg.error)}</p>`;
                        }
                    } catch (_) { /* skip malformed */ }
                }
            }

            if (!fullText) {
                bubble.innerHTML = '<p style="color:var(--gray-400);">Нет ответа</p>';
            }
        } catch (err) {
            console.error("stream error", err);
            bubble.innerHTML = `<p style="color:#b91c1c;">Ошибка подключения: ${escapeHtml(err.message)}</p>`;
        }

        isStreaming = false;
        btnSend.disabled = !chatInput.value.trim();
        scrollToBottom();
    });

    /* ── DOM helpers ─────────────────────────────────────────────── */
    function appendMessage(role, content) {
        const div = document.createElement("div");
        div.className = `msg msg-${role}`;
        const avatarLabel = role === "user" ? "Вы" : "AI";
        div.innerHTML = `
            <div class="msg-avatar">${avatarLabel}</div>
            <div class="msg-bubble">${content ? renderMarkdown(content) : ""}</div>
        `;
        chatMessages.appendChild(div);
        return div;
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

    function escapeHtml(str) {
        const el = document.createElement("span");
        el.textContent = str;
        return el.innerHTML;
    }

    /* ── Markdown rendering (lightweight) ───────────────────────── */
    function renderMarkdown(text) {
        let html = escapeHtml(text);

        // Code blocks ```...```
        html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
            `<pre><code>${code.trim()}</code></pre>`
        );

        // Inline code
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

        // Bold **text**
        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

        // Italic *text*
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");

        // Headers
        html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
        html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
        html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
        html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

        // Unordered lists
        html = html.replace(/^[-*] (.+)$/gm, "<li>$1</li>");
        html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

        // Numbered lists
        html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

        // Paragraphs
        html = html.replace(/\n{2,}/g, "</p><p>");
        html = html.replace(/\n/g, "<br>");

        // Wrap in paragraph if not starting with block element
        if (!/^<(h[1-4]|ul|ol|pre|p)/.test(html)) {
            html = "<p>" + html + "</p>";
        }

        return html;
    }

    /* ── Init ───────────────────────────────────────────────────── */
    loadChats();
})();
