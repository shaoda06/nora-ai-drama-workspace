import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { mkdtemp } from 'node:fs/promises';
const root=fileURLToPath(new URL('../frontend', import.meta.url));
const require=createRequire(root+'/package.json');
const {chromium}=require('playwright');
const {createServer}=await import(require.resolve('vite'));
const react=(await import(require.resolve('@vitejs/plugin-react'))).default;
const server=await createServer({configFile:false,root,plugins:[react()],server:{host:'127.0.0.1',port:0}});
await server.listen();
const browser=await chromium.launch({headless:true});
const screenshots=await mkdtemp('/tmp/nora-task-card-details-');
try {
 for(const width of [1362,390,320]) {
  const page=await browser.newPage({viewport:{width,height:916}}), errors=[], writes=[];
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())});
  const rows=['one','two'].map((id,i)=>({queue:'local',group_id:'group',id,project:'隔离测试',title:'片段'+(i+1),task_type:'video-first-pass',status:'local_queued',category:'queued',source_session_name:'来源会话长名称与任务标题独立保留'.repeat(6),remote_url:'http://fixture-node',created_at:'2026-10-27T00:00:00Z'}));
  const running={...rows[0],id:'running',queue:undefined,category:undefined,status:'running',title:'EP003-C003 · CH007素材补齐及背景板返修R003一采',prompt_id:'running-prompt',started_at:'2026-10-27T00:00:00Z',connection:'connected',node:null,progress:null,error:null,collected:0,expected:1};
  let complete=false;
  await page.route('**/api/**',async route=>{
    const r=route.request(), path=new URL(r.url()).pathname;
    if(r.method()!=='GET')writes.push(path);
    if(path==='/api/comfy/tasks')return route.fulfill({json:{tasks:[running],local_tasks:rows,remote_nodes:[{url:'http://fixture-node',name:'隔离节点',connection:'connected',queue:[{prompt_id:'running-prompt',status:'running',queue_position:null}],running_count:1,queued_count:0}],local_counts:{'http://fixture-node':{queued:2,paused:0,history:0}},history_updated_at:{}}});
    const match=path.match(/\/api\/comfy\/tasks\/(one|two|running)\/detail$/);
    if(match){
      const members=[...rows,running];
      const summary={...members.find(x=>x.id===match[1]),notification:'waiting',collected:0,expected:1};
      return route.fulfill({json:{summary,events:[],outputs:[],records:[],notification_batches:[],resolution_evidence:[],replacement_tasks:[],group:{id:'group',title:'第三集返修任务组',status:complete?'completed':'running',terminal:complete,completed_tasks:complete?3:1,expected_tasks:3,collected_outputs:complete?3:1,expected_outputs:3,tasks:members.map((x,i)=>({task_id:x.id,title:x.title,status:complete||i===0?'completed':'running',completed:complete||i===0,needs_attention:false}))}}});
    }
    throw Error('unexpected '+path);
  });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/task-sidebar.html`);
  await page.getByRole('button',{name:'展开任务进度',exact:true}).click();
  const remote=page.locator('.comfy-task'), local=page.locator('[data-local-task-id="one"]');
  await remote.getByRole('heading',{name:running.title,exact:true}).waitFor();
  const linkStyles=[];
  for(const [card,container] of [[remote,'.comfy-task-session-row'],[local,'.local-queue-card-title']]){
    const button=card.getByRole('button',{name:/查看.*详情/});
    assert.equal(await button.textContent(),'任务组详情 →');
    linkStyles.push(await button.evaluate(el=>{const s=getComputedStyle(el);return {font:s.fontSize,line:s.lineHeight,padding:s.padding,underline:s.textDecorationLine,color:s.color}}));
    assert.match(linkStyles.at(-1).underline,/underline/);
    const bounds=await button.boundingBox(),row=await card.locator(container).boundingBox();
    assert.ok(Math.abs(bounds.x+bounds.width-row.x-row.width)<=1,'详情入口在卡片内容右侧');
    if(container==='.comfy-task-session-row'){
      const source=await card.locator('.comfy-task-session').boundingBox();
      assert.ok(source.x+source.width<=bounds.x,'长会话名不覆盖详情');
      assert.ok(source.y<bounds.y+bounds.height&&bounds.y<source.y+source.height,'运行卡来源会话与详情同排');
    }
    assert.ok(await card.evaluate(n=>n.scrollWidth<=n.clientWidth+1));
    await card.screenshot({path:`${screenshots}/${width}-${container.includes('session')?'running':'queued'}.png`});
  }
  assert.deepEqual(linkStyles[0],linkStyles[1]);
  await remote.getByRole('button',{name:/查看.*详情/}).click();
  await page.getByRole('region',{name:'任务组进度'}).waitFor();
  await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'查看片段1任务组详情',exact:true}).click();
  const group=page.getByRole('region',{name:'任务组进度'});
  await group.waitFor();
  assert.match(await group.innerText(),/全组收尾：1 \/ 3/);
  await group.getByRole('button',{name:'片段2',exact:true}).click();
  await page.getByRole('dialog').getByRole('heading',{name:'片段2',exact:true}).waitFor();
  complete=true;
  await page.getByText('全组已完成，统一通知来源 Agent。',{exact:true}).waitFor({timeout:10000});
  assert.match(await group.innerText(),/全组收尾：3 \/ 3/);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  assert.equal(overflow,false);
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  await page.close();
 }
 console.log('PASS: 1362/390/320px; aligned shared detail labels, long source name, group progress, member navigation, live completion; no writes/errors/overflow; screenshots '+screenshots);
} finally {await browser.close();await server.close();}
