'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, CheckCircle2, KeyRound, Trash2 } from 'lucide-react';

import { fetchCurrentUser, requestJson } from '@/lib/api';
import { SamidaMark } from '@/components/samida-mark';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type ProviderCredential = {
  provider_key: string;
  configured: boolean;
  base_url_override: string | null;
  default_model: string | null;
  updated_at: string | null;
};

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic (Claude)',
  gpt_image: 'GPT Image (OpenAI)',
  flux: 'Flux (Black Forest Labs)',
  nano_banana: 'Nano Banana (Gemini)',
  pollinations: 'Pollinations.ai (free, default)',
};

const PROVIDER_MODEL_PLACEHOLDERS: Record<string, string> = {
  openai: 'gpt-5.6-luna',
  anthropic: 'claude-opus-5',
  gpt_image: 'gpt-image-1',
  flux: 'flux-pro-1.1',
  nano_banana: 'gemini-2.5-flash-image',
  pollinations: 'flux',
};

const PROVIDER_KEY_FIELD_LABELS: Record<string, string> = {
  pollinations: 'API token (optional — removes the watermark, still free)',
};

function ProviderCard({
  credential,
  kind,
  onSaved,
  onRemoved,
}: {
  credential: ProviderCredential;
  kind: 'chat' | 'image';
  onSaved: (updated: ProviderCredential) => void;
  onRemoved: (providerKey: string) => void;
}) {
  const [apiKey, setApiKey] = useState('');
  const [defaultModel, setDefaultModel] = useState(credential.default_model ?? '');
  const [baseUrlOverride, setBaseUrlOverride] = useState(credential.base_url_override ?? '');
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!apiKey.trim()) {
      setError('Please enter an API key.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await requestJson<ProviderCredential>(
        `/api/settings/providers/${credential.provider_key}?kind=${kind}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            api_key: apiKey.trim(),
            base_url_override: baseUrlOverride.trim() || null,
            default_model: defaultModel.trim() || null,
          }),
        },
      );
      setApiKey('');
      onSaved(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the key.');
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove() {
    setRemoving(true);
    setError(null);
    try {
      await requestJson<void>(`/api/settings/providers/${credential.provider_key}?kind=${kind}`, {
        method: 'DELETE',
      });
      onRemoved(credential.provider_key);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove the key.');
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="context-card">
      <div className="panel-heading">
        <KeyRound size={16} />
        <h3>{PROVIDER_LABELS[credential.provider_key] ?? credential.provider_key}</h3>
        {credential.configured && (
          <span className="provider-configured-badge">
            <CheckCircle2 size={13} /> Configured
          </span>
        )}
      </div>
      {error && <p className="auth-error">{error}</p>}
      <div className="auth-form">
        <div className="auth-field">
          <Label htmlFor={`${credential.provider_key}-key`}>
            {PROVIDER_KEY_FIELD_LABELS[credential.provider_key] ?? 'API key'}
            {credential.configured ? ' (replace saved key)' : ''}
          </Label>
          <Input
            id={`${credential.provider_key}-key`}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={credential.configured ? '••••••••••••' : 'sk-…'}
            type="password"
            value={apiKey}
          />
        </div>
        <div className="auth-field">
          <Label htmlFor={`${credential.provider_key}-model`}>Default model (optional)</Label>
          <Input
            id={`${credential.provider_key}-model`}
            onChange={(event) => setDefaultModel(event.target.value)}
            placeholder={`e.g. ${PROVIDER_MODEL_PLACEHOLDERS[credential.provider_key] ?? ''}`}
            value={defaultModel}
          />
          <span className="field-hint">Use the provider&apos;s technical model ID, not its marketing name.</span>
        </div>
        <div className="auth-field">
          <Label htmlFor={`${credential.provider_key}-base-url`}>Custom base URL (optional)</Label>
          <Input
            id={`${credential.provider_key}-base-url`}
            onChange={(event) => setBaseUrlOverride(event.target.value)}
            value={baseUrlOverride}
          />
        </div>
        <div className="provider-card-actions">
          <Button disabled={saving} onClick={() => void handleSave()} type="button">
            {saving ? 'Saving…' : 'Save'}
          </Button>
          {credential.configured && (
            <Button
              disabled={removing}
              onClick={() => void handleRemove()}
              type="button"
              variant="destructive"
            >
              <Trash2 size={14} /> {removing ? 'Removing…' : 'Remove'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function resetCredential(credential: ProviderCredential): ProviderCredential {
  return { ...credential, configured: false, base_url_override: null, default_model: null, updated_at: null };
}

export default function SettingsPage() {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [chatCredentials, setChatCredentials] = useState<ProviderCredential[]>([]);
  const [imageCredentials, setImageCredentials] = useState<ProviderCredential[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadCredentials = useCallback(async () => {
    try {
      const [chat, image] = await Promise.all([
        requestJson<ProviderCredential[]>('/api/settings/providers?kind=chat'),
        requestJson<ProviderCredential[]>('/api/settings/providers?kind=image'),
      ]);
      setChatCredentials(chat);
      setImageCredentials(image);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'Could not load settings.');
    }
  }, []);

  useEffect(() => {
    void fetchCurrentUser().then((user) => {
      if (!user) {
        router.push('/login');
        return;
      }
      setAuthChecked(true);
      void loadCredentials();
    });
  }, [router, loadCredentials]);

  if (!authChecked) {
    return <main className="app-shell" />;
  }

  return (
    <main className="settings-page">
      <header className="settings-header">
        <a className="settings-back" href="/"><ArrowLeft size={16} /> Back to chat</a>
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <SamidaMark />
          </div>
          <div><h1>SAMIDA</h1><p>Settings</p></div>
        </div>
      </header>
      <section className="settings-content">
        <h2>Model providers</h2>
        <p className="settings-intro">
          OpenAI and Anthropic require your own API key — it&apos;s stored encrypted and only used for your own chats.
          Ollama is always available without a key.
        </p>
        {loadError && <p className="auth-error">{loadError}</p>}
        <div className="provider-card-grid">
          {chatCredentials.map((credential) => (
            <ProviderCard
              credential={credential}
              key={credential.provider_key}
              kind="chat"
              onRemoved={(providerKey) =>
                setChatCredentials((current) =>
                  current.map((item) => (item.provider_key === providerKey ? resetCredential(item) : item)),
                )
              }
              onSaved={(updated) =>
                setChatCredentials((current) =>
                  current.map((item) => (item.provider_key === updated.provider_key ? updated : item)),
                )
              }
            />
          ))}
        </div>

        <h2 className="settings-section-heading">Image generation</h2>
        <p className="settings-intro">
          Image generation works out of the box using Pollinations.ai — free, no key needed (images get a
          small watermark; add a free Pollinations token below to remove it). Add a key for one of the
          other providers instead if you want higher quality — if you configure more than one, GPT Image
          is used first, then Flux, then Gemini.
        </p>
        <div className="provider-card-grid">
          {imageCredentials.map((credential) => (
            <ProviderCard
              credential={credential}
              key={credential.provider_key}
              kind="image"
              onRemoved={(providerKey) =>
                setImageCredentials((current) =>
                  current.map((item) => (item.provider_key === providerKey ? resetCredential(item) : item)),
                )
              }
              onSaved={(updated) =>
                setImageCredentials((current) =>
                  current.map((item) => (item.provider_key === updated.provider_key ? updated : item)),
                )
              }
            />
          ))}
        </div>
      </section>
    </main>
  );
}
