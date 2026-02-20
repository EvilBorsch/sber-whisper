import React from "react";
import ReactDOM from "react-dom/client";
import { getSettings, hideSettings, saveSettings, type AppSettings } from "../shared/api";
import "./settings.css";

function SettingsApp() {
  const [settings, setSettings] = React.useState<AppSettings | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [status, setStatus] = React.useState("");

  React.useEffect(() => {
    void getSettings().then((value) => setSettings(value));
  }, []);

  if (!settings) {
    return <main className="settings-shell">Loading settings...</main>;
  }

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      const saved = await saveSettings(settings);
      setSettings(saved);
      setStatus("Saved");
    } catch (error) {
      setStatus(`Save failed: ${String(error)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="settings-shell">
      <form className="settings-card" onSubmit={onSave}>
        <h1>Sber Whisper Settings</h1>

        <label>
          <span>Hotkey</span>
          <input
            type="text"
            value={settings.hotkey}
            onChange={(e) => setSettings({ ...settings, hotkey: e.target.value })}
          />
        </label>

        <label>
          <span>Popup timeout (sec)</span>
          <input
            type="number"
            min={1}
            max={120}
            value={settings.popup_timeout_sec}
            onChange={(e) =>
              setSettings({ ...settings, popup_timeout_sec: Number.parseInt(e.target.value, 10) || 10 })
            }
          />
        </label>

        <label className="row-check">
          <input
            type="checkbox"
            checked={settings.auto_launch}
            onChange={(e) => setSettings({ ...settings, auto_launch: e.target.checked })}
          />
          <span>Launch at login</span>
        </label>

        <div className="footer">
          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button type="button" className="secondary" onClick={() => void hideSettings()}>
            Close
          </button>
        </div>

        <p className="status">{status}</p>
      </form>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <SettingsApp />
  </React.StrictMode>,
);
