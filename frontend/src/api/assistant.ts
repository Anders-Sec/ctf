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
   * hiccup rather than as the dungeon master's considered opinion.
   */
  error: string | null;
}

export interface Conversation {
  available: boolean;
  messages: AssistantMessage[];
}

export const getConversation = () => api.get<Conversation>("/assistant/conversation");

export const sendMessage = (content: string, challengeId: string | null) =>
  api.post<{ message: AssistantMessage }>("/assistant/messages", {
    content,
    challenge_id: challengeId,
  });

export const clearConversation = () => api.delete<void>("/assistant/conversation");
