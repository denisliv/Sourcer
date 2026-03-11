/* AlfaHRService — Home page: dev cards toast */
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".service-card-dev").forEach(card => {
        card.addEventListener("click", () => showDevToast("В разработке"));
    });
});
