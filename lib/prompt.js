/**
 * The prompt section.
 *
 * Static when nothing new arrived: a short note that the tools exist. It grows
 * a paragraph when the newest user message carried a picture, because that is
 * the only moment where "do you want this as your pointer?" is a good idea.
 */

const STATIC = [
  '## Mouse cursors (Cursor Maker)',
  '',
  '`cursor_from_image` turns one picture into a full 16-role Windows cursor scheme and switches to it;',
  '`cursor_status` lists what exists, `cursor_apply` switches back to an older set, and `cursor_restore`',
  'returns the pointer the user had before the first install.',
  '',
  'A pointer change is global and visible in every window, so ask before replacing it: one short',
  'question with a yes/no pair of options is enough. Do not ask again for the same picture once the',
  'user has answered, and never install a scheme they did not approve.',
].join('\n');

/**
 * @param agent - the scope the section is being assembled for.
 * @param store - the shared picture memory.
 * @returns section text, or an empty string when the section does not apply.
 */
export function promptFor(agent, store) {
  const batch = store.latest(agent);
  if (batch === undefined || batch.images.length === 0) return STATIC;

  const lines = batch.images.map((image) => {
    const size = image.width && image.height ? ` ${image.width}x${image.height}` : '';
    const where = image.path ? `at ${image.path}` : '(no file path recorded, resolve it through the tool)';
    return `- ${image.name}${size} ${where}`;
  });

  return [
    STATIC,
    '',
    `### The picture the user just sent`,
    '',
    ...lines,
    '',
    'Ask once, early, whether they want it as their mouse cursor. If they agree, call',
    '`cursor_from_image` (omit `image` and it uses this same picture). If they decline, let it go and',
    'do not raise it again for this picture.',
  ].join('\n');
}