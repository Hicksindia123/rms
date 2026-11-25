import { useCallback, useState } from 'react';
import { Bookmark } from 'lucide-react';
import { Button, Modal, Input } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { viewsApi, type SavedView, type SavedViewIn } from './api';

interface SavedViewSelectorProps {
  resourceCode: string;
  currentFilters: Record<string, unknown>;
  onSelectView: (view: SavedView) => void;
  selectedViewId?: string | null;
}

export function SavedViewSelector({
  resourceCode,
  currentFilters,
  onSelectView,
  selectedViewId,
}: SavedViewSelectorProps) {
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [newViewName, setNewViewName] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);

  // A failed load leaves the list empty (only "Default View"), as before.
  const fetchViews = useCallback(() => viewsApi.fetchSavedViews(resourceCode), [resourceCode]);
  const { data: viewsData, setData: setViews } = useApiQuery(fetchViews);
  const views: SavedView[] = viewsData ?? [];

  const handleCreate = async () => {
    if (!newViewName.trim()) return;
    setSaving(true);
    try {
      const payload: SavedViewIn = {
        resource_code: resourceCode,
        name: newViewName.trim(),
        filters: currentFilters,
        is_default: isDefault,
      };
      const created = await viewsApi.createSavedView(payload);
      setSaveModalOpen(false);
      setNewViewName('');
      setIsDefault(false);
      setViews(await viewsApi.fetchSavedViews(resourceCode));
      onSelectView(created);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
        <select
          value={selectedViewId || ''}
          onChange={(e) => {
            const v = views.find((item) => item.id === e.target.value);
            if (v) onSelectView(v);
          }}
          style={{
            height: '36px',
            borderRadius: '6px',
            border: '1px solid #cbd5e1',
            padding: '0 2rem 0 0.75rem',
            fontSize: '0.8125rem',
            backgroundColor: '#fff',
            cursor: 'pointer',
            minWidth: '150px',
          }}
        >
          <option value="">Default View</option>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name} {v.is_default ? '★' : ''}
            </option>
          ))}
        </select>
      </div>

      <Button
        variant="secondary"
        size="sm"
        onClick={() => {
          setSaveModalOpen(true);
        }}
        title="Save current filters as a view preset"
      >
        <Bookmark size={14} style={{ marginRight: '0.25rem' }} /> Save View
      </Button>

      {saveModalOpen && (
        <Modal
          isOpen={true}
          onClose={() => {
            setSaveModalOpen(false);
          }}
          title="Save Current View Preset"
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                View Name
              </label>
              <Input
                type="text"
                placeholder="e.g. Inward Pendencies, High Value Returns..."
                value={newViewName}
                onChange={(e) => {
                  setNewViewName(e.target.value);
                }}
                autoFocus
              />
            </div>

            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                fontSize: '0.8125rem',
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => {
                  setIsDefault(e.target.checked);
                }}
              />
              <span>Set as my default view for this page</span>
            </label>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.5rem',
                marginTop: '0.5rem',
              }}
            >
              <Button
                variant="secondary"
                onClick={() => {
                  setSaveModalOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  void handleCreate();
                }}
                isLoading={saving}
                disabled={!newViewName.trim()}
              >
                Save Preset
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
