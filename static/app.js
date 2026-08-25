// ABOUTME: Frontend logic for Keating: course switching, lessons navigation, course-overview
// ABOUTME: and settings rendering, chat thread, PDF upload/attach, and mobile pane tabs, against the FastAPI backend.

const state = {
  course: null,
  uploadedPdf: null, // relative path of the most recently uploaded PDF, for "attach to next message"
  preview: null, // what the preview pane shows: {kind: "overview"} | {kind: "file", path} | {kind: "practice"} | {kind: "settings"} | null
  settings: null, // platform settings from GET /api/settings (includes the models catalog)
  lessons: [], // the selected course's lessons as last rendered — practice rows map lesson ids to paths through it
};

const el = (id) => document.getElementById(id);

// Thrown when the server says the session is gone. It exists so callers can tell "your
// session ended" apart from "that request failed": the login view is already up by the time
// this reaches them, so rendering it into a pane would be noise.
class AuthError extends Error {
  constructor() {
    super("your session has ended");
    this.name = "AuthError";
  }
}

async function api(path, options) {
  const res = await fetch(path, options);
  // Every API call in the app goes through here, which is why this is the only place the
  // logged-out condition is handled. Thirteen separate renderings of one condition is how an
  // app ends up half-showing stale content after a session expires.
  if (res.status === 401) {
    showLogin({ authenticated: false, bootstrapped: true });
    throw new AuthError();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      // ignore — not JSON
    }
    if (Array.isArray(detail)) {
      // FastAPI validation errors (422) arrive as a list of {loc, msg, ...} objects.
      detail = detail
        .map((err) => `${(err.loc || []).filter((p) => p !== "body").join(".")}: ${err.msg}`)
        .join("; ");
    }
    throw new Error(detail);
  }
  return res;
}

// --- Courses -----------------------------------------------------------

async function loadCourses() {
  const res = await api("/api/courses");
  const { courses } = await res.json();
  const list = el("course-list");
  list.innerHTML = "";
  // Each entry carries the manifest title for display; the slug stays the identity.
  for (const { slug, title } of courses) {
    const li = document.createElement("li");
    li.textContent = title || slug;
    // The slug stays the identity: the title is display only, so selection and the
    // active-row highlight both read the slug from here, never from the label.
    li.dataset.slug = slug;
    li.title = slug;
    li.className = slug === state.course ? "active" : "";
    li.tabIndex = 0;
    // Clicking the already-active course opens its overview in the preview pane;
    // clicking any other course switches to it.
    const activate = () => {
      if (slug === state.course) openCourseOverview({ switchPane: true });
      else selectCourse(slug);
    };
    li.addEventListener("click", activate);
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
    list.appendChild(li);
  }
  if (!state.course && courses.length > 0) {
    selectCourse(courses[0].slug);
  }
}

async function createCourse() {
  const input = el("new-course-slug");
  const slug = input.value.trim();
  if (!slug) return;
  try {
    await api("/api/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug }),
    });
    input.value = "";
    await loadCourses();
    selectCourse(slug);
  } catch (e) {
    alert(`Couldn't create course: ${e.message}`);
  }
}

async function selectCourse(slug) {
  state.course = slug;
  state.uploadedPdf = null;
  el("attach-label").style.display = "none";
  document.querySelectorAll("#course-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.slug === slug);
  });
  el("chat-header").innerHTML = `Teaching workspace: <span class="course-name">${escapeHtml(slug)}</span>`;
  el("mobile-course-name").textContent = slug;
  // allSettled: one failed fetch must not silently blank the other panes.
  const results = await Promise.allSettled([
    loadLessons(slug),
    loadChatHistory(slug),
    openCourseOverview({ switchPane: false }), // the overview is the default preview content
    refreshSidebarPractice(),
  ]);
  for (const r of results) {
    if (r.status === "rejected") console.error("selectCourse:", r.reason);
  }
}

// --- Lessons -----------------------------------------------------------

function makeActivatable(node, action) {
  node.tabIndex = 0;
  node.addEventListener("click", action);
  node.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      action();
    }
  });
}

// One lesson row: the progress square, number, title, and its derived resources nested
// beneath. Units group these; they do not change them.
function lessonListItem(lesson) {
  const li = document.createElement("li");

  const entry = document.createElement("div");
  entry.className = "lesson-entry";
  const number = document.createElement("span");
  number.className = "lesson-number";
  number.textContent = String(lesson.number).padStart(2, "0");
  const title = document.createElement("span");
  title.className = "lesson-title";
  title.textContent = lesson.title;
  entry.append(number, title);
  entry.title = lesson.title;
  makeActivatable(entry, () => previewFile(lesson.path, entry));
  li.appendChild(entry);

  if (lesson.resources.length > 0) {
    const ul = document.createElement("ul");
    ul.className = "lesson-resources";
    for (const resource of lesson.resources) {
      const rli = document.createElement("li");
      if (resource.type === "external") {
        // A real anchor (so middle/cmd-click still opens the site directly), but a plain
        // click opens the in-app reader; the ↗ mark stays — it marks externality.
        const a = document.createElement("a");
        a.className = "resource-entry";
        a.href = resource.href;
        a.rel = "noopener";
        a.textContent = resource.title;
        a.title = resource.title;
        const mark = document.createElement("span");
        mark.className = "external-mark";
        mark.textContent = " ↗";
        a.appendChild(mark);
        a.addEventListener("click", (e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // modified click: browser default
          e.preventDefault();
          previewReader(resource, a);
        });
        a.addEventListener("keydown", (e) => {
          if (e.key === " ") {
            e.preventDefault();
            previewReader(resource, a);
          }
        });
        rli.appendChild(a);
      } else {
        const div = document.createElement("div");
        div.className = "resource-entry";
        div.textContent = resource.title;
        div.title = resource.title;
        makeActivatable(div, () => previewFile(resource.href, div));
        rli.appendChild(div);
      }
      ul.appendChild(rli);
    }
    li.appendChild(ul);
  }
  return li;
}

// --- Units (the sidebar's middle tier) ----------------------------------------

// Every unit starts open while the whole course still fits a scan; past this many lessons
// the sidebar is a map rather than a list, and only the unit being read starts open.
const UNITS_ALL_OPEN_MAX_LESSONS = 15;

// The learner's own open/closed changes, per course. Defaults apply only where this has
// nothing to say, so a unit the learner closed stays closed across reloads.
const unitStateKey = (course) => `keating.units.${course}`;

