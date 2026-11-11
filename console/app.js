/* Acadza Fix Queue — faculty review console. Vanilla JS, no build step.
   Reads data.json exported by `python -m engine.run`. Actions + audit log persist in localStorage. */
"use strict";

const STORE_KEY = "acadza.fixqueue.v1";
const LANES = {
  decide:    { title: "Needs your decision", sub: "AI can't or mustn't apply these alone", act: "Approve" },
  spotcheck: { title: "Auto-applied · spot-check", sub: "Already live for students — keep or revert", act: "Keep fix" },
  sweep:     { title: "Found by sweep", sub: "Defects no student reported", act: "Approve" },
  replies:   { title: "Replies only", sub: "Record checked and fine — just send the replies", act: "Send replies" },
};
const VERDICT = {
  defect: "Real defect", no_error: "Student mistaken", display_issue: "Display issue", app_issue: "App issue",
  language_mode: "Language request", already_fixed: "Already fixed", not_actionable: "Not actionable",
};
const REPAIR = {
  answer_key: "Answer key wrong", type_mismatch: "Wrong question type", unsound: "No valid answer",
  identical_options: "Identical options", option_repair: "Option missing / blank", stem_data: "Missing data in stem",
  diagram: "Figure missing", wrong_question: "Solution from another question", solution_fix: "Solution has an error",
  solution_missing: "Solution missing", answer_form: "Unit / answer form missing", wrong_chapter: "Wrong chapter",
  syllabus: "Syllabus query", notation: "Notation glitch", markup_leak: "Raw markup visible", spelling: "Spelling",
  noise: "Stray text", exam_reference: "Exam tag in text",
};
const FIELD = { question: "Question text", solution: "Solution", answer: "Answer key", questionType: "Question type", chapter: "Chapter", subject: "Subject" };
const TYPE = { scq: "Single correct", mcq: "Multiple correct", integerQuestion: "Integer" };
const CHECK_LABEL = {
  closed_list: "Valid taxonomy keys", repair_present: "Repair chosen", repair_auto_allowed: "Auto-apply allowed",
  no_injection: "No injection", has_edit: "Has an edit", letters_only: "Letters only", deletion_only: "Deletion only",
  removes_exam_tag: "Removes exam tag", values_unchanged: "Values unchanged", additive: "Additive only",
  value_from_solution: "Value from solution", stem_unchanged: "Stem unchanged", options_complete: "4 options",
  solution_reaches_key: "Ends at key", edits_answer: "Edits answer", valid_for_type: "Valid for type",
  blind_solve_agrees: "Blind solve agrees", second_signal: "Second signal", not_comment_demand: "Not comment's demand",
  valid_type: "Valid type", answer_converted: "Answer re-encoded", answer_valid_for_new_type: "Answer fits type",
  confidence: "Confidence", confident_dismissal: "Confident", already_fixed_has_history: "Fix in history",
  no_edit_without_defect: "No stray edit",
};
const REJECT_REASONS = ["AI verdict is wrong", "Edit is wrong", "Needs more info", "Duplicate / handled elsewhere"];

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let DATA = null;
let state = { status: {}, audit: [], reviewer: "", theme: null };
let ui = { sel: 0, filter: "all", q: "", diff: "rendered", editing: false, rejecting: false, rejectReason: null, list: [] };

/* ---------------------------------------------------------------- persistence */
function load() {
  try { Object.assign(state, JSON.parse(localStorage.getItem(STORE_KEY) || "{}")); } catch (_) { /* private mode */ }
}
function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* ignore */ }
}

/* ---------------------------------------------------------------- html safety */
function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html");
  doc.querySelectorAll("script,iframe,object,embed,link,meta,style,form").forEach((n) => n.remove());
  doc.querySelectorAll("*").forEach((n) => {
    for (const a of [...n.attributes]) {
      if (/^on/i.test(a.name) || /javascript:/i.test(a.value)) n.removeAttribute(a.name);
    }
  });
  return doc.body.innerHTML;
}

/* ---------------------------------------------------------------- diff marking on raw production HTML */
const VOID = new Set(["br", "img", "hr", "input", "meta", "mspace", "none", "mprescripts", "col", "wbr"]);
function balanced(frag) {
  const st = [];
  const re = /<(\/?)([a-zA-Z][\w-]*)\b[^>]*?(\/?)>/g;
  let m;
  while ((m = re.exec(frag))) {
    const [, close, name, self] = m;
    const n = name.toLowerCase();
    if (self || VOID.has(n)) continue;
    if (close) { if (st.pop() !== n) return false; } else st.push(n);
  }
  return st.length === 0 && !/<[^>]*$/.test(frag) && !/^[^<]*>/.test(frag);
}
function insideTag(s, i) { return s.lastIndexOf("<", i - 1) > s.lastIndexOf(">", i - 1); }
function insideEntity(s, i) { const a = s.lastIndexOf("&", i - 1); return a >= 0 && a > s.lastIndexOf(";", i - 1) && i - a < 10 && !/\s/.test(s.slice(a, i)); }
function insideMath(s, i) { return s.lastIndexOf("<math", i) > s.lastIndexOf("</math>", i); }

