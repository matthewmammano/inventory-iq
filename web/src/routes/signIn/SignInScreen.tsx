import { Loading } from "@usefragments/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { deleteApiV1SessionMutation, getApiV1MeQueryKey } from "../../api/@tanstack/react-query.gen";
import type { SignedInAgencyResponse } from "../../api/types.gen";
import { Button } from "../../components/Button";
import { Page } from "../../components/Page";
import { Panel } from "../../components/Panel";
import { useSignedInAgency } from "../../hooks/useSignedInAgency";
import { TextField } from "../../components/TextField";
import { Toast, type ToastMessage } from "../../components/Toast";
import {
  CONTINUE_TO_SCAN_LABEL,
  EMAIL_LABEL,
  LOADING_ACCOUNT_LABEL,
  PASSWORD_LABEL,
  SCAN_PATH,
  SET_PASSWORD_LABEL,
  SIGN_IN_LABEL,
  SIGN_IN_PENDING_LABEL,
  SIGN_IN_SUBTITLE,
  SIGN_IN_TITLE,
  SIGN_IN_UNREACHABLE_NOTE,
  SIGN_OUT_LABEL,
  signedInAsNote,
} from "../../constants";
import { forgotPasswordUrl } from "../../lib/urls";
import { requestSignIn } from "./signInRequest";

import "./SignInScreen.css";

/** The account sign-in: the one screen reachable without a session. */
export function SignInScreen() {
  const account = useSignedInAgency();

  return (
    <Page title={SIGN_IN_TITLE} subtitle={SIGN_IN_SUBTITLE} width="reading" logoUrl={account.data?.logo_url}>
      <div className="iq-sign-in">
        <Body signedIn={account.data} loading={account.isPending} />
      </div>
    </Page>
  );
}

function Body({ signedIn, loading }: { signedIn: SignedInAgencyResponse | undefined; loading: boolean }) {
  if (loading) return <Loading label={LOADING_ACCOUNT_LABEL} />;
  if (signedIn !== undefined) return <SignedInPanel agency={signedIn} />;
  return <SignInForm />;
}

/** A kiosk stays signed in for months, so the screen says whose account it holds before anyone retypes one. */
function SignedInPanel({ agency }: { agency: SignedInAgencyResponse }) {
  const navigate = useNavigate();
  const queries = useQueryClient();
  const signOut = useMutation({
    ...deleteApiV1SessionMutation(),
    onSuccess: () => queries.resetQueries(),
  });

  return (
    <Panel>
      <p className="iq-sign-in-current">{signedInAsNote(agency.display_name)}</p>
      <div className="iq-sign-in-actions">
        <Button onClick={() => navigate(SCAN_PATH)}>{CONTINUE_TO_SCAN_LABEL}</Button>
        <Button variant="quiet" disabled={signOut.isPending} onClick={() => signOut.mutate({})}>
          {SIGN_OUT_LABEL}
        </Button>
      </div>
    </Panel>
  );
}

function SignInForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const navigate = useNavigate();
  const queries = useQueryClient();
  const signIn = useMutation({
    mutationFn: requestSignIn,
    onSuccess: (result) => {
      if (result.kind !== "signedIn") {
        setToast({ tone: "error", text: result.message });
        return;
      }
      queries.setQueryData(getApiV1MeQueryKey(), result.agency);
      navigate(SCAN_PATH);
    },
    onError: () => setToast({ tone: "error", text: SIGN_IN_UNREACHABLE_NOTE }),
  });

  const ready = email !== "" && password !== "" && !signIn.isPending;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) signIn.mutate({ email, password });
  };
  return (
    <form className="iq-sign-in-form" onSubmit={submit}>
      <Panel>
        <TextField
          id="sign-in-email"
          label={EMAIL_LABEL}
          type="email"
          value={email}
          autoComplete="username"
          onValueChange={setEmail}
        />
        <TextField
          id="sign-in-password"
          label={PASSWORD_LABEL}
          type="password"
          value={password}
          autoComplete="current-password"
          onValueChange={setPassword}
        />
        <div className="iq-sign-in-actions">
          <Button type="submit" disabled={!ready}>
            {signIn.isPending ? SIGN_IN_PENDING_LABEL : SIGN_IN_LABEL}
          </Button>
        </div>
      </Panel>
      {signIn.data?.kind === "passwordNotSet" ? (
        <div className="iq-sign-in-actions">
          <Button variant="quiet" onClick={() => window.location.assign(forgotPasswordUrl(email))}>
            {SET_PASSWORD_LABEL}
          </Button>
        </div>
      ) : null}
      <Toast message={toast} onHide={() => setToast(null)} />
    </form>
  );
}
