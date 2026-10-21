export const activeJobStatuses = ["queued", "running", "pausing", "paused", "cancelling"] as const;
export const terminalJobStatuses = ["completed", "failed", "cancelled"] as const;

export function isActiveJob(status: string | undefined | null): boolean {
  return activeJobStatuses.some(value => value === status);
}

export function isTerminalJob(status: string | undefined | null): boolean {
  return terminalJobStatuses.some(value => value === status);
}

export function defaultSessionName(session: { name?: string; date: string }): string {
  return session.name?.trim() || `Training session · ${new Date(session.date).toLocaleString()}`;
}
