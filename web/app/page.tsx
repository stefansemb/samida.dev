'use client';
/* oxlint-disable next/no-img-element -- local images need direct browser rendering. */

import {
  ClipboardEvent,
  KeyboardEvent,
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  BrainCircuit,
  Circle,
  Clock3,
  ExternalLink,
  FileText,
  Gauge,
  Image as ImageIcon,
  Radar,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
  UserRound,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
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

type PendingToolCall = {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: 'low' | 'medium';
  status: 'pending' | 'approved' | 'rejected' | 'executed' | 'failed';
  created_at: string;
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
type Health = {
  status: 'ok' | 'degraded';
  ollama_reachable: boolean;
  configured_model: string;
  model_available: boolean;
  configured_vision_model: string;
  vision_model_available: boolean;
  available_models: string[];
  openai_configured: boolean;
  anthropic_configured: boolean;
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
type WebMcpTool = {
  name: string;
  title: string;
  description: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute(input: unknown): unknown;
};

type AppView = 'chat' | 'reminders' | 'research';
type ResearchReport = {
  id: string;
  created_at: string;
  title: string;
  content: string;
  sources: string[];
  research_type: ResearchType;
};
type ResearchType = 'ai_general' | 'mobile_apps';

function SamidaMark() {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="31"
      viewBox="0 0 32 32"
      width="31"
    >
      <path
        d="M4.5 8A4.5 4.5 0 0 1 9 3.5h14A4.5 4.5 0 0 1 27.5 8v9A4.5 4.5 0 0 1 23 21.5h-6.2L9 27v-5.7a4.5 4.5 0 0 1-4.5-4.3V8Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
      <path
        d="M10 11.5h1m9 0h1M9.5 15.5h13m-6.5 6v3m-4-1h8"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.7"
      />
      <circle cx="10.5" cy="11.5" fill="currentColor" r="1.35" />
      <circle cx="21.5" cy="11.5" fill="currentColor" r="1.35" />
    </svg>
  );
}

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(
        tool: WebMcpTool,
        options?: { signal?: AbortSignal },
      ): void | Promise<void>;
    };
  }
}

const API_URL =
  process.env.NEXT_PUBLIC_SAMIDA_API_URL ?? 'http://127.0.0.1:8000';
const DEFAULT_MODEL = 'gemma4:e4b';
const greeting: Message = {
  role: 'assistant',
  content:
    'Hej Stefan. Jag är ansluten lokalt och redo att hjälpa dig. Vad vill du arbeta med?',
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const failure: unknown = await response.json().catch(() => null);
    const detail =
      typeof failure === 'object' && failure !== null && 'detail' in failure
        ? failure.detail
        : null;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : 'SAMIDA kunde inte genomföra åtgärden.',
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

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
  if (provider === 'anthropic') return `Claude · ${name}`;
  return model;
}

