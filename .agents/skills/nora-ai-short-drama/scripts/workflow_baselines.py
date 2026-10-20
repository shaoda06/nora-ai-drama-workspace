#!/usr/bin/env python3
"""Offline checks of bundled API structure and execution parameters. Never reads canvas files or connects."""
import argparse, ast, copy, json, math, zipfile
from pathlib import Path
from workflow_paths import workflow_directories, workflow_root
UI_FIELDS={'control_after_generate','upload','choose video to upload','videopreview','image_upload','audioUI','preview'}
UI_NODES={'Note','MarkdownNote','SetNode','GetNode','Reroute'}
POSTPROCESS_NODES={'Nora-RTX-RIFE-自动切镜保护超分插帧':'NoraRIFEInterpolationCutTest'}

def validate_rife_package(path):
 with zipfile.ZipFile(path) as package:
  root='ComfyUI-Nora-RIFE-CutTest/'
  required={'__init__.py','nodes.py','cut_protection.py','preflight.py','smoke_test.py',
            'tests/test_cut_protection.py','README.md','LICENSE'}
  assert {root+name for name in required}<=set(package.namelist()), 'Incomplete RIFE node package'
  assert package.testzip() is None, 'Corrupt RIFE node package'
  tree=ast.parse(package.read(root+'nodes.py').decode('utf-8'))
  assert any(isinstance(n,ast.ClassDef) and n.name=='NoraRIFEInterpolationCutTest' for n in tree.body), 'RIFE package class mismatch'
  for name in package.namelist():
   if name.endswith('.py'):ast.parse(package.read(name).decode('utf-8'),filename=name)

def validate_postprocess(api,name):
 interpolation=api['12'];resize=api['1']['inputs'];encode=api['16']['inputs']
 assert interpolation['class_type']==POSTPROCESS_NODES[name], 'Postprocess interpolation node mismatch'
 if interpolation['class_type']=='NoraRIFEInterpolationCutTest':
  assert {'scale','scene_cut_threshold'}<=set(interpolation['inputs']), 'Missing required RIFE inputs'
 frame_input='images' if interpolation['class_type']=='NoraRIFEInterpolationCutTest' else 'frames'
 assert interpolation['inputs'][frame_input]==['7',0], 'Postprocess source images mismatch'
 assert interpolation['inputs']['source_fps']==['7',2], 'Postprocess source FPS mismatch'
 assert resize['images']==['12',0], 'Postprocess must interpolate before upscaling'
 assert encode['images']==['1',0], 'Postprocess encoder must use upscaled images'
 assert encode['frame_rate']==['12',1], 'Postprocess output FPS must follow interpolation'
 assert encode['audio']==['7',1] and encode['trim_to_audio'] is False, 'Postprocess original audio/timing mismatch'
 width,height=resize['resize_type.width'],resize['resize_type.height'];fps=interpolation['inputs']['target_fps']
 notes=[]
 if min(width,height)<1080:notes.append('低于推荐1080P；按本次选定交付依据核对，不因此拒绝本次交付配置')
 if fps<30:notes.append('低于推荐30fps；按本次选定交付依据核对，不因此拒绝本次交付配置')
 return {'width':width,'height':height,'target_fps':fps,'format':encode['format'],
         'crf':encode['crf'],'recommendation_notes':notes}
def is_link(v):return isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and isinstance(v[1],int)
def link_tuple(l):
 return [l['id'],l['origin_id'],l['origin_slot'],l['target_id'],l['target_slot']] if isinstance(l,dict) else l[:5]
