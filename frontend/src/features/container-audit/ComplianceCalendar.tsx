import { useCallback, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { Badge, Button, LoadingState, ErrorState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { apiRequest } from '@/lib/api/client';
import type { CalendarDay, CalendarSummary } from './types';

function formatMonthYear(d: Date): string {
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

function toIsoDate(d: Date): string {
  const year = String(d.getFullYear());
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function ComplianceCalendar() {
  const [currentDate, setCurrentDate] = useState(() => new Date());
  const [selectedDay, setSelectedDay] = useState<CalendarDay | null>(null);

  const { fromDate, toDate } = useMemo(() => {
    const y = currentDate.getFullYear();
    const m = currentDate.getMonth();
    const firstDay = new Date(y, m, 1);
    const lastDay = new Date(y, m + 1, 0);
    return {
      fromDate: toIsoDate(firstDay),
      toDate: toIsoDate(lastDay),
    };
  }, [currentDate]);

  const fetcher = useCallback(() => {
    return apiRequest<CalendarSummary>('/container-audits', {
      query: { from: fromDate, to: toDate },
    });
  }, [fromDate, toDate]);

  const { data, loading, error, reload } = useApiQuery<CalendarSummary>(fetcher);

  const daysMap = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    data?.days.forEach((d) => {
      map.set(d.audit_date, d);
    });
    return map;
  }, [data?.days]);

  const calendarGrid = useMemo(() => {
    const y = currentDate.getFullYear();
    const m = currentDate.getMonth();
    const firstDay = new Date(y, m, 1);
    const lastDay = new Date(y, m + 1, 0);

    const totalDays = lastDay.getDate();
    const startOffset = (firstDay.getDay() + 6) % 7;

    const cells: Array<{ dateStr: string; dayNum: number } | null> = [];
    for (let i = 0; i < startOffset; i++) {
      cells.push(null);
    }
    for (let d = 1; d <= totalDays; d++) {
      const dt = new Date(y, m, d);
      cells.push({
        dateStr: toIsoDate(dt),
        dayNum: d,
      });
    }
    return cells;
  }, [currentDate]);

  const handlePrevMonth = () => {
    setCurrentDate((prev) => new Date(prev.getFullYear(), prev.getMonth() - 1, 1));
    setSelectedDay(null);
  };

  const handleNextMonth = () => {
    setCurrentDate((prev) => new Date(prev.getFullYear(), prev.getMonth() + 1, 1));
    setSelectedDay(null);
  };

  return (
    <div className="space-y-6">
      {/* Calendar Header */}
      <div className="flex items-center justify-between bg-card border border-border rounded-xl p-4">
        <h2 className="font-bold text-lg text-foreground">{formatMonthYear(currentDate)}</h2>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handlePrevMonth}
            aria-label="Previous month"
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <Button variant="secondary" size="sm" onClick={handleNextMonth} aria-label="Next month">
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Status Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs font-medium text-muted-foreground px-1">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-emerald-500 inline-block" />
          <span>Confirmed On-Time</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-amber-500 inline-block" />
          <span>Late Confirmation</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-destructive inline-block" />
          <span>Missed Day</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-muted-foreground/30 inline-block" />
          <span>Pending / Uncounted</span>
        </div>
      </div>

      {loading ? (
        <LoadingState label="Loading monthly compliance data..." />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} title="Failed to load compliance calendar." />
      ) : (
        <div className="bg-card border border-border rounded-xl p-4 sm:p-6">
          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-1 text-center text-xs font-semibold text-muted-foreground pb-2 border-b border-border">
            <span>Mon</span>
            <span>Tue</span>
            <span>Wed</span>
            <span>Thu</span>
            <span>Fri</span>
            <span>Sat</span>
            <span>Sun</span>
          </div>

          {/* Day Cells Grid */}
          <div className="grid grid-cols-7 gap-1.5 mt-2">
            {calendarGrid.map((cell, idx) => {
              if (!cell) {
                return (
                  <div
                    key={`empty-${String(idx)}`}
                    className="h-16 sm:h-20 rounded-lg bg-muted/10"
                  />
                );
              }

              const dayData = daysMap.get(cell.dateStr);
              const status = dayData?.status;
              const isConfirmed = dayData?.confirmed;

              let bgClass = 'bg-background hover:bg-accent/40 border-border';
              let badgeColor = 'bg-muted-foreground/20 text-muted-foreground';

              if (status === 'CONFIRMED') {
                bgClass = 'bg-emerald-500/10 border-emerald-500/30 hover:bg-emerald-500/20';
                badgeColor = 'bg-emerald-500 text-white';
              } else if (status === 'LATE') {
                bgClass = 'bg-amber-500/10 border-amber-500/30 hover:bg-amber-500/20';
                badgeColor = 'bg-amber-500 text-white';
              } else if (status === 'MISSED') {
                bgClass = 'bg-destructive/10 border-destructive/30 hover:bg-destructive/20';
                badgeColor = 'bg-destructive text-destructive-foreground';
              }

              const isSelected = selectedDay?.audit_date === cell.dateStr;

              return (
                <button
                  type="button"
                  key={cell.dateStr}
                  // Status must not be conveyed by colour alone (WCAG 1.4.1, P2-08 fix).
                  aria-label={`${cell.dateStr}: ${status ?? 'no audit recorded'}`}
                  data-status={status ?? 'NONE'}
                  onClick={() => {
                    setSelectedDay(
                      dayData ?? {
                        audit_date: cell.dateStr,
                        status: 'PENDING',
                        is_late: false,
                        confirmed: false,
                        confirmed_at: null,
                        total_containers_counted: 0,
                        total_sellable_packaging_qty: 0,
                        remarks: null,
                      },
                    );
                  }}
                  className={`h-16 sm:h-20 p-1.5 sm:p-2 rounded-lg border flex flex-col justify-between text-left transition-all ${bgClass} ${
                    isSelected ? 'ring-2 ring-primary ring-offset-2' : ''
                  }`}
                >
                  <div className="flex items-center justify-between w-full">
                    <span className="text-xs sm:text-sm font-bold text-foreground">
                      {cell.dayNum}
                    </span>
                    {status && <span className={`w-2 h-2 rounded-full ${badgeColor}`} />}
                  </div>

                  {dayData && isConfirmed ? (
                    <div className="text-[10px] text-muted-foreground hidden sm:block truncate">
                      {String(dayData.total_containers_counted)} pcs (
                      {String(dayData.total_sellable_packaging_qty)} pkg)
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Selected Day Details Card */}
      {selectedDay && (
        <div className="bg-card border border-border rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-foreground">
              Audit Details for {selectedDay.audit_date}
            </h3>
            <Badge
              variant={
                selectedDay.status === 'CONFIRMED'
                  ? 'success'
                  : selectedDay.status === 'LATE'
                    ? 'warning'
                    : selectedDay.status === 'MISSED'
                      ? 'danger'
                      : 'default'
              }
            >
              {selectedDay.status}
            </Badge>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-background border border-border rounded p-2.5">
              <span className="text-muted-foreground block">Confirmed</span>
              <span className="font-semibold text-foreground">
                {selectedDay.confirmed ? 'Yes' : 'No'}
              </span>
            </div>

            <div className="bg-background border border-border rounded p-2.5">
              <span className="text-muted-foreground block">DMT Pieces Counted</span>
              <span className="font-semibold text-foreground">
                {selectedDay.total_containers_counted} pcs
              </span>
            </div>

            <div className="bg-background border border-border rounded p-2.5">
              <span className="text-muted-foreground block">Sellable Packaging</span>
              <span className="font-semibold text-foreground">
                {selectedDay.total_sellable_packaging_qty} pcs
              </span>
            </div>

            <div className="bg-background border border-border rounded p-2.5">
              <span className="text-muted-foreground block">Late Entry</span>
              <span className="font-semibold text-foreground">
                {selectedDay.is_late ? 'Yes' : 'No'}
              </span>
            </div>
          </div>

          {selectedDay.remarks && (
            <p className="text-xs text-muted-foreground bg-background border border-border rounded p-2.5">
              <span className="font-medium text-foreground">Remarks: </span>
              {selectedDay.remarks}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
