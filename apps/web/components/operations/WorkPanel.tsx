'use client';
import {useCallback,useEffect,useState} from 'react';
import {api} from '../../lib/api';
import CommandForm,{evidence,Field} from './CommandForm';
type Order={id:string;external_id:string;marketplace:string;state:string;gross_sale:number;discount:number;fee:number;promotion_cost:number};
type Claim={id:string;order_id:string;category:string;status:string;requested_amount:number;customer_refund:number;supplier_accepted_amount:number;supplier_recovery:number};
type Refund={id:string;order_id:string;claim_id:string;amount:number;status:string};
type Shipment={id:string;order_id:string;marketplace:string;external_order_id:string;external_line_id:string;tracking_hash:string;courier:string;tracking:string;marketplace_synced:boolean;manual_confirmation:string|null;state:string};
type Settlement={id:string;order_id:string;external_id:string;expected:number;actual:number;adjustment:number;difference:number;confirmed_cash:boolean;revision:number};
type Work={orders:Order[];claims:Claim[];refunds:Refund[];shipments:Shipment[];settlements:Settlement[];receipts:{id:string;kind:string;target_id:string;reference:string;actor:string}[];settlement_history:{id:string;settlement_id:string;revision:number;reason:string;before:{actual:number};after:{actual:number}}[]};
export default function WorkPanel({role,section}:{role:string;section:'클레임'|'정산'|'외부 처리 확인'}){
  const [data,setData]=useState<Work|null>(null),[error,setError]=useState('');
  const refresh=useCallback(async()=>{try{setData(await api<Work>('/v1/operations'));}catch(e){setError(String(e));}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  if(!data)return <p>{error||'조회 중…'}</p>;
  const admin=role==='admin',operator=role!=='viewer';
  const amount:Field={name:'amount',label:'금액 (원)',type:'number',min:1};
  const statement:Field[]=[{name:'external_id',label:'마켓 정산서 ID'},{name:'actual',label:'실제 정산 예정액 (원)',type:'number'},{name:'adjustment',label:'명시적 조정액 (원)',type:'number',min:-1000000000,value:0},...evidence];
  return <section aria-label={section}><h2>{section}</h2><button onClick={()=>void refresh()}>목록 새로고침</button>
    {section==='외부 처리 확인'&&data.shipments.map(x=><article key={x.id} className="supplier-form"><h3>{x.external_order_id}</h3><p>{x.courier} · {x.tracking} · 내부 배송 {x.state}</p><p>API 처리 표시: {String(x.marketplace_synced)} · 실제 외부 수동 확인: {x.manual_confirmation?'기록됨':'마켓 배송 외부 확인 필요'}</p>
      {operator&&!x.manual_confirmation&&<CommandForm title="마켓 배송 완료 외부 확인" path={`/v1/shipments/${x.id}/external-confirmation`} fields={evidence} body={v=>({...v,marketplace:x.marketplace,external_order_id:x.external_order_id,external_line_id:x.external_line_id,tracking_hash:x.tracking_hash})} onSaved={refresh}/>}
      {operator&&x.manual_confirmation&&x.state==='SHIPPED'&&<CommandForm title="고객 배송 완료 확인" path={`/v1/orders/${x.order_id}/delivery-confirmation`} fields={evidence} onSaved={refresh}/>}</article>)}
    {section==='클레임'&&<>{operator&&<CommandForm title="클레임 생성" path={v=>`/v1/orders/${v.order_id}/claims`} fields={[{name:'order_id',label:'배송된 주문',options:data.orders.filter(o=>o.state==='DELIVERED').map(o=>({value:o.id,label:o.external_id}))},{name:'external_id',label:'클레임 참조 번호'},{name:'category',label:'클레임 유형',options:['ROTTEN','BROKEN','BRUISED','WRONG_ITEM','MISSING_WEIGHT','DELIVERY_DELAY','MISSING_ITEM','OTHER'].map(x=>({value:x,label:x}))},amount,{name:'parcel_label',label:'운송장 증빙 확인',type:'checkbox',required:false},{name:'entire_contents',label:'전체 내용물 증빙 확인',type:'checkbox',required:false},{name:'damage_closeup',label:'손상 상세 증빙 확인',type:'checkbox',required:false}]} body={v=>({external_id:v.external_id,category:v.category,amount:v.amount,evidence:['parcel_label','entire_contents','damage_closeup'].filter(k=>v[k])})} onSaved={refresh}/>}
      {data.claims.map(c=><article key={c.id} className="supplier-form"><h3>클레임 {c.id}</h3><p>{c.category} · {c.status} · 요청 {c.requested_amount} / 고객 환불 {c.customer_refund} / 공급사 회수 {c.supplier_recovery}</p>
        {['EVIDENCE_REQUIRED','MANUAL_REVIEW'].includes(c.status)&&<p className="notice">증빙 부족 또는 예외 검토 필요. 공급사 일반 응답으로 임의 완료할 수 없습니다. 관리자 환불 승인 가능 여부를 별도로 검토하세요.</p>}
        {operator&&['READY','SUPPLIER_REVIEW'].includes(c.status)&&<CommandForm title="공급사 응답 기록" path={`/v1/claims/${c.id}/supplier-response`} fields={[{name:'accepted',label:'공급사 결정',options:[{value:'true',label:'수락'},{value:'false',label:'거절'}]},{...amount,min:0},...evidence]} body={v=>({...v,accepted:v.accepted==='true'})} onSaved={refresh}/>}
        {admin&&c.supplier_accepted_amount>0&&!c.supplier_recovery&&<CommandForm title="공급사 환급 회수 확인" notice="공급사 약속이 아니라 실제 입금된 공급사 전용 예치금 증빙입니다." path={`/v1/claims/${c.id}/supplier-recovery`} fields={[amount,...evidence]} onSaved={refresh}/>}
        {admin&&['REFUND_ELIGIBLE','PARTIALLY_REFUNDED','MANUAL_REVIEW'].includes(c.status)&&<CommandForm title="고객 환불 기록 준비" notice="외부 환불을 자동 실행하지 않습니다. 준비 후 마켓에서 처리한 정확한 금액의 증빙을 확인하세요." path={`/v1/claims/${c.id}/refunds`} fields={[amount,{name:'key',label:'고유 환불 요청 키'}]} onSaved={refresh}/>}
        {data.refunds.filter(r=>r.claim_id===c.id).map(r=><div key={r.id}><p>환불 {r.id} · {r.amount}원 · {r.status}</p>{admin&&r.status==='EVIDENCE_PENDING'&&<CommandForm title="완료된 고객 환불 확인" path={`/v1/refunds/${r.id}/external-confirmation`} fields={[...evidence,{name:'confirmed_customer_refunded',label:`고객에게 정확히 ${r.amount}원 환불이 완료되었음을 확인했습니다.`,type:'checkbox'}]} body={v=>({...v,order_id:r.order_id,claim_id:r.claim_id,amount:r.amount,marketplace:data.orders.find(o=>o.id===r.order_id)?.marketplace})} onSaved={refresh}/>}</div>)}
      </article>)}</>}
    {section==='정산'&&<>{operator&&<CommandForm title="정산서 기록" notice="정산서 입력은 현금 입금 확인이 아닙니다. 조정액은 관리자만 입력할 수 있습니다." path={v=>`/v1/orders/${v.order_id}/settlement`} fields={[{name:'order_id',label:'정산 대상 주문',options:data.orders.filter(o=>o.state==='DELIVERED').map(o=>({value:o.id,label:o.external_id}))},...statement]} body={v=>{const {order_id,...rest}=v;return rest;}} onSaved={refresh}/>}
      {data.settlements.map(s=><article className="supplier-form" key={s.id}><h3>{s.external_id} · 정정 {s.revision}회</h3><p>예상 {s.expected} / 실제 {s.actual} / 차이 {s.difference} / 조정 {s.adjustment}</p><p>{s.confirmed_cash?'입금 확인됨':'정산 실제 입금 확인 필요'}</p>{s.difference!==0&&<p className="notice">정산 차이 검토 필요. 자동 종료하지 않습니다.</p>}
        {admin&&!s.confirmed_cash&&<><CommandForm title="정산 실제 은행 입금 확인" path={`/v1/settlements/${s.id}/cash-confirmation`} fields={[{...amount,value:s.actual},...evidence]} body={v=>({...v,expected_revision:s.revision})} onSaved={refresh}/>
        <CommandForm title="미확정 정산서 정정" notice="이전 증빙과 원장은 보존되고 역분개 및 대체 분개가 추가됩니다." path={`/v1/settlements/${s.id}/corrections`} fields={[...statement,{name:'reason',label:'정정 사유',options:['WRONG_AMOUNT','WRONG_REFERENCE','WRONG_ADJUSTMENT','REPLACEMENT_STATEMENT'].map(x=>({value:x,label:x}))}]} body={v=>({...v,expected_revision:s.revision})} onSaved={refresh}/></>}
        {data.settlement_history.filter(h=>h.settlement_id===s.id).map(h=><p key={h.id}>정정 {h.revision}: {h.before.actual} → {h.after.actual} · {h.reason}</p>)}
      </article>)}</>}
    <details><summary>외부 증빙 이력</summary>{data.receipts.map(r=><p key={r.id}>{r.kind} · {r.reference} · {r.actor}</p>)}</details>
  </section>;
}
