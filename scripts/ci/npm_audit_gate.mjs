import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export function validateAudit(report, exitCode) {
  if (![0, 1].includes(exitCode) || !report || report.error || report.auditReportVersion !== 2) {
    throw new Error('npm audit did not produce a complete supported report');
  }
  const counts = report.metadata?.vulnerabilities;
  const levels = ['info', 'low', 'moderate', 'high', 'critical'];
  if (!counts || !report.vulnerabilities || typeof report.vulnerabilities !== 'object' ||
      [...levels, 'total'].some(key => !Number.isSafeInteger(counts[key]) || counts[key] < 0) ||
      levels.reduce((sum, key) => sum + counts[key], 0) !== counts.total) {
    throw new Error('npm audit vulnerability counts are absent or invalid');
  }
  if (counts.high + counts.critical > 0 || (exitCode === 1 && counts.total === 0)) {
    throw new Error('npm audit high/critical findings or unexplained failure');
  }
  return counts;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const report = JSON.parse(readFileSync(process.argv[2], 'utf8'));
    console.log(JSON.stringify(validateAudit(report, Number(process.argv[3]))));
  } catch {
    console.error('npm audit gate rejected incomplete, invalid, or high/critical result');
    process.exitCode = 1;
  }
}