class Canvas:
 def __init__(self,g,prefix='',parent=None,instance=None,definitions=None):
  self.g=g;self.prefix=prefix;self.parent=parent;self.instance=instance
  self.nodes={n['id']:n for n in g['nodes']};self.links={x[0]:x for x in map(link_tuple,g.get('links',[]))}
  self.defs=definitions if definitions is not None else {d['id']:d for d in g.get('definitions',{}).get('subgraphs',[])}
  self.children={}
  assert len(self.nodes)==len(g['nodes']), 'Duplicate canvas node ID'
  assert len(self.links)==len(g.get('links',[])), 'Duplicate canvas link ID'
  for n in self.nodes.values():
   named=n.get('widgets_values_named',{});stored=n.get('widgets_values',[])
   if named:
    if isinstance(stored,list):assert stored==list(named.values()), ('Canvas widget mismatch',self.prefix,n['id'])
    else:
     for field,value in named.items():
      if field not in UI_FIELDS:assert stored.get(field)==value, ('Canvas widget mismatch',self.prefix,n['id'],field)
  for link_id,origin,slot,target,target_slot in self.links.values():
   if origin in self.nodes:
    assert link_id in (self.nodes[origin].get('outputs',[])[slot].get('links') or []), ('Broken output',link_id)
   else:assert parent and origin==g['inputNode']['id'], ('Missing source',origin)
   if target in self.nodes:
    assert self.nodes[target]['inputs'][target_slot].get('link')==link_id, ('Broken input',link_id)
   else:assert parent and target==g['outputNode']['id'], ('Missing target',target)
 def child(self,n):
  if n['id'] not in self.children:self.children[n['id']]=Canvas(self.defs[n['type']],self.prefix+str(n['id'])+':',self,n,self.defs)
  return self.children[n['id']]
 def follow(self,i,ignore=False,seen=()):
  l=self.links.get(i.get('link'));return self.resolve(l[1],l[2],ignore,seen) if l else None
 def resolve(self,id,slot=0,ignore=False,seen=()):
  key=(self.prefix,id,slot);assert key not in seen,('routing cycle',key);seen=seen+(key,)
  if self.parent and id==self.g['inputNode']['id']:
   i=self.instance['inputs'][slot]
   return self.parent.follow(i,ignore,seen) if i.get('link') is not None else self.instance.get('widgets_values_named',{}).get(i['name'])
  n=self.nodes[id]
  if n['type'] in self.defs:
   c=self.child(n);output=c.g['outputNode']['id'];ls=[l for l in c.links.values() if l[3]==output and l[4]==slot];assert len(ls)==1
   return c.resolve(ls[0][1],ls[0][2],ignore,seen)
  if n['type']=='GetNode':
   sets=[s for s in self.nodes.values() if s['type']=='SetNode' and s['widgets_values'][0]==n['widgets_values'][0]];assert len(sets)==1
   return self.resolve(sets[0]['id'],0,ignore,seen)
  if n['type'] in ('SetNode','Reroute'):return self.follow(n['inputs'][0],ignore,seen)
  if not ignore and n.get('mode')==2:return None
  if not ignore and n.get('mode')==4:
   ins=[i for i in n.get('inputs',[]) if i.get('link') is not None and i['type']==n.get('outputs',[])[slot]['type']];assert len(ins)<=1
   return self.follow(ins[0],ignore,seen) if ins else None
  return [self.prefix+str(id),slot]
 def object(self,id):
  n=self.nodes[id];v={k:copy.deepcopy(v) for k,v in n.get('widgets_values_named',{}).items() if k not in UI_FIELDS}
  for i in n.get('inputs',[]):
   if i.get('link') is not None:
    x=self.follow(i)
    if x is not None:v[i['name']]=x
    else:v.pop(i['name'],None)
  return {'class_type':n['type'],'inputs':v,'_meta':{'title':n.get('title',n['type'])}}
 def find(self,key):
  if ':' not in key:return self,int(key)
  id,rest=key.split(':',1);return self.child(self.nodes[int(id)]).find(rest)
 def active_nodes(self):
  for id,n in self.nodes.items():
   if n.get('mode',0) in (2,4):continue
   if n['type'] in self.defs:yield from self.child(n).active_nodes()
   elif n['type'] not in UI_NODES:yield self.prefix+str(id)
 def api(self,root,optional=True):
  out={};active=set()
  def walk(key):
   if key in out:return
   assert key not in active,('cycle',key);active.add(key);c,id=self.find(key);n=c.object(id)
   for v in n['inputs'].values():
    if is_link(v):walk(v[0])
   active.remove(key);out[key]=n
  for output in root if isinstance(root,(list,tuple)) else [root]:walk(str(output))
  if optional and 265 in self.nodes:
   for i in self.nodes[265]['inputs']:
    if i['name'].startswith(('ref_images.','ref_audios.','ref_videos.')) and i.get('link') is not None:
     src=self.follow(i,True);assert is_link(src);walk(src[0])
     out[src[0]]['_meta']['nora_optional_reference']={'target':'265','input':i['name'],'output_slot':src[1]}
  return out

