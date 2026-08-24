// ABOUTME: The weekly page's "mark this review as held" control: POSTs the session to
// ABOUTME: /api/weekly-session and tells the parent shell to refresh its weekly line.

(function () {
  "use strict";
  var block = document.getElementById("weekly-mark");
  var button = document.getElementById("weekly-mark-button");
  var match = document.location.pathname.match(/^\/weekly\/([^/]+)(?:\/|$)/);
  if (!block || !button || !match) return;
  var course = decodeURIComponent(match[1]);

  function done() {
    var line = document.createElement("p");
    line.className = "weekly-mark-done";
    line.textContent = "Marked as held.";
    block.replaceChildren(line);
    // The weekly page runs standalone in the app's preview iframe; announcing the
    // recorded session lets the sidebar's weekly line refresh instead of waiting for
    // the next course-level refetch. Same origin only, and never load-bearing.
    if (window.parent === window) return;
    try {
      window.parent.postMessage({ type: "keating:weekly-session" }, window.location.origin);
    } catch (err) {
      // A cross-origin or otherwise unreachable parent is not this page's problem.
    }
  }

  function fail(detail) {
    button.disabled = false;
    var existing = document.getElementById("weekly-mark-error");
    if (existing) existing.remove();
    var line = document.createElement("p");
    line.className = "weekly-mark-note";
    line.id = "weekly-mark-error";
    line.textContent = "Couldn't record this session: " + detail + ". Try again.";
    block.appendChild(line);
  }

  button.addEventListener("click", function () {
    button.disabled = true;
    fetch("/api/weekly-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course: course }),
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (!response.ok) {
            throw new Error(body && body.detail ? String(body.detail) : "HTTP " + response.status);
          }
          return body;
        });
      })
      .then(done)
      .catch(function (err) { fail(err.message); });
  });
})();
