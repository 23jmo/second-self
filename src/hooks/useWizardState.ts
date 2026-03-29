import { useReducer } from "react";

export interface WizardState {
  step: number;
  name: string;
  role: string;
}

type WizardAction =
  | { type: "NEXT" }
  | { type: "SET_USER"; name: string; role: string }
  | { type: "RESET" };

const initialState: WizardState = {
  step: 0,
  name: "",
  role: "",
};

function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "NEXT":
      return { ...state, step: Math.min(state.step + 1, 4) };
    case "SET_USER":
      return { ...state, step: 2, name: action.name, role: action.role };
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

export function useWizardState() {
  const [state, dispatch] = useReducer(wizardReducer, initialState);

  const next = () => dispatch({ type: "NEXT" });
  const setUser = (name: string, role: string) =>
    dispatch({ type: "SET_USER", name, role });
  const reset = () => dispatch({ type: "RESET" });

  return { state, next, setUser, reset };
}
