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
    var chips = Array.prototype.map.call(list.querySelectorAll("[data-chip]"), function (c) { return c.dataset.chip; });
    list.querySelectorAll("[data-row]").forEach(function (r) {
      var keys = " " + (r.dataset.keys || "") + " ";
      var ok = (!q || r.dataset.search.indexOf(q) !== -1) &&
               chips.every(function (k) { return keys.indexOf(" " + k + " ") !== -1; }) &&
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
  function onFilterInput(e) {
    var list = e.target.closest("[data-list]");
    if (list && e.target.matches("[data-filter-text], [data-filter-select]")) applyFilter(list);
  }
  // A select fires "change" everywhere and "input" only in some browsers; listen for both.
  document.addEventListener("input", onFilterInput);
  document.addEventListener("change", onFilterInput);
  // Tags in the search bar: typed (Enter), picked from the suggestions, or clicked on a row.
  function tagInput(list) { return list && list.querySelector("[data-taginput]"); }
  function tagMap(box) { try { return JSON.parse(box.dataset.tags || "{}"); } catch (err) { return {}; } }
  function addChip(list, key) {
    var box = tagInput(list); if (!box || !key) return;
    var chips = box.querySelector("[data-chips]");
    if (chips.querySelector('[data-chip="' + key + '"]')) return;
    var map = tagMap(box), name = Object.keys(map).find(function (n) { return map[n] === key; }) || key;
    var chip = document.createElement("span");
    chip.className = "chip-tag"; chip.dataset.chip = key; chip.textContent = name;
    var x = document.createElement("button"); x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Remove " + name);
    chip.appendChild(x); chips.appendChild(chip);
    applyFilter(list);
  }
  function lookup(box, text) {
    var map = tagMap(box), t = text.trim().toLowerCase();
    var name = Object.keys(map).find(function (n) { return n.toLowerCase() === t || map[n].toLowerCase() === t; });
    return name ? map[name] : null;
  }
  document.addEventListener("keydown", function (e) {
    var box = e.target.closest("[data-taginput]"); if (!box || e.target.tagName !== "INPUT") return;
    var list = box.closest("[data-list]");
    if (e.key === "Enter") {
      e.preventDefault();
      var key = lookup(box, e.target.value);
      if (key) { e.target.value = ""; addChip(list, key); }
    } else if (e.key === "Backspace" && !e.target.value) {
      var last = box.querySelector("[data-chip]:last-of-type"); if (last) { last.remove(); applyFilter(list); }
    }
  });
  document.addEventListener("input", function (e) {
    var box = e.target.closest("[data-taginput]"); if (!box) return;
    if (e.inputType && e.inputType !== "insertReplacementText") return;   // a pick from the suggestions
    var key = lookup(box, e.target.value);
    if (key) { e.target.value = ""; addChip(box.closest("[data-list]"), key); }
  });
  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-tag]");
    if (add) { e.preventDefault(); addChip(add.closest("[data-list]"), add.dataset.addTag); return; }
    var x = e.target.closest(".chip-tag button");
    if (x) { var l = x.closest("[data-list]"); x.parentNode.remove(); applyFilter(l); return; }
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

// Review queue: keyboard shortcuts, and the next open suggestion once one is decided.
(function () {
  if (!document.body.hasAttribute("data-review")) return;
  function go(sel) { var a = document.querySelector(sel); if (a) window.location = a.getAttribute("href"); }
  function nextOpen() {
    var n = document.querySelector("[data-next-open]");
    window.location = n ? n.getAttribute("data-next-open") : "/review";
  }
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
    var k = e.key.toLowerCase();
    var actions = document.querySelector('#detail [id^="actions-"]');
    if (k === "a" && actions) { var acc = actions.querySelector("button.primary"); if (acc) { e.preventDefault(); acc.click(); } }
    else if (k === "d" && actions) {
      var dis = Array.prototype.find.call(actions.querySelectorAll("button"), function (b) { return /dismiss/i.test(b.textContent); });
      if (dis) { e.preventDefault(); dis.click(); }
    }
    else if (k === "j" || e.key === "ArrowRight") { e.preventDefault(); go("[data-key-next]"); }
    else if (k === "k" || e.key === "ArrowLeft") { e.preventDefault(); go("[data-key-prev]"); }
  });
  // After accept or dismiss swaps in its status, move on (a raised conviction review stays in view).
  document.addEventListener("htmx:afterSwap", function (e) {
    var t = e.detail.target;
    if (!t || !/^actions-/.test(t.id || "")) return;
    var swapped = document.getElementById(t.id) || t;
    if (swapped.querySelector(".flash.err")) return;
    setTimeout(nextOpen, 700);
  });
})();

