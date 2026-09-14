'use client';
/* oxlint-disable next/no-img-element -- local images need direct browser rendering. */

import {
  ChangeEvent,
  ClipboardEvent,
  KeyboardEvent,
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useRouter } from 'next/navigation';
import { API_URL, CurrentUser, fetchCurrentUser, logout, requestJson } from '@/lib/api';
import {
  BrowserWorkspace,
  browserWorkspaceFromFileList,
  executeBrowserWorkspaceTool,
  isBraveBrowser,
  pickBrowserWorkspaceHandle,
  supportsDirectoryPicker,
} from '@/lib/browser-workspace';
import { SamidaMark } from '@/components/samida-mark';
import {
  BrainCircuit,
  Circle,
  Clock3,
  FileText,
  Folder,
  FolderOpen,
  Gauge,
  Image as ImageIcon,
  LogOut,
  Settings as SettingsIcon,
  Pencil,
  Plus,
  Send,
  ShieldCheck,
  Trash2,
  UserRound,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type PendingToolCall = {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: 'low' | 'medium';
  status: 'pending' | 'approved' | 'rejected' | 'executed' | 'failed';
  created_at: string;
  browser_workspace: boolean;
};
type Message = {
  id?: string;
  role: 'user' | 'assistant';
  content: string;
  image_url?: string | null;
  ocr_text?: string | null;
  created_at?: string;
  tool_call?: PendingToolCall | null;
};
type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
type ConversationDetail = Conversation & { messages: Message[] };
type ModelCatalogEntry = {
  provider_key: string;
  model_name: string;
  display_name: string;
  supports_vision: boolean;
  supports_tools: boolean;
  requires_user_key: boolean;
  usable: boolean;
};
type Health = {
  status: 'ok' | 'degraded';
  ollama_reachable: boolean;
  configured_model: string;
  model_available: boolean;
  configured_vision_model: string;
  vision_model_available: boolean;
  available_models: string[];
};
type PendingImage = {
  filename: string;
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp';
  data_base64: string;
  preview_url: string;
};
type ChatResult = {
  conversation: Conversation;
  user_message: Message;
  assistant_message: Message;
  provider: string;
  model: string;
  context_files: string[];
  usage?: UsageInfo | null;
  pending_tool_call?: PendingToolCall | null;
};
type ToolCallDecisionResult = {
  conversation: Conversation;
  assistant_message: Message;
  pending_tool_call?: PendingToolCall | null;
};
type UsageInfo = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};
type SkillSummary = {
  name: string;
};
type WebMcpTool = {
  name: string;
  title: string;
  description: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute(input: unknown): unknown;
};

type AppView = 'chat' | 'reminders';

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(
        tool: WebMcpTool,
        options?: { signal?: AbortSignal },
      ): void | Promise<void>;
    };
  }
  interface Window {
    readonly samidaDesktop?: {
      pickFolder(): Promise<string | null>;
    };
  }
}

const DEFAULT_MODEL = 'anthropic:claude-haiku-4-5';
const greeting: Message = {
  role: 'assistant',
  content: "Hi! I'm connected and ready to help. What would you like to work on?",
};

function argText(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
}

function resolveProviderModel(selectedModel: string): { provider: 'ollama' | 'openai' | 'anthropic'; model: string } {
  for (const provider of ['openai', 'anthropic'] as const) {
    const prefix = `${provider}:`;
    if (selectedModel.startsWith(prefix)) {
      return { provider, model: selectedModel.slice(prefix.length) };
    }
  }
  return { provider: 'ollama', model: selectedModel };
}

function modelLabel(model: string): string {
  const { provider, model: name } = resolveProviderModel(model);
  if (provider === 'openai') return `OpenAI · ${name}`;
  if (provider === 'anthropic') return `Claude · ${name.replace(/^claude-/i, '')}`;
  return model;
}

function fileToImage(file: File): Promise<PendingImage> {
  return new Promise((resolve, reject) => {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      reject(new Error('Use PNG, JPEG, or WebP.'));
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      reject(new Error('The screenshot can be at most 10 MB.'));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('The screenshot could not be read.'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('The screenshot could not be read.'));
        return;
      }
      const dataUrl = reader.result;
      resolve({
        filename: file.name || 'clipboard.png',
        mime_type: file.type as PendingImage['mime_type'],
        data_base64: dataUrl.split(',')[1],
        preview_url: dataUrl,
      });
    };
    reader.readAsDataURL(file);
  });
}

