"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CircleDot,
  Loader2,
  MessageSquarePlus,
  MessagesSquare,
  StickyNote,
  Trash2,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useApp } from "@/components/app/app-context";
import { formatDateTime, ListSkeleton, relativeTime, StatusBadge, TagPill } from "@/components/app/common";
import { ErrorState } from "@/components/app/team/team-page";
import { FormError, FormField } from "@/components/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import {
  useConversationList,
  useCustomer,
  useCustomerNotes,
  useCustomerTimeline,
  useTags,
  wsKeys,
  wsPath,
} from "@/lib/inbox-queries";
import type { Conversation, Customer } from "@/lib/types";

export function CustomerDetail() {
  const { customerId } = useParams<{ customerId: string }>();
  const { workspace } = useApp();
  const ws = workspace!.id;
  const customer = useCustomer(ws, customerId);

  if (customer.isPending) return <ListSkeleton rows={6} className="mx-auto max-w-5xl" />;
  if (customer.isError) {
    return (
      <div className="mx-auto max-w-5xl">
        <ErrorState
          message={
            customer.error instanceof ApiError && customer.error.status === 404
              ? "This customer doesn't exist or isn't in this workspace."
              : customer.error.message
          }
          onRetry={() => customer.refetch()}
        />
      </div>
    );
  }
  return <CustomerView key={customer.data.id} customer={customer.data} />;
}

