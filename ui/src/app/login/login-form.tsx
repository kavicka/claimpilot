"use client";

import { Alert, Button, TextField } from "@claimpilot/ui";
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Wrong username or password." : errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full max-w-[340px] animate-rise flex-col gap-20">
      <div className="flex justify-center">
        <Brand />
      </div>
      {/* POST, so a submit before the page has loaded its script never puts the password in the URL */}
      <form method="post" onSubmit={submit} className="cp-floating flex flex-col gap-14 p-20">
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
        {error ? (
          <Alert tone="danger" className="items-start">
            {error}
          </Alert>
        ) : null}
        <Button type="submit" variant="primary" block loading={busy}>
          {busy ? "Logging in" : "Log in"}
        </Button>
      </form>
    </div>
  );
}