function RemindersPanel() {
  const [reminders, setReminders] = useState<Array<{id:string;text:string;due_at:string;event_at?:string|null;done:boolean;recurrence:string}>>([]);
  const [text, setText] = useState(''); const [dueAt, setDueAt] = useState(''); const [eventAt, setEventAt] = useState(''); const [recurrence, setRecurrence] = useState('once'); const [rangeStart, setRangeStart] = useState('1'); const [rangeEnd, setRangeEnd] = useState('14');
  const load = useCallback(() => { void requestJson<typeof reminders>('/api/reminders').then(setReminders).catch(() => setReminders([])); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
    const timer = window.setInterval(() => {
      void requestJson<typeof reminders>('/api/reminders').then((items) => {
        setReminders(items);
        const now = new Date();
        items.filter((r) => !r.done && new Date(r.due_at).getTime() <= now.getTime() && now.getTime() - new Date(r.due_at).getTime() < 120000).forEach((r) => {
          const key = `samida-notified-${r.id}-${now.toISOString().slice(0, 10)}`;
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && !sessionStorage.getItem(key)) { new Notification('SAMIDA reminder', { body: r.text }); sessionStorage.setItem(key, '1'); }
        });
      }).catch(() => undefined);
    }, 60000);
    return () => window.clearInterval(timer);
  }, []);
  async function addReminder(event: { preventDefault(): void }) { event.preventDefault(); if (!text.trim() || !dueAt) return; await requestJson('/api/reminders', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({text, due_at: dueAt, event_at: eventAt || null, recurrence, range_start: recurrence === 'monthly_range' ? Number(rangeStart) : null, range_end: recurrence === 'monthly_range' ? Number(rangeEnd) : null}) }); setText(''); setDueAt(''); setEventAt(''); load(); }
  async function complete(id: string) { await requestJson(`/api/reminders/${id}/complete`, {method:'POST'}); load(); }
  async function remove(id: string) { await requestJson(`/api/reminders/${id}`, {method:'DELETE'}); load(); }
  return (
    <section className="research-workspace">
      <header className="research-header"><div><span className="eyebrow">Planning</span><h2>Reminders</h2><p>Create and manage your reminders.</p></div></header>
      <div className="reminder-event-control"><label>Event at<input type="datetime-local" value={eventAt} onChange={(e) => setEventAt(e.target.value)} /></label><span>The reminder itself is set in the When field below.</span></div>
      <div className="research-content"><section className="research-card"><form onSubmit={(e) => void addReminder(e)} className="reminder-form"><label>Reminder<input value={text} onChange={(e) => setText(e.target.value)} placeholder="What do you want to remember?" required /></label><label>When<input type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} required /></label><label>Recurrence<select value={recurrence} onChange={(e) => setRecurrence(e.target.value)}><option value="once">Once</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="monthly_range">Day range every month</option></select></label>{recurrence === 'monthly_range' && <><label>From day<input type="number" min="1" max="31" value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} /></label><label>To day<input type="number" min="1" max="31" value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} /></label></>}<button className="reminder-submit" type="submit">+ Add</button></form>{reminders.length === 0 ? <p className="empty-research">No reminders yet. Add your first one above.</p> : reminders.map((r) => <div key={r.id} className="reminder-item"><span>{r.done ? '✓' : '○'} {r.text}<small>{r.due_at} · {r.recurrence}</small></span><span>{!r.done && <button onClick={() => void complete(r.id)} type="button">Done</button>} <button onClick={() => void remove(r.id)} type="button">Remove</button></span></div>)}</section></div>
    </section>
  );
}

