import type { AsrEvent } from "../shared/api";

export type PopupView = "listening" | "loading" | "transcribing" | "inserted" | "empty" | "error";

export interface PopupState {
  view: PopupView;
  message: string;
  recording: boolean;
  modelLoading: boolean;
}

export const initialPopupState: PopupState = {
  view: "listening",
  message: "",
  recording: false,
  modelLoading: false,
};

// Чистая state-машина пилюли: события sidecar и Rust-оболочки переводят её между видами.
// Пока модель грузится, запись уже идёт, поэтому «loading» лишь подменяет волну текстом.
export function reducePopup(state: PopupState, event: AsrEvent): PopupState {
  switch (event.event) {
    case "dictation_starting":
    case "recording_started":
      return { ...state, recording: true, view: state.modelLoading ? "loading" : "listening" };

    case "model_loading":
      // Прогрев модели вне диктовки (при старте приложения) вид не меняет.
      return {
        ...state,
        modelLoading: true,
        view: state.recording || state.view === "transcribing" ? "loading" : state.view,
      };

    case "model_loaded":
      return {
        ...state,
        modelLoading: false,
        view: state.view === "loading" ? (state.recording ? "listening" : "transcribing") : state.view,
      };

    case "recording_stopped":
      return { ...state, recording: false, view: state.modelLoading ? "loading" : "transcribing" };

    case "final_transcript":
      // Пустой результат ничего не вставляет — показываем это вместо «Inserted».
      return (event.text ?? "").trim() ? state : { ...state, view: "empty" };

    case "text_inserted":
      return { ...state, view: "inserted" };

    case "error":
      return {
        ...state,
        recording: false,
        modelLoading: false,
        view: "error",
        message: event.message ?? "Unexpected error",
      };

    default:
      return state;
  }
}
