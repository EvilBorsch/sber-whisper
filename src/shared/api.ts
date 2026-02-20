import { invoke } from "@tauri-apps/api/core";

export interface AppSettings {
  hotkey: string;
  popup_timeout_sec: number;
  auto_launch: boolean;
  language_mode: "ru";
  theme: "siri_aurora";
}

export type AsrEventKind =
  | "ready"
  | "recording_started"
  | "recording_stopped"
  | "partial_transcript"
  | "final_transcript"
  | "job_cancelled"
  | "error"
  | "metrics";

export interface AsrEvent {
  event: AsrEventKind;
  text?: string;
  message?: string;
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

export function openSettings(): Promise<void> {
  return invoke("open_settings_window");
}

export function hideSettings(): Promise<void> {
  return invoke("hide_settings_window");
}
