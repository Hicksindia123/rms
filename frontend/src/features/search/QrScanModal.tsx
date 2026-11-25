import { useState, useRef, useEffect } from 'react';
import { Camera, QrCode, AlertCircle, ArrowRight } from 'lucide-react';
import { Button, Modal, Input } from '@/components/ui';
import { searchApi } from './api';

interface QrScanModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (route: string) => void;
}

export function QrScanModal({ isOpen, onClose, onNavigate }: QrScanModalProps) {
  // Modal renders nothing while closed, so the body remounts (fresh code/error state)
  // every time the modal opens.
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Scan QR Code / Barcode">
      <QrScanBody onClose={onClose} onNavigate={onNavigate} />
    </Modal>
  );
}

function QrScanBody({ onClose, onNavigate }: Omit<QrScanModalProps, 'isOpen'>) {
  const [scannedCode, setScannedCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 150);
    return () => {
      clearTimeout(timer);
    };
  }, []);

  const handleResolve = async (codeToResolve: string) => {
    const raw = codeToResolve.trim();
    if (!raw) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await searchApi.globalSearch(raw, 5);
      if (resp.direct_match) {
        onClose();
        onNavigate(resp.direct_match.route);
        return;
      }
      if (resp.total > 0 && resp.groups.length > 0) {
        // Navigate to search results with query
        onClose();
        onNavigate(`/search?q=${encodeURIComponent(raw)}`);
        return;
      }
      setError(`No record found for barcode / QR: "${raw}"`);
    } catch {
      setError('Search lookup failed. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <p style={{ margin: 0, fontSize: '0.875rem', color: '#64748b' }}>
        Scan a Goods Slip QR tag, Container Barcode, or enter docket/batch code:
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void handleResolve(scannedCode);
        }}
        style={{ display: 'flex', gap: '0.5rem' }}
      >
        <div style={{ position: 'relative', flex: 1 }}>
          <span
            style={{
              position: 'absolute',
              left: '0.75rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: '#94a3b8',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <QrCode size={18} />
          </span>
          <Input
            ref={inputRef}
            type="text"
            placeholder="e.g. GS/2026/00001, CONT-A-01..."
            value={scannedCode}
            onChange={(e) => {
              setScannedCode(e.target.value);
            }}
            style={{ paddingLeft: '2.5rem' }}
            disabled={busy}
            autoFocus
          />
        </div>
        <Button type="submit" isLoading={busy} disabled={!scannedCode.trim()}>
          Go <ArrowRight size={16} style={{ marginLeft: '0.25rem' }} />
        </Button>
      </form>

      <div
        style={{
          border: '2px dashed #cbd5e1',
          borderRadius: '8px',
          padding: '1.5rem',
          textAlign: 'center',
          backgroundColor: '#f8fafc',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.5rem',
        }}
      >
        <Camera size={32} color="#64748b" />
        <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#334155' }}>
          Hardware Scanners Supported
        </div>
        <div style={{ fontSize: '0.75rem', color: '#64748b', maxWidth: '300px' }}>
          Handheld USB or Bluetooth barcode/QR scanners type directly into the field and press Enter
          automatically.
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '0.75rem',
            backgroundColor: '#fef2f2',
            color: '#991b1b',
            borderRadius: '6px',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
