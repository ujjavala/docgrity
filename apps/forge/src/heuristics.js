/**
 * Heuristic (no-AI) scan mode.
 *
 * Pure deterministic algorithms — no LLM calls, no egress, no API key.
 * Detects duplicates (lexical shingle similarity) and open questions
 * (pattern matching). Contradictions are NOT supported: telling apart
 * "the SLA is 4 hours" from "the SLA is 24 hours" needs semantic
 * reasoning, so that check requires a configured AI provider.
 *
 * Output shapes mirror agents.js exactly ({output, model, promptVersion})
 * so scans.js can swap assessors without branching downstream. Findings
 * record model = HEURISTIC_MODEL for auditability.
 */

export const HEURISTIC_MODEL = 'heuristic-v1';

/* ---------- Text utilities ---------- */

const normalizeWords = (text) =>
  String(text ?? '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);

/** Word n-gram shingle set. */
export function shingles(text, n = 3) {
  const words = normalizeWords(text);
  const out = new Set();
  for (let i = 0; i + n <= words.length; i++) out.add(words.slice(i, i + n).join(' '));
  return out;
}

/**
 * Lexical similarity between two texts.
 * jaccard: symmetric overlap; containment: how much of the SMALLER page is
 * contained in the larger one (catches "page B is a copy of a section of A").
 */
export function lexicalSimilarity(aText, bText) {
  const a = shingles(aText);
  const b = shingles(bText);
  if (!a.size || !b.size) return { jaccard: 0, containment: 0 };
  let inter = 0;
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  for (const s of small) if (large.has(s)) inter++;
  return {
    jaccard: inter / (a.size + b.size - inter),
    containment: inter / small.size,
  };
}

const sentences = (text) =>
  String(text ?? '')
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);

const normKey = (s) => normalizeWords(s).join(' ');

/* ---------- Duplicates ---------- */

/**
 * Assess whether two pages are duplicates using shingle similarity.
 * Confidence IS the similarity score (calibrated: exact copy ≈ 0.98,
 * lightly edited copy ≈ 0.75–0.9, unrelated ≈ <0.1). Paraphrased
 * (semantic) duplicates are a known false negative of this mode.
 */
export function heuristicAssessDuplicate(pageA, pageB) {
  const { jaccard, containment } = lexicalSimilarity(pageA.text, pageB.text);
  // Containment discounted so a tiny page quoted inside a big one doesn't
  // score as a full duplicate of it.
  const score = Math.max(jaccard, containment * 0.9);
  const confidence = Math.min(0.98, Math.round(score * 100) / 100);
  const isDuplicate = confidence >= 0.5;

  const evidence = isDuplicate ? sharedEvidence(pageA, pageB) : [];
  const output = {
    is_duplicate: isDuplicate && evidence.length > 0, // no evidence → no finding
    confidence,
    summary: isDuplicate
      ? `Lexical similarity ${Math.round(jaccard * 100)}% (containment ${Math.round(
          containment * 100
        )}%) between "${pageA.title}" and "${pageB.title}". Detected by built-in heuristics (no AI); paraphrased duplicates are not detected in this mode.`
      : '',
    recommended_action: containment > jaccard + 0.2 ? 'MERGE' : 'REVIEW',
    evidence,
  };
  return { output, model: HEURISTIC_MODEL, promptVersion: HEURISTIC_MODEL };
}

/** Shared/near-shared sentences as evidence — the matched text itself. */
function sharedEvidence(pageA, pageB, maxItems = 3) {
  const aSents = sentences(pageA.text);
  const bKeys = new Set(sentences(pageB.text).map(normKey));
  const shared = aSents
    .filter((s) => {
      const k = normKey(s);
      return k.split(' ').length >= 5 && bKeys.has(k);
    })
    .sort((x, y) => y.length - x.length)
    .slice(0, maxItems);

  if (shared.length) {
    return shared.flatMap((s) => [
      { page: 'A', excerpt: s.slice(0, 1000) },
      { page: 'B', excerpt: s.slice(0, 1000) },
    ]);
  }
  // No identical sentence (edited copy): use the A-sentence with the highest
  // shingle overlap against B, if it overlaps substantially.
  const bShingles = shingles(pageB.text);
  let best = null;
  for (const s of aSents) {
    const sh = shingles(s);
    if (sh.size < 3) continue;
    let inter = 0;
    for (const g of sh) if (bShingles.has(g)) inter++;
    const ratio = inter / sh.size;
    if (ratio >= 0.5 && (!best || ratio > best.ratio)) best = { s, ratio };
  }
  return best ? [{ page: 'A', excerpt: best.s.slice(0, 1000) }] : [];
}

/* ---------- Open questions ---------- */

// Explicit work markers — very high precision.
const MARKER_RE = /\b(TODO|TBD|TBC|FIXME|XXX)\b|\?{3,}/g;
// Template placeholders left in published pages.
const PLACEHOLDER_RE = /\{[^{}\n]{2,60}\}|<insert[^>\n]{0,60}>|\[(?:TBD|TBC|TODO|FILL ?IN|PLACEHOLDER)[^\]\n]{0,40}\]/gi;
// Uncertainty cues that make a "?" sentence a genuine open question rather
// than an FAQ heading or rhetorical device.
const CUE_RE =
  /\b(should we|do we|can we|who (?:is|owns|will)|not sure|unclear|unknown|undecided|to be (?:decided|confirmed)|need(?:s)? to (?:decide|confirm)|open question|pending)\b/i;

/**
 * Find open questions by pattern. Confidence encodes precision of the
 * pattern class:
 *   0.9  explicit markers (TODO/TBD/FIXME/???)
 *   0.85 template placeholders
 *   0.75 "?" sentence containing an uncertainty cue
 *   0.5  bare "?" sentence (FAQ headings etc.) — deliberately BELOW the
 *        default 0.7 threshold so it is filtered out (false-positive guard)
 */
export function heuristicAssessOpenQuestions(page) {
  const questions = [];
  const seen = new Set();
  const push = (question, excerpt, confidence, severity) => {
    const key = normKey(excerpt).slice(0, 120);
    if (!key || seen.has(key)) return;
    seen.add(key);
    questions.push({
      question: question.slice(0, 500),
      excerpt: excerpt.slice(0, 1000),
      confidence,
      severity,
    });
  };

  for (const s of sentences(page.text)) {
    MARKER_RE.lastIndex = 0;
    PLACEHOLDER_RE.lastIndex = 0;
    const marker = MARKER_RE.exec(s);
    if (marker) {
      push(`Unresolved marker "${marker[0]}" left in the page`, s, 0.9, 'MEDIUM');
      continue;
    }
    const placeholder = PLACEHOLDER_RE.exec(s);
    if (placeholder) {
      push(`Template placeholder "${placeholder[0]}" never filled in`, s, 0.85, 'MEDIUM');
      continue;
    }
    if (s.endsWith('?')) {
      if (CUE_RE.test(s)) push(`Open question: ${s}`, s, 0.75, 'LOW');
      else push(`Possible question (may be an FAQ heading): ${s}`, s, 0.5, 'LOW');
    }
  }
  return {
    output: { questions },
    model: HEURISTIC_MODEL,
    promptVersion: HEURISTIC_MODEL,
  };
}
