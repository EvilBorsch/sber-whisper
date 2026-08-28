import React from "react";
import ReactDOM from "react-dom/client";
import { getSettings, hideSettings, saveSettings, type AppSettings } from "../shared/api";
import "./settings.css";

const HOTKEY_HINT = navigator.platform.startsWith("Mac") ? "Cmd+G" : "Ctrl+G";

function SettingsApp() {
  const [settings, setSettings] = React.useState<AppSettings | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [status, setStatus] = React.useState("");
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    void getSettings().then((value) => setSettings(value));
  }, []);

  if (!settings) {
    return (
      <main className="shell">
        <p className="loading">Loading…</p>
      </main>
    );
  }

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      const saved = await saveSettings(settings);
      setSettings(saved);
      setFailed(false);
      setStatus("Settings saved");
    } catch (error) {
      setFailed(true);
      setStatus(String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="shell">
      <header data-tauri-drag-region>
        <h1 data-tauri-drag-region>Sber Whisper</h1>
        <p data-tauri-drag-region>Press the hotkey to dictate, press it again to insert the text.</p>
      </header>

      <form onSubmit={onSave}>
        <section className="field">
          <div className="field-text">
            <span className="field-label">Hotkey</span>
            <span className="field-hint">Combination like {HOTKEY_HINT}</span>
          </div>
          <input
            type="text"
            className="control control-text"
            spellCheck={false}
            value={settings.hotkey}
            onChange={(e) => setSettings({ ...settings, hotkey: e.target.value })}
          />
        </section>

        <section className="field">
          <div className="field-text">
            <span className="field-label">Error auto-hide</span>
            <span className="field-hint">Seconds before an error message disappears</span>
          </div>
          <input
            type="number"
            className="control control-number"
            min={1}
            max={120}
            value={settings.popup_timeout_sec}
            onChange={(e) =>
              setSettings({ ...settings, popup_timeout_sec: Number.parseInt(e.target.value, 10) || 10 })
            }
          />
        </section>

        <section className="field">
          <div className="field-text">
            <span className="field-label">Model keepalive</span>
            <span className="field-hint">Minutes of idle time before the model unloads from memory</span>
          </div>
          <input
            type="number"
            className="control control-number"
            min={1}
            max={240}
            value={settings.model_keepalive_min}
            onChange={(e) =>
              setSettings({ ...settings, model_keepalive_min: Number.parseInt(e.target.value, 10) || 5 })
            }
          />
        </section>

        <section className="field">
          <div className="field-text">
            <span className="field-label">Launch at login</span>
            <span className="field-hint">Start Sber Whisper automatically</span>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={settings.auto_launch}
              onChange={(e) => setSettings({ ...settings, auto_launch: e.target.checked })}
            />
            <span className="track" aria-hidden="true" />
          </label>
        </section>

        <p className={`status ${failed ? "is-error" : "is-ok"}`}>{status}</p>

        <div className="footer">
          <button type="button" className="secondary" onClick={() => void hideSettings()}>
            Close
          </button>
          <button type="submit" className="primary" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <SettingsApp />
  </React.StrictMode>,
);
