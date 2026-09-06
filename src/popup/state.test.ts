import { describe, expect, test } from "vitest";
import { initialPopupState, reducePopup, type PopupState } from "./state";
import type { AsrEvent } from "../shared/api";

function replay(events: AsrEvent[], from: PopupState = initialPopupState): PopupState[] {
  const states: PopupState[] = [];
  let state = from;
  for (const event of events) {
    state = reducePopup(state, event);
    states.push(state);
  }
  return states;
}

describe("popup state machine", () => {
  test("cold dictation shows model loading, then listening, then transcribing and inserted", () => {
    const views = replay([
      { event: "dictation_starting" },
      { event: "model_loading" },
      { event: "recording_started" },
      { event: "model_loaded" },
      { event: "recording_stopped" },
      { event: "text_inserted" },
    ]).map((s) => s.view);

    expect(views).toEqual(["listening", "loading", "loading", "listening", "transcribing", "inserted"]);
  });

  test("stopping while model still loads keeps loading view until model is ready", () => {
    const views = replay([
      { event: "dictation_starting" },
      { event: "model_loading" },
      { event: "recording_stopped" },
      { event: "model_loaded" },
      { event: "final_transcript", text: "привет" },
      { event: "text_inserted" },
    ]).map((s) => s.view);

    expect(views).toEqual(["listening", "loading", "loading", "transcribing", "transcribing", "inserted"]);
  });

  test("model preloaded at app start makes next dictation listen immediately", () => {
    const states = replay([
      { event: "model_loading" },
      { event: "model_loaded" },
      { event: "dictation_starting" },
      { event: "recording_started" },
    ]);

    expect(states[states.length - 1].view).toBe("listening");
  });

  test("preload at app start does not change the resting view", () => {
    const states = replay([{ event: "model_loading" }]);
    expect(states[0]).toMatchObject({ view: "listening", modelLoading: true });
  });

  test("dictation started while preload still in progress shows loading", () => {
    const states = replay([{ event: "model_loading" }, { event: "dictation_starting" }]);
    expect(states[states.length - 1].view).toBe("loading");
  });

  test("warm dictation never shows loading", () => {
    const views = replay([
      { event: "dictation_starting" },
      { event: "recording_started" },
      { event: "recording_stopped" },
      { event: "text_inserted" },
    ]).map((s) => s.view);

    expect(views).toEqual(["listening", "listening", "transcribing", "inserted"]);
  });

  test("empty transcript shows empty view", () => {
    const states = replay([
      { event: "dictation_starting" },
      { event: "recording_stopped" },
      { event: "final_transcript", text: "   " },
    ]);
    expect(states[states.length - 1].view).toBe("empty");
  });

  test("error shows message and clears loading flag so next dictation is not stuck", () => {
    const states = replay([
      { event: "dictation_starting" },
      { event: "model_loading" },
      { event: "error", message: "Transcription failed" },
      { event: "dictation_starting" },
    ]);

    expect(states[2]).toMatchObject({ view: "error", message: "Transcription failed", modelLoading: false });
    expect(states[states.length - 1].view).toBe("listening");
  });
});
