import { api } from "./client";

export type AssistantRole = "user" | "assistant";

export interface AssistantMessage {
  id: string;
  role: AssistantRole;
  content: string;
  challenge_id: string | null;
  created_at: string;
  /**
   * Set when the model could not answer, so the bubble can be styled as a
   * hiccup rather than as the System AI's considered opinion.
   */
  error: string | null;
}

export interface Conversation {
  available: boolean;
  messages: AssistantMessage[];
  /** The rung in force — which prompt and which gates this player faces. */
  ladder_level: number;
  /**
   * The highest rung their solves have earned, and the ceiling on the selector.
   * Derived server-side; a level sent by the client is ignored.
   */
  max_ladder_level: number;
}

export interface LadderSelection {
  ladder_level: number;
  max_ladder_level: number;
  conversation_cleared: boolean;
}

export const getConversation = () => api.get<Conversation>("/assistant/conversation");

/**
 * Step back to a rung already beaten. Always clears the conversation: a
 * carried-over transcript keeps the previous level's successful injections in
 * context, where they weaken the prompt that replaces it.
 */
export const selectLadderLevel = (level: number) =>
  api.put<LadderSelection>("/assistant/ladder-level", { level });

export const sendMessage = (content: string, challengeId: string | null) =>
  api.post<{ message: AssistantMessage }>("/assistant/messages", {
    content,
    challenge_id: challengeId,
  });

export const clearConversation = () => api.delete<void>("/assistant/conversation");
