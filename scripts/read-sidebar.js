import { execSync } from 'child_process';

const files = [
  'dashboard/nextjs/src/components/layout/Sidebar.tsx',
  'dashboard/nextjs/src/components/Sidebar.tsx',
  'dashboard/nextjs/src/app/(root)/layout.tsx',
  'dashboard/nextjs/src/app/globals.css',
  'dashboard/nextjs/src/app/layout.tsx',
];

for (const file of files) {
  console.log(`\n${'='.repeat(60)}`);
  console.log(`FILE: ${file}`);
  console.log('='.repeat(60));
  try {
    const content = execSync(`cat /vercel/share/${file}`, {
      encoding: 'utf8',
    });
    console.log(content.substring(0, 3000));
  } catch (e) {
    console.log(`Error reading ${file}: ${e.message}`);
    // Try git show
    try {
      const content2 = execSync(`cd /vercel/share && git show HEAD:${file}`, {
        encoding: 'utf8',
      });
      console.log('(from git):');
      console.log(content2.substring(0, 3000));
    } catch (e2) {
      console.log(`Git error: ${e2.message}`);
    }
  }
}