function fileToImage(file: File): Promise<PendingImage> {
  return new Promise((resolve, reject) => {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      reject(new Error('Använd PNG, JPEG eller WebP.'));
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      reject(new Error('Skärmdumpen får vara högst 10 MB.'));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Skärmdumpen kunde inte läsas.'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('Skärmdumpen kunde inte läsas.'));
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

function ResearchPanel() {
  const [researchType, setResearchType] = useState<ResearchType>('ai_general');
  const [reports, setReports] = useState<ResearchReport[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadRequestRef = useRef(0);
  const researchTypeRef = useRef<ResearchType>('ai_general');

  useEffect(() => {
    const requestId = ++loadRequestRef.current;
    const controller = new AbortController();
    void requestJson<ResearchReport[]>(`/api/research/reports?research_type=${researchType}`, { signal: controller.signal })
      .then((loaded) => {
        if (requestId === loadRequestRef.current) setReports(loaded);
      })
      .catch((caught) => {
        if (requestId === loadRequestRef.current && !(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(caught instanceof Error ? caught.message : 'Rapporterna kunde inte läsas.');
        }
      });
    return () => controller.abort();
  }, [researchType]);

  function selectResearchType(next: ResearchType) {
    researchTypeRef.current = next;
    loadRequestRef.current += 1;
    setResearchType(next);
    setReports([]);
    setSelectedReportId(null);
    setError(null);
  }

  async function runResearch() {
    const requestedType = researchTypeRef.current;
    setIsRunning(true);
    setError(null);
    try {
      const report = await requestJson<ResearchReport>(`/api/research/run?research_type=${requestedType}`, { method: 'POST' });
      if (researchTypeRef.current === requestedType) {
        setReports((current) => [report, ...current]);
        setSelectedReportId(report.id);
      }
    } catch (caught) {
      if (researchTypeRef.current === requestedType) {
        setError(caught instanceof Error ? caught.message : 'Research kunde inte köras.');
      }
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="research-workspace">
      <header className="research-header">
        <div>
          <span className="eyebrow">Omvärldsbevakning</span>
          <h2>{researchType === 'mobile_apps' ? 'Mobilappar & trender' : 'AI-research'}</h2>
          <p>{researchType === 'mobile_apps' ? 'Veckovis spaning efter trendande appar, verklig efterfrågan och produktluckor.' : 'Daglig bevakning av sådant som är nytt, användbart och värt att följa inom AI.'}</p>
        </div>
        <button className="research-action" disabled={isRunning} onClick={() => void runResearch()} type="button">
          <RefreshCw className={isRunning ? 'spin' : ''} size={16} /> {isRunning ? 'Research körs...' : 'Kör nu'}
        </button>
      </header>

      <div className="research-content">
        <div className="research-type-tabs" role="tablist" aria-label="Researchtyp">
          <button className={researchType === 'ai_general' ? 'active' : ''} onClick={() => selectResearchType('ai_general')} role="tab" type="button">AI och teknik</button>
          <button className={researchType === 'mobile_apps' ? 'active' : ''} onClick={() => selectResearchType('mobile_apps')} role="tab" type="button">Mobilappar & trender</button>
        </div>
        <section className="research-hero">
          <div className="research-hero-icon"><Radar size={28} /></div>
          <div>
            <span className="eyebrow">{researchType === 'mobile_apps' ? 'Veckovis research' : 'Daglig research'}</span>
            <h3>{researchType === 'mobile_apps' ? 'Hitta appbehov värda att bygga för' : 'Följ AI-utvecklingen praktiskt'}</h3>
            <p>
              {researchType === 'mobile_apps' ? 'Rapporterna letar efter efterfrågan, återkommande problem, konkurrenter och små MVP:er. Din personliga träningsapp behandlas separat från marknadsidéerna.' : 'Här kommer dagliga rapporter om AI-plattformar, GitHub-projekt, plugins, agenter, lokala modeller och nya möjligheter.'}
            </p>
          </div>
        </section>

        <div className="research-grid">
          <section className="research-card">
            <div className="panel-heading"><Clock3 size={18} /><h3>Rapporthistorik</h3></div>
            {error && <p className="research-error">{error}</p>}
            {reports.length === 0 && !error && <p className="empty-research">Inga rapporter ännu. Kör den första researchen med knappen ovan.</p>}
            {reports.length > 0 && <div className="report-list">{reports.map((report) => <button className={`report-item ${selectedReportId === report.id ? 'active' : ''}`} key={report.id} onClick={() => setSelectedReportId(report.id)} type="button"><strong>{report.title}</strong><span>{new Date(report.created_at).toLocaleString('sv-SE')}</span></button>)}</div>}
          </section>
          <section className="research-card">
            <div className="panel-heading"><FileText size={18} /><h3>Bevakningsområden</h3></div>
            <ul className="research-topics">{researchType === 'mobile_apps' ? <><li>Trendande mobilappar</li><li>Användarbehov och efterfrågan</li><li>Konkurrenter och marknadsluckor</li><li>Lovande MVP-idéer</li><li>Hållbara trender kontra hype</li></> : <><li>AI-plattformar och trender</li><li>GitHub-projekt och plugins</li><li>AI-agenter och system</li><li>Lokala LLM-modeller</li><li>Praktiska sätt att använda AI</li></>}</ul>
          </section>
        </div>

        {reports.find((report) => report.id === selectedReportId) && (() => {
          const report = reports.find((item) => item.id === selectedReportId)!;
          return (
            <article className="report-view">
              <div className="report-view-heading">
                <div><span className="eyebrow">Vald rapport</span><h3>{report.title}</h3></div>
                <span>{new Date(report.created_at).toLocaleString('sv-SE')}</span>
              </div>
              <div className="report-content">{report.content}</div>
              <div className="report-sources">
                <strong>Källor</strong>
                {report.sources.map((source) => <a href={source} key={source} rel="noreferrer" target="_blank">{source} <ExternalLink size={12} /></a>)}
              </div>
            </article>
          );
        })()}

        <p className="research-note"><ExternalLink size={14} /> Källor och länkar visas tillsammans med varje framtida rapport.</p>
      </div>
    </section>
  );
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
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && !sessionStorage.getItem(key)) { new Notification('SAMIDA-påminnelse', { body: r.text }); sessionStorage.setItem(key, '1'); }
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
      <header className="research-header"><div><span className="eyebrow">Planering</span><h2>Reminders</h2><p>Skapa och hantera dina lokala påminnelser.</p></div></header>
      <div className="reminder-event-control"><label>Händelse kl.<input type="datetime-local" value={eventAt} onChange={(e) => setEventAt(e.target.value)} /></label><span>Påminnelsen ställs in i fältet När nedan.</span></div>
      <div className="research-content"><section className="research-card"><form onSubmit={(e) => void addReminder(e)} className="reminder-form"><label>Påminnelse<input value={text} onChange={(e) => setText(e.target.value)} placeholder="Vad ska du komma ihåg?" required /></label><label>När<input type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} required /></label><label>Återkomst<select value={recurrence} onChange={(e) => setRecurrence(e.target.value)}><option value="once">En gång</option><option value="daily">Dagligen</option><option value="weekly">Veckovis</option><option value="monthly">Månadsvis</option><option value="monthly_range">Dagspann varje månad</option></select></label>{recurrence === 'monthly_range' && <><label>Från dag<input type="number" min="1" max="31" value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} /></label><label>Till dag<input type="number" min="1" max="31" value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} /></label></>}<button className="reminder-submit" type="submit">+ Lägg till</button></form>{reminders.length === 0 ? <p className="empty-research">Inga påminnelser ännu. Lägg till din första ovan.</p> : reminders.map((r) => <div key={r.id} className="reminder-item"><span>{r.done ? '✓' : '○'} {r.text}<small>{r.due_at} · {r.recurrence}</small></span><span>{!r.done && <button onClick={() => void complete(r.id)} type="button">Klar</button>} <button onClick={() => void remove(r.id)} type="button">Ta bort</button></span></div>)}</section></div>
    </section>
  );
}

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([greeting]);
  const [draft, setDraft] = useState('');
  const [pendingImage, setPendingImage] = useState<PendingImage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [priorities, setPriorities] = useState('');
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);
  const [selectedProfile, setSelectedProfile] = useState('minimal');
  const [workingDirectory, setWorkingDirectory] = useState('C:\\AiProjects\\SAMIDA');
  const [pickingWorkspace, setPickingWorkspace] = useState(false);
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
  const endRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);
  const activeRef = useRef<Conversation | null>(null);

  const refreshConversations = useCallback(async () => {
    const items = await requestJson<Conversation[]>('/api/conversations');
    setConversations(items);
    return items;
  }, []);

  /* oxlint-disable react/react-compiler -- initial data loading synchronizes API state. */
  useEffect(() => {
    void requestJson<{content:string}>('/api/priorities').then((r) => setPriorities(r.content)).catch(() => undefined);
  }, []);
  useEffect(() => {
    void refreshConversations().catch((caught) =>
      startTransition(() => setError(caught.message)),
    );
    requestJson<Health>('/api/health')
      .then((result) => startTransition(() => setHealth(result)))
      .catch(() => startTransition(() => setHealth(null)));
  }, [refreshConversations]);
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
      body: JSON.stringify({ title: 'Ny chatt' }),
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

  async function decideToolCall(decision: 'approve' | 'reject') {
    const conversation = activeRef.current;
    if (!pendingToolCall || !conversation) return;
    setResolvingToolCall(true);
    try {
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
      if (!normalized && !image) throw new Error('Skriv något eller klistra in en bild.');
      if (sendingRef.current) throw new Error('SAMIDA arbetar redan med ett svar.');

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
                working_directory: workingDirectory.trim() || null,
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
          caught instanceof Error ? caught : new Error('Ett okänt fel inträffade.');
        setError(failure.message);
        throw failure;
      } finally {
        sendingRef.current = false;
        setIsSending(false);
      }
    },
    [createConversation, refreshConversations, selectedModel, selectedProfile, workingDirectory],
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
      const result = await requestJson<{ path: string | null }>('/api/workspace/pick', { method: 'POST' });
      if (result.path) setWorkingDirectory(result.path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Katalogen kunde inte väljas.');
    } finally {
      setPickingWorkspace(false);
    }
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
      setError(caught instanceof Error ? caught.message : 'Bilden kunde inte läsas.');
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
          title: 'Skicka chattmeddelande',
          description: 'Skicka ett textmeddelande till den aktiva SAMIDA-chatten.',
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
              throw new Error('message måste vara en textsträng.');
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
  const usageStatus = lastUsedProvider === 'openai' || lastUsedProvider === 'anthropic'
    ? 'Se API-dashboard'
    : 'Ingen molnlimit';
  const availableModels = Array.from(
    new Set([
      ...(health?.available_models ?? []),
      health?.configured_model ?? DEFAULT_MODEL,
      health?.configured_vision_model ?? 'qwen3-vl:8b',
    ]),
  );
  if (health?.openai_configured) {
    availableModels.push(
      'openai:gpt-5.6-luna',
      'openai:gpt-5.6-terra',
      'openai:gpt-5.6-sol',
    );
  }
  if (health?.anthropic_configured) {
    availableModels.push(
      'anthropic:claude-opus-5',
      'anthropic:claude-sonnet-5',
      'anthropic:claude-haiku-4-5',
    );
  }
  const selectableModels = availableModels.filter((model) => {
    const normalized = model.toLowerCase();
    return !normalized.includes('cloud') && !normalized.startsWith('bge-');
  });

  return (
    <main className="app-shell">
      <nav className="top-nav" aria-label="SAMIDA-sektioner">
        <button className={`top-nav-button ${activeView === 'chat' ? 'active' : ''}`} onClick={() => setActiveView('chat')} type="button"><BrainCircuit size={15} /> Chatt</button>
        <button className={`top-nav-button ${activeView === 'reminders' ? 'active' : ''}`} onClick={() => setActiveView('reminders')} type="button"><Clock3 size={15} /> Reminders</button>
        <button className={`top-nav-button ${activeView === 'research' ? 'active' : ''}`} onClick={() => setActiveView('research')} type="button"><Radar size={15} /> Research</button>
      </nav>
      <aside className="identity-panel">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <SamidaMark />
          </div>
          <div><h1>SAMIDA</h1><p>Lokal assistent</p></div>
        </div>

        <Button className="new-chat-button" onClick={() => void createConversation()}>
          <Plus size={17} /> Ny chatt
        </Button>

        <div className="conversation-list" aria-label="Sparade chattar">
          <span className="list-label">Chattar</span>
          {conversations.length === 0 && <p className="no-chats">Inga sparade chattar ännu.</p>}
          {conversations.map((conversation) => (
            <div
              className={`conversation-row ${activeConversation?.id === conversation.id ? 'active' : ''}`}
              key={conversation.id}
            >
              {renamingId === conversation.id ? (
                <input
                  aria-label="Nytt namn på chatten"
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
                aria-label={`Byt namn på ${conversation.title}`}
                className="row-action"
                onClick={() => {
                  setRenamingId(conversation.id);
                  setRenameValue(conversation.title);
                }}
                title="Byt namn"
                type="button"
              ><Pencil size={14} /></button>
              <button
                aria-label={`Ta bort ${conversation.title}`}
                className="row-action danger"
                onClick={() => setDeleteTarget(conversation)}
                title="Ta bort"
                type="button"
              ><Trash2 size={14} /></button>
            </div>
          ))}
        </div>

        <div className="local-note">
          <ShieldCheck size={17} />
          <div><strong>Lokalt läge</strong><span>Minne och chattar sparas på datorn.</span></div>
        </div>
      </aside>

      {activeView === 'research' ? <ResearchPanel /> : activeView === 'reminders' ? <RemindersPanel /> : <section className="chat-workspace">
        <header className="chat-header">
          <div><span className="eyebrow">Chatt</span></div>
          <div className="header-actions">
            <label className="model-picker">
              <span>Modell</span>
              <select
                aria-label="Välj modell"
                onChange={(event) => setSelectedModel(event.target.value)}
                value={selectedModel}
              >
                {selectableModels.map((model) => (
                  <option key={model} value={model}>
                    {modelLabel(model)}
                  </option>
                ))}
              </select>
            </label>
            <label className="model-picker">
              <span>Profil</span>
              <select aria-label="Välj profil" onChange={(event) => setSelectedProfile(event.target.value)} value={selectedProfile}>
                <option value="minimal">Minimal</option>
                <option value="samida-standard">SAMIDA-standard</option>
                <option value="coding">Kodning</option>
                <option value="jarvis">Jarvis</option>
                <option value="unreal">Unreal</option>
              </select>
            </label>
            <label className="model-picker workspace-picker">
              <span>Arbetskatalog</span>
              <input aria-label="Arbetskatalog" readOnly value={workingDirectory} />
              <button className="row-action" disabled={pickingWorkspace} onClick={() => void pickWorkspace()} type="button">{pickingWorkspace ? '...' : 'Välj'}</button>
            </label>
          </div>
          <div className={`connection-pill connection-status ${connected ? 'online' : ''}`}>
            <Circle size={9} fill="currentColor" />
            {connected ? 'Ansluten' : 'Kontrollerar anslutning'}
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
                <span className="message-author">{message.role === 'assistant' ? 'SAMIDA' : 'Stefan'}</span>
                {message.image_url && (
                  <img
                    alt="Inklistrad skärmdump"
                    className="message-image"
                    src={message.image_url.startsWith('data:') ? message.image_url : `${API_URL}${message.image_url}`}
                  />
                )}
                {message.ocr_text && (
                  <details className="ocr-details">
                    <summary>Text som OCR läste ur bilden</summary>
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
                        pending: 'väntar på godkännande',
                        rejected: 'avvisad',
                        executed: 'utförd',
                        failed: 'misslyckades',
                        approved: 'godkänd',
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
              <div><span className="message-author">SAMIDA</span><div className="thinking-dots" aria-label="SAMIDA tänker"><i /><i /><i /></div></div>
            </article>
          )}
          <div ref={endRef} />
        </div>

        <div className="composer-wrap">
          {error && <p className="error-message">{error}</p>}
          {pendingImage && (
            <div className="image-preview">
              <img alt="Skärmdump som ska skickas" src={pendingImage.preview_url} />
              <span><ImageIcon size={15} /> Skärmdump bifogad</span>
              <button aria-label="Ta bort skärmdump" onClick={() => setPendingImage(null)} title="Ta bort bild" type="button"><X size={16} /></button>
            </div>
          )}
          <form className="composer" onSubmit={sendMessage}>
            <textarea
              aria-label="Meddelande till SAMIDA"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={(event) => void handlePaste(event)}
              placeholder="Skriv eller klistra in en skärmdump…"
              rows={1}
              value={draft}
            />
            <Button aria-label="Skicka meddelande" className="send-button" disabled={(!draft.trim() && !pendingImage) || isSending} size="icon" type="submit"><Send size={18} /></Button>
          </form>
          <p className="composer-hint">Ctrl + V klistrar in en skärmdump · Enter skickar</p>
        </div>
      </section>}

      <aside className="context-panel">
        <section className="context-card priority-card"><div className="panel-heading"><Circle size={9} fill="currentColor" /><h3>Active priorities</h3></div><div className="priority-content">{(priorities || 'Inga prioriteringar.').split('\n').filter((line) => line.trim() && !line.startsWith('#')).map((line) => <p key={line}>{line.replace(/^- \[[ xX]\]\s*/, '').replace(/^\d+\.\s*/, '')}</p>)}</div></section>
        <section className="usage-card">
          <div className="panel-heading"><Gauge size={18} /><h3>Usage</h3></div>
          <dl className="status-list usage-list">
            <div><dt>Provider</dt><dd>{lastUsedProvider ?? 'ollama'}</dd></div>
            <div><dt>Modell</dt><dd>{lastUsedModel ?? health?.configured_model ?? 'gemma4:e4b'}</dd></div>
            <div><dt>Denna chatt</dt><dd>{chatMessageCount} meddelanden</dd></div>
            <div><dt>Tokens</dt><dd>{chatUsage?.total_tokens ?? '–'}</dd></div>
            <div><dt>Limit</dt><dd className="good">{usageStatus}</dd></div>
          </dl>
        </section>
        <section className="context-card">
          <div className="panel-heading"><FileText size={18} /><h3>Använd kontext</h3></div>
          {contextFiles.length ? <ul>{contextFiles.map((file) => <li key={file}>{file}</li>)}</ul> : <p className="empty-context">Filerna som används visas här efter ditt första meddelande.</p>}
        </section>
      </aside>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Ta bort chatten?</AlertDialogTitle>
            <AlertDialogDescription>
              Chatten ”{deleteTarget?.title}” och dess sparade skärmdumpar tas bort permanent.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Avbryt</AlertDialogCancel>
            <AlertDialogAction className="delete-confirm" onClick={() => void deleteConversation()}>Ta bort</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(pendingToolCall)}
        onOpenChange={(open) => !open && setPendingToolCall(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingToolCall?.tool_name === 'write_file' ? 'SAMIDA vill skriva en fil' : 'SAMIDA vill köra ett verktyg'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingToolCall?.tool_name === 'write_file'
                ? `Skriva till "${argText(pendingToolCall.arguments.path)}" i ${workingDirectory}. Granska innehållet innan du godkänner.`
                : `Verktyg: ${pendingToolCall?.tool_name ?? ''}.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {pendingToolCall?.tool_name === 'write_file' && (
            <pre className="tool-call-preview">
              {argText(pendingToolCall.arguments.content).slice(0, 800)}
            </pre>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resolvingToolCall} onClick={() => void decideToolCall('reject')}>
              Avvisa
            </AlertDialogCancel>
            <AlertDialogAction disabled={resolvingToolCall} onClick={() => void decideToolCall('approve')}>
              Godkänn
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}
