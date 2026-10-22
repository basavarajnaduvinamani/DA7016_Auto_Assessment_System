// Offline engine for the web demo: a JavaScript port of autoassess's
// spec validation, segmentation, lexical baseline grader, rubric feedback
// and sheet summary (src/autoassess/*.py). Used until an LLM key is
// connected; the Python package remains the reference implementation.
(function (root) {
  "use strict";

  const EPS = 1e-6;

  // Python's round(): half to even.
  function pyRound(x) {
    const f = Math.floor(x);
    const d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
    return Math.round(x);
  }

  // ---------------------------------------------------------------- spec
  function validateSpec(raw) {
    const errors = [];
    if (!raw || typeof raw !== "object") return { errors: ["The spec is empty or not a YAML/JSON object."] };
    const qs = Array.isArray(raw.questions) ? raw.questions : [];
    if (!raw.exam_id) errors.push("exam_id is missing.");
    if (!qs.length) errors.push("The spec has no questions.");
    const seenQ = new Set();
    const questions = qs.map((q, i) => {
      const id = String(q.id ?? `#${i + 1}`);
      if (seenQ.has(id)) errors.push(`Duplicate question id ${id}.`);
      seenQ.add(id);
      const crit = Array.isArray(q.criteria) ? q.criteria : [];
      if (!crit.length) errors.push(`${id}: no rubric criteria.`);
      const max = Number(q.max_marks);
      if (!(max > 0)) errors.push(`${id}: max_marks must be a positive number.`);
      const criteria = crit.map((c, j) => ({
        id: String(c.id ?? `${id}.c${j + 1}`),
        description: String(c.description ?? "").trim(),
        marks: Number(c.marks),
        allow_partial: c.allow_partial !== false,
      }));
      criteria.forEach((c) => {
        if (!(c.marks > 0)) errors.push(`${c.id}: marks must be positive.`);
        if (!c.description) errors.push(`${c.id}: description is empty.`);
      });
      const total = criteria.reduce((s, c) => s + (c.marks || 0), 0);
      if (crit.length && max > 0 && Math.abs(total - max) > EPS)
        errors.push(`${id}: rubric criteria add up to ${fmt(total)} marks but the question is worth ${fmt(max)}.`);
      const ids = criteria.map((c) => c.id);
      const dup = [...new Set(ids.filter((x, k) => ids.indexOf(x) !== k))];
      if (dup.length) errors.push(`${id}: duplicate criterion ids ${dup.join(", ")}.`);
      return {
        id,
        text: String(q.text ?? ""),
        max_marks: max,
        model_answer: q.model_answer ? String(q.model_answer) : null,
        aliases: Array.isArray(q.aliases) ? q.aliases.map(String) : [],
        criteria,
      };
    });
    const spec = {
      exam_id: String(raw.exam_id ?? ""),
      title: String(raw.title ?? raw.exam_id ?? "Exam"),
      language: String(raw.language ?? "en"),
      questions,
    };
    spec.total_marks = questions.reduce((s, q) => s + (q.max_marks || 0), 0);
    return { spec, errors };
  }

  const VAGUE = /\b(good|well|proper(ly)?|appropriate(ly)?|clear(ly)?|adequate(ly)?|overall|neat(ly)?|nice)\b/i;
  function lintSpec(spec) {
    const w = [];
    for (const q of spec.questions) {
      if (!q.model_answer) w.push(`${q.id}: no model answer; grading leans entirely on the rubric`);
      for (const c of q.criteria) {
        const words = c.description.split(/\s+/).filter(Boolean).length;
        if (words < 4) w.push(`${c.id}: description is very short (${words} words)`);
        else if (VAGUE.test(c.description) && words < 12) w.push(`${c.id}: vague wording with no checkable condition`);
        if (!c.allow_partial && c.marks > 2) w.push(`${c.id}: ${fmt(c.marks)} marks all-or-nothing; consider splitting it`);
      }
    }
    return w;
  }

  // ---------------------------------------------------------- segmentation
  function normLabel(label) {
    let s = label.toLowerCase().trim().replace(/[.):-]+$/, "");
    s = s.replace(/^(q|ques|question|ans|answer|a)\s*\.?\s*/, "");
    return s.replace(/[\s().]/g, "");
  }
  const LABEL = /^\s*(?:(?:q|ques|question|ans|answer)\s*\.?\s*(?:no\.?\s*)?)?(\d{1,2}\s*(?:\(?[a-h]\)?|\(?(?:i|ii|iii|iv|v|vi)\)?)?)\s*(?:[.):\-]|\s(?=\S))/i;

  function findLabel(line, variants) {
    const m = LABEL.exec(line);
    if (!m) return null;
    const prefixed = !/^\d/.test(line.trimStart());
    let qid = variants.get(normLabel(m[1]));
    if (qid === undefined) {
      const num = /\d+/.exec(m[1].trim());
      qid = num ? variants.get(num[0]) : undefined;
    }
    return qid === undefined ? null : { qid, end: m[0].length, prefixed };
  }

  function segment(spec, text) {
    const variants = new Map();
    for (const q of spec.questions) for (const l of [q.id, ...q.aliases]) variants.set(normLabel(l), q.id);
    const lines = text.split(/\r?\n/);
    const prefixedSheet = lines.some((l) => {
      const h = findLabel(l, variants);
      return h && h.prefixed;
    });
    const parts = new Map();
    let current = null;
    for (const line of lines) {
      const hit = findLabel(line, variants);
      let t = line;
      if (hit && (hit.prefixed || (!prefixedSheet && !parts.has(hit.qid)))) {
        current = hit.qid;
        t = line.slice(hit.end).trim();
      }
      if (current === null) continue;
      if (!parts.has(current)) parts.set(current, []);
      parts.get(current).push(t);
    }
    const out = {};
    for (const q of spec.questions) out[q.id] = (parts.get(q.id) || []).join("\n").trim();
    return out;
  }

  // ------------------------------------------------------ lexical baseline
  const STOP = new Set(
    `a an the of to in on for and or but is are was were be been being as at by with from that this these those
    it its into than then so such any some each every one two three at least e g eg says states state mentions
    gives give explains explain answer student valid example examples like how what when why which who whom
    there their them they he she we you your our has have had do does did not no can could should would may
    might must will shall`.split(/\s+/)
  );
  const stem = (w) => w.slice(0, 6);
  function contentWords(text) {
    const out = new Set();
    for (const w of text.toLowerCase().match(/[a-z]+/g) || []) if (w.length > 2 && !STOP.has(w)) out.add(stem(w));
    return out;
  }
  const sentences = (t) => t.split(/(?<=[.!?])\s+|\n+/).map((s) => s.trim()).filter(Boolean);

  function gradeQuestionLexical(q, answer) {
    answer = answer.trim();
    const aw = contentWords(answer);
    const sents = sentences(answer);
    const criteria = q.criteria.map((c) => {
      const target = contentWords(c.description);
      let hit = 0;
      target.forEach((w) => aw.has(w) && hit++);
      const coverage = target.size ? hit / target.size : 0;
      let marks = c.allow_partial ? pyRound(c.marks * Math.min(1, coverage / 0.6) * 4) / 4 : coverage >= 0.5 ? c.marks : 0;
      marks = Math.min(marks, c.marks);
      let best = null, bestN = -1;
      for (const s of sents) {
        let n = 0;
        contentWords(s).forEach((w) => target.has(w) && n++);
        if (n > bestN) { best = s; bestN = n; }
      }
      const verdict = marks >= c.marks ? "met" : marks > 0 ? "partial" : "not_met";
      const reason =
        coverage >= 0.6 ? "Key words for this point appear in your answer."
        : coverage > 0 ? "Only some key words for this point appear in your answer."
        : "Key words for this point were not found in your answer.";
      return { criterion_id: c.id, verdict, marks_awarded: marks, evidence: marks > 0 ? best : null, reason };
    });
    const total = Math.min(criteria.reduce((s, r) => s + r.marks_awarded, 0), q.max_marks);
    return { question_id: q.id, marks_awarded: total, max_marks: q.max_marks, criteria, confidence: 1, flags: answer ? [] : ["unanswered"] };
  }

  // -------------------------------------------------------------- feedback
  const lowerFirst = (s) => s.charAt(0).toLowerCase() + s.slice(1);
  function rubricItems(q, g) {
    const crit = Object.fromEntries(q.criteria.map((c) => [c.id, c]));
    const items = [];
    for (const r of g.criteria) {
      const c = crit[r.criterion_id];
      if (r.marks_awarded > 0) items.push({ criterion_id: c.id, kind: "earned", text: `You covered this: ${lowerFirst(c.description)}` });
      if (r.marks_awarded < c.marks) {
        const missing = r.marks_awarded > 0 ? "This point was only partly covered." : "This point was missing.";
        items.push({
          criterion_id: c.id,
          kind: "lost",
          text: `${missing} ${r.reason || ""}`.trim(),
          next_step: `Make sure your answer ${lowerFirst(c.description)}`.replace(/\.+$/, "") + ".",
        });
      }
    }
    return items;
  }

  function sheetSummary(spec, questions, total) {
    const ratio = (q) => q.marks_awarded / q.max_marks;
    const rows = [...questions].sort((a, b) => ratio(a) - ratio(b));
    const best = [...rows].reverse().filter((q) => ratio(q) >= 0.7);
    const missing = questions.filter((q) => q.flags.includes("unanswered")).map((q) => q.question_id);
    const weak = rows.filter((q) => ratio(q) < 0.5 && !missing.includes(q.question_id)).map((q) => q.question_id);
    const parts = [`Total: ${fmt(total)} of ${fmt(spec.total_marks)} marks.`];
    if (best.length) parts.push(`Strongest answers: ${best.map((q) => q.question_id).join(", ")}.`);
    if (weak.length) parts.push(`Focus your revision on ${weak.join(", ")}; the points to add are listed under each question.`);
    if (missing.length) parts.push(`Not attempted: ${missing.join(", ")}.`);
    return parts.join(" ");
  }

  function gradeSheet(spec, text, studentId) {
    const answers = segment(spec, text);
    const questions = spec.questions.map((q) => {
      const g = gradeQuestionLexical(q, answers[q.id] || "");
      if (!answers[q.id]) {
        g.feedback_summary = `No answer was found for ${q.id}. Attempt every question: even a partial answer can earn marks.`;
        g.feedback_items = [];
      } else {
        g.feedback_summary = `${fmt(g.marks_awarded)} of ${fmt(g.max_marks)} marks.`;
        g.feedback_items = rubricItems(q, g).sort((a, b) => (a.kind === "earned" ? 0 : 1) - (b.kind === "earned" ? 0 : 1));
      }
      return g;
    });
    const total = questions.reduce((s, q) => s + q.marks_awarded, 0);
    return { exam_id: spec.exam_id, student_id: studentId, questions, total, summary_feedback: sheetSummary(spec, questions, total), answers };
  }

  // Character span of `evidence` in `answer`, ignoring case and punctuation.
  function findSpan(evidence, answer) {
    const norm = (t) => {
      const out = [], idx = [];
      const re = /[\p{L}\p{N}_']+/gu;
      let m;
      while ((m = re.exec(t))) {
        if (out.length) { out.push(" "); idx.push(m.index); }
        for (let k = 0; k < m[0].length; k++) { out.push(m[0][k].toLowerCase()); idx.push(m.index + k); }
      }
      return [out.join(""), idx];
    };
    const [q] = norm(evidence || "");
    const [hay, idx] = norm(answer);
    if (!q) return null;
    const pos = hay.indexOf(q);
    if (pos < 0) return null;
    return [idx[pos], idx[pos + q.length - 1] + 1];
  }

  function fmt(x) {
    return Number.isInteger(x) ? String(x) : String(Math.round(x * 100) / 100);
  }

  const api = { validateSpec, lintSpec, segment, gradeQuestionLexical, gradeSheet, findSpan, fmt, pyRound };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AutoAssess = api;
})(typeof window !== "undefined" ? window : globalThis);
