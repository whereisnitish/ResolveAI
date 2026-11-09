import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PriorityIcon, shortAgo, StatusBadge, TagPill } from "@/components/app/common";
import { buildInboxFilters } from "@/components/app/inbox/inbox-layout";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  usePathname: () => "/app/inbox",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("buildInboxFilters", () => {
  it.each([
    ["mine", "open", "", { status: "open", assignee: "me" }],
    ["unassigned", "pending", "", { status: "pending", assignee: "unassigned" }],
    ["all", "resolved", " refund ", { status: "resolved", q: "refund" }],
    ["team:abc", "closed", "", { status: "closed", team: "abc" }],
    ["all", "bogus", "", { status: "open" }],
  ])("view=%s status=%s q=%j", (view, status, q, expected) => {
    expect(buildInboxFilters(view, status, q)).toEqual(expected);
  });
});

describe("shortAgo", () => {
  it("formats compact relative times", () => {
    const now = Date.now();
    expect(shortAgo(new Date(now - 10_000).toISOString())).toBe("now");
    expect(shortAgo(new Date(now - 5 * 60_000).toISOString())).toBe("5m");
    expect(shortAgo(new Date(now - 3 * 3_600_000).toISOString())).toBe("3h");
    expect(shortAgo(new Date(now - 2 * 86_400_000).toISOString())).toBe("2d");
    expect(shortAgo(null)).toBe("");
  });
});

describe("badges", () => {
  it("renders status and accessible priority", () => {
    render(
      <>
        <StatusBadge status="pending" />
        <PriorityIcon priority="urgent" />
      </>,
    );
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByLabelText("Urgent priority")).toBeInTheDocument();
  });

  it("renders tag names as text (no HTML injection)", () => {
    render(<TagPill tag={{ id: "1", name: "<b>vip</b>", color: "#ff0000" }} />);
    expect(screen.getByText("<b>vip</b>")).toBeInTheDocument();
  });
});
