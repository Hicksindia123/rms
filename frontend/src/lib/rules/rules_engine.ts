/**
 * Shared conditional-rules engine and field validation evaluator (TypeScript).
 *
 * Mirrors the authoritative Python evaluator in backend/app/shared/rules_engine.py
 * for client-side UX (master plan §6.1, §10, prompt P1-07).
 */

export interface RuleComparison {
  field?: string | undefined;
  context?: string | undefined;
  op?:
    ('eq' | 'neq' | 'in' | 'nin' | 'gt' | 'gte' | 'lt' | 'lte' | 'empty' | 'not_empty') | undefined;
  value?: unknown;
}

export interface RuleGroup {
  all?: Rule[] | undefined;
  any?: Rule[] | undefined;
  not?: Rule | undefined;
}

export type Rule = RuleComparison & RuleGroup;
export type RuleCondition = Rule;

export interface SumEqualsSpec {
  fields: string[];
  target: string | number;
}

export interface CrossFieldSumsSpec {
  sum_equals?: SumEqualsSpec | undefined;
}

export interface RestrictedWhenSpec {
  condition: Rule;
  allowed_values: unknown[];
}

export interface FieldValidation {
  min?: number | undefined;
  max?: number | undefined;
  min_length?: number | undefined;
  max_length?: number | undefined;
  regex?: string | undefined;
  date_not_in_future?: boolean | undefined;
  file_types?: string[] | undefined;
  max_file_size?: number | undefined;
  cross_field_sums?: CrossFieldSumsSpec | undefined;
  restricted_when?: RestrictedWhenSpec | undefined;
}

export type ValidationSpec = FieldValidation;

export function resolvePath(target: unknown, path: string): unknown {
  if (!target || !path || typeof target !== 'object') {
    return undefined;
  }
  const obj = target as Record<string, unknown>;
  if (path in obj) {
    return obj[path];
  }

  const parts = path.split('.');
  let current: unknown = target;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in (current as Record<string, unknown>)) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return current;
}

export function isEmptyValue(val: unknown): boolean {
  if (val === null || val === undefined) {
    return true;
  }
  if (typeof val === 'string') {
    return val.trim().length === 0;
  }
  if (Array.isArray(val)) {
    return val.length === 0;
  }
  if (typeof val === 'object') {
    return Object.keys(val).length === 0;
  }
  return false;
}

function compareNumbers(left: unknown, right: unknown, op: string): boolean {
  const nLeft = Number(left);
  const nRight = Number(right);
  if (isNaN(nLeft) || isNaN(nRight)) {
    return false;
  }
  if (op === 'gt') return nLeft > nRight;
  if (op === 'gte') return nLeft >= nRight;
  if (op === 'lt') return nLeft < nRight;
  if (op === 'lte') return nLeft <= nRight;
  return false;
}

export function evaluateRule(
  rule: Rule | null | undefined,
  values: Record<string, unknown>,
  context?: Record<string, unknown> | null,
): boolean {
  if (!rule) {
    return true;
  }

  // Compound boolean logic
  if (Array.isArray(rule.all)) {
    if (rule.all.length === 0) return true;
    return rule.all.every((child) => evaluateRule(child, values, context));
  }

  if (Array.isArray(rule.any)) {
    if (rule.any.length === 0) return false;
    return rule.any.some((child) => evaluateRule(child, values, context));
  }

  if (rule.not) {
    return !evaluateRule(rule.not, values, context);
  }

  // Leaf rule: field or context operand
  const op = rule.op ?? 'eq';
  const expectedValue = rule.value;

  let actualValue: unknown;
  if (rule.context) {
    actualValue = resolvePath(context, rule.context);
  } else if (rule.field) {
    actualValue = resolvePath(values, rule.field);
  } else {
    // Empty rule object evaluates to true (visible by default)
    return true;
  }

  if (op === 'empty') {
    return isEmptyValue(actualValue);
  }
  if (op === 'not_empty') {
    return !isEmptyValue(actualValue);
  }

  if (op === 'eq') {
    return actualValue === expectedValue;
  }
  if (op === 'neq') {
    return actualValue !== expectedValue;
  }

  if (op === 'in') {
    if (!Array.isArray(expectedValue)) return false;
    return expectedValue.includes(actualValue);
  }

  if (op === 'nin') {
    if (!Array.isArray(expectedValue)) return false;
    return !expectedValue.includes(actualValue);
  }

  if (['gt', 'gte', 'lt', 'lte'].includes(op)) {
    return compareNumbers(actualValue, expectedValue, op);
  }

  return false;
}

