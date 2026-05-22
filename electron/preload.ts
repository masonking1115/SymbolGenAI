import { contextBridge } from "electron";

// Placeholder for future IPC bridges (datasheet parsing, library DB, AI chat).
// Kept intentionally minimal for the editor MVP.
contextBridge.exposeInMainWorld("api", {
  version: "0.1.0",
});

export {};
