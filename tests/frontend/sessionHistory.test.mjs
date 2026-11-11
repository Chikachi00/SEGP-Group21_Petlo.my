import test from "node:test";
import assert from "node:assert/strict";
import { loadSessionHistory } from "../../src/features/sessions/sessionHistory.ts";

function pageResult(page, total = 800) {
  return { page, page_size: 100, total,
    items: Array.from({ length: Math.min(100, total - (page - 1) * 100) }, (_, index) => ({ session_id: `s-${(page - 1) * 100 + index}` })) };
}

test("history pages overlap within a fixed limit and retain server ordering", async () => {
  let active = 0, maxActive = 0;
  const calls = [];
  const result = await loadSessionHistory({ signal: new AbortController().signal, trash: true,
    readPage: async ({ page, pageSize, trash }) => {
      assert.equal(pageSize, 100);
      assert.equal(trash, true);
      calls.push(page);
      maxActive = Math.max(maxActive, ++active);
      await new Promise(resolve => setTimeout(resolve, page % 3));
      active--;
      return pageResult(page);
    },
  });
  assert.equal(maxActive, 3);
  assert.deepEqual(calls, [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(result.map(session => session.session_id), Array.from({ length: 800 }, (_, index) => `s-${index}`));
});

test("single-page and empty histories make only one request", async () => {
  for (const total of [0, 23, 100]) {
    let calls = 0;
    const result = await loadSessionHistory({ signal: new AbortController().signal,
      readPage: async ({ page }) => { calls++; return pageResult(page, total); },
    });
    assert.equal(result.length, total);
    assert.equal(calls, 1);
  }
});

test("a failed history page aborts outstanding requests and stops scheduling pages", async () => {
  const calls = [];
  let cancelled = 0;
  await assert.rejects(loadSessionHistory({ signal: new AbortController().signal,
    readPage: async ({ page, signal }) => {
      calls.push(page);
      if (page === 1) return pageResult(page);
      if (page === 2) throw new Error("offline");
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => {
        cancelled++;
        reject(signal.reason);
      }, { once: true }));
    },
  }), /offline/);
  assert.deepEqual(calls, [1, 2, 3, 4]);
  assert.equal(cancelled, 2);
});

test("cancellation prevents history reads and incomplete data is rejected", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(loadSessionHistory({ signal: controller.signal,
    readPage: async () => { assert.fail("Aborted history must not read a page."); },
  }), { name: "AbortError" });
  for (const total of [-1, Number.NaN, 100]) {
    await assert.rejects(loadSessionHistory({ signal: new AbortController().signal,
      readPage: async () => ({ items: [], total }),
    }), { code: "INVALID_RESPONSE" });
  }
  await assert.rejects(loadSessionHistory({ signal: new AbortController().signal,
    readPage: async () => ({ items: [{ session_id: "s-1" }], total: 23 }),
  }), { code: "INVALID_RESPONSE" });
  await assert.rejects(loadSessionHistory({ signal: new AbortController().signal,
    readPage: async ({ page }) => ({ ...pageResult(page, 200), items: [{ session_id: `s-${page}` }] }),
  }), { code: "INVALID_RESPONSE" });
});
