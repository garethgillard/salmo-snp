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
