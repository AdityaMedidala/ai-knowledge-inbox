import { MARKER_SOURCE } from './citations.ts'

export const VERDICT_HREF = '#verdict-'

export interface SentenceRef {
  index: number
  sentence: string // as the server split it: no [n] markers, no ** , whitespace collapsed
}

const MARKER_AT = new RegExp(MARKER_SOURCE, 'y')
const BOLD = '**'

/** Non-whitespace characters of the markdown with their offsets, skipping ** and [n] markers,
 * so text compares equal to the server's cleaned sentences. */
function skeleton(markdown: string): { text: string; offsets: number[] } {
  let text = ''
  const offsets: number[] = []
  let i = 0
  while (i < markdown.length) {
    if (markdown.startsWith(BOLD, i)) {
      i += BOLD.length
      continue
    }
    MARKER_AT.lastIndex = i
    const marker = MARKER_AT.exec(markdown)
    if (marker) {
      i += marker[0].length
      continue
    }
    if (!/\s/.test(markdown[i] ?? '')) {
      text += markdown[i]
      offsets.push(i)
    }
    i += 1
  }
  return { text, offsets }
}

/** Offset just after the sentence's trailing citation markers (so the verdict follows them). */
function afterMarkers(markdown: string, end: number): number {
  let position = end
  for (;;) {
    let probe = position
    while (markdown[probe] === ' ' || markdown[probe] === '\t') probe += 1
    MARKER_AT.lastIndex = probe
    const marker = MARKER_AT.exec(markdown)
    if (!marker) return position
    position = probe + marker[0].length
  }
}

/** Insert `[✓](#verdict-<index>)` links after each verified sentence, in order. A sentence
 * that can't be located is left unmarked (it still counts in the summary). */
export function insertVerdictMarkers(markdown: string, sentences: readonly SentenceRef[]): string {
  const { text, offsets } = skeleton(markdown)
  const inserts: { at: number; token: string }[] = []
  let cursor = 0
  for (const { index, sentence } of sentences) {
    const needle = sentence.replace(/\s+/g, '')
    const found = needle ? text.indexOf(needle, cursor) : -1
    if (found < 0) continue
    const last = offsets[found + needle.length - 1]
    if (last === undefined) continue
    inserts.push({ at: afterMarkers(markdown, last + 1), token: `[✓](${VERDICT_HREF}${index})` })
    cursor = found + needle.length
  }
  let out = markdown
  for (const { at, token } of inserts.reverse()) out = out.slice(0, at) + token + out.slice(at)
  return out
}

export interface JudgedSentence {
  verdict: 'supported' | 'partial' | 'unsupported'
  decided_by: string
}

export type VerdictKind = JudgedSentence['verdict'] | 'uncited'

/** The server marks a sentence with no citation `unsupported` without checking it; the UI shows
 * it as its own neutral kind so "not checked" never looks like "contradicted by the sources". */
export function verdictKind(sentence: JudgedSentence): VerdictKind {
  return sentence.decided_by === 'no_citation' ? 'uncited' : sentence.verdict
}

export function summarizeVerdicts(sentences: readonly JudgedSentence[]): {
  cited: number
  supported: number
  uncited: number
} {
  const kinds = sentences.map(verdictKind)
  const uncited = kinds.filter((kind) => kind === 'uncited').length
  return {
    cited: kinds.length - uncited,
    supported: kinds.filter((kind) => kind === 'supported').length,
    uncited,
  }
}
