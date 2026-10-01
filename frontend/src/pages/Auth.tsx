import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError, errorMessage } from "../lib/api";
import { loginWithPassword, type TokenResponse, useAuth } from "../stores/auth";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function Shell({ subtitle, children }: { subtitle: string; children: React.ReactNode }) {
  return (
    <div className="min-h-full flex items-center justify-center p-4 bg-bg">
      <div className="w-full max-w-sm panel">
        <div className="px-5 pt-5 pb-3 border-b border-line">
          <div className="text-head font-bold tracking-[0.2em] text-sm">WILDFIRETWIN</div>
          <div className="text-2xs text-dim tracking-[0.16em] mt-1 uppercase">{subtitle}</div>
        </div>
        <div className="p-5">{children}</div>
        <div className="px-5 pb-4 text-2xs text-dim leading-relaxed">Decision-support research prototype. Not an emergency warning system.</div>
      </div>
    </div>
  );
}

function Message({ kind, text }: { kind: "error" | "ok"; text: string }) {
  return <p role={kind === "error" ? "alert" : "status"} className={`text-xs m-0 mb-3 ${kind === "error" ? "text-crit" : "text-ok"}`}>{text}</p>;
}

declare global {
  interface Window { google?: { accounts: { id: { initialize: (o: object) => void; renderButton: (el: HTMLElement, o: object) => void } } } }
}

function GoogleButton({ onToken }: { onToken: (r: TokenResponse) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "unconfigured" | "error">("loading");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<{ configured: boolean; client_id: string | null }>("/api/auth/google/config")
      .then((cfg) => {
        if (!cfg.configured || !cfg.client_id) return setState("unconfigured");
        const s = document.createElement("script");
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true;
        s.onload = () => {
          window.google?.accounts.id.initialize({
            client_id: cfg.client_id,
            callback: async (resp: { credential: string }) => {
              try {
                onToken(await api<TokenResponse>("/api/auth/google", { method: "POST", json: { credential: resp.credential } }));
              } catch (e) {
                setErr(errorMessage(e));
              }
            },
          });
          if (ref.current) window.google?.accounts.id.renderButton(ref.current, { theme: "filled_black", size: "large", width: 300, text: "continue_with" });
          setState("ready");
        };
        s.onerror = () => setState("error");
        document.head.appendChild(s);
      })
      .catch(() => setState("error"));
  }, [onToken]);
  return (
    <div>
      {state === "unconfigured" && (
        <button className="btn w-full" disabled title="Server has no GOOGLE_CLIENT_ID configured">[ Continue with Google ] — not configured</button>
      )}
      {state === "error" && <p className="text-2xs text-warn m-0">Google Sign-In unavailable.</p>}
      <div ref={ref} className={state === "ready" ? "flex justify-center" : "hidden"} />
      {err && <Message kind="error" text={err} />}
    </div>
  );
}

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next") || "/";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!EMAIL_RE.test(email.trim())) return setError("Invalid email address.");
    setBusy(true);
    try {
      await loginWithPassword(email.trim(), password);
      navigate(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell subtitle="Secure Access">
      <form onSubmit={submit} noValidate>
        {params.get("signup") === "ok" && <Message kind="ok" text="Signup successful." />}
        {error && <Message kind="error" text={error} />}
        <label className="label" htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" className="input mb-3" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label className="label" htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" className="input mb-4" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "[ Sign in ]"}</button>
      </form>
      <div className="my-4 text-center text-2xs text-dim">— OR —</div>
      <GoogleButton onToken={(r) => { setSession(r.access_token, r.expires_in, r.user); navigate(next); }} />
      <p className="text-xs text-dim mt-4 mb-0">No account? <Link to="/signup" className="text-fire">Create one</Link> · <Link to="/" className="text-dim underline">Continue to map</Link></p>
    </Shell>
  );
}