function storedUnitState(course) {
  try {
    const raw = localStorage.getItem(unitStateKey(course));
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch (_) {
    return null; // private mode, quota, hand-edited value: the defaults still work
  }
}

function persistUnitState(course, key, open) {
  const stored = storedUnitState(course) || {};
  stored[key] = open;
  try {
    localStorage.setItem(unitStateKey(course), JSON.stringify(stored));
  } catch (_) {
    // A sidebar that forgets is worse than one that errors; it is not worth an alert.
  }
}

// Which groups open when the learner has expressed no preference: all of them for a course
// small enough to read whole, otherwise just the one holding the open lesson — falling back
// to the first group that has lessons when nothing is open.
function defaultOpenUnits(groups, openPath) {
  const total = groups.reduce((n, group) => n + group.lessons.length, 0);
  if (total <= UNITS_ALL_OPEN_MAX_LESSONS) return new Set(groups.map((group) => group.key));
  const holding = groups.find((group) => group.lessons.some((lesson) => lesson.path === openPath));
  if (holding) return new Set([holding.key]);
  const first = groups.find((group) => group.lessons.length > 0);
  return new Set(first ? [first.key] : []);
}

// "Part I · Consciousness and its correlates" — the id's last segment is the tier's own
// numbering (part-i, domain-a), and the manifest's unit_label is the course's own word for
// the tier.
function unitSummaryLabel(unitLabel, unit) {
  return `${unitLabel} ${unit.id.split("-").pop().toUpperCase()} · ${unit.title}`;
}

// "3 verified · 2 practiced · 4 untouched" — plain counts of items, in plain words
// (charter P7): no percentage, no bar, no streak. A zero clause is left out rather than
// shown, and a unit carrying no items yields the empty string, which renders no line.
function unitRollupLine(progress) {
  if (!progress) return "";
  const clauses = [];
  if (progress.verified) clauses.push(`${progress.verified} verified`);
  if (progress.practiced) clauses.push(`${progress.practiced} practiced`);
  if (progress.untouched) clauses.push(`${progress.untouched} untouched`);
  return clauses.join(" · ");
}

// A unit as a native <details>: keyboard-operable and announced without an icon library.
// This is disclosure for NAVIGATION — a way to fold a long course down to its structure.
// It is NOT the click-to-reveal quiz pattern that was deliberately removed: nothing behind
// this summary is an answer, and nothing here is gated on an attempt. Do not reuse it for
// content the learner is supposed to retrieve.
function unitGroup(group, open, onToggle) {
  const li = document.createElement("li");
  const details = document.createElement("details");
  details.className = "unit-group";
  details.open = open;
  // The unit's identifying hue, computed server-side from its manifest `order` and carried
  // on /api/lessons — this sets it once per group and every mark inside reads it from CSS.
  // Unassigned has no unit and so no hue; the stylesheet's fallbacks cover that case.
  if (group.color) details.style.setProperty("--unit-hue", group.color);

  const summary = document.createElement("summary");
  const name = document.createElement("span");
  name.className = "unit-name";
  if (group.color) {
    const mark = document.createElement("span");
    mark.className = "unit-mark";
    name.appendChild(mark);
  }
  name.appendChild(document.createTextNode(group.label));
  summary.appendChild(name);
  summary.title = group.label;
  if (group.rollup) {
    const rollup = document.createElement("span");
    rollup.className = "unit-rollup";
    rollup.textContent = group.rollup;
    summary.appendChild(rollup);
  }
  details.appendChild(summary);

  if (group.lessons.length === 0) {
    // A declared unit with nothing in it yet is the course's forward map, not an omission.
    const note = document.createElement("p");
    note.className = "empty-note unit-empty";
    note.textContent = "No lessons yet.";
    details.appendChild(note);
  } else {
    const ul = document.createElement("ul");
    ul.className = "unit-lessons";
    for (const lesson of group.lessons) ul.appendChild(lessonListItem(lesson));
    details.appendChild(ul);
  }

  // <details> may queue a toggle event for the initial open state, so only a change from
  // what was rendered counts as the learner's own — otherwise a default would persist
  // itself and outrank every later default.
  let rendered = open;
  details.addEventListener("toggle", () => {
    if (details.open === rendered) return;
    rendered = details.open;
    onToggle(details.open);
  });

  li.appendChild(details);
  return li;
}

async function loadLessons(slug) {
  const list = el("lesson-list");
  let data;
  try {
    const res = await api(`/api/lessons?course=${encodeURIComponent(slug)}`);
    data = await res.json();
  } catch (err) {
    state.lessons = [];
    list.innerHTML = "";
    const li = document.createElement("li");
    li.className = "empty-note";
    li.textContent = `Couldn't load lessons (${err.message}). Reload the page to retry.`;
    list.appendChild(li);
    return;
  }
  const units = data.units || [];
  const unassigned = data.unassigned || [];
  const unitLabel = data.unit_label || "Unit";
  // The flat list stays what practice rows resolve their lesson ids against.
  state.lessons = [...units.flatMap((unit) => unit.lessons), ...unassigned];
  list.innerHTML = "";

  if (units.length === 0) {
    // No tier declared, so nothing to be unassigned from: a course written before units
    // (or one whose structure is not yet known) renders the flat list it always has.
    if (state.lessons.length === 0) {
      const li = document.createElement("li");
      li.className = "empty-note";
      li.textContent = "No lessons yet. Ask your teacher to begin.";
      list.appendChild(li);
      return;
    }
    for (const lesson of state.lessons) list.appendChild(lessonListItem(lesson));
    return;
  }

  const groups = units.map((unit) => ({
    key: `unit:${unit.id}`,
    label: unitSummaryLabel(unitLabel, unit),
    rollup: unitRollupLine(unit.progress),
    color: unit.color,
    lessons: unit.lessons,
  }));
  if (unassigned.length > 0) {
    // Lessons declaring no unit, or one the manifest does not define. Last, and without a
    // rollup or a hue — it is a gap in the course's structure, not a part of it.
    groups.push({ key: "unassigned", label: "Unassigned", rollup: "", color: null, lessons: unassigned });
  }

  const stored = storedUnitState(slug);
  const openPath = state.preview && state.preview.kind === "file" ? state.preview.path : null;
  const defaults = defaultOpenUnits(groups, openPath);
  for (const group of groups) {
    const open = stored && group.key in stored ? Boolean(stored[group.key]) : defaults.has(group.key);
    list.appendChild(unitGroup(group, open, (next) => persistUnitState(slug, group.key, next)));
  }
}

// Refresh everything derived from the course's files — after a chat turn or an upload,
// the lesson list and (if showing) the overview may both be stale.
async function refreshCourseView() {
  if (!state.course) return;
  const tasks = [loadLessons(state.course), refreshSidebarPractice()];
  if (state.preview && state.preview.kind === "overview") {
    tasks.push(openCourseOverview({ switchPane: false }));
  } else if (state.preview && state.preview.kind === "practice") {
    tasks.push(openPracticeView({ switchPane: false }));
  }
  await Promise.all(tasks);
}

// --- File preview -----------------------------------------------------------

function clearPreview() {
  state.preview = null;
  el("preview-title").textContent = "No course selected";
  el("preview-body").innerHTML = '<div id="preview-placeholder">Select a course to see its overview here.</div>';
}

async function previewFile(path, entryEl) {
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  if (entryEl) entryEl.classList.add("selected");
  // Sidebar entries carry the human title; fall back to the path so the frame is never unnamed.
  const title = (entryEl && entryEl.title) || path;

  state.preview = { kind: "file", path };
  el("preview-title").textContent = path;
  if (MOBILE_QUERY.matches) setPane("preview");
  setPreviewCollapsed(false); // requested content must never render into a hidden pane
  const body = el("preview-body");
  body.innerHTML = "";

  const lower = path.toLowerCase();
  if (lower.endsWith(".html")) {
    const iframe = document.createElement("iframe");
    iframe.title = title || path;   // screen readers announce the frame by what it holds
    iframe.src = `/workspace/${encodeURIComponent(state.course)}/${path.split("/").map(encodeURIComponent).join("/")}`;
    body.appendChild(iframe);
  } else if (lower.endsWith(".pdf")) {
    const iframe = document.createElement("iframe");
    iframe.title = title || path;
    iframe.src = `/api/file?course=${encodeURIComponent(state.course)}&path=${encodeURIComponent(path)}`;
    body.appendChild(iframe);
  } else {
    try {
      const res = await api(`/api/file?course=${encodeURIComponent(state.course)}&path=${encodeURIComponent(path)}`);
      const text = await res.text();
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.appendChild(pre);
    } catch (e) {
      body.innerHTML = `<div id="preview-placeholder">Couldn't load file: ${escapeHtml(e.message)}</div>`;
    }
  }
}

// External resources open through the backend reader (/api/reader) inside the preview
// pane — the escape hatch to the original site lives inside the reader page itself.
function previewReader(resource, entryEl) {
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  if (entryEl) entryEl.classList.add("selected");

  state.preview = { kind: "reader", url: resource.href };
  el("preview-title").textContent = resource.title;
  if (MOBILE_QUERY.matches) setPane("preview");
  setPreviewCollapsed(false); // requested content must never render into a hidden pane
  const body = el("preview-body");
  body.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.title = resource.title || "Reader";
  iframe.src = `/api/reader?course=${encodeURIComponent(state.course)}&url=${encodeURIComponent(resource.href)}`;
  body.appendChild(iframe);
}

// --- Course overview -----------------------------------------------------------

async function openCourseOverview({ switchPane = true } = {}) {
  if (!state.course) return;
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "overview" };
  el("preview-title").textContent = "Course overview";
  if (switchPane && MOBILE_QUERY.matches) setPane("preview");
  // switchPane doubles as "the user explicitly asked for this": background refreshes
  // (course switch, post-chat refresh) leave a tucked-away pane tucked away.
  if (switchPane) setPreviewCollapsed(false);
  const body = el("preview-body");
  try {
    const res = await api(`/api/course-overview?course=${encodeURIComponent(state.course)}`);
    const data = await res.json();
    body.innerHTML = "";
    body.appendChild(renderOverview(data));
  } catch (e) {
    body.innerHTML = `<div id="preview-placeholder">Couldn't load overview: ${escapeHtml(e.message)}</div>`;
  }
}

function renderOverview(data) {
  const root = document.createElement("div");
  root.className = "overview";

  const header = document.createElement("header");
  header.className = "overview-header";
  const h1 = document.createElement("h1");
  h1.className = "overview-title";
  h1.textContent = data.title;
  const controls = document.createElement("div");
  controls.className = "overview-controls";
  const renameInput = document.createElement("input");
  renameInput.type = "text";
  renameInput.className = "rename-input";
  renameInput.value = state.course;
  renameInput.setAttribute("aria-label", "Course slug");
  const renameBtn = document.createElement("button");
  renameBtn.className = "btn btn-secondary";
  renameBtn.textContent = "Rename";
  renameBtn.addEventListener("click", () => renameCourse(renameInput.value.trim()));
  renameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") renameCourse(renameInput.value.trim());
  });
  const archiveBtn = document.createElement("button");
  archiveBtn.className = "btn btn-secondary";
  archiveBtn.textContent = "Archive";
  archiveBtn.addEventListener("click", archiveCourse);
  controls.append(renameInput, renameBtn, archiveBtn);
  header.append(h1, controls);
  root.appendChild(header);

  const makeSection = (heading) => {
    const section = document.createElement("section");
    section.className = "overview-section";
    const h2 = document.createElement("h2");
    h2.textContent = heading;
    section.appendChild(h2);
    root.appendChild(section);
    return section;
  };

  const makeProse = (html) => {
    const prose = document.createElement("div");
    prose.className = "overview-prose";
    prose.innerHTML = html;
    adoptProseLinks(prose);
    return prose;
  };

  if (data.mission_html) {
    makeSection("Mission").appendChild(makeProse(data.mission_html));
  }

  if (data.resources_html || data.unclaimed_files.length > 0) {
    const section = makeSection("Resources");
    if (data.resources_html) {
      section.appendChild(makeProse(data.resources_html));
    }
    if (data.unclaimed_files.length > 0) {
      const h3 = document.createElement("h3");
      h3.className = "overview-subheading";
      h3.textContent = "Files";
      section.appendChild(h3);
      const ul = document.createElement("ul");
      ul.className = "overview-files";
      for (const name of data.unclaimed_files) {
        const li = document.createElement("li");
        li.textContent = name;
        makeActivatable(li, () => previewFile(name, null));
        ul.appendChild(li);
      }
      section.appendChild(ul);
    }
  }

  if (data.notes_html) {
    makeSection("Notes").appendChild(makeProse(data.notes_html));
  }

  if (data.learning_records.length > 0) {
    const section = makeSection("Learning records");
    for (const record of data.learning_records) {
      const details = document.createElement("details");
      details.className = "overview-record";
      const summary = document.createElement("summary");
      const number = document.createElement("span");
      number.className = "record-number";
      number.textContent = String(record.number).padStart(2, "0");
      summary.append(number, ` ${record.title}`);
      details.appendChild(summary);
      details.appendChild(makeProse(record.html));
      section.appendChild(details);
    }
  }

  if (data.reference.length > 0) {
    const section = makeSection("Reference");
    const ul = document.createElement("ul");
    ul.className = "overview-files";
    for (const doc of data.reference) {
      const li = document.createElement("li");
      li.textContent = doc.title;
      li.title = doc.path;
      makeActivatable(li, () => previewFile(doc.path, null));
      ul.appendChild(li);
    }
    section.appendChild(ul);
  }

  return root;
}

