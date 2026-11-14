import React, { useState, useEffect } from 'react';
import type { OptionSet, OptionItem, AllowedStatus, SystemBehavior } from './types';
import { optionsApi } from '@/lib/api/configApi';
import { Button, Badge, Modal, Input, Textarea, Select, Checkbox } from '@/components/ui';

export const OptionSetsManager: React.FC = () => {
  const [optionSets, setOptionSets] = useState<OptionSet[]>([]);
  const [selectedSetId, setSelectedSetId] = useState<string>('');
  const [currentSet, setCurrentSet] = useState<OptionSet | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Edit / Add Item modal state
  const [editingItem, setEditingItem] = useState<OptionItem | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // New item form state
  const [newItem, setNewItem] = useState<{
    code: string;
    label: string;
    sort_order: number;
    is_active: boolean;
    allowed_status: AllowedStatus;
    system_behavior: SystemBehavior;
    rule_text: string;
    next_action_text: string;
  }>({
    code: '',
    label: '',
    sort_order: 10,
    is_active: true,
    allowed_status: 'YES',
    system_behavior: 'ALLOW',
    rule_text: '',
    next_action_text: '',
  });

  // Load option sets list
  useEffect(() => {
    let ignore = false;
    optionsApi
      .listSets()
      .then((sets) => {
        if (!ignore) {
          setOptionSets(sets);
          if (sets.length > 0 && !selectedSetId) {
            const first = sets[0];
            if (first) {
              setSelectedSetId(first.id);
            }
          }
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setError((err as Error).message || 'Failed to load option sets');
          setIsLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedSetId]);

  // Load selected option set details
  useEffect(() => {
    if (!selectedSetId) return;
    let ignore = false;
    optionsApi
      .getSet(selectedSetId)
      .then((fullSet) => {
        if (!ignore) {
          setCurrentSet(fullSet);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setError((err as Error).message || 'Failed to load option set details');
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedSetId, refreshTrigger]);

  const handleEditClick = (item: OptionItem) => {
    setEditingItem({ ...item });
    setReason('');
    setModalError(null);
    setIsEditModalOpen(true);
  };

  const handleSaveEdit = async () => {
    if (!editingItem) return;
    setModalError(null);

    // G-05 validation: system_behavior=HAZARD cannot have allowed_status=YES
    if (editingItem.system_behavior === 'HAZARD' && editingItem.allowed_status === 'YES') {
      setModalError('Guard G-05: Hazardous items cannot be set to allowed_status = YES');
      return;
    }

    // Changing NO -> YES/CONDITIONAL requires mandatory reason
    const originalItem = currentSet?.items?.find((i) => i.id === editingItem.id);
    const wasNo = originalItem?.allowed_status === 'NO';
    const isNowAllowed =
      editingItem.allowed_status === 'YES' || editingItem.allowed_status === 'CONDITIONAL';

    if (wasNo && isNowAllowed && !reason.trim()) {
      setModalError(
        'A reason is mandatory when changing allowed status from NO to YES or CONDITIONAL (G-05 audit log requirement).',
      );
      return;
    }

    setIsSubmitting(true);
    try {
      await optionsApi.updateItem(editingItem.id, {
        label: editingItem.label,
        sort_order: editingItem.sort_order,
        is_active: editingItem.is_active,
        allowed_status: editingItem.allowed_status,
        rule_text: editingItem.rule_text ?? null,
        next_action_text: editingItem.next_action_text ?? null,
        remarks: editingItem.remarks ?? null,
        system_behavior: editingItem.system_behavior,
        reason: reason.trim() ? reason.trim() : null,
      });

      setIsEditModalOpen(false);
      setEditingItem(null);
      setRefreshTrigger((prev) => prev + 1);
    } catch (err: unknown) {
      setModalError((err as Error).message || 'Failed to save changes');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveNew = async () => {
    if (!selectedSetId) return;
    setModalError(null);

    if (!newItem.code.trim()) {
      setModalError('Code is required');
      return;
    }
    if (!newItem.label.trim()) {
      setModalError('Label is required');
      return;
    }
    if (newItem.system_behavior === 'HAZARD' && newItem.allowed_status === 'YES') {
      setModalError('Guard G-05: Hazardous items cannot be set to allowed_status = YES');
      return;
    }

    setIsSubmitting(true);
    try {
      await optionsApi.createItem(selectedSetId, {
        code: newItem.code.trim().toUpperCase(),
        label: newItem.label.trim(),
        sort_order: newItem.sort_order,
        is_active: newItem.is_active,
        allowed_status: newItem.allowed_status,
        system_behavior: newItem.system_behavior,
        rule_text: newItem.rule_text.trim() ? newItem.rule_text.trim() : null,
        next_action_text: newItem.next_action_text.trim() ? newItem.next_action_text.trim() : null,
      });

      setIsAddModalOpen(false);
      setNewItem({
        code: '',
        label: '',
        sort_order: 10,
        is_active: true,
        allowed_status: 'YES',
        system_behavior: 'ALLOW',
        rule_text: '',
        next_action_text: '',
      });
      setRefreshTrigger((prev) => prev + 1);
    } catch (err: unknown) {
      setModalError((err as Error).message || 'Failed to create item');
    } finally {
      setIsSubmitting(false);
    }
  };

  const originalItem = currentSet?.items?.find((i) => i.id === editingItem?.id);
  const requiresReason =
    originalItem?.allowed_status === 'NO' &&
    (editingItem?.allowed_status === 'YES' || editingItem?.allowed_status === 'CONDITIONAL');

  return (
    <div
      className="option-sets-manager"
      style={{ padding: '1rem', width: '100%', maxWidth: '1200px', margin: '0 auto' }}
    >
      <header style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, margin: '0 0 0.5rem 0' }}>
          Option Sets & Dropdown Catalogue
        </h2>
        <p style={{ margin: 0, color: 'var(--color-fg-muted)', fontSize: '0.9375rem' }}>
          Manage dropdown values, system behaviors, and G-05 hazard guards across the RMS workflow.
        </p>
      </header>

      {error && (
        <div
          role="alert"
          style={{
            padding: '0.75rem 1rem',
            marginBottom: '1rem',
            backgroundColor: '#fee2e2',
            color: '#b91c1c',
            borderRadius: 'var(--radius-md)',
            border: '1px solid #f87171',
          }}
        >
          {error}
        </div>
      )}

      {/* Option set selector bar */}
      <div
        style={{
          display: 'flex',
          gap: '1rem',
          alignItems: 'center',
          backgroundColor: '#ffffff',
          padding: '1rem',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-sm)',
          marginBottom: '1.5rem',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: 1, minWidth: '240px' }}>
          <label
            htmlFor="option-set-select"
            style={{
              display: 'block',
              fontSize: '0.875rem',
              fontWeight: 600,
              marginBottom: '0.25rem',
            }}
          >
            Select Option Set ({optionSets.length} sets):
          </label>
          <select
            id="option-set-select"
            className="select"
            value={selectedSetId}
            onChange={(e) => {
              setSelectedSetId(e.target.value);
            }}
            disabled={isLoading}
          >
            {Array.isArray(optionSets)
              ? optionSets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.code}) - {s.items_count ?? 0} items
                  </option>
                ))
              : null}
          </select>
        </div>

        {currentSet && (
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end' }}>
            <Button
              variant="primary"
              size="md"
              onClick={() => {
                setModalError(null);
                setIsAddModalOpen(true);
              }}
            >
              + Add Option Item
            </Button>
          </div>
        )}
      </div>

      {/* Option set items list */}
      {currentSet && (
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-sm)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '1rem 1.25rem',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '0.5rem',
            }}
          >
            <div>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>
                {currentSet.name}
              </h2>
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-fg-muted)' }}>
                Code: <code>{currentSet.code}</code> | Scope: {currentSet.scope || 'ALL'}
              </span>
            </div>
            <Badge variant="info">{(currentSet.items || []).length} Options</Badge>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ backgroundColor: 'var(--color-bg-subtle)', textAlign: 'left' }}>
                  <th style={{ padding: '0.75rem 1rem' }}>Sort</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Code</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Label</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Allowed Status</th>
                  <th style={{ padding: '0.75rem 1rem' }}>System Behavior</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Active</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Rule Text</th>
                  <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(currentSet.items || []).length === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
                      style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--color-fg-muted)',
                      }}
                    >
                      No option items configured for this set yet.
                    </td>
                  </tr>
                ) : (
                  (currentSet.items || [])
                    .sort((a, b) => a.sort_order - b.sort_order)
                    .map((item) => (
                      <tr
                        key={item.id}
                        style={{
                          borderBottom: '1px solid var(--color-border)',
                          backgroundColor: item.is_active ? 'transparent' : '#f9fafb',
                        }}
                      >
                        <td style={{ padding: '0.75rem 1rem', color: 'var(--color-fg-muted)' }}>
                          {item.sort_order}
                        </td>
                        <td style={{ padding: '0.75rem 1rem' }}>
                          <code style={{ fontWeight: 600 }}>{item.code}</code>
                        </td>
                        <td style={{ padding: '0.75rem 1rem', fontWeight: 500 }}>{item.label}</td>
                        <td style={{ padding: '0.75rem 1rem' }}>
                          {item.allowed_status === 'YES' && <Badge variant="success">YES</Badge>}
                          {item.allowed_status === 'NO' && <Badge variant="danger">NO</Badge>}
                          {item.allowed_status === 'CONDITIONAL' && (
                            <Badge variant="warning">CONDITIONAL</Badge>
                          )}
                        </td>
                        <td style={{ padding: '0.75rem 1rem' }}>
                          <Badge
                            variant={
                              item.system_behavior === 'HAZARD'
                                ? 'danger'
                                : item.system_behavior === 'SCRAP'
                                  ? 'warning'
                                  : 'neutral'
                            }
                          >
                            {item.system_behavior}
                          </Badge>
                        </td>
                        <td style={{ padding: '0.75rem 1rem' }}>
                          {item.is_active ? (
                            <span style={{ color: '#166534', fontWeight: 600 }}>Active</span>
                          ) : (
                            <span style={{ color: '#4b5563', fontWeight: 500 }}>Inactive</span>
                          )}
                        </td>
                        <td
                          style={{
                            padding: '0.75rem 1rem',
                            maxWidth: '220px',
                            color: item.rule_text ? '#b45309' : 'var(--color-fg-muted)',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {item.rule_text || '—'}
                        </td>
                        <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              handleEditClick(item);
                            }}
                          >
                            Edit
                          </Button>
                        </td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Edit Option Item Modal */}
      {editingItem && (
        <Modal
          isOpen={isEditModalOpen}
          onClose={() => {
            setIsEditModalOpen(false);
          }}
          title={`Edit Option: ${editingItem.code}`}
          footer={
            <>
              <Button
                variant="outline"
                size="md"
                onClick={() => {
                  setIsEditModalOpen(false);
                }}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="md"
                onClick={() => {
                  void handleSaveEdit();
                }}
                isLoading={isSubmitting}
              >
                Save Changes
              </Button>
            </>
          }
        >
          {modalError && (
            <div
              style={{
                padding: '0.75rem',
                marginBottom: '1rem',
                backgroundColor: '#fee2e2',
                color: '#b91c1c',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.875rem',
              }}
            >
              {modalError}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Option Code (Immutable after creation):
              </label>
              <Input value={editingItem.code} disabled />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Label:
              </label>
              <Input
                value={editingItem.label}
                onChange={(e) => {
                  setEditingItem({ ...editingItem, label: e.target.value });
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    marginBottom: '0.25rem',
                  }}
                >
                  Sort Order:
                </label>
                <Input
                  type="number"
                  value={editingItem.sort_order}
                  onChange={(e) => {
                    setEditingItem({
                      ...editingItem,
                      sort_order: parseInt(e.target.value, 10) || 0,
                    });
                  }}
                />
              </div>

              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    marginBottom: '0.25rem',
                  }}
                >
                  System Behavior:
                </label>
                <Select
                  options={[
                    { value: 'ALLOW', label: 'ALLOW' },
                    { value: 'HAZARD', label: 'HAZARD (G-05 Guarded)' },
                    { value: 'SCRAP', label: 'SCRAP' },
                    { value: 'RTV', label: 'RTV' },
                    { value: 'HOLD', label: 'HOLD' },
                    { value: 'ESCALATE', label: 'ESCALATE' },
                  ]}
                  value={editingItem.system_behavior}
                  onChange={(e) => {
                    setEditingItem({
                      ...editingItem,
                      system_behavior: e.target.value as SystemBehavior,
                    });
                  }}
                />
              </div>
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Allowed Status:
              </label>
              <Select
                options={[
                  {
                    value: 'YES',
                    label: 'YES (Allowed)',
                    disabled: editingItem.system_behavior === 'HAZARD',
                  },
                  { value: 'NO', label: 'NO (Not Allowed)' },
                  { value: 'CONDITIONAL', label: 'CONDITIONAL (Allowed under conditions)' },
                ]}
                value={editingItem.allowed_status}
                onChange={(e) => {
                  setEditingItem({
                    ...editingItem,
                    allowed_status: e.target.value as AllowedStatus,
                  });
                }}
              />
              {editingItem.system_behavior === 'HAZARD' && (
                <p style={{ fontSize: '0.75rem', color: '#dc2626', marginTop: '0.25rem' }}>
                  ⚠️ Guard G-05: System behavior HAZARD strictly forbids allowed_status = YES.
                </p>
              )}
            </div>

            {requiresReason && (
              <div
                style={{
                  backgroundColor: '#fffbeb',
                  border: '1px solid #fde68a',
                  padding: '0.75rem',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    marginBottom: '0.25rem',
                    color: '#92400e',
                  }}
                >
                  Mandatory Audit Reason (Status change NO → {editingItem.allowed_status}):
                </label>
                <Textarea
                  value={reason}
                  onChange={(e) => {
                    setReason(e.target.value);
                  }}
                  placeholder="Enter business justification for overriding the disallowed status..."
                  rows={2}
                />
              </div>
            )}

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Rule Text (Displayed as helper in forms):
              </label>
              <Textarea
                value={editingItem.rule_text || ''}
                onChange={(e) => {
                  setEditingItem({ ...editingItem, rule_text: e.target.value });
                }}
                rows={2}
              />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Next Action Text:
              </label>
              <Input
                value={editingItem.next_action_text || ''}
                onChange={(e) => {
                  setEditingItem({ ...editingItem, next_action_text: e.target.value });
                }}
              />
            </div>

            <div>
              <Checkbox
                id="edit-item-active"
                label="Option is Active (Deactivation hides from new entries only)"
                checked={editingItem.is_active}
                onChange={(e) => {
                  setEditingItem({ ...editingItem, is_active: e.target.checked });
                }}
              />
            </div>
          </div>
        </Modal>
      )}

      {/* Add New Option Item Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => {
          setIsAddModalOpen(false);
        }}
        title={`Add Option to ${currentSet?.name || 'Set'}`}
        footer={
          <>
            <Button
              variant="outline"
              size="md"
              onClick={() => {
                setIsAddModalOpen(false);
              }}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              onClick={() => {
                void handleSaveNew();
              }}
              isLoading={isSubmitting}
            >
              Create Option
            </Button>
          </>
        }
      >
        {modalError && (
          <div
            style={{
              padding: '0.75rem',
              marginBottom: '1rem',
              backgroundColor: '#fee2e2',
              color: '#b91c1c',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.875rem',
            }}
          >
            {modalError}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 600,
                marginBottom: '0.25rem',
              }}
            >
              Option Code (e.g. DIRECT_TRUCK, BATTERY):
            </label>
            <Input
              value={newItem.code}
              onChange={(e) => {
                setNewItem({ ...newItem, code: e.target.value.toUpperCase() });
              }}
              placeholder="UNIQUE_CODE"
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 600,
                marginBottom: '0.25rem',
              }}
            >
              Label:
            </label>
            <Input
              value={newItem.label}
              onChange={(e) => {
                setNewItem({ ...newItem, label: e.target.value });
              }}
              placeholder="User-facing display name"
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Sort Order:
              </label>
              <Input
                type="number"
                value={newItem.sort_order}
                onChange={(e) => {
                  setNewItem({
                    ...newItem,
                    sort_order: parseInt(e.target.value, 10) || 0,
                  });
                }}
              />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                System Behavior:
              </label>
              <Select
                options={[
                  { value: 'ALLOW', label: 'ALLOW' },
                  { value: 'HAZARD', label: 'HAZARD (G-05 Guarded)' },
                  { value: 'SCRAP', label: 'SCRAP' },
                  { value: 'RTV', label: 'RTV' },
                  { value: 'HOLD', label: 'HOLD' },
                  { value: 'ESCALATE', label: 'ESCALATE' },
                ]}
                value={newItem.system_behavior}
                onChange={(e) => {
                  setNewItem({
                    ...newItem,
                    system_behavior: e.target.value as SystemBehavior,
                  });
                }}
              />
            </div>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 600,
                marginBottom: '0.25rem',
              }}
            >
              Allowed Status:
            </label>
            <Select
              options={[
                {
                  value: 'YES',
                  label: 'YES (Allowed)',
                  disabled: newItem.system_behavior === 'HAZARD',
                },
                { value: 'NO', label: 'NO (Disallowed)' },
                { value: 'CONDITIONAL', label: 'CONDITIONAL' },
              ]}
              value={newItem.allowed_status}
              onChange={(e) => {
                setNewItem({
                  ...newItem,
                  allowed_status: e.target.value as AllowedStatus,
                });
              }}
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 600,
                marginBottom: '0.25rem',
              }}
            >
              Rule Text:
            </label>
            <Textarea
              value={newItem.rule_text}
              onChange={(e) => {
                setNewItem({ ...newItem, rule_text: e.target.value });
              }}
              rows={2}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
};
