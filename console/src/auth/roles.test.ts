import { describe, expect, it } from 'vitest';
import { isReadOnly, rolesFromGroups } from './roles';

describe('rolesFromGroups', () => {
  it('keeps the known console groups', () => {
    expect(rolesFromGroups(['backoffice', 'judge'])).toEqual(['backoffice', 'judge']);
  });

  it('ignores unknown groups and malformed claims', () => {
    expect(rolesFromGroups(['admins', 'sales_rep'])).toEqual(['sales_rep']);
    expect(rolesFromGroups(undefined)).toEqual([]);
    expect(rolesFromGroups('judge')).toEqual([]);
    expect(rolesFromGroups([1, null, 'judge'])).toEqual(['judge']);
  });
});

describe('isReadOnly', () => {
  it('is true only for judge-only users (FN-28)', () => {
    expect(isReadOnly(['judge'])).toBe(true);
    expect(isReadOnly(['judge', 'backoffice'])).toBe(false);
    expect(isReadOnly(['sales_rep'])).toBe(false);
  });

  it('is false for users without roles: they are denied elsewhere, not "read-only"', () => {
    expect(isReadOnly([])).toBe(false);
  });
});
