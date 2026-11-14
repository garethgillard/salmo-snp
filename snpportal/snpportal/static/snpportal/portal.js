/* snpportal: small progressive enhancements; every page works without them. */
(function () {
  "use strict";

  // Download the SVG inside an element as a PNG at 2x: <button data-png="element id" data-name="file name">
  function savePng(svg, name) {
    var box = svg.viewBox && svg.viewBox.baseVal, w = (box && box.width) || svg.clientWidth, h = (box && box.height) || svg.clientHeight;
    var img = new Image();
    img.onload = function () {
      var canvas = document.createElement("canvas");
      canvas.width = w * 2;
      canvas.height = h * 2;
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name + ".png";
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      });
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(svg));
  }

  document.addEventListener("click", function (e) {
    var copy = e.target.closest("[data-copy]");  // <button data-copy="text">: copy to the clipboard
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(copy.getAttribute("data-copy")).then(function () {
        var label = copy.innerHTML;  // text or an icon
        copy.textContent = "Copied";
        setTimeout(function () { copy.innerHTML = label; }, 1200);
      });
    }
    var png = e.target.closest("[data-png]");
    if (png) {
      var svg = document.getElementById(png.getAttribute("data-png")).querySelector("svg");
      if (svg) savePng(svg, png.getAttribute("data-name") || "figure");
    }
  });

  // Menus (<details class="sp-menu|sp-dlmenu">) close on a click outside them or on Escape.
  function closeMenus(except) {
    document.querySelectorAll("details.sp-menu[open], details.sp-dlmenu[open]").forEach(function (d) {
      if (d !== except) d.removeAttribute("open");
    });
  }
  document.addEventListener("click", function (e) { closeMenus(e.target.closest && e.target.closest("details.sp-menu, details.sp-dlmenu")); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(null); });

  // A link to #id opens the closed <details> that is, or holds, that id (Help questions).
  function openTarget() {
    var id = decodeURIComponent(location.hash.slice(1)), el = id && document.getElementById(id);
    for (var d = el; d; d = d.parentElement) if (d.tagName === "DETAILS") d.open = true;
    if (el) el.scrollIntoView();
  }
  window.addEventListener("hashchange", openTarget);
  openTarget();

  // Score: '#gwas' (older links to its GWAS section), '#paste' or '#regions' selects that tab, as ?input= does.
  function showTab() {
    var tab = document.getElementById("tab-" + location.hash.slice(1));
    if (tab && tab.getAttribute("data-bs-toggle") === "tab" && window.bootstrap) bootstrap.Tab.getOrCreateInstance(tab).show();
  }
  window.addEventListener("hashchange", showTab);
  showTab();

  // Drag-and-drop onto <div class="sp-drop" data-drop-for="file input id">; shows the chosen file's name.
  document.querySelectorAll("[data-drop-for]").forEach(function (zone) {
    var input = document.getElementById(zone.getAttribute("data-drop-for"));
    var label = zone.querySelector("[data-drop-label]");
    function show() { if (label && input.files.length) label.textContent = input.files[0].name; }
    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function (e) { e.preventDefault(); zone.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.remove("over"); });
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
    });
    input.addEventListener("change", show);
  });

  // j/k move between table rows that open a card (rows with [data-card]); Enter opens it. With a card open they step
  // to the next or previous row's card instead, and x takes the card's SNP out of the selection (or puts it back).
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, select, textarea") || ["j", "k", "x"].indexOf(e.key) < 0) return;
    if (document.querySelector("#drawer.sp-wide")) return;  // the card's locus browser is open over the page
    var step = document.querySelector({j: "#drawer [data-next]", k: "#drawer [data-prev]", x: "#drawer [data-pick]"}[e.key]);
    if (step || document.getElementById("drawer")) { if (step) step.click(); return; }
    if (e.key === "x") return;
    var rows = Array.prototype.slice.call(document.querySelectorAll("tr[data-card]"));
    if (!rows.length) return;
    var i = rows.indexOf(document.activeElement.closest && document.activeElement.closest("tr[data-card]"));
    var next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "j" ? 1 : -1)))];
    var link = next.querySelector("a.sp-snp") || next.querySelector("a");
    if (link) link.focus();
  });
})();

