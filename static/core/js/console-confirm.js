// <form data-confirm-off="what else goes off">: asks before the form is sent (console, features
// that others rely on).
const dialog = document.querySelector("[data-confirm-off-dialog]");

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!dialog || !form.dataset.confirmOff) return;
  if (form.dataset.confirmed) return;
  event.preventDefault();
  dialog.querySelector("[data-confirm-off-text]").textContent = form.dataset.confirmOff;
  dialog.addEventListener("close", () => {
    if (dialog.returnValue !== "confirm") return;
    form.dataset.confirmed = "true";
    form.requestSubmit();
  }, { once: true });
  dialog.showModal();
});
