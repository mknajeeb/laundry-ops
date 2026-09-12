/**
 * Session-scoped FoldingUserSelect options cache.
 * Avoids re-fetching listFoldingUsers on every Review bag expand.
 */

import { listFoldingUsers } from "../../api";

let cachedOptions = null;
let inflight = null;

export function clearFoldingUserOptionsCache() {
  cachedOptions = null;
  inflight = null;
}

export async function getFoldingUserOptions() {
  if (cachedOptions) return cachedOptions;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await listFoldingUsers();
      const opts = res.data?.user_options || [];
      const names = opts.length
        ? opts
        : (res.data?.users || []).map((u) => ({ user_name: u, label: u }));
      cachedOptions = names;
      return names;
    } catch {
      return [];
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}
