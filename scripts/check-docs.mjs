#!/usr/bin/env node

/**
 * Validate the project's two-level documentation index.
 *
 * Every folder below docs/ must have a README.md. A folder README links to all
 * immediate Markdown documents and child-folder README files, each followed by
 * a short description. docs/README.md may link only to folder README files.
 *
 * Side effects: writes validation errors to stderr and sets a non-zero exit
 * code when the documentation structure is incomplete.
 */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(scriptDir, '..', 'docs');
const errors = [];

/**
 * Escape a string for exact use in a regular expression.
 *
 * @param {string} value Text to escape.
 * @returns {string} Escaped regular-expression fragment.
 */
function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Read immediate directory entries without following links.
 *
 * @param {string} directory Absolute directory path.
 * @returns {fs.Dirent[]} Directory entries sorted by name.
 * @throws {Error} When the directory cannot be read.
 */
function entries(directory) {
  return fs.readdirSync(directory, { withFileTypes: true })
    .filter((entry) => !entry.name.startsWith('.'))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/**
 * Test that a README has a descriptive Markdown link to a relative target.
 *
 * @param {string} readme Markdown content.
 * @param {string} target Relative link target.
 * @returns {boolean} True when a link and non-empty description are present.
 */
function hasDescribedLink(readme, target) {
  const pattern = new RegExp(
    `\\[[^\\]]+\\]\\(${escapeRegExp(target)}\\):\\s+\\S+`,
    'm',
  );
  return pattern.test(readme);
}

/**
 * Validate one documentation directory and all of its descendants.
 *
 * @param {string} directory Absolute path of the directory to validate.
 * @param {boolean} isRoot Whether this is docs/ itself.
 * @returns {void}
 */
function validateDirectory(directory, isRoot) {
  const relativeDirectory = path.relative(docsRoot, directory) || 'docs';
  const readmePath = path.join(directory, 'README.md');

  if (!fs.existsSync(readmePath)) {
    errors.push(`${relativeDirectory}: missing README.md`);
    return;
  }

  const readme = fs.readFileSync(readmePath, 'utf8');
  const children = entries(directory);
  const markdownFiles = children
    .filter((entry) => entry.isFile() && entry.name.endsWith('.md') && entry.name !== 'README.md')
    .map((entry) => entry.name);
  const directories = children.filter((entry) => entry.isDirectory()).map((entry) => entry.name);

  if (isRoot && markdownFiles.length > 0) {
    errors.push('docs: detailed Markdown files must be placed in a logical subfolder');
  }

  for (const file of markdownFiles) {
    if (!hasDescribedLink(readme, file)) {
      errors.push(`${relativeDirectory}/README.md: missing described link to ${file}`);
    }
  }

  for (const childDirectory of directories) {
    const target = `${childDirectory}/README.md`;
    if (!hasDescribedLink(readme, target)) {
      errors.push(`${relativeDirectory}/README.md: missing described link to ${target}`);
    }
    validateDirectory(path.join(directory, childDirectory), false);
  }

  if (isRoot) {
    const links = [...readme.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)].map((match) => match[1]);
    for (const link of links) {
      if (!/^[^/]+\/README\.md$/.test(link)) {
        errors.push(`docs/README.md: only folder README links are allowed (${link})`);
      }
    }
  }
}

if (!fs.existsSync(docsRoot)) {
  errors.push('docs: directory is missing');
} else {
  validateDirectory(docsRoot, true);
}

if (errors.length > 0) {
  process.stderr.write(`Documentation check failed:\n${errors.map((error) => `- ${error}`).join('\n')}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write('Documentation structure is valid.\n');
}
