import { execSync } from 'child_process';
import { readdirSync, statSync, existsSync, readFileSync } from 'fs';
import { join } from 'path';

// Find current working directory and project structure
console.log('PWD:', process.cwd());
console.log('');

// List directories in cwd
try {
  const cwd = process.cwd();
  const entries = readdirSync(cwd);
  console.log('CWD contents:', entries.join('\n'));
} catch(e) {
  console.log('Error listing cwd:', e.message);
}

// Try to find sidebar files recursively
function findFiles(dir, pattern, results = []) {
  try {
    const entries = readdirSync(dir);
    for (const entry of entries) {
      if (entry === 'node_modules' || entry === '.git') continue;
      const fullPath = join(dir, entry);
      try {
        const stat = statSync(fullPath);
        if (stat.isDirectory()) {
          findFiles(fullPath, pattern, results);
        } else if (entry.toLowerCase().includes(pattern.toLowerCase())) {
          results.push(fullPath);
        }
      } catch(e) {}
    }
  } catch(e) {}
  return results;
}

const cwd = process.cwd();
console.log('\n--- Sidebar files ---');
const sidebarFiles = findFiles(cwd, 'sidebar');
sidebarFiles.forEach(f => console.log(f));

console.log('\n--- Layout files ---');
const layoutFiles = findFiles(cwd, 'layout');
layoutFiles.forEach(f => console.log(f));

console.log('\n--- Nav files ---');
const navFiles = findFiles(cwd, 'nav');
navFiles.forEach(f => console.log(f));

// Try reading globals.css
const cssFiles = findFiles(cwd, 'globals');
console.log('\n--- Globals css files ---');
cssFiles.forEach(f => console.log(f));

// Read first sidebar file found
if (sidebarFiles.length > 0) {
  console.log('\n--- SIDEBAR CONTENT ---');
  console.log(readFileSync(sidebarFiles[0], 'utf-8'));
}
