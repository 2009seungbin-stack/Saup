'use client';
import {FormEvent,useState} from 'react';
import {api} from '../../lib/api';
import {at,won} from '../suppliers/types';
import CommandForm from '../operations/CommandForm';

export const CUSTOMER_CATEGORY='MARKETPLACE_CANCELLATION_RECONCILIATION_REQUIRED';

type Snapshot = {snapshot_hash:string;order_id:string;marketplace:string;external_order_id:string;external_line_id:string;
  customer_refund_amount:number;payment_id:string;payment_amount:number;supplier_recovery_id:string;recovery_amount:number};
type RefundRecord = {id:string;amount:number;reference:string;evidence_hash:string;actor:string;recorded_at:string};
type StatementRecord = {id:string;revision:number;customer_refund_amount:number;seller_payout_amount:number;seller_debit_amount:number;
  retained_fee_amount:number;outstanding_balance:number;classification:string;reference:string;evidence_hash:string;actor:string;recorded_at:string};
export type MarketplaceReview = {id:string;status:string;stage?:string;next_action?:string|null;eligible?:boolean;
  blocked_reason?:string|null;snapshot?:Snapshot|null|Record<string,unknown>;
  marketplace_cancellation?:{refund_evidence:RefundRecord|null;statement:StatementRecord|null;
    reconciliation:{id:string;order_state_after:string;actor:string;completed_at:string}|null}};

const STAGES:Record<string,string> = {
  CUSTOMER_REFUND_EVIDENCE_MISSING:'공급사 환급 완료 · 고객 환불 증빙 없음',
  MARKETPLACE_STATEMENT_MISSING:'고객 환불 증빙 기록됨 · 마켓 최종 정산서 없음',
  READY_FOR_COMPLETION:'최종 정산서 기록됨 · 완료 가능',
  RESOLVED:'해결됨 · 마켓 주문 취소 완료',
  BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT:'차단 — 지원하지 않는 판매자 잔여 정산',
  BLOCKED:'차단 — 자동 대사 조건 불충족',
};
const FIELDS = [['seller_payout_amount','판매자 지급액'],['seller_debit_amount','판매자 차감액'],
  ['retained_fee_amount','마켓 보유 수수료'],['outstanding_balance','미결 잔액']] as const;
type Field = typeof FIELDS[number][0];
const REF = '[A-Za-z0-9][A-Za-z0-9._:/-]*';

function amount(value:string){
  if(!/^(0|[1-9][0-9]{0,12})$/.test(value))throw new Error('금액은 0 이상의 정수로 직접 입력해야 합니다.');
  return Number(value);
}

