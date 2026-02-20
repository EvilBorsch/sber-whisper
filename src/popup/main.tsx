import React from "react";
import ReactDOM from "react-dom/client";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { getSettings, hidePopup, openSettings, type AsrEvent } from "../shared/api";
import "./popup.css";

type UiState = "idle" | "listening" | "transcribing" | "done" | "error";

function PopupApp() {
  const [state, setState] = React.useState<UiState>("idle");
  const [text, setText] = React.useState("");
  const [detail, setDetail] = React.useState("Waiting for hotkey...");
  const hideTimer = React.useRef<number | null>(null);
  const timeoutSec = React.useRef(10);

  const clearHideTimer = React.useCallback(() => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const scheduleHide = React.useCallback(() => {
    clearHideTimer();
    hideTimer.current = window.setTimeout(() => {
      void hidePopup();
      setState("idle");
      setText("");
      setDetail("Waiting for hotkey...");
    }, timeoutSec.current * 1000);
  }, [clearHideTimer]);

  React.useEffect(() => {
    void getSettings().then((settings) => {
      timeoutSec.current = settings.popup_timeout_sec;
    });

    const setup = async () => {
      const unlisten = await listen<AsrEvent>("asr_event", (event) => {
        const payload = event.payload;
        void getCurrentWebviewWindow().show();

        if (payload.event === "recording_started") {
          clearHideTimer();
          setState("listening");
          setText("");
          setDetail("Listening...");
          return;
        }

        if (payload.event === "recording_stopped") {
          setState("transcribing");
          setDetail("Transcribing...");
          return;
        }

        if (payload.event === "partial_transcript") {
          setState("transcribing");
          setText(payload.text ?? "");
          setDetail("Transcribing...");
          return;
        }

        if (payload.event === "final_transcript") {
          setState("done");
          setText(payload.text ?? "");
          setDetail("Copied to clipboard");
          scheduleHide();
          return;
        }

        if (payload.event === "job_cancelled") {
          setState("idle");
          setText("");
          setDetail("Cancelled");
          scheduleHide();
          return;
        }

        if (payload.event === "error") {
          setState("error");
          setDetail(payload.message ?? "Unexpected error");
          scheduleHide();
          return;
        }
      });

      return unlisten;
    };

    let current: UnlistenFn | null = null;
    void setup().then((fn) => {
      current = fn;
    });

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key.length === 1 || e.key === "Escape" || e.key === "Enter") {
        void hidePopup();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      clearHideTimer();
      window.removeEventListener("keydown", onKeyDown);
      current?.();
    };
  }, [clearHideTimer, scheduleHide]);

  return (
    <main className={`popup-shell state-${state}`}>
      <div className="nebula" aria-hidden="true" />
      <div className="card">
        <button className="close" onClick={() => void hidePopup()} aria-label="Close">
          x
        </button>
        <button className="settings" onClick={() => void openSettings()} aria-label="Open settings">
          S
        </button>

        <div className="orb-wrap" aria-hidden="true">
          <div className="orb" />
          <div className="pulse" />
        </div>

        <p className="detail">{detail}</p>
        <p className="text">{text || " "}</p>
      </div>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <PopupApp />
  </React.StrictMode>,
);
