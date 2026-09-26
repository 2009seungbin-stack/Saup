'use client';
import {useEffect, useRef, useState} from 'react';
import {CreativeDraft, CreativeOutput, detailHtml, download, emptyDraft, readPhoto, renderCreative, restoreDraft, themes, zip} from '../../lib/creative';
import styles from './CreativeStudio.module.css';

type Product = {id:string;title:string;sku:string;price:number;marketplace:string};
type Preview = CreativeOutput & {url:string};
const labels: Record<string,string> = {'thumbnail-clean.png':'사진 중심','thumbnail-title.png':'상품명 강조','thumbnail-card.png':'카드형','detail.png':'상세페이지'};
export default function CreativeStudio({products,role}:{products:Product[];role:string}) {
  const [draft,setDraft]=useState<CreativeDraft>({...emptyDraft}),[outputs,setOutputs]=useState<Preview[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[dirty,setDirty]=useState(false);
  const [selected,setSelected]=useState(''),[preview,setPreview]=useState('detail.png');
  const urls=useRef<string[]>([]);
  useEffect(()=>()=>urls.current.forEach(URL.revokeObjectURL),[]);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};if(dirty)window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
  function update(next:Partial<CreativeDraft>) {
    setDraft(d=>({...d,...next}));setDirty(true);setMessage('');
    urls.current.forEach(URL.revokeObjectURL);urls.current=[];setOutputs([]);
  }
  async function task(fn:()=>Promise<void>) {setBusy(true);setError('');setMessage('');try{await fn();}catch(e){setError(e instanceof Error?e.message:'제작 중 오류가 발생했습니다.');}finally{setBusy(false);}}
  function loadProduct() {
    const p=products.find(p=>p.id===selected);if(!p)return;
    // A new product must not inherit the previous product's facts or pictures.
    if(dirty&&!window.confirm('현재 편집 내용을 새 상품으로 바꿀까요? 필요한 경우 편집 파일을 먼저 저장하세요.'))return;
    update({...emptyDraft,title:p.title,sku:p.sku,price:String(p.price),theme:draft.theme,thumbnailSize:draft.thumbnailSize,detailWidth:draft.detailWidth});
  }
  async function addPhotos(files:FileList|null) {
    if(!files?.length)return;
    await task(async()=>{if(draft.photos.length+files.length>6)throw new Error('사진은 최대 6장까지 사용할 수 있습니다.');
      const added=[];for(const file of Array.from(files))added.push(await readPhoto(file));update({photos:[...draft.photos,...added]});});
  }
  async function generate() {
    await task(async()=>{const rendered=await renderCreative(draft);urls.current.forEach(URL.revokeObjectURL);
      const next=rendered.map(o=>({...o,url:URL.createObjectURL(o.blob)}));urls.current=next.map(o=>o.url);setOutputs(next);setMessage('상세페이지 1개와 섬네일 3개를 생성했습니다.');});
  }
  function saveDraft(){download(new Blob([JSON.stringify(draft)],{type:'application/json'}),'saup-creative-project.json');setDirty(false);setMessage('사진과 편집 내용을 파일로 저장했습니다.');}
  async function exportAll(){await task(async()=>{const detail=outputs.find(o=>o.name==='detail.png');if(!detail)throw new Error('먼저 이미지를 생성하세요.');
    const blob=await zip([...outputs,{name:'detail.html',blob:new Blob([detailHtml(draft.title,'detail.png')],{type:'text/html;charset=utf-8'})},
      {name:'saup-creative-project.json',blob:new Blob([JSON.stringify(draft)],{type:'application/json'})},
      {name:'README.txt',blob:new Blob(['detail.html과 detail.png는 같은 폴더에 두세요.\n섬네일은 용도에 맞는 한 가지를 선택하세요. 마켓별 업로드 규격은 게시 전에 확인하세요.\n편집 파일에는 상품 사진과 입력 내용이 포함됩니다. Saup 상품 제작에서 다시 열 수 있습니다.\n이 파일은 외부 마켓에 자동 게시되지 않습니다.'],{type:'text/plain;charset=utf-8'})}]);
    download(blob,'saup-product-assets.zip');setDirty(false);setMessage('PNG 4개, 상세 HTML, 편집 파일을 ZIP으로 저장했습니다.');});}
  if(role==='viewer')return <div className={styles.studio}><h2>상품 제작</h2><p>상세페이지·섬네일 제작은 운영자 또는 관리자 계정으로 이용할 수 있습니다.</p></div>;
  const active=outputs.find(o=>o.name===preview);
  return <div className={styles.studio}>
    <div className={styles.intro}><div><span className={styles.eyebrow}>SAUP CREATIVE STUDIO</span><h2>상품 사진을, 판매 콘텐츠로.</h2><p>사진과 확인된 상품 정보로 상세페이지와 섬네일을 한 번에 만드세요.</p></div><span className={styles.pill}>사진 기반 자동 레이아웃</span></div>
    <div className={styles.layout}>
      <div className={styles.editor}>
        <fieldset disabled={busy}>
          <section className={styles.block}><h3>01 · 상품 정보</h3><label>등록 상품<select aria-label="등록 상품" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">직접 입력하거나 상품 선택</option>{products.map(p=><option value={p.id} key={p.id}>{p.title} · {p.marketplace} · {p.sku}</option>)}</select></label><button type="button" onClick={loadProduct} disabled={!selected}>선택 상품 불러오기</button>
            <label>상품명<input maxLength={80} value={draft.title} onChange={e=>update({title:e.target.value})} placeholder="예: 세라믹 머그 350ml"/></label>
            <label>한 줄 소개<input maxLength={120} value={draft.subtitle} onChange={e=>update({subtitle:e.target.value})} placeholder="상품의 특징을 직접 입력하세요"/></label>
            <div className={styles.two}><label>브랜드<input maxLength={40} value={draft.brand} onChange={e=>update({brand:e.target.value})}/></label><label>상품 코드<input maxLength={80} value={draft.sku} onChange={e=>update({sku:e.target.value})}/></label></div>
            <label className={styles.check}><input type="checkbox" checked={draft.showPrice} onChange={e=>update({showPrice:e.target.checked})}/>판매가 표시</label>
            {draft.showPrice&&<label>판매가 (원)<input inputMode="numeric" maxLength={10} value={draft.price} onChange={e=>update({price:e.target.value})}/></label>}
          </section>
          <section className={styles.block}><h3>02 · 상품 사진</h3><p>첫 번째 사진이 대표 사진입니다. 최대 6장 · JPG/PNG/WebP · 장당 10MB</p>
            <label className={styles.upload}>＋ 사진 추가<input aria-label="상품 사진 추가" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e=>{void addPhotos(e.target.files);e.target.value='';}}/></label>
            <div className={styles.photos}>{draft.photos.map((src,i)=><div key={i}><img src={src} alt={`상품 사진 ${i+1}`}/><small>{i===0?'대표 사진':`추가 사진 ${i}`}</small><div>{i>0&&<button aria-label={`${i+1}번 사진을 대표로`} onClick={()=>update({photos:[src,...draft.photos.filter((_,j)=>j!==i)]})}>대표로</button>}<button aria-label={`${i+1}번 사진 삭제`} onClick={()=>update({photos:draft.photos.filter((_,j)=>j!==i)})}>삭제</button></div></div>)}</div>
          </section>
          <section className={styles.block}><h3>03 · 상세 내용</h3><p>입력한 내용만 포함합니다. 비워 둔 항목은 결과물에서 생략됩니다.</p>
            <label>상품 정보<textarea rows={4} maxLength={800} value={draft.facts} onChange={e=>update({facts:e.target.value})} placeholder={'소재: 확인된 소재\n크기: 실제 규격\n구성: 실제 구성품'}/></label>
            <label>상세 설명<textarea rows={5} maxLength={1600} value={draft.description} onChange={e=>update({description:e.target.value})}/></label>
            <label>구매 전 확인<textarea rows={3} maxLength={800} value={draft.notice} onChange={e=>update({notice:e.target.value})} placeholder="확인된 보관법, 배송 안내, 주의사항 등"/></label>
          </section>
          <section className={styles.block}><h3>04 · 디자인과 출력</h3><div className={styles.swatches}>{Object.entries(themes).map(([key,t])=><button key={key} type="button" aria-pressed={draft.theme===key} onClick={()=>update({theme:key as CreativeDraft['theme']})}><i style={{background:t.accent}}/>{t.name}</button>)}</div>
            <div className={styles.two}><label>섬네일 크기<select aria-label="섬네일 크기" value={draft.thumbnailSize} onChange={e=>update({thumbnailSize:Number(e.target.value)})}>{[800,1000,1200].map(v=><option key={v} value={v}>{v} × {v}px</option>)}</select></label><label>상세페이지 너비<select aria-label="상세페이지 너비" value={draft.detailWidth} onChange={e=>update({detailWidth:Number(e.target.value)})}>{[860,1000].map(v=><option key={v} value={v}>{v}px</option>)}</select></label></div>
            <button className="primary" onClick={()=>void generate()} disabled={!draft.title.trim()||!draft.photos.length}>{busy?'제작 중…':'상세페이지·섬네일 자동 생성'}</button>
          </section>
          <div className={styles.project}><button onClick={saveDraft}>편집 파일 저장</button><label className={styles.upload}>편집 파일 열기<input aria-label="편집 파일 열기" type="file" accept="application/json,.json" onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f&&(!dirty||window.confirm('현재 내용을 편집 파일로 바꿀까요?')))void task(async()=>{const d=await restoreDraft(f);update(d);setMessage('편집 파일을 불러왔습니다. 자동 생성을 눌러 결과를 확인하세요.');});}}/></label></div>
          <p className={styles.footnote}>편집 내용은 서버에 저장되지 않습니다. 페이지를 새로고침하거나 닫기 전에 편집 파일을 저장하세요. 사진은 흰 배경에 맞추어 최대 1600px로 정리됩니다.</p>
        </fieldset>
      </div>
      <section className={styles.preview} aria-label="제작 결과 미리보기"><div className={styles.previewHead}><div><h3>미리보기</h3><p>상세페이지 + 섬네일 3종</p></div><button className="primary" disabled={busy||!outputs.length} onClick={()=>void exportAll()}>전체 ZIP 다운로드</button></div>
        {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status" className={styles.success}>{message}</p>}
        {outputs.length>0?<><div className={styles.tabs}>{outputs.map(o=><button key={o.name} aria-pressed={preview===o.name} onClick={()=>setPreview(o.name)}>{labels[o.name]}</button>)}</div>{active&&<><div className={styles.dimensions}><span>{active.width} × {active.height}px · PNG</span><button onClick={()=>download(active.blob,active.name)}>현재 PNG 다운로드</button></div><div className={styles.artboard}><img src={active.url} alt={`${labels[active.name]} 미리보기`}/></div></>}</>:<div className={styles.empty}><div>01 → 04</div><h3>사진 한 장에서 시작하세요</h3><p>상품명과 사진을 넣고 자동 생성을 누르면<br/>다운로드 가능한 결과물이 여기에 나타납니다.</p><span>사진 중심 · 상품명 강조 · 카드형 · 긴 상세페이지</span></div>}
      </section>
    </div>
  </div>;
}