export function evaluateValidation(
  validation: FieldValidation | null | undefined,
  fieldValue: unknown,
  values: Record<string, unknown>,
  isRequired = false,
  label = 'Field',
  context?: Record<string, unknown> | null,
): string[] {
  const errors: string[] = [];

  // 1. Required check
  if (isRequired && isEmptyValue(fieldValue)) {
    errors.push(`${label} is required`);
    return errors;
  }

  // Check cross-field sums
  if (validation?.cross_field_sums?.sum_equals) {
    const eqSpec = validation.cross_field_sums.sum_equals;
    const fields = eqSpec.fields;
    const target = eqSpec.target;

    let total = 0;
    for (const f of fields) {
      const val = values[f];
      const num = Number(val);
      if (!isNaN(num) && val !== null && val !== '') {
        total += num;
      }
    }

    const targetLabel = String(target);
    let targetVal: number;
    if (typeof target === 'string') {
      const rawTarget = values[target];
      const num = Number(rawTarget);
      targetVal = isNaN(num) ? 0 : num;
    } else {
      targetVal = typeof target === 'number' ? target : Number(target) || 0;
    }

    if (Math.abs(total - targetVal) > 1e-6) {
      errors.push(
        `Sum of fields (${String(total)}) must equal ${targetLabel} (${String(targetVal)})`,
      );
    }
  }

  // If field is empty and not required, skip value-specific constraints
  if (isEmptyValue(fieldValue)) {
    return errors;
  }

  if (!validation) {
    return errors;
  }

  // 2. Min / Max numeric
  if (validation.min !== undefined) {
    const num = Number(fieldValue);
    if (isNaN(num)) {
      errors.push(`${label} must be a valid number`);
    } else if (num < validation.min) {
      errors.push(`Value must be at least ${String(validation.min)}`);
    }
  }

  if (validation.max !== undefined) {
    const num = Number(fieldValue);
    if (isNaN(num)) {
      errors.push(`${label} must be a valid number`);
    } else if (num > validation.max) {
      errors.push(`Value must be at most ${String(validation.max)}`);
    }
  }

  // 3. Min / Max length
  if (validation.min_length !== undefined) {
    if (String(fieldValue).length < validation.min_length) {
      errors.push(`${label} must have at least ${String(validation.min_length)} characters`);
    }
  }

  if (validation.max_length !== undefined) {
    if (String(fieldValue).length > validation.max_length) {
      errors.push(`${label} must have at most ${String(validation.max_length)} characters`);
    }
  }

  // 4. Regex
  if (validation.regex) {
    const re = new RegExp(validation.regex);
    if (!re.test(String(fieldValue))) {
      errors.push('Value does not match required format');
    }
  }

  // 5. Date not in future
  if (validation.date_not_in_future) {
    const today = new Date().toISOString().slice(0, 10);
    const dateStr = String(fieldValue).slice(0, 10);
    if (dateStr > today) {
      errors.push('Date cannot be in the future');
    }
  }

  // 6. File types
  if (validation.file_types && typeof fieldValue === 'string') {
    const valLower = fieldValue.toLowerCase();
    const allowed = validation.file_types.map((ext) => ext.toLowerCase());
    const matched = allowed.some((ext) => valLower.endsWith(ext));
    if (!matched) {
      errors.push(`File must be of allowed type: ${validation.file_types.join(', ')}`);
    }
  }

  // 7. Restricted when
  if (validation.restricted_when) {
    const { condition, allowed_values } = validation.restricted_when;
    if (evaluateRule(condition, values, context)) {
      if (!allowed_values.includes(fieldValue)) {
        errors.push('Selected option is not allowed under current conditions');
      }
    }
  }

  return errors;
}
