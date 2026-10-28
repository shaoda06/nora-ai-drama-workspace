// Real sidebar and native wheel input; synthetic read-only task responses only.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {mkdtemp} from 'node:fs/promises';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium}=require('playwright');
const {createServer}=await import(require.resolve('vite'));
const react=(await import(require.resolve('@vitejs/plugin-react'))).default;
const out=await mkdtemp('/tmp/nora-sidebar-wheel-');
const server=await createServer({configFile:false,root:fileURLToPath(new URL('../frontend',import.meta.url)),plugins:[react()],server:{host:'127.0.0.1',port:0}});
await server.listen();const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 for(const width of (process.argv.includes('--probe')?[1362]:[1362,390,320])){
  const page=await browser.newPage({viewport:{width,height:916}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  await page.route('**/api/**',route=>{
   const req=route.request();if(req.method()!=='GET'){writes.push(req.url());return route.abort()}
   assert.equal(new URL(req.url()).pathname,'/api/comfy/tasks');
   return route.fulfill({json:{tasks:[],local_tasks:Array.from({length:20},(_,i)=>({queue:'local',id:'wheel-'+i,project:'隔离项目',title:'滚动示例 '+i,task_type:'image',status:'local_queued',category:'queued',remote_url:'http://fixture-node',created_at:'2026-10-28T00:00:00Z'})),remote_nodes:[{url:'http://fixture-node',name:'隔离节点',connection:'connected',queue:[],running_count:0,queued_count:0,updated_at:'2026-10-28T00:00:00Z'}],local_counts:{'http://fixture-node':{queued:20,paused:0,history:0}},history_updated_at:{}}});
  });
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/task-sidebar.html`);
  assert.equal(await page.title(),'任务侧栏隔离回归');
  await page.addStyleTag({content:'main{min-height:2200px}'});
  const wheel=async(locator,delta)=>{const b=await locator.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+Math.min(b.height/2,100));await page.mouse.wheel(0,delta);await page.waitForTimeout(200)};
  const reset=()=>page.evaluate(()=>window.scrollTo(0,300));
  const windowTop=()=>page.evaluate(()=>window.scrollY);
  await reset();await page.mouse.move(width-20,700);await page.mouse.wheel(0,200);await page.waitForTimeout(200);assert.ok(await windowTop()>300,'背景本身必须能滚动');
  await page.getByRole('button',{name:'展开任务进度',exact:true}).click();
  const side=page.getByRole('complementary',{name:'生成任务进度'});
  const local=side.getByRole('region',{name:'本地队列'}).locator('.comfy-queue-body');
  const remote=side.getByRole('region',{name:'远端队列'}).locator('.comfy-queue-body');
  await local.locator('.local-queue-card').first().waitFor();
  assert.ok(await local.evaluate(e=>e.scrollHeight>e.clientHeight));
  assert.ok(await remote.evaluate(e=>e.scrollHeight<=e.clientHeight));
  for(const [name,area] of [['节点标题',side.locator('.comfy-node-heading')],['空列表',remote],['分类标题',side.locator('.comfy-local-heading')],['侧边窄栏',side.locator('.comfy-rail-label')]]){
   await reset();await wheel(area,250);assert.equal(await windowTop(),300,`${width}px ${name}不应滚动背景`);
  }
  await reset();await local.evaluate(e=>e.scrollTop=0);await wheel(local,250);
  assert.ok(await local.evaluate(e=>e.scrollTop>0),'侧栏列表正常滚动');assert.equal(await windowTop(),300);
  for(const [edge,delta] of [['top',-400],['bottom',400]]){
   await reset();await local.evaluate((e,edge)=>e.scrollTop=edge==='top'?0:e.scrollHeight,edge);
   const before=await local.evaluate(e=>e.scrollTop);await wheel(local,delta);
   assert.ok(Math.abs(await local.evaluate(e=>e.scrollTop)-before)<=1,'列表边界允许浏览器1px取整');assert.equal(await windowTop(),300,`${edge}边界不传给背景`);
  }
  if(width>700){await reset();await page.mouse.move(900,700);await page.mouse.wheel(0,250);await page.waitForTimeout(200);assert.ok(await windowTop()>300,'侧栏外仍可滚动背景')}
  await page.screenshot({path:`${out}/${width}.png`});
  await page.getByRole('button',{name:'收起任务进度',exact:true}).click();
  await reset();await page.mouse.move(width-20,700);await page.mouse.wheel(0,250);await page.waitForTimeout(200);assert.ok(await windowTop()>300,'收起后背景正常滚动');
  assert.equal(await page.locator('vite-error-overlay').count(),0);assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify({width,passed:true,out,errors,writes}));await page.close();
 }
}finally{await browser.close();await server.close()}