// --- Practice page (reading pane) --------------------------------------------

// Labels mirror quiz.js exactly — the sparkline tooltips and the quiz reveal must
// name confidence levels and verdicts identically.
const PRACTICE_CONFIDENCE_LABELS = ["Guessing", "Unsure", "Fairly sure", "Certain"];
const PRACTICE_VERDICT_LABELS = {
  correct: "Correct",
  partially_correct: "Partially correct",
  incorrect: "Incorrect",
  not_attempted: "Not attempted",
};
const PRACTICE_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"];

function practiceDate(ts) {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts.slice(0, 10);
  return `${PRACTICE_MONTHS[d.getMonth()]} ${d.getDate()}`;
}

function practiceRelativeTime(ts) {
  const then = new Date(ts).getTime();
  if (isNaN(then)) return ts.slice(0, 10);
  const count = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return count(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return count(hours, "hour");
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 31) return count(days, "day");
  const months = Math.round(days / 30.4);
  if (months < 12) return count(months, "month");
  return count(Math.round(months / 12), "year");
}

// One 9px Keating square per attempt. Fill STATE encodes the verdict (never hue):
// filled = correct, half = partially correct, hollow = incorrect, gray-hollow = not
// attempted / gave up. The tooltip carries the exact record.
function practiceSquare(attempt) {
  const span = document.createElement("span");
  let cls = "practice-square";
  if (attempt.verdict === "correct") cls += " filled";
  else if (attempt.verdict === "partially_correct") cls += " half";
  else if (attempt.verdict === "not_attempted") cls += " gaveup";
  span.className = cls;
  span.title = `${practiceDate(attempt.ts)} · ${
    PRACTICE_CONFIDENCE_LABELS[attempt.confidence - 1] || attempt.confidence
  } · ${PRACTICE_VERDICT_LABELS[attempt.verdict] || attempt.verdict}`;
  return span;
}

// "23 attempts across 9 items. 2 gave-ups. 1 high-confidence miss." — plain factual
// counts; zero-count clauses are omitted rather than stated.
function practiceSummarySentence(summary) {
  const n = (count, noun, plural) => `${count} ${count === 1 ? noun : plural || noun + "s"}`;
  const parts = [
    `${n(summary.total_attempts, "attempt")} across ${n(summary.distinct_items, "item")}.`,
  ];
  if (summary.gave_ups > 0) parts.push(`${n(summary.gave_ups, "gave-up")}.`);
  if (summary.high_confidence_misses > 0) {
    parts.push(`${n(summary.high_confidence_misses, "high-confidence miss", "high-confidence misses")}.`);
  }
  return parts.join(" ");
}

function renderPracticeTable(items) {
  const wrap = document.createElement("div");
  wrap.className = "practice-table-wrap";
  const table = document.createElement("table");
  table.className = "practice-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["", "Concept", "Lesson", "Attempts", "Last practiced"]) {
    const th = document.createElement("th");
    th.textContent = label;
    if (label === "Attempts") th.className = "practice-count";
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const item of items) {
    const tr = document.createElement("tr");

    const sparkTd = document.createElement("td");
    const spark = document.createElement("span");
    spark.className = "practice-sparkline";
    for (const attempt of item.attempts) spark.appendChild(practiceSquare(attempt));
    sparkTd.appendChild(spark);

    const conceptTd = document.createElement("td");
    const concept = document.createElement("div");
    concept.className = "practice-concept";
    concept.textContent = item.concept || item.item_id;
    conceptTd.appendChild(concept);
    if (item.high_confidence_miss) {
      const flag = document.createElement("div");
      flag.className = "practice-flag";
      flag.textContent = "high-confidence miss";
      conceptTd.appendChild(flag);
    }

    const lessonTd = document.createElement("td");
    lessonTd.className = "practice-lesson";
    lessonTd.textContent = item.lesson;

    const countTd = document.createElement("td");
    countTd.className = "practice-count";
    countTd.textContent = String(item.attempts.length);

    const lastTd = document.createElement("td");
    lastTd.className = "practice-last";
    lastTd.textContent = practiceRelativeTime(item.last_ts);
    const lastDate = new Date(item.last_ts);
    lastTd.title = isNaN(lastDate.getTime())
      ? item.last_ts
      : `${practiceDate(item.last_ts)}, ${lastDate.getFullYear()}`;

    tr.append(sparkTd, conceptTd, lessonTd, countTd, lastTd);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

// Confidence (rows) by verdict (columns) counts — no percentages, no colors, blank
// cells for zero. Only the three graded verdicts appear as columns.
function renderCalibrationTable(calibration) {
  const table = document.createElement("table");
  table.className = "practice-calibration";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["", "Correct", "Partial", "Incorrect"]) {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  PRACTICE_CONFIDENCE_LABELS.forEach((label, i) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = label;
    tr.appendChild(th);
    for (let v = 0; v < 3; v++) {
      const td = document.createElement("td");
      const count = calibration.matrix[i][v];
      td.textContent = count > 0 ? String(count) : "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

// The full-density practice view is its own page in the reading pane, the same view
// pattern as Settings; the sidebar Practice section is the ambient view and the way in.
// switchPane doubles as "the user explicitly asked for this": background refreshes
// (the postMessage announcements from the preview iframe) leave a tucked-away pane
// tucked away.
async function openPracticeView({ switchPane = true } = {}) {
  if (!state.course) return;
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "practice" };
  el("preview-title").textContent = "Practice";
  if (switchPane && MOBILE_QUERY.matches) setPane("preview");
  if (switchPane) setPreviewCollapsed(false);
  const body = el("preview-body");
  try {
    const res = await api(`/api/practice?course=${encodeURIComponent(state.course)}`);
    const practice = await res.json();
    body.innerHTML = "";
    body.appendChild(renderPracticeView(practice));
  } catch (e) {
    body.innerHTML = `<div id="preview-placeholder">Couldn't load practice: ${escapeHtml(e.message)}</div>`;
  }
}

function renderPracticeView(practice) {
  const root = document.createElement("div");
  root.className = "overview practice-view";

  const header = document.createElement("header");
  header.className = "overview-header";
  const h1 = document.createElement("h1");
  h1.className = "overview-title";
  h1.textContent = "Practice";
  header.appendChild(h1);
  root.appendChild(header);

  const makeSection = (heading) => {
    const section = document.createElement("section");
    section.className = "overview-section";
    const h2 = document.createElement("h2");
    h2.textContent = heading;
    section.appendChild(h2);
    root.appendChild(section);
    return section;
  };

  const attempts = makeSection("Attempts");
  const summary = document.createElement("p");
  summary.className = "practice-summary";
  summary.textContent = practiceSummarySentence(practice.summary);
  attempts.appendChild(summary);
  if (practice.items.length > 0) {
    attempts.appendChild(renderPracticeTable(practice.items));
  }

  // The calibration table only means something once there are a few graded attempts
  // (give-ups aren't graded and say nothing about calibration).
  const gradedAttempts = practice.calibration
    ? practice.calibration.matrix.reduce((sum, row) => sum + row[0] + row[1] + row[2], 0)
    : 0;
  if (gradedAttempts >= 5) {
    const section = makeSection("Calibration");
    section.appendChild(renderCalibrationTable(practice.calibration));
    if (practice.summary.high_confidence_misses > 0) {
      const note = document.createElement("p");
      note.className = "practice-note";
      note.textContent = "High-confidence misses are the items most worth re-testing.";
      section.appendChild(note);
    }
  }

  return root;
}

// --- Practice section (sidebar) -----------------------------------------------

// The sidebar shows at most this many trailing attempts per sparkline; older attempts
// compress into a leading text ellipsis (the overview shows the full history).
const SIDEBAR_SPARKLINE_CAP = 8;

// "9 attempts · 4 items · 4 gave-ups" — the overview sentence compressed to one
// metadata line; zero-count clauses are omitted rather than stated.
function sidebarPracticeSummaryLine(summary) {
  const n = (count, noun, plural) => `${count} ${count === 1 ? noun : plural || noun + "s"}`;
  const parts = [n(summary.total_attempts, "attempt"), n(summary.distinct_items, "item")];
  if (summary.gave_ups > 0) parts.push(n(summary.gave_ups, "gave-up"));
  if (summary.high_confidence_misses > 0) {
    parts.push(n(summary.high_confidence_misses, "high-confidence miss", "high-confidence misses"));
  }
  return parts.join(" · ");
}

// Today's review: the generated daily-review page (GET /review/{course}) presenting
// the due items through the same quiz machinery lessons use, in the preview iframe —
// the previewFile pattern, with its own preview kind so refreshes leave it alone
// (reloading it would wipe an in-progress attempt).
function openReviewView() {
  if (!state.course) return;
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "review" };
  el("preview-title").textContent = "Today's review";
  if (MOBILE_QUERY.matches) setPane("preview");
  setPreviewCollapsed(false); // requested content must never render into a hidden pane
  const body = el("preview-body");
  body.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.title = "Today's review";
  iframe.src = `/review/${encodeURIComponent(state.course)}`;
  body.appendChild(iframe);
}

// "Today's review · 3 due" above the summary line — navigation into the review page,
// present only while something is due (zero due renders no line at all, per P7: no
// empty chrome, no streaks). due is /api/practice's due_today ({count, item_ids}).
function renderSidebarReviewLine(due) {
  const line = el("practice-sidebar-review");
  line.textContent = "";
  if (!due || due.count === 0) {
    line.hidden = true;
    return;
  }
  line.append("Today’s review · ");
  const count = document.createElement("span");
  count.className = "review-due-count";
  count.textContent = `${due.count} due`;
  line.appendChild(count);
  line.hidden = false;
}

// Weekly review: the delayed unassisted check plus calibration, mission, and the
// what-happened-in-the-world prompt (GET /weekly/{course}), in the preview iframe. Its own
// preview kind, like the daily review, so background refreshes never reload an
// in-progress attempt out from under the learner.
function openWeeklyView() {
  if (!state.course) return;
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "weekly" };
  el("preview-title").textContent = "Weekly review";
  if (MOBILE_QUERY.matches) setPane("preview");
  setPreviewCollapsed(false); // requested content must never render into a hidden pane
  const body = el("preview-body");
  body.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.title = "Weekly review";
  iframe.src = `/weekly/${encodeURIComponent(state.course)}`;
  // Serving the page is what records the session in the cadence log, so the sidebar's
  // "due" marker is stale the moment the frame loads; re-read it rather than leave the
  // line contradicting the record.
  iframe.addEventListener("load", () => refreshSidebarPractice());
  body.appendChild(iframe);
}

// "Weekly review · due" under the daily line — always present once the course has practice
// events (the whole Practice section hides otherwise), because the weekly session is a
// standing ritual rather than a queue. The accent-deep "due" suffix appears only when the
// seven-day cadence has lapsed; there is never a count. weekly is /api/practice's weekly
// block ({due, last_session_ts, eligible_count}).
function renderSidebarWeeklyLine(weekly) {
  const line = el("practice-sidebar-weekly");
  line.textContent = "Weekly review";
  if (!weekly || !weekly.due) return;
  line.append(" · ");
  const flag = document.createElement("span");
  flag.className = "weekly-due";
  flag.textContent = "due";
  line.appendChild(flag);
}

// Practice items carry a lesson id ("0001"); the loaded lessons list carries numbers
// and file paths. Null when the lesson isn't (or is no longer) in the list.
function lessonForPracticeItem(item) {
  const id = String(item.lesson);
  return (
    state.lessons.find(
      (lesson) =>
        String(lesson.number).padStart(4, "0") === id.padStart(4, "0") ||
        lesson.path.startsWith(`lessons/${id}-`) ||
        lesson.path.startsWith(`lessons/${id}.`)
    ) || null
  );
}

// Re-fetches /api/practice and re-renders the sidebar section. The section stays
// hidden (Lessons expands to fill) when there's no course, no events, or the fetch
// fails — an ambient view degrades to absent rather than erroring.
async function refreshSidebarPractice() {
  const section = el("practice-section");
  const course = state.course;
  // The section itself follows the course, not the events: Compose is a way into practice
  // rather than a readout of it, so it has to be reachable before there is anything to
  // read out. The readout lines below it stay absent until the course has events.
  section.classList.toggle("has-course", Boolean(course));
  if (!course) return;
  let practice = null;
  try {
    const res = await api(`/api/practice?course=${encodeURIComponent(course)}`);
    practice = await res.json();
  } catch (err) {
    console.error("refreshSidebarPractice:", err);
  }
  if (course !== state.course) return; // course switched mid-fetch; the newer call owns the section
  const hasEvents = Boolean(practice && practice.summary && practice.summary.total_attempts > 0);
  el("practice-sidebar-weekly").hidden = !hasEvents;
  el("practice-sidebar-summary").hidden = !hasEvents;
  el("practice-sidebar-list").hidden = !hasEvents;
  if (!hasEvents) {
    renderSidebarReviewLine(null);
    return;
  }

  renderSidebarReviewLine(practice.due_today);
  renderSidebarWeeklyLine(practice.weekly);
  el("practice-sidebar-summary").textContent = sidebarPracticeSummaryLine(practice.summary);

  const list = el("practice-sidebar-list");
  list.innerHTML = "";
  const items = [...practice.items].sort((a, b) => new Date(b.last_ts) - new Date(a.last_ts));
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "practice-row";

    const spark = document.createElement("span");
    spark.className = "practice-sparkline";
    if (item.attempts.length > SIDEBAR_SPARKLINE_CAP) {
      const ellipsis = document.createElement("span");
      ellipsis.className = "practice-ellipsis";
      ellipsis.textContent = "…";
      spark.appendChild(ellipsis);
    }
    for (const attempt of item.attempts.slice(-SIDEBAR_SPARKLINE_CAP)) {
      spark.appendChild(practiceSquare(attempt));
    }
    li.appendChild(spark);

    const concept = document.createElement("div");
    concept.className = "practice-row-concept";
    concept.textContent = item.concept || item.item_id;
    concept.title = item.concept || item.item_id;
    li.appendChild(concept);

    if (item.high_confidence_miss) {
      const flag = document.createElement("div");
      flag.className = "practice-flag";
      flag.textContent = "high-confidence miss";
      li.appendChild(flag);
    }

    li.title = `Last practiced ${practiceRelativeTime(item.last_ts)}`;
    // Row click opens the item's source lesson in the preview pane; an unmapped
    // lesson id (item predates a renumber, list failed to load) is a quiet no-op.
    makeActivatable(li, () => {
      const lesson = lessonForPracticeItem(item);
      if (lesson) previewFile(lesson.path, null);
    });
    list.appendChild(li);
  }
}

