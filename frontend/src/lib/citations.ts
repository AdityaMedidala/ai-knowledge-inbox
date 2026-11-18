export const CITE_HREF = '#cite-'

// [1], [1, 2], [1][2] and fullwidth 【1】 (some models emit it), optionally with a locator
// suffix after the number (【2†section 6】, 【4:0†source】, [3†L10-L20]). Same rule as the
// backend's citations.MARKER. Not markdown links like [1](…).
const MARKER = /[[【](\d+(?:\s*,\s*\d+)*)(?:[†‡:][^\]】\n]{0,80})?[\]】](?!\()/g

/** Turn [n] markers that point at a real source into `[n](#cite-n)` links; leave others as text. */
export function linkCitations(markdown: string, validRefs: ReadonlySet<number>): string {
  return markdown.replace(MARKER, (whole, refs: string) => {
    const numbers = refs.split(',').map((n) => Number(n.trim()))
    if (!numbers.every((n) => validRefs.has(n))) return whole
    return numbers.map((n) => `[${n}](${CITE_HREF}${n})`).join('')
  })
}
