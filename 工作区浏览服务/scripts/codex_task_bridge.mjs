// Version-coupled Desktop adapter. Only fixed read/send operations are exposed to the backend.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
if (!['read', 'send'].includes(request.operation)) throw new Error('Unsupported operation');
const child = spawn(process.execPath, [request.server], { env: process.env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
const lines = createInterface({ input: child.stdout });
const waiting = new Map();
let sequence = 0;
const deadline = setTimeout(() => { child.kill(); process.exit(1); }, 35000);
child.stderr.resume();
child.on('error', () => process.exit(1));
child.on('exit', () => { for (const pending of waiting.values()) pending.reject(new Error('Desktop adapter closed')); });
lines.on('line', line => {
  const message = JSON.parse(line);
  const pending = waiting.get(message.id);
  if (pending) {
    waiting.delete(message.id);
    if (message.error) pending.reject(new Error('Desktop request rejected'));
    else pending.resolve(message.result);
  }
});
function rpc(method, params) {
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
  const args = request.operation === 'read'
    ? { threadId: request.threadId, turnLimit: 1, includeOutputs: false, maxOutputCharsPerItem: 200 }
    : { threadId: request.threadId, prompt: request.prompt };
  const result = await rpc('tools/call', {
    name: request.operation === 'read' ? 'read_thread' : 'send_message_to_thread', arguments: args,
    _meta: { 'openai/threadId': request.caller },
  });
  process.stdout.write(JSON.stringify(result));
} finally {
  clearTimeout(deadline);
  lines.close();
  child.stdin.end();
  child.kill();
}
