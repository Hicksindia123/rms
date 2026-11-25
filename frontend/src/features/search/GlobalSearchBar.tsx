import { useCallback, useEffect, useRef, useState } from 'react';
import { QrCode, Search, X } from 'lucide-react';

import { Badge } from '@/components/ui';
import { searchApi, type SearchResponse, type SearchResultItem } from './api';

interface Props {
  onNavigate: (route: string) => void;
  onOpenQrScanner?: () => void;
}

export function GlobalSearchBar({ onNavigate, onOpenQrScanner }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceTimer = useRef<number | null>(null);

  // Flattened results for keyboard navigation
  const flatItems: SearchResultItem[] = data?.groups.flatMap((g) => g.items) ?? [];

  const performSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await searchApi.search(q.trim());
      setData(res);
      setSelectedIndex(-1);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setOpen(true);

    if (debounceTimer.current) window.clearTimeout(debounceTimer.current);
    debounceTimer.current = window.setTimeout(() => {
      void performSearch(val);
    }, 200);
  };

  const handleSelect = (item: SearchResultItem) => {
    setOpen(false);
    setQuery('');
    onNavigate(item.route);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (e.key === 'ArrowDown') setOpen(true);
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev < flatItems.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : flatItems.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (data?.direct_route) {
        setOpen(false);
        setQuery('');
        onNavigate(data.direct_route);
      } else if (selectedIndex >= 0 && selectedIndex < flatItems.length) {
        const item = flatItems[selectedIndex];
        if (item) handleSelect(item);
      } else if (flatItems.length > 0 && flatItems[0]) {
        handleSelect(flatItems[0]);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  // Global hotkey: '/' or 'Ctrl+K' focuses the search bar
  useEffect(() => {
    const onGlobalKeyDown = (e: KeyboardEvent) => {
      if (
        (e.key === '/' &&
          (e.target as HTMLElement).tagName !== 'INPUT' &&
          (e.target as HTMLElement).tagName !== 'TEXTAREA') ||
        (e.key.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey))
      ) {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onGlobalKeyDown);
    return () => {
      window.removeEventListener('keydown', onGlobalKeyDown);
    };
  }, []);

  // Click outside listener
  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: '100%',
        maxWidth: '380px',
      }}
    >
      <div
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          border: '1px solid rgba(255, 255, 255, 0.2)',
          padding: '0 0.5rem',
          height: '36px',
        }}
      >
        <Search size={16} style={{ color: '#94a3b8', flexShrink: 0 }} aria-hidden="true" />
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open && !!data}
          aria-autocomplete="list"
          aria-label="Global search across Goods Slips, parties, documents, vouchers and containers"
          placeholder="Search anything... (/)"
          value={query}
          onChange={handleChange}
          onFocus={() => {
            if (query.trim()) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          style={{
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#f8fafc',
            width: '100%',
            padding: '0 0.5rem',
            fontSize: '0.875rem',
          }}
        />
        {query ? (
          <button
            type="button"
            aria-label="Clear search query"
            onClick={() => {
              setQuery('');
              setData(null);
              setOpen(false);
              inputRef.current?.focus();
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              padding: '0.25rem',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <X size={14} />
          </button>
        ) : null}
        {onOpenQrScanner ? (
          <button
            type="button"
            aria-label="Scan QR or barcode"
            title="Scan QR / Barcode"
            onClick={onOpenQrScanner}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#cbd5e1',
              cursor: 'pointer',
              padding: '0.25rem',
              marginLeft: '0.25rem',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <QrCode size={16} />
          </button>
        ) : null}
      </div>

      {/* Results Dropdown */}
      {open && query.trim() ? (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            right: 0,
            background: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5)',
            maxHeight: '420px',
            overflowY: 'auto',
            zIndex: 1000,
            color: '#f8fafc',
            padding: '0.5rem 0',
          }}
        >
          {loading ? (
            <div
              style={{
                padding: '1rem',
                textAlign: 'center',
                color: '#94a3b8',
                fontSize: '0.875rem',
              }}
            >
              Searching...
            </div>
          ) : data && data.total > 0 ? (
            <>
              {data.is_qr_match && data.direct_route ? (
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    margin: '0.25rem 0.5rem',
                    background: 'rgba(56, 189, 248, 0.15)',
                    border: '1px solid #38bdf8',
                    borderRadius: '6px',
                    fontSize: '0.8125rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span>Direct QR match found! Press Enter to view.</span>
                  <Badge variant="info">Direct Match</Badge>
                </div>
              ) : null}

              {data.groups.map((group) => (
                <div key={group.type} style={{ marginBottom: '0.5rem' }}>
                  <div
                    style={{
                      fontSize: '0.6875rem',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: '#94a3b8',
                      padding: '0.25rem 0.75rem',
                    }}
                  >
                    {group.label} ({group.count})
                  </div>
                  {group.items.map((item) => {
                    // Position in flatItems (same object references), so keyboard and
                    // mouse selection share one index without mutating during render.
                    const itemIndex = flatItems.indexOf(item);
                    const isSelected = itemIndex === selectedIndex;
                    return (
                      <div
                        key={item.id}
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => {
                          handleSelect(item);
                        }}
                        onMouseEnter={() => {
                          setSelectedIndex(itemIndex);
                        }}
                        style={{
                          padding: '0.5rem 0.75rem',
                          cursor: 'pointer',
                          background: isSelected ? 'rgba(255, 255, 255, 0.1)' : 'transparent',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '0.5rem',
                        }}
                      >
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          <div style={{ fontWeight: 600, fontSize: '0.875rem', color: '#f8fafc' }}>
                            {item.title}
                          </div>
                          {item.subtitle ? (
                            <div
                              style={{
                                fontSize: '0.75rem',
                                color: '#94a3b8',
                                marginTop: '0.125rem',
                              }}
                            >
                              {item.subtitle}
                            </div>
                          ) : null}
                        </div>
                        {item.badge ? (
                          <Badge variant={item.badge_variant ?? 'neutral'}>{item.badge}</Badge>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ))}
              <div
                style={{
                  padding: '0.375rem 0.75rem',
                  borderTop: '1px solid #334155',
                  fontSize: '0.6875rem',
                  color: '#64748b',
                  textAlign: 'right',
                }}
              >
                {data.total} result{data.total === 1 ? '' : 's'} in {data.took_ms} ms
              </div>
            </>
          ) : (
            <div
              style={{
                padding: '1rem',
                textAlign: 'center',
                color: '#94a3b8',
                fontSize: '0.875rem',
              }}
            >
              No matches found for &quot;{query}&quot;
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
