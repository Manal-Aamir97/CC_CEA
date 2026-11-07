// Small progressive enhancements. Every page works without JavaScript.

// Ask before destructive actions (forms marked with data-confirm)
document.addEventListener("submit", (event) => {
  const form = event.submitter && event.submitter.form ? event.submitter.form : event.target;
  const message = form.dataset ? form.dataset.confirm : null;
  if (message && !window.confirm(message)) event.preventDefault();
});

// Apply expense filters as soon as a dropdown changes
document.querySelectorAll(".filters select").forEach((el) => {
  el.addEventListener("change", () => el.form.submit());
});

// Let success messages fade after a few seconds
setTimeout(() => {
  document.querySelectorAll(".flash-success").forEach((el) => {
    el.style.transition = "opacity .6s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 700);
  });
}, 4000);
