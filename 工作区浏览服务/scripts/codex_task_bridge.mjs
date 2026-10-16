// Version-coupled Desktop adapter. Only fixed read/send operations are exposed to the backend.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

const incoming = createInterface({ input: process.stdin });
const commands = incoming[Symbol.asyncIterator]();
const request = JSON.parse((await commands.next()).value);
if (!['read', 'send', 'session'].includes(request.operation)) throw new Error('Unsupported operation');
const child = spawn(process.execPath, [request.server], { env: process.env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
const lines = createInterface({ input: child.stdout });
const waiting = new Map();
let sequence = 0;
let deadline;
function arm() { clearTimeout(deadline); deadline = setTimeout(() => { child.kill(); process.exit(1); }, 35000); }
arm();
child.stderr.resume();
child.on('error', () => process.exit(1));
child.on('exit', () => { for (const pending of waiting.values()) pending.reject(new Error('Desktop adapter closed')); });
function rejectPending(error) {
  for (const pending of waiting.values()) pending.reject(error);
  waiting.clear();
}
child.stdin.on('error', () => rejectPending(new Error('Desktop input closed')));
lines.on('line', line => {
  let message;
  try { message = JSON.parse(line); }
  catch { rejectPending(new Error('Invalid Desktop response')); child.kill(); return; }
  const pending = waiting.get(message.id);
  if (pending) {
    waiting.delete(message.id);
    if (message.error) pending.reject(new Error('Desktop request rejected'));
    else pending.resolve(message.result);
  }
});
function rpc(method, params) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.reject(new Error('Desktop adapter closed'));
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    waiting.set(id, { resolve, reject });
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
  });
}
try {
  await rpc('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'nora-comfy-tasks', version: '1.0.0' } });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  await rpc('tools/list', {});
  async function perform(operation, prompt) {
    if (!['read', 'send'].includes(operation)) throw new Error('Unsupported operation');
    const args = operation === 'read'
      ? { threadId: request.threadId, turnLimit: 1, includeOutputs: false, maxOutputCharsPerItem: 200 }
      : { threadId: request.threadId, prompt };
    const result = await rpc('tools/call', {
      name: operation === 'read' ? 'read_thread' : 'send_message_to_thread', arguments: args,
      _meta: { 'openai/threadId': request.caller },
    });
    return result;
  }
  if (request.operation === 'session') {
    clearTimeout(deadline);
    while (true) {
      const next = await commands.next();
      if (next.done) break;
      const command = JSON.parse(next.value);
      arm();
      try {
        const result = await perform(command.operation, command.prompt);
        process.stdout.write(JSON.stringify({ id: command.id, result }) + '\n');
      } catch (error) {
        process.stdout.write(JSON.stringify({ id: command.id, error: String(error) }) + '\n');
      } finally { clearTimeout(deadline); }
    }
  } else {
    process.stdout.write(JSON.stringify(await perform(request.operation, request.prompt)));
  }
} finally {
  clearTimeout(deadline);
  lines.close();
  incoming.close();
  child.stdin.end();
  child.kill();
}
