'use client';
import {FormEvent,useCallback,useEffect,useRef,useState} from 'react';
import {api} from '../../lib/api';

type PreviewRow={row:number;external_id:string;external_line_id:string;product_title:string|null;quantity:number;net_amount:number;status:string};
type Preview={preview_token:string;file_hash:string;new_count:number;duplicate_count:number;error_count:number;can_commit:boolean;rows:PreviewRow[];errors:{row:number;code:string;fields?:string[]}[]};
type Pending={id:string;external_id:string;external_line_id:string;state:string;net_amount:number;snapshot_hash:string;file_hash:string;can_verify_and_validate:boolean;blocked_reasons:string[];reviews:{category:string;status:string}[]};
type Receipt={id:string;created_at:string;marketplace:string;new_count:number;duplicate_count:number};
type CommitResult=Receipt&{replayed:boolean;items:{id:string;state:string;duplicate:boolean}[]};
const won=(v:number)=>new Intl.NumberFormat('ko-KR',{style:'currency',currency:'KRW',maximumFractionDigits:0}).format(v);
const errorText:Record<string,string>={
  IDENTIFIER_MUST_BE_TEXT:'주문번호·행번호·상품ID·전화번호·우편번호를 텍스트 형식으로 입력하세요.',
  INVALID_NUMBER:'금액·수량을 올바른 정수로 입력하세요. 할인금액이 없으면 0을 입력하세요.',
  ROW_VALIDATION_FAILED:'필수 값 또는 주소·금액·수량이 올바르지 않습니다.',
  INVALID_IDENTIFIER:'식별자에 탭이나 줄바꿈이 포함되어 있습니다.',
  FORMULA_NOT_ALLOWED:'수식은 가져올 수 없습니다. 확인된 원본 값을 입력하세요.',
  DUPLICATE_ORDER_ROW:'파일 안에 같은 주문번호와 행번호가 중복되어 있습니다.',
  INVALID_LISTING:'선택한 마켓의 판매상품ID가 아닙니다. 상품ID 목록을 확인하세요.',
  ORDER_FILE_REQUIRES_EXCEL_SUPPLIER:'이 입력 경로는 Excel 공급사에 연결된 상품만 지원합니다.',
  ORDER_IDENTITY_PAYLOAD_CONFLICT:'이미 등록된 주문과 금액·주소·상품 등이 다릅니다. 기존 주문을 덮어쓰지 않습니다.',
  ORDER_PREVIEW_STALE:'미리보기 이후 주문 정보가 달라졌습니다. 다시 미리 보기를 실행하세요.',
  ORDER_PREVIEW_EXPIRED:'미리보기 유효시간이 지났습니다. 같은 파일을 다시 확인하세요.',
  ORDER_PREVIEW_TOKEN_INVALID:'파일·마켓·로그인 사용자가 달라졌습니다. 다시 미리 보기를 실행하세요.',
  ORDER_TEMPLATE_HEADERS_REQUIRED:'다운로드한 양식의 열 이름과 순서를 유지하세요.',
  ORDER_TEMPLATE_SHEET_REQUIRED:'표준 양식의 ‘주문’ 시트 하나만 포함해야 합니다.',
  ORDER_WORKSHEET_LIMIT:'표준 양식은 500행까지 지원합니다. 추가 열·시트·숨겨진 행도 확인하세요.',
  EMPTY_ORDER_FILE:'입력된 주문 행이 없습니다.',
  ORDER_VALIDATION_SNAPSHOT_STALE:'확인 중에 주문·상품 정보가 바뀌었습니다. 대기 목록을 새로고침하고 다시 확인하세요.',
  CURRENT_MARKETPLACE_EVIDENCE_REQUIRED:'최근 15분 이내에 확인한 현재 주문 상태의 증거가 필요합니다.',
  ORDER_HOLD:'설정된 주문 보류 시간이 아직 지나지 않았습니다.',
  ORDER_ALREADY_HAS_BUSINESS_EFFECTS:'이미 발주 또는 자금 예약이 있습니다. 기존 공급사 업무에서 처리하세요.',
  ORDER_NOT_VALIDATABLE:'취소되었거나 이미 다음 단계로 진행한 주문입니다.',
  ORDER_HAS_UNSUPPORTED_REVIEW:'다른 검토가 남아 있습니다. 검토 큐에서 원인을 확인하세요.',
  SUPPLIER_CUTOFF:'공급사 주문 마감 이후입니다.',
  OUT_OF_STOCK:'공급사 재고가 부족합니다.',
  STALE_INVENTORY:'공급사 재고 정보가 오래되었습니다.',
  INSUFFICIENT_CASH:'안전 준비금과 기존 예약을 제외한 자금이 부족합니다.',
  MARGIN_BELOW_THRESHOLD:'설정한 최소 마진에 미달합니다.',
  LISTING_PAUSED:'상품이 판매중지 상태입니다.',
  MARKETPLACE_ORDER_SOURCE_VERIFICATION_REQUIRED:'현재 마켓 주문 상태를 확인해야 합니다.',
};
const explain=(code:string)=>errorText[code]||code;

