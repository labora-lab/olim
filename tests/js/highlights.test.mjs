/**
 * Behaviour of the highlight macro (olim/templates/macros/highlights.html).
 *
 * The macro is a few hundred lines of DOM manipulation that no Python test can
 * reach, and it has now produced several user-visible bugs. This executes the real
 * script against a DOM.
 *
 *   npm install            # linkedom is a devDependency
 *   make test-js
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parseHTML } from 'linkedom';

const MACRO = 'olim/templates/macros/highlights.html';
const UI = `<div id="highlights-container">
    <input id="highlight-input"><div id="highlights-list"></div>
  </div>`;

/** Load the macro's script into a fresh DOM and return its window/document. */
function mount(bodyHtml) {
  const script = readFileSync(MACRO, 'utf8').split('<script>')[1].split('</script>')[0];
  const { window, document } = parseHTML(
    `<!doctype html><html><body>${bodyHtml}${UI}</body></html>`
  );
  globalThis.window = window;
  globalThis.document = document;
  globalThis.NodeFilter = { SHOW_TEXT: 4 };
  globalThis.fetch = window.fetch = () => Promise.resolve({});
  window.CSS = { escape: (v) => String(v).replace(/["\\]/g, '\\$&') };
  window.showToast = () => {};
  window.console = { log() {}, error() {} };
  // linkedom ships no TreeWalker; a text-node walker is all the macro uses.
  document.createTreeWalker = (root) => {
    const nodes = [];
    (function collect(node) {
      for (const child of node.childNodes || []) {
        child.nodeType === 3 ? nodes.push(child) : collect(child);
      }
    })(root);
    let i = 0;
    return { nextNode: () => (i < nodes.length ? nodes[i++] : null) };
  };
  new Function(script).call(window);
  return { window, document };
}

const marks = (document) => [...document.querySelectorAll('mark')].map((m) => m.textContent);
const chips = (document) => document.querySelectorAll('#highlights-list [data-term]').length;

test('a lowercase term marks every casing, across containers', () => {
  const { window, document } = mount(`
    <div class="highlightable"><p>Patient has FEVER and fever and Fever.</p></div>
    <div class="highlightable"><p>Second node also mentions fever here.</p></div>`);
  window.initEntryHighlight(['fever']);
  assert.deepEqual(marks(document), ['FEVER', 'fever', 'Fever', 'fever']);
});

test('a mixed-case term marks every casing', () => {
  const { window, document } = mount('<div class="highlightable"><p>FEVER fever Fever</p></div>');
  window.initEntryHighlight(['FeVeR']);
  assert.equal(marks(document).length, 3);
});

test('a differently-cased duplicate is recognised, not added again', () => {
  const { window, document } = mount('<div class="highlightable"><p>fever</p></div>');
  window.initEntryHighlight(['fever']);
  assert.equal(window.addHighlight('FEVER'), false, 'should report "already present"');
  assert.equal(chips(document), 1);
});

test('removal is case-insensitive', () => {
  const { window, document } = mount('<div class="highlightable"><p>Fever and fever</p></div>');
  window.initEntryHighlight(['fever']);
  assert.equal(marks(document).length, 2);
  window.removeHighlight('FEVER');
  assert.equal(marks(document).length, 0);
  assert.equal(chips(document), 0);
});

test('a term containing a quote neither throws nor fails to match', () => {
  const { window, document } = mount('<div class="highlightable"><p>the "quoted" word</p></div>');
  window.initEntryHighlight(['"quoted"']);
  assert.equal(marks(document).length, 1);
  window.removeHighlight('"quoted"');
  assert.equal(marks(document).length, 0);
});

test('distinct terms each get their own chip and marks', () => {
  const { window, document } = mount('<div class="highlightable"><p>fever and cough</p></div>');
  window.initEntryHighlight(['fever', 'COUGH']);
  assert.equal(marks(document).length, 2);
  assert.equal(chips(document), 2);
});

test('nothing is marked without a .highlightable container', () => {
  const { window, document } = mount('<div class="prose"><p>fever</p></div>');
  window.initEntryHighlight(['fever']);
  assert.equal(marks(document).length, 0, 'no target');
  assert.equal(chips(document), 1, 'but the chip still renders — the silent-failure mode');
});
