// ABOUTME: Attempt-gated retrieval for lesson quiz items: injects its own stylesheet, requires
// ABOUTME: a typed answer and confidence rating, grades via POST /api/attempt, reveals feedback.

(function () {
  "use strict";

  var CONFIDENCE_LABELS = ["Guessing", "Unsure", "Fairly sure", "Certain"];
  var VERDICT_LABELS = {
    correct: "Correct",
    partially_correct: "Partially correct",
    incorrect: "Not yet",
    not_attempted: "Not attempted",
  };
  var VERDICT_WORDS = {
    correct: "correct",
    partially_correct: "partially correct",
    incorrect: "incorrect",
    not_attempted: "not attempted",
  };
  var FEEDBACK_PARTS = [
    ["criterion", "Criterion"],
    ["task", "Task"],
    ["process", "Process"],
    ["self_regulation", "Self-regulation"],
  ];
  var MIN_ATTEMPT_CHARS = 5;

  // Quiz items live in three kinds of documents, all same-origin with the API: lessons
  // served at /workspace/{course}/lessons/..., the generated daily-review page at
  // /review/{course}, and the generated weekly-review page at /weekly/{course}. One match
  // against this document's own URL yields both facts the API needs: which course, and
  // which surface the attempt was made from. The source is load-bearing beyond bookkeeping
  // — an attempt sourced "weekly" is what marks that week's session genuinely held.
  var SOURCE_BY_PREFIX = { workspace: "lesson", review: "review", weekly: "weekly" };

  function contextFromLocation() {
    var match = document.location.pathname.match(/^\/(workspace|review|weekly)\/([^/]+)(?:\/|$)/);
    if (!match) return { course: null, source: "lesson" };
    return { course: decodeURIComponent(match[2]), source: SOURCE_BY_PREFIX[match[1]] };
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function squareGlyph(filled) {
    return el("span", filled ? "quiz-square filled" : "quiz-square");
  }

  // Lessons render inside an iframe in Keating; a completed attempt (graded or
  // given up) is announced to the parent so its practice views can refresh live. Same
  // origin only, and never load-bearing — a standalone lesson just skips it.
  function notifyParentOfAttempt(itemId) {
    if (window.parent === window) return;
    try {
      window.parent.postMessage({ type: "keating:attempt", itemId: itemId }, window.location.origin);
    } catch (err) {
      // A cross-origin or otherwise unreachable parent is not this quiz item's problem.
    }
  }

  function setUpItem(item, context) {
    var course = context.course;
    if (item.tagName === "DETAILS") return; // legacy click-to-reveal markup — not ours to transform
    var meta;
    var metaScript = item.querySelector("script.quiz-meta");
    try {
      meta = JSON.parse(metaScript ? metaScript.textContent : "");
    } catch (err) {
      item.appendChild(
        el("p", "quiz-error", "This quiz item is misconfigured (bad quiz-meta JSON): " + err.message)
      );
      return;
    }
    if (typeof meta.answer !== "string" || typeof meta.rubric !== "string") {
      item.appendChild(
        el("p", "quiz-error", "This quiz item is misconfigured: quiz-meta needs \"answer\" and \"rubric\".")
      );
      return;
    }

    var questionEl = item.querySelector(".quiz-q");
    var renderTs = Date.now();
    var firstInteraction = null;
    var confidence = null;
    var pending = false;
    var revealed = false;

    var form = el("div", "quiz-form");

    var textarea = el("textarea", "quiz-response");
    textarea.placeholder = "Type your answer from memory.";
    textarea.rows = 3;
    form.appendChild(textarea);

    var confidenceLabel = el("span", "quiz-label", "How sure are you?");
    form.appendChild(confidenceLabel);

    var confidenceGroup = el("div", "quiz-confidence");
    confidenceGroup.setAttribute("role", "group");
    confidenceGroup.setAttribute("aria-label", "How sure are you?");
    var confidenceButtons = CONFIDENCE_LABELS.map(function (label, i) {
      var button = el("button", null, label);
      button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", function () {
        if (pending || revealed) return;
        markInteraction();
        confidence = i + 1;
        confidenceButtons.forEach(function (other) {
          other.setAttribute("aria-pressed", other === button ? "true" : "false");
        });
        refreshSubmit();
      });
      confidenceGroup.appendChild(button);
      return button;
    });
    form.appendChild(confidenceGroup);

    var actions = el("div", "quiz-actions");
    var submit = el("button", "quiz-submit", "Check my answer");
    submit.type = "button";
    submit.disabled = true;
    actions.appendChild(submit);

    var giveUp = el("button", "quiz-giveup", "I can't recall this — show the answer");
    giveUp.type = "button";
    actions.appendChild(giveUp);
    form.appendChild(actions);

    var statusLine = null;
    var errorLine = null;

    item.appendChild(form);

    function markInteraction() {
      if (firstInteraction === null) firstInteraction = Date.now();
    }
    textarea.addEventListener("focus", markInteraction);
    textarea.addEventListener("keydown", markInteraction);
    textarea.addEventListener("input", refreshSubmit);

    function refreshSubmit() {
      submit.disabled =
        pending || revealed || confidence === null ||
        textarea.value.trim().length < MIN_ATTEMPT_CHARS;
    }

    function setPending(on) {
      pending = on;
      textarea.disabled = on;
      confidenceButtons.forEach(function (button) { button.disabled = on; });
      giveUp.disabled = on;
      refreshSubmit();
      if (on) {
        statusLine = el("p", "quiz-status");
        statusLine.appendChild(squareGlyph(false));
        statusLine.appendChild(document.createTextNode("Checking..."));
        form.appendChild(statusLine);
      } else if (statusLine) {
        statusLine.remove();
        statusLine = null;
      }
    }

    function showError(detail) {
      errorLine = el(
        "p", "quiz-error",
        "Couldn't grade this attempt: " + detail + ". Your attempt was not lost — it's still in the box; retry."
      );
      form.appendChild(errorLine);
    }

    // A dead session, reported in place. This page runs inside the shell's reading pane, and
    // reloading the top document from here would destroy an attempt the learner has already
    // typed — the wrong trade for fixing a session problem. The text stays in the box.
    function showSessionEnded() {
      errorLine = el(
        "p", "quiz-error",
        "Your Keating session has ended, so this attempt could not be recorded. Reload Keating to sign in — your answer is still in the box."
      );
      form.appendChild(errorLine);
    }

    function lockInputs(gaveUp) {
      revealed = true;
      textarea.readOnly = true;
      textarea.disabled = false; // readable, selectable, just no longer editable
      textarea.classList.add("locked");
      confidenceButtons.forEach(function (button) { button.disabled = true; });
      actions.remove();
      if (gaveUp && confidence === null) {
        // The defaulted rating is reflected in the control so the calibration line and
        // the buttons never disagree.
        confidenceButtons[0].setAttribute("aria-pressed", "true");
      }
    }

    function reveal(result, sentConfidence) {
      var block = el("div", "quiz-reveal");

      var verdictLine = el("p", "quiz-verdict");
      verdictLine.appendChild(squareGlyph(result.verdict === "correct"));
      verdictLine.appendChild(
        document.createTextNode(VERDICT_LABELS[result.verdict] || result.verdict)
      );
      block.appendChild(verdictLine);

      var canonical = el("div", "quiz-canonical");
      canonical.appendChild(el("span", "quiz-label", "The answer"));
      canonical.appendChild(el("p", null, result.answer));
      block.appendChild(canonical);

      var feedbackList = el("dl", "quiz-feedback");
      FEEDBACK_PARTS.forEach(function (part) {
        var row = el("div");
        row.appendChild(el("dt", null, part[1]));
        row.appendChild(el("dd", null, (result.feedback && result.feedback[part[0]]) || ""));
        feedbackList.appendChild(row);
      });
      block.appendChild(feedbackList);

      block.appendChild(
        el(
          "p", "quiz-calibration",
          "You said: " + CONFIDENCE_LABELS[sentConfidence - 1] +
            " · Result: " + (VERDICT_WORDS[result.verdict] || result.verdict)
        )
      );

      if (sentConfidence >= 3 && result.verdict === "incorrect") {
        block.appendChild(
          el(
            "p", "quiz-hypercorrection",
            "A miss at high confidence is exactly the thing worth extra attention — it marks where your sense of knowing and your knowledge disagree. Expect this one to come back."
          )
        );
      }

      item.appendChild(block);
    }

    function submitAttempt(gaveUp) {
      if (pending || revealed) return;
      if (errorLine) { errorLine.remove(); errorLine = null; }
      var sentConfidence = confidence !== null ? confidence : 1; // give-ups default to Guessing
      var payload = {
        course: course,
        item_id: item.dataset.itemId || "",
        concept: item.dataset.concept || "",
        lesson: item.dataset.lesson || "",
        type: item.dataset.type || "recall",
        cumulative: item.dataset.cumulative === "true",
        question: questionEl ? questionEl.textContent.trim() : "",
        response: textarea.value.trim(),
        confidence: sentConfidence,
        latency_ms: Date.now() - (firstInteraction !== null ? firstInteraction : renderTs),
        gave_up: gaveUp,
        answer: meta.answer,
        rubric: meta.rubric,
        source: context.source,
      };

      if (course === null) {
        showError("this lesson isn't being served from Keating (no /workspace/ URL), so the grading API can't be reached");
        return;
      }

      setPending(true);
      fetch("/api/attempt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          if (response.status === 401) {
            setPending(false);
            showSessionEnded();
            return null;
          }
          return response.json().catch(function () { return {}; }).then(function (body) {
            if (!response.ok) {
              var detail = body && body.detail ? String(body.detail) : "HTTP " + response.status;
              throw new Error(detail);
            }
            return body;
          });
        })
        .then(function (result) {
          if (result === null) return; // the session ended; showSessionEnded already reported it
          setPending(false);
          lockInputs(gaveUp);
          reveal(result, sentConfidence);
          notifyParentOfAttempt(payload.item_id);
        })
        .catch(function (err) {
          setPending(false);
          showError(err.message);
        });
    }

    submit.addEventListener("click", function () { submitAttempt(false); });
    giveUp.addEventListener("click", function () { submitAttempt(true); });
  }

  // The quiz component ships with its own stylesheet: injecting it here means a lesson
  // needs only the one script tag, and the component styles travel with the machinery.
  function injectStylesheet() {
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/quiz.css";
    document.head.prepend(link);
  }

  document.addEventListener("DOMContentLoaded", function () {
    injectStylesheet();
    var context = contextFromLocation();
    document.querySelectorAll(".quiz-item").forEach(function (item) {
      setUpItem(item, context);
    });
  });
})();