export default function OrderIntakePanel({role,onSuppliers}:{role:string;onSuppliers:()=>void}){
  const [market,setMarket]=useState('coupang'),[file,setFile]=useState<File|null>(null),[preview,setPreview]=useState<Preview|null>(null);
  const [source,setSource]=useState(''),[authorized,setAuthorized]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [history,setHistory]=useState<Receipt[]>([]),[pending,setPending]=useState<Pending[]>([]),[selected,setSelected]=useState<Pending|null>(null);
  const [reference,setReference]=useState(''),[hash,setHash]=useState(''),[checked,setChecked]=useState(false);
  const requestRef=useRef<{fingerprint:string;body:Record<string,unknown>}|null>(null);
  const refresh=useCallback(async()=>{
    setHistory(await api<Receipt[]>('/v1/order-imports'));
    if(role!=='viewer')setPending(await api<Pending[]>('/v1/order-intake/pending'));
  },[role]);
  useEffect(()=>{void refresh().catch(e=>setError(explain(String(e.message||e))));},[refresh]);
  function reset(){setPreview(null);setAuthorized(false);setError('');setNotice('');}
  async function previewFile(event:FormEvent){event.preventDefault();if(!file)return;
    setBusy(true);setError('');setPreview(null);setAuthorized(false);
    try{const data=new FormData();data.append('marketplace',market);data.append('file',file);
      setPreview(await api<Preview>('/v1/order-imports/preview',{method:'POST',body:data}));
    }catch(e){setError(explain(e instanceof Error?e.message:String(e)));}finally{setBusy(false);}}
  async function commit(){if(!file||!preview||!authorized)return;setBusy(true);setError('');
    try{const data=new FormData();data.append('file',file);data.append('command',JSON.stringify({marketplace:market,preview_token:preview.preview_token,source_reference:source,confirmed_authorized_source:true}));
      const result=await api<CommitResult>('/v1/order-imports/commit',{method:'POST',body:data});
      setNotice(result.replayed?'이미 처리한 파일입니다. 주문은 중복 생성되지 않았습니다.':`새 주문 ${result.new_count}건을 등록했습니다. 현재 주문 상태를 확인한 뒤 내부 검증을 진행하세요.`);
      setPreview(null);setAuthorized(false);await refresh();
    }catch(e){setError(explain(e instanceof Error?e.message:String(e)));}finally{setBusy(false);}}
  async function open(order:Pending){setBusy(true);setError('');setSelected(null);setChecked(false);setReference('');setHash('');requestRef.current=null;
    try{setSelected(await api<Pending>(`/v1/order-intake/${order.id}`));}catch(e){setError(explain(e instanceof Error?e.message:String(e)));}finally{setBusy(false);}}
  async function verify(event:FormEvent){event.preventDefault();if(!selected||!checked)return;setBusy(true);setError('');
    const identity=JSON.stringify([selected.id,selected.snapshot_hash,reference,hash]);
    // Network retries retain the exact key, payload and observation timestamp.
    if(requestRef.current?.fingerprint!==identity)requestRef.current={fingerprint:identity,body:{
      idempotency_key:`order-verify-${crypto.randomUUID()}`,snapshot_hash:selected.snapshot_hash,
      source_reference:reference,evidence_hash:hash,observed_at:new Date().toISOString(),confirmed_current_order_open:true}};
    try{const result=await api<{state:string}>(`/v1/order-intake/${selected.id}/verify-and-validate`,{method:'POST',body:JSON.stringify(requestRef.current.body)});
      setNotice(result.state==='SUPPLIER_ORDER_PENDING'?'내부 검증을 통과했습니다. 공급사 운영에서 발주 배치를 생성하세요. 아직 공급사 접수·지급 완료가 아닙니다.':'내부 검증에서 중단되었습니다. 대기 목록의 검토 사유를 확인하세요.');
      setSelected(null);setChecked(false);requestRef.current=null;await refresh();
    }catch(e){setError(explain(e instanceof Error?e.message:String(e)));}finally{setBusy(false);}}
  async function hashLocal(f:File){if(f.size>10_000_000)throw new Error('증빙 파일은 10MB 이하로 선택하세요.');
    const digest=await crypto.subtle.digest('SHA-256',await f.arrayBuffer());
    setHash(Array.from(new Uint8Array(digest)).map(v=>v.toString(16).padStart(2,'0')).join(''));setChecked(false);requestRef.current=null;}
  return <section className="supplier-operations">
    <h2>주문 가져오기</h2>
    <p className="notice">파일을 등록해도 발주하거나 송금하지 않습니다. 판매자 원본을 확인한 후 기존 재고·마진·자금 검증을 진행합니다.</p>
    {role!=='viewer'&&<>
      <form className="supplier-form" onSubmit={previewFile}>
        <div className="toolbar"><label>주문 마켓<select aria-label="주문 마켓" value={market} disabled={busy} onChange={e=>{setMarket(e.target.value);reset();}}>
          <option value="coupang">쿠팡</option><option value="temu">테무</option><option value="aliexpress">알리익스프레스</option></select></label>
          <a className="button" href="/api/v1/order-imports/template">빈 주문 양식</a>
          <a className="button" href={`/api/v1/order-imports/catalog?marketplace=${market}`}>판매상품ID 목록</a></div>
        <p className="muted">Saup 표준 XLSX 양식 · 최대 500행 · 금액은 원 단위 정수 · 할인금액도 입력 · 고객 정보는 미리보기에 표시하지 않습니다. 마켓 원본을 자동 변환하는 기능은 아닙니다.</p>
        <label>주문 XLSX 파일<input type="file" accept=".xlsx" disabled={busy} onChange={e=>{setFile(e.target.files?.[0]||null);reset();}} required/></label>
        <button className="primary" disabled={busy||!file}>파일 미리 보기</button>
      </form>
      {preview&&<section className="supplier-form"><h3>미리보기 · 신규 {preview.new_count} / 중복 {preview.duplicate_count} / 오류 {preview.error_count}</h3>
        <div className="tablewrap"><table><thead><tr><th>행</th><th>주문 / 상품</th><th>수량</th><th>할인 후 금액</th><th>상태</th></tr></thead>
          <tbody>{preview.rows.map(row=><tr key={row.row}><td>{row.row}</td><td>{row.external_id} / {row.external_line_id}<small>{row.product_title}</small></td><td>{row.quantity}</td><td>{won(row.net_amount)}</td><td>{row.status}</td></tr>)}</tbody></table></div>
        {preview.errors.map((e,i)=><p className="error" key={i}>{e.row}행 · {explain(e.code)} {e.fields?.join(', ')}</p>)}
        {preview.can_commit?<>
          <label>주문 원본 참조 번호<input value={source} maxLength={160} onChange={e=>{setSource(e.target.value);setAuthorized(false);}} disabled={busy} placeholder="seller-export-20260927-001"/></label>
          <label className="check"><input type="checkbox" checked={authorized} onChange={e=>setAuthorized(e.target.checked)} disabled={busy}/>권한 있는 판매자 원본이며 미리보기의 마켓·주문·상품·금액을 확인했습니다.</label>
          <button disabled={busy||!authorized||!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$/.test(source)} onClick={()=>void commit()}>주문 등록 · 아직 발주 안 함</button>
        </>:<p>오류 행을 수정한 파일로 다시 미리 보기를 실행하세요. 정상 행만 몰래 등록하지 않습니다.</p>}
      </section>}
      <h3>원본 확인 / 내부 검증 대기</h3>
      <button disabled={busy} onClick={()=>{setSelected(null);void refresh().catch(e=>setError(String(e)));}}>주문 대기 새로고침</button>
      <div className="tablewrap"><table><thead><tr><th>주문</th><th>상태</th><th>다음 확인</th><th>작업</th></tr></thead><tbody>
        {pending.map(order=><tr key={order.id}><td>{order.external_id}<small>행 {order.external_line_id}</small></td><td>{order.state}</td>
          <td>{order.blocked_reasons.map(explain).join(' / ')||order.reviews.map(r=>explain(r.category)).join(' / ')||'원본 재확인 필요'}</td>
          <td><button disabled={busy} onClick={()=>void open(order)}>원본 확인 후 검증</button></td></tr>)}
      </tbody></table></div>
      {!pending.length&&<p className="empty">원본 확인이나 재검증을 기다리는 파일 주문이 없습니다.</p>}
      {selected&&<form className="supplier-form" onSubmit={verify}><h3>현재 주문 확인 · {selected.external_id} / {selected.external_line_id}</h3>
        <p>판매자 페이지나 최신 주문 자료에서 이 행이 취소되지 않은 유효 주문임을 확인하세요. 업로드한 파일 자체를 최신 상태 확인으로 간주하지 않습니다.</p>
        {selected.can_verify_and_validate?<>
          <label>현재 주문 확인 참조<input value={reference} onChange={e=>{setReference(e.target.value);setChecked(false);}} required maxLength={160} pattern="[A-Za-z0-9][A-Za-z0-9._:/-]*" disabled={busy}/></label>
          <label>현재 주문 증빙 SHA-256<input value={hash} onChange={e=>{setHash(e.target.value);setChecked(false);}} required pattern="[a-f0-9]{64}" maxLength={64} disabled={busy}/></label>
          <label>현재 주문 증빙 파일 · 해시만 계산<input type="file" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)void hashLocal(f).catch(e=>setError(String(e)));}}/></label>
          <label className="check"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)} disabled={busy}/>지금 이 주문 행이 유효하고 취소되지 않았음을 원본에서 직접 확인했습니다.</label>
          <button className="primary" disabled={busy||!checked}>확인 기록 후 내부 검증</button>
        </>:<p className="error">{selected.blocked_reasons.map(explain).join(' / ')}</p>}
      </form>}
      <button onClick={onSuppliers}>공급사 발주 / 접수 / 배송으로 이동</button>
    </>}
    {notice&&<p role="status" className="notice">{notice}</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    <h3>주문 파일 처리 이력</h3>
    <div className="tablewrap"><table><thead><tr><th>처리 시각</th><th>마켓</th><th>신규</th><th>중복</th><th>기록 ID</th></tr></thead>
      <tbody>{history.map(row=><tr key={row.id}><td>{new Date(row.created_at).toLocaleString('ko-KR')}</td><td>{row.marketplace}</td><td>{row.new_count}</td><td>{row.duplicate_count}</td><td className="mono">{row.id}</td></tr>)}</tbody></table></div>
    {!history.length&&<p>등록한 주문 파일이 없습니다.</p>}
  </section>;
}
