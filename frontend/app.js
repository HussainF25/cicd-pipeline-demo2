// PRESENTATION TIER - talks to the backend only through the REST API (JSON),
// sending the login token (JWT) with every request.
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const state = { students: [], courses: [], summary: [], results: [], roster: {}, notifications: [], seen: 0, editing: null, profile: null };
const TOKEN_KEY = "sms_token";

// ---------- API helper ----------
async function api(method, path, body, { quiet = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const json = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/api/login") { signOut("Your session has ended. Sign in again."); throw new Error("Signed out"); }
  if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Some values are invalid. Check them and try again.");
  if (!quiet) showTrace(method, path, json.trace || []);
  return json.data;
}

// ---------- system view (architecture strip, only at /?system) ----------
$("#system-strip").hidden = !new URLSearchParams(location.search).has("system");
function showTrace(method, path, trace) {
  $$(".path li").forEach((li) => li.classList.remove("on", "miss"));
  $('[data-node="browser"]').classList.add("on");
  const notes = [];
  trace.forEach((step) => {
    if (step === "cache") { $('[data-node="cache"]').classList.add("on"); notes.push("cache hit"); }
    else if (step === "cache-miss") { $('[data-node="cache"]').classList.add("miss"); notes.push("cache miss"); }
    else if (step === "cache-cleared") { $('[data-node="cache"]').classList.add("miss"); notes.push("cache cleared"); }
    else $(`[data-node="${step}"]`)?.classList.add("on");
    if (step === "queue") notes.push("emails queued, API replied without waiting");
  });
  $("#trace-text").textContent = `Last request: ${method} ${path.split("?")[0]}` + (notes.length ? ` (${notes.join(", ")})` : "");
}

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const TINTS = ["#1F4D3A", "#2F5F8A", "#8A4B2F", "#6B4C8A", "#9A6410", "#2E7472"];
const initials = (n) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
const tint = (n) => TINTS[[...n].reduce((a, c) => a + c.charCodeAt(0), 0) % TINTS.length];
const avatar = (n) => `<div class="avatar" style="--tint:${tint(n)}">${esc(initials(n))}</div>`;
const person = (n, line) => `<div class="person">${avatar(n)}<div><strong>${esc(n)}</strong><span>${esc(line)}</span></div></div>`;
const grade = (m) => (m === "" || m == null || isNaN(m) ? "" : m >= 85 ? "A" : m >= 70 ? "B" : m >= 55 ? "C" : m >= 45 ? "D" : "F");
const toDate = (s) => new Date(s.replace(" ", "T") + "Z");
const fmtDate = (s) => toDate(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
const today = () => new Date().toISOString().slice(0, 10);
const byName = (a, b) => a.name.localeCompare(b.name);
const courseById = (id) => state.courses.find((c) => c.id === id);
const enrolledIn = (courseId) => state.students.filter((s) => s.course_ids.includes(courseId)).sort(byName);

function toast(text, isError = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(t._t);
  t._t = setTimeout(() => (t.className = ""), 3200);
}
async function run(fn) { try { await fn(); } catch (e) { if (e.message !== "Signed out") toast(e.message, true); } }
function downloadCSV(filename, rows) {
  const csv = rows.map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
document.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) e.target.closest("dialog").close(); });

// ---------- sign in / out ----------
function showLogin(message) {
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#login-error").hidden = !message;
  if (message) $("#login-error").textContent = message;
  $('#login-form [name="password"]').focus();
}
function signOut(message) {
  localStorage.removeItem(TOKEN_KEY);
  clearInterval(state.poller);
  closeDrawer();
  showLogin(message);
}
$("#signout").addEventListener("click", () => signOut());
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  try {
    const out = await api("POST", "/api/login", body);
    localStorage.setItem(TOKEN_KEY, out.token);
    e.target.password.value = "";
    await boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
    $("#login-error").hidden = false;
  }
});

