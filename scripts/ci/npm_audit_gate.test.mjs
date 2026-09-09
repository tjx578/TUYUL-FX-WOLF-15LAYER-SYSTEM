import assert from 'node:assert/strict';
import test from 'node:test';
import {validateAudit} from './npm_audit_gate.mjs';

function report(update = {}) {
  return {auditReportVersion: 2, vulnerabilities: {}, metadata: {vulnerabilities: {
    info: 0, low: 0, moderate: 0, high: 0, critical: 0, total: 0, ...update,
  }}};
}

test('complete clean audit accepted', () => assert.equal(validateAudit(report(), 0).total, 0));
test('existing moderate-only policy retained', () => assert.equal(validateAudit(report({moderate: 2, total: 2}), 0).moderate, 2));
for (const [name, value, exit] of [
  ['registry error', {error: {code: 'EAUDITNOLOCK'}}, 1],
  ['missing metadata', {auditReportVersion: 2}, 0],
  ['invalid counts', report({high: '0'}), 0],
  ['inconsistent total', report({total: 1}), 0],
  ['high severity', report({high: 1, total: 1}), 1],
  ['critical severity', report({critical: 1, total: 1}), 0],
  ['process error', report(), 2],
  ['unexplained failure', report(), 1],
]) {
  test(name + ' rejected', () => assert.throws(() => validateAudit(value, exit)));
}