/* results: a click anywhere on a table row opens its evidence card (via the row's SNP link, which htmx loads into
   #card), and the open row is highlighted. */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("tr[data-card]");
    var link = row && (row.querySelector("a.sp-snp") || row.querySelector("a[hx-get]"));  // the SNP's link, not the selector
    if (!link) return;
    if (!e.target.closest("a, button, input, select, label, summary")) link.click();
    document.querySelectorAll("tr.sp-selected").forEach(function (r) { r.classList.remove("sp-selected"); });
    row.classList.add("sp-selected");
  });
  // On narrow screens the card sits below the table: bring it into view once loaded.
  document.addEventListener("htmx:afterSwap", function (e) {
    var card = e.detail && e.detail.target;
    if (!card || card.id !== "card") return;
    var box = card.getBoundingClientRect();
    if (box.top > window.innerHeight || box.bottom < 0) card.scrollIntoView({behavior: "smooth", block: "start"});
  });
})();
/* end results */

/* confirm: a form with data-confirm asks first in a small dialog (Cancel, or the red data-confirm-ok button) instead of
   the browser's confirm box; a click outside or Esc cancels. Without JavaScript the form just submits. */
(function () {
  "use strict";
  var dialog, pending;
  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "sp-confirm";
    dialog.setAttribute("aria-labelledby", "sp-confirm-text");
    dialog.innerHTML = '<div><div class="sp-confirm-body"><span class="sp-confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6' +
      'M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg></span><p id="sp-confirm-text"></p></div>' +
      '<div class="sp-confirm-btns"><button type="button" class="btn btn-sm btn-outline-secondary" data-no>Cancel</button>' +
      '<button type="button" class="btn btn-sm btn-danger" data-yes></button></div></div>';
    (document.querySelector(".sp") || document.body).appendChild(dialog);
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog || e.target.closest("[data-no]")) dialog.close();  // the dialog itself: the backdrop
      if (!e.target.closest("[data-yes]")) return;
      dialog.close();
      pending.form.setAttribute("data-confirmed", "");
      if (pending.by) pending.form.requestSubmit(pending.by); else pending.form.requestSubmit();
    });
  }
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.hasAttribute || !form.hasAttribute("data-confirm")) return;
    if (form.hasAttribute("data-confirmed")) { form.removeAttribute("data-confirmed"); return; }
    e.preventDefault();
    if (!dialog) build();
    pending = {form: form, by: e.submitter};
    dialog.querySelector("p").textContent = form.getAttribute("data-confirm");
    dialog.querySelector("[data-yes]").textContent = form.getAttribute("data-confirm-ok") || "Delete";
    dialog.showModal();
  }, true);
})();

/* tour: the arrows, the dots, the arrow keys and a click on the slide (its right half goes on, its left half back)
   switch slides without reloading (the arrows and dots are ?slide=N links, which work without JavaScript). Hovering a
   half lights its arrow. The counter is a live region; focus inside a slide that goes moves to the new slide's title. */