// ---------- routing ----------
const PAGES = {
  students: { title: "Students", sub: () => `${state.students.length} enrolled across ${state.courses.length} courses` },
  attendance: { title: "Attendance", sub: () => "Take the class register and track attendance" },
  results: { title: "Results", sub: () => "Enter marks and publish grades to students" },
};
const currentView = () => (PAGES[location.hash.slice(1)] ? location.hash.slice(1) : "students");
async function route() {
  const view = currentView();
  $$(".nav-link").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $("#page-title").textContent = PAGES[view].title;
  $("#page-sub").textContent = PAGES[view].sub();
  if (view === "students") await run(refreshStudents);
  if (view === "attendance") await run(loadRoster);
  if (view === "results") await run(() => loadGradebook());
}
window.addEventListener("hashchange", route);

// ---------- loaders ----------
async function loadCourses(quiet = false) {
  state.courses = await api("GET", "/api/courses", null, { quiet });
  const opts = state.courses.map((c) => `<option value="${c.id}">${c.code} ${esc(c.title)}</option>`).join("");
  $$(".course-select").forEach((s) => { const v = s.value; s.innerHTML = opts; if (v && courseById(+v)) s.value = v; });
}
const loadStudents = async (quiet = true) => (state.students = await api("GET", "/api/students", null, { quiet }));
const loadSummary = async () => (state.summary = await api("GET", "/api/attendance/summary", null, { quiet: true }));
const loadResults = async (quiet = true) => (state.results = await api("GET", "/api/results", null, { quiet }));

// ---------- STUDENTS ----------
function overallAttendance(id) {
  const rows = state.summary.filter((r) => r.student_id === id);
  if (!rows.length) return null;
  const att = rows.reduce((a, r) => a + r.attended, 0), tot = rows.reduce((a, r) => a + r.total, 0);
  return Math.round((100 * att) / tot);
}
async function refreshStudents() {
  await loadStudents(false);
  await Promise.all([loadSummary(), loadResults()]);
  renderStudents();
}
function renderStudentStats() {
  const pcts = state.students.map((s) => overallAttendance(s.id)).filter((p) => p != null);
  const avg = pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : null;
  const risk = pcts.filter((p) => p < 75).length;
  const published = state.results.filter((r) => r.published).length;
  $("#student-stats").innerHTML = `
    <div><dt>Students</dt><dd>${state.students.length}</dd></div>
    <div><dt>Average attendance</dt><dd>${avg == null ? "–" : avg + "%"}</dd></div>
    <div><dt>Below 75% attendance</dt><dd class="${risk ? "risk" : ""}">${risk}</dd></div>
    <div><dt>Results published</dt><dd>${published}<small>of ${state.results.length} graded</small></dd></div>`;
}
function renderStudents() {
  renderStudentStats();
  const programs = [...new Set(state.students.map((s) => s.program))].sort();
  const pf = $("#program-filter"), keep = pf.value;
  pf.innerHTML = `<option value="">All programs</option>` + programs.map((p) => `<option>${esc(p)}</option>`).join("");
  if (programs.includes(keep)) pf.value = keep;

  const q = $("#student-search").value.trim().toLowerCase();
  const list = state.students.filter((s) =>
    (!pf.value || s.program === pf.value) &&
    (!q || s.name.toLowerCase().includes(q) || s.email.includes(q) || (s.roll_no || "").toLowerCase().includes(q)));
  $("#students-body").innerHTML = list.length
    ? list.map((s) => {
        const pct = overallAttendance(s.id);
        const att = pct == null ? `<span class="pill none">No classes yet</span>` : `<span class="pill ${pct < 75 ? "warn" : "ok"}">${pct}%</span>`;
        const tags = s.course_ids.length ? s.course_ids.map((id) => `<span class="tag">${esc(courseById(id)?.code)}</span>`).join("") : `<span class="muted">None</span>`;
        return `<tr tabindex="0" data-id="${s.id}" aria-label="Open ${esc(s.name)}"><td>${person(s.name, s.email)}</td><td>${esc(s.roll_no)}</td>
          <td>${esc(s.program)}</td><td><div class="tags">${tags}</div></td><td class="num">${att}</td></tr>`;
      }).join("")
    : `<tr><td colspan="5" class="empty"><strong>${q || pf.value ? "No students match" : "No students yet"}</strong>${q || pf.value ? "Try a different search or program." : "Add your first student to get started."}</td></tr>`;
  if (currentView() === "students") $("#page-sub").textContent = PAGES.students.sub();
}
$("#student-search").addEventListener("input", renderStudents);
$("#program-filter").addEventListener("change", renderStudents);
$("#students-body").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) run(() => openProfile(+tr.dataset.id)); });
$("#students-body").addEventListener("keydown", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr && e.key === "Enter") run(() => openProfile(+tr.dataset.id)); });
$("#export-students").addEventListener("click", () => {
  downloadCSV(`students-${today()}.csv`, [["Roll no", "Name", "Email", "Program", "Courses", "Attendance %", "Joined"],
    ...state.students.map((s) => [s.roll_no, s.name, s.email, s.program, s.course_ids.map((id) => courseById(id)?.code).join("; "),
      overallAttendance(s.id) ?? "", s.created_at.slice(0, 10)])]);
  toast("Student list downloaded.");
});