function narrow(find, rep) {
  const max = Math.min(find.length, rep.length);
  let p = 0;
  while (p < max && find[p] === rep[p]) p++;
  const okStart = (i) => i <= 0 || ((/[\s>]/.test(find[i - 1]) || find[i] === "<") && !insideTag(find, i) && !insideEntity(find, i));
  while (p > 0 && !okStart(p)) p--;
  let s = 0; // suffix computed after p is final, so the two never overlap
  while (s < max - p && find[find.length - 1 - s] === rep[rep.length - 1 - s]) s++;
  let e = find.length - s;
  const okEnd = (i) => i >= find.length || ((/[\s<]/.test(find[i]) || /[\s>]/.test(find[i - 1])) && !insideTag(find, i) && !insideEntity(find, i));
  while (e < find.length && !okEnd(e)) e++;
  s = find.length - e;
  return { p, s, del: find.slice(p, find.length - s), ins: rep.slice(p, rep.length - s) };
}

function wrap(html, at, frag, kind) {
  // returns [newFragmentHtml, prefixPatch(fn)] - we build strings around position `at` in html
  if (!frag) return kind === "ins" ? "" : (insideMath(html, at) ? "" : '<span class="caret" title="inserted here"></span>');
  const block = /<(h\d|p|div|ol|ul|li|table)\b/i.test(frag);
  if (!insideMath(html, at)) {
    if (balanced(frag)) return block ? `<div class="hl-${kind}">${frag}</div>` : `<span class="hl-${kind}">${frag}</span>`;
    return null;
  }
  if (balanced(frag) && /</.test(frag)) return `<mrow class="hl-${kind}">${frag}</mrow>`;
  return null; // plain text inside a token element or unbalanced: caller highlights the enclosing element
}

function tagEnclosing(html, at, kind) {
  // add a highlight class to the nearest enclosing MathML token, else the enclosing <math>
  const re = /<(mi|mn|mo|mtext|ms)\b/g;
  let m, last = -1, lastName = "";
  while ((m = re.exec(html)) && m.index < at) { last = m.index; lastName = m[1]; }
  if (last >= 0 && html.indexOf(`</${lastName}>`, last) >= at) {
    return html.slice(0, last + 1 + lastName.length) + ` class="hl-${kind}"` + html.slice(last + 1 + lastName.length);
  }
  const mi = html.lastIndexOf("<math", at);
  if (mi >= 0 && insideMath(html, at)) return html.slice(0, mi + 5) + ` class="hl-${kind}"` + html.slice(mi + 5);
  return html;
}

function markedPair(html, edit) {
  const idx = html.indexOf(edit.find);
  if (idx < 0) return { before: html, after: html, missing: true };
  const n = narrow(edit.find, edit.replace);
  const at = idx + n.p;
  const tail = idx + edit.find.length - n.s;
  const afterHtml = html.slice(0, idx) + edit.replace + html.slice(idx + edit.find.length);
  let before, after;
  const wb = wrap(html, at, n.del, "del");
  before = wb === null ? tagEnclosing(html, at, "del") : html.slice(0, at) + wb + html.slice(tail);
  const atA = idx + n.p, tailA = idx + edit.replace.length - n.s;
  const wa = wrap(afterHtml, atA, n.ins, "ins");
  after = wa === null ? tagEnclosing(afterHtml, atA, "ins") : afterHtml.slice(0, atA) + (wa || "") + afterHtml.slice(tailA);
  return { before, after, narrow: n };
}

function plainText(html) {
  const d = document.createElement("div");
  d.innerHTML = sanitize(html);
  return (d.textContent || "").replace(/\s+/g, " ").trim();
}

/* ---------------------------------------------------------------- derived data */
function caseKey(c) { return c.questionId; }
function caseStatus(c) { return state.status[caseKey(c)] || null; }
function findingStatus(c, i) { return state.status[`${caseKey(c)}#f${i}`] || null; }
function leadResult(c) {
  const order = { auto_apply: 0, faculty_review: 1, no_change: 2 };
  const rs = c.reports.map((r) => r.result);
  return rs.sort((a, b) => order[a.route] - order[b.route] || (b.verdict === "defect") - (a.verdict === "defect"))[0] || null;
}
function caseEdits(c) {
  const seen = new Set(), out = [];
  for (const r of c.reports) {
    const res = r.result;
    for (const e of [res.edit, ...(res.extra_edits || [])]) {
      if (!e) continue;
      const k = JSON.stringify(e);
      if (!seen.has(k)) { seen.add(k); out.push(e); }
    }
  }
  return out;
}
function urgencyClass(u) { return u >= 85 ? "u-crit" : u >= 55 ? "u-high" : u >= 25 ? "u-mid" : "u-low"; }
function caseTitle(c) {
  const lr = leadResult(c);
  if (lr && lr.verdict === "defect") return REPAIR[lr.repair] || lr.repair;
  if (lr) {
    const base = c.reports.some((r) => r.screen.injection) ? "Prompt injection — ignored" : VERDICT[lr.verdict];
    return c.findings.length ? `${base} + ${c.findings.length} unreported` : base;
  }
  return `${REPAIR[c.findings[0]?.repair] || "Finding"} (unreported)`;
}
function shortSummary(c) {
  const q = DATA.questions[c.questionId];
  return `${q.subject} · ${q.chapter}`;
}

