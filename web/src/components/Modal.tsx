import { Dialog } from "@usefragments/ui";
import type { ReactNode } from "react";

import { CANCEL_LABEL, CLOSE_LABEL } from "../constants";
import { Button } from "./Button";

import "./Modal.css";

type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  onConfirm?: () => void;
  children?: ReactNode;
};

/**
 * Fragments' dialog at kiosk size: a titled sheet, a body that scrolls on its own,
 * and a footer whose answers are the same button in two emphases.
 */
export function Modal({ open, onClose, title, description, confirmLabel, onConfirm, children }: ModalProps) {
  const changeOpen = (next: boolean) => {
    if (!next) onClose();
  };

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <Dialog.Content className="iq-modal" width="lg" initialFocus={false}>
        <Dialog.Header className="iq-modal-header">
          <Dialog.Title className="iq-modal-title">{title}</Dialog.Title>
          {description !== undefined ? (
            <Dialog.Description className="iq-modal-note">{description}</Dialog.Description>
          ) : null}
        </Dialog.Header>
        {children === undefined ? null : <Dialog.Body className="iq-modal-body">{children}</Dialog.Body>}
        <Dialog.Footer className="iq-modal-footer">
          <Dialog.Close
            render={
              <Button variant="quiet" size="small" onClick={onClose}>
                {onConfirm ? CANCEL_LABEL : CLOSE_LABEL}
              </Button>
            }
          />
          {onConfirm && confirmLabel ? (
            <Button size="small" onClick={onConfirm}>
              {confirmLabel}
            </Button>
          ) : null}
        </Dialog.Footer>
      </Dialog.Content>
    </Dialog>
  );
}
