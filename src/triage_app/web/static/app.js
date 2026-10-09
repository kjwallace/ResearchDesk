// Small progressive enhancements; every page works without this file.
(function () {
  // The company picker in the tab bar opens that company's page.
  document.addEventListener("change", function (e) {
    var sel = e.target.closest("select[data-nav]");
    if (sel && sel.value) window.location = sel.dataset.nav + sel.value;
  });

  // A row that loads into the detail pane becomes the selected row.
  document.addEventListener("htmx:beforeRequest", function (e) {
    var row = e.target.closest(".row[data-pane], .row [data-pane]");
    if (!row) return;
    row = row.closest(".row");
    var list = row.closest("[data-list]") || document;
    list.querySelectorAll(".row.on").forEach(function (r) { r.classList.remove("on"); });
    row.classList.add("on");
  });
  // On narrow screens the pane sits below the list; bring it into view.
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "pane" && window.matchMedia("(max-width: 1100px)").matches && e.detail.requestConfig &&
        e.detail.requestConfig.triggeringEvent && e.detail.requestConfig.triggeringEvent.type === "click") {
      e.target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  // Client-side filtering of a long list: search text, a select, and sub-tabs.
  function applyFilter(list) {
    var q = (list.querySelector("[data-filter-text]") || {}).value || "";
    q = q.trim().toLowerCase();
    var sel = list.querySelector("[data-filter-select]");
    var key = sel ? sel.value : "";
    var tab = list.querySelector("[data-filter-tab].on");
    var tabKey = tab ? tab.dataset.filterTab : "";
    var shown = 0;
    list.querySelectorAll("[data-row]").forEach(function (r) {
      var ok = (!q || r.dataset.search.indexOf(q) !== -1) &&
               (!key || (" " + r.dataset.keys + " ").indexOf(" " + key + " ") !== -1) &&
               (!tabKey || (" " + r.dataset.keys + " ").indexOf(" " + tabKey + " ") !== -1);
      r.hidden = !ok;
      if (ok) shown++;
    });
    list.querySelectorAll("details.group").forEach(function (g) {
      var any = g.querySelector("[data-row]:not([hidden])");
      g.hidden = !any && !!g.querySelector("[data-row]");
    });
    var out = list.querySelector("[data-shown]");
    if (out) out.textContent = shown;
  }
  document.addEventListener("input", function (e) {
    var list = e.target.closest("[data-list]");
    if (list && e.target.matches("[data-filter-text], [data-filter-select]")) applyFilter(list);
  });
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-filter-tab]");
    if (!t) return;
    var list = t.closest("[data-list]");
    list.querySelectorAll("[data-filter-tab]").forEach(function (x) {
      x.classList.toggle("on", x === t);
      x.setAttribute("aria-pressed", x === t ? "true" : "false");
    });
    applyFilter(list);
  });
})();
