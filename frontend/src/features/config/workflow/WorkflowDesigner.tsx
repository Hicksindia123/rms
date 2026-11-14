import { useEffect, useState } from 'react';
import { GitFork, CheckCircle2, AlertCircle, Plus, Lock } from 'lucide-react';

export interface WorkflowStage {
  id: string;
  code: string;
  label: string;
  sort_order: number;
}

export interface StepAssignment {
  assignment_type: string;
  role_id: string | null;
  role_code: string | null;
  user_id: string | null;
}

export interface WorkflowStep {
  id: string;
  code: string;
  label: string;
  stage_id: string;
  stage_code?: string;
  form_definition_id: string | null;
  form_code?: string;
  sla_hours: number | null;
  requires_approval: boolean;
  sort_order: number;
  is_active: boolean;
  assignments: StepAssignment[];
}

export interface WorkflowTransition {
  id: string;
  from_step_id: string;
  from_step_code?: string;
  to_step_id: string;
  to_step_code?: string;
  condition: Record<string, unknown> | null;
  system_guards: string[];
  priority: number;
}

export interface WorkflowVersionDetail {
  id: string;
  version_no: number;
  status: string;
  stages: WorkflowStage[];
  steps: WorkflowStep[];
  transitions: WorkflowTransition[];
}

