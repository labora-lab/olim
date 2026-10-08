/**
 * Hiding and showing labels on the labeling screens (scripts.js hideById/unhideById
 * and the hidden-labels helper from macros/labels-menu.html).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parseHTML } from 'linkedom';

const FUNCTIONS = ['fillPlaceholders', 'hideById', 'unhideById', 'updateHiddenLabelsNotice'];

function mount() {
  const { document } = parseHTML(`<!doctype html><html><body>
    <div id="hidden-labels-notice" data-title="Hidden labels ({count})" class="hidden">
      <span data-role="title">Hidden labels (0)</span>
      <button data-hidden-label="12" class="hidden"></button>
      <button data-hidden-label="15" class="hidden"></button>
    </div>
    <div id="label_12"><button id="hide_btn_12"></button><button id="unhide_btn_12" class="hidden"></button></div>
    <div id="label_15"><button id="hide_btn_15"></button><button id="unhide_btn_15" class="hidden"></button></div>
  </body></html>`);
  globalThis.document = document;
  const source = readFileSync('olim/static/js/scripts.js', 'utf8');
  const bodies = FUNCTIONS.map((name) => {
    const start = source.indexOf(`function ${name}(`);
    return source.slice(start, source.indexOf('\n}\n', start) + 2);
  });
  const api = new Function(`${bodies.join('\n')}; return { hideById, unhideById };`)();
  return { document, ...api };
}

const title = (d) => d.querySelector('[data-role="title"]').textContent;
const noticeShown = (d) => !d.getElementById('hidden-labels-notice').classList.contains('hidden');

test('hiding a label lists it in the helper', () => {
  const { document, hideById } = mount();
  hideById('12');
  assert.equal(document.getElementById('label_12').style.display, 'none');
  assert.ok(noticeShown(document));
  assert.equal(title(document), 'Hidden labels (1)');
  hideById('15');
  assert.equal(title(document), 'Hidden labels (2)');
});

test('showing a label again makes it visible and updates the helper', () => {
  const { document, hideById, unhideById } = mount();
  hideById('12');
  document.getElementById('label_12').classList.add('hidden'); // as rendered server-side
  unhideById('12');
  const label = document.getElementById('label_12');
  assert.equal(label.style.display, '');
  assert.equal(label.classList.contains('hidden'), false);
  assert.equal(noticeShown(document), false);
});
