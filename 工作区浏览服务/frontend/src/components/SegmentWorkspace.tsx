import { useContext, useState } from 'react';
import type { GenerationContext, SegmentVideo as VideoItem } from '../api';
import { Original, PreviewContext, Rich } from '../components';
import { TabNav } from './TabNav';
import { TabSelect } from './TabSelect';
import { candidateLabel, SegmentVideo } from './SegmentVideo';
import { CopyButton } from './CopyButton';

function SegmentReferences({ context }: { context?: GenerationContext }) {
  const preview = useContext(PreviewContext);
  return <section className="segment-references" aria-label="参考图区域">
    {context ? (['common', 'segment'] as const).map(group => <div className="segment-reference-group" key={group}>
      <h3>{group === 'common' ? '公共参考图' : '本组参考图'}</h3>
      <div className="segment-reference-images">{context.references[group].map((image, index) => <figure key={index}>
        <figcaption>{image.label}</figcaption>
        {image.url ? <button className="reference-preview" onClick={() => preview({ kind: 'image', name: image.name, url: image.url })} aria-label={`查看 ${image.label} ${image.name}`}><img src={image.url} alt={image.name} loading="lazy" /></button> : <p className="muted">原图缺失</p>}
      </figure>)}{!context.references[group].length && <p className="muted">{context.issues.length ? '该次参考图关联尚未完整记录。' : '该次未使用此类参考图。'}</p>}</div>
    </div>) : <span className="placeholder-label">参考图区域</span>}
  </section>;
}

export function SegmentWorkspace({ items }: { items: VideoItem[] }) {
  const [stage, setStage] = useState('');
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState('script');
  const [language, setLanguage] = useState('zh');
  const latest = items.reduce<VideoItem | undefined>((latest, item) => !latest || Number(item.run.slice(1)) > Number(latest.run.slice(1)) ? item : latest, undefined);
  const versions = items.filter(item => item.stage === stage).sort((a, b) => Number(b.approved) - Number(a.approved) || a.candidateNumber - b.candidateNumber);
  const current = versions.find(item => item.key === selected);
  const context = current?.context;
  const prompt = context?.prompts[language === 'zh' ? 'chinese' : 'english'];
  return <>
    <div className="segment-selectors tabs tabs-grouped">
      <TabSelect label="画质选择" selected={stage} onChange={value => { setStage(value); setSelected(''); }} items={['一采', '二采', '后处理'].map(value => ({ value, label: value }))} />
      <TabSelect label="版本切换" disabled={!stage} selected={current?.key || ''} onChange={setSelected} items={versions.map(item => ({ value: item.key, label: item.approved ? '正式版' : candidateLabel(item.candidateNumber) }))} />
      <button disabled={!latest} onClick={() => { setStage(latest!.stage); setSelected(latest!.key); }}>最新</button>
    </div>
    <div className="segment-workspace">
      <div className="segment-media-column">
        <SegmentVideo key={current?.key || 'empty'} current={current} />
        <SegmentReferences context={context} />
      </div>
      <section className="segment-script" aria-label="分镜脚本与提示词区域">
        <div className="segment-script-header">
          <TabNav label="分段文字内容" items={[{ value: 'script', label: '分镜脚本' }, { value: 'prompt', label: '提示词' }]} selected={tab} onChange={setTab} disabled={!current} />
          <Original url={tab === 'script' ? context?.scriptUrl : context?.prompts[language === 'zh' ? 'chineseUrl' : 'englishUrl']} label="查看原文件" />
        </div>
        <div className="segment-script-content">
        {!context ? <div className="script-placeholder">{tab === 'script' ? '分镜脚本区域' : '提示词区域'}</div> : <>
          {context.source && <p className="muted">生成资料来源：{context.source}</p>}
          {tab === 'script' ? context.scriptHtml ? <Rich html={context.scriptHtml} /> : <div className="script-placeholder">该次分镜原文尚未关联或已缺失。</div> : <>
            <div className="segment-prompt-actions">
              <TabNav label="提示词语言" items={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} selected={language} onChange={setLanguage} />
              {prompt && <CopyButton label="复制" text={prompt} />}
            </div>
            {prompt ? <pre className="segment-prompt-text">{prompt}</pre> : <div className="script-placeholder">该次{language === 'zh' ? '中文参考版' : '实际提交的英文提示词'}尚未关联或已缺失。</div>}
          </>}
          {context.issues.length > 0 && <div className="notice">{context.issues.map(issue => <p key={issue}>{issue}</p>)}</div>}
        </>}
        </div>
      </section>
    </div>
  </>;
}