// --- Compose (the learner-authored artifact surface) --------------------------

// Charter P1/P8: the learner drafts the artifact, closed-book, and the AI's version
// arrives afterwards as a critique target. Two modes share this view — a free recall,
// logged as a retrieval event like any quiz attempt, and a glossary definition that ends
// up in GLOSSARY.md in the learner's own words.

// Floors on a committed draft, mirroring the server's own (main.py COMPOSE_*_MIN_CHARS).
const COMPOSE_RECALL_MIN_CHARS = 40;
const COMPOSE_DEFINE_MIN_CHARS = 20;

const COMPOSE_FEEDBACK_PARTS = [
  ["criterion", "Criterion"],
  ["task", "Task"],
  ["process", "Process"],
  ["self_regulation", "Self-regulation"],
];

// Each grader's own bands, mapped to the square glyph's fill state (filled / half /
// hollow) and to the word the calibration line reads back. `low` marks the band that
// triggers the high-confidence note.
const COMPOSE_BANDS = {
  recall: {
    substantial: { label: "Substantial recall", word: "substantial", fill: "filled" },
    partial: { label: "Partial recall", word: "partial", fill: "half" },
    thin: { label: "Thin recall", word: "thin", fill: "", low: true },
  },
  define: {
    sound: { label: "Sound", word: "sound", fill: "filled" },
    partial: { label: "Partial", word: "partial", fill: "half" },
    off: { label: "Off", word: "off", fill: "", low: true },
  },
};

function composeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// The 9px Keating square in its verdict role, same geometry and fill grammar as the
// practice sparkline's.
function composeSquare(fill) {
  return composeEl("span", fill ? `practice-square ${fill}` : "practice-square");
}

// A segmented control: the quiz component's confidence idiom, used here for both the
// mode switch and the confidence rating. onPick receives the zero-based index.
function composeSegmented(labels, ariaLabel, onPick) {
  const group = composeEl("div", "compose-segmented");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", ariaLabel);
  const buttons = labels.map((label, i) => {
    const button = composeEl("button", null, label);
    button.type = "button";
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      buttons.forEach((other) => {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      onPick(i);
    });
    group.appendChild(button);
    return button;
  });
  return { group, buttons };
}

function composeConfidence(onPick) {
  const label = composeEl("span", "compose-label", "How sure are you?");
  const control = composeSegmented(PRACTICE_CONFIDENCE_LABELS, "How sure are you?", (i) =>
    onPick(i + 1)
  );
  return { label, ...control };
}

function composeFeedbackList(feedback) {
  const list = composeEl("dl", "compose-feedback");
  for (const [key, label] of COMPOSE_FEEDBACK_PARTS) {
    const row = composeEl("div");
    row.appendChild(composeEl("dt", null, label));
    row.appendChild(composeEl("dd", null, (feedback && feedback[key]) || ""));
    list.appendChild(row);
  }
  return list;
}

// Predicted against actual, in the reveal, never before it (charter P13).
function composeCalibration(block, confidence, band, lowNote) {
  block.appendChild(
    composeEl(
      "p",
      "compose-calibration",
      `You said: ${PRACTICE_CONFIDENCE_LABELS[confidence - 1]} · Result: ${band.word}`
    )
  );
  if (confidence >= 3 && band.low) {
    block.appendChild(composeEl("p", "compose-hypercorrection", lowNote));
  }
}

// A labelled list, omitted entirely when the group is empty — an absent heading means
// nothing fell into it, which is information the learner can read directly.
function composeGroup(parent, label, points) {
  if (!Array.isArray(points) || points.length === 0) return false;
  parent.appendChild(composeEl("span", "compose-label", label));
  const list = composeEl("ul");
  for (const point of points) list.appendChild(composeEl("li", null, point));
  parent.appendChild(list);
  return true;
}

