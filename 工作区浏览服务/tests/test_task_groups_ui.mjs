import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../frontend', import.meta.url));
const require=createRequire(root+'/package.json');
const {chromium}=require('playwright');
const {createServer}=await import(require.resolve('vite'));
const react=(await import(require.resolve('@vitejs/plugin-react'))).default;
const server=await createServer({configFile:false,root,plugins:[react()],server:{host:'127.0.0.1',port:0}});
await server.listen();
const browser=await chromium.launch({headless:true});
try {
 for(const width of [1362,390,320]) {
  const page=await browser.newPage({viewport:{width,height:916}}), errors=[], writes=[];
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())});
  const rows=['one','two'].map((id,i)=>({queue:'local',group_id:'group',id,project:'隔离测试',title:'片段'+(i+1),task_type:'video-first-pass',status:'local_queued',category:'queued',remote_url:'http://fixture-node',created_at:'2026-10-27T00:00:00Z'}));
  let complete=false;
  await page.route('**/api/**',async route=>{
    const r=route.request(), path=new URL(r.url()).pathname;
    if(r.method()!=='GET')writes.push(path);
    if(path==='/api/comfy/tasks')return route.fulfill({json:{tasks:[],local_tasks:rows,remote_nodes:[{url:'http://fixture-node',name:'隔离节点',connection:'connected',queue:[],running_count:0,queued_count:0}],local_counts:{'http://fixture-node':{queued:2,paused:0,history:0}},history_updated_at:{}}});
    const match=path.match(/\/api\/comfy\/tasks\/(one|two)\/detail$/);
    if(match){
      const summary={...rows.find(x=>x.id===match[1]),notification:'waiting',collected:0,expected:1};
      return route.fulfill({json:{summary,events:[],outputs:[],records:[],notification_batches:[],resolution_evidence:[],replacement_tasks:[],group:{id:'group',title:'第三集返修任务组',status:complete?'completed':'running',terminal:complete,completed_tasks:complete?2:1,expected_tasks:2,collected_outputs:complete?2:1,expected_outputs:2,tasks:rows.map((x,i)=>({task_id:x.id,title:x.title,status:complete||i===0?'completed':'running',completed:complete||i===0,needs_attention:false}))}}});
    }
    throw Error('unexpected '+path);
  });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/task-sidebar.html`);
  await page.getByRole('button',{name:'展开任务进度',exact:true}).click();
  await page.getByRole('button',{name:'查看片段1详情',exact:true}).click();
  const group=page.getByRole('region',{name:'任务组进度'});
  await group.waitFor();
  assert.match(await group.innerText(),/全组收尾：1 \/ 2/);
  await group.getByRole('button',{name:'片段2',exact:true}).click();
  await page.getByRole('dialog').getByRole('heading',{name:'片段2',exact:true}).waitFor();
  complete=true;
  await page.getByText('全组已完成，统一通知来源 Agent。',{exact:true}).waitFor({timeout:10000});
  assert.match(await group.innerText(),/全组收尾：2 \/ 2/);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  assert.equal(overflow,false);
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  await page.close();
 }
 console.log('PASS: 1362/390/320px; group progress, member navigation, live completion; no writes/errors/overflow');
} finally {await browser.close();await server.close();}
