import { Input } from "@usefragments/ui";
import { useEffect, useRef } from "react";

import { SEARCH_PLACEHOLDER } from "../constants";

import "./ScanField.css";

type ScanFieldProps = {
  value: string;
  onValueChange: (value: string) => void;
  count?: string;
};

/**
 * The search and scan field. It takes focus on a pointer device so a scanner
 * burst lands in it, and leaves focus alone on a touchscreen so no keyboard pops up.
 */
export function ScanField({ value, onValueChange, count }: ScanFieldProps) {
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;
    field.current?.focus();
  }, []);

  return (
    <div className="iq-scan-field">
      <Input
        ref={field}
        id="item-search"
        type="search"
        size="lg"
        value={value}
        onValueChange={onValueChange}
        placeholder={SEARCH_PLACEHOLDER}
        autoComplete="off"
        count={count}
      />
    </div>
  );
}
