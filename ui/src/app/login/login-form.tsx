"use client";

import { Alert, Button, Reveal, TextField, useReplay } from "@claimpilot/ui";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Brand } from "@/components/shell/sidebar";
import { ApiError, api, errorMessage } from "@/lib/api";

function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // A refused login shakes the form once, next to the message that says why.
  const [refused, setRefused] = useState(0);
  const shake = useReplay(refused);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      setDone(true);
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Wrong username or password." : errorMessage(err));
      setRefused((n) => n + 1);
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full max-w-[21.25rem] animate-rise flex-col gap-20">
      <div className="flex justify-center">
        <Brand />
      </div>
      {/* POST, so a submit before the page has loaded its script never puts the password in the URL */}
      <form method="post" onSubmit={submit} className="cp-floating flex flex-col gap-14 p-20" data-shake={shake}>
        <div className="flex flex-col gap-4">
          <h1 className="cp-text-panel-title text-ink">Log in</h1>
          <p className="cp-text-label-regular text-ink-subtle">Use your handler account.</p>
        </div>
        <TextField
          label="Username"
          id="username"
          name="username"
          autoComplete="username"
          autoFocus
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <TextField
          label="Password"
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {/* Closed, the reveal still takes a flex gap; the negative margin cancels it and the alert's margin gives it back when open. */}
        <Reveal open={error !== null} className="-my-7">
          {error ? (
            <Alert tone="danger" className="my-7 items-start">
              {error}
            </Alert>
          ) : null}
        </Reveal>
        <Button type="submit" variant="primary" block loading={busy && !done} done={done}>
          {done ? "Logged in" : busy ? "Logging in" : "Log in"}
        </Button>
      </form>
    </div>
  );
}