async function openComposeView({ switchPane = true } = {}) {
  if (!state.course) return;
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "compose" };
  el("preview-title").textContent = "Compose";
  if (switchPane && MOBILE_QUERY.matches) setPane("preview");
  if (switchPane) setPreviewCollapsed(false);
  const body = el("preview-body");
  try {
    const res = await api(`/api/compose-targets?course=${encodeURIComponent(state.course)}`);
    const targets = await res.json();
    body.innerHTML = "";
    body.appendChild(renderComposeView(targets));
  } catch (e) {
    body.innerHTML = `<div id="preview-placeholder">Couldn't load Compose: ${escapeHtml(e.message)}</div>`;
  }
}

function renderComposeView(targets) {
  const root = composeEl("div", "overview compose-view");

  const header = composeEl("header", "overview-header");
  header.appendChild(composeEl("h1", "overview-title", "Compose"));
  root.appendChild(header);

  const section = composeEl("section", "overview-section");
  const modes = composeEl("div", "compose-modes");
  const panel = composeEl("div", "compose-panel");

  let mode = "recall";
  const switcher = composeSegmented(["Recall", "Define"], "What to compose", (i) => {
    const picked = i === 0 ? "recall" : "define";
    if (picked === mode) return;
    mode = picked;
    panel.innerHTML = "";
    panel.appendChild(picked === "recall" ? renderRecallMode(targets) : renderDefineMode(targets));
  });
  switcher.buttons[0].setAttribute("aria-pressed", "true");
  modes.appendChild(switcher.group);

  panel.appendChild(renderRecallMode(targets));
  section.append(modes, panel);
  root.appendChild(section);
  return root;
}

// --- Compose: recall mode ------------------------------------------------------

function renderRecallMode(targets) {
  const panel = composeEl("div", "compose-recall");
  const renderTs = Date.now();
  let firstInteraction = null;
  let confidence = null;
  let pending = false;
  let done = false;
  let errorLine = null;

  const targetLabel = composeEl("label", "compose-label", "What to recall");
  targetLabel.htmlFor = "compose-target";
  const select = composeEl("select", "compose-target");
  select.id = "compose-target";
  select.appendChild(new Option("Choose what to recall", ""));
  if (targets.lessons.length > 0) {
    const group = document.createElement("optgroup");
    group.label = "Lessons";
    for (const lesson of targets.lessons) {
      const number = String(lesson.number).padStart(2, "0");
      group.appendChild(new Option(`Lesson ${number} · ${lesson.title}`, `lesson:${lesson.path}`));
    }
    select.appendChild(group);
  }
  if (targets.concepts.length > 0) {
    const group = document.createElement("optgroup");
    group.label = "Concepts";
    for (const concept of targets.concepts) {
      group.appendChild(new Option(concept, `concept:${concept}`));
    }
    select.appendChild(group);
  }

  const instruction = composeEl(
    "p",
    "compose-instruction",
    "Close the reading. Write everything you remember about this, in whatever order it comes."
  );

  const draft = composeEl("textarea", "compose-draft");
  draft.rows = 12;
  draft.placeholder = "Write from memory.";

  const rating = composeConfidence((value) => {
    if (pending || done) return;
    markInteraction();
    confidence = value;
    refresh();
  });

  const actions = composeEl("div", "compose-actions");
  const submit = composeEl("button", "btn btn-primary", "Check my recall");
  submit.type = "button";
  submit.disabled = true;
  actions.appendChild(submit);

  panel.append(targetLabel, select, instruction, draft, rating.label, rating.group, actions);

  function markInteraction() {
    if (firstInteraction === null) firstInteraction = Date.now();
  }

  function refresh() {
    submit.disabled =
      pending ||
      done ||
      !select.value ||
      confidence === null ||
      draft.value.trim().length < COMPOSE_RECALL_MIN_CHARS;
  }

  select.addEventListener("change", () => {
    markInteraction();
    refresh();
  });
  draft.addEventListener("focus", markInteraction);
  draft.addEventListener("input", () => {
    markInteraction();
    refresh();
  });

  let statusLine = null;
  function setPending(on) {
    pending = on;
    select.disabled = on;
    draft.disabled = on;
    rating.buttons.forEach((button) => {
      button.disabled = on;
    });
    refresh();
    if (on) {
      statusLine = composeEl("p", "compose-status");
      statusLine.appendChild(composeSquare(""));
      statusLine.appendChild(document.createTextNode("Checking…"));
      panel.appendChild(statusLine);
    } else if (statusLine) {
      statusLine.remove();
      statusLine = null;
    }
  }

  submit.addEventListener("click", async () => {
    if (pending || done) return;
    if (errorLine) {
      errorLine.remove();
      errorLine = null;
    }
    const separator = select.value.indexOf(":");
    const sentConfidence = confidence;
    const payload = {
      course: state.course,
      target_type: select.value.slice(0, separator),
      target_ref: select.value.slice(separator + 1),
      response: draft.value.trim(),
      confidence: sentConfidence,
      latency_ms: Date.now() - (firstInteraction !== null ? firstInteraction : renderTs),
    };
    setPending(true);
    try {
      const res = await api("/api/compose/recall", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await res.json();
      setPending(false);
      done = true;
      // The draft stays readable beside its critique; nothing about it is editable now.
      draft.disabled = false;
      draft.readOnly = true;
      draft.classList.add("locked");
      rating.buttons.forEach((button) => {
        button.disabled = true;
      });
      actions.remove();
      panel.appendChild(renderRecallCritique(result, sentConfidence));
      refreshSidebarPractice();
    } catch (e) {
      setPending(false);
      errorLine = composeEl(
        "p",
        "compose-error",
        `Couldn't check this recall: ${e.message}. Your writing is still in the box; retry.`
      );
      panel.appendChild(errorLine);
    }
  });

  return panel;
}

function renderRecallCritique(result, confidence) {
  const block = composeEl("div", "compose-critique");
  const band = COMPOSE_BANDS.recall[result.verdict] || {
    label: result.verdict,
    word: result.verdict,
    fill: "",
  };

  const verdict = composeEl("p", "compose-verdict");
  verdict.appendChild(composeSquare(band.fill));
  verdict.appendChild(document.createTextNode(band.label));
  block.appendChild(verdict);

  const coverage = composeEl("div", "compose-coverage");
  let any = composeGroup(coverage, "You had", result.had);
  any = composeGroup(coverage, "You missed", result.missed) || any;
  any = composeGroup(coverage, "Not quite right", result.not_quite) || any;
  if (any) block.appendChild(coverage);

  block.appendChild(composeFeedbackList(result.feedback));
  composeCalibration(
    block,
    confidence,
    band,
    "A thin recall at high confidence is the signal worth the most attention: it marks where your sense of knowing and your knowledge disagree."
  );
  block.appendChild(
    composeEl("p", "compose-closing", "Take anything surprising here to your teacher in the chat.")
  );
  return block;
}

// --- Compose: define mode ------------------------------------------------------

function renderDefineMode(targets) {
  const panel = composeEl("div", "compose-define");
  const renderTs = Date.now();
  let firstInteraction = null;
  let confidence = null;
  let pending = false;
  let checked = false;
  let errorLine = null;

  const termLabel = composeEl("label", "compose-label", "The term you're defining");
  termLabel.htmlFor = "compose-term";
  const term = composeEl("input", "compose-term");
  term.type = "text";
  term.id = "compose-term";
  term.placeholder = "One term";

  const termsLabel = composeEl("span", "compose-label", "Already in your glossary");
  const termsRow = composeEl("div", "compose-terms");

  function renderTermsList(names) {
    termsRow.innerHTML = "";
    const has = Array.isArray(names) && names.length > 0;
    termsLabel.hidden = !has;
    termsRow.hidden = !has;
    if (!has) return;
    for (const name of names) {
      const button = composeEl("button", null, name);
      button.type = "button";
      button.title = `Draft a new definition of ${name}`;
      // Loading a term loads its name only: the saved definition stays out of sight so
      // the revision is still written from memory.
      button.addEventListener("click", () => {
        term.value = name;
        markInteraction();
        refresh();
        draft.focus();
      });
      termsRow.appendChild(button);
    }
  }

  const instruction = composeEl(
    "p",
    "compose-instruction",
    "Define it from memory, in your own words, in one or two sentences."
  );

  const draft = composeEl("textarea", "compose-draft");
  draft.rows = 5;
  draft.placeholder = "Write from memory.";

  const rating = composeConfidence((value) => {
    if (pending || checked) return;
    markInteraction();
    confidence = value;
    refresh();
  });

  const actions = composeEl("div", "compose-actions");
  const submit = composeEl("button", "btn btn-primary", "Check my definition");
  submit.type = "button";
  submit.disabled = true;
  actions.appendChild(submit);

  renderTermsList(targets.glossary_terms);
  panel.append(
    termLabel, term, termsLabel, termsRow, instruction, draft, rating.label, rating.group, actions
  );

  function markInteraction() {
    if (firstInteraction === null) firstInteraction = Date.now();
  }

  function refresh() {
    submit.disabled =
      pending ||
      checked ||
      term.value.trim().length === 0 ||
      confidence === null ||
      draft.value.trim().length < COMPOSE_DEFINE_MIN_CHARS;
  }

  term.addEventListener("input", () => {
    markInteraction();
    refresh();
  });
  draft.addEventListener("focus", markInteraction);
  draft.addEventListener("input", () => {
    markInteraction();
    refresh();
  });

  let statusLine = null;
  function setPending(on) {
    pending = on;
    term.disabled = on;
    draft.disabled = on;
    rating.buttons.forEach((button) => {
      button.disabled = on;
    });
    refresh();
    if (on) {
      statusLine = composeEl("p", "compose-status");
      statusLine.appendChild(composeSquare(""));
      statusLine.appendChild(document.createTextNode("Checking…"));
      panel.appendChild(statusLine);
    } else if (statusLine) {
      statusLine.remove();
      statusLine = null;
    }
  }

  submit.addEventListener("click", async () => {
    if (pending || checked) return;
    if (errorLine) {
      errorLine.remove();
      errorLine = null;
    }
    const sentConfidence = confidence;
    const payload = {
      course: state.course,
      term: term.value.trim(),
      draft: draft.value.trim(),
      confidence: sentConfidence,
      latency_ms: Date.now() - (firstInteraction !== null ? firstInteraction : renderTs),
    };
    setPending(true);
    try {
      const res = await api("/api/compose/define", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await res.json();
      setPending(false);
      checked = true;
      rating.buttons.forEach((button) => {
        button.disabled = true;
      });
      actions.remove();
      panel.appendChild(renderDefineCritique(result, sentConfidence));
      // The draft goes back to being editable: the critique is a target to revise
      // against, and what gets saved is whatever the learner ends up writing.
      panel.appendChild(renderSaveRow(term, draft, renderTermsList));
      refreshSidebarPractice();
    } catch (e) {
      setPending(false);
      errorLine = composeEl(
        "p",
        "compose-error",
        `Couldn't check this definition: ${e.message}. Your writing is still in the box; retry.`
      );
      panel.appendChild(errorLine);
    }
  });

  return panel;
}

function renderDefineCritique(result, confidence) {
  const block = composeEl("div", "compose-critique");
  const band = COMPOSE_BANDS.define[result.verdict] || {
    label: result.verdict,
    word: result.verdict,
    fill: "",
  };

  block.appendChild(composeFeedbackList(result.feedback));

  const reference = composeEl("div", "compose-reference");
  reference.appendChild(composeEl("span", "compose-label", "A reference definition"));
  reference.appendChild(composeEl("p", null, result.reference_definition || ""));
  reference.appendChild(
    composeEl(
      "p",
      "compose-hierarchy",
      "Yours is the entry that will be saved. This is only a comparison target."
    )
  );
  block.appendChild(reference);

  const questions = composeEl("div", "compose-coverage");
  if (composeGroup(questions, "Questions to put to your draft", result.discrepancies)) {
    block.appendChild(questions);
  }

  composeCalibration(
    block,
    confidence,
    band,
    "A definition that misses at high confidence is the signal worth the most attention: it marks where your sense of knowing and your knowledge disagree."
  );
  return block;
}

// The revision affordance: the learner's own words go to GLOSSARY.md, and the row says
// so. Saving replaces itself with a confirmation rather than staying armed.
function renderSaveRow(term, draft, renderTermsList) {
  const wrap = composeEl("div", "compose-save");

  const avoidLabel = composeEl("label", "compose-label", "Aliases to avoid (optional)");
  avoidLabel.htmlFor = "compose-avoid";
  const avoid = composeEl("input", "compose-term");
  avoid.type = "text";
  avoid.id = "compose-avoid";
  avoid.placeholder = "Other words for this, kept out of use";

  const actions = composeEl("div", "compose-actions");
  const save = composeEl("button", "btn btn-primary", "Save to glossary");
  save.type = "button";
  actions.appendChild(save);

  const note = composeEl("p", "compose-note", "Saved in your words, not the reference version.");
  wrap.append(avoidLabel, avoid, actions, note);

  save.addEventListener("click", async () => {
    save.disabled = true;
    const existingError = wrap.querySelector(".compose-error");
    if (existingError) existingError.remove();
    try {
      await api("/api/glossary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course: state.course,
          term: term.value.trim(),
          definition: draft.value.trim(),
          avoid: avoid.value.trim() || null,
        }),
      });
      wrap.innerHTML = "";
      wrap.appendChild(composeEl("p", "compose-note", "Saved to GLOSSARY.md."));
      draft.readOnly = true;
      draft.classList.add("locked");
      const res = await api(`/api/compose-targets?course=${encodeURIComponent(state.course)}`);
      const targets = await res.json();
      renderTermsList(targets.glossary_terms);
    } catch (e) {
      save.disabled = false;
      wrap.appendChild(
        composeEl("p", "compose-error", `Couldn't save this entry: ${e.message}. Retry.`)
      );
    }
  });

  return wrap;
}