/* ---------------------------------------------------------------- top summary */
function renderSummary() {
  const cases = DATA.cases;
  const count = (lane) => cases.filter((c) => c.lane === lane).length;
  const handled = cases.filter((c) => caseStatus(c)).length;
  const live = cases.filter((c) => c.lane === "spotcheck").length;
  $("#summary").innerHTML = `
    <div class="progress" title="Cases you have acted on"><span>${handled}/${cases.length}</span><div class="bar"><i style="width:${(100 * handled) / cases.length}%"></i></div></div>
    <div class="stat key"><b>${count("decide")}</b> need you</div>
    <div class="stat"><b>${live}</b> fixes live</div>
    <div class="stat"><b>${count("sweep")}</b> sweep finds</div>
    <div class="stat"><b>${count("replies")}</b> replies only</div>
    <div class="stat" title="LLM outputs: ${esc(DATA.mode)} · ${esc(DATA.model)} · ${esc(DATA.promptVersions.join(", "))}">${DATA.mode === "replay" ? "recorded run" : "live run"}</div>`;
  $("#auditCount").textContent = state.audit.length;
}

/* ---------------------------------------------------------------- queue */
function matches(c) {
  if (ui.filter === "open" && caseStatus(c)) return false;
  if (ui.filter !== "all" && ui.filter !== "open" && c.lane !== ui.filter) return false;
  if (!ui.q) return true;
  const q = DATA.questions[c.questionId];
  const hay = [c.questionId, q.subject, q.chapter, caseTitle(c), ...c.reports.map((r) => `${r.report.reportId} ${r.report.comment}`)].join(" ").toLowerCase();
  return hay.includes(ui.q.toLowerCase());
}
function renderFilters() {
  const f = [["all", "All"], ["open", "Open"], ["decide", "Decide"], ["spotcheck", "Live fixes"], ["sweep", "Sweep"], ["replies", "Replies"]];
  $("#filters").innerHTML = f.map(([k, l]) => `<button class="chip" data-filter="${k}" aria-pressed="${ui.filter === k}">${l}</button>`).join("");
}
function renderQueue() {
  ui.list = DATA.cases.filter(matches);
  const nav = $("#queueList");
  let html = "", lastLane = null;
  ui.list.forEach((c, i) => {
    if (c.lane !== lastLane) {
      const n = ui.list.filter((x) => x.lane === c.lane).length;
      const bulk = c.lane === "replies" ? `<button class="lane-act" data-bulk="replies">Send all ${n}</button>` : "";
      html += `<div class="lane-head"><span>${LANES[c.lane].title} · ${n}</span>${bulk}</div><div class="lane-sub">${LANES[c.lane].sub}</div>`;
      lastLane = c.lane;
    }
    const st = caseStatus(c);
    const first = c.reports[0]?.report;
    const cls = st ? (st.action === "reject" ? "item done rejected" : "item done") : "item";
    html += `<button class="${cls}" data-i="${i}" aria-current="${i === ui.sel}">
      <span class="u ${urgencyClass(c.urgency)}" title="Urgency ${c.urgency}: ${esc(c.urgencyReason)}"></span>
      <span><div class="t">${esc(caseTitle(c))}</div>
        <div class="m">${esc(shortSummary(c))}</div>
        ${first ? `<div class="c">“${esc(first.comment)}”</div>` : `<div class="c">${esc(c.findings[0]?.evidence || "")}</div>`}</span>
      <span class="r"><span class="n">${c.reports.length ? `${c.reports.length} report${c.reports.length > 1 ? "s" : ""}` : "no reports"}</span></span>
    </button>`;
  });
  nav.innerHTML = html || `<p class="empty">Nothing matches.</p>`;
  const open = DATA.cases.filter((c) => !caseStatus(c)).length;
  $("#queueFoot").innerHTML = `Ordered by lane, then by harm: wrong grading → unanswerable → wrong teaching → mis-filing → cosmetic; more reporters rank higher. ${open} open.`;
  const cur = nav.querySelector('[aria-current="true"]');
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

/* ---------------------------------------------------------------- case view */
function renderCase() {
  const main = $("#case");
  const c = ui.list[ui.sel];
  if (!c) { main.innerHTML = `<div class="empty">No case selected.</div>`; return; }
  const q = DATA.questions[c.questionId];
  const lr = leadResult(c);
  const st = caseStatus(c);
  const edits = st && st.edits ? st.edits : caseEdits(c);
  const hasEdits = edits.length > 0;
  const live = c.lane === "spotcheck";
  const sub = lr
    ? `${VERDICT[lr.verdict]}${lr.repair ? " · " + esc(REPAIR[lr.repair]) : ""} · ${c.urgencyReason}`
    : c.urgencyReason;

  let banner = "";
  if (st) {
    const who = esc(st.reviewer || "faculty"), when = new Date(st.at).toLocaleString();
    const claimed = !caseEdits(c).length && lr && lr.verdict === "defect";
    const label = { approve: live ? "Fix kept" : claimed ? "Claimed" : !caseEdits(c).length ? "Replies sent" : "Approved and applied", edit: "Edited and applied", reject: live ? "Fix reverted" : "Rejected", bulk: "Replies sent" }[st.action];
    banner = `<div class="done-banner ${st.action === "reject" ? "rej" : ""}">${label} by ${who} · ${when}<button class="btn ghost" data-act="undo">Undo</button></div>`;
  }

  main.innerHTML = `<div class="case-body" id="caseBody">
    ${banner}
    <div class="case-head">
      <span class="pill lane-${c.lane}">${LANES[c.lane].title}</span>
      <span>${esc(q.subject)} › ${esc(q.chapter)}</span>
      <span>${TYPE[q.type] || q.type}${q.level ? " · " + esc(q.level.toLowerCase()) : ""}</span>
      <span class="mono copy" data-copy="${c.questionId}" title="Copy question id">${c.questionId}</span>
    </div>
    <h1 class="case-title">${esc(caseTitle(c))}</h1>
    <p class="case-sub">${sub}</p>
    <div class="grid">
      <div>
        ${renderChangeCard(c, q, edits, lr, live)}
        ${renderFindings(c, q)}
        ${renderRecord(c, q)}
      </div>
      <div>
        ${renderWhy(c, q, lr)}
        ${renderStudents(c, st)}
      </div>
    </div></div>
    ${renderActionBar(c, st, hasEdits, live)}`;
  main.querySelectorAll(".pane").forEach((p) => {
    const h = p.querySelector(".hl-ins, .hl-del, .caret");
    if (h) p.scrollTop = Math.max(0, h.offsetTop - p.offsetTop - 60);
  });
}

function renderChangeCard(c, q, edits, lr, live) {
  const title = live ? "Change already live" : edits.length ? (lr && lr.route === "faculty_review" ? "Suggested change — not applied" : "Proposed change") : "No change to the question";
  if (!edits.length) {
    let body;
    if (lr && lr.verdict === "defect") body = `<p>The AI did not propose an edit — this needs authored content (${esc(REPAIR[lr.repair])}). Approving marks it as taken by you; the replies tell students a faculty member is on it.</p>`;
    else if (lr) body = `<p><b>${VERDICT[lr.verdict]}.</b> The stored question, key and solution were checked; nothing changes. Only the student replies go out.</p>`;
    else body = `<p>No student report. See the sweep findings below.</p>`;
    return `<section class="card"><div class="card-h"><h3>${title}</h3></div><div class="card-b">${body}${renderChecks(c)}</div></section>`;
  }
  const blocks = edits.map((e, i) => renderEdit(c, q, e, i)).join("");
  return `<section class="card"><div class="card-h"><h3>${title}</h3>
      <span class="seg" role="group" aria-label="Diff view"><button data-diff="rendered" aria-pressed="${ui.diff === "rendered"}">Rendered</button><button data-diff="source" aria-pressed="${ui.diff === "source"}">Source</button></span></div>
    <div class="card-b">${blocks}${renderChecks(c)}</div></section>`;
}

function changeLine(q, e) {
  if (e.field === "answer") return `<span class="lbl">Key</span><del>${esc(fmtAnswer(e.find))}</del><span class="arrow">→</span><ins>${esc(fmtAnswer(e.replace))}</ins>`;
  if (e.field === "questionType") return `<span class="lbl">Type</span><del>${esc(TYPE[e.find] || e.find)}</del><span class="arrow">→</span><ins>${esc(TYPE[e.replace] || e.replace)}</ins>`;
  if (e.field === "chapter" || e.field === "subject") return `<span class="lbl">${FIELD[e.field]}</span><del>${esc(e.find)}</del><span class="arrow">→</span><ins>${esc(e.replace)}</ins>`;
  const n = narrow(e.find, e.replace);
  const d = plainText(n.del) || (n.del ? "markup" : ""), a = plainText(n.ins) || (n.ins ? "markup" : "");
  if ((d + a).length > 120) return `<span class="lbl">${FIELD[e.field]}</span><span>rewritten — ${Math.round(e.find.length / 100) / 10}k → ${Math.round(e.replace.length / 100) / 10}k chars, see diff</span>`;
  return `<span class="lbl">${FIELD[e.field]}</span>${d ? `<del>${esc(d)}</del>` : `<span class="arrow">insert</span>`}${d && a ? '<span class="arrow">→</span>' : ""}${a ? `<ins>${esc(a)}</ins>` : `<span class="arrow">(removed)</span>`}`;
}
function fmtAnswer(v) {
  try { const x = JSON.parse(v); if (Array.isArray(x)) return x.map((s) => (s === "" ? "∅" : s)).join(" · "); } catch (_) { /* plain */ }
  return v;
}

function renderEdit(c, q, e, i) {
  const editing = ui.editing && !caseStatus(c);
  const head = `<div class="change">${changeLine(q, e)}</div>`;
  let body = "";
  if (e.field === "answer" && q.type !== "integerQuestion" && /^[\["A-D, \]]+$/.test(e.find + e.replace)) {
    const oldL = (fmtAnswer(e.find).match(/[A-D]/g) || []), newL = (fmtAnswer(e.replace).match(/[A-D]/g) || []);
    body = `<div class="opts">${"ABCD".split("").filter((L) => L in q.options || oldL.includes(L) || newL.includes(L)).map((L) => {
      const isOld = oldL.includes(L) && !newL.includes(L), isNew = newL.includes(L) && !oldL.includes(L), both = oldL.includes(L) && newL.includes(L);
      const cls = isOld ? "old" : isNew ? "new" : "";
      const tag = isOld ? "was key" : isNew ? "new key" : both ? "key" : "";
      const t = q.options[L];
      return `<div class="opt ${cls}"><span class="L">${L}</span><span>${t ? esc(t) : '<span class="blank">blank</span>'}</span><span class="tag">${tag}</span></div>`;
    }).join("")}</div>`;
  } else if (e.field === "question" || e.field === "solution") {
    const html = e.field === "question" ? q.question : q.solution;
    const mp = markedPair(html, e);
    if (mp.missing) body = `<div class="guard-note">This edit's find-string is not in the stored ${e.field} any more.</div>`;
    else if (ui.diff === "source") body = renderSource(e);
    else body = `<div class="ba"><div><div class="cap"><span class="dot b"></span>Before</div><div class="pane qhtml">${sanitize(mp.before)}</div></div>
                 <div><div class="cap"><span class="dot a"></span>After${editing ? " (live preview)" : ""}</div><div class="pane qhtml" data-after-i="${i}">${sanitize(mp.after)}</div></div></div>`;
  }
  const editor = editing ? `<div style="margin-top:10px"><div class="field-tag">Edit replacement (${e.field === "question" || e.field === "solution" ? "HTML" : "value"})</div>
     <textarea class="edit ${e.field === "question" || e.field === "solution" ? "code" : ""}" data-edit-i="${i}" rows="${e.replace.length > 200 ? 8 : 3}">${esc(e.replace)}</textarea></div>` : "";
  return `<div class="edit-block">${head}${body}${editor}</div>`;
}

function renderSource(e) {
  const n = narrow(e.find, e.replace);
  const ctxB = e.find.slice(Math.max(0, n.p - 60), n.p), ctxA = e.find.slice(e.find.length - n.s, e.find.length - n.s + 60);
  return `<pre class="src pane"><span class="ctx">${esc(ctxB)}</span><del>${esc(n.del)}</del><ins>${esc(n.ins)}</ins><span class="ctx">${esc(ctxA)}</span></pre>`;
}

function renderChecks(c) {
  const all = new Map();
  for (const r of c.reports) for (const k of r.checks) {
    const key = k.check;
    if (!all.has(key) || !k.ok) all.set(key, k);
  }
  if (!all.size) return "";
  const items = [...all.values()];
  const bad = items.filter((k) => !k.ok), good = items.filter((k) => k.ok);
  const chip = (k) => `<span class="check ${k.ok ? "ok" : "bad"}" title="${esc(k.detail)}">${esc(CHECK_LABEL[k.check.split(":")[0]] || k.check)}${k.check.includes(":") ? " · " + esc(k.check.split(":")[1]) : ""}</span>`;
  const lr = leadResult(c);
  const note = bad.length && lr && lr.verdict === "defect"
    ? `<div class="guard-note"><b>Why a human is needed:</b> ${bad.map((k) => esc(k.detail)).join(" · ")}</div>` : "";
  return `<div class="checks" aria-label="Guard checks">${bad.map(chip).join("")}
    <details class="checks-more"><summary class="check ok">${good.length} guard check${good.length === 1 ? "" : "s"} passed</summary><div class="checks">${good.map(chip).join("")}</div></details></div>${note}`;
}

function renderWhy(c, q, lr) {
  const s = c.solve;
  let solve = "";
  if (s) {
    const key = Array.isArray(q.answer) ? q.answer.join(",") : q.answer;
    const norm = (x) => String(x || "").toUpperCase().replace(/[^A-D0-9.,]/g, "").split(",").filter(Boolean).sort().join(",");
    const agreeKey = s.answer && norm(s.answer) === norm(key);
    const ansEdit = caseEdits(c).find((e) => e.field === "answer");
    const agreeNew = ansEdit && s.answer && norm(s.answer) === norm(fmtAnswer(ansEdit.replace).replace(/ · /g, ","));
    const verdict = !s.answer ? `<span class="solve-disagree">no visible option fits</span>`
      : agreeNew ? `<span class="solve-agree">agrees with the new key, not the old (${esc(key)})</span>`
      : agreeKey ? `<span class="solve-agree">matches stored key</span>` : `<span class="solve-disagree">differs from stored key (${esc(key)})</span>`;
    solve = `<dl class="kv">
      <dt>Blind solve</dt><dd><b>${esc(s.answer || "—")}</b> · ${esc(s.final_value)} · ${verdict}</dd>
      <dt>Working</dt><dd>${esc(s.working)}</dd>
      ${s.missing_data ? `<dt>Missing</dt><dd>${esc(s.missing_data)}</dd>` : ""}
      ${s.assumptions ? `<dt>Assumed</dt><dd>${esc(s.assumptions)}</dd>` : ""}
    </dl>`;
  }
  const conf = lr ? Math.round(lr.confidence * 100) : null;
  const dets = c.detectors.length ? `<details class="more"><summary>Code checks on the record (${c.detectors.length})</summary><ul>${c.detectors.map((d) => `<li>${esc(d.detail)}</li>`).join("")}</ul></details>` : "";
  return `<section class="card why"><div class="card-h"><h3>Why the AI thinks so</h3></div><div class="card-b">
    ${lr ? `<p>${esc(lr.evidence)}</p>` : `<p>${esc(c.assessment)}</p>`}
    ${conf !== null ? `<div class="conf">Confidence <div class="meter"><i style="width:${conf}%"></i></div> ${conf}%</div>` : ""}
    ${solve}
    <details class="more"><summary>Full assessment of the record</summary><p style="margin:8px 0 0">${esc(c.assessment)}</p></details>
    ${dets}
  </div></section>`;
}

function renderStudents(c, st) {
  if (!c.reports.length) return "";
  const editing = ui.editing && !st;
  const rows = c.reports.map((r) => {
    const rep = r.report, res = r.result, sc = r.screen;
    const reply = (st && st.replies && st.replies[rep.reportId]) ?? res.student_reply;
    const flags = [
      sc.injection ? `<span class="pill sec" title="${esc(sc.injection_patterns.join(" | "))}">Prompt injection — ignored</span>` : "",
      sc.register === "hinglish" ? `<span class="pill v-ok">Hinglish</span>` : "",
      `<span class="pill ${res.verdict === "defect" ? "v-defect" : "v-ok"}">${VERDICT[res.verdict]}</span>`,
    ].join("");
    const when = new Date(rep.reportedAt).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    const replyStatus = st ? (st.action === "reject" ? "held" : "sent") : res.route === "auto_apply" ? "ready" : "preview";
    return `<div class="student">
      <div class="meta"><b>${rep.reportId}</b><span>${esc(rep.source)} · ${when}</span>${flags}</div>
      <div class="bubble ${sc.injection ? "inj" : ""}">${esc(rep.comment)}</div>
      <div class="reply"><div class="lbl">Reply to student <span class="pill v-ok">${replyStatus}</span></div>
        ${editing ? `<textarea class="edit" data-reply="${rep.reportId}" rows="3">${esc(reply)}</textarea>` : `<div class="txt">${esc(reply)}</div>`}
      </div></div>`;
  }).join("");
  return `<section class="card"><div class="card-h"><h3>Students (${c.reports.length})</h3></div>${rows}</section>`;
}

function renderFindings(c, q) {
  if (!c.findings.length) return "";
  const rows = c.findings.map((f, i) => {
    const st = findingStatus(c, i);
    const edits = f.edits.map((e) => {
      if (e.field === "question" || e.field === "solution") {
        const mp = markedPair(e.field === "question" ? q.question : q.solution, e);
        return `<div class="change" style="font-size:13.5px">${changeLine(q, e)}</div>`;
      }
      return `<div class="change" style="font-size:13.5px">${changeLine(q, e)}</div>`;
    }).join("");
    const acts = st ? `<span class="pill ${st.action === "reject" ? "status-rej" : "status-done"}">${st.action === "reject" ? "Rejected" : "Approved"}</span>`
      : `<span class="acts"><button class="btn" data-f-approve="${i}" ${f.edits.length ? "" : "disabled title='No edit to apply - assign to faculty'"}>Approve</button><button class="btn danger" data-f-reject="${i}">Reject</button></span>`;
    return `<div class="finding"><div class="top-line"><span class="pill lane-sweep">${esc(REPAIR[f.repair] || f.repair)}</span>${acts}</div>
      <p class="ev">${esc(f.evidence)}</p>${edits}</div>`;
  }).join("");
  return `<section class="card"><div class="card-h"><h3>Also found in this record — not reported</h3><span class="n" style="font-size:12px;color:var(--muted)">${c.findings.length}</span></div>${rows}</section>`;
}

function renderRecord(c, q) {
  return `<section class="card"><details><summary class="card-h" style="cursor:pointer;list-style:none"><h3>Full question as stored</h3><span style="font-size:12px;color:var(--muted)">key ${esc(Array.isArray(q.answer) ? JSON.stringify(q.answer) : q.answer)}</span></summary>
    <div class="card-b"><div class="field-tag">Question</div><div class="qhtml">${sanitize(q.question)}</div>
    <div class="field-tag" style="margin-top:14px">Solution</div><div class="qhtml">${sanitize(q.solution)}</div>
    ${q.errorHistory.length ? `<div class="field-tag" style="margin-top:14px">History</div><ul>${q.errorHistory.map((h) => `<li>${esc(h.at)} · ${esc(h.actor)} · ${esc(h.note || h.type)}</li>`).join("")}</ul>` : ""}
    </div></details></section>`;
}

function renderActionBar(c, st, hasEdits, live) {
  if (st) return `<div class="actionbar"><button class="btn" data-act="next">Next case <kbd>j</kbd></button><span class="hint">Done. Undo with <kbd>u</kbd>.</span></div>`;
  if (ui.rejecting) {
    return `<div class="actionbar" style="display:block">
      <div class="reasons">${REJECT_REASONS.map((r) => `<button class="chip" data-reason="${esc(r)}" aria-pressed="${ui.rejectReason === r}">${esc(r)}</button>`).join("")}</div>
      <input class="edit" id="rejectNote" placeholder="Note for the audit log (optional)" style="margin-bottom:10px">
      <button class="btn danger" data-act="confirm-reject" ${ui.rejectReason ? "" : "disabled"}>${live ? "Revert fix" : "Reject"}</button>
      <button class="btn ghost" data-act="cancel">Cancel</button>
      <span class="hint">${live ? "Reverting restores the original record; replies are held for you to answer." : "Nothing is applied; replies are held."}</span></div>`;
  }
  if (ui.editing) {
    return `<div class="actionbar"><button class="btn primary" data-act="save-edit">Save & ${live ? "keep" : "apply"} <kbd>⌘↵</kbd></button><button class="btn ghost" data-act="cancel">Cancel <kbd>Esc</kbd></button><span class="hint">Your edits are recorded next to the AI's original in the audit log.</span></div>`;
  }
  const lr = leadResult(c);
  const approve = live ? "Keep fix" : c.lane === "replies" ? "Send replies" : hasEdits ? "Approve & apply" : lr && lr.verdict === "defect" ? "Take it — I'll fix" : "Approve";
  return `<div class="actionbar">
    <button class="btn primary" data-act="approve">${approve} <kbd>a</kbd></button>
    <button class="btn" data-act="edit">Edit <kbd>e</kbd></button>
    <button class="btn danger" data-act="reject">${live ? "Revert" : "Reject"} <kbd>r</kbd></button>
    <span class="hint"><kbd>j</kbd>/<kbd>k</kbd> move · <kbd>s</kbd> source · <kbd>?</kbd> keys</span></div>`;
}

/* ---------------------------------------------------------------- actions + audit */
function audit(entry) {
  const e = { id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`, at: new Date().toISOString(), reviewer: state.reviewer || "faculty", ...entry };
  state.audit.push(e);
  return e;
}
function act(kind, extra = {}) {
  const c = ui.list[ui.sel];
  if (!c || caseStatus(c)) return;
  const proposed = caseEdits(c);
  const replies = Object.fromEntries(c.reports.map((r) => [r.report.reportId, r.result.student_reply]));
  let edits = proposed;
  if (kind === "edit") {
    edits = proposed.map((e, i) => { const t = document.querySelector(`[data-edit-i="${i}"]`); return t ? { ...e, replace: t.value } : e; });
    document.querySelectorAll("[data-reply]").forEach((t) => { replies[t.dataset.reply] = t.value; });
  }
  const lr = leadResult(c);
  const entry = audit({
    action: kind, lane: c.lane, questionId: c.questionId, reportIds: c.reports.map((r) => r.report.reportId),
    verdict: lr?.verdict, repair: lr?.repair, route: lr?.route,
    proposedEdits: proposed, finalEdits: kind === "reject" ? [] : edits,
    replies: kind === "reject" ? {} : replies, reason: extra.reason, note: extra.note,
    effect: c.lane === "spotcheck" ? (kind === "reject" ? "reverted live fix" : "kept live fix")
      : kind === "reject" ? "no change applied; replies held"
      : edits.length ? "applied edits; replies sent"
      : lr?.verdict === "defect" ? "claimed by reviewer (needs authored content); replies sent" : "replies sent",
  });
  state.status[caseKey(c)] = { action: kind, at: entry.at, reviewer: entry.reviewer, auditId: entry.id, edits: kind === "edit" ? edits : null, replies: kind === "edit" ? replies : null };
  ui.editing = ui.rejecting = false; ui.rejectReason = null;
  save();
  toast(`${{ approve: c.lane === "spotcheck" ? "Kept" : "Approved", edit: "Saved edit", reject: c.lane === "spotcheck" ? "Reverted" : "Rejected" }[kind]} · ${caseTitle(c)}`, true);
  nextOpen();
}
function undo() {
  const last = [...state.audit].reverse().find((e) => e.action !== "undo" && !e.undone);
  if (!last) return;
  last.undone = true;
  audit({ action: "undo", undoes: last.id, questionId: last.questionId });
  if (last.findingIndex !== undefined) delete state.status[`${last.questionId}#f${last.findingIndex}`];
  else if (last.action === "bulk") last.questionIds.forEach((q) => delete state.status[q]);
  else delete state.status[last.questionId];
  save();
  const i = ui.list.findIndex((c) => c.questionId === last.questionId);
  if (i >= 0) ui.sel = i;
  toast("Undone");
  renderAll();
}
function findingAct(i, kind) {
  const c = ui.list[ui.sel];
  const f = c.findings[i];
  const e = audit({ action: kind === "approve" ? "approve_finding" : "reject_finding", lane: c.lane, questionId: c.questionId, findingIndex: i, repair: f.repair, proposedEdits: f.edits, finalEdits: kind === "approve" ? f.edits : [] });
  state.status[`${caseKey(c)}#f${i}`] = { action: kind, at: e.at, reviewer: e.reviewer };
  save();
  toast(`${kind === "approve" ? "Approved" : "Rejected"} finding · ${REPAIR[f.repair] || f.repair}`, true);
  renderAll();
}
function bulkReplies() {
  const open = ui.list.filter((c) => c.lane === "replies" && !caseStatus(c));
  if (!open.length) return;
  if (!confirm(`Send ${open.reduce((n, c) => n + c.reports.length, 0)} replies across ${open.length} cases? Each is logged separately.`)) return;
  const e = audit({ action: "bulk", lane: "replies", questionIds: open.map((c) => c.questionId), reportIds: open.flatMap((c) => c.reports.map((r) => r.report.reportId)), effect: "replies sent" });
  open.forEach((c) => { state.status[caseKey(c)] = { action: "bulk", at: e.at, reviewer: e.reviewer, auditId: e.id }; });
  save();
  toast(`Sent replies for ${open.length} cases`, true);
  renderAll();
}
function nextOpen() {
  const start = ui.sel;
  for (let k = 1; k <= ui.list.length; k++) {
    const i = (start + k) % ui.list.length;
    if (!caseStatus(ui.list[i])) { ui.sel = i; break; }
  }
  renderAll();
  scrollCaseTop();
}
function move(d) {
  if (!ui.list.length) return;
  ui.sel = Math.max(0, Math.min(ui.list.length - 1, ui.sel + d));
  ui.editing = ui.rejecting = false;
  renderAll();
  scrollCaseTop();
}

function scrollCaseTop() { const b = $("#caseBody"); if (b) b.scrollTop = 0; }

let toastTimer = null;
function toast(msg, withUndo = false) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(msg)}</span>${withUndo ? '<button data-act="undo">Undo</button>' : ""}`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 5000);
}

function renderAudit() {
  $("#auditList").innerHTML = [...state.audit].reverse().map((e) => `<li>
    <div class="when">${new Date(e.at).toLocaleString()} · ${esc(e.reviewer)}</div>
    <div class="what">${esc(e.action)}${e.undone ? " (undone)" : ""} · ${esc(e.questionId || (e.questionIds || []).length + " cases")}</div>
    <div>${esc(e.effect || e.repair || "")} ${e.reason ? "· " + esc(e.reason) : ""} ${e.note ? "· “" + esc(e.note) + "”" : ""}</div>
    ${e.finalEdits && e.finalEdits.length ? `<pre>${esc(JSON.stringify(e.finalEdits, null, 1)).slice(0, 1200)}</pre>` : ""}
  </li>`).join("") || `<li style="color:var(--muted)">No actions yet.</li>`;
}

function renderAll() { renderSummary(); renderFilters(); renderQueue(); renderCase(); if (!$("#auditDrawer").hidden) renderAudit(); }

/* ---------------------------------------------------------------- events */
function bind() {
  $("#reviewer").value = state.reviewer;
  $("#reviewer").addEventListener("change", (e) => { state.reviewer = e.target.value.trim(); save(); });
  $("#search").addEventListener("input", (e) => { ui.q = e.target.value; ui.sel = 0; renderQueue(); renderCase(); });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button, [data-copy]");
    if (!t) return;
    if (t.dataset.filter) { ui.filter = t.dataset.filter; ui.sel = 0; renderAll(); }
    else if (t.dataset.i !== undefined) { ui.sel = +t.dataset.i; ui.editing = ui.rejecting = false; renderAll(); scrollCaseTop(); $("#queue").classList.remove("open"); }
    else if (t.dataset.diff) { ui.diff = t.dataset.diff; renderCase(); }
    else if (t.dataset.bulk) bulkReplies();
    else if (t.dataset.fApprove !== undefined) findingAct(+t.dataset.fApprove, "approve");
    else if (t.dataset.fReject !== undefined) findingAct(+t.dataset.fReject, "reject");
    else if (t.dataset.reason) { ui.rejectReason = t.dataset.reason; const note = $("#rejectNote")?.value; renderCase(); if (note) $("#rejectNote").value = note; }
    else if (t.dataset.copy) { navigator.clipboard?.writeText(t.dataset.copy); toast("Question id copied"); }
    else if (t.dataset.act) {
      const a = t.dataset.act;
      if (a === "approve") act("approve");
      else if (a === "edit") { ui.editing = true; renderCase(); document.querySelector("textarea.edit")?.focus(); }
      else if (a === "save-edit") act("edit");
      else if (a === "reject") { ui.rejecting = true; renderCase(); }
      else if (a === "confirm-reject") act("reject", { reason: ui.rejectReason, note: $("#rejectNote")?.value || "" });
      else if (a === "cancel") { ui.editing = ui.rejecting = false; renderCase(); }
      else if (a === "undo") undo();
      else if (a === "next") nextOpen();
    }
  });
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.editI === undefined) return;
    const c = ui.list[ui.sel], q = DATA.questions[c.questionId];
    const edit = { ...caseEdits(c)[+t.dataset.editI], replace: t.value };
    const pane = document.querySelector(`[data-after-i="${t.dataset.editI}"]`);
    if (pane && (edit.field === "question" || edit.field === "solution")) {
      pane.innerHTML = sanitize(markedPair(edit.field === "question" ? q.question : q.solution, edit).after);
    }
  });
  $("#auditBtn").onclick = () => { renderAudit(); $("#auditDrawer").hidden = false; };
  $("#auditClose").onclick = () => ($("#auditDrawer").hidden = true);
  $("#auditExport").onclick = () => {
    const blob = new Blob([JSON.stringify(state.audit, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `acadza-audit-${new Date().toISOString().slice(0, 10)}.json`; a.click();
  };
  $("#helpBtn").onclick = () => ($("#helpModal").hidden = false);
  $("#helpClose").onclick = () => ($("#helpModal").hidden = true);
  $("#themeBtn").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    state.theme = dark ? "light" : "dark"; document.documentElement.dataset.theme = state.theme; save();
  };
  $("#queueToggle").onclick = () => $("#queue").classList.toggle("open");
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA/.test(document.activeElement?.tagName);
    if (e.key === "Escape") { $("#helpModal").hidden = true; $("#auditDrawer").hidden = true; if (ui.editing || ui.rejecting) { ui.editing = ui.rejecting = false; renderCase(); } document.activeElement?.blur(); return; }
    if (typing) { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && ui.editing) act("edit"); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "j" || k === "ArrowDown") { e.preventDefault(); move(1); }
    else if (k === "k" || k === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (k === "a") act("approve");
    else if (k === "e") { if (!caseStatus(ui.list[ui.sel])) { ui.editing = true; renderCase(); } }
    else if (k === "r") { if (!caseStatus(ui.list[ui.sel])) { ui.rejecting = true; renderCase(); } }
    else if (k === "s") { ui.diff = ui.diff === "rendered" ? "source" : "rendered"; renderCase(); }
    else if (k === "u") undo();
    else if (k === "/") { e.preventDefault(); $("#search").focus(); }
    else if (k === "?") $("#helpModal").hidden = false;
  });
}

async function init() {
  load();
  if (state.theme) document.documentElement.dataset.theme = state.theme;
  try {
    DATA = await (await fetch("data.json", { cache: "no-cache" })).json();
  } catch (err) {
    $("#case").innerHTML = `<div class="empty">Could not load data.json. Serve this folder over HTTP (e.g. <code>python3 -m http.server</code>).</div>`;
    return;
  }
  bind();
  renderAll();
}
init();
