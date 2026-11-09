"use client";

import { useMutation } from "@tanstack/react-query";
import {
  BarChart3,
  Bot,
  BookOpen,
  Check,
  ChevronsUpDown,
  Contact,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  Plug,
  Settings,
  Users,
  Workflow,
  CreditCard,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { AppProvider, useApp } from "@/components/app/app-context";
import { RealtimeProvider } from "@/components/app/realtime";
import { LogoMark } from "@/components/brand";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useConversationCounts } from "@/lib/inbox-queries";
import { useLogout } from "@/lib/queries";
import { WORKSPACE_ROLE_LABELS } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Modules on the roadmap are listed (disabled) so the product shape is visible. */
  soon?: boolean;
  countKey?: "inbox";
}

const PRIMARY_NAV: NavItem[] = [
  { href: "/app", label: "Dashboard", icon: LayoutDashboard },
  { href: "/app/inbox", label: "Inbox", icon: Inbox, countKey: "inbox" },
  { href: "/app/customers", label: "Customers", icon: Contact },
  { href: "/app/ai-agents", label: "AI Agents", icon: Bot },
  { href: "/app/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/app/automation", label: "Automation", icon: Workflow },
  { href: "/app/analytics", label: "Analytics", icon: BarChart3 },
];

const SECONDARY_NAV: NavItem[] = [
  { href: "/app/team", label: "Team", icon: Users },
  { href: "/app/integrations", label: "Integrations", icon: Plug },
  { href: "/app/billing", label: "Billing", icon: CreditCard },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

export function initials(nameOrEmail: string): string {
  const parts = nameOrEmail.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { workspace, canWorkspace } = useApp();
  const counts = useConversationCounts(workspace?.id, canWorkspace("conversations.view"));
  const renderItem = (item: NavItem) => {
    const active = item.href === "/app" ? pathname === "/app" : pathname.startsWith(item.href);
    const Icon = item.icon;
    if (item.soon) {
      return (
        <li key={item.href}>
          <span
            aria-disabled
            className="flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground/60"
          >
            <Icon className="size-4" />
            {item.label}
            <span className="ml-auto text-[10px] font-medium tracking-wide uppercase">Soon</span>
          </span>
        </li>
      );
    }
    return (
      <li key={item.href}>
        <Link
          href={item.href}
          onClick={onNavigate}
          aria-current={active ? "page" : undefined}
          className={cn(
            "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
            active
              ? "bg-sidebar-accent text-sidebar-accent-foreground"
              : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
          )}
        >
          <Icon className={cn("size-4", active && "text-primary")} />
          {item.label}
          {item.countKey === "inbox" && counts.data && counts.data.mine + counts.data.unassigned > 0 ? (
            <span
              className="ml-auto rounded-full bg-primary/10 px-1.5 text-[11px] font-semibold text-primary tabular-nums"
              title="Assigned to you + unassigned"
            >
              {counts.data.mine + counts.data.unassigned}
            </span>
          ) : null}
        </Link>
      </li>
    );
  };
  return (
    <nav className="flex flex-1 flex-col gap-6" aria-label="Main">
      <ul className="grid gap-0.5">{PRIMARY_NAV.map(renderItem)}</ul>
      <ul className="mt-auto grid gap-0.5">{SECONDARY_NAV.map(renderItem)}</ul>
    </nav>
  );
}

function WorkspaceSwitcher() {
  const { me, workspace, setWorkspaceId } = useApp();
  const orgName = (id: string) => me.organizations.find((o) => o.id === id)?.name ?? "";
  const byOrg = me.organizations
    .map((org) => ({ org, workspaces: me.workspaces.filter((w) => w.organization_id === org.id) }))
    .filter((g) => g.workspaces.length > 0);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            className="flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors hover:bg-sidebar-accent/70"
          />
        }
      >
        <LogoMark className="size-8 shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{workspace?.name ?? "No workspace"}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {workspace ? orgName(workspace.organization_id) : me.user.email}
          </span>
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        {byOrg.map(({ org, workspaces }, index) => (
          <DropdownMenuGroup key={org.id}>
            {index > 0 ? <DropdownMenuSeparator /> : null}
            <DropdownMenuLabel>{org.name}</DropdownMenuLabel>
            {workspaces.map((ws) => (
              <DropdownMenuItem key={ws.id} onClick={() => setWorkspaceId(ws.id)}>
                <span className="flex-1 truncate">{ws.name}</span>
                {ws.id === workspace?.id ? <Check className="text-primary" /> : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { me, workspace } = useApp();
  const router = useRouter();
  const logout = useLogout();
  const signOut = () =>
    logout.mutate(undefined, {
      onSettled: () => router.replace("/login"),
    });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" className="h-9 gap-2 px-1.5" aria-label="Account menu" />}
      >
        <Avatar className="size-7">
          <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
            {initials(me.user.full_name || me.user.email)}
          </AvatarFallback>
        </Avatar>
        <span className="hidden max-w-40 truncate text-sm font-medium sm:block">
          {me.user.full_name || me.user.email}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <span className="block truncate text-sm font-medium text-foreground">{me.user.full_name}</span>
            <span className="block truncate">{me.user.email}</span>
            {workspace ? (
              <span className="mt-1 block">{WORKSPACE_ROLE_LABELS[workspace.role]} in {workspace.name}</span>
            ) : null}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/app/settings")}>
          <Settings /> Settings
        </DropdownMenuItem>
        <DropdownMenuItem onClick={signOut} disabled={logout.isPending}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function VerifyEmailBanner() {
  const { me } = useApp();
  const resend = useMutation({
    mutationFn: () => api.post("auth/verify-email/resend"),
    onSuccess: () => toast.success(`Verification link sent to ${me.user.email}`),
    onError: (error) => toast.error(error.message),
  });
  if (me.user.email_verified) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
      <span>Please verify your email address ({me.user.email}).</span>
      <button
        type="button"
        className="font-medium underline underline-offset-4 disabled:opacity-60"
        onClick={() => resend.mutate()}
        disabled={resend.isPending || resend.isSuccess}
      >
        {resend.isSuccess ? "Link sent" : "Resend link"}
      </button>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-5 px-3 py-3">
      <WorkspaceSwitcher />
      <NavLinks onNavigate={onNavigate} />
    </div>
  );
}

function NoWorkspace() {
  const { me } = useApp();
  return (
    <div className="mx-auto max-w-md py-24 text-center">
      <h1 className="text-lg font-semibold">No workspace access yet</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {me.organizations.length > 0
          ? "You're a member of an organization but haven't been added to any of its workspaces. Ask an admin to add you."
          : "You aren't a member of any organization. Ask your admin to send you an invitation."}
      </p>
      <Badge variant="secondary" className="mt-4">
        {me.user.email}
      </Badge>
    </div>
  );
}

function ShellFrame({ children }: { children: ReactNode }) {
  const { workspace, me, canWorkspace } = useApp();
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const fullBleed = pathname.startsWith("/app/inbox");
  const content = !workspace ? (
    <NoWorkspace />
  ) : canWorkspace("conversations.view") ? (
    <RealtimeProvider key={workspace.id} workspaceId={workspace.id} currentUserId={me.user.id}>
      {children}
    </RealtimeProvider>
  ) : (
    children
  );
  return (
    <div className="flex min-h-screen bg-background">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r bg-sidebar md:block">
        <Sidebar />
      </aside>
      <div className={cn("flex min-w-0 flex-1 flex-col", fullBleed && "h-screen")}>
        <VerifyEmailBanner />
        <header className="sticky top-0 z-10 flex h-14 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger render={<Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu" />}>
              <Menu />
            </SheetTrigger>
            <SheetContent side="left" className="w-64 bg-sidebar p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>
          <div className="ml-auto">
            <UserMenu />
          </div>
        </header>
        <main className={cn("flex-1", fullBleed ? "min-h-0" : "px-4 py-6 sm:px-8")}>{content}</main>
      </div>
    </div>
  );
}

export function ShellSkeleton() {
  return (
    <div className="flex min-h-screen" aria-busy="true" aria-label="Loading">
      <div className="hidden w-60 border-r bg-sidebar p-3 md:block">
        <Skeleton className="h-11 w-full" />
        <div className="mt-6 grid gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-8">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="mt-6 h-40 w-full max-w-3xl" />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AppProvider fallback={<ShellSkeleton />}>
      <ShellFrame>{children}</ShellFrame>
    </AppProvider>
  );
}
