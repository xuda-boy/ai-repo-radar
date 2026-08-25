(() => {
  const statusButton = document.querySelector("#system-status");
  const statusPopover = document.querySelector("#status-popover");
  const liveRegion = document.querySelector("#live-region");

  if (statusButton && statusPopover) {
    statusButton.addEventListener("click", () => {
      const expanded = statusButton.getAttribute("aria-expanded") === "true";
      statusButton.setAttribute("aria-expanded", expanded ? "false" : "true");
      statusPopover.hidden = expanded;
    });

    document.addEventListener("click", (event) => {
      if (statusButton.contains(event.target) || statusPopover.contains(event.target)) return;
      statusButton.setAttribute("aria-expanded", "false");
      statusPopover.hidden = true;
    });
  }

  document.body.addEventListener("htmx:beforeRequest", (event) => {
    const row = event.detail.elt.closest("[data-select-row]");
    if (row) {
      row.parentElement.querySelectorAll("[data-select-row]").forEach((peer) => {
        peer.setAttribute("aria-pressed", peer === row ? "true" : "false");
      });
    }
    const button = event.detail.elt.querySelector?.("button[type='submit']");
    if (button) button.disabled = true;
  });

  document.body.addEventListener("htmx:afterRequest", (event) => {
    const button = event.detail.elt.querySelector?.("button[type='submit']");
    if (button) button.disabled = false;
  });

  document.body.addEventListener("radar:feedbackSaved", (event) => {
    const detail = event.detail || {};
    const pending = Number(detail.pending || 0);
    const syncLabel = document.querySelector("#sync-label");
    const popoverSync = document.querySelector("#popover-sync");
    if (syncLabel) syncLabel.textContent = pending ? `${pending} 条反馈待同步` : "数据已同步";
    if (popoverSync) popoverSync.textContent = pending ? `${pending} 条待处理` : "无待处理";
    if (statusButton) statusButton.classList.toggle("has-pending", pending > 0);
    if (liveRegion) liveRegion.textContent = detail.message || "反馈已保存到本地";
  });

  document.body.addEventListener("htmx:responseError", () => {
    if (liveRegion) liveRegion.textContent = "操作未完成；本地数据没有被覆盖，请重试。";
  });
})();
