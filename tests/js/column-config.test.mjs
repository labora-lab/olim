/**
 * Column configuration editor (olim/templates/macros/column-config.html), shared by
 * the dataset upload form and the dataset edit page. Runs the real script from
 * scripts.js against the macro's markup.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parseHTML } from 'linkedom';

const MACRO = 'olim/templates/macros/column-config.html';
const SCRIPTS = 'olim/static/js/scripts.js';

const FIELDS = [
  { field: 'a', label: 'A' },
  { field: 'metadata_text', label: 'text' },
  { field: 'b', label: 'B' },
];

/** Mount the macro (Jinja stripped) and return a new editor plus its root. */
function mount(options) {
  const markup = readFileSync(MACRO, 'utf8')
    .replace(/\{#[\s\S]*?#\}/g, '')
    .replace(/\{%[\s\S]*?%\}/g, '')
    .replace(/\{\{\s*id\s*\}\}/g, 'editor')
    .replace(/\{\{[\s\S]*?\}\}/g, 'label');
  const { window, document } = parseHTML(`<!doctype html><html><body>${markup}</body></html>`);
  globalThis.document = document;
  globalThis.Option = class {
    constructor(text, value) {
      const option = document.createElement('option');
      option.textContent = text;
      option.value = value;
      return option;
    }
  };
  const source = readFileSync(SCRIPTS, 'utf8');
  const start = source.indexOf('function createColumnConfigEditor');
  const body = source.slice(start, source.indexOf('\n}\n', start) + 2);
  const create = new Function(`${body}; return createColumnConfigEditor;`)();
  const root = document.getElementById('editor');
  return { editor: create(root, options), root, window };
}

const rows = (root) =>
  [...root.querySelectorAll('[data-role="list"] [data-role="name"]')].map((n) => n.textContent);
const addOptions = (root) =>
  [...root.querySelectorAll('[data-role="add"] option')].slice(1).map((o) => o.value);

/** linkedom's <select> has no value setter: select through the options instead. */
function choose(select, window, value) {
  select.querySelectorAll('option').forEach((o) => o.toggleAttribute('selected', o.value === value));
  select.dispatchEvent(new window.Event('change'));
}

const pick = (root, window, value) => choose(root.querySelector('[data-role="add"]'), window, value);

test('starts from the given config with labels for fields', () => {
  const { editor, root } = mount({
    fields: FIELDS,
    config: {
      text_is_html: true,
      show_remaining_as_metadata: false,
      extra_columns: [{ column: 'metadata_text', render_as: 'pdf_url', as_tab: true }],
    },
  });
  assert.deepEqual(rows(root), ['text']);
  assert.deepEqual(addOptions(root), ['a', 'b']);
  assert.deepEqual(editor.getConfig(), {
    text_is_html: true,
    text_hidden: false,
    show_remaining_as_metadata: false,
    extra_columns: [{ column: 'metadata_text', render_as: 'pdf', show_title: false, as_tab: true }],
  });
});

test('defaults show remaining columns as metadata', () => {
  const { editor, root } = mount({ fields: FIELDS });
  assert.equal(editor.getConfig().show_remaining_as_metadata, true);
  assert.equal(root.querySelector('[data-role="empty"]').classList.contains('hidden'), false);
});

test('adding, reordering and removing extra columns reports each change', () => {
  const changes = [];
  const { editor, root, window } = mount({ fields: FIELDS, onChange: (c) => changes.push(c) });
  pick(root, window, 'a');
  pick(root, window, 'b');
  assert.deepEqual(rows(root), ['A', 'B']);
  assert.deepEqual(addOptions(root), ['metadata_text']);

  root.querySelectorAll('[data-action="up"]')[1].dispatchEvent(new window.Event('click'));
  assert.deepEqual(rows(root), ['B', 'A']);

  const renderAs = root.querySelectorAll('[data-field="render_as"]')[1];
  choose(renderAs, window, 'image');
  assert.equal(editor.getConfig().extra_columns[1].render_as, 'image');

  root.querySelector('[data-action="remove"]').dispatchEvent(new window.Event('click'));
  assert.deepEqual(rows(root), ['A']);
  assert.equal(changes.length, 5);
  assert.deepEqual(
    changes.at(-1).extra_columns.map((c) => c.column),
    ['a'],
  );
});

test('fields that disappear drop their extra columns', () => {
  const { editor } = mount({
    fields: FIELDS,
    config: { extra_columns: [{ column: 'a' }, { column: 'b' }] },
  });
  editor.setFields(FIELDS.filter((f) => f.field !== 'a'));
  assert.deepEqual(
    editor.getConfig().extra_columns.map((c) => c.column),
    ['b'],
  );
});
