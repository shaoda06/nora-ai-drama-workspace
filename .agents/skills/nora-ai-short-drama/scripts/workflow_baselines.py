#!/usr/bin/env python3
"""Offline verification of bundled canvas/API pairs. Never connects or writes baselines."""
import argparse, copy, json
from pathlib import Path
UI_FIELDS={'control_after_generate','upload','choose video to upload','videopreview','image_upload','audioUI','preview'}
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
 def api(self,root,optional=True):
  out={};active=set()
  def walk(key):
   if key in out:return
   assert key not in active,('cycle',key);active.add(key);c,id=self.find(key);n=c.object(id)
   for v in n['inputs'].values():
    if is_link(v):walk(v[0])
   active.remove(key);out[key]=n
  walk(str(root))
  if optional and 265 in self.nodes:
   for i in self.nodes[265]['inputs']:
    if i['name'].startswith(('ref_images.','ref_audios.','ref_videos.')) and i.get('link') is not None:
     src=self.follow(i,True);assert is_link(src);walk(src[0])
     out[src[0]]['_meta']['nora_optional_reference']={'target':'265','input':i['name'],'output_slot':src[1]}
  return out

def semantic(api):return {k:{'class_type':v['class_type'],'inputs':v['inputs']} for k,v in api.items()}
def output_for(name):return 3 if name=='Nora-RTX-图片2倍超分' else 461 if name.startswith('Qwen') else 264 if '仅一采' in name else 214 if '仅二采' in name else 16

def verify(directory):
 results=[]
 for p in sorted(Path(directory).glob('*.workflow.json')):
  stem=p.name.removesuffix('.workflow.json');a=p.with_name(stem+'.api.json');assert a.exists(),f'Missing API: {a.name}'
  expected=Canvas(json.loads(p.read_text(encoding="utf-8"))).api(output_for(stem));actual=json.loads(a.read_text(encoding="utf-8"))
  assert semantic(actual)==semantic(expected),f'Canvas/API mismatch: {stem}'
  for k,n in expected.items():
   if 'nora_optional_reference' in n['_meta']:assert actual[k].get('_meta',{}).get('nora_optional_reference')==n['_meta']['nora_optional_reference']
  refs=[(k,n['_meta']['nora_optional_reference']) for k,n in expected.items() if 'nora_optional_reference' in n['_meta']]
  assert len(refs)==(15 if '多参考视频' in stem else 0)
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
  results.append({'workflow':stem,'nodes':len(actual),'optional_references':len(refs),'reference_combinations':count})
  # Shared first-pass graph inputs must remain identical between H3 stages.
 first_path=Path(directory)/'Nora-MiniMaxH3-多参考视频-仅一采.api.json'
 second_path=Path(directory)/'Nora-MiniMaxH3-多参考视频-仅二采.api.json'
 if first_path.exists() and second_path.exists():
  first=semantic(json.loads(first_path.read_text(encoding="utf-8")));second=semantic(json.loads(second_path.read_text(encoding="utf-8")))
  for node_id in first.keys() & second.keys():assert first[node_id]==second[node_id], ('Shared H3 mismatch',node_id)
 return results
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__, epilog='Python 3.9+, standard library; do not use -O. Prints one JSON line per scanned pair, then PASS; exit 0 on success, nonzero on error. Check expected workflow coverage: an empty directory can also pass.')
 p.add_argument('--directory',type=Path,default=Path(__file__).resolve().parents[1]/'references/comfyui-workflow',help='Directory containing bundled-name *.workflow.json / *.api.json pairs (non-recursive). Default: references/comfyui-workflow under this skill; explicit relative paths use the current working directory.')
 args=p.parse_args()
 for r in verify(args.directory):print(json.dumps(r,ensure_ascii=False))
 print('PASS: offline pair consistency only; remote compatibility and execution not tested.')