export function WorkflowDesigner() {
  const [workflow, setWorkflow] = useState<WorkflowVersionDetail | null>(null);
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'columns' | 'diagram' | 'transitions'>('columns');

  // Publish modal state
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishReason, setPublishReason] = useState('');
  const [publishing, setPublishing] = useState(false);

  // Step drawer edit state
  const [stepLabel, setStepLabel] = useState('');
  const [savingStep, setSavingStep] = useState(false);

  useEffect(() => {
    let ignore = false;
    fetch('/api/v1/config/workflow/RMS_STANDARD')
      .then((res) => res.json())
      .then(
        (defData: {
          has_draft?: boolean;
          draft_version_no?: number;
          latest_published_version?: number;
        }) => {
          const verToLoad = defData.has_draft
            ? defData.draft_version_no
            : defData.latest_published_version;
          return fetch(`/api/v1/config/workflow/RMS_STANDARD/versions/${String(verToLoad ?? 1)}`);
        },
      )
      .then((res) => res.json())
      .then((verData: WorkflowVersionDetail) => {
        if (!ignore) {
          setWorkflow(verData);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  async function reloadWorkflow() {
    const defRes = await fetch('/api/v1/config/workflow/RMS_STANDARD');
    if (!defRes.ok) return;
    const defData = (await defRes.json()) as {
      has_draft?: boolean;
      draft_version_no?: number;
      latest_published_version?: number;
    };
    const verToLoad = defData.has_draft
      ? defData.draft_version_no
      : defData.latest_published_version;
    const verRes = await fetch(
      `/api/v1/config/workflow/RMS_STANDARD/versions/${String(verToLoad ?? 1)}`,
    );
    if (!verRes.ok) return;
    const verData = (await verRes.json()) as WorkflowVersionDetail;
    setWorkflow(verData);
  }

  async function handleCreateDraft() {
    setError(null);
    try {
      const res = await fetch('/api/v1/config/workflow/RMS_STANDARD/draft', {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to create draft');
      await reloadWorkflow();
      setSuccess('Draft created. You can now edit steps, stages, and transitions.');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error creating draft');
    }
  }

  async function handleSaveStepLabel() {
    if (!selectedStep || !stepLabel.trim()) return;
    setSavingStep(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/config/workflow/RMS_STANDARD/draft/step-label?step_code=${selectedStep.code}&new_label=${encodeURIComponent(
          stepLabel,
        )}`,
        { method: 'PUT' },
      );
      if (!res.ok) {
        const d = (await res.json()) as { error?: { message?: string } };
        throw new Error(d.error?.message || 'Failed to update step label');
      }
      setSuccess(`Step '${selectedStep.code}' label updated.`);
      await reloadWorkflow();
      setSelectedStep((prev) => (prev ? { ...prev, label: stepLabel } : null));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error saving step');
    } finally {
      setSavingStep(false);
    }
  }

  async function handlePublishDraft() {
    if (!publishReason.trim()) {
      setError('A mandatory reason is required to publish a workflow version.');
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/config/workflow/RMS_STANDARD/draft/publish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: publishReason }),
      });
      if (!res.ok) {
        const d = (await res.json()) as { error?: { message?: string } };
        throw new Error(d.error?.message || 'Publishing draft failed');
      }
      setSuccess(`Workflow version published successfully.`);
      setPublishModalOpen(false);
      setPublishReason('');
      await reloadWorkflow();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error publishing workflow');
    } finally {
      setPublishing(false);
    }
  }

  const isDraft = workflow?.status === 'DRAFT';

  return (
    <div
      style={{
        maxWidth: '1400px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem',
      }}
    >
      {/* Top Banner */}
      <div
        style={{
          backgroundColor: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: '8px',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '8px',
              backgroundColor: '#eff6ff',
              color: '#2563eb',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <GitFork size={22} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
                Workflow Designer: RMS Standard (v{workflow?.version_no || 1})
              </h2>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  backgroundColor: isDraft ? '#fef3c7' : '#dcfce7',
                  color: isDraft ? '#92400e' : '#15803d',
                  padding: '0.15rem 0.5rem',
                  borderRadius: '9999px',
                }}
              >
                {workflow?.status}
              </span>
            </div>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Master Plan §2, §6.5 end-to-end return lifecycle state machine, role assignments, and
              locked system guards.
            </p>
          </div>
        </div>

        {/* View toggles & Action buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div
            style={{
              display: 'flex',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              overflow: 'hidden',
            }}
          >
            <button
              type="button"
              onClick={() => {
                setActiveView('columns');
              }}
              style={{
                padding: '0.4rem 0.75rem',
                border: 'none',
                backgroundColor: activeView === 'columns' ? '#1d4ed8' : '#ffffff',
                color: activeView === 'columns' ? '#ffffff' : '#334155',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Stage Columns
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveView('diagram');
              }}
              style={{
                padding: '0.4rem 0.75rem',
                border: 'none',
                backgroundColor: activeView === 'diagram' ? '#1d4ed8' : '#ffffff',
                color: activeView === 'diagram' ? '#ffffff' : '#334155',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Visual Diagram
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveView('transitions');
              }}
              style={{
                padding: '0.4rem 0.75rem',
                border: 'none',
                backgroundColor: activeView === 'transitions' ? '#1d4ed8' : '#ffffff',
                color: activeView === 'transitions' ? '#ffffff' : '#334155',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Transitions List
            </button>
          </div>

          {!isDraft ? (
            <button
              type="button"
              onClick={() => {
                void handleCreateDraft();
              }}
              style={{
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: '#2563eb',
                color: '#ffffff',
                fontWeight: 600,
                fontSize: '0.875rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <Plus size={16} /> Create Draft v{(workflow?.version_no || 1) + 1}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                setPublishModalOpen(true);
              }}
              style={{
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: '#15803d',
                color: '#ffffff',
                fontWeight: 600,
                fontSize: '0.875rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <CheckCircle2 size={16} /> Publish Version {workflow.version_no}
            </button>
          )}
        </div>
      </div>

      {success && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: '6px',
            color: '#15803d',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <CheckCircle2 size={16} /> {success}
        </div>
      )}
      {error && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            color: '#b91c1c',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* VIEW 1: STAGE COLUMNS (Desktop horizontal scroll / mobile stacked) */}
      {activeView === 'columns' && workflow && (
        <div
          className="workflow-stage-columns"
          style={{
            display: 'flex',
            gap: '1rem',
            overflowX: 'auto',
            paddingBottom: '1rem',
          }}
        >
          {workflow.stages.map((stage) => {
            const stageSteps = workflow.steps.filter((s) => s.stage_id === stage.id);
            return (
              <div
                key={stage.id}
                className="workflow-stage-card"
                style={{
                  minWidth: '280px',
                  maxWidth: '320px',
                  flex: '0 0 auto',
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  padding: '1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.75rem',
                }}
              >
                <div style={{ borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem' }}>
                  <span style={{ fontSize: '0.7rem', fontWeight: 700, color: '#64748b' }}>
                    STAGE {stage.sort_order}
                  </span>
                  <h3
                    style={{
                      fontSize: '0.9375rem',
                      fontWeight: 700,
                      margin: '0.2rem 0 0 0',
                      color: '#1e293b',
                    }}
                  >
                    {stage.label}
                  </h3>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {stageSteps.map((step) => {
                    const isSelected = selectedStep?.id === step.id;
                    return (
                      <div
                        key={step.id}
                        onClick={() => {
                          setSelectedStep(step);
                          setStepLabel(step.label);
                        }}
                        style={{
                          backgroundColor: '#ffffff',
                          border: isSelected ? '2px solid #3b82f6' : '1px solid #cbd5e1',
                          borderRadius: '6px',
                          padding: '0.75rem',
                          cursor: 'pointer',
                          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.4rem',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                        >
                          <span
                            style={{
                              fontSize: '0.75rem',
                              fontFamily: 'monospace',
                              fontWeight: 700,
                              color: '#0f172a',
                            }}
                          >
                            {step.code}
                          </span>
                          {step.requires_approval && (
                            <span
                              style={{
                                fontSize: '0.65rem',
                                backgroundColor: '#fef3c7',
                                color: '#92400e',
                                padding: '0.1rem 0.35rem',
                                borderRadius: '4px',
                                fontWeight: 600,
                              }}
                            >
                              Approval Required
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#334155' }}>
                          {step.label}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                          SLA: {step.sla_hours || 4}h | Form: {step.form_code || 'None'}
                        </div>
                        {step.assignments.length > 0 && (
                          <div
                            style={{
                              display: 'flex',
                              gap: '0.3rem',
                              flexWrap: 'wrap',
                              marginTop: '0.25rem',
                            }}
                          >
                            {step.assignments.map((a, i) => (
                              <span
                                key={i}
                                style={{
                                  fontSize: '0.65rem',
                                  backgroundColor:
                                    a.assignment_type === 'APPROVE' ? '#fee2e2' : '#e0f2fe',
                                  color: a.assignment_type === 'APPROVE' ? '#991b1b' : '#0369a1',
                                  padding: '0.1rem 0.35rem',
                                  borderRadius: '3px',
                                  fontWeight: 600,
                                }}
                              >
                                {a.role_code} ({a.assignment_type})
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* VIEW 2: VISUAL READ-ONLY DIAGRAM (SVG/Flex Layout) */}
      {activeView === 'diagram' && workflow && (
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            padding: '1.5rem',
            overflowX: 'auto',
          }}
        >
          <h3 style={{ fontSize: '1rem', fontWeight: 700, margin: '0 0 1rem 0', color: '#0f172a' }}>
            Visual Workflow Transition Flow
          </h3>
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', minWidth: '900px' }}
          >
            {workflow.stages.map((stage) => {
              const sSteps = workflow.steps.filter((s) => s.stage_id === stage.id);
              return (
                <div
                  key={stage.id}
                  style={{ border: '1px solid #e2e8f0', borderRadius: '6px', padding: '1rem' }}
                >
                  <div
                    style={{
                      fontWeight: 700,
                      fontSize: '0.875rem',
                      color: '#64748b',
                      marginBottom: '0.75rem',
                    }}
                  >
                    STAGE {stage.sort_order}: {stage.label}
                  </div>
                  <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                    {sSteps.map((step) => (
                      <div
                        key={step.id}
                        style={{
                          backgroundColor: '#f8fafc',
                          border: '1px solid #cbd5e1',
                          borderRadius: '6px',
                          padding: '0.6rem 0.9rem',
                          minWidth: '160px',
                        }}
                      >
                        <div
                          style={{ fontSize: '0.75rem', fontFamily: 'monospace', fontWeight: 700 }}
                        >
                          {step.code}
                        </div>
                        <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#334155' }}>
                          {step.label}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* VIEW 3: TRANSITIONS LIST */}
      {activeView === 'transitions' && workflow && (
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              textAlign: 'left',
              fontSize: '0.875rem',
            }}
          >
            <thead
              style={{
                backgroundColor: '#f8fafc',
                borderBottom: '1px solid #e2e8f0',
                color: '#475569',
              }}
            >
              <tr>
                <th style={{ padding: '0.75rem 1rem' }}>From Step</th>
                <th style={{ padding: '0.75rem 1rem' }}>To Step</th>
                <th style={{ padding: '0.75rem 1rem' }}>Condition Rule</th>
                <th style={{ padding: '0.75rem 1rem' }}>System Guards</th>
              </tr>
            </thead>
            <tbody>
              {workflow.transitions.map((tr) => (
                <tr key={tr.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', fontWeight: 600 }}>
                    {tr.from_step_code}
                  </td>
                  <td
                    style={{
                      padding: '0.75rem 1rem',
                      fontFamily: 'monospace',
                      fontWeight: 600,
                      color: '#2563eb',
                    }}
                  >
                    {tr.to_step_code}
                  </td>
                  <td
                    style={{
                      padding: '0.75rem 1rem',
                      fontSize: '0.75rem',
                      fontFamily: 'monospace',
                    }}
                  >
                    {tr.condition ? JSON.stringify(tr.condition) : 'Always permissible'}
                  </td>
                  <td style={{ padding: '0.75rem 1rem' }}>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      {tr.system_guards.length > 0 ? (
                        tr.system_guards.map((g) => (
                          <span
                            key={g}
                            style={{
                              fontSize: '0.7rem',
                              fontWeight: 700,
                              backgroundColor: '#fee2e2',
                              color: '#b91c1c',
                              padding: '0.15rem 0.45rem',
                              borderRadius: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                            }}
                          >
                            <Lock size={10} /> {g}
                          </span>
                        ))
                      ) : (
                        <span style={{ color: '#475569', fontSize: '0.75rem' }}>None</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Step Drawer (Flyout / Bottom on Mobile) */}
      {selectedStep && (
        <div
          style={{
            position: 'fixed',
            right: 0,
            top: 0,
            bottom: 0,
            width: '400px',
            maxWidth: '100vw',
            backgroundColor: '#ffffff',
            boxShadow: '-4px 0 12px rgba(0,0,0,0.15)',
            zIndex: 100,
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1.25rem',
            overflowY: 'auto',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderBottom: '1px solid #e2e8f0',
              paddingBottom: '0.75rem',
            }}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Step Details: {selectedStep.code}
            </h3>
            <button
              type="button"
              onClick={() => {
                setSelectedStep(null);
              }}
              style={{
                border: 'none',
                background: 'transparent',
                fontSize: '1.25rem',
                cursor: 'pointer',
                color: '#64748b',
              }}
            >
              ✕
            </button>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.35rem',
              }}
            >
              Step Label
            </label>
            <input
              type="text"
              disabled={!isDraft}
              value={stepLabel}
              onChange={(e) => {
                setStepLabel(e.target.value);
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '0.875rem',
              }}
            />
            {isDraft && (
              <button
                type="button"
                disabled={savingStep}
                onClick={() => {
                  void handleSaveStepLabel();
                }}
                style={{
                  marginTop: '0.5rem',
                  padding: '0.4rem 0.75rem',
                  backgroundColor: '#2563eb',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '4px',
                  fontWeight: 600,
                  fontSize: '0.75rem',
                  cursor: 'pointer',
                }}
              >
                {savingStep ? 'Saving...' : 'Update Step Label'}
              </button>
            )}
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.35rem',
              }}
            >
              Associated Dynamic Form
            </label>
            <div
              style={{
                padding: '0.5rem',
                backgroundColor: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                fontSize: '0.875rem',
                fontFamily: 'monospace',
              }}
            >
              {selectedStep.form_code || 'None'}
            </div>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.35rem',
              }}
            >
              SLA Target Hours
            </label>
            <div
              style={{
                padding: '0.5rem',
                backgroundColor: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                fontSize: '0.875rem',
              }}
            >
              {selectedStep.sla_hours || 4} hours
            </div>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.35rem',
              }}
            >
              Role Assignments (§3.3)
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {selectedStep.assignments.map((a, i) => (
                <div
                  key={i}
                  style={{
                    padding: '0.4rem 0.6rem',
                    backgroundColor: '#f1f5f9',
                    borderRadius: '4px',
                    fontSize: '0.8125rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                  }}
                >
                  <span>{a.role_code}</span>
                  <span
                    style={{
                      fontWeight: 600,
                      color: a.assignment_type === 'APPROVE' ? '#b91c1c' : '#0369a1',
                    }}
                  >
                    {a.assignment_type}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Publish Modal */}
      {publishModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 200,
          }}
        >
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '8px',
              padding: '1.5rem',
              width: '480px',
              maxWidth: '90vw',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Publish Workflow Version {workflow?.version_no}
            </h3>
            <p style={{ margin: 0, fontSize: '0.875rem', color: '#64748b' }}>
              Publishing will freeze this workflow snapshot (G-18), retire the previous version, and
              immediately govern new consignments. A version reason is mandatory.
            </p>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.35rem',
                }}
              >
                Version Notes / Reason (Mandatory)
              </label>
              <textarea
                value={publishReason}
                onChange={(e) => {
                  setPublishReason(e.target.value);
                }}
                rows={3}
                placeholder="Reason for publishing this workflow version..."
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.875rem',
                }}
              />
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.5rem',
                marginTop: '0.5rem',
              }}
            >
              <button
                type="button"
                onClick={() => {
                  setPublishModalOpen(false);
                }}
                style={{
                  padding: '0.5rem 1rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#ffffff',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={publishing}
                onClick={() => {
                  void handlePublishDraft();
                }}
                style={{
                  padding: '0.5rem 1rem',
                  borderRadius: '6px',
                  border: 'none',
                  backgroundColor: '#15803d',
                  color: '#ffffff',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {publishing ? 'Publishing...' : 'Confirm & Publish'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