// Criteria: example editing only. Nothing is sent to the server; a reload discards every change.
(function () {
  function markDirty(root) {
    var d = root.querySelector("[data-dirty]"); if (d) d.hidden = false;
    var b = root.querySelector('[data-act="discard"]'); if (b) b.hidden = false;
  }
  function renumber(root) {
    var items = root.querySelectorAll("[data-rule]");
    items.forEach(function (li, i) { li.querySelector(".rid").textContent = (i + 1) + "."; });
    var c = root.querySelector("[data-count]");
    if (c) c.textContent = items.length + " of " + root.dataset.max;
    var add = root.querySelector("form.add-rule");
    if (add) add.querySelector("button").disabled = items.length >= +root.dataset.max;
  }
  function ruleItem(text) {
    var li = document.createElement("li");
    li.setAttribute("data-rule", ""); li.className = "draft";
    li.innerHTML = '<span class="rid"></span><span class="rtext"></span><span class="rule-tools">' +
      '<button type="button" class="ghost" data-act="edit">Edit</button>' +
      '<button type="button" class="ghost danger" data-act="delete">Remove</button></span>';
    li.querySelector(".rtext").textContent = text;
    return li;
  }
  document.addEventListener("submit", function (e) {
    var form = e.target.closest('form[data-act="add-rule"]');
    if (!form) return;
    e.preventDefault();
    var root = form.closest("[data-crit-editor]"), input = form.querySelector("input");
    var text = input.value.trim();
    if (!text || root.querySelectorAll("[data-rule]").length >= +root.dataset.max) return;
    root.querySelector("[data-rules]").appendChild(ruleItem(text));
    input.value = ""; renumber(root); markDirty(root);
  });
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-act]");
    if (!btn || btn.tagName === "FORM") return;
    var act = btn.getAttribute("data-act");
    var root = btn.closest("[data-crit-editor]");
    if (act === "discard") { window.__discarding = true; window.location.reload(); return; }
    if (act === "delete" && root) { btn.closest("[data-rule]").remove(); renumber(root); markDirty(root); return; }
    if (act === "edit" && root) {
      var li = btn.closest("[data-rule]"), span = li.querySelector(".rtext");
      if (!li.querySelector("input")) {
        var inp = document.createElement("input"); inp.type = "text"; inp.value = span.textContent;
        span.hidden = true; span.after(inp); inp.focus(); btn.textContent = "Save";
        inp.addEventListener("keydown", function (k) { if (k.key === "Enter") { k.preventDefault(); btn.click(); } });
      } else {
        var inp2 = li.querySelector("input");
        var next = inp2.value.trim();
        if (next && next !== span.textContent) { span.textContent = next; li.classList.add("draft"); markDirty(root); }
        inp2.remove(); span.hidden = false; btn.textContent = "Edit";
      }
      return;
    }
    if (act === "add-category") {
      var sec = btn.closest("[data-crit-section]"), cards = sec.querySelector(".crit-cards");
      var card = document.createElement("div"); card.className = "crit-card draft";
      card.innerHTML = '<input type="text" placeholder="Category name" aria-label="Category name">' +
        '<textarea rows="3" placeholder="What this category means" aria-label="Definition"></textarea>' +
        '<span class="actions"><button type="button" class="primary" data-act="keep-category">Add</button>' +
        '<button type="button" class="ghost" data-act="drop-category">Cancel</button></span>';
      cards.appendChild(card); card.querySelector("input").focus(); return;
    }
    if (act === "drop-category") { btn.closest(".crit-card").remove(); return; }
    if (act === "keep-category") {
      var c = btn.closest(".crit-card"), name = c.querySelector("input").value.trim(), def = c.querySelector("textarea").value.trim();
      if (!name) { c.querySelector("input").focus(); return; }
      c.innerHTML = "<b></b><span class='small muted clamp3'></span><span class='tag warn' style='justify-self:start'>Example, not saved</span>";
      c.querySelector("b").textContent = name; c.querySelector("span").textContent = def || "No definition yet.";
    }
  });
  // A changed page warns before it is left, since nothing is kept.
  window.addEventListener("beforeunload", function (e) {
    if (!window.__discarding && document.querySelector(".crit-card.draft, li.draft")) { e.preventDefault(); e.returnValue = ""; }
  });
})();

// Criteria: "Add a new category" (example only) puts a card in the chosen section of the overview.
(function () {
  var form = document.querySelector("[data-new-category]");
  if (!form) return;
  function open() {
    if (!document.querySelector("[data-crit-section]")) { window.location = "/criteria#new"; return; }
    form.hidden = false; form.scrollIntoView({ behavior: "smooth", block: "center" }); form.querySelector("input").focus();
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest('[data-act="open-new-category"], [data-act="close-new-category"]');
    if (!b) return;
    if (b.getAttribute("data-act") === "open-new-category") open(); else { form.reset(); form.hidden = true; }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var name = form.name.value.trim(), def = form.definition.value.trim();
    if (!name) return;
    var sec = document.getElementById(form.section.value);
    var card = document.createElement("div");
    card.className = "crit-card draft";
    card.innerHTML = "<b></b><span class='small muted clamp3'></span><span class='tag warn' style='justify-self:start'>Example, not saved</span>";
    card.querySelector("b").textContent = name;
    card.querySelector("span").textContent = def || "No definition yet.";
    sec.querySelector(".crit-cards").appendChild(card);
    form.reset(); form.hidden = true;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  if (location.hash === "#new") open();
})();

// Saving from any edit panel closes it and returns it to rest, whether or not anything changed.
document.addEventListener("submit", function (e) {
  var panel = e.target.closest("details.tool, details.more");
  if (panel) setTimeout(function () { panel.open = false; }, 0);
});

// Live trace: expand or collapse every step at once.
document.addEventListener("click", function (e) {
  var b = e.target.closest('[data-act="expand-steps"]');
  if (!b) return;
  var trace = b.closest("[data-trace]"), steps = trace.querySelectorAll("li.step > details");
  var open = b.textContent.trim() === "Expand all";
  steps.forEach(function (d) { d.open = open; });
  b.textContent = open ? "Collapse all" : "Expand all";
});