export default function Home() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([greeting]);
  const [draft, setDraft] = useState('');
  const [pendingImage, setPendingImage] = useState<PendingImage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalogEntry[]>([]);
  const [priorities, setPriorities] = useState('');
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);
  const [selectedProfile, setSelectedProfile] = useState('minimal');
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [selectedSkill, setSelectedSkill] = useState('none');
  const [workingDirectory, setWorkingDirectory] = useState('');
  const [pickingWorkspace, setPickingWorkspace] = useState(false);
  const [pickingBrowserFolder, setPickingBrowserFolder] = useState(false);
  const [lastUsedModel, setLastUsedModel] = useState<string | null>(null);
  const [lastUsedProvider, setLastUsedProvider] = useState<string | null>(null);
  const [chatUsage, setChatUsage] = useState<UsageInfo | null>(null);
  const [contextFiles, setContextFiles] = useState<string[]>([]);
  const [activeView, setActiveView] = useState<AppView>('chat');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null);
  const [resolvingToolCall, setResolvingToolCall] = useState(false);
  const [browserWorkspace, setBrowserWorkspace] = useState<BrowserWorkspace | null>(null);
  const [isBrave, setIsBrave] = useState(false);
  const browserFileInputRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);
  const activeRef = useRef<Conversation | null>(null);

  const refreshConversations = useCallback(async () => {
    const items = await requestJson<Conversation[]>('/api/conversations');
    setConversations(items);
    return items;
  }, []);

  useEffect(() => {
    void fetchCurrentUser().then((result) => {
      if (!result) {
        router.push('/login');
        return;
      }
      startTransition(() => {
        setCurrentUser(result);
        setAuthChecked(true);
      });
    });
  }, [router]);

  const handleLogout = useCallback(async () => {
    await logout();
    router.push('/login');
  }, [router]);

  /* oxlint-disable react/react-compiler -- initial data loading synchronizes API state. */
  useEffect(() => {
    if (!authChecked) return;
    void requestJson<{content:string}>('/api/priorities').then((r) => setPriorities(r.content)).catch(() => undefined);
  }, [authChecked]);
  useEffect(() => {
    if (!authChecked) return;
    void refreshConversations().catch((caught) =>
      startTransition(() => setError(caught.message)),
    );
    requestJson<Health>('/api/health')
      .then((result) => startTransition(() => setHealth(result)))
      .catch(() => startTransition(() => setHealth(null)));
    requestJson<ModelCatalogEntry[]>('/api/models/catalog?kind=chat')
      .then((result) => startTransition(() => setModelCatalog(result)))
      .catch(() => startTransition(() => setModelCatalog([])));
    requestJson<SkillSummary[]>('/api/skills')
      .then((result) => startTransition(() => setSkills(result)))
      .catch(() => startTransition(() => setSkills([])));
  }, [refreshConversations, authChecked]);
  /* oxlint-enable react/react-compiler */

  useEffect(() => {
    activeRef.current = activeConversation;
  }, [activeConversation]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending]);

  const createConversation = useCallback(async () => {
    const created = await requestJson<Conversation>('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New chat' }),
    });
    setConversations((current) => [created, ...current]);
    setActiveConversation(created);
    setMessages([greeting]);
    setContextFiles([]);
    setChatUsage(null);
    setError(null);
    setPendingToolCall(null);
    return created;
  }, []);

  async function openConversation(conversation: Conversation) {
    const detail = await requestJson<ConversationDetail>(
      `/api/conversations/${conversation.id}`,
    );
    setActiveConversation(detail);
    setMessages(detail.messages.length ? detail.messages : [greeting]);
    setContextFiles([]);
    setChatUsage(null);
    setError(null);
    setPendingToolCall(null);
  }

  const applyClientToolResult = useCallback(
    async (call: PendingToolCall, result: Record<string, unknown>) => {
      const conversation = activeRef.current;
      if (!conversation) return;
      const response = await requestJson<ToolCallDecisionResult>(
        `/api/conversations/${conversation.id}/tool-calls/${call.id}/client-result`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ result }) },
      );
      setMessages((current) => [...current, response.assistant_message]);
      setActiveConversation(response.conversation);
      activeRef.current = response.conversation;
      setPendingToolCall(response.pending_tool_call ?? null);
      await refreshConversations();
    },
    [refreshConversations],
  );

  async function decideToolCall(decision: 'approve' | 'reject') {
    const conversation = activeRef.current;
    if (!pendingToolCall || !conversation) return;
    setResolvingToolCall(true);
    try {
      if (pendingToolCall.browser_workspace) {
        const clientResult =
          decision === 'approve'
            ? browserWorkspace
              ? await executeBrowserWorkspaceTool(browserWorkspace, pendingToolCall.tool_name, pendingToolCall.arguments)
              : { error: 'No local folder is selected.' }
            : { status: 'rejected', message: 'The user rejected the action.' };
        await applyClientToolResult(pendingToolCall, clientResult);
        return;
      }
      const result = await requestJson<ToolCallDecisionResult>(
        `/api/conversations/${conversation.id}/tool-calls/${pendingToolCall.id}/${decision}`,
        { method: 'POST' },
      );
      setMessages((current) => [...current, result.assistant_message]);
      setActiveConversation(result.conversation);
      activeRef.current = result.conversation;
      setPendingToolCall(result.pending_tool_call ?? null);
      await refreshConversations();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Verktygsanropet kunde inte hanteras.',
      );
    } finally {
      setResolvingToolCall(false);
    }
  }

  useEffect(() => {
    if (supportsDirectoryPicker()) return;
    void isBraveBrowser().then(setIsBrave);
  }, []);

  useEffect(() => {
    if (!pendingToolCall || !pendingToolCall.browser_workspace || pendingToolCall.tool_name === 'write_file') return;
    let cancelled = false;
    void (async () => {
      setResolvingToolCall(true);
      try {
        const clientResult = browserWorkspace
          ? await executeBrowserWorkspaceTool(browserWorkspace, pendingToolCall.tool_name, pendingToolCall.arguments)
          : { error: 'No local folder is selected.' };
        if (!cancelled) await applyClientToolResult(pendingToolCall, clientResult);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Could not run the local file tool.');
      } finally {
        if (!cancelled) setResolvingToolCall(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pendingToolCall, browserWorkspace, applyClientToolResult]);

  async function saveRename(conversation: Conversation) {
    const title = renameValue.trim();
    if (!title) return;
    const updated = await requestJson<Conversation>(
      `/api/conversations/${conversation.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      },
    );
    setConversations((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    if (activeRef.current?.id === updated.id) setActiveConversation(updated);
    setRenamingId(null);
  }

  async function deleteConversation() {
    if (!deleteTarget) return;
    await requestJson<void>(`/api/conversations/${deleteTarget.id}`, {
      method: 'DELETE',
    });
    setConversations((current) =>
      current.filter((item) => item.id !== deleteTarget.id),
    );
    if (activeRef.current?.id === deleteTarget.id) {
      setActiveConversation(null);
      setMessages([greeting]);
      setContextFiles([]);
    }
    setDeleteTarget(null);
  }

  const submitContent = useCallback(
    async (content: string, image: PendingImage | null = null) => {
      const normalized = content.trim();
      if (!normalized && !image) throw new Error('Type something or paste an image.');
      if (sendingRef.current) throw new Error('SAMIDA is already working on a response.');

      sendingRef.current = true;
      setIsSending(true);
      setError(null);
      try {
        let conversation = activeRef.current;
        if (!conversation) conversation = await createConversation();

        const localUserMessage: Message = {
          role: 'user',
          content: normalized,
          image_url: image?.preview_url,
        };
        setMessages((current) => [
          ...(current.length === 1 && current[0] === greeting ? [] : current),
          localUserMessage,
        ]);

        const { provider: chatProvider, model: chatModel } = resolveProviderModel(selectedModel);
        const result = await requestJson<ChatResult>(
          `/api/conversations/${conversation.id}/chat`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                content: normalized,
                provider: chatProvider,
                model: chatModel,
                profile: selectedProfile,
                skill: selectedSkill === 'none' ? null : selectedSkill,
                working_directory: workingDirectory.trim() || null,
                browser_workspace: Boolean(browserWorkspace),
                image: image
                ? {
                    filename: image.filename,
                    mime_type: image.mime_type,
                    data_base64: image.data_base64,
                  }
                : null,
            }),
          },
        );
        setMessages((current) => [...current, result.assistant_message]);
        setActiveConversation(result.conversation);
        activeRef.current = result.conversation;
        setContextFiles(result.context_files);
        setLastUsedModel(result.model);
        setLastUsedProvider(result.provider);
        setChatUsage(result.usage ?? null);
        setPendingToolCall(result.pending_tool_call ?? null);
        await refreshConversations();
        return result;
      } catch (caught) {
        const failure =
          caught instanceof Error ? caught : new Error('An unknown error occurred.');
        setError(failure.message);
        throw failure;
      } finally {
        sendingRef.current = false;
        setIsSending(false);
      }
    },
    [createConversation, refreshConversations, selectedModel, selectedProfile, selectedSkill, workingDirectory, browserWorkspace],
  );

  async function sendMessage(event?: { preventDefault: () => void }) {
    event?.preventDefault();
    if (isSending || (!draft.trim() && !pendingImage)) return;
    const content = draft;
    const image = pendingImage;
    setDraft('');
    setPendingImage(null);
    await submitContent(content, image).catch(() => undefined);
  }

  async function pickWorkspace() {
    setPickingWorkspace(true);
    try {
      if (window.samidaDesktop) {
        const path = await window.samidaDesktop.pickFolder();
        if (path) setWorkingDirectory(path);
        return;
      }
      const result = await requestJson<{ path: string | null }>('/api/workspace/pick', { method: 'POST' });
      if (result.path) setWorkingDirectory(result.path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The folder could not be selected.');
    } finally {
      setPickingWorkspace(false);
    }
  }

  async function chooseBrowserFolder() {
    if (pickingBrowserFolder) return;
    if (supportsDirectoryPicker()) {
      setPickingBrowserFolder(true);
      try {
        setBrowserWorkspace(await pickBrowserWorkspaceHandle());
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === 'AbortError') return;
        if (caught instanceof DOMException && /already active/i.test(caught.message)) {
          setError('A folder picker is already open - finish or cancel it, then try again.');
          return;
        }
        setError(caught instanceof Error ? caught.message : 'Could not access that folder.');
      } finally {
        setPickingBrowserFolder(false);
      }
      return;
    }
    browserFileInputRef.current?.click();
  }

  function handleBrowserFolderInputChange(event: ChangeEvent<HTMLInputElement>) {
    const fileList = event.target.files;
    if (fileList) setBrowserWorkspace(browserWorkspaceFromFileList(fileList));
    event.target.value = '';
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  async function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const imageItem = Array.from(event.clipboardData.items).find((item) =>
      item.type.startsWith('image/'),
    );
    if (!imageItem) return;
    event.preventDefault();
    const file = imageItem.getAsFile();
    if (!file) return;
    try {
      setPendingImage(await fileToImage(file));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The image could not be read.');
    }
  }

  useEffect(() => {
    const modelContext = document.modelContext;
    if (!modelContext?.registerTool) return;
    const lifecycle = new AbortController();
    void Promise.resolve(
      modelContext.registerTool(
        {
          name: 'send_chat_message',
          title: 'Send chat message',
          description: 'Send a text message to the active SAMIDA chat.',
          inputSchema: {
            type: 'object',
            properties: { message: { type: 'string', minLength: 1 } },
            required: ['message'],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: false, untrustedContentHint: false },
          async execute(input) {
            if (
              typeof input !== 'object' ||
              input === null ||
              !('message' in input) ||
              typeof input.message !== 'string'
            ) {
              throw new Error('message must be a string.');
            }
            const result = await submitContent(input.message);
            return {
              answer: result.assistant_message.content,
              model: result.model,
              conversation_id: result.conversation.id,
            };
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch((caught) => console.warn('WebMCP kunde inte registreras.', caught));
    return () => lifecycle.abort();
  }, [submitContent]);

  const connected = health?.status === 'ok';
  const chatMessageCount = messages.length === 1 && messages[0] === greeting
    ? 0
    : messages.length;
  const effectiveProvider = lastUsedProvider ?? resolveProviderModel(selectedModel).provider;
  const usageStatus = effectiveProvider === 'openai' || effectiveProvider === 'anthropic'
    ? 'Se API-dashboard'
    : 'Ingen molnlimit';
  const selectableModels = modelCatalog
    .filter((entry) => entry.usable)
    .map((entry) =>
      entry.provider_key === 'ollama' ? entry.model_name : `${entry.provider_key}:${entry.model_name}`,
    );

  if (!authChecked) {
    return <main className="app-shell" />;
  }

  return (
    <main className="app-shell">
      <nav className="top-nav" aria-label="SAMIDA sections">
        <div className="top-nav-group">
          <button className={`top-nav-button ${activeView === 'chat' ? 'active' : ''}`} onClick={() => setActiveView('chat')} type="button"><BrainCircuit size={15} /> Chat</button>
          <button className={`top-nav-button ${activeView === 'reminders' ? 'active' : ''}`} onClick={() => setActiveView('reminders')} type="button"><Clock3 size={15} /> Reminders</button>
          <a className="top-nav-button" href="/settings"><SettingsIcon size={15} /> Settings</a>
        </div>
      </nav>
      <aside className="identity-panel">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <SamidaMark />
          </div>
          <div><h1>SAMIDA</h1><p>Personal assistant</p></div>
        </div>

        <Button className="new-chat-button" onClick={() => void createConversation()}>
          <Plus size={17} /> New chat
        </Button>

        <div className="conversation-list" aria-label="Saved chats">
          <span className="list-label">Chats</span>
          {conversations.length === 0 && <p className="no-chats">No saved chats yet.</p>}
          {conversations.map((conversation) => (
            <div
              className={`conversation-row ${activeConversation?.id === conversation.id ? 'active' : ''}`}
              key={conversation.id}
            >
              {renamingId === conversation.id ? (
                <input
                  aria-label="New name for the chat"
                  className="rename-input"
                  onBlur={() => void saveRename(conversation)}
                  onChange={(event) => setRenameValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveRename(conversation);
                    if (event.key === 'Escape') setRenamingId(null);
                  }}
                  value={renameValue}
                />
              ) : (
                <button
                  className="conversation-open"
                  onClick={() => void openConversation(conversation)}
                  type="button"
                >
                  {conversation.title}
                </button>
              )}
              <button
                aria-label={`Rename ${conversation.title}`}
                className="row-action"
                onClick={() => {
                  setRenamingId(conversation.id);
                  setRenameValue(conversation.title);
                }}
                title="Rename"
                type="button"
              ><Pencil size={14} /></button>
              <button
                aria-label={`Delete ${conversation.title}`}
                className="row-action danger"
                onClick={() => setDeleteTarget(conversation)}
                title="Delete"
                type="button"
              ><Trash2 size={14} /></button>
            </div>
          ))}
        </div>

        <div className="local-note">
          <ShieldCheck size={17} />
          <div><strong>{currentUser?.email}</strong><span>Inloggad</span></div>
          <button
            aria-label="Logga ut"
            className="logout-button"
            onClick={() => void handleLogout()}
            title="Logga ut"
            type="button"
          ><LogOut size={14} /></button>
        </div>
      </aside>

      {activeView === 'reminders' ? <RemindersPanel /> : <section className="chat-workspace">
        <header className="chat-header">
          <div><span className="eyebrow">Chat</span></div>
          <div className={`connection-pill connection-status ${connected ? 'online' : ''}`}>
            <Circle size={9} fill="currentColor" />
            {connected ? 'Connected' : 'Checking connection'}
          </div>
        </header>

        <div className="message-scroll" aria-live="polite">
          <div className="conversation-date">I dag</div>
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={message.id ?? `${index}-${message.role}`}>
              <div className="message-avatar" aria-hidden="true">
                {message.role === 'assistant' ? <BrainCircuit size={18} /> : <UserRound size={18} />}
              </div>
              <div>
                <span className="message-author">{message.role === 'assistant' ? 'SAMIDA' : 'You'}</span>
                {message.image_url && (
                  <img
                    alt="Pasted screenshot"
                    className="message-image"
                    src={message.image_url.startsWith('data:') ? message.image_url : `${API_URL}${message.image_url}`}
                  />
                )}
                {message.ocr_text && (
                  <details className="ocr-details">
                    <summary>Text OCR read from the image</summary>
                    <pre>{message.ocr_text}</pre>
                  </details>
                )}
                {message.content && <p>{message.content}</p>}
                {message.tool_call && (
                  <div className={`tool-call-badge status-${message.tool_call.status}`}>
                    <ShieldCheck size={13} />
                    <span>
                      {message.tool_call.tool_name}
                      {typeof message.tool_call.arguments.path === 'string'
                        ? ` · ${message.tool_call.arguments.path}`
                        : ''}
                      {' · '}
                      {{
                        pending: 'waiting for approval',
                        rejected: 'rejected',
                        executed: 'executed',
                        failed: 'failed',
                        approved: 'approved',
                      }[message.tool_call.status]}
                    </span>
                  </div>
                )}
              </div>
            </article>
          ))}
          {isSending && (
            <article className="message assistant thinking">
              <div className="message-avatar"><BrainCircuit size={18} /></div>
              <div><span className="message-author">SAMIDA</span><div className="thinking-dots" aria-label="SAMIDA is thinking"><i /><i /><i /></div></div>
            </article>
          )}
          <div ref={endRef} />
        </div>

        <div className="composer-wrap">
          {error && <p className="error-message">{error}</p>}
          {pendingImage && (
            <div className="image-preview">
              <img alt="Screenshot to send" src={pendingImage.preview_url} />
              <span><ImageIcon size={15} /> Screenshot attached</span>
              <button aria-label="Remove screenshot" onClick={() => setPendingImage(null)} title="Remove image" type="button"><X size={16} /></button>
            </div>
          )}
          <div className="composer-tabs">
            <Select onValueChange={(value) => setSelectedModel(value as string)} value={selectedModel}>
              <SelectTrigger aria-label="Choose model" className="composer-tab-trigger" size="sm">
                <SelectValue>{(value: string) => modelLabel(value)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {selectableModels.length === 0 && (
                  <SelectItem disabled value="__no_models__">
                    No models yet — add an API key under Settings
                  </SelectItem>
                )}
                {selectableModels.map((model) => (
                  <SelectItem key={model} value={model}>
                    {modelLabel(model)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select onValueChange={(value) => setSelectedProfile(value as string)} value={selectedProfile}>
              <SelectTrigger aria-label="Choose profile" className="composer-tab-trigger" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="minimal">Minimal</SelectItem>
                {currentUser?.is_owner && (
                  <>
                    <SelectItem value="samida-standard">SAMIDA standard</SelectItem>
                    <SelectItem value="coding">Coding</SelectItem>
                    <SelectItem value="jarvis">Jarvis</SelectItem>
                    <SelectItem value="unreal">Unreal</SelectItem>
                  </>
                )}
              </SelectContent>
            </Select>
            <Select onValueChange={(value) => setSelectedSkill(value as string)} value={selectedSkill}>
              <SelectTrigger aria-label="Choose skill" className="composer-tab-trigger" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No skill</SelectItem>
                {skills.map((skill) => (
                  <SelectItem key={skill.name} value={skill.name}>
                    {skill.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <form className="composer" onSubmit={sendMessage}>
            {currentUser?.is_owner && (
              <Popover>
                <PopoverTrigger
                  aria-label="Working directory"
                  className="composer-plus-button"
                  title="Set the working directory SAMIDA can read and edit files in"
                  type="button"
                >
                  <Plus size={18} />
                </PopoverTrigger>
                <PopoverContent>
                  <PopoverTitle>Working directory</PopoverTitle>
                  <PopoverDescription>
                    Lets SAMIDA read and edit files in this folder. Leave empty to disable file tools.
                  </PopoverDescription>
                  <Input
                    onChange={(event) => setWorkingDirectory(event.target.value)}
                    placeholder="/home/you/project"
                    value={workingDirectory}
                  />
                  <Button disabled={pickingWorkspace} onClick={() => void pickWorkspace()} type="button" variant="outline">
                    {pickingWorkspace ? 'Opening…' : 'Choose folder (desktop only)'}
                  </Button>
                </PopoverContent>
              </Popover>
            )}
            <Popover>
              <PopoverTrigger
                aria-label="Local folder"
                className="composer-plus-button"
                title="Let SAMIDA read (and, in Chrome/Edge, write) files in a folder on your own computer"
                type="button"
              >
                {browserWorkspace ? <FolderOpen size={18} /> : <Folder size={18} />}
              </PopoverTrigger>
              <PopoverContent>
                <PopoverTitle>Local folder</PopoverTitle>
                <PopoverDescription>
                  {supportsDirectoryPicker()
                    ? 'SAMIDA can read and write files here, directly in your browser - nothing is sent to the server’s filesystem.'
                    : 'This browser can only read files here; saving a changed file downloads it instead of writing it back.'}
                </PopoverDescription>
                {!supportsDirectoryPicker() && isBrave && (
                  <p className="field-hint">
                    Using Brave? Full read+write is available behind a flag: open brave://flags, search
                    “File System Access API”, set it to Enabled, and relaunch.
                  </p>
                )}
                {browserWorkspace ? (
                  <>
                    <p className="field-hint">Selected: {browserWorkspace.name}</p>
                    <Button onClick={() => setBrowserWorkspace(null)} type="button" variant="outline">
                      Clear
                    </Button>
                  </>
                ) : (
                  <Button disabled={pickingBrowserFolder} onClick={() => void chooseBrowserFolder()} type="button" variant="outline">
                    {pickingBrowserFolder ? 'Opening…' : 'Choose local folder'}
                  </Button>
                )}
              </PopoverContent>
            </Popover>
            <input
              // @ts-expect-error -- webkitdirectory isn't in the standard React input typing
              webkitdirectory=""
              multiple
              onChange={handleBrowserFolderInputChange}
              ref={browserFileInputRef}
              style={{ display: 'none' }}
              type="file"
            />
            <textarea
              aria-label="Message to SAMIDA"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={(event) => void handlePaste(event)}
              placeholder="Type a message or paste a screenshot…"
              rows={1}
              value={draft}
            />
            <Button aria-label="Send message" className="send-button" disabled={(!draft.trim() && !pendingImage) || isSending} size="icon" type="submit"><Send size={18} /></Button>
          </form>
          <p className="composer-hint">Ctrl+V pastes a screenshot · Enter sends</p>
        </div>
      </section>}

      <aside className="context-panel">
        <section className="context-card priority-card"><div className="panel-heading"><Circle size={9} fill="currentColor" /><h3>{currentUser?.is_owner ? 'Active priorities' : 'What SAMIDA can do'}</h3></div><div className="priority-content">{(priorities || 'No priorities set.').split('\n').filter((line) => line.trim() && !line.startsWith('#')).map((line) => <p key={line}>{line.replace(/^- \[[ xX]\]\s*/, '').replace(/^\d+\.\s*/, '')}</p>)}</div></section>
        <section className="usage-card">
          <div className="panel-heading"><Gauge size={18} /><h3>Usage</h3></div>
          <dl className="status-list usage-list">
            <div><dt>Provider</dt><dd>{effectiveProvider}</dd></div>
            <div><dt>Model</dt><dd>{lastUsedModel ?? resolveProviderModel(selectedModel).model}</dd></div>
            <div><dt>This chat</dt><dd>{chatMessageCount} messages</dd></div>
            <div><dt>Tokens</dt><dd>{chatUsage?.total_tokens ?? '–'}</dd></div>
            <div><dt>Limit</dt><dd className="good">{usageStatus}</dd></div>
          </dl>
        </section>
        <section className="context-card">
          <div className="panel-heading"><FileText size={18} /><h3>Context used</h3></div>
          {contextFiles.length ? <ul>{contextFiles.map((file) => <li key={file}>{file}</li>)}</ul> : <p className="empty-context">The files used will show up here after your first message.</p>}
        </section>
      </aside>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this chat?</AlertDialogTitle>
            <AlertDialogDescription>
              The chat &ldquo;{deleteTarget?.title}&rdquo; and its saved screenshots will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction className="delete-confirm" onClick={() => void deleteConversation()}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(pendingToolCall) && !(pendingToolCall?.browser_workspace && pendingToolCall.tool_name !== 'write_file')}
        onOpenChange={(open) => !open && setPendingToolCall(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingToolCall?.tool_name === 'write_file' ? 'SAMIDA wants to write a file' : 'SAMIDA wants to run a tool'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingToolCall?.tool_name === 'write_file'
                ? `Write to "${argText(pendingToolCall.arguments.path)}" in ${
                    pendingToolCall.browser_workspace ? (browserWorkspace?.name ?? 'your local folder') : workingDirectory
                  }. Review the content before approving.`
                : `Tool: ${pendingToolCall?.tool_name ?? ''}.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {pendingToolCall?.tool_name === 'write_file' && (
            <pre className="tool-call-preview">
              {argText(pendingToolCall.arguments.content).slice(0, 800)}
            </pre>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resolvingToolCall} onClick={() => void decideToolCall('reject')}>
              Reject
            </AlertDialogCancel>
            <AlertDialogAction disabled={resolvingToolCall} onClick={() => void decideToolCall('approve')}>
              Approve
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}
