/**
 * Visitor token persistence. localStorage can throw (privacy mode, blocked
 * storage); in that case the visitor simply gets a fresh identity per page load.
 */
export function storageKey(workspaceId: string): string {
  return `resolveai:${workspaceId}:visitor`;
}

export function loadVisitorToken(workspaceId: string): string | null {
  try {
    return window.localStorage.getItem(storageKey(workspaceId));
  } catch {
    return null;
  }
}

export function saveVisitorToken(workspaceId: string, token: string): void {
  try {
    window.localStorage.setItem(storageKey(workspaceId), token);
  } catch {
    // ignore: storage unavailable
  }
}

export function clearVisitorToken(workspaceId: string): void {
  try {
    window.localStorage.removeItem(storageKey(workspaceId));
  } catch {
    // ignore
  }
}