// add / edit dialog
function openStudentDialog(student = null) {
  state.editing = student;
  const f = $("#student-form");
  f.reset();
  $("#student-error").hidden = true;
  $("#student-dialog-title").textContent = student ? "Edit student" : "Add student";
  $("#student-dialog-sub").textContent = student ? `${student.roll_no}` : "They’ll get a welcome email with their roll number.";
  $("#student-submit").textContent = student ? "Save changes" : "Add student";
  if (student) {
    f.name.value = student.name; f.email.value = student.email;
    if (![...f.program.options].some((o) => o.value === student.program)) f.program.add(new Option(student.program));
    f.program.value = student.program;
  }
  const chosen = student ? student.course_ids : state.courses.map((c) => c.id);
  $("#course-checks").innerHTML = state.courses.length
    ? state.courses.map((c) => `<label><input type="checkbox" name="course" value="${c.id}" ${chosen.includes(c.id) ? "checked" : ""}> ${c.code} ${esc(c.title)}</label>`).join("")
    : `<span class="muted">No courses yet.</span>`;
  $("#student-dialog").showModal();
}
$("#open-add").addEventListener("click", () => openStudentDialog());
$("#student-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { name: f.name.value, email: f.email.value, program: f.program.value,
    course_ids: [...f.querySelectorAll('[name="course"]:checked')].map((i) => +i.value) };
  try {
    if (state.editing) {
      await api("PUT", `/api/students/${state.editing.id}`, body);
      toast("Changes saved.");
    } else {
      const out = await api("POST", "/api/students", body);
      toast(`${body.name} added as ${out.roll_no}. Welcome email on its way.`);
    }
    $("#student-dialog").close();
    await loadStudents(); await loadResults();
    renderStudents();
    if (state.editing && state.profile?.id === state.editing.id) await openProfile(state.editing.id, true);
  } catch (err) {
    if (err.message === "Signed out") return;
    $("#student-error").textContent = err.message;
    $("#student-error").hidden = false;
  }
});

