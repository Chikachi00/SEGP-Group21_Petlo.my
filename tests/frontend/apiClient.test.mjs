import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient, ApiError } from "../../src/services/apiClient.ts";

test("JSON requests use the configured prefix and serialize once", async () => {
  const client = createApiClient({ baseUrl: "https://example.invalid/api/v1/", fetchImpl: async (url, init) => {
    assert.equal(url, "https://example.invalid/api/v1/sessions");
    assert.equal(init.method, "POST");
    assert.equal(init.body, '{"dog_id":"dog-1"}');
    assert.equal(init.headers.get("Content-Type"), "application/json");
    return Response.json({ session_id: "session-1" }, { status: 201 });
  }});
  assert.deepEqual(await client.request("POST", "/sessions", { json: { dog_id: "dog-1" } }), { session_id: "session-1" });
});

test("multipart upload preserves FormData and lets fetch generate its boundary", async () => {
  const body = new FormData();
  body.append("camera_perspective", "front");
  const client = createApiClient({ baseUrl: "/api/v1", fetchImpl: async (_url, init) => {
    assert.equal(init.body, body);
    assert.equal(init.headers.has("Content-Type"), false);
    return Response.json({ video_id: "v-1" });
  }});
  await client.request("POST", "/videos", { body, headers: { "Content-Type": "multipart/form-data" } });
});

test("server errors preserve status, code and request ID without retrying a mutation", async () => {
  let calls = 0;
  const client = createApiClient({ baseUrl: "/api/v1", fetchImpl: async () => {
    calls++;
    return Response.json({ error: { code: "JOB_ALREADY_RUNNING", message: "Already running.", request_id: "r-1" } }, { status: 409 });
  }});
  await assert.rejects(client.request("POST", "/analysis"), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.equal(error.code, "JOB_ALREADY_RUNNING");
    assert.equal(error.requestId, "r-1");
    return true;
  });
  assert.equal(calls, 1);
});

test("HTML and empty success responses are not treated as API data", async () => {
  for (const body of ["<html>SPA fallback</html>", ""]) {
    const client = createApiClient({ baseUrl: "/api/v1", fetchImpl: async () => new Response(body) });
    await assert.rejects(client.request("GET", "/sessions"), { code: "INVALID_RESPONSE" });
  }
  const client = createApiClient({ baseUrl: "/api/v1", fetchImpl: async () => new Response(null, { status: 204 }) });
  assert.equal(await client.request("DELETE", "/resource"), undefined);
});

test("caller cancellation remains distinguishable from an API timeout", async () => {
  const fetchImpl = async (_url, { signal }) => new Promise((_resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
  const client = createApiClient({ baseUrl: "/api/v1", fetchImpl });
  const controller = new AbortController();
  const request = client.request("GET", "/job", { signal: controller.signal });
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  await assert.rejects(client.request("GET", "/job", { timeoutMs: 5 }), { code: "TIMEOUT" });
});
