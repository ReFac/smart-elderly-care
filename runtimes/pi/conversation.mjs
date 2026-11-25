// Pi owns the conversational model → tool → observation → answer loop. The Python
// host supplies its authorised cloud transport and tool callbacks for this turn only.
import { createInterface } from "node:readline";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// The signed bridge and the offline, lock-verified SDK can reside in different
// release directories. Only the trusted host supplies this path at process start.
const sdk = name => import(pathToFileURL(join(process.argv[2], "@earendil-works", name, "dist/index.js")).href);
const { runAgentLoop } = await sdk("pi-agent-core");
const { createAssistantMessageEventStream } = await sdk("pi-ai");

const active = new Map();
function send(id, event) {
  process.stdout.write(JSON.stringify({ id, ...event }) + "\n");
}

async function run(id, start, state) {
  function host(event) {
    if (state.cancelled || state.pending) throw new Error("turn closed");
    return new Promise((resolve, reject) => {
      state.pending = { resolve, reject };
      send(id, event);
    });
  }
  const tools = start.tools.map(tool => ({
    ...tool.function,
    label: tool.function.name,
    execute: async (callId, args) => {
      const result = await host({ op: "tool", callId, name: tool.function.name, args });
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: {} };
    },
  }));
  const model = { id: start.model, api: "openai-completions", provider: "careops" };
  let steps = 0;
  async function cloud(_model, transcript) {
    if (++steps > 2 || transcript.messages.some(item => item.role === "toolResult" && item.isError)) {
      throw new Error("invalid tool call");
    }
    // The host already holds the approved projection and all evidence. Request it
    // by phase to avoid retransmitting the transcript or disclosing credentials.
    const response = await host({ op: "model", phase: steps === 1 ? "initial" : "synthesis" });
    const content = response.calls
      ? response.calls.map(call => ({ type: "toolCall", ...call }))
      : [{ type: "text", text: response.text }];
    const stopReason = response.calls ? "toolUse" : "stop";
    const message = {
      role: "assistant", api: model.api, provider: model.provider, model: model.id,
      content, stopReason, timestamp: Date.now(),
      // The SDK never settles bills. Its local adapter observes no direct
      // provider usage. The Python transport persists every upstream receipt.
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0 },
    };
    const stream = createAssistantMessageEventStream();
    stream.push({ type: "done", reason: stopReason, message });
    return stream;
  }
  const messages = start.messages.map(m => ({ ...m, timestamp: Date.now() }));
  await runAgentLoop(messages, { messages: [], tools },
    { model, convertToLlm: items => items, toolExecution: "sequential" },
    () => {}, state.abort.signal, cloud);
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", line => {
  try {
    const { id, op, value, ...start } = JSON.parse(line);
    const existing = active.get(id);
    if (op === "start" && !existing) {
      const state = { pending: null, cancelled: false, abort: new AbortController() };
      active.set(id, state);
      // Drop turn-local context even if a host callback stalls. The Python
      // provider transport separately settles any receipt already in flight.
      const timeout = setTimeout(() => {
        state.cancelled = true;
        state.abort.abort();
        state.pending?.reject(new Error("turn expired"));
        send(id, { op: "expired" });
      }, start.deadlineMs);
      run(id, start, state)
        .then(() => { if (!state.cancelled) send(id, { op: "done" }); })
        .catch(() => { if (!state.cancelled) send(id, { op: "failed" }); })
        .finally(() => { clearTimeout(timeout); active.delete(id); });
    } else if (op === "return" && existing?.pending) {
      const pending = existing.pending;
      existing.pending = null;
      pending.resolve(value);
    } else if (op === "cancel" && existing) {
      existing.cancelled = true;
      existing.abort.abort();
      existing.pending?.reject(new Error("turn closed"));
    }
  } catch {
    // A broken host protocol is terminal; a fresh process accepts later requests.
    process.exit(1);
  }
});
input.on("close", () => process.exit(0));
