import React from "react";
import ReactDOM from "react-dom/client";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { getSettings, hidePopup, openSettings, type AsrEvent } from "../shared/api";
import "./popup.css";

type UiState = "idle" | "listening" | "transcribing" | "done" | "error";
const CLOSE_ANIMATION_MS = 180;

function PopupApp() {
  const [state, setState] = React.useState<UiState>("idle");
  const [text, setText] = React.useState("");
  const [detail, setDetail] = React.useState("Waiting for hotkey...");
  const [isClosing, setIsClosing] = React.useState(false);
  const [isVisible, setIsVisible] = React.useState(false);
  const [enterKey, setEnterKey] = React.useState(0);
  const hideTimer = React.useRef<number | null>(null);
  const closeTimer = React.useRef<number | null>(null);
  const timeoutSec = React.useRef(10);
  const visibleRef = React.useRef(false);
  const bars = React.useMemo(() => Array.from({ length: 18 }, (_, i) => i), []);

  const resetUi = React.useCallback(() => {
    setState("idle");
    setText("");
    setDetail("Waiting for hotkey...");
  }, []);

  const clearHideTimer = React.useCallback(() => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const clearCloseTimer = React.useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const hideWithAnimation = React.useCallback(() => {
    if (!visibleRef.current || closeTimer.current !== null) {
      return;
    }

    clearHideTimer();
    setIsClosing(true);
    closeTimer.current = window.setTimeout(() => {
      void hidePopup();
      visibleRef.current = false;
      setIsVisible(false);
      setIsClosing(false);
      resetUi();
      closeTimer.current = null;
    }, CLOSE_ANIMATION_MS);
  }, [clearHideTimer, resetUi]);

  const showWindow = React.useCallback(() => {
    clearCloseTimer();
    if (!visibleRef.current) {
      setEnterKey((value) => value + 1);
    }
    visibleRef.current = true;
    setIsVisible(true);
    setIsClosing(false);
    void getCurrentWebviewWindow().show();
  }, [clearCloseTimer]);

  const scheduleHide = React.useCallback(() => {
    clearHideTimer();
    hideTimer.current = window.setTimeout(() => {
      hideWithAnimation();
    }, timeoutSec.current * 1000);
  }, [clearHideTimer, hideWithAnimation]);

  React.useEffect(() => {
    void getSettings().then((settings) => {
      timeoutSec.current = settings.popup_timeout_sec;
    });

    const setup = async () => {
      const unlisten = await listen<AsrEvent>("asr_event", (event) => {
        const payload = event.payload;
        showWindow();

        if (payload.event === "recording_started") {
          clearHideTimer();
          setIsClosing(false);
          setState("listening");
          setText("");
          setDetail("Listening. Hold hotkey and speak.");
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
          setText("");
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
      if (visibleRef.current) {
        e.preventDefault();
        hideWithAnimation();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      clearHideTimer();
      clearCloseTimer();
      window.removeEventListener("keydown", onKeyDown);
      current?.();
    };
  }, [clearCloseTimer, clearHideTimer, hideWithAnimation, scheduleHide, showWindow]);

  return (
    <main className={`popup-shell state-${state} ${isVisible ? "is-visible" : "is-hidden"} ${isClosing ? "is-closing" : ""}`}>
      <div className="ambient" aria-hidden="true" />
      <div className="card" key={enterKey}>
        <button className="icon-button close" onClick={hideWithAnimation} aria-label="Close">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M5 5 L15 15 M15 5 L5 15" />
          </svg>
        </button>
        <button className="icon-button settings" onClick={() => void openSettings()} aria-label="Open settings">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M10 4 L11.5 4.4 L12.3 5.7 L13.8 5.8 L15 7 L14.7 8.5 L15.6 9.7 L15 11 L13.6 11.3 L12.7 12.7 L11.2 12.8 L10 14 L8.8 12.8 L7.3 12.7 L6.4 11.3 L5 11 L4.4 9.7 L5.3 8.5 L5 7 L6.2 5.8 L7.7 5.7 L8.5 4.4 Z M10 7.5 A2.5 2.5 0 1 0 10 12.5 A2.5 2.5 0 1 0 10 7.5 Z" />
          </svg>
        </button>

        <div className="status-row">
          <span className="status-dot" aria-hidden="true" />
          <p className="detail">{detail}</p>
        </div>

        <div className="visualizer" aria-hidden="true">
          <div className="orb-core" />
          <div className="ring ring-a" />
          <div className="ring ring-b" />
          <div className="wave-bars">
            {bars.map((i) => (
              <span key={i} style={{ animationDelay: `${i * 56}ms` }} />
            ))}
          </div>
        </div>

        <p className={`text ${text ? "has-text" : "is-empty"}`}>{text || " "}</p>
      </div>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <PopupApp />
  </React.StrictMode>,
);
