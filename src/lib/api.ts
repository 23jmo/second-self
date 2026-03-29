// API client for the FastAPI backend (proxied through /api)

export interface SecondSelfProfile {
  identity: { name: string; role: string; company: string };
  voice: {
    formality: string;
    avg_email_length: string;
    signature_phrases: string[];
    opens_with: string;
    closes_with: string;
    tone: string;
  };
  behavior: {
    work_hours: string;
    meeting_load: string;
    response_style: string;
    peak_focus_time: string;
  };
  context: {
    active_projects: string[];
    top_collaborators: string[];
    current_priorities: string[];
  };
}

export interface OnboardResponse {
  profile: SecondSelfProfile;
  sources_used: string[];
  session_id: string;
  created_at: string;
}

export interface ActionTaken {
  tool: string;
  summary: string;
}

export interface ChatResponse {
  response: string;
  actions_taken: ActionTaken[];
}

export interface AuthCallbackResponse {
  status: string;
  session_id: string;
}

export interface AuthSession {
  authenticated: boolean;
  email?: string;
  name?: string;
}

export async function getAuthSession(): Promise<AuthSession> {
  const res = await fetch("/api/auth/status");
  if (!res.ok) return { authenticated: false };
  return res.json();
}

export async function postOnboard(
  name: string,
  email: string,
  context: string,
  sessionId: string,
): Promise<OnboardResponse> {
  const res = await fetch("/api/onboard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, context, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function postChat(
  message: string,
  sessionId: string,
): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