// Rendered-markdown links: external ones open in a new tab; course-relative ones open in
// the preview pane instead of navigating the app away.
function adoptProseLinks(prose) {
  prose.querySelectorAll("a[href]").forEach((a) => {
    const href = a.getAttribute("href");
    if (/^https?:\/\//i.test(href)) {
      a.target = "_blank";
      a.rel = "noopener";
    } else if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("#")) {
      // mailto: and friends, or in-page fragments — leave untouched
    } else {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        previewFile(href.replace(/^\.\//, ""), null);
      });
    }
  });
}

async function renameCourse(newSlug) {
  if (!newSlug || newSlug === state.course) return;
  try {
    await api(`/api/courses/${encodeURIComponent(state.course)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_slug: newSlug }),
    });
  } catch (e) {
    alert(`Couldn't rename course: ${e.message}`);
    return;
  }
  state.course = newSlug;
  await loadCourses();
  await selectCourse(newSlug);
}

async function archiveCourse() {
  if (!confirm("Archive this course? It moves to .archive/ and can be restored manually.")) return;
  try {
    await api(`/api/courses/${encodeURIComponent(state.course)}/archive`, { method: "POST" });
  } catch (e) {
    alert(`Couldn't archive course: ${e.message}`);
    return;
  }
  state.course = null;
  state.uploadedPdf = null;
  el("attach-label").style.display = "none";
  el("lesson-list").innerHTML = "";
  el("chat-thread").innerHTML = "";
  el("chat-header").textContent = "No course selected";
  el("mobile-course-name").textContent = "";
  clearPreview();
  refreshSidebarPractice(); // no course selected -> the section hides
  await loadCourses(); // auto-selects the first remaining course, if any
}

// --- Settings view -----------------------------------------------------------

// The settings page renders in the reading pane, same pattern as the course overview
// (on mobile it lives in the Preview tab). It re-fetches /api/settings on open so the
// form always starts from what the server actually has.
async function openSettings() {
  document.querySelectorAll("#lesson-list .selected").forEach((n) => n.classList.remove("selected"));
  state.preview = { kind: "settings" };
  el("preview-title").textContent = "Settings";
  if (MOBILE_QUERY.matches) setPane("preview");
  setPreviewCollapsed(false); // requested content must never render into a hidden pane
  const body = el("preview-body");
  try {
    const res = await api("/api/settings");
    state.settings = await res.json();
    body.innerHTML = "";
    body.appendChild(renderSettings(state.settings));
  } catch (e) {
    body.innerHTML = `<div id="preview-placeholder">Couldn't load settings: ${escapeHtml(e.message)}</div>`;
  }
}

function renderSettings(data) {
  const root = document.createElement("div");
  root.className = "overview settings";

  const header = document.createElement("header");
  header.className = "overview-header";
  const h1 = document.createElement("h1");
  h1.className = "overview-title";
  h1.textContent = "Settings";
  header.appendChild(h1);
  root.appendChild(header);

  const modelById = new Map(data.models.map((m) => [m.id, m]));

  const makeSection = (heading) => {
    const section = document.createElement("section");
    section.className = "overview-section";
    const h2 = document.createElement("h2");
    h2.textContent = heading;
    section.appendChild(h2);
    root.appendChild(section);
    return section;
  };

  const makeNote = (text) => {
    const p = document.createElement("p");
    p.className = "settings-note";
    p.textContent = text;
    return p;
  };

  const makeField = (labelText, inputId, control) => {
    const field = document.createElement("div");
    field.className = "settings-field";
    const label = document.createElement("label");
    label.htmlFor = inputId;
    label.textContent = labelText;
    control.id = inputId;
    field.append(label, control);
    return field;
  };

  // Models: two selects over the same catalog, each echoing its selection's price.
  const modelsSection = makeSection("Models");

  const makeModelSelect = (selectedId) => {
    const select = document.createElement("select");
    for (const m of data.models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.label;
      opt.selected = m.id === selectedId;
      select.appendChild(opt);
    }
    const price = makeNote(modelById.get(select.value)?.price || "");
    select.addEventListener("change", () => {
      price.textContent = modelById.get(select.value)?.price || "";
    });
    return { select, price };
  };

  const chatModel = makeModelSelect(data.chat_model);
  const chatField = makeField("Teaching model", "setting-chat-model", chatModel.select);
  chatField.appendChild(chatModel.price);

  const gradingModel = makeModelSelect(data.grading_model);
  const gradingField = makeField("Grading model", "setting-grading-model", gradingModel.select);
  gradingField.appendChild(gradingModel.price);
  gradingField.appendChild(
    makeNote("Grading is a rubric-check task; a smaller model here is the main cost lever.")
  );

  modelsSection.append(chatField, gradingField);

  // Layout: remember-sizes preference plus the two configured pane defaults.
  const layoutSection = makeSection("Layout");

  const rememberField = document.createElement("div");
  rememberField.className = "settings-field";
  const rememberLabel = document.createElement("label");
  rememberLabel.className = "settings-check";
  const rememberInput = document.createElement("input");
  rememberInput.type = "checkbox";
  rememberInput.id = "setting-remember-sizes";
  rememberInput.checked = data.layout.remember_sizes;
  rememberLabel.append(rememberInput, "Remember pane sizes");
  rememberField.append(rememberLabel, makeNote("Off: every session starts at the defaults below."));

  const makeWidthInput = (value, min, max) => {
    const input = document.createElement("input");
    input.type = "number";
    input.min = String(min);
    input.max = String(max);
    input.step = "1";
    input.value = String(value);
    return input;
  };

  const sidebarInput = makeWidthInput(data.layout.sidebar_w, RAIL.sidebar.min, RAIL.sidebar.max);
  const sidebarField = makeField("Sidebar width", "setting-sidebar-w", sidebarInput);
  sidebarField.appendChild(makeNote(`${RAIL.sidebar.min}–${RAIL.sidebar.max} px`));

  const chatInput = makeWidthInput(data.layout.chat_w, RAIL.chat.min, RAIL.chat.max);
  const chatWidthField = makeField("Chat width", "setting-chat-w", chatInput);
  chatWidthField.appendChild(makeNote(`${RAIL.chat.min}–${RAIL.chat.max} px`));

  const restoreField = document.createElement("div");
  restoreField.className = "settings-field";
  const restoreBtn = document.createElement("button");
  restoreBtn.className = "btn btn-secondary";
  restoreBtn.textContent = "Restore safe defaults";
  restoreBtn.addEventListener("click", () => {
    sidebarInput.value = "250";
    chatInput.value = "460";
    clearStoredPaneSizes();
    railSync.sidebar?.(setPaneWidth("sidebar", 250));
    railSync.chat?.(setPaneWidth("chat", 460));
  });
  restoreField.appendChild(restoreBtn);

  layoutSection.append(rememberField, sidebarField, chatWidthField, restoreField);

  // Save row: the page's one primary, a quiet inline confirmation, and the existing
  // error-text pattern for anything the server rejects.
  const saveRow = document.createElement("div");
  saveRow.className = "settings-save-row";
  const saveBtn = document.createElement("button");
  saveBtn.className = "btn btn-primary";
  saveBtn.textContent = "Save settings";
  const savedNote = document.createElement("span");
  savedNote.className = "settings-note";
  savedNote.textContent = "Saved.";
  savedNote.hidden = true;
  saveRow.append(saveBtn, savedNote);

  const errorNote = document.createElement("div");
  errorNote.className = "settings-error";
  errorNote.hidden = true;

  saveBtn.addEventListener("click", async () => {
    savedNote.hidden = true;
    errorNote.hidden = true;
    saveBtn.disabled = true;
    const payload = {
      chat_model: chatModel.select.value,
      grading_model: gradingModel.select.value,
      layout: {
        remember_sizes: rememberInput.checked,
        sidebar_w: parseInt(sidebarInput.value, 10),
        chat_w: parseInt(chatInput.value, 10),
      },
    };
    try {
      const res = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const saved = await res.json();
      state.settings = { ...saved, models: data.models };
      // Models need nothing further client-side (the server reads them at request
      // time); the layout defaults apply to the live panes now — with remembered
      // sizes active, applyLayoutSettings keeps those instead.
      applyLayoutSettings(saved.layout);
      savedNote.hidden = false;
    } catch (e) {
      errorNote.textContent = `Couldn't save: ${e.message}`;
      errorNote.hidden = false;
    } finally {
      saveBtn.disabled = false;
    }
  });

  root.append(saveRow, errorNote);
  return root;
}

// --- Chat -----------------------------------------------------------

function renderTurn(turn) {
  const thread = el("chat-thread");
  if (turn.text) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${turn.role}`;
    bubble.textContent = turn.text;
    thread.appendChild(bubble);
  }
  if (turn.activity && turn.activity.length > 0) {
    const log = document.createElement("div");
    log.className = "activity-log";
    for (const call of turn.activity) {
      const line = document.createElement("div");
      line.textContent = describeToolCall(call);
      log.appendChild(line);
    }
    thread.appendChild(log);
  }
}

function describeToolCall(call) {
  const input = call.input || {};
  switch (call.name) {
    case "write_file":
      return `wrote ${input.relative_path}`;
    case "read_file":
      return `read ${input.relative_path}`;
    case "list_dir":
      return `listed ${input.relative_path || "."}`;
    default:
      return `${call.name}(${JSON.stringify(input)})`;
  }
}

async function loadChatHistory(slug) {
  const thread = el("chat-thread");
  thread.innerHTML = "";
  try {
    const res = await api(`/api/chat-history?course=${encodeURIComponent(slug)}`);
    const { turns } = await res.json();
    if (turns.length === 0) {
      const note = document.createElement("div");
      note.className = "bubble system";
      note.textContent = "No conversation yet. Say hello to start the mission interview.";
      thread.appendChild(note);
    } else {
      turns.forEach(renderTurn);
    }
    thread.scrollTop = thread.scrollHeight;
  } catch (e) {
    thread.innerHTML = `<div class="bubble system">Couldn't load history: ${escapeHtml(e.message)}</div>`;
  }
}

