import Link from "next/link";

import { Logo } from "@/components/brand";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="relative flex min-h-screen flex-col bg-muted/40">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-gradient-to-b from-primary/10 to-transparent"
      />
      <header className="relative px-6 py-5">
        <Logo />
      </header>
      <main className="relative flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:pt-12">
        <div className="w-full max-w-md">{children}</div>
      </main>
      <footer className="relative px-6 py-6 text-center text-xs text-muted-foreground">
        © 2026 ResolveAI ·{" "}
        <Link href="/" className="hover:text-foreground">
          Home
        </Link>
      </footer>
    </div>
  );
}
