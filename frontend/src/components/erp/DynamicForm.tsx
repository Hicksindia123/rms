import React, { useMemo } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { evaluateRule, evaluateValidation } from '@/lib/rules';
import type { FormSnapshot, FormFieldSnapshot } from '@/features/config/forms/types';
import {
  Input,
  Textarea,
  Select,
  RadioGroup,
  Checkbox,
  MultiSelect,
  FileUpload,
  AsyncCombobox,
  Button,
} from '@/components/ui';

/** Lets a screen supply its own control for a field (e.g. a master-data picker) while the form
 * keeps ownership of the value, visibility, required-ness and validation. */
export interface FieldRenderApi {
  value: unknown;
  onChange: (value: unknown) => void;
  error: string | undefined;
  values: Record<string, unknown>;
  setFieldValue: (key: string, value: unknown) => void;
  readOnly: boolean;
}

export interface DynamicFormProps {
  formSnapshot: FormSnapshot;
  initialValues?: Record<string, unknown>;
  onSubmit?: (values: Record<string, unknown>) => void | Promise<void>;
  context?: Record<string, unknown>;
  readOnly?: boolean;
  submitLabel?: string;
  className?: string;
  isSubmitting?: boolean;
  onValuesChange?: (values: Record<string, unknown>) => void;
  /** Custom controls by field_key (e.g. a master-data picker); other fields use the defaults. */
  fieldRenderers?: Partial<
    Record<string, (field: FormFieldSnapshot, api: FieldRenderApi) => React.ReactNode>
  >;
  /** Field errors returned by the API ({field_key: [messages]}). */
  serverErrors?: Record<string, string[]> | undefined;
  /** Keep the submit button visible at the bottom of the viewport (mobile forms). */
  stickySubmit?: boolean;
  /** Content rendered just above the submit button (e.g. a warning banner). */
  beforeSubmit?: React.ReactNode;
}

