'use client';
import {FormEvent,useCallback,useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {won} from '../suppliers/types';

type Snapshot = {payment_id:string;amount:number;evidence_id?:string;revision_id?:string|null;reason?:string;
  reference?:string;evidence_hash?:string;supplier_id?:string;bank_amount?:number;deposit_amount?:number;destination_fingerprint?:string};
type Review = {id:string;category:string;entity_id:string;status:string;action:string|null;
  eligible?:boolean;blocked_reason?:string|null;snapshot?:Snapshot|null;
  history?:{id:string;action:string;actor:string;resolved_at:string}[]};

export default function ReviewResolutionPanel({role,onSaved}:{role:string;onSaved:()=>Promise<void>}) {
  const [rows,setRows]=useState<Review[]>([]),[selected,setSelected]=useState<Review|null>(null);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [reference,setReference]=useState(''),[hash,setHash]=useState(''),[verified,setVerified]=useState(false);
  const refresh=useCallback(async()=>setRows(await api<Review[]>('/v1/review-resolutions')),[]);
  useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[refresh]);
  async function open(id:string){setBusy(true);setError('');setSelected(null);setVerified(false);
    try{const row=await api<Review>(`/v1/review-resolutions/${id}`);setSelected(row);
      setReference(row.snapshot?.reference||'');setHash(row.snapshot?.evidence_hash||'');
    }catch(e){setError(String(e));}finally{setBusy(false);}}
  async function submit(event:FormEvent){event.preventDefault();if(!selected?.snapshot||!verified)return;
    const snapshot=selected.snapshot;
    const correction=selected.action==='CORRECT_UNCONFIRMED_PAYMENT_EVIDENCE';
    const payload=correction?{expected_revision_id:snapshot.revision_id??null,reference,evidence_hash:hash,verified_same_payment:true}:
      {payment_id:snapshot.payment_id,supplier_id:snapshot.supplier_id,amount:snapshot.amount,
       bank_amount:snapshot.bank_amount,deposit_amount:snapshot.deposit_amount,destination_fingerprint:snapshot.destination_fingerprint,
       reference,evidence_hash:hash,confirmed_funds_received:true};
    setBusy(true);setError('');
    try{await api(`/v1/review-resolutions/${selected.id}/${correction?'correct-payment-evidence':'confirm-supplier-recovery'}`,
      {method:'POST',body:JSON.stringify({...payload,idempotency_key:`review-${selected.id}`})});
      setSelected(await api<Review>(`/v1/review-resolutions/${selected.id}`));setVerified(false);await refresh();await onSaved();
    }catch(e){setError(String(e));}finally{setBusy(false);}}
  const correction=selected?.action==='CORRECT_UNCONFIRMED_PAYMENT_EVIDENCE';
  return <section className="supplier-operations">
    <h2>검토 해결 · 증빙과 공급사 환급</h2>
    <p className="notice">검토 확인은 해결이 아닙니다. 이 화면은 송금하지 않으며, 공급사 환급을 기록해도 고객 환불·주문 종료는 별도 확인이 필요합니다.</p>
    <button disabled={busy} onClick={()=>void refresh().catch(e=>setError(String(e)))}>검토 해결 새로고침</button>
    <div className="tablewrap"><table><thead><tr><th>검토 ID</th><th>유형</th><th>상태</th><th>허용 명령</th></tr></thead>
      <tbody>{rows.map(row=><tr key={row.id}><td className="mono">{role==='viewer'?row.id:<button disabled={busy} onClick={()=>void open(row.id)}>{row.id}</button>}</td>
        <td>{row.category}</td><td>{row.status}</td><td>{row.action||'전용 대사 절차 필요'}</td></tr>)}</tbody></table></div>
    {rows.length===0&&<p>이 범위의 검토가 없습니다.</p>}
    {selected&&<section className="supplier-form"><h3>{selected.id}</h3><p role="status">검토 상태: {selected.status}</p>
      {selected.blocked_reason&&<p className="notice">현재 실행 불가: {selected.blocked_reason}</p>}
      {selected.snapshot&&<p>고정 지급 금액: {won(selected.snapshot.amount)} · 지급 ID: {selected.snapshot.payment_id}</p>}
      {selected.eligible&&role!=='admin'&&<p>관리자만 해결 명령을 실행할 수 있습니다.</p>}
      {selected.eligible&&role==='admin'&&<form onSubmit={submit}>
        <h4>{correction?'미확정 증빙 정정':'지급 후 공급사 전액 환급 확인'}</h4>
        <p>{correction?'원본은 보존됩니다. 금액·수취처·예치금 배분은 변경하지 않습니다.':
          `은행 ${won(selected.snapshot?.bank_amount??0)} / 동일 공급사 예치금 ${won(selected.snapshot?.deposit_amount??0)}의 실제 수령만 확인합니다. 부분 환급·배송 이후 거래는 지원하지 않습니다.`}</p>
        <label>해결 참조 번호<input required maxLength={160} pattern="[A-Za-z0-9][A-Za-z0-9._:/-]*" value={reference} onChange={e=>setReference(e.target.value)} disabled={busy||correction&&selected.snapshot?.reason==='WRONG_ATTACHMENT'}/></label>
        <label>해결 증빙 SHA-256<input required maxLength={64} pattern="[a-f0-9]{64}" value={hash} onChange={e=>setHash(e.target.value)} disabled={busy||correction&&selected.snapshot?.reason==='WRONG_REFERENCE'}/></label>
        <label className="check"><input type="checkbox" checked={verified} onChange={e=>setVerified(e.target.checked)} disabled={busy}/>
          {correction?'동일한 지급의 증빙 정보 정정이며 금액과 수취처는 변경하지 않음을 확인했습니다.':'표시된 은행·공급사 예치금 배분대로 환급액이 실제 입금되었음을 확인했습니다.'}</label>
        <button className="primary" disabled={busy||!verified}>{correction?'증빙 정정 적용':'관리자 공급사 환급 확인'}</button>
      </form>}
      {(selected.history??[]).map(item=><p key={item.id}>{item.action} · {item.actor} · {new Date(item.resolved_at).toLocaleString('ko-KR')}</p>)}
    </section>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
