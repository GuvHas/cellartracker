"""Run cellar.html's real script under node, with a DOM good enough to load it.

The page has no build step and no test framework - deliberately, because it is
served straight out of the integration directory into the Home Assistant
Companion app, where every kilobyte is a cold start on someone's phone. So
there is no bundler to hang a Jest or Vitest suite off, and adding npm to a
HACS integration repository would cost more than it returns.

What is left is better than it sounds: the page's decision-making lives in
plain top-level functions with no DOM access at all, and node can call them
directly. That is the contract this harness depends on and the reason the
source keeps those functions at the top level rather than tucked inside an
IIFE - a comment in cellar.html says so.

``test_dashboard_token`` has its own, smaller prelude. The duplication is
deliberate: it answers a different question (auth wiring at load) with a
different stub, and merging the two would make both fragile.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

CELLAR_HTML = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components" / "cellar_tracker" / "www" / "cellar.html"
)

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to exercise the dashboard"
)


def page_script() -> str:
    """The page's own <script> body, verbatim."""
    return re.search(r"<script>(.*)</script>", CELLAR_HTML.read_text(), re.S).group(1)


# A fake element that records enough to be inspected. Not a DOM implementation
# and not trying to be: it exists so the page's load-time wiring runs, and so a
# render can be asserted on without a headless browser.
PRELUDE = """
const fixture = %s;

function makeElement(tag) {
    const el = {
        tagName: String(tag || 'div').toUpperCase(),
        children: [], listeners: {}, dataset: {}, style: {},
        className: '', textContent: '', value: '', hidden: false,
        attributes: {},
        classList: {
            _set: new Set(),
            add(...names) { names.forEach((n) => el.classList._set.add(n)); },
            remove(...names) { names.forEach((n) => el.classList._set.delete(n)); },
            toggle(name, on) { on ? el.classList._set.add(name) : el.classList._set.delete(name); },
            contains(name) { return el.classList._set.has(name); },
        },
        // A real DOM inserts a fragment's children and discards the
        // fragment itself. Nesting it instead would let a test pass against
        // a shape the browser never produces.
        appendChild(child) { el.children.push(...flatten(child)); return child; },
        append(...kids) { kids.forEach((k) => el.children.push(...flatten(k))); },
        replaceChildren(...kids) {
            el.children = kids.reduce((acc, k) => acc.concat(flatten(k)), []);
        },
        removeChild(child) {
            const at = el.children.indexOf(child);
            if (at !== -1) el.children.splice(at, 1);
            return child;
        },
        setAttribute(name, value) { el.attributes[name] = String(value); },
        getAttribute(name) { return name in el.attributes ? el.attributes[name] : null; },
        removeAttribute(name) { delete el.attributes[name]; },
        addEventListener(type, fn) { (el.listeners[type] ||= []).push(fn); },
        dispatch(type, event) { (el.listeners[type] || []).forEach((fn) => fn(event || {})); },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        closest() { return null; },
        focus() {},
        select() { el.selected = true; },
    };
    return el;
}

function flatten(node) {
    return node && node.tagName === '#FRAGMENT' ? node.children : [node];
}

const elements = {};
function byId(id) { return (elements[id] ||= makeElement('div')); }

globalThis.sessionStorage = {
    getItem: () => null, setItem: () => {}, removeItem: () => {},
};

globalThis.window = {
    location: { search: fixture.search || '', pathname: '/cellartracker/cellar.html' },
    history: { replaceState() {} },
    parent: { document: { querySelector: () => null } },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
};

globalThis.document = {
    getElementById: byId,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: makeElement,
    createDocumentFragment: () => makeElement('#fragment'),
    addEventListener() {},
    body: makeElement('body'),
    // The legacy path, and the only one that works without a secure context.
    execCommand(command) {
        if (fixture.execCommand === false) return false;
        if (command === 'copy') copied.push('exec');
        return fixture.execCommand !== false;
    },
};

// Home Assistant is very often served over plain http on a LAN address, which
// is not a secure context - so navigator.clipboard is frequently absent
// entirely. The fixture picks which world the page is running in.
const copied = [];
const clipboard = fixture.clipboard || 'async';
// defineProperty, not assignment: node 21+ ships its own `navigator` as a
// getter-only global, so `globalThis.navigator = ...` silently does nothing
// and every clipboard fixture would quietly test the same world.
Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    writable: true,
    value: clipboard === 'missing'
        ? {}
        : {
            clipboard: {
                writeText: (text) => clipboard === 'rejects'
                    ? Promise.reject(new Error('denied'))
                    : (copied.push(text), Promise.resolve()),
            },
        },
});

// The stubs above are worthless if the runtime refused one of them, and a
// refusal is silent outside strict mode. Fail loudly instead.
if (clipboard === 'missing' && navigator.clipboard) {
    throw new Error('the navigator stub did not take effect');
}
if (clipboard !== 'missing' && !navigator.clipboard) {
    throw new Error('the navigator stub did not take effect');
}

// The page fetches at load. Answer with the fixture so the render path runs;
// an empty fixture answers 401, which is the existing tests' scenario.
globalThis.fetch = (url) => {
    const path = String(url);
    if (!fixture.wines) return Promise.resolve({ ok: false, status: 401, json: async () => ({}) });
    const body = path.indexOf('settings') !== -1
        ? { currency: 'SEK', currency_symbol: 'kr' }
        : fixture.wines;
    return Promise.resolve({ ok: true, status: 200, json: async () => body });
};

globalThis.console = { ...console, warn() {}, error() {} };

function report(name, ok, detail) {
    if (!ok) { console.log('FAIL ' + name + (detail ? ': ' + detail : '')); failures++; }
}
let failures = 0;
"""


def run_js(checks: str, *, wines=None, search="", clipboard="async",
           exec_command=True) -> str:
    """Load the page script, then run `checks`. Non-zero exit means a failure."""
    fixture = json.dumps(
        {"wines": wines, "search": search,
         "clipboard": clipboard, "execCommand": exec_command}
    )
    source = "\n".join(
        [
            PRELUDE % fixture,
            page_script(),
            textwrap.dedent(checks),
            "if (failures) process.exit(1);",
        ]
    )
    result = subprocess.run(
        ["node", "--input-type=commonjs", "-e", source],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).strip()
    return result.stdout


def check(expression: str, message: str) -> str:
    """One assertion, reported by name rather than by a bare exit code."""
    return f"report({json.dumps(message)}, {expression});\n"


def equals(expression: str, expected, message: str) -> str:
    """Assert a value, and print what was actually produced when it differs."""
    wanted = json.dumps(expected)
    return (
        f"{{ const actual = {expression};\n"
        f"  report({json.dumps(message)},\n"
        f"    JSON.stringify(actual) === JSON.stringify({wanted}),\n"
        f"    'expected ' + JSON.stringify({wanted}) + ', got ' + JSON.stringify(actual)); }}\n"
    )