export function SignupPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!EMAIL_RE.test(email.trim())) return setError("Invalid email address.");
    if (password !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      const r = await api<{ email: string; expires_in: number; resend_in: number }>("/api/auth/signup", {
        method: "POST", json: { email: email.trim(), password, confirm_password: confirm } });
      navigate(`/verify?email=${encodeURIComponent(r.email)}&ttl=${r.expires_in}&resend=${r.resend_in}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell subtitle="Create Account">
      <form onSubmit={submit} noValidate>
        {error && <Message kind="error" text={error} />}
        <label className="label" htmlFor="su-email">Email</label>
        <input id="su-email" type="email" autoComplete="email" className="input mb-3" value={email} onChange={(e) => setEmail(e.target.value)} />
        <label className="label" htmlFor="su-pw">Password (min 8, letters + numbers/symbols)</label>
        <input id="su-pw" type="password" autoComplete="new-password" className="input mb-3" value={password} onChange={(e) => setPassword(e.target.value)} />
        <label className="label" htmlFor="su-pw2">Confirm password</label>
        <input id="su-pw2" type="password" autoComplete="new-password" className="input mb-4" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Sending code…" : "[ Sign up ]"}</button>
      </form>
      <p className="text-xs text-dim mt-4 mb-0">Have an account? <Link to="/login" className="text-fire">Sign in</Link></p>
    </Shell>
  );
}

function mmss(s: number) {
  const v = Math.max(0, Math.floor(s));
  return `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`;
}

export function VerifyOtpPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const email = params.get("email") ?? "";
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState(() => Date.now() + Number(params.get("ttl") ?? 300) * 1000);
  const [resendAt, setResendAt] = useState(() => Date.now() + Number(params.get("resend") ?? 60) * 1000);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!/^\d{6}$/.test(code)) return setError("Enter the 6-digit code.");
    setBusy(true);
    try {
      const r = await api<TokenResponse>("/api/auth/verify-otp", { method: "POST", json: { email, code } });
      setSession(r.access_token, r.expires_in, r.user);
      setInfo(r.message ?? "Signup successful.");
      setTimeout(() => navigate("/"), 900);
    } catch (err) {
      const left = err instanceof ApiError ? (err.details as { attempts_left?: number } | undefined)?.attempts_left : undefined;
      setError(errorMessage(err) + (left !== undefined ? ` (${left} attempts left)` : ""));
    } finally {
      setBusy(false);
    }
  };
  const resend = async () => {
    setError(null);
    try {
      const r = await api<{ expires_in: number; resend_in: number; message: string }>("/api/auth/resend-otp", { method: "POST", json: { email } });
      setExpiresAt(Date.now() + r.expires_in * 1000);
      setResendAt(Date.now() + r.resend_in * 1000);
      setInfo(r.message);
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const left = (expiresAt - now) / 1000;
  const resendLeft = (resendAt - now) / 1000;
  return (
    <Shell subtitle="Verify Email">
      <form onSubmit={verify} noValidate>
        {error && <Message kind="error" text={error} />}
        {info && <Message kind="ok" text={info} />}
        <p className="text-xs text-dim mt-0">Code sent to <span className="text-ink">{email}</span></p>
        <label className="label" htmlFor="otp">6-digit code</label>
        <input id="otp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
               onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
               className="input mb-3 text-center tracking-[0.8em] text-base h-10" placeholder="______" />
        <div className="text-xs mb-4">Expires in: <span className={left <= 30 ? "text-warn" : "text-head"}>{left > 0 ? mmss(left) : "expired"}</span></div>
        <button className="btn-primary w-full" disabled={busy || left <= 0}>{busy ? "Verifying…" : "[ Verify ]"}</button>
      </form>
      <button className="btn w-full mt-2" onClick={resend} disabled={resendLeft > 0}>
        [ Resend code ]{resendLeft > 0 ? ` ${mmss(resendLeft)}` : ""}
      </button>
    </Shell>
  );
}
