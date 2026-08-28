import { invoke } from "@tauri-apps/api/core";

export interface AppSettings {
  hotkey: string;
  popup_timeout_sec: number;
  model_keepalive_min: number;
  auto_launch: boolean;
  language_mode: "ru";
  theme: "siri_aurora";
}

export type AsrEventKind =
  | "ready"
  | "dictation_starting"
  | "recording_started"
  | "recording_stopped"
  | "audio_level"
  | "final_transcript"
  | "text_inserted"
  | "job_cancelled"
  | "error"
  | "metrics";

export interface AsrEvent {
  event: AsrEventKind;
  text?: string;
  message?: string;
  level?: number;
  device?: string;
  model?: string;
  latency_ms?: number;
}

export function getSettings(): Promise<AppSettings> {
  return invoke("get_settings");
}

export function saveSettings(settings: AppSettings): Promise<AppSettings> {
  return invoke("save_settings", { settings });
}

export function hidePopup(): Promise<void> {
  return invoke("hide_popup");
}

export function cancelCurrent(): Promise<void> {
  return invoke("cancel_current");
}

export function openSettings(): Promise<void> {
  return invoke("open_settings_window");
}

export function hideSettings(): Promise<void> {
  return invoke("hide_settings_window");
}
