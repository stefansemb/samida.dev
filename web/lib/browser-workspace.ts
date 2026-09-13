// Lets SAMIDA read (and, in Chrome/Edge, write) files in a folder the user
// picks in their own browser - never touching the server's filesystem.
// Chrome/Edge get the File System Access API (live read+write handle);
// Firefox/Safari fall back to <input type="file" webkitdirectory> (a
// one-time snapshot - reads work the same, but "writing" triggers a
// download instead of a silent overwrite, since the browser gives no way
// to write back to an arbitrary folder there).

export type BrowserWorkspace =
  | { kind: 'handle'; handle: FileSystemDirectoryHandle; name: string }
  | { kind: 'filelist'; files: File[]; name: string };

type DirEntry = { name: string; type: 'dir' | 'file'; size: number | null };

export function supportsDirectoryPicker(): boolean {
  return typeof window !== 'undefined' && 'showDirectoryPicker' in window;
}

export async function pickBrowserWorkspaceHandle(): Promise<BrowserWorkspace> {
  const picker = (window as unknown as { showDirectoryPicker: () => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker;
  const handle = await picker();
  return { kind: 'handle', handle, name: handle.name };
}

export function browserWorkspaceFromFileList(fileList: FileList): BrowserWorkspace | null {
  const files = Array.from(fileList);
  if (files.length === 0) return null;
  const firstRelative = (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath || files[0].name;
  const name = firstRelative.split('/')[0] || 'folder';
  return { kind: 'filelist', files, name };
}

function stripRootSegment(relativePath: string): string {
  const idx = relativePath.indexOf('/');
  return idx === -1 ? relativePath : relativePath.slice(idx + 1);
}

async function walkToDirectoryHandle(
  root: FileSystemDirectoryHandle,
  relativePath: string,
  options?: { create?: boolean },
): Promise<FileSystemDirectoryHandle> {
  if (!relativePath || relativePath === '.') return root;
  let current = root;
  for (const part of relativePath.split('/').filter(Boolean)) {
    current = await current.getDirectoryHandle(part, options);
  }
  return current;
}

async function listDirectoryViaHandle(root: FileSystemDirectoryHandle, relativePath: string) {
  const dirHandle = await walkToDirectoryHandle(root, relativePath);
  const entries: DirEntry[] = [];
  const iterable = dirHandle as unknown as { entries(): AsyncIterable<[string, FileSystemHandle]> };
  for await (const [name, handle] of iterable.entries()) {
    if (name.startsWith('.')) continue;
    if (handle.kind === 'directory') {
      entries.push({ name, type: 'dir', size: null });
    } else {
      const file = await (handle as FileSystemFileHandle).getFile();
      entries.push({ name, type: 'file', size: file.size });
    }
  }
  entries.sort((a, b) => a.name.localeCompare(b.name));
  return { path: relativePath || '.', entries };
}

async function readFileViaHandle(root: FileSystemDirectoryHandle, relativePath: string) {
  const parts = relativePath.split('/').filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) return { error: 'Please provide a file path.' };
  const dirHandle = await walkToDirectoryHandle(root, parts.join('/'));
  const fileHandle = await dirHandle.getFileHandle(fileName);
  const file = await fileHandle.getFile();
  const content = await file.text();
  return { path: relativePath, content };
}

async function writeFileViaHandle(root: FileSystemDirectoryHandle, relativePath: string, content: string) {
  const parts = relativePath.split('/').filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) return { error: 'Please provide a file path.' };
  const dirHandle = await walkToDirectoryHandle(root, parts.join('/'), { create: true });
  const fileHandle = await dirHandle.getFileHandle(fileName, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(content);
  await writable.close();
  return { path: relativePath, bytes_written: new TextEncoder().encode(content).length };
}

function listDirectoryViaFileList(files: File[], relativePath: string) {
  const normalized = relativePath && relativePath !== '.' ? relativePath.replace(/\/$/, '') : '';
  const prefix = normalized ? `${normalized}/` : '';
  const kinds = new Map<string, 'dir' | 'file'>();
  const sizes = new Map<string, number>();
  for (const file of files) {
    const rel = stripRootSegment((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name);
    if (!rel.startsWith(prefix)) continue;
    const remainder = rel.slice(prefix.length);
    if (!remainder) continue;
    const [first, ...rest] = remainder.split('/');
    if (rest.length > 0) {
      kinds.set(first, 'dir');
    } else {
      kinds.set(first, 'file');
      sizes.set(first, file.size);
    }
  }
  const entries: DirEntry[] = Array.from(kinds.entries())
    .filter(([name]) => !name.startsWith('.'))
    .map(([name, type]) => ({ name, type, size: type === 'file' ? (sizes.get(name) ?? null) : null }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return { path: relativePath || '.', entries };
}

async function readFileViaFileList(files: File[], relativePath: string) {
  const match = files.find(
    (file) => stripRootSegment((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name) === relativePath,
  );
  if (!match) return { error: `The file does not exist: ${relativePath}` };
  const content = await match.text();
  return { path: relativePath, content };
}

function writeFileViaFileList(content: string, relativePath: string) {
  // No API can write back into an arbitrary folder here - offer a download instead.
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = relativePath.split('/').pop() || 'file.txt';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return {
    path: relativePath,
    bytes_written: new TextEncoder().encode(content).length,
    downloaded: true,
    message: 'This browser can only download the file, not save it back into the folder directly.',
  };
}

export async function executeBrowserWorkspaceTool(
  workspace: BrowserWorkspace,
  toolName: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const relativePath = typeof args.path === 'string' ? args.path : '.';
  const content = typeof args.content === 'string' ? args.content : '';
  try {
    if (workspace.kind === 'handle') {
      if (toolName === 'list_directory') return await listDirectoryViaHandle(workspace.handle, relativePath);
      if (toolName === 'read_file') return await readFileViaHandle(workspace.handle, relativePath);
      if (toolName === 'write_file') return await writeFileViaHandle(workspace.handle, relativePath, content);
    } else {
      if (toolName === 'list_directory') return listDirectoryViaFileList(workspace.files, relativePath);
      if (toolName === 'read_file') return await readFileViaFileList(workspace.files, relativePath);
      if (toolName === 'write_file') return writeFileViaFileList(content, relativePath);
    }
    return { error: `Unknown tool: ${toolName}` };
  } catch (caught) {
    if (caught instanceof DOMException && (caught.name === 'NotFoundError' || caught.name === 'TypeMismatchError')) {
      return { error: `The path does not exist: ${relativePath}` };
    }
    return { error: caught instanceof Error ? caught.message : 'The local file operation failed.' };
  }
}
