import test from "node:test";
import assert from "node:assert/strict";
import { waitUntilVisible } from "../../src/services/browserVisibility.ts";

class VisibilitySource extends EventTarget {
  visibilityState = "hidden";
  listeners = new Set();
  addEventListener(type, listener, options) {
    this.listeners.add(listener);
    super.addEventListener(type, listener, options);
  }
  removeEventListener(type, listener) {
    this.listeners.delete(listener);
    super.removeEventListener(type, listener);
  }
  show() {
    this.visibilityState = "visible";
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

test("hidden reads wait for visibility and remove their event listeners", async () => {
  const source = new VisibilitySource();
  let resolved = false;
  const waiting = waitUntilVisible(new AbortController().signal, source).then(() => { resolved = true; });
  await Promise.resolve();
  assert.equal(resolved, false);
  assert.equal(source.listeners.size, 1);
  source.show();
  await waiting;
  assert.equal(resolved, true);
  assert.equal(source.listeners.size, 0);
});

test("hidden waits respect caller cancellation and clean up listeners", async () => {
  const source = new VisibilitySource();
  const controller = new AbortController();
  const waiting = waitUntilVisible(controller.signal, source);
  controller.abort();
  await assert.rejects(waiting, { name: "AbortError" });
  assert.equal(source.listeners.size, 0);
});

test("visible and non-browser callers continue immediately", async () => {
  const source = new VisibilitySource();
  source.show();
  await waitUntilVisible(new AbortController().signal, source);
  await waitUntilVisible(new AbortController().signal);
  assert.equal(source.listeners.size, 0);
});
