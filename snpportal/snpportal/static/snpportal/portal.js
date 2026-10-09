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
        var label = copy.textContent;
        copy.textContent = "Copied";
        setTimeout(function () { copy.textContent = label; }, 1200);
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

  // j/k move between table rows that open a card (rows with [data-card]); Enter opens it.
  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, select, textarea") || (e.key !== "j" && e.key !== "k")) return;
    var rows = Array.prototype.slice.call(document.querySelectorAll("tr[data-card]"));
    if (!rows.length) return;
    var i = rows.indexOf(document.activeElement.closest && document.activeElement.closest("tr[data-card]"));
    var next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "j" ? 1 : -1)))];
    var link = next.querySelector("a");
    if (link) link.focus();
  });
})();

/* results: a click anywhere on a table row opens its evidence card (via the row's SNP link, which htmx loads into
   #card), and the open row is highlighted. */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("tr[data-card]");
    var link = row && row.querySelector("a[hx-get]");
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

/* tour: Previous, Next, the dots and the arrow keys switch slides without reloading (they are ?slide=N links, which
   work without JavaScript). The counter is a live region; focus inside a slide that goes moves to the new slide's title. */
(function () {
  "use strict";
  var tour = document.querySelector("[data-tour]");
  if (!tour) return;
  var slides = Array.prototype.slice.call(tour.querySelectorAll(".sp-slide"));
  var dots = Array.prototype.slice.call(tour.querySelectorAll(".sp-tour-dots a"));
  var prev = tour.querySelector("[data-tour-prev]"), next = tour.querySelector("[data-tour-next]");
  var count = tour.querySelector("[data-tour-count]");
  var at = Math.max(0, slides.findIndex(function (s) { return !s.hidden; }));

  function show(i) {
    if (i < 0 || i >= slides.length || i === at) return;
    var focusIn = slides[at].contains(document.activeElement), first = i === 0, last = i === slides.length - 1;
    slides[at].hidden = true;
    dots[at].removeAttribute("aria-current");
    slides[i].hidden = false;
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
    next.textContent = next.getAttribute(last ? "data-end" : "data-next");
    count.textContent = "Slide " + (i + 1) + " of " + slides.length;
    history.replaceState(null, "", "?slide=" + (i + 1));
    if (focusIn) slides[i].querySelector("h2").focus();
  }

  tour.addEventListener("click", function (e) {
    var a = e.target.closest("[data-tour-prev], [data-tour-next], .sp-tour-dots a");
    if (!a || (a.getAttribute("href") || "").charAt(0) !== "?" || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    show(a === prev ? at - 1 : a === next ? at + 1 : dots.indexOf(a));
  });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, select, textarea, [contenteditable]")) return;
    if (e.key === "ArrowLeft") show(at - 1);
    if (e.key === "ArrowRight") show(at + 1);
  });
})();
/* end tour */

/* table: the filter dropdowns (details.sp-dd) stay open while their ticks apply (each change swaps #results); a click
   outside one closes it. Escape closes the card drawer. */
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
  document.addEventListener("keydown", function (e) {  // Escape closes the card drawer
    var close = e.key === "Escape" && document.querySelector("#drawer .btn-close");
    if (close) close.click();
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
  /* the mouse line: follows the mouse over the track column (not the chromosome) and names the base under it on the
     ruler; a click on the tracks holds it still and the next click lets it go; the [data-line] button turns it off */
  var cur = null, held = false, off = false;
  try { off = localStorage.getItem("sp-line") === "off"; } catch (e) { /* storage blocked: the line starts on */ }
  function at(e) {  // the tracks under the mouse and its x on the axis, or null
    var t = e.target.closest ? e.target : null, box = t && !t.closest(".sp-trk-chr") && t.closest("#locus-view .sp-tracks");
    var ax = box && box.querySelector(".sp-ax"), r = ax && ax.getBoundingClientRect(), x = r ? e.clientX - r.left : -1;
    return r && x >= 0 && x <= r.width ? {box: box, ax: ax, r: r, x: x} : null;
  }
  function follow(e) {
    var p = at(e);
    if (cur && (!p || cur !== p.box)) { cur.classList.remove("sp-cur"); cur = null; }
    if (!p) return;
    var a = +p.box.getAttribute("data-start"), b = +p.box.getAttribute("data-end"), base = Math.min(b, a + 1 + Math.floor(p.x / p.r.width * (b - a)));
    p.box.style.setProperty("--sp-x", (p.r.left - p.ax.parentNode.getBoundingClientRect().left + p.x) + "px");
    p.box.style.setProperty("--sp-pos", JSON.stringify(base.toLocaleString("en")));
    p.box.classList.add("sp-cur");
    cur = p.box;
  }
  function buttons() {
    document.querySelectorAll("#locus-view [data-line]").forEach(function (b) { b.classList.toggle("active", !off); b.setAttribute("aria-pressed", !off); });
  }
  document.addEventListener("mousemove", function (e) {
    if (cur && !cur.isConnected) { cur = null; held = false; }  // a move swapped the view
    if (!off && !held) follow(e);
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("#locus-view [data-line]")) {
      off = !off;
      held = false;
      if (cur) { cur.classList.remove("sp-cur"); cur = null; }
      try { localStorage.setItem("sp-line", off ? "off" : "on"); } catch (err) { /* not remembered */ }
      buttons();
    } else if (!off && at(e) && !e.target.closest("a, button, input")) {  // not a gene link or a group's toggle
      follow(e);
      held = !held;
    }
  });
  document.addEventListener("htmx:afterSettle", buttons);
  buttons();
})();
/* end browser */
