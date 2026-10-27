import { useEffect, useState } from "react";

export type ScanStatusState = "ready" | "loading" | "offline" | "failed";

/** What the item query knows about itself, the only app-side condition scanning depends on. */
type ItemsState = {
  failed: boolean;
  loading: boolean;
};

/** Live scan readiness, from the browser's own connectivity plus the item query's state. */
export function useScanStatus({ failed, loading }: ItemsState): ScanStatusState {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  if (!online) return "offline";
  if (failed) return "failed";
  if (loading) return "loading";
  return "ready";
}
