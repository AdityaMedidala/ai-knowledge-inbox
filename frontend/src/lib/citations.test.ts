/// <reference types="node" />
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { linkCitations, markerParts } from './citations.ts'

const refs = new Set([1, 2, 3, 4, 5])

test('links plain, grouped and adjacent markers', () => {
  assert.equal(
    linkCitations('A [1]. B [2, 3]. C [4][5].', refs),
    'A [1.](#cite-1) B [2](#cite-2)[3.](#cite-3) C [4](#cite-4)[5.](#cite-5)',
  )
})

test('links fullwidth markers', () => {
  assert.equal(linkCitations('A 【1】【3】.', refs), 'A [1](#cite-1)[3.](#cite-3)')
})

test('links markers with a locator suffix and drops the suffix', () => {
  assert.equal(
    linkCitations('Docs say so【2†section 6】【4:0†source】 and [3†L10-L20].', refs),
    'Docs say so[2](#cite-2)[4](#cite-4) and [3.](#cite-3)',
  )
})

test('leaves unknown refs, markdown links and non-citation brackets alone', () => {
  const text = 'Gone [9]. Link [1](https://x.dev). List [a], [x†1] and [1 2].'
  assert.equal(linkCitations(text, refs), text)
})

test('keeps the punctuation after a marker with the pill, and leaves other text alone', () => {
  assert.equal(linkCitations('Yes [1]), then [2]!', refs), 'Yes [1),](#cite-1) then [2!](#cite-2)')
  assert.equal(linkCitations('Unknown [9].', refs), 'Unknown [9].')
})

test('markerParts splits a link text into ref and trailing punctuation', () => {
  assert.deepEqual(markerParts('3.'), { ref: 3, trailing: '.' })
  assert.deepEqual(markerParts('12'), { ref: 12, trailing: '' })
})
