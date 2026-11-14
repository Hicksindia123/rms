import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import {
  evaluateRule,
  evaluateValidation,
  type Rule,
  type FieldValidation,
} from '../../src/lib/rules';

interface TestCase {
  id: string;
  description: string;
  rule?: Rule | null;
  values?: Record<string, unknown>;
  context?: Record<string, unknown> | null;
  expected?: boolean;
  validation_spec?: FieldValidation;
  field_value?: unknown;
  expected_valid?: boolean;
  expected_error?: string | null;
  is_required?: boolean;
}

describe('Rules Engine Parity Tests (shared/rules-test-vectors.json)', () => {
  const vectorsPath = path.resolve(__dirname, '../../../shared/rules-test-vectors.json');
  const rawData = fs.readFileSync(vectorsPath, 'utf-8');
  const testVectors = JSON.parse(rawData) as { cases: TestCase[] };
  const cases: TestCase[] = testVectors.cases;

  it('contains at least 40 test cases', () => {
    expect(cases.length).toBeGreaterThanOrEqual(40);
  });

  for (const tc of cases) {
    it(`evaluates ${tc.id}: ${tc.description}`, () => {
      const values = tc.values || {};
      const context = tc.context || null;

      if (tc.rule !== undefined && tc.rule !== null) {
        const actual = evaluateRule(tc.rule, values, context);
        expect(actual).toBe(tc.expected);
      }

      if (tc.validation_spec) {
        const errors = evaluateValidation(
          tc.validation_spec,
          tc.field_value,
          values,
          tc.is_required || false,
          'Field',
          context,
        );
        const isValid = errors.length === 0;
        expect(isValid).toBe(tc.expected_valid);

        if (tc.expected_error) {
          const expectedErr = tc.expected_error;
          const hasErrorText = errors.some((err) => err.includes(expectedErr));
          expect(hasErrorText).toBe(true);
        }
      }
    });
  }
});
