'use client';
import {FormEvent,useCallback,useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {Supplier,Profile,Candidate,SupplierBatch,at,won} from './types';
import AcknowledgementForm from './AcknowledgementForm';
import PaymentEvidenceForm from './PaymentEvidenceForm';

type Trail={id:string;event:string;actor:string;created_at:string};
export default function SupplierOperations({role,mode,onShipmentImport}:{role:string;mode:string;onShipmentImport:()=>void}) {
  const [batches,setBatches]=useState<SupplierBatch[]>([]),[suppliers,setSuppliers]=useState<Supplier[]>([]),[profiles,setProfiles]=useState<Profile[]>([]),[candidates,setCandidates]=useState<Candidate[]>([]);
  const [supplier,setSupplier]=useState(''),[profile,setProfile]=useState(''),[selected,setSelected]=useState<string[]>([]),[path,setPath]=useState('MANUAL_EVIDENCE');
  const [activeId,setActiveId]=useState(''),[active,setActive]=useState<SupplierBatch|null>(null),[paymentId,setPaymentId]=useState(''),[trail,setTrail]=useState<Trail[]>([]);
  const [channel,setChannel]=useState('EMAIL'),[sendReference,setSendReference]=useState(''),[sentConfirmed,setSentConfirmed]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const canOperate=role==='operator'||role==='admin';
  const refresh=useCallback(async()=>{
    const [bs,su,pr,ca]=await Promise.all([api<SupplierBatch[]>('/v1/supplier-order-batches'),api<Supplier[]>('/v1/suppliers'),api<Profile[]>('/v1/profiles'),canOperate?api<Candidate[]>('/v1/supplier-orders/eligible'):Promise.resolve([])]);
    setBatches(bs);setSuppliers(su);setProfiles(pr);setCandidates(ca);
  },[canOperate]);
  const detail=useCallback(async()=>{
    if(!activeId)return;
    const [value,events]=await Promise.all([api<SupplierBatch>(`/v1/supplier-order-batches/${activeId}`),api<Trail[]>(`/v1/supplier-order-batches/${activeId}/trail`)]);
    setActive(value);setTrail(events);
  },[activeId]);
  const reload=useCallback(async()=>{await refresh();await detail();},[refresh,detail]);
  useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[refresh]);
  useEffect(()=>{setActive(null);setPaymentId('');setSendReference('');setSentConfirmed(false);void detail().catch(e=>setError(String(e)));},[detail]);
  async function action(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await reload();}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function create(event:FormEvent){event.preventDefault();await action(async()=>{
    const payload={supplier_id:supplier,profile_id:profile,supplier_order_ids:[...selected].sort(),payment_path:path};
    // Payload-derived key survives double-click, network retry and page reopen.
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(payload)));
    const key='console-batch-'+Array.from(new Uint8Array(bytes)).map(x=>x.toString(16).padStart(2,'0')).join('');
    const result=await api<SupplierBatch>('/v1/supplier-order-batches',{method:'POST',body:JSON.stringify({...payload,idempotency_key:key})});
    setSelected([]);setActiveId(result.id);
  });}
  async function download(){if(!active)return;await action(async()=>{
    const response=await fetch(`/api/v1/supplier-order-batches/${active.id}/file`,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok){const body=await response.json();throw new Error(body.error||'다운로드 실패');}
    const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`supplier-batch-${active.id}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });}
  async function cancellation(so:string,confirm:boolean){
    if(confirm){const reference=window.prompt('공급사의 실제 취소 확인 참조 번호');if(!reference)return;
      if(!window.confirm('공급사가 취소를 확인했습니까? 지급·증빙이 있으면 자금은 자동 복구되지 않고 대사 검토로 남습니다.'))return;
      await action(()=>api(`/v1/supplier-orders/${so}/cancellation/confirm`,{method:'POST',body:JSON.stringify({reference,supplier_confirmed_cancelled:true})}));
    }else if(window.confirm('이 공급사 주문의 취소를 요청합니까? 전송 후에는 공급사 확인 전까지 예약이 유지됩니다.'))await action(()=>api(`/v1/supplier-orders/${so}/cancel`,{method:'POST'}));
  }
  return <div className="supplier-operations">
    <div className="toolbar"><h2>공급사 Excel 운영</h2><button disabled={busy} onClick={()=>void reload().catch(e=>setError(String(e)))}>새로고침</button>{canOperate&&<button onClick={onShipmentImport}>송장 파일 가져오기</button>}</div>
    <p className="notice">생성 → 다운로드 → 실제 전송 → 공급사 응답 → 지급 증빙 → 송장 대기. 화면의 목록에는 고객 주소·전화번호를 표시하지 않습니다.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    {canOperate&&<details><summary>새 발주 배치 생성</summary><form className="supplier-form" onSubmit={create}>
      <div className="supplier-fields"><label>공급사<select required value={supplier} onChange={e=>{setSupplier(e.target.value);setProfile('');setSelected([]);}}><option value="">공급사 선택</option>{suppliers.filter(x=>x.mode==='excel'&&x.active).map(x=><option value={x.id} key={x.id}>{x.name}</option>)}</select></label>
      <label>고정할 프로필<select required value={profile} onChange={e=>setProfile(e.target.value)}><option value="">프로필 선택</option>{profiles.filter(x=>x.supplier_id===supplier).map(x=><option value={x.id} key={x.id}>{x.name} · v{x.version}</option>)}</select></label>
      <label>지급 확인 경로<select value={path} onChange={e=>setPath(e.target.value)}><option value="MANUAL_EVIDENCE">수동 지급 증빙 · 관리자 확인</option>{mode!=='production'&&<option value="DEMO_PROVIDER">합성 모의 지급 · 실제 송금 아님</option>}</select></label></div>
      {candidates.filter(x=>x.supplier_id===supplier).map(x=><label className="check" key={x.id}><input type="checkbox" checked={selected.includes(x.id)} onChange={e=>setSelected(e.target.checked?[...selected,x.id]:selected.filter(id=>id!==x.id))}/><span className="mono">{x.id}</span> · {won(x.amount)}</label>)}
      <button className="primary" disabled={busy||!profile||selected.length===0}>{selected.length}건 배치 생성</button>
    </form></details>}
    <div className="tablewrap"><table><thead><tr><th>배치 / 공급사</th><th>프로필</th><th>행</th><th>파일 / 접수 상태</th><th>수락 / 거절 / 검토</th><th>지급 / 송장 대기</th><th>생성 / 다운로드 / 전송</th></tr></thead><tbody>
      {batches.map(b=><tr key={b.id}><td><button className="mono" onClick={()=>setActiveId(b.id)}>{b.id}</button><small>{suppliers.find(x=>x.id===b.supplier_id)?.name||b.supplier_id}</small></td><td>{profiles.find(x=>x.id===b.profile_id)?.name||b.profile_id}<small>고정 v{b.profile_version}</small></td><td>{b.order_count}</td><td>{b.status}<small>{b.acknowledgement_state}</small></td><td>{b.accepted_count} / {b.rejected_count} / {b.review_count}</td><td>{b.payment_pending_count} / {b.shipment_pending_count}</td><td><small>{at(b.generated_at)}</small><small>{at(b.exported_at)}</small><small>{at(b.sent_at)}</small></td></tr>)}
    </tbody></table></div>
    {!batches.length&&<p className="empty">생성된 공급사 배치가 없습니다.</p>}
    {active&&<section className="supplier-detail"><h3 className="mono">{active.id}</h3>
      <p>접수 확인: {at(active.acknowledged_at)} · 지급 경로: {active.payment_path}</p>
      <div className="toolbar">{canOperate&&!['INVALIDATED','CANCELLED','CANCEL_PENDING'].includes(active.status)&&<button disabled={busy} onClick={()=>void download()}>개인정보 포함 발주서 다운로드</button>}{canOperate&&!['RESOLVED','INVALIDATED','CANCELLED'].includes(active.status)&&<button disabled={busy} onClick={()=>{if(window.confirm('배치 전체 취소를 요청합니까?'))void action(()=>api(`/v1/supplier-order-batches/${active.id}/cancel`,{method:'POST'}));}}>배치 취소 요청</button>}{role==='admin'&&active.status!=='RESOLVED'&&<button disabled={busy} onClick={()=>void action(()=>api(`/v1/supplier-order-batches/${active.id}/resolve`,{method:'POST'}))}>업무 종료 검증</button>}</div>
      {canOperate&&['FILE_READY','EXPORTED'].includes(active.status)&&<form className="supplier-form" onSubmit={e=>{e.preventDefault();void action(()=>api(`/v1/supplier-order-batches/${active.id}/mark-sent`,{method:'POST',body:JSON.stringify({send_channel:channel,send_reference:sendReference,file_hash:active.file_hash})}));}}>
        <h4>실제 전송 기록</h4><label>전송 채널<select value={channel} onChange={e=>setChannel(e.target.value)}>{['EMAIL','PORTAL','MESSENGER','MANUAL','OTHER'].map(x=><option key={x}>{x}</option>)}</select></label>
        <label>전송 참조 번호<input required value={sendReference} onChange={e=>setSendReference(e.target.value)} maxLength={160} pattern="[A-Za-z0-9][A-Za-z0-9._:/-]*" placeholder="email-message-001"/></label>
        <label className="check"><input type="checkbox" required checked={sentConfirmed} onChange={e=>setSentConfirmed(e.target.checked)}/>이 배치의 파일을 실제로 전송했습니다.</label><button disabled={busy||!sentConfirmed}>전송 사실 기록</button>
      </form>}
      {canOperate&&active.sent_at&&!active.acknowledged_at&&<AcknowledgementForm key={active.id} batch={active} onSaved={reload}/>}
      <div className="tablewrap"><table><thead><tr><th>공급사 주문</th><th>접수 / 거절 사유</th><th>공급사 진행 상태</th><th>지급 상태</th><th>작업</th></tr></thead><tbody>{active.items?.map(line=><tr key={line.supplier_order_id}><td className="mono">{line.supplier_order_id}</td><td>{line.ack_status}<small>{line.rejection_reason}</small></td><td>{line.status}</td><td>{line.payment_status||'미준비'}</td><td>{canOperate&&line.payment_id&&active.payment_path==='MANUAL_EVIDENCE'&&<button onClick={()=>setPaymentId(line.payment_id||'')}>지급 증빙</button>}{canOperate&&!['CANCELLED','SHIPPED'].includes(line.status)&&<button disabled={busy} onClick={()=>void cancellation(line.supplier_order_id,false)}>취소 요청</button>}{role==='admin'&&line.status==='CANCEL_PENDING'&&<button disabled={busy} onClick={()=>void cancellation(line.supplier_order_id,true)}>공급사 취소 확인</button>}{role==='admin'&&line.status==='MANUAL_REVIEW'&&<button disabled={busy} onClick={()=>{const reference=window.prompt('공급사가 원래 조건을 재확인한 참조 번호');if(reference&&window.confirm('원래 금액·수량·SKU·배송지가 변경 없이 재확인되었습니까?'))void action(()=>api(`/v1/supplier-orders/${line.supplier_order_id}/revalidate`,{method:'POST',body:JSON.stringify({reference,original_terms_reconfirmed:true})}));}}>원래 조건 재검증</button>}</td></tr>)}</tbody></table></div>
      {paymentId&&canOperate&&<PaymentEvidenceForm key={paymentId} paymentId={paymentId} role={role} onSaved={reload}/>}
      <details><summary>공급사 업무 감사 이력 ({trail.length})</summary>{trail.map(event=><p key={event.id}>{at(event.created_at)} · <b>{event.event}</b> · {event.actor}</p>)}</details>
    </section>}
  </div>;
}
