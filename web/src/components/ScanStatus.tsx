import type { ScanStatusState } from "../hooks/useScanStatus";
import { SCAN_STATUS_FAILED, SCAN_STATUS_LOADING, SCAN_STATUS_OFFLINE, SCAN_STATUS_READY } from "../constants";

import "./ScanStatus.css";

const STATUS_TEXT: Record<ScanStatusState, string> = {
  ready: SCAN_STATUS_READY,
  loading: SCAN_STATUS_LOADING,
  offline: SCAN_STATUS_OFFLINE,
  failed: SCAN_STATUS_FAILED,
};

/** The live line above the field: a lamp and three or four words. */
export function ScanStatus({ state }: { state: ScanStatusState }) {
  return (
    <p className={`iq-scan-status iq-scan-status-${state}`} role="status" aria-live="polite">
      <span className="iq-scan-lamp" />
      {STATUS_TEXT[state]}
    </p>
  );
}
