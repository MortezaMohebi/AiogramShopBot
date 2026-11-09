"use client";

import {
  fromDate, getLocalTimeZone, parseDate, PersianCalendar, Time, toCalendar,
  toCalendarDateTime, today, toZoned, type CalendarDate,
} from "@internationalized/date";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import {
  Button as AriaButton, Calendar, CalendarCell, CalendarGrid, CalendarGridBody, CalendarGridHeader,
  CalendarHeaderCell, CalendarMonthPicker, CalendarYearPicker, Dialog,
  DialogTrigger, I18nProvider, Popover,
} from "react-aria-components";
import { Button, buttonVariants } from "@/components/ui/button";
import { ClockWheel } from "@/components/ui/clock-wheel";
import { parseCalendarDate, persianDateLabel, utcPickerValue } from "@/lib/persian-calendar";
import { cn } from "@/lib/utils";

const persian = new PersianCalendar();
const yearLabel = new Intl.NumberFormat("fa-IR", { useGrouping: false });
const monthLabel = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { month: "long", year: "numeric", timeZone: "UTC" });
const clockNumber = new Intl.NumberFormat("fa-IR", { minimumIntegerDigits: 2 });
const navButton = buttonVariants({ variant: "ghost", size: "icon" });
const subscribeToZone = () => () => {};

type PickerValue =
  | { name: string; defaultValue?: string; value?: never; onChange?: never }
  | { name?: never; defaultValue?: never; value: string; onChange: (value: string) => void };
type View = "day" | "month" | "year";

function CalendarChoices({ label, items, value, onChoose }: {
  label: string;
  items: { id: number; formatted: string }[];
  value: string | number | bigint;
  onChoose: (id: number) => void;
}) {
  return <div role="group" aria-label={label} className="grid grid-cols-3 gap-1">
    {items.map((item) => <Button key={item.id} type="button" size="sm"
      autoFocus={item.id === value} aria-pressed={item.id === value}
      variant={item.id === value ? "default" : "ghost"} onClick={() => onChoose(item.id)}>
      {item.formatted}
    </Button>)}
  </div>;
}

