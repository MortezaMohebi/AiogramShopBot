"use client";

import { useCallback, useEffect, useId, useRef, type Dispatch, type SetStateAction } from "react";
import { Button } from "@/components/ui/button";

const number = new Intl.NumberFormat("fa-IR", { minimumIntegerDigits: 2 });
const rowHeight = 32;

function moveClockValue(value: number, steps: number, step: number, max: number) {
  // A saved minute or the current minute can fall between two stops.
  const index = steps > 0 ? Math.floor(value / step) : Math.ceil(value / step);
  const stops = max / step + 1;
  return (((index + steps) % stops + stops) % stops) * step;
}

export function ClockWheel({ label, max, step, value, onChange }: {
  label: string; max: number; step: number; value: number; onChange: Dispatch<SetStateAction<number>>;
}) {
  const id = useId();
  const wheel = useRef<HTMLDivElement>(null);
  const selected = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointerId: number; y: number } | null>(null);
  const didDrag = useRef(false);
  const move = useCallback((steps: number) => {
    onChange((current) => moveClockValue(current, steps, step, max));
  }, [max, onChange, step]);

  useEffect(() => {
    const element = wheel.current;
    if (!element) return;
    let distance = 0;
    let lastEvent = 0;
    function onWheel(event: WheelEvent) {
      if (event.ctrlKey || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      event.preventDefault();
      const delta = event.deltaMode === 0 ? event.deltaY : event.deltaY * rowHeight;
      if (event.timeStamp - lastEvent > 180 || Math.sign(distance) !== Math.sign(delta)) distance = 0;
      lastEvent = event.timeStamp;
      distance += Math.max(-rowHeight, Math.min(rowHeight, delta));
      const steps = Math.trunc(distance / rowHeight);
      if (steps) {
        distance -= steps * rowHeight;
        move(steps);
      }
    }
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [move]);

  function neighbor(direction: -1 | 1) {
    const text = number.format(moveClockValue(value, direction, step, max));
    return <Button type="button" variant="ghost" size="sm" tabIndex={-1}
      aria-label={`${label} ${text}`} className="h-8 min-h-8 w-full text-sm text-muted-foreground"
      onClick={() => {
        move(direction);
        selected.current?.focus({ preventScroll: true });
      }}>{text}</Button>;
  }

  return <div className="grid min-w-0 justify-items-center gap-1">
    <span id={id} className="text-xs text-muted-foreground">{label}</span>
    <div ref={wheel} className="w-full max-w-24 touch-none select-none rounded-md active:cursor-grabbing"
      onPointerDown={(event) => {
        if (!event.isPrimary || event.button !== 0) return;
        drag.current = { pointerId: event.pointerId, y: event.clientY };
        didDrag.current = false;
      }}
      onPointerMove={(event) => {
        const gesture = drag.current;
        if (!gesture || gesture.pointerId !== event.pointerId) return;
        const steps = Math.trunc((gesture.y - event.clientY) / rowHeight);
        if (!steps) return;
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.setPointerCapture(event.pointerId);
        }
        didDrag.current = true;
        gesture.y -= steps * rowHeight;
        move(steps);
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onPointerLeave={() => { if (!didDrag.current) drag.current = null; }}
      onClickCapture={(event) => {
        if (didDrag.current && event.detail > 0) event.stopPropagation();
        didDrag.current = false;
      }}>
      {neighbor(-1)}
      <div ref={selected} role="spinbutton" tabIndex={0} aria-labelledby={id}
        aria-valuemin={0} aria-valuemax={Math.max(value, max)}
        aria-valuenow={value} aria-valuetext={number.format(value)}
        className="flex h-8 cursor-grab items-center justify-center rounded-md border border-primary/40 bg-primary/10 text-base font-semibold tabular-nums focus-visible:outline-2 focus-visible:outline-ring"
        onKeyDown={(event) => {
          switch (event.key) {
            case "ArrowUp": move(1); break;
            case "ArrowDown": move(-1); break;
            case "Home": onChange(0); break;
            case "End": onChange(max); break;
            default: return;
          }
          event.preventDefault();
        }}>{number.format(value)}</div>
      {neighbor(1)}
    </div>
  </div>;
}
