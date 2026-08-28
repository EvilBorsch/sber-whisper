import React from "react";
import ReactDOM from "react-dom/client";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { cancelCurrent, getSettings, hidePopup, openSettings, type AsrEvent } from "../shared/api";
import "./popup.css";

type UiState = "listening" | "transcribing" | "inserted" | "empty" | "error";

const BAR_COUNT = 32;
const CLOSE_ANIMATION_MS = 180;
const INSERTED_HIDE_MS = 900;
const EMPTY_HIDE_MS = 1100;

function PopupApp() {
  const [state, setState] = React.useState<UiState>("listening");
  const [message, setMessage] = React.useState("");
  const [levels, setLevels] = React.useState<number[]>(() => Array<number>(BAR_COUNT).fill(0));
  const [isVisible, setIsVisible] = React.useState(false);
  const [isClosing, setIsClosing] = React.useState(false);
  const [showKey, setShowKey] = React.useState(0);
  const visibleRef = React.useRef(false);
  const hideTimer = React.useRef<number | null>(null);
  const closeTimer = React.useRef<number | null>(null);
  const errorTimeoutSec = React.useRef(10);
  const stateRef = React.useRef<UiState>("listening");
  stateRef.current = state;

  const cancelPendingHide = React.useCallback(() => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setIsClosing(false);
  }, []);

  const hideNow = React.useCallback(() => {
    if (!visibleRef.current || closeTimer.current !== null) {
      return;
    }
    setIsClosing(true);
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      visibleRef.current = false;
      setIsVisible(false);
      setIsClosing(false);
      void hidePopup();
    }, CLOSE_ANIMATION_MS);
  }, []);

  const scheduleHide = React.useCallback(
    (ms: number) => {
      if (hideTimer.current !== null) {
        window.clearTimeout(hideTimer.current);
      }
      hideTimer.current = window.setTimeout(hideNow, ms);
    },
    [hideNow],
  );

  React.useEffect(() => {
    void getSettings().then((settings) => {
      errorTimeoutSec.current = settings.popup_timeout_sec;
    });

    const setup = async () => {
      const unlisten = await listen<AsrEvent>("asr_event", (event) => {
        const payload = event.payload;

        switch (payload.event) {
          case "dictation_starting":
          case "recording_started":
            cancelPendingHide();
            setLevels(Array<number>(BAR_COUNT).fill(0));
            setState("listening");
            if (!visibleRef.current) {
              setShowKey((value) => value + 1);
            }
            visibleRef.current = true;
            setIsVisible(true);
            break;

          case "audio_level":
            setLevels((prev) => [...prev.slice(1), payload.level ?? 0]);
            break;

          case "recording_stopped":
            setState("transcribing");
            break;

          case "final_transcript":
            // Пустой результат ничего не вставляет — коротко показываем это и прячемся.
            if (!(payload.text ?? "").trim()) {
              setState("empty");
              scheduleHide(EMPTY_HIDE_MS);
            }
            break;

          case "text_inserted":
            setState("inserted");
            scheduleHide(INSERTED_HIDE_MS);
            break;

          case "job_cancelled":
            hideNow();
            break;

          case "error":
            cancelPendingHide();
            setState("error");
            setMessage(payload.message ?? "Unexpected error");
            if (!visibleRef.current) {
              setShowKey((value) => value + 1);
            }
            visibleRef.current = true;
            setIsVisible(true);
            scheduleHide(errorTimeoutSec.current * 1000);
            break;
        }
      });

      return unlisten;
    };

    let current: UnlistenFn | null = null;
    void setup().then((fn) => {
      current = fn;
    });

    return () => {
      cancelPendingHide();
      current?.();
    };
  }, [cancelPendingHide, hideNow, scheduleHide]);

  const onClose = () => {
    if (stateRef.current === "listening" || stateRef.current === "transcribing") {
      void cancelCurrent();
    }
    hideNow();
  };

  return (
    <main className={`shell ${isVisible ? "is-visible" : "is-hidden"} ${isClosing ? "is-closing" : ""}`}>
      <div className={`pill state-${state}`} key={showKey}>
        <span className="dot" aria-hidden="true" />

        {state === "error" || state === "empty" ? (
          <p className="message">{state === "empty" ? "No speech detected" : message}</p>
        ) : state === "inserted" ? (
          <span className="inserted-label">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8.5 L6.5 12 L13 4.5" />
            </svg>
            Inserted
          </span>
        ) : (
          <div className="bars" aria-hidden="true">
            {levels.map((level, i) => (
              <span
                key={i}
                style={{
                  height: `${4 + level * 26}px`,
                  animationDelay: `${i * 45}ms`,
                }}
              />
            ))}
          </div>
        )}

        <div className="actions">
          <button onClick={() => void openSettings()} aria-label="Open settings">
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M10 4 L11.5 4.4 L12.3 5.7 L13.8 5.8 L15 7 L14.7 8.5 L15.6 9.7 L15 11 L13.6 11.3 L12.7 12.7 L11.2 12.8 L10 14 L8.8 12.8 L7.3 12.7 L6.4 11.3 L5 11 L4.4 9.7 L5.3 8.5 L5 7 L6.2 5.8 L7.7 5.7 L8.5 4.4 Z" />
            </svg>
          </button>
          <button onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M6 6 L14 14 M14 6 L6 14" />
            </svg>
          </button>
        </div>
      </div>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <PopupApp />
  </React.StrictMode>,
);
