import React, { useEffect, useRef } from 'react';
import { Camera, Trash2 } from 'lucide-react';
import { Button } from './Button';

export interface FileUploadProps {
  id?: string | undefined;
  name: string;
  accept?: string | undefined;
  maxSizeBytes?: number | undefined;
  value?: File | string | null | undefined;
  onChange?: ((file: File | string | null) => void) | undefined;
  error?: string | undefined;
  helperText?: string | undefined;
  disabled?: boolean | undefined;
}

export const FileUpload: React.FC<FileUploadProps> = ({
  id,
  name,
  accept = 'image/*,application/pdf',
  maxSizeBytes,
  value,
  onChange,
  error,
  helperText,
  disabled = false,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previewImgRef = useRef<HTMLImageElement>(null);

  const isImageDataUrl =
    typeof value === 'string' &&
    (value.startsWith('data:image/') || value.startsWith('blob:') || value.startsWith('http'));
  const isImageFile = value instanceof File && value.type.startsWith('image/');

  // An image File is previewed through an object URL assigned straight to the <img> (no state),
  // and revoked when the value changes or the component unmounts.
  useEffect(() => {
    const img = previewImgRef.current;
    if (!(value instanceof File) || !value.type.startsWith('image/') || !img) return;
    const url = URL.createObjectURL(value);
    img.src = url;
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [value]);

  const showPreview = isImageDataUrl || isImageFile;
  const fileName = value instanceof File ? value.name : typeof value === 'string' && !isImageDataUrl ? value : null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    if (!file) {
      onChange?.(null);
      return;
    }
    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = () => {
        onChange?.(reader.result as string);
      };
      reader.readAsDataURL(file);
    } else {
      onChange?.(file);
    }
  };

  const handleClear = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    onChange?.(null);
  };

  return (
    <div className="form-control-wrapper" id={id}>
      <input
        ref={fileInputRef}
        type="file"
        name={name}
        accept={accept}
        onChange={handleFileChange}
        disabled={disabled}
        style={{ display: 'none' }}
        id={`${id ?? name}-file-input`}
      />

      {showPreview ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.85rem',
            padding: '0.5rem 0.75rem',
            border: '1px solid #cbd5e1',
            borderRadius: 'var(--radius-md)',
            backgroundColor: '#ffffff',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          <img
            ref={previewImgRef}
            {...(isImageDataUrl ? { src: value } : {})}
            alt="Document Preview"
            style={{
              width: '54px',
              height: '54px',
              objectFit: 'cover',
              borderRadius: '6px',
              border: '1px solid #e2e8f0',
              flexShrink: 0,
            }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#0f172a', display: 'block' }}>
              Document Image Attached
            </span>
            <span style={{ fontSize: '0.75rem', color: '#64748b', display: 'block' }}>
              {fileName ?? 'Image captured and ready'}
            </span>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            Change
          </Button>
          {!disabled ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={handleClear}
              style={{ color: 'var(--color-danger)' }}
              aria-label="Remove photo"
            >
              <Trash2 size={15} aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            padding: '0.5rem 0.75rem',
            border: '1px dashed #cbd5e1',
            borderRadius: 'var(--radius-md)',
            backgroundColor: '#fafafa',
          }}
        >
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
          >
            <Camera size={15} aria-hidden="true" />
            <span>{fileName ? 'Change File' : 'Take Photo / Choose File'}</span>
          </Button>

          <span
            style={{
              fontSize: '0.8125rem',
              color: fileName ? 'var(--color-fg)' : 'var(--color-fg-muted)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: 1,
            }}
          >
            {fileName || 'No picture selected (optional)'}
          </span>

          {fileName && !disabled ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={handleClear}
              style={{ color: 'var(--color-danger)' }}
            >
              Remove
            </Button>
          ) : null}
        </div>
      )}

      {maxSizeBytes ? (
        <p style={{ fontSize: '0.75rem', color: 'var(--color-fg-muted)', marginTop: '0.25rem' }}>
          Max size: {Math.round(maxSizeBytes / (1024 * 1024))} MB
        </p>
      ) : null}

      {error ? (
        <p className="form-control__error" role="alert" style={{ marginTop: '0.25rem' }}>
          {error}
        </p>
      ) : helperText ? (
        <p className="form-control__helper" style={{ marginTop: '0.25rem' }}>
          {helperText}
        </p>
      ) : null}
    </div>
  );
};
