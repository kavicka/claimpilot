"use client";

import { LoaderCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Brand } from "@/components/shell/sidebar";
import { Button } from "@/components/ui/button";
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
    <div className="w-full max-w-[360px] animate-rise">
      <Brand className="mb-6 justify-center" />
      {/* POST, so a submit before the page has loaded its script never puts the password in the URL */}
      <form
        method="post"
        onSubmit={submit}
        className="rounded-2xl border border-line bg-sheet p-6 shadow-[0_1px_2px_rgb(0_0_0/0.04),0_12px_32px_rgb(0_0_0/0.06)]"
      >
        <h1 className="text-lg font-semibold tracking-tight">Log in</h1>
        <p className="mt-1 text-sm text-ink-2">Use your handler account.</p>

        <label className="mt-5 block text-[13px] font-medium" htmlFor="username">
          Username
        </label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          autoFocus
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="mt-1.5 h-10 w-full rounded-lg border border-line-2 bg-white px-3 text-sm outline-none transition focus:border-ink focus:ring-2 focus:ring-ink/10"
        />

        <label className="mt-4 block text-[13px] font-medium" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1.5 h-10 w-full rounded-lg border border-line-2 bg-white px-3 text-sm outline-none transition focus:border-ink focus:ring-2 focus:ring-ink/10"
        />

        {error ? (
          <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" className="mt-5 h-10 w-full" disabled={busy}>
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
          {busy ? "Logging in" : "Log in"}
        </Button>
      </form>
    </div>
  );
}