// profile panel
async function openProfile(id, quiet = false) {
  const p = await api("GET", `/api/students/${id}`, null, { quiet });
  state.profile = p;
  const pct = overallAttendance(id);
  const cards = p.courses.length ? p.courses.map((c) => {
    const cp = c.total ? Math.round((100 * c.attended) / c.total) : null;
    const res = c.grade == null ? `<span class="pill none">Not graded</span>`
      : `<span class="grade g-${c.grade}">${c.grade}</span>`;
    const status = c.grade == null ? "" : c.published ? `<span class="pill ok">Published</span>` : `<span class="pill draft">Draft</span>`;
    return `<div class="course-card"><div class="top"><div><strong>${esc(c.code)} ${esc(c.title)}</strong>
      <span class="meta">${c.grade == null ? "No marks yet" : `${c.marks} marks`} ${status}</span></div>${res}</div>
      ${cp == null ? `<span class="muted small">No classes recorded yet</span>` :
      `<div class="bar-row ${cp < 75 ? "risk" : ""}"><span>Attendance, ${c.attended} of ${c.total} classes</span><span class="pct">${cp}%</span>
       <div class="bar"><i style="width:${cp}%"></i></div></div>`}</div>`;
  }).join("") : `<p class="muted">Not enrolled in any courses. Use Edit details to enrol them.</p>`;
  $("#drawer-body").innerHTML = `
    <div class="drawer-head">
      <button class="drawer-close" id="drawer-close" aria-label="Close profile"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
      ${avatar(p.name)}<h2>${esc(p.name)}</h2><p>${esc(p.email)}</p>
      <dl class="facts"><dt>Roll no.</dt><dd>${esc(p.roll_no)}</dd><dt>Program</dt><dd>${esc(p.program)}</dd>
        <dt>Joined</dt><dd>${fmtDate(p.created_at)}</dd><dt>Attendance</dt><dd>${pct == null ? "No classes yet" : pct + "% overall"}</dd></dl>
    </div>
    <div class="drawer-section"><h3>Courses</h3>${cards}</div>
    <div class="drawer-actions">
      <button class="btn ghost" id="p-edit">Edit details</button>
      <button class="btn ghost" id="p-print">Print transcript</button>
      <button class="btn danger-text" id="p-delete">Delete student</button>
    </div>`;
  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  $("#drawer-close").onclick = closeDrawer;
  $("#p-edit").onclick = () => openStudentDialog(state.students.find((s) => s.id === id));
  $("#p-print").onclick = () => printTranscript(p);
  $("#p-delete").onclick = () => {
    $("#confirm-text").textContent = `This permanently removes ${p.name} (${p.roll_no}) and all of their attendance and results.`;
    $("#confirm-dialog").showModal();
  };
  if (!quiet) $("#drawer-close").focus();
}
function closeDrawer() { $("#drawer").hidden = true; $("#drawer-backdrop").hidden = true; state.profile = null; }
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden && !document.querySelector("dialog[open]")) closeDrawer(); });
$("#confirm-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(async () => {
    const p = state.profile;
    await api("DELETE", `/api/students/${p.id}`);
    $("#confirm-dialog").close();
    closeDrawer();
    toast(`${p.name} has been deleted.`);
    await refreshStudents();
  });
});
function printTranscript(p) {
  const rowsHtml = p.courses.map((c) => `<tr><td>${esc(c.code)}</td><td>${esc(c.title)}</td>
    <td>${c.total ? Math.round((100 * c.attended) / c.total) + "%" : "–"}</td>
    <td>${c.published ? c.marks : "Pending"}</td><td>${c.published ? c.grade : "Pending"}</td></tr>`).join("");
  $("#print-area").innerHTML = `<h1>Northfield University</h1><p>Academic transcript</p>
    <div class="meta"><b>${esc(p.name)}</b><br>Roll no. ${esc(p.roll_no)}<br>${esc(p.program)}<br>${esc(p.email)}<br>Issued ${new Date().toLocaleDateString()}</div>
    <table><thead><tr><th>Code</th><th>Course</th><th>Attendance</th><th>Marks</th><th>Grade</th></tr></thead>
    <tbody>${rowsHtml || `<tr><td colspan="5">No courses</td></tr>`}</tbody></table>
    <p class="sig">Only published results are shown. Issued by the Registrar’s Office, Northfield University.</p>`;
  window.print();
}

