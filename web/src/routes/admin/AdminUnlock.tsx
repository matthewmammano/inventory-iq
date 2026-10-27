import { Loading } from "@usefragments/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";

import {
  deleteApiV1AgenciesByAgencyIdAdminSessionMutation,
  getApiV1AgenciesByAgencyIdAdminSessionOptions,
  getApiV1AgenciesByAgencyIdAdminSessionQueryKey,
} from "../../api/@tanstack/react-query.gen";
import { Button } from "../../components/Button";
import { Keypad } from "../../components/Keypad";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { Panel } from "../../components/Panel";
import { Toast, type ToastMessage } from "../../components/Toast";
import { useSignedInAgency } from "../../hooks/useSignedInAgency";
import {
  ADMIN_PIN_LENGTH,
  ADMIN_PIN_SUBTITLE,
  ADMIN_PIN_TITLE,
  ADMIN_UNLOCKED_NOTE,
  ADMIN_UNLOCKED_TITLE,
  LOADING_ADMIN_LABEL,
  LOCK_ADMIN_LABEL,
  OPEN_ADMIN_LABEL,
  SCAN_PATH,
  SIGN_IN_PATH,
  TEMPORARY_PIN_CONFIRM_LABEL,
  TEMPORARY_PIN_CONFIRM_NOTE,
  TEMPORARY_PIN_CONFIRM_TITLE,
  TEMPORARY_PIN_FAILED_NOTE,
  TEMPORARY_PIN_LABEL,
  TEMPORARY_PIN_SENT_NOTE,
  UNLOCK_LABEL,
  UNLOCK_PENDING_LABEL,
  UNLOCK_UNREACHABLE_NOTE,
} from "../../constants";
import { adminPanelUrl } from "../../lib/urls";
import { requestAdminUnlock, requestTemporaryPin, type AdminSessionResult } from "./adminSessionRequests";

import "./AdminUnlock.css";

/** The admin door: the PIN screen while this browser is locked, the way through once it is not. */
export function AdminUnlock() {
  const navigate = useNavigate();
  const account = useSignedInAgency();
  const agencyId = account.data?.id;
  const session = useQuery({
    ...getApiV1AgenciesByAgencyIdAdminSessionOptions({ path: { agency_id: agencyId ?? 0 } }),
    enabled: agencyId !== undefined,
  });

  if (account.isError) return <Navigate to={SIGN_IN_PATH} replace />;

  const unlocked = session.data?.unlocked === true;
  const waiting = agencyId === undefined || session.isPending;

  return (
    <Page
      title={unlocked ? ADMIN_UNLOCKED_TITLE : ADMIN_PIN_TITLE}
      subtitle={unlocked ? undefined : ADMIN_PIN_SUBTITLE}
      logoUrl={account.data?.logo_url}
      onBack={() => navigate(SCAN_PATH)}
    >
      <Gate agencyId={agencyId} waiting={waiting} unlocked={unlocked} />
    </Page>
  );
}

type GateProps = { agencyId: number | undefined; waiting: boolean; unlocked: boolean };

function Gate({ agencyId, waiting, unlocked }: GateProps) {
  if (waiting || agencyId === undefined) return <Loading label={LOADING_ADMIN_LABEL} />;
  if (unlocked) return <UnlockedPanel agencyId={agencyId} />;
  return <PinEntry agencyId={agencyId} />;
}

/** Admin screens are still v1, so an unlocked browser is handed to them rather than kept here. */
function UnlockedPanel({ agencyId }: { agencyId: number }) {
  const queries = useQueryClient();
  const lock = useMutation({
    ...deleteApiV1AgenciesByAgencyIdAdminSessionMutation(),
    onSettled: () =>
      queries.invalidateQueries({
        queryKey: getApiV1AgenciesByAgencyIdAdminSessionQueryKey({ path: { agency_id: agencyId } }),
      }),
  });

  return (
    <div className="iq-unlock">
      <Panel>
        <p className="iq-unlock-status">{ADMIN_UNLOCKED_NOTE}</p>
        <div className="iq-unlock-actions">
          <Button onClick={() => window.location.assign(adminPanelUrl(agencyId))}>{OPEN_ADMIN_LABEL}</Button>
          <Button
            variant="quiet"
            disabled={lock.isPending}
            onClick={() => lock.mutate({ path: { agency_id: agencyId } })}
          >
            {LOCK_ADMIN_LABEL}
          </Button>
        </div>
      </Panel>
    </div>
  );
}

function PinEntry({ agencyId }: { agencyId: number }) {
  const [pin, setPin] = useState("");
  const [asking, setAsking] = useState(false);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const unlock = useMutation({
    mutationFn: requestAdminUnlock,
    onSuccess: (result) => {
      if (result.kind === "ok") {
        window.location.assign(adminPanelUrl(agencyId));
        return;
      }
      setPin("");
      setToast({ tone: "error", text: result.message });
    },
    onError: () => setToast({ tone: "error", text: UNLOCK_UNREACHABLE_NOTE }),
  });
  const temporaryPin = useMutation({
    mutationFn: requestTemporaryPin,
    onSuccess: (result) => setToast(sentToast(result)),
    onError: () => setToast({ tone: "error", text: TEMPORARY_PIN_FAILED_NOTE }),
  });

  const ready = pin.length === ADMIN_PIN_LENGTH && !unlock.isPending;
  const submit = () => {
    if (ready) unlock.mutate({ agencyId, pin });
  };
  const sendTemporaryPin = () => {
    setAsking(false);
    temporaryPin.mutate(agencyId);
  };

  return (
    <div className="iq-unlock">
      <Panel>
        <Keypad value={pin} length={ADMIN_PIN_LENGTH} onValueChange={setPin} onSubmit={submit} />
        <div className="iq-unlock-actions">
          <Button disabled={!ready} onClick={submit}>
            {unlock.isPending ? UNLOCK_PENDING_LABEL : UNLOCK_LABEL}
          </Button>
        </div>
      </Panel>
      <div className="iq-unlock-aside">
        <Button variant="quiet" size="small" disabled={temporaryPin.isPending} onClick={() => setAsking(true)}>
          {TEMPORARY_PIN_LABEL}
        </Button>
      </div>
      <Modal
        open={asking}
        onClose={() => setAsking(false)}
        title={TEMPORARY_PIN_CONFIRM_TITLE}
        description={TEMPORARY_PIN_CONFIRM_NOTE}
        confirmLabel={TEMPORARY_PIN_CONFIRM_LABEL}
        onConfirm={sendTemporaryPin}
      />
      <Toast message={toast} onHide={() => setToast(null)} />
    </div>
  );
}

/** The API words its own refusals, so only the sent case needs wording here. */
function sentToast(result: AdminSessionResult): ToastMessage {
  if (result.kind === "ok") return { tone: "success", text: TEMPORARY_PIN_SENT_NOTE };
  return { tone: "error", text: result.message };
}
