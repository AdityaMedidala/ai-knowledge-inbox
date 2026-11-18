/// <reference types="node" />
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { validateIngest } from './ingest-validation.ts'
import { NOTE_MAX_CHARS, TITLE_MAX_CHARS } from './limits.ts'

test('a note needs text, within the limits; the error names the field', () => {
  assert.deepEqual(validateIngest('note', '   ', '', '')?.field, 'content')
  assert.equal(validateIngest('note', 'x'.repeat(NOTE_MAX_CHARS + 1), '', '')?.field, 'content')
  assert.equal(validateIngest('note', 'ok', 'x'.repeat(TITLE_MAX_CHARS + 1), '')?.field, 'title')
  assert.equal(validateIngest('note', 'ok', 'Title', ''), null)
})

test('a URL must be http(s)', () => {
  assert.equal(validateIngest('url', '', '', 'ftp://x.dev')?.field, 'url')
  assert.equal(validateIngest('url', '', '', 'example.com')?.field, 'url')
  assert.equal(validateIngest('url', '', '', ' https://sqlite.org/wal.html '), null)
})
