"use client";

import { useEffect, useState } from "react";
import { AuthScreen } from "../components/auth-screen";
import { Brand } from "../components/brand";
import { Workspace } from "../components/workspace";
import { api, ApiError } from "../lib/api";

type Status = "checking" | "signed-out" | "signed-in" | "unavailable";

export default function Home() {
  const [status, setStatus] = useState<Status>("checking");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    api.me().then(() => {
      if (active) setStatus("signed-in");
    }).catch((error: unknown) => {
      if (active) setStatus(error instanceof ApiError && error.status === 401 ? "signed-out" : "unavailable");
    });
    return () => { active = false; };
  }, [attempt]);

  if (status === "checking" || status === "unavailable") {
    return (
      <main className="startup-page">
        <Brand />
        <section className="startup-card" aria-live="polite">
          {status === "checking" ? <p>Opening your workspace…</p> : <>
            <h1>We couldn’t open your workspace.</h1>
            <p>Check that the workspace API is running, then try again.</p>
            <button className="primary-button" onClick={() => { setStatus("checking"); setAttempt((value) => value + 1); }}>Try again</button>
          </>}
        </section>
      </main>
    );
  }
  if (status === "signed-out") {
    return <AuthScreen notice={notice} onSignedIn={() => { setNotice(""); setStatus("signed-in"); }} />;
  }
  return <Workspace onSignedOut={(expired) => {
    setNotice(expired ? "Your session has expired. Please sign in again." : "");
    setStatus("signed-out");
  }} />;
}
