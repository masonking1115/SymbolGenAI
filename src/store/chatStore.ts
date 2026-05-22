import { create } from "zustand";
import { nanoid } from "nanoid";

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  ts: number;
}

interface ChatState {
  messages: ChatMessage[];
  isThinking: boolean;
  send: (content: string) => Promise<void>;
  clear: () => void;
  appendSystem: (content: string) => void;
}

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "assistant",
  ts: Date.now(),
  content:
    "Hi — I'm the Symbol Library AI assistant. I'm not connected to Claude yet (that lands in the next milestone), but I can still take notes and the chat UI is fully wired up.\n\nTry asking me things like:\n• \"Generate a schematic symbol from this datasheet\"\n• \"Rename R1 to R10\"\n• \"What standard symbols do we have?\"\n\nOnce the API plug-in is live, these requests will run against the live schematic and library.",
};

/**
 * Placeholder responder. Replaced in the next milestone by a real Claude
 * call wired through the Electron main-process IPC bridge.
 */
async function stubReply(prompt: string): Promise<string> {
  // Slight delay to make the "thinking" state visible.
  await new Promise((r) => setTimeout(r, 380 + Math.random() * 220));
  const trimmed = prompt.trim();
  if (!trimmed) return "(empty message)";
  if (/upload|datasheet|pdf/i.test(trimmed)) {
    return "Upload datasheets from the left panel (PDF, .md, .SchLib). Once the parser lands I'll extract pin tables and generate a `SymbolDefinition` for each part.";
  }
  if (/library|symbol|part/i.test(trimmed)) {
    return "The built-in catalog has 10 symbols (R, C, L, D, LED, NPN, PNP, GND, VCC, 1×2 header) — see the toolbar above the canvas. Uploaded `.SchLib` files will be parsed into this library in milestone 2.";
  }
  if (/wire|connect|net/i.test(trimmed)) {
    return "Press W (or click a pin) to start a wire. Tab flips the bend direction, Esc cancels. Wires snap to pins within ~6 grid units.";
  }
  return `I heard: "${trimmed}".\n\nThe Claude integration isn't wired up yet — that's milestone 3. For now I'm a stub so you can validate the chat UI, scroll behavior, and layout.`;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [WELCOME],
  isThinking: false,

  send: async (content) => {
    const trimmed = content.trim();
    if (!trimmed) return;
    if (get().isThinking) return;

    const userMsg: ChatMessage = {
      id: nanoid(8),
      role: "user",
      content: trimmed,
      ts: Date.now(),
    };
    set((s) => ({ messages: [...s.messages, userMsg], isThinking: true }));

    try {
      const reply = await stubReply(trimmed);
      const asstMsg: ChatMessage = {
        id: nanoid(8),
        role: "assistant",
        content: reply,
        ts: Date.now(),
      };
      set((s) => ({
        messages: [...s.messages, asstMsg],
        isThinking: false,
      }));
    } catch (err) {
      set((s) => ({
        messages: [
          ...s.messages,
          {
            id: nanoid(8),
            role: "system",
            content: `Error: ${err instanceof Error ? err.message : String(err)}`,
            ts: Date.now(),
          },
        ],
        isThinking: false,
      }));
    }
  },

  appendSystem: (content) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: nanoid(8), role: "system", content, ts: Date.now() },
      ],
    })),

  clear: () => set({ messages: [WELCOME], isThinking: false }),
}));
