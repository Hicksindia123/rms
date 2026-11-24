import React, { useRef } from 'react';
import { FileVideo, Image as ImageIcon, Trash2, Upload } from 'lucide-react';

import { Button } from '@/components/ui';

import { formatBytes } from './uploads';

interface Props {
  id: string;
  label: string;
  required?: boolean;
  kind: 'video' | 'image';
  /** Accepted MIME types + extensions (from the form config). */
  accept: string;
  multiple?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
  error?: string | null | undefined;
  helper?: string | undefined;
  disabled?: boolean;
}

/**
 * DEC-73: file picker for the E-Commerce gate form. Gallery / file upload ONLY: the input has no
 * `capture` attribute, so the browser offers the gallery or file manager instead of opening the
 * camera directly (the package-opening video is recorded beforehand).
 */
export const MediaPicker: React.FC<Props> = ({
  id,
  label,
  required = false,
  kind,
  accept,
  multiple = false,
  files,
  onChange,
  error,
  helper,
  disabled = false,
}) => {
  const input = useRef<HTMLInputElement>(null);
  const Icon = kind === 'video' ? FileVideo : ImageIcon;
  const total = files.reduce((n, f) => n + f.size, 0);
  return (
    <div className="space-y-2" data-testid={`picker-${id}`}>
      <span id={`${id}-label`} className="form-control__label">
        {label}
        {required ? <span className="text-red-600"> *</span> : null}
      </span>
      <input
        ref={input}
        id={id}
        type="file"
        accept={accept}
        multiple={multiple}
        className="sr-only"
        aria-labelledby={`${id}-label`}
        disabled={disabled}
        onChange={(e) => {
          const picked = Array.from(e.target.files ?? []);
          e.target.value = '';
          if (picked.length === 0) return;
          onChange(multiple ? [...files, ...picked] : picked.slice(0, 1));
        }}
      />
      {files.length > 0 ? (
        <ul className="m-0 list-none space-y-2 p-0">
          {files.map((f, i) => (
            <li
              key={`${f.name}-${String(i)}`}
              className="flex min-h-[44px] items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"
            >
              <Icon className="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-sm">{f.name}</span>
              <span className="shrink-0 text-xs text-slate-500">{formatBytes(f.size)}</span>
              <Button
                type="button"
                variant="ghost"
                className="min-h-[44px] min-w-[44px] shrink-0"
                aria-label={`Remove ${f.name}`}
                disabled={disabled}
                onClick={() => {
                  onChange(files.filter((_, j) => j !== i));
                }}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {multiple || files.length === 0 ? (
        <Button
          type="button"
          variant="outline"
          className="min-h-[44px] w-full sm:w-auto"
          disabled={disabled}
          onClick={() => input.current?.click()}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          {files.length === 0
            ? kind === 'video'
              ? 'Choose video from gallery / files'
              : 'Choose images'
            : 'Add more images'}
        </Button>
      ) : null}
      {multiple && files.length > 0 ? (
        <p className="form-control__helper">Total {formatBytes(total)}</p>
      ) : null}
      {error ? (
        <p className="form-control__error" role="alert">
          {error}
        </p>
      ) : helper ? (
        <p className="form-control__helper">{helper}</p>
      ) : null}
    </div>
  );
};
