"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Contact, Loader2, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useApp } from "@/components/app/app-context";
import { ListSkeleton, relativeTime, TagPill } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { FormError, FormField } from "@/components/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { useCustomerList, useTags, wsKeys, wsPath } from "@/lib/inbox-queries";
import type { Customer } from "@/lib/types";
import { cn } from "@/lib/utils";

type TypeFilter = "" | "identified" | "anonymous";

export function CustomerList() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [type, setType] = useState<TypeFilter>("");
  const [tag, setTag] = useState("");
  const [page, setPage] = useState(1);
  const tags = useTags(ws);
  const customers = useCustomerList(ws, { q, type, tag, page });

  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(handle);
  }, [search]);

  const total = customers.data?.count ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / 25));

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Customers"
        description="Everyone who has talked to you — identified customers and anonymous website visitors."
        actions={canWorkspace("customers.manage") ? <NewCustomerDialog /> : null}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email or phone"
            className="h-9 pl-8"
            aria-label="Search customers"
          />
        </div>
        <div className="flex rounded-lg border p-0.5" role="group" aria-label="Customer type">
          {(
            [
              ["", "All"],
              ["identified", "Identified"],
              ["anonymous", "Visitors"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              aria-pressed={type === value}
              onClick={() => {
                setType(value);
                setPage(1);
              }}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium",
                type === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {tags.data && tags.data.length > 0 ? (
          <select
            aria-label="Filter by tag"
            value={tag}
            onChange={(e) => {
              setTag(e.target.value);
              setPage(1);
            }}
            className="h-9 rounded-lg border bg-background px-2 text-sm"
          >
            <option value="">All tags</option>
            {tags.data.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {customers.isPending ? (
        <ListSkeleton rows={6} className="rounded-xl border" />
      ) : customers.isError ? (
        <ErrorState message={customers.error.message} onRetry={() => customers.refetch()} />
      ) : customers.data.results.length === 0 ? (
        <EmptyState
          icon={<Contact className="size-6" />}
          title={q || type || tag ? "No customers match these filters" : "No customers yet"}
          description={
            q || type || tag
              ? "Try clearing your search or filters."
              : "Customers appear automatically when visitors chat through your website widget."
          }
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Customer</TableHead>
                <TableHead className="hidden md:table-cell">Tags</TableHead>
                <TableHead className="hidden sm:table-cell">Conversations</TableHead>
                <TableHead className="pr-4 text-right">Last seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className={cn(customers.isPlaceholderData && "opacity-60")}>
              {customers.data.results.map((c) => (
                <CustomerRow key={c.id} customer={c} />
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between border-t px-4 py-2 text-sm text-muted-foreground">
            <span>
              {total} customer{total === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setPage((p) => p - 1)}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                <ChevronLeft />
              </Button>
              <span className="tabular-nums">
                {page} / {pageCount}
              </span>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={page >= pageCount}
                aria-label="Next page"
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function CustomerRow({ customer: c }: { customer: Customer }) {
  const router = useRouter();
  const href = `/app/customers/${c.id}`;
  return (
    <TableRow className="cursor-pointer" onClick={() => router.push(href)}>
      <TableCell className="pl-4">
        <Link href={href} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
          {c.display_name}
        </Link>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {c.email || (c.is_anonymous ? "Anonymous visitor" : "No email")}
          {c.is_anonymous ? (
            <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
              Visitor
            </Badge>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <div className="flex flex-wrap gap-1">
          {c.tags.slice(0, 3).map((t) => (
            <TagPill key={t.id} tag={t} />
          ))}
        </div>
      </TableCell>
      <TableCell className="hidden text-sm sm:table-cell">{c.conversation_count ?? 0}</TableCell>
      <TableCell className="pr-4 text-right text-sm text-muted-foreground">{relativeTime(c.last_seen_at ?? c.created_at)}</TableCell>
    </TableRow>
  );
}

const newCustomerSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(150),
  email: z.union([z.literal(""), z.string().trim().email("Enter a valid email")]),
  phone: z.string().trim().max(32).regex(/^[0-9+()\-. ]*$/, "Digits and + ( ) - . only"),
});
type NewCustomerValues = z.infer<typeof newCustomerSchema>;

function NewCustomerDialog() {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<NewCustomerValues>({
    resolver: zodResolver(newCustomerSchema),
    defaultValues: { name: "", email: "", phone: "" },
  });
  const create = useMutation({
    mutationFn: (values: NewCustomerValues) => api.post<Customer>(`${wsPath(ws)}/customers`, values),
    onSuccess: (customer) => {
      void queryClient.invalidateQueries({ queryKey: wsKeys.customers(ws) });
      toast.success("Customer created");
      setOpen(false);
      reset();
      router.push(`/app/customers/${customer.id}`);
    },
    onError: (error) => setFormError(applyApiErrors(error, setError, ["name", "email", "phone"])),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> New customer
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New customer</DialogTitle>
          <DialogDescription>Add someone you want to start a conversation with.</DialogDescription>
        </DialogHeader>
        <form
          id="new-customer"
          className="grid gap-4"
          noValidate
          onSubmit={handleSubmit((values) => {
            setFormError(null);
            create.mutate(values);
          })}
        >
          <FormError message={formError} />
          <FormField id="nc-name" label="Name" error={errors.name?.message} {...register("name")} />
          <FormField id="nc-email" label="Email" type="email" error={errors.email?.message} {...register("email")} />
          <FormField id="nc-phone" label="Phone" error={errors.phone?.message} {...register("phone")} />
        </form>
        <DialogFooter>
          <Button type="submit" form="new-customer" disabled={create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" /> : null} Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
