import React, { useState, useEffect, useMemo } from 'react';
import type {
  FormSnapshot,
  FormFieldSnapshot,
  FormDefinitionSummary,
  FormVersionSummary,
  VersionDiffResult,
  ControlType,
} from './types';
import { formsApi, optionsApi } from '@/lib/api/configApi';
import type { OptionSet } from '../options/types';
import { DynamicForm } from '@/components/erp/DynamicForm';
import { RuleBuilder } from './RuleBuilder';
import { Button, Badge, Modal, Input, Textarea, Select, Checkbox } from '@/components/ui';

export const FormBuilder: React.FC = () => {
  const [forms, setForms] = useState<FormDefinitionSummary[]>([]);
  const [selectedFormCode, setSelectedFormCode] = useState<string>('S1_GATE_INWARD');
  const [currentForm, setCurrentForm] = useState<FormSnapshot | null>(null);
  const [versions, setVersions] = useState<FormVersionSummary[]>([]);
  const [optionSets, setOptionSets] = useState<OptionSet[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // View state
  const [activeTab, setActiveTab] = useState<'editor' | 'preview'>('editor');
  const [previewDevice, setPreviewDevice] = useState<'desktop' | 'mobile'>('desktop');

  // Field editing state
  const [editingFieldIndex, setEditingFieldIndex] = useState<number | null>(null);
  const [editingField, setEditingField] = useState<FormFieldSnapshot | null>(null);
  const [isFieldDrawerOpen, setIsFieldDrawerOpen] = useState(false);

  // Publish modal state
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const [changeNotes, setChangeNotes] = useState('');
  const [isPublishing, setIsPublishing] = useState(false);

  // Diff modal state
  const [isDiffModalOpen, setIsDiffModalOpen] = useState(false);
  const [diffResult, setDiffResult] = useState<VersionDiffResult | null>(null);
  const [diffV1, setDiffV1] = useState<number>(1);
  const [diffV2, setDiffV2] = useState<number>(2);

  // Load forms list and option sets on mount
  useEffect(() => {
    let ignore = false;
    Promise.all([formsApi.listForms().catch(() => []), optionsApi.listSets().catch(() => [])])
      .then(([formsList, sets]) => {
        if (!ignore) {
          setForms(formsList);
          setOptionSets(sets);
          if (formsList.length > 0 && !selectedFormCode && formsList[0]) {
            setSelectedFormCode(formsList[0].code);
          }
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setError((err as Error).message || 'Failed to initialize Form Builder');
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedFormCode]);

  // Load selected form version
  useEffect(() => {
    if (!selectedFormCode) return;
    let ignore = false;
    Promise.all([
      formsApi.getPublished(selectedFormCode),
      formsApi.listVersions(selectedFormCode).catch(() => []),
    ])
      .then(([published, vers]) => {
        if (!ignore) {
          setCurrentForm(published);
          setVersions(vers);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setError((err as Error).message || `Failed to load form ${selectedFormCode}`);
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedFormCode]);

  // Create draft version from published
  const handleCreateDraft = async () => {
    if (!selectedFormCode) return;
    setIsLoading(true);
    setError(null);
    try {
      const draft = await formsApi.createDraft(selectedFormCode);
      setCurrentForm(draft);
      const vers = await formsApi.listVersions(selectedFormCode);
      setVersions(vers);
      setSuccessMsg(`Draft v${String(draft.version)} created! You can now edit fields.`);
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to create draft');
    } finally {
      setIsLoading(false);
    }
  };

  // Reorder fields
  const handleMoveField = (index: number, direction: 'up' | 'down') => {
    if (!currentForm) return;
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= currentForm.fields.length) return;

    const newFields = [...currentForm.fields];
    const [moved] = newFields.splice(index, 1);
    if (!moved) return;
    newFields.splice(targetIndex, 0, moved);

    // Update sort orders
    newFields.forEach((f, idx) => {
      f.sort_order = (idx + 1) * 10;
    });

    setCurrentForm({ ...currentForm, fields: newFields });
  };

  // Open field drawer
  const handleEditField = (index: number) => {
    if (!currentForm) return;
    const target = currentForm.fields[index];
    if (!target) return;
    setEditingFieldIndex(index);
    setEditingField({ ...target });
    setIsFieldDrawerOpen(true);
  };

  // Add new field
  const handleAddNewField = () => {
    if (!currentForm) return;
    const nextSort = (currentForm.fields.length + 1) * 10;
    const newField: FormFieldSnapshot = {
      field_key: `custom_field_${String(currentForm.fields.length + 1)}`,
      label: 'New Field',
      control_type: 'text',
      sort_order: nextSort,
      is_core: false,
      is_active: true,
      required: false,
    };
    setEditingFieldIndex(currentForm.fields.length);
    setEditingField(newField);
    setIsFieldDrawerOpen(true);
  };

  // Save edited field into form fields
  const handleSaveField = () => {
    if (!currentForm || !editingField || editingFieldIndex === null) return;
    const newFields = [...currentForm.fields];
    const fieldToSave = { ...editingField };

    // If option set selected, attach option set options if available
    if (fieldToSave.option_set_code) {
      const optSet = optionSets.find((s) => s.code === fieldToSave.option_set_code);
      if (optSet && optSet.items) {
        fieldToSave.options = optSet.items.map((i) => ({
          code: i.code,
          label: i.label,
          sort_order: i.sort_order,
          allowed_status: i.allowed_status,
          rule_text: i.rule_text ?? null,
          is_active: i.is_active,
        }));
      }
    }

    if (editingFieldIndex >= newFields.length) {
      newFields.push(fieldToSave);
    } else {
      newFields[editingFieldIndex] = fieldToSave;
    }

    setCurrentForm({ ...currentForm, fields: newFields });
    setIsFieldDrawerOpen(false);
    setEditingField(null);
    setEditingFieldIndex(null);
  };

  // Delete field (allowed only if not core)
  const handleDeleteField = (index: number) => {
    if (!currentForm) return;
    const field = currentForm.fields[index];
    if (!field) return;
    if (field.is_core) {
      alert('Cannot delete core field bound to workflow tables.');
      return;
    }
    const newFields = currentForm.fields.filter((_, i) => i !== index);
    setCurrentForm({ ...currentForm, fields: newFields });
  };

  // Save draft fields to backend
  const handleSaveDraft = async () => {
    if (!currentForm) return;
    setIsLoading(true);
    setError(null);
    try {
      const updated = await formsApi.updateDraftFields(
        currentForm.form_code,
        currentForm.version,
        currentForm.fields,
      );
      setCurrentForm(updated);
      setSuccessMsg('Draft fields saved successfully.');
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to save draft fields');
    } finally {
      setIsLoading(false);
    }
  };

  // Validate draft
  const handleValidateDraft = async () => {
    if (!currentForm) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await formsApi.validateDraft(currentForm.form_code, currentForm.version);
      if (result.valid) {
        setSuccessMsg('Draft passed all validation checks! Ready to publish.');
      } else {
        setError(`Validation failed: ${result.errors.join(', ')}`);
      }
    } catch (err: unknown) {
      setError((err as Error).message || 'Validation request failed');
    } finally {
      setIsLoading(false);
    }
  };

  // Publish draft
  const handlePublish = async () => {
    if (!currentForm) return;
    setIsPublishing(true);
    setError(null);
    try {
      const published = await formsApi.publishVersion(
        currentForm.form_code,
        currentForm.version,
        changeNotes.trim() || `Published version ${String(currentForm.version)}`,
      );
      setCurrentForm(published);
      const vers = await formsApi.listVersions(currentForm.form_code);
      setVersions(vers);
      setIsPublishModalOpen(false);
      setChangeNotes('');
      setSuccessMsg(`Form version ${String(published.version)} published successfully!`);
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to publish version');
    } finally {
      setIsPublishing(false);
    }
  };

  // View diff
  const handleViewDiff = async () => {
    if (!currentForm) return;
    setIsLoading(true);
    try {
      const diff = await formsApi.diffVersions(currentForm.form_code, diffV1, diffV2);
      setDiffResult(diff);
      setIsDiffModalOpen(true);
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to calculate diff');
    } finally {
      setIsLoading(false);
    }
  };

  // Available field keys for visual rule builder
  const availableFieldKeys = useMemo(() => {
    if (!currentForm) return [];
    return currentForm.fields.map((f) => f.field_key);
  }, [currentForm]);

  return (
    <div
      className="form-builder"
      style={{ padding: '1rem', width: '100%', maxWidth: '1400px', margin: '0 auto' }}
    >
      <header style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, margin: '0 0 0.5rem 0' }}>
          Form Builder & Version Manager
        </h2>
        <p style={{ margin: 0, color: 'var(--color-fg-muted)', fontSize: '0.9375rem' }}>
          Customize workflow step forms, configure conditional visibility, validate drafts, and
          publish version snapshots.
        </p>
      </header>

      {/* Notifications */}
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
      {successMsg && (
        <div
          role="alert"
          style={{
            padding: '0.75rem 1rem',
            marginBottom: '1rem',
            backgroundColor: '#dcfce7',
            color: '#15803d',
            borderRadius: 'var(--radius-md)',
            border: '1px solid #86efac',
          }}
        >
          {successMsg}
        </div>
      )}

      {/* Header controls bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#ffffff',
          padding: '1rem',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-sm)',
          marginBottom: '1.5rem',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div>
            <label
              htmlFor="form-select"
              style={{
                display: 'block',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--color-fg-muted)',
              }}
            >
              Workflow Step Form:
            </label>
            <select
              id="form-select"
              className="select"
              value={selectedFormCode}
              onChange={(e) => {
                setSelectedFormCode(e.target.value);
              }}
              disabled={isLoading}
              style={{ minWidth: '220px' }}
            >
              {Array.isArray(forms)
                ? forms.map((f) => (
                    <option key={f.code} value={f.code}>
                      {f.code} — {f.name}
                    </option>
                  ))
                : null}
            </select>
          </div>

          {currentForm && (
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1rem' }}
            >
              <Badge variant={currentForm.status === 'PUBLISHED' ? 'success' : 'warning'}>
                {currentForm.status} v{currentForm.version}
              </Badge>
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-fg-muted)' }}>
                ({currentForm.fields.length} fields)
              </span>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <div
            style={{
              display: 'flex',
              background: 'var(--color-bg-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '2px',
            }}
          >
            <Button
              variant={activeTab === 'editor' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => {
                setActiveTab('editor');
              }}
            >
              Form Editor
            </Button>
            <Button
              variant={activeTab === 'preview' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => {
                setActiveTab('preview');
              }}
            >
              Live Preview
            </Button>
          </div>

          {currentForm?.status === 'PUBLISHED' && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void handleCreateDraft();
              }}
            >
              + Create New Draft
            </Button>
          )}

          {currentForm?.status === 'DRAFT' && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void handleSaveDraft();
                }}
              >
                Save Draft
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void handleValidateDraft();
                }}
              >
                Validate
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  setIsPublishModalOpen(true);
                }}
              >
                Publish...
              </Button>
            </>
          )}

          {versions.length > 1 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const last = versions[versions.length - 1];
                const first = versions[0];
                setDiffV1(last ? last.version : 1);
                setDiffV2(first ? first.version : 2);
                void handleViewDiff();
              }}
            >
              Diff Versions
            </Button>
          )}
        </div>
      </div>

      {/* Main Tab Content */}
      {activeTab === 'editor' ? (
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-sm)',
            padding: '1.25rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '1rem',
            }}
          >
            <div>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>
                Form Fields Configuration
              </h2>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-fg-muted)', margin: 0 }}>
                {currentForm?.status === 'PUBLISHED'
                  ? 'Viewing published snapshot. Create a draft to edit or reorder fields.'
                  : 'Editing draft version. Save fields when done and validate before publishing.'}
              </p>
            </div>

            {currentForm?.status === 'DRAFT' && (
              <Button variant="primary" size="sm" onClick={handleAddNewField}>
                + Add Custom Field
              </Button>
            )}
          </div>

          {/* Fields list table */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ backgroundColor: 'var(--color-bg-subtle)', textAlign: 'left' }}>
                  <th style={{ padding: '0.625rem 0.75rem', width: '50px' }}>Order</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Field Key</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Label</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Section</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Control Type</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Status</th>
                  <th style={{ padding: '0.625rem 0.75rem' }}>Conditional Rules</th>
                  <th style={{ padding: '0.625rem 0.75rem', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const fieldsList = currentForm?.fields ?? [];
                  const total = fieldsList.length;

                  return fieldsList.map((field, idx) => (
                    <tr
                      key={field.field_key}
                      style={{
                        borderBottom: '1px solid var(--color-border)',
                        backgroundColor: field.is_active === false ? '#f3f4f6' : 'transparent',
                      }}
                    >
                      <td style={{ padding: '0.625rem 0.75rem' }}>
                        {currentForm?.status === 'DRAFT' ? (
                          <div style={{ display: 'flex', gap: '2px' }}>
                            <button
                              type="button"
                              disabled={idx === 0}
                              onClick={() => {
                                handleMoveField(idx, 'up');
                              }}
                              style={{
                                cursor: idx === 0 ? 'default' : 'pointer',
                                border: 'none',
                                background: 'none',
                              }}
                            >
                              ▲
                            </button>
                            <button
                              type="button"
                              disabled={idx === total - 1}
                              onClick={() => {
                                handleMoveField(idx, 'down');
                              }}
                              style={{
                                cursor: idx === total - 1 ? 'default' : 'pointer',
                                border: 'none',
                                background: 'none',
                              }}
                            >
                              ▼
                            </button>
                          </div>
                        ) : (
                          field.sort_order
                        )}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem' }}>
                        <code style={{ fontWeight: 600 }}>{field.field_key}</code>
                        {field.is_core && (
                          <Badge
                            variant="neutral"
                            style={{ marginLeft: '0.5rem', fontSize: '0.6875rem' }}
                          >
                            CORE
                          </Badge>
                        )}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', fontWeight: 500 }}>
                        {field.label}
                        {field.required && <span style={{ color: 'var(--color-danger)' }}> *</span>}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', color: 'var(--color-fg-muted)' }}>
                        {field.section || 'General'}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem' }}>
                        <Badge variant="info">{field.control_type}</Badge>
                        {field.option_set_code && (
                          <span
                            style={{
                              fontSize: '0.75rem',
                              display: 'block',
                              color: 'var(--color-fg-muted)',
                            }}
                          >
                            set: {field.option_set_code}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem' }}>
                        {field.is_active === false ? (
                          <span style={{ color: '#9ca3af' }}>Inactive</span>
                        ) : (
                          <span style={{ color: '#15803d' }}>Active</span>
                        )}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', fontSize: '0.75rem' }}>
                        {field.visible_when ? (
                          <span style={{ color: '#0369a1', display: 'block' }}>👁️ conditional</span>
                        ) : null}
                        {field.required_when ? (
                          <span style={{ color: '#b45309', display: 'block' }}>⚠️ req-when</span>
                        ) : null}
                        {!field.visible_when && !field.required_when && '—'}
                      </td>
                      <td style={{ padding: '0.625rem 0.75rem', textAlign: 'right' }}>
                        <div
                          style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.375rem' }}
                        >
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              handleEditField(idx);
                            }}
                          >
                            Edit
                          </Button>
                          {currentForm?.status === 'DRAFT' && !field.is_core && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                handleDeleteField(idx);
                              }}
                              style={{ color: 'var(--color-danger)' }}
                            >
                              Delete
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Live Preview Tab */
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-sm)',
            padding: '1.25rem',
          }}
        >
          {/* Device viewport toggle */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '1.5rem',
              paddingBottom: '1rem',
              borderBottom: '1px solid var(--color-border)',
            }}
          >
            <div>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>
                Live Form Preview: {currentForm?.name}
              </h2>
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-fg-muted)', margin: 0 }}>
                Test conditional visibility rules and submission validation live.
              </p>
            </div>

            <div
              style={{
                display: 'flex',
                background: 'var(--color-bg-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '2px',
              }}
            >
              <Button
                variant={previewDevice === 'desktop' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => {
                  setPreviewDevice('desktop');
                }}
              >
                Desktop Full
              </Button>
              <Button
                variant={previewDevice === 'mobile' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => {
                  setPreviewDevice('mobile');
                }}
              >
                Mobile (360px)
              </Button>
            </div>
          </div>

          {currentForm && (
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                backgroundColor: previewDevice === 'mobile' ? '#f3f4f6' : 'transparent',
                padding: previewDevice === 'mobile' ? '2rem 1rem' : 0,
                borderRadius: 'var(--radius-md)',
              }}
            >
              <div
                className={previewDevice === 'mobile' ? 'mobile-preview-frame' : ''}
                style={{
                  width: previewDevice === 'mobile' ? '360px' : '100%',
                  maxWidth: previewDevice === 'mobile' ? '360px' : '720px',
                  backgroundColor: '#ffffff',
                  padding: '1.5rem',
                  borderRadius: previewDevice === 'mobile' ? '24px' : 'var(--radius-md)',
                  boxShadow:
                    previewDevice === 'mobile'
                      ? '0 10px 25px -5px rgba(0, 0, 0, 0.2), 0 0 0 8px #1f2937'
                      : 'none',
                  border: previewDevice === 'desktop' ? '1px solid var(--color-border)' : 'none',
                }}
              >
                <DynamicForm
                  key={`${currentForm.form_code}-${String(currentForm.version)}-${previewDevice}`}
                  formSnapshot={currentForm}
                  submitLabel="Test Submit Form"
                  onSubmit={(data) => {
                    alert(`Form submitted valid payload:\n${JSON.stringify(data, null, 2)}`);
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Field Editor Drawer / Modal */}
      {editingField && (
        <Modal
          isOpen={isFieldDrawerOpen}
          onClose={() => {
            setIsFieldDrawerOpen(false);
          }}
          title={`Edit Field: ${editingField.field_key}`}
          size="lg"
          footer={
            <>
              <Button
                variant="outline"
                size="md"
                onClick={() => {
                  setIsFieldDrawerOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" size="md" onClick={handleSaveField}>
                Apply Field Changes
              </Button>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
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
                  Field Key:
                </label>
                <Input
                  value={editingField.field_key}
                  disabled={editingField.is_core}
                  onChange={(e) => {
                    setEditingField({ ...editingField, field_key: e.target.value });
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
                  Label:
                </label>
                <Input
                  value={editingField.label}
                  onChange={(e) => {
                    setEditingField({ ...editingField, label: e.target.value });
                  }}
                />
              </div>
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
                  Control Type:
                </label>
                <Select
                  options={[
                    { value: 'text', label: 'Text Input' },
                    { value: 'textarea', label: 'Textarea' },
                    { value: 'number', label: 'Number' },
                    { value: 'date', label: 'Date' },
                    { value: 'dropdown', label: 'Dropdown (Select)' },
                    { value: 'radio', label: 'Radio Group' },
                    { value: 'checkbox', label: 'Checkbox' },
                    { value: 'multiselect', label: 'MultiSelect' },
                    { value: 'file', label: 'File Upload' },
                    { value: 'master_ref', label: 'Master Ref (Combobox)' },
                  ]}
                  value={editingField.control_type}
                  disabled={editingField.is_core}
                  onChange={(e) => {
                    setEditingField({
                      ...editingField,
                      control_type: e.target.value as ControlType,
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
                  Section Name:
                </label>
                <Input
                  value={editingField.section || ''}
                  placeholder="e.g. Inward Header, Dispatch Info"
                  onChange={(e) => {
                    setEditingField({ ...editingField, section: e.target.value });
                  }}
                />
              </div>
            </div>

            {['dropdown', 'radio', 'checkbox', 'multiselect'].includes(
              editingField.control_type,
            ) && (
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    marginBottom: '0.25rem',
                  }}
                >
                  Option Set:
                </label>
                <Select
                  options={[
                    { value: '', label: '-- None (Custom) --' },
                    ...optionSets.map((s) => ({
                      value: s.code,
                      label: `${s.name} (${s.code})`,
                    })),
                  ]}
                  value={editingField.option_set_code || ''}
                  onChange={(e) => {
                    setEditingField({
                      ...editingField,
                      option_set_code: e.target.value || null,
                    });
                  }}
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
                Help Text / Instructions:
              </label>
              <Input
                value={editingField.help_text || ''}
                placeholder="Guidance displayed beneath the control"
                onChange={(e) => {
                  setEditingField({ ...editingField, help_text: e.target.value });
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
              <Checkbox
                id="edit-field-req"
                label="Required Field"
                checked={Boolean(editingField.required)}
                onChange={(e) => {
                  setEditingField({ ...editingField, required: e.target.checked });
                }}
              />
              <Checkbox
                id="edit-field-active"
                label="Active"
                checked={editingField.is_active !== false}
                onChange={(e) => {
                  setEditingField({ ...editingField, is_active: e.target.checked });
                }}
              />
            </div>

            {/* Visual Rule Builder for Visible When */}
            <div style={{ marginTop: '0.5rem' }}>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.375rem',
                }}
              >
                Visible When (Conditional Display Rule):
              </label>
              <RuleBuilder
                value={editingField.visible_when}
                onChange={(rule) => {
                  setEditingField({ ...editingField, visible_when: rule });
                }}
                availableFields={availableFieldKeys}
              />
            </div>

            {/* Visual Rule Builder for Required When */}
            <div style={{ marginTop: '0.5rem' }}>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  marginBottom: '0.375rem',
                }}
              >
                Required When (Conditional Required Rule):
              </label>
              <RuleBuilder
                value={editingField.required_when}
                onChange={(rule) => {
                  setEditingField({ ...editingField, required_when: rule });
                }}
                availableFields={availableFieldKeys}
              />
            </div>
          </div>
        </Modal>
      )}

      {/* Publish Confirmation Modal */}
      <Modal
        isOpen={isPublishModalOpen}
        onClose={() => {
          setIsPublishModalOpen(false);
        }}
        title={`Publish Form ${currentForm?.form_code ?? ''} (v${String(currentForm?.version ?? '')})`}
        footer={
          <>
            <Button
              variant="outline"
              size="md"
              onClick={() => {
                setIsPublishModalOpen(false);
              }}
              disabled={isPublishing}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              onClick={() => {
                void handlePublish();
              }}
              isLoading={isPublishing}
            >
              Confirm & Publish
            </Button>
          </>
        }
      >
        <p style={{ fontSize: '0.875rem', margin: '0 0 1rem 0' }}>
          Publishing freezes this version snapshot and retires the previous published version.
          Operational screens will immediately use this new published version.
        </p>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.875rem',
              fontWeight: 600,
              marginBottom: '0.25rem',
            }}
          >
            Version Notes / Change Description:
          </label>
          <Textarea
            value={changeNotes}
            onChange={(e) => {
              setChangeNotes(e.target.value);
            }}
            placeholder="e.g. Added vehicle verification and conditional transporter remarks."
            rows={3}
          />
        </div>
      </Modal>

      {/* Version Diff Modal */}
      <Modal
        isOpen={isDiffModalOpen}
        onClose={() => {
          setIsDiffModalOpen(false);
        }}
        title={`Diff: Version ${String(diffResult?.v1 ?? '')} vs Version ${String(diffResult?.v2 ?? '')}`}
        size="lg"
        footer={
          <Button
            variant="primary"
            size="md"
            onClick={() => {
              setIsDiffModalOpen(false);
            }}
          >
            Close
          </Button>
        }
      >
        {diffResult && (
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.875rem' }}
          >
            <div>
              <h3
                style={{
                  fontSize: '0.9375rem',
                  fontWeight: 600,
                  color: '#15803d',
                  margin: '0 0 0.5rem 0',
                }}
              >
                Added Fields ({diffResult.added_fields.length})
              </h3>
              {diffResult.added_fields.length === 0 ? (
                <p style={{ color: 'var(--color-fg-muted)', margin: 0 }}>None</p>
              ) : (
                <ul>
                  {diffResult.added_fields.map((f) => (
                    <li key={f.field_key}>
                      <code>{f.field_key}</code> — {f.label} ({f.control_type})
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h3
                style={{
                  fontSize: '0.9375rem',
                  fontWeight: 600,
                  color: '#dc2626',
                  margin: '0 0 0.5rem 0',
                }}
              >
                Removed Fields ({diffResult.removed_fields.length})
              </h3>
              {diffResult.removed_fields.length === 0 ? (
                <p style={{ color: 'var(--color-fg-muted)', margin: 0 }}>None</p>
              ) : (
                <ul>
                  {diffResult.removed_fields.map((f) => (
                    <li key={f.field_key}>
                      <code>{f.field_key}</code> — {f.label}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h3
                style={{
                  fontSize: '0.9375rem',
                  fontWeight: 600,
                  color: '#b45309',
                  margin: '0 0 0.5rem 0',
                }}
              >
                Modified Fields ({diffResult.modified_fields.length})
              </h3>
              {diffResult.modified_fields.length === 0 ? (
                <p style={{ color: 'var(--color-fg-muted)', margin: 0 }}>None</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {diffResult.modified_fields.map((m) => (
                    <div
                      key={m.field_key}
                      style={{
                        padding: '0.5rem',
                        backgroundColor: 'var(--color-bg-subtle)',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      <strong>{m.field_key}:</strong>
                      <pre style={{ margin: '0.25rem 0 0 0', fontSize: '0.75rem' }}>
                        Before: {JSON.stringify(m.before)}
                        {'\n'}
                        After: {JSON.stringify(m.after)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
