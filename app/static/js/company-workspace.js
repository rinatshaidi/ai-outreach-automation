"use strict";

document.addEventListener("DOMContentLoaded", () => {
  for (const form of document.querySelectorAll("form[data-single-submit]")) {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type=submit]");
      if (!(button instanceof HTMLButtonElement) || button.disabled) return;
      button.disabled = true;
      const pending = button.dataset.pendingLabel;
      if (pending) button.textContent = pending;
    });
  }

  for (const button of document.querySelectorAll("[data-copy-draft]")) {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyDraft || "");
      if (!(target instanceof HTMLTextAreaElement)) return;
      const original = button.textContent;
      try {
        await navigator.clipboard.writeText(target.value);
        button.textContent = document.documentElement.lang === "ru" ? "Скопировано" : "Copied";
      } catch (_) {
        target.focus();
        target.select();
        document.execCommand("copy");
        button.textContent = document.documentElement.lang === "ru" ? "Скопировано" : "Copied";
      }
      window.setTimeout(() => { button.textContent = original; }, 1800);
    });
  }
});
