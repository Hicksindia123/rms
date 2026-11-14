import React, { useState } from 'react';
import type { Rule } from '@/lib/rules';
import { Button } from '@/components/ui';

export interface RuleBuilderProps {
  value: Rule | null | undefined;
  onChange: (rule: Rule | null) => void;
  availableFields?: string[];
}

export const RuleBuilder: React.FC<RuleBuilderProps> = ({
  value,
  onChange,
  availableFields = [],
}) => {
  const [mode, setMode] = useState<'visual' | 'json'>('visual');
  const [jsonText, setJsonText] = useState(() => (value ? JSON.stringify(value, null, 2) : ''));
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Normalize rule into group or leaf
  const isGroup = value && ('all' in value || 'any' in value);
  const groupType = value && 'any' in value ? 'any' : 'all';
  const rulesList: Rule[] = isGroup
    ? value.any || value.all || []
    : value && (value.field || value.context || value.op)
      ? [value]
      : [];

  const handleGroupTypeChange = (newType: 'all' | 'any') => {
    if (rulesList.length === 0) {
      onChange(null);
      return;
    }
    if (newType === 'any') {
      onChange({ any: rulesList });
    } else {
      onChange({ all: rulesList });
    }
  };

  const handleAddCondition = () => {
    const newLeaf: Rule = {
      field: availableFields[0] || 'field_key',
      op: 'eq',
      value: '',
    };
    const updated = [...rulesList, newLeaf];
    if (updated.length === 1 && !isGroup) {
      onChange(newLeaf);
    } else {
      onChange(groupType === 'any' ? { any: updated } : { all: updated });
    }
  };

  const handleRemoveCondition = (index: number) => {
    const updated = rulesList.filter((_, i) => i !== index);
    if (updated.length === 0) {
      onChange(null);
    } else if (updated.length === 1) {
      onChange(updated[0] ?? null);
    } else {
      onChange(groupType === 'any' ? { any: updated } : { all: updated });
    }
  };

  const handleUpdateCondition = (index: number, updatedRule: Rule) => {
    const updated = [...rulesList];
    updated[index] = updatedRule;
    if (updated.length === 1 && !isGroup) {
      onChange(updated[0] ?? null);
    } else {
      onChange(groupType === 'any' ? { any: updated } : { all: updated });
    }
  };

  const handleJsonApply = () => {
    setJsonError(null);
    if (!jsonText.trim()) {
      onChange(null);
      return;
    }
    try {
      const parsed = JSON.parse(jsonText) as Rule;
      onChange(parsed);
    } catch (err: unknown) {
      setJsonError((err as Error).message || 'Invalid JSON syntax');
    }
  };

  return (
    <div
      className="rule-builder"
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        padding: '0.875rem',
        backgroundColor: '#fafafa',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Rule Logic:</span>
          {rulesList.length > 1 && (
            <select
              value={groupType}
              onChange={(e) => {
                handleGroupTypeChange(e.target.value as 'all' | 'any');
              }}
              className="select"
              style={{ padding: '0.25rem 0.5rem', width: 'auto', fontSize: '0.8125rem' }}
            >
              <option value="all">Match ALL conditions (AND)</option>
              <option value="any">Match ANY condition (OR)</option>
            </select>
          )}
        </div>

        <div style={{ display: 'flex', gap: '0.25rem' }}>
          <button
            type="button"
            className={`btn btn--sm ${mode === 'visual' ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => {
              setMode('visual');
              setJsonText(value ? JSON.stringify(value, null, 2) : '');
            }}
          >
            Visual
          </button>
          <button
            type="button"
            className={`btn btn--sm ${mode === 'json' ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => {
              setMode('json');
              setJsonText(value ? JSON.stringify(value, null, 2) : '');
            }}
          >
            JSON
          </button>
        </div>
      </div>

      {mode === 'visual' ? (
        <div>
          {rulesList.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--color-fg-muted)' }}>
              <p style={{ margin: 0, fontSize: '0.875rem' }}>No conditions set (always active).</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddCondition}
                style={{ marginTop: '0.5rem' }}
              >
                + Add Condition
              </Button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {rulesList.map((cond, idx) => {
                const isContext = Boolean(cond.context);
                const operand = cond.context || cond.field || '';
                const op: NonNullable<Rule['op']> = cond.op || 'eq';
                const val = cond.value ?? '';
                const isUnary = op === 'empty' || op === 'not_empty';

                return (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.375rem',
                      flexWrap: 'wrap',
                      background: '#fff',
                      padding: '0.5rem',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <select
                      value={isContext ? 'context' : 'field'}
                      onChange={(e) => {
                        const becomesContext = e.target.value === 'context';
                        if (becomesContext) {
                          handleUpdateCondition(idx, {
                            context: 'product_category.code',
                            op,
                            value: val,
                          });
                        } else {
                          handleUpdateCondition(idx, {
                            field: availableFields[0] || 'field_key',
                            op,
                            value: val,
                          });
                        }
                      }}
                      className="select"
                      style={{ width: '90px', fontSize: '0.8125rem' }}
                    >
                      <option value="field">Field</option>
                      <option value="context">Context</option>
                    </select>

                    {isContext ? (
                      <input
                        type="text"
                        value={operand}
                        onChange={(e) => {
                          handleUpdateCondition(idx, {
                            context: e.target.value,
                            op,
                            value: val,
                          });
                        }}
                        placeholder="context.path"
                        className="input"
                        style={{ width: '150px', fontSize: '0.8125rem' }}
                      />
                    ) : availableFields.length > 0 ? (
                      <select
                        value={operand}
                        onChange={(e) => {
                          handleUpdateCondition(idx, {
                            field: e.target.value,
                            op,
                            value: val,
                          });
                        }}
                        className="select"
                        style={{ width: '150px', fontSize: '0.8125rem' }}
                      >
                        {availableFields.map((f) => (
                          <option key={f} value={f}>
                            {f}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={operand}
                        onChange={(e) => {
                          handleUpdateCondition(idx, {
                            field: e.target.value,
                            op,
                            value: val,
                          });
                        }}
                        placeholder="field_key"
                        className="input"
                        style={{ width: '150px', fontSize: '0.8125rem' }}
                      />
                    )}

                    <select
                      value={op}
                      onChange={(e) => {
                        const newOp = e.target.value as Rule['op'];
                        handleUpdateCondition(idx, {
                          ...(isContext ? { context: operand } : { field: operand }),
                          op: newOp,
                          value: val,
                        });
                      }}
                      className="select"
                      style={{ width: '100px', fontSize: '0.8125rem' }}
                    >
                      <option value="eq">== (eq)</option>
                      <option value="neq">!= (neq)</option>
                      <option value="in">in list</option>
                      <option value="nin">not in</option>
                      <option value="gt">&gt; (gt)</option>
                      <option value="gte">&gt;= (gte)</option>
                      <option value="lt">&lt; (lt)</option>
                      <option value="lte">&lt;= (lte)</option>
                      <option value="empty">is empty</option>
                      <option value="not_empty">not empty</option>
                    </select>

                    {!isUnary && (
                      <input
                        type="text"
                        value={
                          Array.isArray(val)
                            ? val.join(', ')
                            : typeof val === 'string'
                              ? val
                              : typeof val === 'number' || typeof val === 'boolean'
                                ? String(val)
                                : ''
                        }
                        onChange={(e) => {
                          const raw = e.target.value;
                          let parsedVal: unknown = raw;
                          if (op === 'in' || op === 'nin') {
                            parsedVal = raw.split(',').map((s) => s.trim());
                          }
                          handleUpdateCondition(idx, {
                            ...(isContext ? { context: operand } : { field: operand }),
                            op,
                            value: parsedVal,
                          });
                        }}
                        placeholder={op === 'in' || op === 'nin' ? 'A, B, C' : 'value'}
                        className="input"
                        style={{ flex: 1, minWidth: '100px', fontSize: '0.8125rem' }}
                      />
                    )}

                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        handleRemoveCondition(idx);
                      }}
                      style={{ color: 'var(--color-danger)', padding: '0 0.5rem' }}
                      title="Remove condition"
                    >
                      ✕
                    </Button>
                  </div>
                );
              })}

              <div style={{ marginTop: '0.5rem' }}>
                <Button type="button" variant="outline" size="sm" onClick={handleAddCondition}>
                  + Add Condition
                </Button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div>
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
            }}
            rows={5}
            className="textarea"
            style={{
              fontFamily: 'monospace',
              fontSize: '0.8125rem',
              width: '100%',
            }}
            placeholder='{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'
          />
          {jsonError && (
            <p style={{ color: 'var(--color-danger)', fontSize: '0.75rem', marginTop: '0.25rem' }}>
              {jsonError}
            </p>
          )}
          <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem' }}>
            <Button type="button" size="sm" variant="primary" onClick={handleJsonApply}>
              Apply JSON
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                onChange(null);
              }}
            >
              Clear
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