// new course
$$(".new-course").forEach((b) => b.addEventListener("click", () => {
  $("#course-form").reset(); $("#course-error").hidden = true; $("#course-dialog").showModal();
}));
$("#course-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  try {
    const out = await api("POST", "/api/courses", body);
    $("#course-dialog").close();
    await loadCourses(true);
    $$(".course-select").forEach((s) => (s.value = out.id));
    toast(`${body.code.toUpperCase()} created. Enrol students from their profile.`);
    await route();
  } catch (err) {
    if (err.message === "Signed out") return;
    $("#course-error").textContent = err.message;
    $("#course-error").hidden = false;
  }
});

// ---------- ATTENDANCE ----------
async function loadRoster() {
  const courseId = +$("#att-course").value, date = $("#att-date").value;
  if (!courseId) return;
  const saved = await api("GET", `/api/attendance?course_id=${courseId}&date=${date}`);
  state.roster = {};
  enrolledIn(courseId).forEach((s) => (state.roster[s.id] = true));
  saved.forEach((r) => { if (r.student_id in state.roster) state.roster[r.student_id] = !!r.present; });
  renderRoster(saved.length > 0);
  await loadSummary();
  renderAttSummary();
}
function renderRoster(alreadySaved) {
  const list = enrolledIn(+$("#att-course").value);
  $("#roster").innerHTML = list.length
    ? list.map((s) => {
        const p = state.roster[s.id];
        return `<li>${person(s.name, s.roll_no)}
          <div class="toggle" role="group" aria-label="${esc(s.name)} attendance">
            <button type="button" class="present ${p ? "on" : ""}" data-id="${s.id}" data-v="1" aria-pressed="${p}">Present</button>
            <button type="button" class="absent ${!p ? "on" : ""}" data-id="${s.id}" data-v="0" aria-pressed="${!p}">Absent</button>
          </div></li>`;
      }).join("")
    : `<li class="empty"><div><strong>No students enrolled in this course</strong>Open a student on the Students page and use Edit details to enrol them.</div></li>`;
  $("#att-save").textContent = alreadySaved ? "Update attendance" : "Save attendance";
  $("#att-save").disabled = !list.length;
  updateAttCount();
}
function updateAttCount() {
  const vals = Object.values(state.roster);
  const present = vals.filter(Boolean).length;
  $("#att-count").textContent = vals.length ? `${present} present, ${vals.length - present} absent` : "";
}
$("#roster").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-id]");
  if (!b) return;
  state.roster[b.dataset.id] = b.dataset.v === "1";
  b.parentElement.querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
  updateAttCount();
});
$("#att-all").addEventListener("click", () => {
  Object.keys(state.roster).forEach((k) => (state.roster[k] = true));
  renderRoster($("#att-save").textContent.startsWith("Update"));
});
function renderAttSummary() {
  const courseId = +$("#att-course").value;
  const enrolled = new Set(enrolledIn(courseId).map((s) => s.id));
  const rows = state.summary.filter((r) => r.course_id === courseId && enrolled.has(r.student_id));
  $("#att-summary").innerHTML = rows.length
    ? rows.map((r) => `<li class="bar-row ${r.percentage < 75 ? "risk" : ""}">
        <span>${esc(r.name)}${r.percentage < 75 ? ' <span class="pill warn">At risk</span>' : ""}</span>
        <span class="pct">${r.percentage}%</span>
        <div class="bar" title="${r.attended} of ${r.total} classes"><i style="width:${r.percentage}%"></i></div></li>`).join("")
    : `<li class="muted">No classes recorded for this course yet.</li>`;
}
$("#att-course").addEventListener("change", () => run(loadRoster));
$("#att-date").addEventListener("change", () => run(loadRoster));
$("#att-save").addEventListener("click", () => run(async () => {
  const out = await api("POST", "/api/attendance/bulk", {
    course_id: +$("#att-course").value, date: $("#att-date").value,
    records: Object.entries(state.roster).map(([id, p]) => ({ student_id: +id, present: p })),
  });
  toast(out.at_risk ? `Attendance saved. ${out.at_risk} student(s) below 75% have been emailed.` : "Attendance saved.");
  $("#att-save").textContent = "Update attendance";
  await loadSummary();
  renderAttSummary();
}));

