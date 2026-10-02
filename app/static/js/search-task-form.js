"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector('#new-search-task form[action="/search-tasks"]');
  if (!form) return;

  const query = form.querySelector('textarea[name="original_query"]');
  const type = form.querySelector('select[name="task_type"]');
  const company = form.querySelector('input[name="company_name_or_url"]');
  if (!(query instanceof HTMLTextAreaElement)) return;

  const russian = document.documentElement.lang === "ru";
  const modernSearch = Boolean(form.querySelector(".search-bar-shell"));
  if (!modernSearch) {
    const label = query.closest("label");
    if (label) {
      label.classList.add("w-100");
      const firstText = Array.from(label.childNodes).find(
        (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim(),
      );
      if (firstText) {
        firstText.textContent = russian
          ? "Опишите, что найти или какую компанию проверить"
          : "Describe what to find or which company to analyze";
      }
    }
    query.rows = 3;
    query.placeholder = russian
      ? "Например: Найди 5 компаний в Мексике, где мой опыт развития бизнеса может быть полезен.\n\nДля одной компании: Проанализируй Airalo, сайт airalo.com."
      : "Example: Find 5 companies in Mexico where my business development experience may be useful.\n\nFor one company: Analyze Airalo, website airalo.com.";
  }
  const resizeQuery = () => {
    query.style.height = "auto";
    query.style.height = `${Math.min(query.scrollHeight, 150)}px`;
  };
  query.addEventListener("input", resizeQuery);
  resizeQuery();

  for (const control of [type, company]) {
    if (!(control instanceof HTMLElement)) continue;
    const container = control.closest(".col-md-4");
    container?.classList.add("search-task-technical-field");
    if (container instanceof HTMLElement) container.hidden = true;
    if (control instanceof HTMLInputElement || control instanceof HTMLSelectElement) {
      control.disabled = true;
    }
  }

  const submit = form.querySelector('button[type="submit"], button:not([type])');
  if (submit instanceof HTMLButtonElement) {
    submit.textContent = russian ? "Найти" : "Search";
    submit.classList.add("search-task-submit");
  }

  form.classList.add("search-task-form");
});

const STAGE_LABELS_RU = {
  queued_for_execution: "Ожидает worker",
  resolving_company: "Ищем официальные сайты",
  company_resolved: "Исследуем компанию",
  research_completed: "Проверяем факты",
  qualification_completed: "Обязательные ограничения подтверждены",
  opportunity_created: "Формируем возможность",
  scoring_completed: "Сопоставляем с профилем",
  contact_research: "Ищем и проверяем публичные контакты",
  contact_research_completed: "Проверяем публичные контакты",
};

function elapsedSeconds(startedAt) {
  if (!startedAt) return 0;
  return Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
}

function taskArticle(task) {
  const byAction = document.querySelector(
    `#search-tasks form[action="/search-tasks/${task.id}/cancel"]`,
  )?.closest("article");
  if (byAction) return byAction;
  return Array.from(document.querySelectorAll("#search-tasks article")).find((article) => {
    const title = article.querySelector("strong")?.textContent?.trim();
    return title === (task.company_name_or_url || task.original_query).trim();
  });
}

function renderLiveTask(task, russian) {
  const article = taskArticle(task);
  if (!(article instanceof HTMLElement)) return;
  let live = article.querySelector(".search-task-live");
  if (!live) {
    live = document.createElement("div");
    live.className = "search-task-live mt-3";
    article.appendChild(live);
  }
  const elapsed = elapsedSeconds(task.started_at);
  const usualSeconds = Math.max(30, Math.min(120, task.result_limit * 20));
  const stage = russian
    ? (STAGE_LABELS_RU[task.current_stage] || "Обрабатываем запрос")
    : (task.current_stage || "Processing").replaceAll("_", " ");
  const found = Math.min(task.found_count, task.result_limit);
  const progress = task.status === "COMPLETED"
    ? 100
    : Math.max(8, Math.min(92, Math.round((found / task.result_limit) * 80 + 12)));
  if (task.status === "RUNNING") {
    live.innerHTML = `
      <div class="d-flex justify-content-between small mb-1">
        <strong>${stage}</strong>
        <span>${russian ? "Прошло" : "Elapsed"}: ${elapsed} ${russian ? "сек." : "sec"}</span>
      </div>
      <div class="progress" role="progressbar" aria-label="Search progress">
        <div class="progress-bar progress-bar-striped progress-bar-animated" style="width:${progress}%"></div>
      </div>
      <div class="small text-secondary mt-1">${russian
        ? `Обычно до ${usualSeconds <= 60 ? "1 минуты" : "2 минут"}. Максимум — 5 минут.`
        : `Usually up to ${usualSeconds <= 60 ? "1 minute" : "2 minutes"}. Maximum: 5 minutes.`}</div>`;
  }
}

async function pollSearchTasks() {
  const section = document.querySelector("#search-tasks");
  if (!section) return;
  try {
    const response = await fetch("/api/v1/search-tasks", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const tasks = await response.json();
    const russian = document.documentElement.lang === "ru";
    const running = tasks.filter((task) => task.status === "RUNNING");
    running.forEach((task) => renderLiveTask(task, russian));
    const staleRunningCard = Array.from(section.querySelectorAll("article")).some((article) => {
      const text = article.textContent || "";
      return text.includes("В работе") || text.toLowerCase().includes("running");
    });
    if (!running.length && staleRunningCard) {
      window.location.reload();
      return;
    }
    if (running.length) window.setTimeout(pollSearchTasks, 2000);
  } catch (_) {
    window.setTimeout(pollSearchTasks, 5000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  for (const form of document.querySelectorAll('#search-tasks form[action$="/cancel"]')) {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button");
      if (button instanceof HTMLButtonElement) {
        button.disabled = true;
        button.textContent = document.documentElement.lang === "ru" ? "Отменяем…" : "Cancelling…";
      }
    });
  }
  pollSearchTasks();
});
