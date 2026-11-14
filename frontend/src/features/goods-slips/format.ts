/** System codes shown as words ("GATE_CREATED" → "Gate created"); no business labels invented. */
export function humanize(code: string | null | undefined): string {
  if (!code) return '';
  const words = code.toLowerCase().split('_').filter(Boolean).join(' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** A calendar date ("2026-11-12" → "12 Nov 2026"), shown without any timezone shift. */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '';
  return new Date(`${isoDate.slice(0, 10)}T00:00:00Z`).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export function age(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${String(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${String(hours)}h`;
  return `${String(Math.floor(hours / 24))}d`;
}