(function () {
  "use strict";
  var tour = document.querySelector("[data-tour]");
  if (!tour) return;
  var slides = Array.prototype.slice.call(tour.querySelectorAll(".sp-slide"));
  var dots = Array.prototype.slice.call(tour.querySelectorAll(".sp-tour-dots a"));
  var prev = tour.querySelector("[data-tour-prev]"), next = tour.querySelector("[data-tour-next]");
  var stage = tour.querySelector(".sp-tour-stage"), deck = tour.querySelector("[data-tour-deck]");
  var count = tour.querySelector("[data-tour-count]");
  var at = Math.max(0, slides.findIndex(function (s) { return !s.hidden; }));

  function show(i) {
    if (i < 0 || i >= slides.length || i === at) return;
    var focusIn = slides[at].contains(document.activeElement), first = i === 0, last = i === slides.length - 1;
    slides[at].hidden = true;
    dots[at].removeAttribute("aria-current");
    slides[i].hidden = false;
    slides[i].classList.remove("sp-in");
    void slides[i].offsetWidth;  // restart the fade-in
    slides[i].classList.add("sp-in");
    dots[i].setAttribute("aria-current", "step");
    at = i;
    if (first) {
      if (document.activeElement === prev) next.focus();
      prev.removeAttribute("href");
      prev.setAttribute("aria-disabled", "true");
    } else {
      prev.href = "?slide=" + i;
      prev.removeAttribute("aria-disabled");
    }
    prev.classList.toggle("disabled", first);
    next.href = last ? next.getAttribute("data-end-href") : "?slide=" + (i + 2);
    next.setAttribute("aria-label", last ? "Start scoring" : "Next slide");
    next.classList.toggle("sp-tour-end", last);
    count.textContent = "Slide " + (i + 1) + " of " + slides.length;
    history.replaceState(null, "", "?slide=" + (i + 1));
    if (focusIn) slides[i].querySelector("h2").focus();
  }

  function side(e) {  // the half of the slide under the pointer, if there is a slide that way
    var box = deck.getBoundingClientRect(), right = e.clientX > box.left + box.width / 2;
    return right ? (at < slides.length - 1 ? 1 : 0) : (at > 0 ? -1 : 0);
  }
  function plain(e) {  // a click on the slide itself, not on a link, button or form, nor ending a text selection
    return !e.target.closest("a, button, input, select, textarea, label, summary") && !String(window.getSelection());
  }

  tour.addEventListener("click", function (e) {
    var a = e.target.closest("[data-tour-prev], [data-tour-next], .sp-tour-dots a");
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    if (a && (a.getAttribute("href") || "").charAt(0) === "?") {
      e.preventDefault();
      show(a === prev ? at - 1 : a === next ? at + 1 : dots.indexOf(a));
    } else if (!a && deck.contains(e.target) && plain(e) && side(e)) {
      show(at + side(e));
    }
  });
  deck.addEventListener("mousemove", function (e) {
    var way = plain(e) ? side(e) : 0;
    stage.setAttribute("data-side", way > 0 ? "next" : way < 0 ? "prev" : "");
  });
  deck.addEventListener("mouseleave", function () { stage.setAttribute("data-side", ""); });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, select, textarea, [contenteditable]")) return;
    if (e.key === "ArrowLeft") show(at - 1);
    if (e.key === "ArrowRight") show(at + 1);
  });
})();
/* end tour */

/* table: the filter dropdowns (details.sp-dd) stay open while their ticks apply (each change swaps #results); a click
   outside one closes it; a list's 'Any' box and its ticks exclude each other; a column's panel is placed on the page.
   Escape, its tab or a click outside closes the card drawer. */
