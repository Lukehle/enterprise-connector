#!/usr/bin/env node
'use strict';
// Read-only workflow inspection through one visible GitHub CLI wrapper.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');

function help() {
  process.stdout.write(`Enterprise Connector CI monitor (GitHub CLI authentication required)
Usage: node scripts/ci_monitor.cjs COMMAND
  --help                          Show this help
  runs [--branch NAME]             List the latest 12 workflow runs
  watch RUN_ID                     Wait for a run and propagate its result
  log-failed RUN_ID                Print failed-job logs
  test-summary RUN_ID              Print status and jobs as JSON
  check-actions [WORKFLOW]         Resolve referenced action versions to commits
No command writes to GitHub or changes account authentication.
`);
}

function gh(args, capture = false) {
  const result = spawnSync('gh', args, { encoding: 'utf8', stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit', shell: false });
  if (result.error) throw new Error('GitHub CLI is unavailable; use an approved installation and authentication.');
  if (result.status !== 0) {
    if (capture && result.stderr) process.stderr.write(result.stderr);
    process.exitCode = result.status || 1;
    return null;
  }
  return capture ? result.stdout.trim() : '';
}

try {
  const [command, ...args] = process.argv.slice(2);
  if (!command || command === '--help' || command === '-h') {
    help();
  } else if (command === 'runs') {
    if (args.length && (args.length !== 2 || args[0] !== '--branch' || !args[1])) throw new Error('Usage: runs [--branch NAME]');
    gh(['run', 'list', '--limit', '12', '--json', 'databaseId,headSha,headBranch,status,conclusion,url,workflowName', ...args]);
  } else if (['watch', 'log-failed', 'test-summary'].includes(command)) {
    if (args.length !== 1 || !/^\d+$/.test(args[0])) throw new Error('Supply one numeric run ID.');
    if (command === 'watch') gh(['run', 'watch', args[0], '--exit-status', '--interval', '15']);
    if (command === 'log-failed') gh(['run', 'view', args[0], '--log-failed']);
    if (command === 'test-summary') gh(['run', 'view', args[0], '--json', 'databaseId,headSha,status,conclusion,jobs,url']);
  } else if (command === 'check-actions') {
    if (args.length > 1) throw new Error('Usage: check-actions [WORKFLOW]');
    const workflow = args[0] || '.github/workflows/ci.yml';
    const text = fs.readFileSync(workflow, 'utf8');
    const matches = [...text.matchAll(/uses:\s*([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)/g)];
    if (!matches.length) throw new Error('No remote action references found.');
    const resolved = [];
    for (const [, repo, ref] of matches) {
      const sha = gh(['api', `repos/${repo}/commits/${ref}`, '--jq', '.sha'], true);
      if (sha !== null) resolved.push({ action: repo, reference: ref, commit: sha });
    }
    process.stdout.write(JSON.stringify({ workflow, actions: resolved }, null, 2) + '\n');
  } else {
    throw new Error(`Unknown command: ${command}`);
  }
} catch (error) {
  process.stderr.write(`CI monitor: ${error.message}\n`);
  process.exitCode = 1;
}
