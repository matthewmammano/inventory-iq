import { useEffect, useRef } from "react";

import { SCANNER_IDLE_MS, UPC_LENGTH } from "../constants";

const isDigit = (key: string) => key.length === 1 && key >= "0" && key <= "9";

const isFormField = (target: EventTarget | null) =>
  target instanceof Element && target.matches("input, select, textarea");

/**
 * Reads a hardware scanner's keystroke burst while no field has focus.
 * A field that already has focus reads the barcode itself.
 */
export function useBarcodeScanner(onBarcode: (upc: string) => void): void {
  const handler = useRef(onBarcode);

  useEffect(() => {
    handler.current = onBarcode;
  }, [onBarcode]);

  useEffect(() => {
    let buffer = "";
    let idleTimer: number | undefined;

    const flush = () => {
      if (buffer.length === UPC_LENGTH) handler.current(buffer);
      buffer = "";
    };

    const onPaste = (event: ClipboardEvent) => {
      const pasted = event.clipboardData?.getData("text")?.trim() ?? "";
      if (pasted.length === UPC_LENGTH && [...pasted].every(isDigit)) handler.current(pasted);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (isFormField(event.target)) return;
      window.clearTimeout(idleTimer);
      if (event.key === "Enter") {
        if (buffer.length === UPC_LENGTH) event.preventDefault();
        flush();
        return;
      }
      if (!isDigit(event.key)) {
        buffer = "";
        return;
      }
      buffer = (buffer + event.key).slice(-UPC_LENGTH);
      idleTimer = window.setTimeout(flush, SCANNER_IDLE_MS);
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
