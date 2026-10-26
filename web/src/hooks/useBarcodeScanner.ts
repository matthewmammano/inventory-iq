import { useEffect, useRef } from "react";

import { SCANNER_BURST_GAP_MS, SCANNER_MIN_DIGITS } from "../constants";

const DIGITS_ONLY = /^\d+$/;

const isDigit = (key: string) => key.length === 1 && key >= "0" && key <= "9";

/**
 * Reads a hardware scanner's keystroke burst wherever focus happens to sit, search field included.
 * Only digits arriving faster than a person can type count as a scan, so typed text stays search text.
 */
export function useBarcodeScanner(onBarcode: (upc: string) => void): void {
  const handler = useRef(onBarcode);

  useEffect(() => {
    handler.current = onBarcode;
  }, [onBarcode]);

  useEffect(() => {
    let buffer = "";
    let lastKeyAt = 0;
    let idleTimer: number | undefined;

    const flush = () => {
      const scanned = buffer;
      buffer = "";
      if (scanned.length >= SCANNER_MIN_DIGITS) handler.current(scanned);
    };

    const onPaste = (event: ClipboardEvent) => {
      const pasted = event.clipboardData?.getData("text")?.trim() ?? "";
      if (pasted.length >= SCANNER_MIN_DIGITS && DIGITS_ONLY.test(pasted)) handler.current(pasted);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      window.clearTimeout(idleTimer);
      if (event.key === "Enter") {
        if (buffer.length >= SCANNER_MIN_DIGITS) event.preventDefault();
        flush();
        return;
      }
      if (!isDigit(event.key)) {
        buffer = "";
        return;
      }
      const now = Date.now();
      buffer = now - lastKeyAt <= SCANNER_BURST_GAP_MS ? buffer + event.key : event.key;
      lastKeyAt = now;
      idleTimer = window.setTimeout(flush, SCANNER_BURST_GAP_MS);
    };

    document.addEventListener("paste", onPaste);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(idleTimer);
      document.removeEventListener("paste", onPaste);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);
}