def semantic(api):return {k:{'class_type':v['class_type'],'inputs':v['inputs']} for k,v in api.items()}

def validate_rtx_inputs(api):
 """Check known required RTX inputs in new tasks, without querying the server."""
 for key,node in api.items():
  if node['class_type']!='RTXVideoSuperResolution':continue
  inputs=node['inputs']
  for field in ('strength','image_encoding'):
   if field not in inputs:raise ValueError(f'RTXVideoSuperResolution {key} missing required input: {field}')
  strength=inputs['strength']
  if type(strength) not in (int,float) or not math.isfinite(strength) or not 0<=strength<=1:
   raise ValueError(f'RTXVideoSuperResolution {key} strength must be a number from 0 to 1')
  if inputs['image_encoding'] not in ('8-bit RGB','10-bit RGB (RGB10A2)'):
   raise ValueError(f'RTXVideoSuperResolution {key} image_encoding is unsupported')

def output_for(name):return [403,504,506] if name=='Minimax-H3-导演台-视频生成-标准版' else 3 if name=='Nora-RTX-图片2倍超分' else 508 if name=='Qwen2.1-文生图-普通版' else 487 if name=='Qwen2.1-图生图-普通版' else 461 if name.startswith('Qwen') else 403 if name=='Minimax-H3-导演台-视频生成-去油版' else 264 if 'SelfLift-备用' in name else 16

def director_editor_state(block, common=False):
 """Compare persisted Director content, excluding preview blobs and root-only fields."""
 if common:
  defaults={'commonEnabled':False,'commonCollapsed':False,'prompt':'','refs':[],'refAudios':[],'refVideos':[]}
  out={k:copy.deepcopy(block.get(k,v)) for k,v in defaults.items()}
  if 't2vCommon' in block:out['t2vCommon']=copy.deepcopy(block['t2vCommon'])
 else:
  out={k:copy.deepcopy(v) for k,v in block.items() if k not in {'previewB64','previewFrames','previewMime','imageB64'}}
  out.setdefault('loras',[])
 for field,file_key in [('refs','imageFile'),('refAudios','audioFile'),('refVideos','videoFile')]:
  defaults={file_key:'','fileName':'','type':'input','subfolder':''}
  if field!='refs':defaults['durationSec']=None
  if field=='refVideos':defaults['pairedAudioFile']=''
  out[field]=sorted(({'index':int(r.get('index',r.get('slot',0))),**{k:r.get(k,v) for k,v in defaults.items()}} for r in block.get(field,[])),key=lambda r:r['index'])
 if not common:
  for field in ['genImage','startImage','endImage','referenceVideo']:
   value=block.get(field)
   if value is None:out.pop(field,None);continue
   defaults={'imageFile':'','fileName':''} if field!='referenceVideo' else {'videoFile':'','fileName':'','type':'input','subfolder':''}
   if field in ('startImage','endImage'):defaults.update(width=0,height=0)
   out[field]={k:value.get(k,v) for k,v in defaults.items()}
 return out

