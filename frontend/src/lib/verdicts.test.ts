/// <reference types="node" />
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { insertVerdictMarkers, summarizeVerdicts, verdictKind } from './verdicts.ts'

const v = (index: number) => `[✓](#verdict-${index})`

test('places each marker after the sentence and its citations', () => {
  const markdown = 'Readers never block [1]. Checkpoints copy pages【2】【3】.'
  const out = insertVerdictMarkers(markdown, [
    { index: 0, sentence: 'Readers never block.' },
    { index: 1, sentence: 'Checkpoints copy pages.' },
  ])
  assert.equal(out, `Readers never block [1].${v(0)} Checkpoints copy pages【2】【3】.${v(1)}`)
})

test('puts the marker after trailing citations that follow the full stop', () => {
  const out = insertVerdictMarkers('The default is 5 seconds. [1]', [
    { index: 0, sentence: 'The default is 5 seconds.' },
  ])
  assert.equal(out, `The default is 5 seconds. [1]${v(0)}`)
})

test('matches through bold markup, list items and line breaks', () => {
  const markdown = '- **Readers** never block\n  writers [1].\n- Only one writer.'
  const out = insertVerdictMarkers(markdown, [
    { index: 0, sentence: 'Readers never block writers.' },
    { index: 1, sentence: 'Only one writer.' },
  ])
  assert.equal(out, `- **Readers** never block\n  writers [1].${v(0)}\n- Only one writer.${v(1)}`)
})

test('skips sentences it cannot find and keeps going in order', () => {
  const out = insertVerdictMarkers('Alpha. Beta.', [
    { index: 0, sentence: 'Gamma.' },
    { index: 1, sentence: 'Beta.' },
  ])
  assert.equal(out, `Alpha. Beta.${v(1)}`)
})

test('repeated sentences are matched left to right', () => {
  const out = insertVerdictMarkers('Yes. Yes.', [
    { index: 0, sentence: 'Yes.' },
    { index: 1, sentence: 'Yes.' },
  ])
  assert.equal(out, `Yes.${v(0)} Yes.${v(1)}`)
})

test('uncited sentences are their own kind and are left out of the cited count', () => {
  const sentences = [
    { verdict: 'supported', decided_by: 'jev' },
    { verdict: 'unsupported', decided_by: 'no_citation' },
    { verdict: 'unsupported', decided_by: 'jev' },
    { verdict: 'partial', decided_by: 'groq' },
  ] as const
  assert.deepEqual(sentences.map(verdictKind), ['supported', 'uncited', 'unsupported', 'partial'])
  assert.deepEqual(summarizeVerdicts(sentences), { cited: 3, supported: 1, uncited: 1 })
})