async function sendMessage() {
  const input = el("chat-input");
  const message = input.value.trim();
  if (!message || !state.course) return;

  const attachChecked = el("attach-checkbox").checked;
  const attachPdf = attachChecked ? state.uploadedPdf : null;

  input.value = "";
  el("send-btn").disabled = true;

  const thread = el("chat-thread");
  const userBubble = document.createElement("div");
  userBubble.className = "bubble user";
  userBubble.textContent = message + (attachPdf ? `\n\n[attaching ${attachPdf}]` : "");
  thread.appendChild(userBubble);
  thread.scrollTop = thread.scrollHeight;

  const pending = document.createElement("div");
  pending.className = "bubble system thinking";
  pending.textContent = "Thinking...";
  thread.appendChild(pending);
  thread.scrollTop = thread.scrollHeight;

  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course: state.course, message, attach_pdf: attachPdf }),
    });
    const data = await res.json();
    pending.remove();
    renderTurn({ role: "assistant", text: data.reply, activity: data.activity });
    if (attachPdf) {
      el("attach-checkbox").checked = false;
    }
    await refreshCourseView();
  } catch (e) {
    pending.classList.remove("thinking"); // the square glyph marks a pending reply, not an error
    pending.textContent = `Error: ${e.message}`;
    // A turn the model never answered is not kept in the history, because the API requires
    // alternating roles and an unanswered turn would break the next request. The learner's
    // words are theirs, though, so they go back in the box to be sent again or edited.
    if (!input.value.trim()) {
      input.value = message;
    }
  } finally {
    el("send-btn").disabled = false;
    thread.scrollTop = thread.scrollHeight;
  }
}

// --- Upload -----------------------------------------------------------

async function uploadPdf() {
  const fileInput = el("upload-input");
  const file = fileInput.files[0];
  if (!file || !state.course) return;

  const status = el("upload-status");
  status.textContent = "Uploading...";

  const form = new FormData();
  form.append("course", state.course);
  form.append("file", file);

  try {
    const res = await api("/api/upload", { method: "POST", body: form });
    const data = await res.json();
    state.uploadedPdf = data.path;
    status.textContent = `Uploaded ${data.path}`;
    el("attach-filename").textContent = data.path;
    el("attach-label").style.display = "inline-flex";
    el("attach-checkbox").checked = true;
    fileInput.value = "";
    await refreshCourseView();
  } catch (e) {
    status.textContent = `Upload failed: ${e.message}`;
  }
}

// --- Mobile pane tabs -----------------------------------------------------------

const MOBILE_QUERY = window.matchMedia("(max-width: 900px)");

function setPane(pane) {
  el("app").dataset.pane = pane;
  document.querySelectorAll("#mobile-tabs .tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.pane === pane);
  });
}

document.querySelectorAll("#mobile-tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => setPane(tab.dataset.pane));
});

// --- Pane rails and preview collapse (desktop >900px) ---------------------------

// Clamp ranges for the drag rails, in px (mirrored by the backend's settings
// validation). The pane-width DEFAULTS start from style.css (:root --sidebar-w /
// --chat-w) and are overwritten by the platform settings once /api/settings loads;
// remembered sizes (layout.remember_sizes) persist to localStorage on resize end,
// otherwise sizes reset to the configured defaults on reload.
const RAIL = {
  sidebar: { min: 220, max: 320 },
  chat: { min: 380, max: 620 },
  previewMin: 420, // the reading pane (the flexing center) never drops below this while dragging
  step: 16, // arrow-key increment
};

const PANE_STORAGE_KEY = "keating.pane-sizes";

function readPaneWidth(which) {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(`--${which}-w`));
}

const PANE_DEFAULTS = {
  sidebar: readPaneWidth("sidebar"),
  chat: readPaneWidth("chat"),
};

// Each rail registers its aria-valuenow updater here so settings-driven width changes
// (which bypass the rail's own handlers) keep the accessibility values in sync.
const railSync = {};

