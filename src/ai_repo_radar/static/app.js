(() => {
  const statusButton = document.querySelector("#system-status");
  const statusPopover = document.querySelector("#status-popover");
  const mobileStatusButton = document.querySelector("#mobile-status");
  const liveRegion = document.querySelector("#live-region");
  const body = document.body;

  if (statusButton && statusPopover) {
    const toggleStatus = () => {
      const expanded = statusButton.getAttribute("aria-expanded") === "true";
      statusButton.setAttribute("aria-expanded", expanded ? "false" : "true");
      mobileStatusButton?.setAttribute("aria-expanded", expanded ? "false" : "true");
      statusPopover.hidden = expanded;
    };

    statusButton.addEventListener("click", toggleStatus);
    mobileStatusButton?.addEventListener("click", toggleStatus);

    document.addEventListener("click", (event) => {
      if (
        statusButton.contains(event.target)
        || mobileStatusButton?.contains(event.target)
        || statusPopover.contains(event.target)
      ) return;
      statusButton.setAttribute("aria-expanded", "false");
      mobileStatusButton?.setAttribute("aria-expanded", "false");
      statusPopover.hidden = true;
    });
  }

  document.body.addEventListener("htmx:beforeRequest", (event) => {
    const row = event.detail.elt.closest("[data-select-row]");
    if (row) {
      row.parentElement.querySelectorAll("[data-select-row]").forEach((peer) => {
        peer.setAttribute("aria-pressed", peer === row ? "true" : "false");
        peer.classList.toggle("is-selected", peer === row);
      });
    }
    const button = event.detail.elt.querySelector?.("button[type='submit']");
    if (button) button.disabled = true;
  });

  document.body.addEventListener("htmx:afterRequest", (event) => {
    const button = event.detail.elt.querySelector?.("button[type='submit']");
    if (button) button.disabled = false;
  });

  const updateSyncIndicators = (detail) => {
    const pending = Number(detail.pending || 0);
    const configured = detail.configured !== false && detail.configured !== "false";
    const syncLabel = document.querySelector("#sync-label");
    const popoverSync = document.querySelector("#popover-sync");
    const label = detail.label || (configured
      ? (pending ? `${pending} 条反馈待同步` : "数据已同步")
      : (pending ? `${pending} 条反馈仅本地` : "仅本地模式"));
    const freshnessTone = statusButton?.dataset.freshnessTone || "success";
    if (syncLabel && freshnessTone === "success") syncLabel.textContent = label;
    if (popoverSync) {
      popoverSync.textContent = configured
        ? (pending ? `${pending} 条待处理` : "无待处理")
        : (pending ? `${pending} 条仅本地` : "仅本地模式");
    }
    if (statusButton && freshnessTone === "success") {
      statusButton.classList.toggle("has-pending", pending > 0 || !configured);
      statusButton.classList.remove("has-error");
    }
    if (mobileStatusButton && freshnessTone === "success") {
      mobileStatusButton.classList.toggle("has-pending", pending > 0 || !configured);
      mobileStatusButton.classList.remove("has-error");
    }
  };

  const updateDataIndicators = (detail) => {
    const freshnessLabel = document.querySelector("#data-freshness-label");
    const freshnessDetail = document.querySelector("#data-freshness-detail");
    const lastChecked = document.querySelector("#data-last-checked");
    const syncLabel = document.querySelector("#sync-label");
    const tone = detail.tone || "warning";
    const systemTone = detail.systemTone || tone;
    if (freshnessLabel) {
      freshnessLabel.textContent = detail.label || "状态未知";
      freshnessLabel.className = tone;
    }
    if (freshnessDetail && detail.detail) freshnessDetail.textContent = detail.detail;
    if (lastChecked && detail.lastChecked) lastChecked.textContent = detail.lastChecked;
    if (statusButton) {
      statusButton.dataset.freshnessTone = tone;
      statusButton.classList.toggle("has-pending", ["warning", "sample"].includes(systemTone));
      statusButton.classList.toggle("has-error", systemTone === "error");
    }
    if (mobileStatusButton) {
      mobileStatusButton.classList.toggle("has-pending", ["warning", "sample"].includes(systemTone));
      mobileStatusButton.classList.toggle("has-error", systemTone === "error");
    }
    if (syncLabel && detail.systemLabel) syncLabel.textContent = detail.systemLabel;
  };

  document.body.addEventListener("radar:feedbackSaved", (event) => {
    const detail = event.detail || {};
    updateSyncIndicators(detail);
    if (liveRegion) liveRegion.textContent = detail.message || "反馈已保存到本地";
  });

  document.body.addEventListener("radar:feedbackRevoked", (event) => {
    const detail = event.detail || {};
    updateSyncIndicators(detail);
    if (liveRegion) liveRegion.textContent = detail.message || "撤回已保存到本地";
  });

  document.body.addEventListener("radar:syncUpdated", (event) => {
    const detail = event.detail || {};
    updateSyncIndicators(detail);
    if (liveRegion) liveRegion.textContent = detail.message || "反馈同步状态已更新";
  });

  document.body.addEventListener("radar:dataUpdated", (event) => {
    const detail = event.detail || {};
    updateDataIndicators(detail);
    if (liveRegion) liveRegion.textContent = detail.message || "日报更新状态已刷新";
  });

  document.body.addEventListener("htmx:responseError", () => {
    if (liveRegion) liveRegion.textContent = "操作未完成；本地数据没有被覆盖，请重试。";
  });

  document.addEventListener("submit", (event) => {
    const message = event.target?.dataset?.confirm;
    if (!message || window.confirm(message)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  const pollDataStatus = async () => {
    if (document.hidden || body.dataset.autoSync !== "true") return;
    try {
      const response = await fetch(body.dataset.statusUrl || "/data-status", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const detail = await response.json();
      const currentReportDate = body.dataset.reportDate || "";
      if (detail.report_date && detail.report_date !== currentReportDate) {
        window.location.reload();
        return;
      }
      updateDataIndicators({
        label: detail.label,
        tone: detail.tone,
        detail: detail.detail,
        lastChecked: detail.last_checked,
        systemLabel: detail.system_label,
        systemTone: detail.system_tone,
      });
    } catch (_error) {
      // The existing page stays usable; the next interval retries silently.
    }
  };

  if (body.dataset.autoSync === "true") {
    window.setTimeout(pollDataStatus, 5000);
    window.setInterval(pollDataStatus, 60000);
  }

  const projectFilters = [...document.querySelectorAll("[data-kind-filter]")];
  const projectCards = [...document.querySelectorAll("[data-project-kind]")];
  const visibleProjectCount = document.querySelector("#visible-project-count");
  const projectFilterEmpty = document.querySelector("#project-filter-empty");

  const applyProjectFilter = (kind) => {
    let visible = 0;
    projectCards.forEach((card) => {
      const matches = kind === "all" || card.dataset.projectKind === kind;
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    projectFilters.forEach((filter) => {
      const active = filter.dataset.kindFilter === kind;
      filter.classList.toggle("is-active", active);
      filter.setAttribute("aria-pressed", active ? "true" : "false");
    });
    if (visibleProjectCount) visibleProjectCount.textContent = `${visible} 个结果`;
    if (projectFilterEmpty) projectFilterEmpty.hidden = visible !== 0;

    const selected = projectCards.find((card) => card.classList.contains("is-selected"));
    if (selected?.hidden) {
      projectCards.find((card) => !card.hidden)?.click();
    }
  };

  projectFilters.forEach((filter) => {
    filter.setAttribute("aria-pressed", filter.classList.contains("is-active") ? "true" : "false");
    filter.addEventListener("click", () => applyProjectFilter(filter.dataset.kindFilter || "all"));
  });
})();