/** The calendar emits civil dates or ISO timestamps, depending on the field. */
export function PersianDatePicker({
  name, label, defaultValue = "", value: controlledValue, onChange, withTime = false,
}: PickerValue & { label: string; withTime?: boolean }) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const formValue = useRef<HTMLInputElement>(null);
  const notifyForm = useRef(false);
  const zone = useSyncExternalStore(subscribeToZone, getLocalTimeZone, () => "UTC");
  const [localValue, setLocalValue] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("day");
  const [focused, setFocused] = useState<CalendarDate | null>(null);
  const [draft, setDraft] = useState<CalendarDate | null>(null);
  const [hour, setHour] = useState(0);
  const [minute, setMinute] = useState(0);
  const value = controlledValue ?? localValue;
  useEffect(() => {
    if (!notifyForm.current) return;
    notifyForm.current = false;
    formValue.current?.dispatchEvent(new Event("input", { bubbles: true }));
  }, [value]);
  const utc = withTime ? utcPickerValue(value) : "";
  const local = utc ? fromDate(new Date(utc), zone) : null;
  const datePart = local?.toString().slice(0, 10) ?? value;
  const selected = parseCalendarDate(datePart);
  const current = selected ? parseDate(datePart) : null;
  const year = focused ? toCalendar(focused, persian).year : null;

  function changeOpen(next: boolean) {
    if (next) {
      setView("day");
      setFocused(current ?? today(zone));
      setDraft(current);
      if (withTime) {
        const now = fromDate(new Date(), zone);
        setHour(local?.hour ?? now.hour);
        setMinute(local?.minute ?? Math.floor(now.minute / 5) * 5);
      }
    }
    setOpen(next);
  }

  function commit(nextValue: string) {
    if (onChange) onChange(nextValue);
    else if (nextValue !== value) {
      notifyForm.current = true;
      setLocalValue(nextValue);
    }
    setOpen(false);
  }

  function chooseDay(date: CalendarDate) {
    if (withTime) setDraft(date);
    else commit(date.toString());
  }

  function chooseToday() {
    const now = fromDate(new Date(), zone);
    const date = parseDate(now.toString().slice(0, 10));
    setView("day");
    setFocused(date);
    chooseDay(date);
    if (withTime) {
      setHour(now.hour);
      setMinute(now.minute);
    }
  }

  function confirmTime() {
    if (!draft) return;
    const sameTime = local?.hour === hour && local.minute === minute;
    if (sameTime && draft.toString() === datePart) {
      commit(value);
      return;
    }
    const time = new Time(hour, minute, sameTime ? local.second : 0, sameTime ? local.millisecond : 0);
    const dateTime = toCalendarDateTime(parseDate(draft.toString()), time);
    commit(toZoned(dateTime, zone).toAbsoluteString());
  }

  function moveYears(direction: number) {
    setFocused((date) => date ? toCalendar(date, persian).add({ years: direction * (view === "year" ? 12 : 1) }) : null);
  }

  return <div className="relative grid min-w-0 gap-2 text-sm">
    <label id={`${id}-label`} htmlFor={id}>{label}</label>
    {name ? <input ref={formValue} data-draft-field type="hidden" name={name} value={selected ? value : ""} /> : null}
    <I18nProvider locale="fa-IR-u-ca-persian">
      <DialogTrigger isOpen={open} onOpenChange={changeOpen}>
        <AriaButton ref={trigger} id={id} aria-labelledby={`${id}-label ${id}-value`}
          className={cn(buttonVariants({ variant: "outline" }),
            "w-full min-w-0 justify-start border-input bg-background px-3 text-start font-normal",
            selected && "pe-11")}>
          <span id={`${id}-value`} className={cn("min-w-0 truncate", !selected && "text-muted-foreground")}>
            {selected ? persianDateLabel(selected) : withTime ? "انتخاب تاریخ و زمان" : "انتخاب تاریخ"}
            {local ? <> · <bdi>{clockNumber.format(local.hour)}:{clockNumber.format(local.minute)}</bdi></> : null}
          </span>
        </AriaButton>
        <Popover placement="bottom start" offset={6} containerPadding={8}
          className="z-50 w-80 max-w-[calc(100vw-1rem)] overflow-y-auto overscroll-contain rounded-xl border border-border bg-popover text-popover-foreground shadow-xl">
          <Dialog aria-label={label} className="space-y-3 bg-popover p-3 outline-none">
            <Calendar aria-label="تقویم شمسی" value={withTime ? draft : current} focusedValue={focused}
              onFocusChange={setFocused} onChange={chooseDay} firstDayOfWeek="sat" autoFocus>
              {view === "day" ? <>
                <header className="mb-2 flex items-center justify-between">
                  <AriaButton slot="previous" aria-label="ماه قبل" className={navButton}>
                    <ChevronRight aria-hidden="true" />
                  </AriaButton>
                  <Button type="button" variant="ghost" size="sm" aria-label="انتخاب ماه" onClick={() => setView("month")}>
                    {focused ? monthLabel.format(focused.toDate("UTC")) : "انتخاب ماه"}
                  </Button>
                  <AriaButton slot="next" aria-label="ماه بعد" className={navButton}>
                    <ChevronLeft aria-hidden="true" />
                  </AriaButton>
                </header>
                <CalendarGrid className="w-full table-fixed border-separate border-spacing-px text-center">
                  <CalendarGridHeader>
                    {(day) => <CalendarHeaderCell className="pb-1 text-xs font-normal text-muted-foreground">{day}</CalendarHeaderCell>}
                  </CalendarGridHeader>
                  <CalendarGridBody>
                    {(date) => <CalendarCell date={date}
                      className="flex h-9 cursor-pointer items-center justify-center rounded-md border border-transparent text-sm outline-none data-[disabled]:cursor-default data-[disabled]:opacity-50 data-[focus-visible]:outline-2 data-[focus-visible]:outline-ring data-[hovered]:bg-accent data-[outside-month]:invisible data-[selected]:bg-primary data-[selected]:text-primary-foreground data-[today]:border-primary" />}
                  </CalendarGridBody>
                </CalendarGrid>
              </> : <>
                <header className="mb-2 flex items-center justify-between">
                  <Button type="button" variant="ghost" size="icon" aria-label={view === "month" ? "سال قبل" : "سال‌های قبل"}
                    onClick={() => moveYears(-1)}><ChevronRight aria-hidden="true" /></Button>
                  {view === "month" && year ? <Button type="button" variant="ghost" size="sm"
                    aria-label="انتخاب سال" onClick={() => setView("year")}>{yearLabel.format(year)}</Button> :
                    <span className="font-medium">انتخاب سال</span>}
                  <Button type="button" variant="ghost" size="icon" aria-label={view === "month" ? "سال بعد" : "سال‌های بعد"}
                    onClick={() => moveYears(1)}><ChevronLeft aria-hidden="true" /></Button>
                </header>
                {view === "month" ? <CalendarMonthPicker format="long">{({ items, value, onChange }) =>
                  <CalendarChoices label="ماه‌ها" items={items} value={value}
                    onChoose={(month) => { onChange(month); setView("day"); }} />
                }</CalendarMonthPicker> : <CalendarYearPicker visibleYears={12}>{({ items, value, onChange }) =>
                  <CalendarChoices label="سال‌ها" items={items} value={value}
                    onChoose={(year) => { onChange(year); setView("month"); }} />
                }</CalendarYearPicker>}
              </>}
            </Calendar>
            {withTime && view === "day" ? <div className="grid grid-cols-2 gap-3 border-t border-border pt-2">
              <ClockWheel label="ساعت" max={23} step={1} value={hour} onChange={setHour} />
              <ClockWheel label="دقیقه" max={55} step={5} value={minute} onChange={setMinute} />
            </div> : null}
            <div className="flex items-center justify-between gap-2 border-t border-border pt-2">
              <Button type="button" variant="ghost" size="sm" onClick={chooseToday}>امروز</Button>
              {withTime && view === "day" ? <Button type="button" size="sm"
                disabled={!draft} onClick={confirmTime}>تأیید</Button> : null}
            </div>
          </Dialog>
        </Popover>
      </DialogTrigger>
    </I18nProvider>
    {selected ? <Button type="button" variant="ghost" size="icon" className="absolute end-1 bottom-1 size-8 text-muted-foreground"
      aria-label={`پاک‌کردن تاریخ: ${label}`} onClick={() => {
        trigger.current?.focus();
        commit("");
      }}><X aria-hidden="true" /></Button> : null}
  </div>;
}
