const btn = document.getElementById("menu-button");
const nav = document.querySelector(".nav__menu");

btn.addEventListener("click", function() {
    if (this.classList.contains("menu-not-active")) {
        this.classList.remove("menu-not-active");
        this.classList.add("menu-active");
        nav.classList.add("active");
    } else {
        this.classList.remove("menu-active");
        this.classList.add("menu-not-active");
        nav.classList.remove("active");
    }
});

window.addEventListener("click", function(event) {
    const btn = document.getElementById("menu-button");
    const nav = document.querySelector(".nav__menu");
    
    if (!btn.contains(event.target)) {
        btn.classList.remove("menu-active");
        btn.classList.add("menu-not-active");
        nav.classList.remove("active");
    }
});
