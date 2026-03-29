import { useReducer } from "react";
import type { SecondSelfProfile } from "@/lib/api";

export interface WizardState {
  step: number;
  name: string;
  role: string;
  sessionId: string;
  email: string;
  profile: SecondSelfProfile | null;
}

type WizardAction =
  | { type: "NEXT" }
  | { type: "BACK" }
  | { type: "SET_USER"; name: string; role: string }
  | { type: "SET_SESSION"; sessionId: string; email: string }
  | { type: "SET_PROFILE"; profile: SecondSelfProfile }
  | { type: "RESET" };

const initialState: WizardState = {
  step: 0,
  name: "",
  role: "",
  sessionId: "",
  email: "",
  profile: null,
};

function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "NEXT":
      return { ...state, step: Math.min(state.step + 1, 5) };
    case "BACK":
      return { ...state, step: Math.max(state.step - 1, 0) };
    case "SET_USER":
      return { ...state, step: 2, name: action.name, role: action.role };
    case "SET_SESSION":
      return { ...state, sessionId: action.sessionId, email: action.email };
    case "SET_PROFILE":
      return { ...state, profile: action.profile };
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

export function useWizardState() {
  const [state, dispatch] = useReducer(wizardReducer, initialState);

  const next = () => dispatch({ type: "NEXT" });
  const back = () => dispatch({ type: "BACK" });
  const setUser = (name: string, role: string) =>
    dispatch({ type: "SET_USER", name, role });
  const setSession = (sessionId: string, email: string) =>
    dispatch({ type: "SET_SESSION", sessionId, email });
  const setProfile = (profile: SecondSelfProfile) =>
    dispatch({ type: "SET_PROFILE", profile });
  const reset = () => dispatch({ type: "RESET" });

  return { state, next, back, setUser, setSession, setProfile, reset };
}
