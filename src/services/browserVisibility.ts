/** Suspend background reads while the browser cannot display their results. */
export function waitUntilVisible(signal: AbortSignal, source: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener"> | undefined =
  typeof document === "undefined" ? undefined : document): Promise<void> {
  signal.throwIfAborted();
  if (!source || source.visibilityState !== "hidden") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      source.removeEventListener("visibilitychange", onVisibility);
      signal.removeEventListener("abort", onAbort);
    };
    const onVisibility = () => {
      if (source.visibilityState === "hidden") return;
      cleanup();
      resolve();
    };
    const onAbort = () => {
      cleanup();
      reject(signal.reason ?? new DOMException("Request aborted", "AbortError"));
    };
    source.addEventListener("visibilitychange", onVisibility);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
    else onVisibility();
  });
}