(function () {
  "use strict";
  var open = [];
  document.addEventListener("htmx:beforeSwap", function () {
    open = Array.prototype.map.call(document.querySelectorAll("details.sp-dd[open]"), function (d) { return d.id; });
  });
  document.addEventListener("htmx:afterSettle", function () {
    open.forEach(function (id) { var d = document.getElementById(id); if (d) d.open = true; });
    open = [];
  });
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.sp-dd[open]").forEach(function (d) { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("change", function (e) {  // 'Any' clears a list's ticks, a tick clears 'Any' (capture: before htmx sends)
    var box = e.target, list = box.type === "checkbox" && box.closest && box.closest(".sp-dd-list");
    if (!list) return;
    var ticks = list.querySelectorAll("input[type=checkbox][name]"), any = list.querySelector("[data-any]");
    if (box === any) {
      any.checked = true;
      ticks.forEach(function (b) { b.checked = false; });
    } else if (any) {
      any.checked = !list.querySelector("input[type=checkbox][name]:checked");
    }
  }, true);
  function place(d) {  // a column's filter panel, on the page under its funnel: the table's scroll box would clip it
    var panel = d.querySelector(".sp-dd-panel"), r = d.querySelector("summary").getBoundingClientRect();
    panel.style.position = "fixed";
    panel.style.top = (r.bottom + 4) + "px";
    panel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - panel.offsetWidth - 8)) + "px";
  }
  document.addEventListener("toggle", function (e) {
    if (e.target.classList && e.target.classList.contains("sp-dd-col") && e.target.open) place(e.target);
  }, true);
  ["scroll", "resize"].forEach(function (name) {
    window.addEventListener(name, function () { document.querySelectorAll("details.sp-dd-col[open]").forEach(place); }, true);
  });
  document.addEventListener("click", function (e) {  // a click outside the card closes it; a row's click opens that row's card
    var drawer = document.getElementById("drawer"), t = e.target;
    if (!drawer || drawer.contains(t) || !t.closest || t.closest("tr[data-card], a, button, input, select, label, summary, .sp-dd-panel")) return;
    var close = drawer.querySelector("[data-close]");
    if (close) close.click();
  });
  // The card's sections (details.sp-cs) stay folded as the reader left them, card after card (this tab only).
  function folds() {
    try { return JSON.parse(sessionStorage.getItem("sp-folds") || "[]"); } catch (err) { return []; }
  }
  function refold() {
    folds().forEach(function (id) { var d = document.getElementById(id); if (d && d.classList.contains("sp-cs")) d.open = false; });
  }
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains("sp-cs")) return;
    var f = folds().filter(function (id) { return id !== d.id; });
    if (!d.open) f.push(d.id);
    try { sessionStorage.setItem("sp-folds", JSON.stringify(f)); } catch (err) { /* private mode: folds reset per card */ }
  }, true);
  document.addEventListener("htmx:afterSwap", refold);
  refold();
  document.addEventListener("keydown", function (e) {  // Escape closes the card's locus browser, else the card drawer
    if (e.key !== "Escape") return;
    if (wide()) { back(); return; }
    var close = document.querySelector("#drawer [data-close]");
    if (close) close.click();
  });
  document.addEventListener("input", function (e) {  // a slider shows its value as it moves; the form applies it on release
    var out = e.target.type === "range" && e.target.closest("label") && e.target.closest("label").querySelector("output");
    if (out) out.textContent = e.target.value;
  });
  /* The card's 'Open in the locus browser' opens it over the whole page, in the drawer (base_embed.html in a frame).
     'Back to the card', Esc (here or in the frame) and the browser's Back all return to the card as it was; a lollipop
     of another SNP of the list opens that SNP's card. Opening adds one Back step; the frame adds none. */
  var pending = null;  // what to do once that Back step has been taken
  function wide() { var d = document.getElementById("drawer"); return d && d.classList.contains("sp-wide") ? d : null; }
  function shut(d) {
    d.classList.remove("sp-wide");
    var pane = d.querySelector(".sp-locus-pane"), link = d.querySelector("[data-locus]");
    if (pane) pane.hidden = true;
    if (link) link.focus();
  }
  function back(then) {
    var d = wide();
    if (d) shut(d);
    if (history.state && history.state.spLocus) { pending = then || function () {}; history.back(); } else if (then) then();
  }
  window.addEventListener("popstate", function (e) {
    var d = wide();
    if (!d && !pending) return;
    e.stopImmediatePropagation();  // not htmx's history restore: the page under the card has not changed
    if (d) shut(d);
    var then = pending;
    pending = null;
    if (then) then();
  }, true);
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("#drawer [data-locus], #drawer [data-back]");
    if (!t || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (t.hasAttribute("data-back")) { back(); return; }
    var d = t.closest("#drawer"), pane = d.querySelector(".sp-locus-pane"), frame = pane && pane.querySelector("iframe");
    if (!frame) return;
    e.preventDefault();
    if (!frame.getAttribute("src")) frame.setAttribute("src", frame.getAttribute("data-src"));  // kept when it is opened again
    pane.hidden = false;
    d.classList.add("sp-wide");
    history.pushState({spLocus: true}, "");
    pane.querySelector("[data-back]").focus();
  });
  window.addEventListener("message", function (e) {
    var m = e.data || {};
    if (e.origin !== location.origin || !wide()) return;
    if (m.sp === "back") back();
    if (m.sp === "card") {  // another SNP's card: in this drawer when it belongs to these results
      var here = location.pathname.match(/\/results\/([0-9a-f-]+)\//);
      if (!here || here[1] !== m.key || !window.htmx) { location.href = m.url; return; }
      back(function () {
        var u = new URL(location.href);
        u.searchParams.set("snp", m.row);
        htmx.ajax("GET", u.pathname + u.search, {target: "#results", select: "#results", swap: "outerHTML"})
          .then(function () { history.replaceState(history.state, "", u.pathname + u.search); });  // a reload keeps this card
      });
    }
  });
})();
/* end table */
/* browser: the locus browser's groups open and close in place; Expand all / Collapse all reach every group. The open
   groups go into the URL (?open=), the region form and every move, so a link or a move keeps them. */
