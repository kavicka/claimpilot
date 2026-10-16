import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-surface-sidebar px-16">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
