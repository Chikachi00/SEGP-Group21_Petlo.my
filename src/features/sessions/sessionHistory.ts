import { ApiError } from "../../services/apiClient.ts";
import { listSessions } from "./api.ts";
import type { SessionList, SessionSummary } from "./types.ts";

const PAGE_SIZE = 100;
const CONCURRENT_PAGES = 3;

function checkPage(result: SessionList, page: number) {
  if (!Array.isArray(result.items) || !Number.isSafeInteger(result.total) || result.total < 0 ||
      result.items.length < Math.max(0, Math.min(PAGE_SIZE, result.total - (page - 1) * PAGE_SIZE))) {
    throw new ApiError("Incomplete session history returned by server.", 200, "INVALID_RESPONSE");
  }
}

/** Fetch independent pages concurrently, retaining the server's newest-first order. */
export async function loadSessionHistory(options: {
  signal: AbortSignal;
  trash?: boolean;
  readPage?: typeof listSessions;
}): Promise<SessionSummary[]> {
  const { signal, trash = false, readPage = listSessions } = options;
  signal.throwIfAborted();
  const first = await readPage({ page: 1, pageSize: PAGE_SIZE, trash, signal });
  signal.throwIfAborted();
  checkPage(first, 1);
  const pageCount = Math.ceil(first.total / PAGE_SIZE);
  if (pageCount <= 1) return first.items;

  const controller = new AbortController();
  const pageSignal = AbortSignal.any([signal, controller.signal]);
  const pages: SessionSummary[][] = [first.items];
  let nextPage = 2;
  try {
    await Promise.all(Array.from({ length: Math.min(CONCURRENT_PAGES, pageCount - 1) }, async () => {
      while (nextPage <= pageCount) {
        pageSignal.throwIfAborted();
        const page = nextPage++;
        const result = await readPage({ page, pageSize: PAGE_SIZE, trash, signal: pageSignal });
        pageSignal.throwIfAborted();
        checkPage(result, page);
        pages[page - 1] = result.items;
      }
    }));
    const items = pages.flat();
    if (items.length < first.total) {
      throw new ApiError("Incomplete session history returned by server.", 200, "INVALID_RESPONSE");
    }
    return items;
  } finally {
    // A failed page stops outstanding requests instead of leaving a background waterfall.
    controller.abort();
  }
}
