import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-desk px-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