export const DynamicForm: React.FC<DynamicFormProps> = ({
  formSnapshot,
  initialValues = {},
  onSubmit,
  context,
  readOnly = false,
  submitLabel = 'Submit',
  className = '',
  isSubmitting = false,
  onValuesChange,
  fieldRenderers,
  serverErrors,
  stickySubmit = false,
  beforeSubmit,
}) => {
  const {
    register,
    handleSubmit,
    control,
    setError,
    setValue,
    clearErrors,
    formState: { errors },
  } = useForm<Record<string, unknown>>({
    defaultValues: initialValues,
    mode: 'onChange',
  });

  const formValues = useWatch({ control }) as Record<string, unknown>;

  // Notify parent of values change if requested
  React.useEffect(() => {
    onValuesChange?.(formValues);
  }, [formValues, onValuesChange]);

  React.useEffect(() => {
    if (!serverErrors) return;
    for (const [key, messages] of Object.entries(serverErrors)) {
      setError(key, { type: 'server', message: messages[0] ?? 'Invalid value' });
    }
  }, [serverErrors, setError]);

  const setFieldValue = React.useCallback(
    (key: string, value: unknown) => {
      setValue(key, value, { shouldDirty: true, shouldValidate: false });
      clearErrors(key);
    },
    [setValue, clearErrors],
  );

  // Compute visibility and requirement dynamically for every field
  const { visibleFields, requiredMap, sections } = useMemo(() => {
    const sorted = [...formSnapshot.fields].sort((a, b) => a.sort_order - b.sort_order);

    const visible: FormFieldSnapshot[] = [];
    const reqMap: Record<string, boolean> = {};
    const sectionMap = new Map<string, FormFieldSnapshot[]>();

    for (const field of sorted) {
      if (field.is_active === false) {
        continue;
      }

      // Check visible_when condition
      const isVisible = evaluateRule(field.visible_when, formValues, context);
      if (!isVisible) {
        continue;
      }

      // Check required_when or explicit required
      const isReq =
        (field.required ?? false) ||
        (Boolean(field.required_when) && evaluateRule(field.required_when, formValues, context));
      reqMap[field.field_key] = isReq;
      visible.push(field);

      const sectionName = field.section?.trim() || 'General';
      const existing = sectionMap.get(sectionName);
      if (existing) {
        existing.push(field);
      } else {
        sectionMap.set(sectionName, [field]);
      }
    }

    return {
      visibleFields: visible,
      requiredMap: reqMap,
      sections: Array.from(sectionMap.entries()),
    };
  }, [formSnapshot.fields, formValues, context]);

  const handleFormSubmit = async (data: Record<string, unknown>) => {
    if (!onSubmit || readOnly) return;

    let hasErrors = false;
    clearErrors();

    // Validate visible fields
    for (const field of visibleFields) {
      const isReq = Boolean(requiredMap[field.field_key]);
      const value = data[field.field_key];
      const validationErrors = evaluateValidation(
        field.validation,
        value,
        data,
        isReq,
        field.label,
        context,
      );

      if (validationErrors.length > 0) {
        hasErrors = true;
        const msg = validationErrors[0] ?? `${field.label} is invalid`;
        setError(field.field_key, {
          type: 'manual',
          message: msg,
        });
      }
    }

    if (hasErrors) {
      return;
    }

    // Prune invisible fields from submission data
    const submissionData: Record<string, unknown> = {};
    for (const field of visibleFields) {
      submissionData[field.field_key] = data[field.field_key];
    }

    await onSubmit(submissionData);
  };

  const renderControl = (field: FormFieldSnapshot) => {
    const errorMsg =
      typeof errors[field.field_key]?.message === 'string'
        ? (errors[field.field_key]?.message as string)
        : undefined;

    const customRenderer = fieldRenderers?.[field.field_key];
    if (customRenderer) {
      return (
        <Controller
          name={field.field_key}
          control={control}
          render={({ field: controllerField }) => (
            <>
              {customRenderer(field, {
                value: controllerField.value,
                onChange: (v: unknown) => {
                  controllerField.onChange(v);
                  clearErrors(field.field_key);
                },
                error: errorMsg,
                values: formValues,
                setFieldValue,
                readOnly,
              })}
            </>
          )}
        />
      );
    }

    const options = (field.options || []).map((opt) => ({
      value: opt.code,
      label: opt.label,
      allowed_status: opt.allowed_status ?? undefined,
      rule_text: opt.rule_text ?? null,
      disabled: opt.is_active === false,
    }));

    switch (field.control_type) {
      case 'dropdown':
        return (
          <Select
            id={`field-${field.field_key}`}
            options={options}
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            value={
              typeof formValues[field.field_key] === 'string' ||
              typeof formValues[field.field_key] === 'number'
                ? (formValues[field.field_key] as string | number)
                : undefined
            }
            {...register(field.field_key)}
          />
        );

      case 'radio':
        return (
          <Controller
            name={field.field_key}
            control={control}
            render={({ field: controllerField }) => (
              <RadioGroup
                id={`field-${field.field_key}`}
                name={field.field_key}
                options={options}
                value={
                  typeof controllerField.value === 'string'
                    ? controllerField.value
                    : typeof controllerField.value === 'number'
                      ? String(controllerField.value)
                      : ''
                }
                onChange={controllerField.onChange}
                disabled={readOnly}
                error={errorMsg}
                helperText={field.help_text ?? undefined}
              />
            )}
          />
        );

      case 'checkbox':
        return (
          <Checkbox
            id={`field-${field.field_key}`}
            label={field.label}
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            {...register(field.field_key)}
          />
        );

      case 'multiselect':
        return (
          <Controller
            name={field.field_key}
            control={control}
            render={({ field: controllerField }) => (
              <MultiSelect
                id={`field-${field.field_key}`}
                name={field.field_key}
                options={options}
                value={
                  Array.isArray(controllerField.value) ? (controllerField.value as string[]) : []
                }
                onChange={controllerField.onChange}
                disabled={readOnly}
                error={errorMsg}
                helperText={field.help_text ?? undefined}
              />
            )}
          />
        );

      case 'textarea':
        return (
          <Textarea
            id={`field-${field.field_key}`}
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            {...register(field.field_key)}
          />
        );

      case 'number':
        return (
          <Input
            id={`field-${field.field_key}`}
            type="number"
            step="any"
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            {...register(field.field_key, {
              setValueAs: (v: unknown) =>
                v === '' || v === null || v === undefined ? null : Number(v),
            })}
          />
        );

      case 'date':
        return (
          <Input
            id={`field-${field.field_key}`}
            type="date"
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            {...register(field.field_key)}
          />
        );

      case 'file':
        return (
          <Controller
            name={field.field_key}
            control={control}
            render={({ field: controllerField }) => (
              <FileUpload
                id={`field-${field.field_key}`}
                name={field.field_key}
                value={controllerField.value as File | string | null | undefined}
                onChange={controllerField.onChange}
                disabled={readOnly}
                error={errorMsg}
                helperText={field.help_text ?? undefined}
                maxSizeBytes={
                  field.validation?.max_file_size
                    ? field.validation.max_file_size * 1024 * 1024
                    : undefined
                }
              />
            )}
          />
        );

      case 'master_ref':
        return (
          <Controller
            name={field.field_key}
            control={control}
            render={({ field: controllerField }) => (
              <AsyncCombobox
                id={`field-${field.field_key}`}
                name={field.field_key}
                value={
                  typeof controllerField.value === 'string'
                    ? controllerField.value
                    : typeof controllerField.value === 'number'
                      ? String(controllerField.value)
                      : ''
                }
                onChange={controllerField.onChange}
                disabled={readOnly}
                error={errorMsg}
                helperText={field.help_text ?? undefined}
                placeholder={`Search ${field.label}...`}
              />
            )}
          />
        );

      case 'text':
      default:
        return (
          <Input
            id={`field-${field.field_key}`}
            type="text"
            disabled={readOnly}
            error={errorMsg}
            helperText={field.help_text ?? undefined}
            {...register(field.field_key)}
          />
        );
    }
  };

  return (
    <form
      className={`dynamic-form ${className}`}
      onSubmit={(e) => {
        void handleSubmit(handleFormSubmit)(e);
      }}
      noValidate
      style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}
    >
      {sections.map(([sectionTitle, fields]) => (
        <fieldset
          key={sectionTitle}
          style={{
            border: sections.length > 1 ? '1px solid var(--color-border)' : 'none',
            borderRadius: 'var(--radius-md)',
            padding: sections.length > 1 ? '1.25rem' : 0,
            margin: 0,
            backgroundColor: sections.length > 1 ? '#ffffff' : 'transparent',
          }}
        >
          {sections.length > 1 && sectionTitle !== 'General' ? (
            <legend
              style={{
                fontSize: '0.9375rem',
                fontWeight: 600,
                padding: '0 0.5rem',
                color: 'var(--color-fg)',
              }}
            >
              {sectionTitle}
            </legend>
          ) : null}

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            {fields.map((field) => {
              const isRequired = Boolean(requiredMap[field.field_key]);
              const isCheckbox = field.control_type === 'checkbox';

              return (
                <div key={field.field_key} className="form-field-row">
                  {!isCheckbox && (
                    <label
                      htmlFor={`field-${field.field_key}`}
                      style={{
                        display: 'block',
                        fontSize: '0.875rem',
                        fontWeight: 500,
                        marginBottom: '0.375rem',
                        color: 'var(--color-fg)',
                      }}
                    >
                      {field.label}
                      {isRequired ? (
                        <span
                          style={{
                            color: 'var(--color-danger)',
                            marginLeft: '0.25rem',
                          }}
                          aria-label="required"
                        >
                          *
                        </span>
                      ) : null}
                    </label>
                  )}
                  {renderControl(field)}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}

      {!readOnly && onSubmit && (
        <div className={stickySubmit ? 'sticky-submit' : undefined} style={{ marginTop: '0.5rem' }}>
          {beforeSubmit ? <div style={{ marginBottom: '0.75rem' }}>{beforeSubmit}</div> : null}
          <Button
            type="submit"
            variant="primary"
            size={stickySubmit ? 'lg' : 'md'}
            isLoading={isSubmitting}
            style={{ width: '100%', minHeight: stickySubmit ? '52px' : '44px' }}
          >
            {submitLabel}
          </Button>
        </div>
      )}
    </form>
  );
};
