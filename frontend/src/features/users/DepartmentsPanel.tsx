import { useCallback, useState } from 'react';
import { Plus } from 'lucide-react';

import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import { usersApi, type Department } from './api';

type Editing = { mode: 'create' } | { mode: 'edit'; dept: Department };

/** P1-05: departments (code immutable; deactivate instead of delete). */
export function DepartmentsPanel({
  canConfigure,
  onChanged,
}: {
  canConfigure: boolean;
  onChanged: () => void;
}) {
  const fetchDepartments = useCallback(() => usersApi.departments(), []);
  const departments = useApiQuery(fetchDepartments);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <div className="masters-panel">
      {canConfigure && (
        <div className="filters">
          <div className="masters-field masters-field--action">
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                setNotice(null);
                setEditing({ mode: 'create' });
              }}
            >
              <Plus size={16} aria-hidden="true" /> Add department
            </Button>
          </div>
        </div>
      )}
      {notice && (
        <p className="masters-notice" role="status">
          {notice}
        </p>
      )}
      {departments.error ? (
        <ErrorState error={departments.error} onRetry={departments.reload} />
      ) : departments.loading || !departments.data ? (
        <LoadingState label="Loading departments…" />
      ) : departments.data.length === 0 ? (
        <EmptyState title="No departments yet" />
      ) : (
        <ul className="masters-list">
          {departments.data.map((d) => (
            <li key={d.id} className="masters-row">
              <div className="masters-row__main">
                <div className="masters-row__title">
                  <span>{d.name}</span>
                  <Badge variant="info">{d.code}</Badge>
                  {!d.is_active && <Badge variant="neutral">Inactive</Badge>}
                </div>
                <div className="masters-row__meta">
                  {d.user_count} {d.user_count === 1 ? 'user' : 'users'}
                </div>
              </div>
              {canConfigure && (
                <Button
                  type="button"
                  size="sm"
                  className="masters-row__action"
                  onClick={() => {
                    setNotice(null);
                    setEditing({ mode: 'edit', dept: d });
                  }}
                >
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <DepartmentDialog
          editing={editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={(msg) => {
            setEditing(null);
            setNotice(msg);
            departments.reload();
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function DepartmentDialog({
  editing,
  onClose,
  onSaved,
}: {
  editing: Editing;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const dept = editing.mode === 'edit' ? editing.dept : null;
  const [code, setCode] = useState('');
  const [name, setName] = useState(dept?.name ?? '');
  const [active, setActive] = useState(dept?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (dept) {
        const out = await usersApi.updateDepartment(dept.id, {
          name: name.trim(),
          is_active: active,
        });
        onSaved(`Saved ${out.name}.`);
      } else {
        const out = await usersApi.createDepartment(code.trim(), name.trim());
        onSaved(`Added ${out.name} (${out.code}).`);
      }
    } catch (err) {
      setError(toApiError(err));
      setBusy(false);
    }
  };

  const valid = name.trim().length > 0 && (dept !== null || code.trim().length >= 2);
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={dept ? `Edit ${dept.name}` : 'Add department'}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!valid}
            onClick={() => {
              void submit();
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="masters-form">
        {dept ? (
          <p className="masters-row__meta">
            Code: <strong>{dept.code}</strong> (cannot be changed)
          </p>
        ) : (
          <label className="masters-field">
            <span className="form-label">
              Code<span className="required-star">*</span>
            </span>
            <Input
              id="dept-code"
              value={code}
              maxLength={40}
              placeholder="e.g. QUALITY_LAB"
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
              }}
            />
          </label>
        )}
        <label className="masters-field">
          <span className="form-label">
            Name<span className="required-star">*</span>
          </span>
          <Input
            id="dept-name"
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        {dept && (
          <Checkbox
            id="dept-active"
            label="Active"
            checked={active}
            onChange={(e) => {
              setActive(e.target.checked);
            }}
          />
        )}
        {error && (
          <p className="user-form__error" role="alert">
            {error.message}
            {error.requestId ? ` (ref ${error.requestId})` : ''}
          </p>
        )}
      </div>
    </Modal>
  );
}
