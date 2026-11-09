"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Multi-series daily line chart (hand-rolled SVG).
 * Spec (dataviz skill): one y-axis, 2px lines, recessive grid, fixed categorical
 * order (validated palette tokens --viz-1..3), legend + direct end labels,
 * crosshair + tooltip on hover/focus, text in text tokens (never series color).
 */
export interface Series {
  key: string;
  label: string;
  color: string; // CSS color (token)
}

const HEIGHT = 240;
const PAD = { top: 12, right: 92, bottom: 28, left: 36 };

function niceMax(value: number): number {
  if (value <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow * 4 >= value)! * pow;
  return step * 4;
}

export function TrendChart<T extends { date: string } & Record<string, number | string>>({
  data,
  series,
}: {
  data: T[];
  series: Series[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const max = useMemo(() => niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0)))), [data, series]);
  const innerW = width - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (data.length <= 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * max));
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(innerW / 70))));
  const fmtDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  // Direct end labels, nudged apart vertically so they never collide.
  const endLabels = useMemo(() => {
    if (!data.length) return [];
    const last = data[data.length - 1];
    const placed = series
      .map((s) => ({ ...s, value: Number(last[s.key]) || 0, y: y(Number(last[s.key]) || 0) }))
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < placed.length; i++) placed[i].y = Math.max(placed[i].y, placed[i - 1].y + 14);
    return placed;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, series, max, width]);

  const onMove = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || !data.length) return;
    const rel = clientX - rect.left - PAD.left;
    setHover(Math.max(0, Math.min(data.length - 1, Math.round((rel / innerW) * (data.length - 1)))));
  };

  const active = hover != null ? data[hover] : null;

  return (
    <div ref={ref} className="relative w-full select-none">
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label={`Daily trend of ${series.map((s) => s.label).join(", ")}`}
        onMouseMove={(e) => onMove(e.clientX)}
        onMouseLeave={() => setHover(null)}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setHover((h) => Math.min(data.length - 1, (h ?? -1) + 1));
          if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? data.length) - 1));
          if (e.key === "Escape") setHover(null);
        }}
        onBlur={() => setHover(null)}
        className="outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        {data.map((d, i) =>
          i % labelEvery === 0 || i === data.length - 1 ? (
            <text key={d.date} x={x(i)} y={HEIGHT - 8} textAnchor="middle" className="fill-muted-foreground text-[11px]">
              {fmtDay(d.date)}
            </text>
          ) : null,
        )}
        {series.map((s) => (
          <polyline
            key={s.key}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            points={data.map((d, i) => `${x(i)},${y(Number(d[s.key]) || 0)}`).join(" ")}
          />
        ))}
        {endLabels.map((l) => (
          <g key={l.key}>
            <circle cx={x(data.length - 1) + 8} cy={l.y} r={3} fill={l.color} />
            <text x={x(data.length - 1) + 15} y={l.y} dy="0.32em" className="fill-foreground text-[11px]">
              {l.label}
            </text>
          </g>
        ))}
        {hover != null && active ? (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="stroke-foreground/30" strokeWidth={1} />
            {series.map((s) => (
              <circle
                key={s.key}
                cx={x(hover)}
                cy={y(Number(active[s.key]) || 0)}
                r={4.5}
                fill={s.color}
                className="stroke-background"
                strokeWidth={2}
              />
            ))}
          </g>
        ) : null}
      </svg>
      {hover != null && active ? (
        <div
          role="status"
          className="pointer-events-none absolute top-2 z-10 min-w-36 rounded-lg border bg-popover px-3 py-2 text-xs shadow-md"
          style={x(hover) > width / 2 ? { right: width - x(hover) + 12 } : { left: x(hover) + 12 }}
        >
          <p className="mb-1 font-medium">{fmtDay(active.date)}</p>
          {series.map((s) => (
            <p key={s.key} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2 rounded-full" style={{ backgroundColor: s.color }} />
                {s.label}
              </span>
              <span className="font-medium tabular-nums">{Number(active[s.key]) || 0}</span>
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