def verify(directory):
 directory=Path(directory)
 folders=[directory, *(folder for folder,_ in workflow_directories(directory))]
 results=[]
 for a in sorted(p for folder in folders for p in folder.glob('*.api.json')):
  stem=a.name.removesuffix('.api.json');actual=json.loads(a.read_text(encoding="utf-8"))
  validate_rtx_inputs(actual)
  outputs=output_for(stem)
  for key in outputs if isinstance(outputs,list) else [outputs]:
   assert str(key) in actual, ('Missing API output',stem,key)
  for node in actual.values():
   for value in node['inputs'].values():
    if is_link(value):assert value[0] in actual, ('Missing API input',stem,value[0])
  refs=[(key,node['_meta']['nora_optional_reference']) for key,node in actual.items() if 'nora_optional_reference' in node.get('_meta',{})]
  assert len(refs)==(15 if '265' in actual and '多参考视频' in stem else 0)
  if stem=='Nora-RTX-图片2倍超分':
   assert actual['1']['inputs']['resize_type.scale']==2, 'Image upscale must remain 2x'
  for director in (n for n in actual.values() if n['class_type']=='MiniMaxH3Director'):
   inputs=director['inputs'];timeline=json.loads(inputs['timeline_data'])
   for field,key in [('width','width'),('height','height'),('ref_max_size','refMaxSize'),('frame_rate','frameRate'),('total_frames','totalFrames')]:
    assert inputs[field]==timeline[key],('Director timeline mismatch',field)
   assert timeline['output']['width']==inputs['width'] and timeline['output']['height']==inputs['height'], 'Director output size mismatch'
   assert timeline['global']['prompt']==inputs['global_prompt'], 'Director public prompt mismatch'
   assert sum(s['frameCount'] for s in timeline['segments'])==inputs['total_frames'], 'Director segment frame mismatch'
   workspace=timeline['batchWorkspaces']['r2v']
   assert director_editor_state(workspace['globalCommon'],True)==director_editor_state(timeline['global'],True), 'Director public workspace mismatch'
   assert [director_editor_state(s) for s in workspace['segments']]==[director_editor_state(s) for s in timeline['segments']], 'Director segment workspace mismatch'
   for field,default in [('selectedIndex',0),('editMode','segment'),('runSelectEnabled',False),('runSelection',[])]:
    assert workspace.get(field,default)==timeline.get(field,default),('Director selection workspace mismatch',field)
  # Exercise all supported reference-count combinations, removing unused loaders.
  count=0
  if refs:
   for ni in range(10):
    for na in range(4):
     for nv in range(4):
      if ni+na+nv>12 or (na and not(ni or nv)):continue
      task=copy.deepcopy(actual)
      for k,r in refs:
       group=r['input'].split('.')[0];limit={'ref_images':ni,'ref_audios':na,'ref_videos':nv}[group]
       if int(r['input'].rsplit('_',1)[1])<limit:task['265']['inputs'][r['input']]=[k,r['output_slot']]
       else:task.pop(k)
      for n in task.values():
       for v in n['inputs'].values():
        if is_link(v):assert v[0] in task
      count+=1
  result={'workflow':stem,'nodes':len(actual),'optional_references':len(refs),'reference_combinations':count}
  if stem in POSTPROCESS_NODES:
   result['postprocess_delivery']=validate_postprocess(actual,stem)
   if actual['12']['class_type']=='NoraRIFEInterpolationCutTest':
    package=Path(__file__).resolve().parents[1]/'dependencies/ComfyUI节点资源/ComfyUI-Nora-RIFE-CutTest.zip'
    validate_rife_package(package)
    result['node_package']=package.name
  results.append(result)
 return results
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__, epilog='Python 3.9+, standard library; do not use -O. Prints one JSON line per scanned API, then PASS; exit 0 on success, nonzero on error. Check expected workflow coverage: an empty directory can also pass.')
 p.add_argument('--directory',type=Path,default=workflow_root(),help='Scan bundled-name *.api.json files in this directory and its immediate category directories registered in workflow_paths.py, excluding other or deeper directories. Default: references/comfyui-workflow under this skill; relative paths use the current working directory. Point directly at a category directory to check only its APIs.')
 args=p.parse_args()
 for r in verify(args.directory):print(json.dumps(r,ensure_ascii=False))
 print('PASS: offline API checks only; remote compatibility and execution not tested.')