function CustomerView({ customer: c }: { customer: Customer }) {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const canManage = canWorkspace("customers.manage");

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/app/customers" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Customers
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <UserRound className="size-6" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{c.display_name}</h1>
            <p className="text-sm text-muted-foreground">
              {c.email || "No email"} {c.is_anonymous ? <Badge variant="secondary">Anonymous visitor</Badge> : null}
            </p>
          </div>
        </div>
        {canWorkspace("conversations.reply") ? <StartConversationDialog customer={c} /> : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="grid content-start gap-6">
          <ProfileCard customer={c} canManage={canManage} />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                Tags {canManage ? <CustomerTagEditor customer={c} /> : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {c.tags.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {c.tags.map((t) => (
                    <TagPill key={t.id} tag={t} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No tags</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              <Row label="First seen" value={formatDateTime(c.created_at)} />
              <Row label="Last seen" value={relativeTime(c.last_seen_at)} />
              {c.last_seen_url ? <Row label="Last page" value={c.last_seen_url} /> : null}
              {c.user_agent ? <Row label="Browser" value={c.user_agent} /> : null}
              {Object.entries(c.attributes).map(([k, v]) => (
                <Row key={k} label={k} value={String(v)} />
              ))}
              <p className="pt-1 text-xs text-muted-foreground">ID: {c.id}</p>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          <Tabs defaultValue="conversations">
            <TabsList>
              <TabsTrigger value="conversations">Conversations</TabsTrigger>
              <TabsTrigger value="notes">Notes</TabsTrigger>
              <TabsTrigger value="activity">Activity</TabsTrigger>
            </TabsList>
            <TabsContent value="conversations" className="mt-4">
              <CustomerConversations ws={ws} customerId={c.id} />
            </TabsContent>
            <TabsContent value="notes" className="mt-4">
              <Notes ws={ws} customerId={c.id} canManage={canManage} />
            </TabsContent>
            <TabsContent value="activity" className="mt-4">
              <Timeline ws={ws} customerId={c.id} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-2">
      <span className="truncate text-muted-foreground">{label}</span>
      <span className="truncate" title={value}>
        {value}
      </span>
    </div>
  );
}

const profileSchema = z.object({
  name: z.string().trim().max(150),
  email: z.union([z.literal(""), z.string().trim().email("Enter a valid email")]),
  phone: z.string().trim().max(32).regex(/^[0-9+()\-. ]*$/, "Digits and + ( ) - . only"),
});
type ProfileValues = z.infer<typeof profileSchema>;

function ProfileCard({ customer: c, canManage }: { customer: Customer; canManage: boolean }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isDirty },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    values: { name: c.name, email: c.email, phone: c.phone },
  });
  const save = useMutation({
    mutationFn: (values: ProfileValues) => api.patch<Customer>(`${wsPath(ws)}/customers/${c.id}`, values),
    onSuccess: (updated) => {
      queryClient.setQueryData(wsKeys.customer(ws, c.id), updated);
      void queryClient.invalidateQueries({ queryKey: wsKeys.customers(ws) });
      toast.success("Customer updated");
    },
    onError: (error) => setFormError(applyApiErrors(error, setError, ["name", "email", "phone"])),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-3"
          noValidate
          onSubmit={handleSubmit((values) => {
            setFormError(null);
            save.mutate(values);
          })}
        >
          <FormError message={formError} />
          <FormField id="c-name" label="Name" disabled={!canManage} error={errors.name?.message} {...register("name")} />
          <FormField id="c-email" label="Email" type="email" disabled={!canManage} error={errors.email?.message} {...register("email")} />
          <FormField id="c-phone" label="Phone" disabled={!canManage} error={errors.phone?.message} {...register("phone")} />
          {canManage ? (
            <Button type="submit" size="sm" disabled={!isDirty || save.isPending} className="justify-self-end">
              {save.isPending ? <Loader2 className="animate-spin" /> : null} Save
            </Button>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}

function CustomerTagEditor({ customer: c }: { customer: Customer }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const tags = useTags(ws);
  const queryClient = useQueryClient();
  const selected = new Set(c.tags.map((t) => t.id));
  const save = useMutation({
    mutationFn: (ids: string[]) => api.patch<Customer>(`${wsPath(ws)}/customers/${c.id}`, { tag_ids: ids }),
    onSuccess: (updated) => queryClient.setQueryData(wsKeys.customer(ws, c.id), updated),
    onError: (error) => toast.error(error.message),
  });
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="ghost" size="sm" />}>Edit</PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        {tags.data?.length ? (
          <ul className="grid max-h-64 gap-0.5 overflow-y-auto">
            {tags.data.map((t) => (
              <li key={t.id}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                  <Checkbox
                    checked={selected.has(t.id)}
                    onCheckedChange={() => {
                      const next = new Set(selected);
                      if (next.has(t.id)) next.delete(t.id);
                      else next.add(t.id);
                      save.mutate([...next]);
                    }}
                  />
                  <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: t.color }} />
                  <span className="truncate">{t.name}</span>
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-2 text-sm text-muted-foreground">
            No tags yet. Create them in{" "}
            <Link href="/app/settings?tab=inbox" className="text-primary hover:underline">
              Settings → Inbox
            </Link>
            .
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}

function CustomerConversations({ ws, customerId }: { ws: string; customerId: string }) {
  const list = useConversationList(ws, { customer: customerId, status: "all" });
  const conversations = list.data?.pages.flatMap((p) => p.results) ?? [];
  if (list.isPending) return <ListSkeleton rows={3} />;
  if (list.isError) return <ErrorState message={list.error.message} onRetry={() => list.refetch()} />;
  if (!conversations.length) {
    return <p className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No conversations yet.</p>;
  }
  return (
    <ul className="grid gap-2">
      {conversations.map((c: Conversation) => (
        <li key={c.id}>
          <Link href={`/app/inbox/${c.id}?view=all&status=${c.status}`} className="block rounded-xl border bg-card p-3 hover:bg-muted/50">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">
                #{c.number} {c.subject ? `· ${c.subject}` : ""}
              </span>
              <StatusBadge status={c.status} />
            </div>
            <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">{c.last_message_preview}</p>
            <p className="mt-1 text-xs text-muted-foreground">{relativeTime(c.last_message_at)}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Notes({ ws, customerId, canManage }: { ws: string; customerId: string; canManage: boolean }) {
  const { me, canWorkspace } = useApp();
  const notes = useCustomerNotes(ws, customerId);
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: wsKeys.customerNotes(ws, customerId) });
    void queryClient.invalidateQueries({ queryKey: wsKeys.customerTimeline(ws, customerId) });
  };
  const add = useMutation({
    mutationFn: () => api.post(`${wsPath(ws)}/customers/${customerId}/notes`, { body }),
    onSuccess: () => {
      setBody("");
      refresh();
    },
    onError: (error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${wsPath(ws)}/customer-notes/${id}`),
    onSuccess: refresh,
    onError: (error) => toast.error(error.message),
  });

  return (
    <div className="grid gap-4">
      {canManage ? (
        <div className="grid gap-2">
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Add a note about this customer (visible to your team only)"
            maxLength={5000}
            aria-label="New note"
          />
          <Button size="sm" className="justify-self-end" onClick={() => add.mutate()} disabled={!body.trim() || add.isPending}>
            {add.isPending ? <Loader2 className="animate-spin" /> : <StickyNote />} Add note
          </Button>
        </div>
      ) : null}
      {notes.isPending ? (
        <ListSkeleton rows={2} />
      ) : notes.isError ? (
        <ErrorState message={notes.error.message} onRetry={() => notes.refetch()} />
      ) : notes.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No notes yet.</p>
      ) : (
        <ul className="grid gap-2">
          {notes.data.map((n) => (
            <li key={n.id} className="rounded-xl border border-amber-200 bg-amber-50/60 p-3">
              <p className="text-sm whitespace-pre-wrap">{n.body}</p>
              <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {n.author?.full_name ?? "Former teammate"} · {relativeTime(n.created_at)}
                </span>
                {n.author?.id === me.user.id || canWorkspace("workspace.update") ? (
                  <Button variant="ghost" size="icon-xs" aria-label="Delete note" onClick={() => remove.mutate(n.id)}>
                    <Trash2 />
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Timeline({ ws, customerId }: { ws: string; customerId: string }) {
  const timeline = useCustomerTimeline(ws, customerId);
  if (timeline.isPending) return <ListSkeleton rows={4} />;
  if (timeline.isError) return <ErrorState message={timeline.error.message} onRetry={() => timeline.refetch()} />;
  return (
    <ol className="relative grid gap-4 border-l pl-5">
      {timeline.data.map((item) => (
        <li key={item.id} className="relative">
          <span className="absolute top-1 -left-[27px] flex size-3.5 items-center justify-center rounded-full bg-background">
            {item.kind === "note" ? (
              <StickyNote className="size-3.5 text-amber-600" />
            ) : item.kind.startsWith("conversation") ? (
              <MessagesSquare className="size-3.5 text-primary" />
            ) : (
              <CircleDot className="size-3.5 text-muted-foreground" />
            )}
          </span>
          <p className="text-sm font-medium">{item.title}</p>
          {item.detail ? <p className="line-clamp-2 text-sm text-muted-foreground">{item.detail}</p> : null}
          <p className="text-xs text-muted-foreground">
            {item.actor_name ? `${item.actor_name} · ` : ""}
            {formatDateTime(item.at)}
            {item.conversation_id ? (
              <>
                {" · "}
                <Link href={`/app/inbox/${item.conversation_id}?view=all&status=all`} className="text-primary hover:underline">
                  View
                </Link>
              </>
            ) : null}
          </p>
        </li>
      ))}
    </ol>
  );
}

function StartConversationDialog({ customer }: { customer: Customer }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const start = useMutation({
    mutationFn: () => api.post<Conversation>(`${wsPath(ws)}/conversations`, { customer_id: customer.id, subject, body }),
    onSuccess: (conv) => {
      void queryClient.invalidateQueries({ queryKey: wsKeys.conversations(ws) });
      setOpen(false);
      router.push(`/app/inbox/${conv.id}?view=all&status=open`);
    },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <MessageSquarePlus /> New conversation
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Message {customer.display_name}</DialogTitle>
          <DialogDescription>
            The customer sees this the next time they open your website widget.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <FormError message={start.error instanceof ApiError ? start.error.message : null} />
          <FormField id="sc-subject" label="Subject (optional)" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} />
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write your message…" aria-label="Message" maxLength={10000} className="min-h-28" />
        </div>
        <DialogFooter>
          <Button onClick={() => start.mutate()} disabled={!body.trim() || start.isPending}>
            {start.isPending ? <Loader2 className="animate-spin" /> : null} Send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
