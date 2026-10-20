/** API mode is explicit: connection failures never silently fall back to demo results. */
export const useApiMode = import.meta.env.VITE_USE_API === "true";