// ---------- RESULTS ----------
let resCourse = null;
async function loadGradebook(quiet = false) {
  await loadResults(quiet);
  renderGradebook();
}
function courseResults(courseId) {
  const enrolled = new Set(enrolledIn(courseId).map((s) => s.id));
  return state.results.filter((r) => r.course_id === courseId && enrolled.has(r.student_id));
}
function renderResultStats(courseId) {
  const res = courseResults(courseId);
  const marks = res.map((r) => r.marks);
  const avg = marks.length ? (marks.reduce((a, b) => a + b, 0) / marks.length).toFixed(1) : "–";
  const top = marks.length ? Math.max(...marks) : "–";
  const pass = marks.length ? Math.round((100 * marks.filter((m) => m >= 45).length) / marks.length) + "%" : "–";
  const counts = ["A", "B", "C", "D", "F"].map((g) => [g, res.filter((r) => r.grade === g).length]);
  const max = Math.max(1, ...counts.map((c) => c[1]));
  $("#result-stats").innerHTML = `
    <div><dt>Class average</dt><dd>${avg}</dd></div>
    <div><dt>Highest mark</dt><dd>${top}</dd></div>
    <div><dt>Pass rate</dt><dd>${pass}</dd></div>
    <div><dt>Grade spread</dt><dd class="dist">${counts.map(([g, n]) =>
      `<span class="${g === "F" ? "f" : ""}" title="${n} × ${g}"><i style="height:${(24 * n) / max}px"></i>${g}</span>`).join("")}</dd></div>`;
}
function renderGradebook() {
  const courseId = +$("#res-course").value;
  resCourse = courseId;
  const byStudent = Object.fromEntries(courseResults(courseId).map((r) => [r.student_id, r]));
  const list = enrolledIn(courseId);
  $("#gradebook").innerHTML = list.length
    ? list.map((s) => {
        const r = byStudent[s.id];
        const g = r ? r.grade : "";
        const status = !r ? `<span class="pill none">Not graded</span>` : r.published ? `<span class="pill ok">Published</span>` : `<span class="pill draft">Draft</span>`;
        return `<tr><td>${person(s.name, s.roll_no)}</td>
          <td><input class="marks-input" type="number" min="0" max="100" step="0.5" data-id="${s.id}" data-orig="${r ? r.marks : ""}" value="${r ? r.marks : ""}" aria-label="Marks for ${esc(s.name)}"></td>
          <td><span class="grade ${g ? "g-" + g : ""}">${g || "–"}</span></td><td>${status}</td></tr>`;
      }).join("")
    : `<tr><td colspan="4" class="empty"><strong>No students enrolled in this course</strong>Enrol students from their profile on the Students page.</td></tr>`;
  const graded = list.filter((s) => byStudent[s.id]).length;
  $("#res-count").textContent = list.length ? `${graded} of ${list.length} graded` : "";
  $("#res-publish").disabled = !Object.values(byStudent).some((r) => !r.published);
  renderResultStats(courseId);
}
$("#gradebook").addEventListener("input", (e) => {
  const inp = e.target.closest(".marks-input");
  if (!inp) return;
  const g = grade(inp.value === "" ? "" : +inp.value);
  const cell = inp.closest("tr").querySelector(".grade");
  cell.className = "grade " + (g ? "g-" + g : "");
  cell.textContent = g || "–";
  inp.classList.toggle("changed", inp.value !== inp.dataset.orig);
  $("#res-publish").disabled = false;
});
$("#res-course").addEventListener("change", (e) => {
  if (changedMarks().length && !confirm("You have unsaved marks for this course. Switch course and discard them?")) {
    e.target.value = resCourse;
    return;
  }
  renderGradebook();
});
window.addEventListener("beforeunload", (e) => { if (currentView() === "results" && changedMarks().length) e.preventDefault(); });

