document.querySelectorAll("[data-deeper-research]").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector("[data-research-button]");
    const progress = form.querySelector("[data-research-progress]");
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    if (progress) {
      progress.classList.remove("d-none");
    }
  });
});
