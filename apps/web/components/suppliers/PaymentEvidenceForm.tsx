'use client';
import {FormEvent,useCallback,useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {SupplierPayment,won} from './types';

export default function PaymentEvidenceForm({paymentId,role,onSaved}:{paymentId:string;role:string;onSaved:()=>Promise<void>}) {
  const [payment,setPayment]=useState<SupplierPayment|null>(null),[reference,setReference]=useState(''),[hash,setHash]=useState('');
  const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [correctionReason,setCorrectionReason]=useState('WRONG_ATTACHMENT');
  const refresh=useCallback(async()=>{
    const value=await api<SupplierPayment>(`/v1/supplier-payments/${paymentId}`);setPayment(value);
    if(value.evidence){setReference(value.evidence.reference);setHash(value.evidence.evidence_hash);}
  },[paymentId]);
  useEffect(()=>{setPayment(null);setConfirmed(false);setError('');void refresh().catch(e=>setError(String(e)));},[refresh]);
  async function action(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await refresh();await onSaved();}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function record(event:FormEvent){event.preventDefault();if(!payment)return;
    const method=payment.deposit_amount===payment.amount?'SUPPLIER_DEPOSIT':payment.deposit_amount===0?'MANUAL_TRANSFER':'OTHER_APPROVED_METHOD';
    await action(()=>api(`/v1/supplier-payments/${payment.id}/evidence`,{method:'POST',body:JSON.stringify({
      supplier_id:payment.supplier_id,method,amount:payment.amount,bank_amount:payment.bank_amount,deposit_amount:payment.deposit_amount,
      destination_fingerprint:payment.destination_fingerprint,reference,evidence_hash:hash})}));
  }
  async function hashLocal(file:File){
    if(file.size>10_000_000){setError('증빙 해시 계산은 10MB 이하 파일만 허용합니다.');return;}
    const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
    setHash(Array.from(new Uint8Array(digest)).map(x=>x.toString(16).padStart(2,'0')).join(''));
  }
  if(!payment)return <p role="status">{error||'지급 스냅샷 확인 중…'}</p>;
  return <section className="supplier-form">
    <h3>지급 증빙 · {won(payment.amount)}</h3>
    <p className="notice">이 화면은 송금하지 않습니다. 증빙 등록과 관리자의 실제 지급 확인은 서로 다른 단계입니다. 수취처·금액은 발주 시 동결된 값과 일치해야 합니다.</p>
    <dl><dt>지급 상태</dt><dd>{payment.status} / 증빙 {payment.evidence_status}</dd><dt>은행 / 해당 공급사 예치금</dt><dd>{won(payment.bank_amount)} / {won(payment.deposit_amount)}</dd><dt>승인 수취처 지문</dt><dd className="mono">{payment.destination_fingerprint}</dd></dl>
    {payment.status==='MANUAL_APPROVAL'&&role==='admin'&&<button disabled={busy} onClick={()=>{
      if(window.confirm(`${won(payment.amount)} 지급 준비를 승인합니까? 송금 성공을 확인하는 작업은 아닙니다.`))void action(()=>api(`/v1/payments/${payment.id}/approve`,{method:'POST',body:JSON.stringify({amount:payment.amount,destination_fingerprint:payment.destination_fingerprint})}));
    }}>한도 검토 후 지급 준비 승인</button>}
    {!payment.evidence_id&&['EVIDENCE_PENDING','MANUAL_APPROVAL'].includes(payment.status)&&<form onSubmit={record}>
      <label>은행·공급사 지급 참조 번호<input value={reference} onChange={e=>setReference(e.target.value)} required maxLength={160} pattern="[A-Za-z0-9][A-Za-z0-9._:/-]*" placeholder="receipt-20260925-001"/></label>
      <label>증빙 SHA-256<input className="mono" value={hash} onChange={e=>setHash(e.target.value)} required pattern="[a-f0-9]{64}" maxLength={64}/></label>
      <label>로컬 증빙 파일에서 해시 계산 · 파일은 업로드하지 않음<input type="file" onChange={e=>{const file=e.target.files?.[0];if(file)void hashLocal(file).catch(e=>setError(String(e)));}}/></label>
      <button disabled={busy}>증빙 기록 · 아직 지급 확정 아님</button>
    </form>}
    {payment.evidence_id&&payment.evidence_status==='RECORDED'&&role==='admin'&&<>
      <label>증빙과 일치하는 지급 참조 번호<input value={reference} onChange={e=>setReference(e.target.value)} required/></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>해당 수취처로 이 금액의 실제 지급이 완료되었음을 증빙으로 확인했습니다.</label>
      <button className="primary" disabled={busy||!confirmed||!reference||payment.status!=='EVIDENCE_PENDING'} onClick={()=>void action(()=>api(`/v1/supplier-payment-evidence/${payment.evidence_id}/confirm`,{method:'POST',body:JSON.stringify({amount:payment.amount,destination_fingerprint:payment.destination_fingerprint,reference,evidence_revision_id:payment.evidence_revision_id,confirmed_money_moved:true})}))}>관리자 지급 증빙 확인</button>
    </>}
    {payment.evidence_id&&payment.evidence_status==='RECORDED'&&role!=='admin'&&<p>관리자 확인 대기 중입니다. 운영자는 지급 확정을 수행할 수 없습니다.</p>}
    {payment.evidence_status==='CONFIRMED'&&<p role="status">관리자 지급 증빙 확인이 완료되었습니다. 이 화면에서 송금을 실행한 것은 아닙니다.</p>}
    {payment.evidence_status==='CORRECTION_REQUIRED'&&<p role="status">증빙 정정 검토 중입니다. 지급 확인이 차단되었습니다. 검토 해결 메뉴에서 처리하세요.</p>}
    {payment.evidence_id&&payment.evidence_status==='RECORDED'&&['EVIDENCE_PENDING','MANUAL_APPROVAL'].includes(payment.status)&&<div>
      <label>증빙 정정 사유<select value={correctionReason} onChange={e=>setCorrectionReason(e.target.value)} disabled={busy}>
        <option value="WRONG_ATTACHMENT">잘못된 증빙 파일</option><option value="WRONG_REFERENCE">잘못된 참조 번호</option><option value="REFERENCE_AND_ATTACHMENT">참조 번호와 증빙 파일</option>
      </select></label>
      <button disabled={busy} onClick={()=>void action(()=>api(`/v1/supplier-payment-evidence/${payment.evidence_id}/correction-request`,{method:'POST',body:JSON.stringify({
        idempotency_key:`evidence-request-${payment.evidence_id}-${payment.evidence_revision_id||'original'}`,
        expected_revision_id:payment.evidence_revision_id,reason:correctionReason})}))}>증빙 정정 요청 · 지급 확인 차단</button>
    </div>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
