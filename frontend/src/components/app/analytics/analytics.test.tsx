import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TrendChart } from "@/components/app/analytics/trend-chart";
import { PricingPlans } from "@/components/pricing-plans";
import { formatDuration, formatMoney } from "@/lib/platform";

class FakeResizeObserver {
  constructor(private cb: ResizeObserverCallback) {}
  observe() {
    this.cb([{ contentRect: { width: 600 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("ResizeObserver", FakeResizeObserver);

const DATA = [
  { date: "2026-11-01", created: 3, resolved: 1, ai_replies: 2 },
  { date: "2026-11-02", created: 5, resolved: 4, ai_replies: 6 },
  { date: "2026-11-03", created: 2, resolved: 3, ai_replies: 1 },
];
const SERIES = [
  { key: "created", label: "New", color: "var(--viz-1)" },
  { key: "resolved", label: "Resolved", color: "var(--viz-2)" },
  { key: "ai_replies", label: "AI replies", color: "var(--viz-3)" },
];

describe("TrendChart", () => {
  it("draws one 2px line per series with direct end labels", () => {
    const { container } = render(<TrendChart data={DATA} series={SERIES} />);
    const lines = container.querySelectorAll("polyline");
    expect(lines).toHaveLength(3);
    lines.forEach((l) => expect(l.getAttribute("stroke-width")).toBe("2"));
    for (const s of SERIES) expect(screen.getByText(s.label)).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("Daily trend of New, Resolved, AI replies");
  });

  it("shows a tooltip with all series values via keyboard", () => {
    render(<TrendChart data={DATA} series={SERIES} />);
    const svg = screen.getByRole("img");
    fireEvent.keyDown(svg, { key: "ArrowRight" });
    fireEvent.keyDown(svg, { key: "ArrowRight" });
    const tip = screen.getByRole("status");
    expect(tip).toHaveTextContent("New5");
    expect(tip).toHaveTextContent("Resolved4");
    expect(tip).toHaveTextContent("AI replies6");
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("formatting", () => {
  it("formats money in minor units per currency", () => {
    expect(formatMoney(9900, "USD")).toBe("$99");
    expect(formatMoney(249900, "INR")).toBe("₹2,499");
  });

  it("formats durations compactly", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(600)).toBe("10m");
    expect(formatDuration(5400)).toBe("1.5h");
  });
});

describe("PricingPlans", () => {
  it("renders public plans and switches currency", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            { code: "starter", name: "Starter", description: "", prices: { INR: 249900, USD: 3900 }, limits: {}, features: ["3 seats"], trial_days: 0 },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PricingPlans />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("$39")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "INR ₹" }));
    expect(screen.getByText("₹2,499")).toBeInTheDocument();
    vi.unstubAllGlobals();
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  });
});