(function () {
  "use strict";
  function groups() { return Array.prototype.slice.call(document.querySelectorAll("#locus-view [data-group]")); }
  function opened() {  // open groups on the page, and those the URL lists that aren't loaded yet (an assay still loading)
    var here = groups().map(function (g) { return g.getAttribute("data-group"); });
    var listed = (new URL(location.href).searchParams.get("open") || "").split(",").filter(function (n) { return n && here.indexOf(n) < 0; });
    return groups().filter(function (g) { return g.classList.contains("open"); }).map(function (g) { return g.getAttribute("data-group"); })
      .concat(listed).join(",");
  }
  function set(g, open) {
    g.classList.toggle("open", open);
    var b = g.querySelector(":scope > .sp-grp-h .sp-tog");
    if (b) b.setAttribute("aria-expanded", open);
    if (open && window.htmx) {  // the functional assays load when their section first opens
      g.querySelectorAll(":scope > .sp-more-rows > .sp-assay-slot").forEach(function (slot) { htmx.trigger(slot, "sp-open"); });
    }
  }
  function sync() {
    var list = opened(), input = document.querySelector("#locus-view [data-open]");
    if (input) input.value = list;
    var url = new URL(location.href);
    if (list) url.searchParams.set("open", list); else url.searchParams.delete("open");
    history.replaceState(history.state, "", url);
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("#locus-view .sp-tog");
    if (t) {
      var g = t.closest("[data-group]");
      set(g, !g.classList.contains("open"));
      sync();
      return;
    }
    var all = e.target.closest && e.target.closest("#locus-view [data-all]");
    if (all) {
      groups().forEach(function (g) { set(g, all.getAttribute("data-all") === "open"); });
      sync();
    }
  });
  document.addEventListener("htmx:configRequest", function (e) {  // moves and assay retries carry the open groups (slots have theirs)
    if (e.detail.elt.closest && e.detail.elt.closest("#locus-view .sp-bctl, #locus-view [data-retry]")) e.detail.parameters.open = opened();
  });
  document.addEventListener("htmx:pushedIntoHistory", function () { if (document.querySelector("#locus-view [data-group]")) sync(); });
  /* the marker line: follows the mouse over the track column (not the chromosome) and names the base under it on the
     ruler. A click pins it to that base (blue): it then moves and zooms with the tracks, waits off-screen when its
     base leaves the window and stays through every move; the next click lets it go. A drag never pins or frees it.
     The [data-line] button turns the line off (and frees a pinned one). */
  var cur = null, held = null, off = false, last = null;  // held: {chrom, base} of the pinned line
  try { off = localStorage.getItem("sp-line") === "off"; } catch (e) { /* storage blocked: the line starts on */ }
  function at(e) {  // the tracks under the mouse and its x on the axis, or null
    var t = e.target && e.target.closest ? e.target : null, box = t && !t.closest(".sp-trk-chr") && t.closest("#locus-view .sp-tracks");
    var ax = box && box.querySelector(".sp-ax"), r = ax && ax.getBoundingClientRect(), x = r ? e.clientX - r.left : -1;
    return r && x >= 0 && x <= r.width ? {box: box, ax: ax, r: r, x: x} : null;
  }
  function seen(box) { return box.spView || {x: 0, w: 1000}; }  // the user units the tracks show now (preview)
  function baseAt(p) {  // the 1-based base under x, wherever the tracks have been moved to
    var a = +p.box.getAttribute("data-start"), b = +p.box.getAttribute("data-end"), v = seen(p.box);
    return a + 1 + Math.floor((p.x / p.r.width * v.w + v.x) / 1000 * (b - a));
  }
  function hide() { if (cur) { cur.classList.remove("sp-cur", "sp-held"); cur = null; } }
  function show(box, base) {  // the line at `base`, or none while that base is outside what the tracks show
    var ax = box.querySelector(".sp-ax"), r = ax.getBoundingClientRect(), v = seen(box);
    var a = +box.getAttribute("data-start"), b = +box.getAttribute("data-end");
    var x = ((base - 0.5 - a) / (b - a) * 1000 - v.x) / v.w * r.width;
    if (cur && cur !== box) hide();
    if (x < 0 || x > r.width) { box.classList.remove("sp-cur"); return; }
    box.style.setProperty("--sp-x", (r.left - ax.parentNode.getBoundingClientRect().left + x) + "px");
    box.style.setProperty("--sp-pos", JSON.stringify(base.toLocaleString("en")));
    box.classList.add("sp-cur");
    box.classList.toggle("sp-held", !!held);
    cur = box;
  }
  function follow(e) {
    var p = at(e);
    if (p) show(p.box, baseAt(p)); else hide();
  }
  function line(box) {  // after the tracks moved: the pinned line at its base, else the line under the resting mouse
    if (off) return;
    if (held) { if (box.getAttribute("data-chrom") === held.chrom) show(box, held.base); else hide(); }
    else if (last) follow({target: document.elementFromPoint(last.x, last.y), clientX: last.x});
  }
  function buttons() {
    document.querySelectorAll("#locus-view [data-line]").forEach(function (b) { b.classList.toggle("active", !off); b.setAttribute("aria-pressed", !off); });
  }
  document.addEventListener("mousemove", function (e) {
    last = {x: e.clientX, y: e.clientY};
    if (cur && !cur.isConnected) cur = null;  // a move swapped the view
    if (!off && !held) follow(e);
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("#locus-view [data-line]")) {
      off = !off;
      held = null;
      hide();
      try { localStorage.setItem("sp-line", off ? "off" : "on"); } catch (err) { /* not remembered */ }
      buttons();
    } else if (!off && at(e) && !e.target.closest("a, button, input")) {  // not a gene link or a group's toggle
      var p = at(e);
      held = held ? null : {chrom: p.box.getAttribute("data-chrom"), base: baseAt(p)};
      follow(e);
    }
  });
  document.addEventListener("htmx:afterSettle", function () {
    var box = document.querySelector("#locus-view .sp-tracks");
    if (cur && !cur.isConnected) cur = null;
    if (box) line(box);
  });
  document.addEventListener("htmx:afterSettle", buttons);
  buttons();
  /* moving with the mouse: drag the tracks to move; drag along the ruler to zoom to that stretch; double-click to zoom
     in 3x there; Ctrl (or Cmd) + wheel, or a pinch, zooms at the mouse; a sideways or Shift + wheel moves; arrows and
     + - press the buttons. The tracks slide or stretch inside their boxes at once (each SVG's viewBox), then the new
     window is fetched as the buttons fetch it, through the form's [data-nav]. A plain wheel still scrolls the page. */
  var gesture = null, loading = false, dragged = false, timer = null;
  function axes(box) { return Array.prototype.slice.call(box.querySelectorAll(".sp-trk:not(.sp-trk-chr) > .sp-ax")); }
  function win(box) {
    var n = function (k) { return +box.getAttribute("data-" + k); };
    return {a: n("start"), b: n("end"), size: n("size"), min: n("min"), max: n("max")};
  }
  function fit(w, a, width) {  // the window of `width` bp starting at a, inside the chromosome and the limits
    width = Math.round(Math.max(w.min, Math.min(w.max, w.size || Infinity, width)));
    a = Math.max(0, Math.round(a));
    if (w.size) a = Math.min(a, w.size - width);
    return [a, a + width];
  }
  function preview(box, x, width) {  // show user units x to x + width of every track (1000 across: all of it)
    box.classList.add("sp-moving");
    axes(box).forEach(function (svg) {
      var v = svg.getAttribute("data-vb") || svg.getAttribute("viewBox");
      svg.setAttribute("data-vb", v);
      v = v.split(" ");
      svg.setAttribute("viewBox", [x, v[1], width, v[3]].join(" "));
      svg.setAttribute("preserveAspectRatio", "none");
    });
    box.spView = {x: x, w: width};
    line(box);
  }
  function restore(box) {
    box.classList.remove("sp-moving");
    axes(box).forEach(function (svg) {
      if (svg.hasAttribute("data-vb")) svg.setAttribute("viewBox", svg.getAttribute("data-vb"));
      svg.removeAttribute("data-vb");
      svg.removeAttribute("preserveAspectRatio");
    });
    box.querySelectorAll(".sp-sel").forEach(function (r) { r.remove(); });
    box.spView = null;
    line(box);
  }
  function go(box, a, b) {  // fetch the window a-b (BED); the preview stays until it is swapped in
    var w = win(box), src = document.querySelector("#locus-view [data-nav]");
    if (!src || !window.htmx || (a === w.a && b === w.b)) { restore(box); return; }
    var q = new URLSearchParams(box.getAttribute("data-query")), list = opened();
    q.set("r", box.getAttribute("data-chrom") + ":" + (a + 1) + "-" + b);
    if (list) q.set("open", list); else q.delete("open");
    src.setAttribute("hx-push-url", src.getAttribute("data-page") + "?" + q);
    loading = true;
    htmx.ajax("GET", src.getAttribute("data-svg") + "?" + q, {source: src});
  }
  function done() { loading = false; }
  function failed() { loading = false; document.querySelectorAll("#locus-view .sp-tracks.sp-moving").forEach(restore); }
  document.addEventListener("htmx:afterSettle", done);
  ["htmx:responseError", "htmx:sendError", "htmx:timeout", "htmx:swapError"].forEach(function (n) { document.addEventListener(n, failed); });
  document.addEventListener("pointerdown", function (e) {
    var p = e.button === 0 && e.pointerType !== "touch" && !loading && !e.target.closest("button, input") && at(e);
    if (!p) return;
    dragged = false;
    gesture = {box: p.box, r: p.r, x0: e.clientX, x: p.x, ruler: !!e.target.closest(".sp-trk-ruler"), svg: p.ax};
    if (gesture.ruler) gesture.svg = e.target.closest(".sp-trk-ruler").querySelector(".sp-ax");
  });
  document.addEventListener("pointermove", function (e) {
    var g = gesture, dx = g ? e.clientX - g.x0 : 0;
    if (!g || g.wheel || (!dragged && Math.abs(dx) < 4)) return;
    dragged = true;
    if (!g.ruler) { preview(g.box, -dx / g.r.width * 1000, 1000); return; }
    if (!g.rect) {
      g.rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      g.rect.setAttribute("class", "sp-sel");
      g.rect.setAttribute("y", 0);
      g.rect.setAttribute("height", g.svg.getAttribute("height"));
      g.svg.appendChild(g.rect);
    }
    g.x1 = Math.max(0, Math.min(g.r.width, g.x + dx));
    g.rect.setAttribute("x", Math.min(g.x, g.x1) / g.r.width * 1000);
    g.rect.setAttribute("width", Math.abs(g.x1 - g.x) / g.r.width * 1000);
  });
  function drop(e) {
    var g = gesture;
    gesture = null;
    if (!g || !dragged) return;
    if (e.type === "pointercancel") { restore(g.box); return; }
    var w = win(g.box), bp = (w.b - w.a) / g.r.width, span;
    if (g.ruler) span = fit(w, w.a + Math.min(g.x, g.x1) * bp, Math.abs(g.x1 - g.x) * bp);
    else span = fit(w, w.a - (e.clientX - g.x0) * bp, w.b - w.a);
    go(g.box, span[0], span[1]);
  }
  document.addEventListener("pointerup", drop);
  document.addEventListener("pointercancel", drop);
  document.addEventListener("click", function (e) {  // the click that ends a drag opens no gene and doesn't hold the line
    if (!dragged) return;
    dragged = false;
    if (e.target.closest && e.target.closest("#locus-view .sp-tracks")) { e.preventDefault(); e.stopPropagation(); }
  }, true);
  document.addEventListener("dragstart", function (e) {  // a gene's link is dragged as the track, not as a link
    if (e.target.closest && e.target.closest("#locus-view .sp-tracks .sp-ax")) e.preventDefault();
  });
  document.addEventListener("dblclick", function (e) {
    var p = !loading && !e.target.closest("a, button, input") && at(e);
    if (!p) return;
    var w = win(p.box), width = (w.b - w.a) / 3, span = fit(w, w.a + p.x / p.r.width * (w.b - w.a) - width / 2, width);
    go(p.box, span[0], span[1]);
  });
  document.addEventListener("wheel", function (e) {
    var zoom = e.ctrlKey || e.metaKey, side = !zoom && (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY));
    var p = (zoom || side) && at(e);
    if (!p) return;
    e.preventDefault();  // not the browser's own zoom or Back swipe
    if (loading) return;
    var w = win(p.box), g = gesture && gesture.wheel ? gesture : (gesture = {wheel: true, box: p.box, scale: 1, shift: 0, f: p.x / p.r.width});
    var d = (e.deltaMode ? 30 : 1) * (side && !e.deltaX ? e.deltaY : side ? e.deltaX : e.deltaY);
    if (zoom) g.scale = Math.max(w.min / (w.b - w.a), Math.min(Math.min(w.max, w.size || Infinity) / (w.b - w.a), g.scale * Math.exp(d * 0.004)));
    else g.shift += d / p.r.width;
    preview(p.box, (g.f * (1 - g.scale) + g.shift) * 1000, g.scale * 1000);
    clearTimeout(timer);
    timer = setTimeout(function () {
      gesture = null;
      var width = (w.b - w.a) * g.scale, span = fit(w, w.a + (g.f * (1 - g.scale) + g.shift) * (w.b - w.a), width);
      go(g.box, span[0], span[1]);
    }, 250);
  }, {passive: false});
  document.addEventListener("keydown", function (e) {
    var tip = {ArrowLeft: "Move left", ArrowRight: "Move right", "+": "Zoom in", "=": "Zoom in", "-": "Zoom out"}[e.key];
    if (!tip || loading || e.ctrlKey || e.metaKey || e.altKey || (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]"))) return;
    var b = document.querySelector('#locus-view .sp-bctl a[aria-label^="' + tip + '"]');
    if (!document.querySelector("#locus-view .sp-tracks")) return;
    e.preventDefault();
    if (b) { loading = true; b.click(); }
  });
})();
/* end browser */

