export const CITE_HREF = '#cite-'

// [1], [1, 2], [1][2] and fullwidth 【1】 (some models emit it), optionally with a locator
// suffix after the number (【2†section 6】, 【4:0†source】, [3†L10-L20]). Same rule as the
// backend's citations.MARKER. Not markdown links like [1](…).
export const MARKER_SOURCE = String.raw`[[【](\d+(?:\s*,\s*\d+)*)(?:[†‡:][^\]】\n]{0,80})?[\]】](?!\()`
// A marker plus the punctuation right after it, which is kept with the pill so it never wraps alone.
const LINKABLE = new RegExp(`${MARKER_SOURCE}([.,;:!?)]{0,3})`, 'g')

/** Turn [n] markers that point at a real source into `[n](#cite-n)` links; leave others as text.
 * Punctuation right after a marker moves into the last link's text (`[1.](#cite-1)`), so the
 * renderer can keep pill and punctuation together; see `markerParts`. */
export function linkCitations(markdown: string, validRefs: ReadonlySet<number>): string {
  return markdown.replace(LINKABLE, (whole, refs: string, trailing: string) => {
    const numbers = refs.split(',').map((n) => Number(n.trim()))
    if (!numbers.every((n) => validRefs.has(n))) return whole
    const last = numbers.length - 1
    return numbers
      .map((n, i) => `[${n}${i === last ? trailing : ''}](${CITE_HREF}${n})`)
      .join('')
  })
}

/** Split a citation link's text (`1.`) into its ref and the punctuation that follows the pill. */
export function markerParts(linkText: string): { ref: number; trailing: string } {
  const match = /^(\d+)(.*)$/.exec(linkText)
  return { ref: Number(match?.[1]), trailing: match?.[2] ?? '' }
}