export default function MarketplaceCancellationPanel({review,role,onChanged}:
  {review:MarketplaceReview;role:string;onChanged:()=>Promise<void>}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [reference,setReference]=useState(''),[hash,setHash]=useState(''),[attested,setAttested]=useState(false);
  const [statementRefund,setStatementRefund]=useState(''),[finalAttested,setFinalAttested]=useState(false),[cancelAttested,setCancelAttested]=useState(false);
  const [settlement,setSettlement]=useState<Record<Field,string>>({seller_payout_amount:'',seller_debit_amount:'',retained_fee_amount:'',outstanding_balance:''});
  const stage=review.stage??'BLOCKED';
  const snapshot=(review.snapshot??null) as Snapshot|null;
  const records=review.marketplace_cancellation;
  const admin=role==='admin'&&review.eligible&&snapshot!==null;
  function reset(){setReference('');setHash('');setAttested(false);setFinalAttested(false);setCancelAttested(false);setStatementRefund('');
    setSettlement({seller_payout_amount:'',seller_debit_amount:'',retained_fee_amount:'',outstanding_balance:''});}
  async function post(action:string,body:Record<string,unknown>){
    setBusy(true);setError('');
    // Stable per review+action: a double click or retry replays; different evidence conflicts server-side.
    try{await api(`/v1/review-resolutions/${review.id}/${action}`,{method:'POST',body:JSON.stringify({...body,idempotency_key:`${action}-${review.id}`})});
      reset();await onChanged();}
    catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  function recordRefund(event:FormEvent){event.preventDefault();if(!snapshot||!attested)return;
    void post('record-marketplace-refund',{snapshot_hash:snapshot.snapshot_hash,supplier_recovery_id:snapshot.supplier_recovery_id,
      marketplace:snapshot.marketplace,external_order_id:snapshot.external_order_id,external_line_id:snapshot.external_line_id,
      customer_refund_amount:snapshot.customer_refund_amount,reference,evidence_hash:hash,confirmed_customer_refunded:true});}
  function recordStatement(event:FormEvent){event.preventDefault();if(!snapshot||!records?.refund_evidence||!finalAttested||!cancelAttested)return;
    try{
      const values=Object.fromEntries(FIELDS.map(([key])=>[key,amount(settlement[key])]));
      void post('record-marketplace-statement',{snapshot_hash:snapshot.snapshot_hash,refund_evidence_id:records.refund_evidence.id,
        customer_refund_amount:amount(statementRefund),...values,reference,evidence_hash:hash,
        confirmed_final_statement:true,confirmed_marketplace_cancelled:true});
    }catch(e){setError(e instanceof Error?e.message:String(e));}}
  function complete(event:FormEvent){event.preventDefault();if(!snapshot||!records?.refund_evidence||!records.statement||!attested)return;
    void post('complete-marketplace-cancellation',{snapshot_hash:snapshot.snapshot_hash,refund_evidence_id:records.refund_evidence.id,
      statement_id:records.statement.id,expected_statement_revision:records.statement.revision??0,confirmed_reconciliation:true});}
  return <section className="supplier-form" aria-label="마켓 고객 취소 대사">
    <h4>마켓 고객 취소 대사</h4>
    <p className="notice">이 화면은 송금하지 않습니다 (this does not send money). 마켓에서 이미 완료된 고객 전액 환불과 최종 취소 정산서를 증빙으로 기록하고, 모든 조건을 다시 확인한 뒤에만 주문을 취소 완료로 바꿉니다. 지급·예약·재고는 변경하지 않습니다.</p>
    <p role="status" data-stage={stage}>대사 단계: {STAGES[stage]??stage} ({stage})</p>
    {review.blocked_reason&&stage!=='RESOLVED'&&<p className="notice">현재 실행 불가: {review.blocked_reason}</p>}
    {stage.startsWith('BLOCKED')&&<p>지원하지 않는 경우(부분 환불, 수수료 보유, 판매자 차감·지급, 배송 이후 거래, 불명확한 정산서, 다중 주문행)는 자동 완료하지 않습니다. 별도 재무 대사가 필요합니다.</p>}
    {snapshot&&<dl className="facts">
      <dt>마켓 주문</dt><dd className="mono">{snapshot.marketplace} · {snapshot.external_order_id} · 행 {snapshot.external_line_id}</dd>
      <dt>필요한 고객 전액 환불</dt><dd>{won(snapshot.customer_refund_amount)}</dd>
      <dt>공급사 환급(별도, 고객 환불 아님)</dt><dd>{won(snapshot.recovery_amount)} · 지급 {snapshot.payment_id}</dd>
    </dl>}
    {records?.refund_evidence&&<p>고객 환불 증빙: {won(records.refund_evidence.amount)} · {records.refund_evidence.reference} · {records.refund_evidence.actor} · {at(records.refund_evidence.recorded_at)}</p>}
    {records?.statement&&<p>최종 정산서: {records.statement.classification} · 고객 환불 {won(records.statement.customer_refund_amount)} · {FIELDS.map(([key,label])=>`${label} ${won(records.statement![key])}`).join(' · ')}</p>}
    {records?.reconciliation&&<p>대사 완료: 주문 {records.reconciliation.order_state_after} · {records.reconciliation.actor} · {at(records.reconciliation.completed_at)}</p>}
    {role==='admin'&&snapshot&&records?.statement&&records.refund_evidence&&!records.reconciliation&&<CommandForm title="미해결 취소 정산서 정정"
      path={`/v1/reviews/${review.id}/marketplace-statement-corrections`} onSaved={onChanged}
      notice="원본은 보존됩니다. 모든 잔여 금액이 0일 때만 기존 완료 조건을 다시 검사할 수 있습니다."
      fields={[{name:'reference',label:'새 정산서 참조 번호'},{name:'evidence_hash',label:'새 정산서 SHA-256'},
        {name:'customer_refund_amount',label:'정정 고객 환불액',type:'number'},
        ...FIELDS.map(([name,label])=>({name,label:`정정 ${label}`,type:'number' as const})),
        {name:'reason',label:'정정 사유',options:['WRONG_AMOUNT','WRONG_REFERENCE','REPLACEMENT_STATEMENT'].map(x=>({value:x,label:x}))},
        {name:'confirmed_final_statement',label:'정정된 최종 정산서를 확인했습니다.',type:'checkbox'},
        {name:'confirmed_marketplace_cancelled',label:'마켓 취소 완료를 확인했습니다.',type:'checkbox'}]}
      body={v=>({...v,idempotency_key:`correct-${records.statement!.id}-${records.statement!.revision??0}-${v.reference}`,
        snapshot_hash:snapshot.snapshot_hash,statement_id:records.statement!.id,expected_revision:records.statement!.revision??0,
        refund_evidence_id:records.refund_evidence!.id})}/>}
    {review.eligible&&role!=='admin'&&<p>관리자만 마켓 취소 대사 명령을 실행할 수 있습니다.</p>}
    {admin&&stage==='CUSTOMER_REFUND_EVIDENCE_MISSING'&&<form onSubmit={recordRefund}>
      <h5>마켓 고객 환불 증빙 기록</h5>
      <p>금액은 고정입니다: {won(snapshot!.customer_refund_amount)} (전액 환불만 지원).</p>
      <label>마켓 고객 환불 참조 번호<input required maxLength={160} pattern={REF} value={reference} onChange={e=>setReference(e.target.value)} disabled={busy}/></label>
      <label>고객 환불 증빙 SHA-256<input required maxLength={64} pattern="[a-f0-9]{64}" value={hash} onChange={e=>setHash(e.target.value)} disabled={busy}/></label>
      <label className="check"><input type="checkbox" checked={attested} onChange={e=>setAttested(e.target.checked)} disabled={busy}/>마켓에서 고객에게 전액 환불이 이미 완료되었음을 증빙으로 확인했습니다. 이 기록은 송금하지 않습니다.</label>
      <button className="primary" disabled={busy||!attested}>고객 환불 증빙 기록</button>
    </form>}
    {admin&&stage==='MARKETPLACE_STATEMENT_MISSING'&&<form onSubmit={recordStatement}>
      <h5>마켓 최종 취소 정산서 기록</h5>
      <p>모든 금액을 0이라도 직접 입력하세요. 판매자 잔여 금액이 있으면 자동 완료가 차단되고 별도 검토가 열립니다.</p>
      <label>정산서 고객 환불액<input required inputMode="numeric" pattern="0|[1-9][0-9]*" value={statementRefund} onChange={e=>setStatementRefund(e.target.value)} disabled={busy}/></label>
      {FIELDS.map(([key,label])=><label key={key}>{label}<input required inputMode="numeric" pattern="0|[1-9][0-9]*" value={settlement[key]}
        onChange={e=>setSettlement(current=>({...current,[key]:e.target.value}))} disabled={busy}/></label>)}
      <label>마켓 정산서 참조 번호<input required maxLength={160} pattern={REF} value={reference} onChange={e=>setReference(e.target.value)} disabled={busy}/></label>
      <label>정산서 증빙 SHA-256<input required maxLength={64} pattern="[a-f0-9]{64}" value={hash} onChange={e=>setHash(e.target.value)} disabled={busy}/></label>
      <label className="check"><input type="checkbox" checked={finalAttested} onChange={e=>setFinalAttested(e.target.checked)} disabled={busy}/>이 문서가 해당 주문행의 최종 취소 정산서임을 확인했습니다.</label>
      <label className="check"><input type="checkbox" checked={cancelAttested} onChange={e=>setCancelAttested(e.target.checked)} disabled={busy}/>마켓에서 주문 취소가 완료되었음을 확인했습니다.</label>
      <button className="primary" disabled={busy||!finalAttested||!cancelAttested}>최종 정산서 기록</button>
    </form>}
    {admin&&stage==='READY_FOR_COMPLETION'&&<form onSubmit={complete}>
      <h5>마켓 취소 대사 완료</h5>
      <p>완료 시 서버가 모든 조건을 다시 확인합니다. 주문만 CANCEL_REQUESTED → CANCELLED로 바뀌며 지급(SUCCEEDED)·예약(SPENT)·재고는 그대로입니다.</p>
      <label className="check"><input type="checkbox" checked={attested} onChange={e=>setAttested(e.target.checked)} disabled={busy}/>기록된 고객 환불 증빙과 0원 최종 정산서를 재확인했으며 이 명령이 송금하지 않음을 이해합니다.</label>
      <button className="primary" disabled={busy||!attested}>마켓 취소 대사 완료</button>
    </form>}
    {error&&<p className="error" role="alert">{error}</p>}
  </section>;
}