function changedMarks() {
  return [...$$(".marks-input")].filter((i) => i.value !== "" && i.value !== i.dataset.orig)
    .map((i) => ({ student_id: +i.dataset.id, marks: +i.value }));
}
async function saveMarks() {
  const marks = changedMarks();
  if (!marks.length) return 0;
  if (marks.some((m) => m.marks < 0 || m.marks > 100)) throw new Error("Marks must be between 0 and 100.");
  await api("POST", "/api/results/bulk", { course_id: +$("#res-course").value, marks });
  return marks.length;
}
$("#res-save").addEventListener("click", () => run(async () => {
  const n = await saveMarks();
  toast(n ? `Marks saved for ${n} student(s).` : "No changes to save.");
  await loadGradebook(true);
}));
$("#res-publish").addEventListener("click", () => run(async () => {
  await saveMarks();
  const out = await api("POST", "/api/results/publish", { course_id: +$("#res-course").value });
  toast(out.published ? `Results published. ${out.published} student(s) are being emailed.` : "These results are already published.");
  await loadGradebook(true);
}));
$("#export-results").addEventListener("click", () => {
  const c = courseById(+$("#res-course").value);
  const byStudent = Object.fromEntries(courseResults(c.id).map((r) => [r.student_id, r]));
  downloadCSV(`results-${c.code}-${today()}.csv`, [["Roll no", "Name", "Course", "Marks", "Grade", "Status"],
    ...enrolledIn(c.id).map((s) => { const r = byStudent[s.id];
      return [s.roll_no, s.name, c.code, r?.marks ?? "", r?.grade ?? "", !r ? "Not graded" : r.published ? "Published" : "Draft"]; })]);
  toast(`${c.code} results downloaded.`);
});

// ---------- notifications (written by the background worker) ----------
async function loadNotifications() {
  const items = await api("GET", "/api/notifications", null, { quiet: true });
  if (state.notifications.length && items.length && items[0].id !== state.notifications[0]?.id) {
    const w = $('[data-node="worker"]');
    w.classList.add("on");
    setTimeout(() => w.classList.remove("on"), 1200);
  }
  const newest = items[0]?.id || 0;
  state.notifications = items;
  const unseen = items.filter((n) => n.id > state.seen).length;
  $("#bell-badge").hidden = unseen <= 0 || !$("#notif-panel").hidden;
  $("#bell-badge").textContent = unseen > 9 ? "9+" : unseen;
  $("#notif-list").innerHTML = items.length
    ? items.map((n) => `<li>${esc(n.message)}<small>To ${esc(n.recipient)}, ${toDate(n.created_at).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</small></li>`).join("")
    : `<li class="muted">No emails sent yet.</li>`;
  return newest;
}
$("#bell").addEventListener("click", (e) => {
  e.stopPropagation();
  const panel = $("#notif-panel");
  panel.hidden = !panel.hidden;
  $("#bell").setAttribute("aria-expanded", !panel.hidden);
  if (!panel.hidden) { state.seen = state.notifications[0]?.id || 0; $("#bell-badge").hidden = true; }
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#notif-panel")) { $("#notif-panel").hidden = true; $("#bell").setAttribute("aria-expanded", "false"); }
});

// ---------- start ----------
async function boot() {
  try {
    const me = await api("GET", "/api/me", null, { quiet: true });
    $("#user-name").textContent = me.name;
    $("#user-role").textContent = me.role;
    $("#user-initials").textContent = initials(me.name);
    $("#login").hidden = true;
    $("#app").hidden = false;
    $("#att-date").value = today();
    await loadCourses();
    await loadStudents();
    state.seen = await loadNotifications();
    $("#bell-badge").hidden = true;
    clearInterval(state.poller);
    state.poller = setInterval(() => loadNotifications().catch(() => {}), 2500);
    await route();
  } catch (e) {
    if (e.message !== "Signed out") showLogin("Can't reach the server. Start it in VS Code, then try again.");
  }
}
localStorage.getItem(TOKEN_KEY) ? boot() : showLogin();
