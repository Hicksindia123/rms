import React from 'react';
import { clsx } from 'clsx';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: string | undefined;
  helperText?: string | undefined;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, helperText, id, rows = 3, ...props }, ref) => {
    return (
      <div className="form-control-wrapper">
        <textarea
          ref={ref}
          id={id}
          rows={rows}
          className={clsx('textarea', error && 'textarea--error', className)}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={
            error
              ? `${id ?? 'textarea'}-error`
              : helperText
                ? `${id ?? 'textarea'}-helper`
                : undefined
          }
          {...props}
        />
        {error ? (
          <p id={`${id ?? 'textarea'}-error`} className="form-control__error" role="alert">
            {error}
          </p>
        ) : helperText ? (
          <p id={`${id ?? 'textarea'}-helper`} className="form-control__helper">
            {helperText}
          </p>
        ) : null}
      </div>
    );
  },
);

Textarea.displayName = 'Textarea';
