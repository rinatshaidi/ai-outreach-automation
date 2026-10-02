document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") return;
  if (form.querySelector('input[name="csrf_token"]')) return;
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (!token) return;
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "csrf_token";
  input.value = token;
  form.appendChild(input);
});

document.body.addEventListener("htmx:configRequest", (event) => {
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (token) event.detail.headers["X-CSRF-Token"] = token;
});
