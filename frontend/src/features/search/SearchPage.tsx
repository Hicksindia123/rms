import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  QrCode,
  ArrowRight,
  Clock,
  FileText,
  Truck,
  Box,
  FileCheck,
  Users,
  Package,
} from 'lucide-react';
import { Button, Input, Badge, EmptyState, LoadingState } from '@/components/ui';
import { searchApi, type SearchResponse } from './api';
import { QrScanModal } from './QrScanModal';

interface SearchPageProps {
  initialQuery?: string;
  onNavigate: (route: string) => void;
}

export function SearchPage({ initialQuery = '', onNavigate }: SearchPageProps) {
  const [query, setQuery] = useState(initialQuery);
  const [activeGroup, setActiveGroup] = useState<string>('ALL');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const performSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await searchApi.globalSearch(q.trim(), 20);
      setResults(resp);
    } catch {
      setError('Failed to perform search. Please check your network.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Run the search for `initialQuery` (on mount and whenever the route's ?q= changes).
  // The synchronous part (loading on, error cleared) is applied during render when the
  // prop changes; the effect only sets state from the async callbacks.
  const [syncedQuery, setSyncedQuery] = useState<string | null>(null);
  if (syncedQuery !== initialQuery) {
    setSyncedQuery(initialQuery);
    if (initialQuery) {
      if (initialQuery.trim()) {
        setLoading(true);
        setError(null);
      } else {
        setResults(null);
      }
    }
  }

  useEffect(() => {
    const q = initialQuery.trim();
    if (!q) return;
    searchApi.globalSearch(q, 20).then(
      (resp) => {
        setResults(resp);
        setLoading(false);
      },
      () => {
        setError('Failed to perform search. Please check your network.');
        setLoading(false);
      },
    );
  }, [initialQuery]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void performSearch(query);
  };

  const directMatch = results?.direct_match;

  const filteredGroups = results
    ? activeGroup === 'ALL'
      ? results.groups
      : results.groups.filter((g) => g.type === activeGroup)
    : [];

  const getGroupIcon = (type: string) => {
    switch (type) {
      case 'GOODS_SLIP':
        return <Truck size={16} />;
      case 'PARTY':
        return <Users size={16} />;
      case 'DOCUMENT':
        return <FileText size={16} />;
      case 'CREDIT_NOTE':
        return <FileCheck size={16} />;
      case 'TRANSFER':
      case 'STORE_ISSUE':
      case 'DISPATCH':
        return <Package size={16} />;
      case 'BATCH':
      case 'CONTAINER':
        return <Box size={16} />;
      default:
        return <FileText size={16} />;
    }
  };

  return (
    <div
      style={{
        maxWidth: '1000px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
            Global Search
          </h1>
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem', color: '#64748b' }}>
            Instant search across Goods Slips, Parties, Documents, Credit Notes, Batches, and
            Containers
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            setScanModalOpen(true);
          }}
        >
          <QrCode size={16} style={{ marginRight: '0.5rem' }} /> Scan QR / Barcode
        </Button>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <span
            style={{
              position: 'absolute',
              left: '0.875rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: '#94a3b8',
              display: 'flex',
            }}
          >
            <Search size={18} />
          </span>
          <Input
            type="text"
            placeholder="Search by GS number, party, docket, CN number, batch, container..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            style={{ paddingLeft: '2.5rem', height: '42px', fontSize: '0.9375rem' }}
            autoFocus
          />
        </div>
        <Button type="submit" isLoading={loading} style={{ height: '42px', padding: '0 1.25rem' }}>
          Search
        </Button>
      </form>

      {/* Direct Match Banner */}
      {directMatch && (
        <div
          style={{
            backgroundColor: '#eef3ff',
            border: '1px solid #bfd0ff',
            borderRadius: '8px',
            padding: '1rem 1.25rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            cursor: 'pointer',
          }}
          onClick={() => {
            onNavigate(directMatch.route);
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span
              style={{
                backgroundColor: '#2a47f0',
                color: '#fff',
                borderRadius: '6px',
                padding: '0.35rem 0.6rem',
                fontSize: '0.75rem',
                fontWeight: 600,
              }}
            >
              EXACT MATCH
            </span>
            <div>
              <div style={{ fontWeight: 600, color: '#212e88' }}>{directMatch.title}</div>
              {directMatch.subtitle && (
                <div style={{ fontSize: '0.8125rem', color: '#3f63fb' }}>
                  {directMatch.subtitle}
                </div>
              )}
            </div>
          </div>
          <Button
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onNavigate(directMatch.route);
            }}
          >
            Open <ArrowRight size={14} style={{ marginLeft: '0.25rem' }} />
          </Button>
        </div>
      )}

      {/* Meta details & Filter Pills */}
      {results && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => {
                setActiveGroup('ALL');
              }}
              style={{
                padding: '0.35rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: activeGroup === 'ALL' ? '#2a47f0' : '#cbd5e1',
                backgroundColor: activeGroup === 'ALL' ? '#2a47f0' : '#fff',
                color: activeGroup === 'ALL' ? '#fff' : '#334155',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              All ({results.total})
            </button>
            {results.groups.map((g) => (
              <button
                key={g.type}
                type="button"
                onClick={() => {
                  setActiveGroup(g.type);
                }}
                style={{
                  padding: '0.35rem 0.75rem',
                  borderRadius: '6px',
                  border: '1px solid',
                  borderColor: activeGroup === g.type ? '#2a47f0' : '#cbd5e1',
                  backgroundColor: activeGroup === g.type ? '#2a47f0' : '#fff',
                  color: activeGroup === g.type ? '#fff' : '#334155',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                }}
              >
                {getGroupIcon(g.type)}
                {g.label} ({g.items.length})
              </button>
            ))}
          </div>

          <div
            style={{
              fontSize: '0.75rem',
              color: '#64748b',
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
            }}
          >
            <Clock size={13} />
            <span>
              Found {results.total} results in {results.search_time_ms ?? results.took_ms} ms
            </span>
          </div>
        </div>
      )}

      {/* Loading & Error States */}
      {loading && <LoadingState label="Searching records..." />}
      {error && <div style={{ color: '#dc2626', fontSize: '0.875rem' }}>{error}</div>}

      {/* Search Result Lists */}
      {!loading && results && results.total === 0 && (
        <EmptyState
          title={`No results for "${query}"`}
          hint="Try checking for typos or searching by phone number, vehicle number, or container barcode."
        />
      )}

      {!loading &&
        filteredGroups.map((group) => (
          <div
            key={group.type}
            style={{
              backgroundColor: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '0.75rem 1rem',
                backgroundColor: '#f8fafc',
                borderBottom: '1px solid #e2e8f0',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                fontWeight: 600,
                color: '#334155',
                fontSize: '0.875rem',
              }}
            >
              {getGroupIcon(group.type)}
              <span>{group.label}</span>
              <span
                style={{
                  fontSize: '0.75rem',
                  backgroundColor: '#e2e8f0',
                  color: '#475569',
                  padding: '0.1rem 0.4rem',
                  borderRadius: '999px',
                  marginLeft: 'auto',
                }}
              >
                {group.items.length}
              </span>
            </div>

            <div>
              {group.items.map((item) => (
                <div
                  key={item.id}
                  onClick={() => {
                    onNavigate(item.route);
                  }}
                  style={{
                    padding: '0.875rem 1rem',
                    borderBottom: '1px solid #f1f5f9',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    cursor: 'pointer',
                    transition: 'background-color 0.1s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#f8fafc';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#fff';
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontWeight: 600, color: '#1e293b' }}>{item.title}</span>
                      {item.badge && <Badge variant="neutral">{item.badge}</Badge>}
                    </div>
                    {item.subtitle && (
                      <div style={{ fontSize: '0.8125rem', color: '#64748b' }}>{item.subtitle}</div>
                    )}
                  </div>
                  <ArrowRight size={16} color="#94a3b8" />
                </div>
              ))}
            </div>
          </div>
        ))}

      <QrScanModal
        isOpen={scanModalOpen}
        onClose={() => {
          setScanModalOpen(false);
        }}
        onNavigate={onNavigate}
      />
    </div>
  );
}
