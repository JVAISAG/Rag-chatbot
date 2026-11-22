"use client";

import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import { Brand } from "./brand";

type Props = { onSignedIn: () => void; notice?: string };

export function AuthScreen({ onSignedIn, notice }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(notice ?? "");
  const [busy, setBusy] = useState(false);

  function selectMode(next: "login" | "register") {
    setMode(next);
    setPassword("");
    setError("");
    setSuccess("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    const cleanUsername = username.trim();
    const cleanEmail = email.trim();
    if (mode === "register" && !cleanUsername && !cleanEmail) {
      setError("Add a username, an email address, or both.");
      return;
    }
    if (mode === "register" && (Array.from(password).length < 8 || Array.from(password).length > 128)) {
      setError("Password must be 8–128 characters long.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await api.login(identifier.trim(), password);
        setPassword("");
        onSignedIn();
      } else {
        await api.register({
          ...(cleanUsername ? { username: cleanUsername } : {}),
          ...(cleanEmail ? { email: cleanEmail } : {}),
          password,
        });
        setIdentifier(cleanUsername || cleanEmail);
        setPassword("");
        setMode("login");
        setSuccess("Your account is ready. Sign in to continue.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <header className="auth-header"><Brand /><span className="header-caption">A HOME FOR YOUR RESEARCH</span></header>
      <main className="auth-layout">
        <section className="auth-intro" aria-labelledby="intro-title">
          <div className="eyebrow"><span className="eyebrow-dot" /> YOUR RESEARCH, IN ONE PLACE</div>
          <h1 id="intro-title">Make space<br />for <em>better thinking.</em></h1>
          <p>Gather the ideas worth returning to, and give your research a place to grow.</p>
          <div className="intro-note"><span className="note-line" /> A quieter way to stay curious.</div>
          <div className="paper-stack" aria-hidden="true">
            <div className="paper paper-back"><span /><span /><span /></div>
            <div className="paper paper-front"><div className="paper-label">RESEARCH NOTES <b>01</b></div><div className="paper-heading" /><div className="paper-heading short" /><div className="paper-rule" /><div className="paper-line" /><div className="paper-line" /><div className="paper-line short" /><div className="paper-stamp">✳</div></div>
          </div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <div className="card-topline"><span>YOUR WORKSPACE</span><span className="tiny-star" aria-hidden="true">✳</span></div>
          <h2 id="auth-title">{mode === "login" ? "Welcome back." : "Start your workspace."}</h2>
          <p className="card-subtitle">{mode === "login" ? "Sign in to return to your collections." : "Create an account for your private research."}</p>
          <div className="auth-tabs" role="tablist" aria-label="Account access">
            <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => selectMode("login")}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === "register"} onClick={() => selectMode("register")}>Create account</button>
          </div>
          <form onSubmit={submit} className="auth-form">
            {mode === "login" ? (
              <div className="field">
                <label htmlFor="identifier">Email or username</label>
                <input id="identifier" name="identifier" autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder="you@example.com" required />
              </div>
            ) : (
              <>
                <p className="field-hint first-hint">Add an email address, a username, or both.</p>
                <div className="field">
                  <label htmlFor="username">Username <span>optional</span></label>
                  <input id="username" name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="your.name" />
                  <p className="field-hint">3–32 letters, numbers, dots, underscores, or hyphens.</p>
                </div>
                <div className="field">
                  <label htmlFor="email">Email address <span>optional</span></label>
                  <input id="email" name="email" type="text" inputMode="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
                </div>
              </>
            )}
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required />
              {mode === "register" && <p className="field-hint">8–128 characters. Spaces and Unicode are welcome.</p>}
            </div>
            {error && <p className="form-message error-message" role="alert">{error}</p>}
            {success && <p className="form-message success-message" role="status">{success}</p>}
            <button className="primary-button full-width" disabled={busy} type="submit">
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}<span aria-hidden="true">↗</span>
            </button>
          </form>
          <div className="auth-footnote"><span className="lock-icon" aria-hidden="true">◇</span> Your collections are private to your account.</div>
        </section>
      </main>
      <footer className="auth-footer"><span>RESEARCH WORKSPACE</span><span>COLLECT THOUGHTFULLY. THINK CLEARLY.</span></footer>
    </div>
  );
}