function storedPaneSizes() {
  try {
    const raw = localStorage.getItem(PANE_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function clearStoredPaneSizes() {
  localStorage.removeItem(PANE_STORAGE_KEY);
}

// Called at the end of every drag/keyboard resize: a no-op unless the "remember pane
// sizes" preference is on.
function persistPaneSizes() {
  if (!state.settings || !state.settings.layout.remember_sizes) return;
  localStorage.setItem(
    PANE_STORAGE_KEY,
    JSON.stringify({ sidebar: readPaneWidth("sidebar"), chat: readPaneWidth("chat") })
  );
}

// Applies a layout settings object to the live panes: the configured widths become the
// rails' reset targets, and either the remembered sizes (clamped) or the configured
// defaults are applied. remember_sizes off also clears anything remembered.
function applyLayoutSettings(layout) {
  PANE_DEFAULTS.sidebar = layout.sidebar_w;
  PANE_DEFAULTS.chat = layout.chat_w;
  let sizes = null;
  if (layout.remember_sizes) {
    sizes = storedPaneSizes();
  } else {
    clearStoredPaneSizes();
  }
  // Widths only apply on desktop: mobile's tabbed layout ignores the pane vars, and
  // setPaneWidth's viewport clamp would mangle them against a phone-width #app.
  if (MOBILE_QUERY.matches) return;
  const applied = {
    sidebar: setPaneWidth("sidebar", (sizes && sizes.sidebar) || layout.sidebar_w),
    chat: setPaneWidth("chat", (sizes && sizes.chat) || layout.chat_w),
  };
  for (const which of ["sidebar", "chat"]) {
    if (railSync[which]) railSync[which](applied[which]);
  }
}

async function loadSettings() {
  const res = await api("/api/settings");
  state.settings = await res.json();
  applyLayoutSettings(state.settings.layout);
}

// Clamps to the pane's own rails AND dynamically caps so the reading pane keeps
// >= previewMin at the current viewport width. Returns the width actually applied.
function setPaneWidth(which, px) {
  const other = which === "sidebar" ? readPaneWidth("chat") : readPaneWidth("sidebar");
  const dynamicMax = Math.min(RAIL[which].max, el("app").clientWidth - other - RAIL.previewMin);
  const clamped = Math.max(RAIL[which].min, Math.min(dynamicMax, px));
  document.documentElement.style.setProperty(`--${which}-w`, `${clamped}px`);
  return clamped;
}

// direction: +1 if dragging right grows this pane (sidebar), -1 if it shrinks it (chat,
// whose rail sits on its left edge — so dragging the pointer left grows chat).
function initRail(railId, which, direction) {
  const rail = el(railId);
  rail.setAttribute("aria-valuemin", String(RAIL[which].min));
  rail.setAttribute("aria-valuemax", String(RAIL[which].max));
  const setNow = (px) => rail.setAttribute("aria-valuenow", String(Math.round(px)));
  setNow(readPaneWidth(which));
  railSync[which] = setNow;

  let drag = null; // {x: pointerdown clientX, w: pane width at pointerdown}
  rail.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    rail.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, w: readPaneWidth(which) };
    rail.classList.add("dragging");
    document.body.classList.add("rail-dragging"); // kills text selection + iframe pointer-events
  });
  rail.addEventListener("pointermove", (e) => {
    if (!drag) return;
    setNow(setPaneWidth(which, drag.w + direction * (e.clientX - drag.x)));
  });
  const endDrag = () => {
    if (!drag) return;
    drag = null;
    rail.classList.remove("dragging");
    document.body.classList.remove("rail-dragging");
    persistPaneSizes();
  };
  rail.addEventListener("pointerup", endDrag);
  rail.addEventListener("pointercancel", endDrag);

  rail.addEventListener("dblclick", () => {
    setNow(setPaneWidth(which, PANE_DEFAULTS[which]));
    persistPaneSizes();
  });
  rail.addEventListener("keydown", (e) => {
    // Arrows move the boundary itself: right widens whichever pane sits left of the rail.
    let delta = null;
    if (e.key === "ArrowRight") delta = RAIL.step;
    else if (e.key === "ArrowLeft") delta = -RAIL.step;
    if (delta !== null) {
      e.preventDefault();
      setNow(setPaneWidth(which, readPaneWidth(which) + direction * delta));
      persistPaneSizes();
    } else if (e.key === "Home") {
      e.preventDefault();
      setNow(setPaneWidth(which, PANE_DEFAULTS[which]));
      persistPaneSizes();
    }
  });
}

function setPreviewCollapsed(collapsed) {
  el("app").classList.toggle("preview-collapsed", collapsed);
}

initRail("rail-sidebar", "sidebar", 1);
initRail("rail-chat", "chat", -1);
el("preview-hide").addEventListener("click", () => setPreviewCollapsed(true));
el("preview-reopen").addEventListener("click", () => setPreviewCollapsed(false));

// --- Utilities -----------------------------------------------------------

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// --- Wiring -----------------------------------------------------------

el("new-course-btn").addEventListener("click", createCourse);
el("new-course-slug").addEventListener("keydown", (e) => {
  if (e.key === "Enter") createCourse();
});

el("send-btn").addEventListener("click", sendMessage);
el("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

el("upload-btn").addEventListener("click", uploadPdf);

el("settings-link").addEventListener("click", openSettings);

// The sidebar Practice heading and summary line both open the full practice page in
// the reading pane; the rows below them keep their own job (opening source lessons).
makeActivatable(document.querySelector("#practice-section h2"), () => openPracticeView());
makeActivatable(el("practice-sidebar-summary"), () => openPracticeView());
// The review line (rendered only while items are due) opens Today's review instead, and
// the weekly line below it opens the weekly session. Wired once here — refreshSidebarPractice
// only toggles their content and visibility.
makeActivatable(el("practice-sidebar-review"), () => openReviewView());
makeActivatable(el("practice-sidebar-weekly"), () => openWeeklyView());
// Compose sits below both review lines and opens the artifact surface in the reading
// pane; unlike them it is present for any selected course, event log or not.
makeActivatable(el("practice-sidebar-compose"), () => openComposeView());

// Practice state changes inside the preview iframe, which announces them by postMessage
// so the practice views refresh live instead of waiting for the next course-level refresh.
// Two announcements: quiz.js sends keating:attempt on each completed attempt (which also
// covers weekly attempts — they close the week server-side), and the weekly page sends
// keating:weekly-session when the learner marks the review held. Debounced: a burst
// refetches once.
const PRACTICE_REFRESH_MESSAGES = new Set(["keating:attempt", "keating:weekly-session"]);
let practiceRefreshTimer = null;
window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  if (!event.data || !PRACTICE_REFRESH_MESSAGES.has(event.data.type)) return;
  clearTimeout(practiceRefreshTimer);
  practiceRefreshTimer = setTimeout(() => {
    practiceRefreshTimer = null;
    refreshSidebarPractice();
    if (state.preview && state.preview.kind === "practice") {
      openPracticeView({ switchPane: false });
    }
  }, 500);
});

// --- The session gate ---------------------------------------------------------

// The 500ms practice refresh keeps firing after a session ends unless it is stopped, which
// leaves a logged-out tab asking the API for a learner's practice state twice a second
// forever. Held here so showLogin can cancel it.
function stopBackgroundRefreshes() {
  clearTimeout(practiceRefreshTimer);
  practiceRefreshTimer = null;
}

// Exactly one of the two views is ever visible. Hiding #app takes the five preview iframes
// with it, so no stale learner content and no stale 401 document sits behind the form.
function showLogin(session) {
  stopBackgroundRefreshes();
  el("app").hidden = true;
  el("login").hidden = false;
  const bootstrapped = session && session.bootstrapped;
  el("login-setup").hidden = bootstrapped;
  el("login-form").hidden = !bootstrapped;
  el("login-invite").hidden = true;
  if (bootstrapped) el("login-username").focus();
}

function showApp(session) {
  el("login").hidden = true;
  el("app").hidden = false;
  el("signed-in-username").textContent = session.username || "";
}

function showLoginError(id, message) {
  const line = el(id);
  line.textContent = message;
  line.hidden = false;
}

// A real submit handler on a real <form>: preventDefault means navigation never starts, so
// form-action 'none' is never engaged, and the form keeps Enter-to-submit and the label and
// role="alert" semantics a synthesised click handler would lose.
el("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  el("login-error").hidden = true;
  const submit = el("login-submit");
  submit.disabled = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: el("login-username").value,
        password: el("login-password").value,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showLoginError("login-error", body.detail || "Sign in failed.");
      return;
    }
    // A full reload rather than an in-place re-render. Signing in as a different account
    // would otherwise inherit the previous account's rendered lesson list, practice rows and
    // chat pane — a leak in the DOM even though the server leaked nothing (charter P25).
    location.reload();
  } catch (e) {
    showLoginError("login-error", "Sign in failed: " + e.message);
  } finally {
    submit.disabled = false;
  }
});

el("login-invite").addEventListener("submit", async (event) => {
  event.preventDefault();
  el("invite-error").hidden = true;
  try {
    const res = await fetch("/api/invite/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: el("invite-code").value,
        username: el("invite-username").value,
        password: el("invite-password").value,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      showLoginError("invite-error", body.detail || "That invite could not be redeemed.");
      return;
    }
    // Redeeming does not sign the account in, so the sign-in form is where it lands next.
    el("login-invite").hidden = true;
    el("login-form").hidden = false;
    el("login-username").value = body.username || "";
    el("login-password").focus();
  } catch (e) {
    showLoginError("invite-error", "That invite could not be redeemed: " + e.message);
  }
});

el("login-show-invite").addEventListener("click", () => {
  el("login-form").hidden = true;
  el("login-invite").hidden = false;
  el("invite-code").focus();
});

el("invite-show-login").addEventListener("click", () => {
  el("login-invite").hidden = true;
  el("login-form").hidden = false;
  el("login-username").focus();
});

el("logout-link").addEventListener("click", async () => {
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch (e) {
    console.error("logout:", e);
  }
  location.reload();
});

// The session is resolved before any other fetch, so a signed-out visit shows the form
// rather than an empty shell. Settings load second so the panes take their configured (or
// remembered) widths before the first paint settles; a failed fetch just leaves the CSS
// initial values in place.
(async () => {
  let session;
  try {
    session = await (await fetch("/api/session")).json();
  } catch (e) {
    console.error("session:", e);
    showLogin({ authenticated: false, bootstrapped: true });
    return;
  }
  if (!session.authenticated) {
    showLogin(session);
    return;
  }
  showApp(session);
  try {
    await loadSettings();
  } catch (e) {
    if (!(e instanceof AuthError)) console.error("loadSettings:", e);
  }
  // Awaited and caught: an unhandled rejection here is exactly how a logged-out app comes to
  // render "No course selected" and look merely empty rather than signed out.
  try {
    await loadCourses();
  } catch (e) {
    if (!(e instanceof AuthError)) console.error("loadCourses:", e);
  }
})();