/* the embedded locus browser (base_embed.html, in the Table's card drawer): locus links and the region form stay in the
   frame without adding Back steps; another SNP's card opens in the drawer; other pages open in a new tab, so the table
   stays as it is; Esc returns to the card */
(function () {
  "use strict";
  if (window.parent === window || !document.querySelector(".sp-embed")) return;
  function tell(m) { window.parent.postMessage(m, location.origin); }
  function stay(url) { url.searchParams.set("embed", "1"); location.replace(url.href); }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey
        || a.getAttribute("target") === "_blank" || a.hasAttribute("download")) return;  // htmx moves prevent their own
    var url = new URL(a.getAttribute("href"), location.href), card = url.pathname.match(/\/results\/([0-9a-f-]+)\/snp\/(\d+)\/$/);
    if (url.origin !== location.origin) return;
    e.preventDefault();
    if (url.pathname === location.pathname) stay(url);
    else if (card) tell({sp: "card", key: card[1], row: +card[2], url: url.href});
    else window.open(url.href, "_blank", "noopener");  // a gene page and the like: a new tab, the table stays as it is
  });
  document.addEventListener("submit", function (e) {
    if (!e.target.matches || !e.target.matches(".sp-bctl")) return;
    e.preventDefault();
    var url = new URL(e.target.getAttribute("action"), location.href);
    new FormData(e.target).forEach(function (v, k) { url.searchParams.append(k, v); });
    stay(url);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") tell({sp: "back"}); });
})();
