'use client';
import {FormEvent, useState} from 'react';
import {api} from '../../lib/api';
import {SupplierBatch, reasons, reasonLabel} from './types';

type Changes = {amount?:string; shipping?:string; quantity?:string; sku?:string; destination_changed?:boolean};
export default function AcknowledgementForm({batch,onSaved}:{batch:SupplierBatch;onSaved:()=>Promise<void>}) {
  const [decisions,setDecisions]=useState<Record<string,string>>({});
  const [changes,setChanges]=useState<Record<string,Changes>>({});
  const [reference,setReference]=useState(''),[attested,setAttested]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const lines=batch.items||[];
  function change(id:string,key:keyof Changes,value:string|boolean) {
    setChanges(old=>({...old,[id]:{...old[id],[key]:value}}));
  }
  async function submit(event:FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    try {
      if(!attested||lines.some(line=>!decisions[line.supplier_order_id]))throw new Error('모든 행의 공급사 응답과 확인란을 입력하세요.');
      const accepted_order_ids=lines.filter(line=>decisions[line.supplier_order_id]==='ACCEPTED').map(line=>line.supplier_order_id);
      const rejected=lines.filter(line=>decisions[line.supplier_order_id]!=='ACCEPTED').map(line=>({supplier_order_id:line.supplier_order_id,reason:decisions[line.supplier_order_id]}));
      const reported_changes=Object.entries(changes).flatMap(([id,value])=>{
        const output:Record<string,string|number|boolean>={supplier_order_id:id};
        for(const key of ['amount','shipping','quantity'] as const)if(value[key]!==undefined&&value[key]!=='')output[key]=Number(value[key]);
        if(value.sku)output.sku=value.sku;
        if(value.destination_changed)output.destination_changed=true;
        return Object.keys(output).length>1?[output]:[];
      });
      await api(`/v1/supplier-order-batches/${batch.id}/acknowledge`,{method:'POST',body:JSON.stringify({accepted_order_ids,rejected,reported_changes,reference})});
      await onSaved();
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <form className="supplier-form" onSubmit={submit}>
    <h3>공급사 접수 결과 기록</h3>
    <p className="notice">파일 전송만으로 수락을 기록하지 않습니다. 변경된 가격·배송비·수량·SKU·주소는 자동 지급을 차단합니다. 모든 행의 결과를 선택하세요.</p>
    {lines.map(line=><fieldset key={line.supplier_order_id} disabled={busy}>
      <legend className="mono">{line.supplier_order_id}</legend>
      <label>실제 공급사 응답<select required value={decisions[line.supplier_order_id]||''} onChange={e=>setDecisions({...decisions,[line.supplier_order_id]:e.target.value})}>
        <option value="">응답 선택</option><option value="ACCEPTED">원래 조건으로 수락</option>
        {reasons.map(reason=><option key={reason} value={reason}>{reasonLabel[reason]}</option>)}
      </select></label>
      <details><summary>공급사가 변경 조건을 통보했습니다</summary><div className="supplier-fields">
        <label>통보 총액<input type="number" min="1" step="1" onChange={e=>change(line.supplier_order_id,'amount',e.target.value)}/></label>
        <label>통보 배송비<input type="number" min="0" step="1" onChange={e=>change(line.supplier_order_id,'shipping',e.target.value)}/></label>
        <label>통보 수량<input type="number" min="1" step="1" onChange={e=>change(line.supplier_order_id,'quantity',e.target.value)}/></label>
        <label>통보 SKU<input maxLength={80} onChange={e=>change(line.supplier_order_id,'sku',e.target.value)}/></label>
        <label className="check"><input type="checkbox" onChange={e=>change(line.supplier_order_id,'destination_changed',e.target.checked)}/>배송지 변경 통보 · 주소 원문은 입력하지 마세요</label>
      </div></details>
    </fieldset>)}
    <label>공급사 확인 참조 번호<input value={reference} onChange={e=>setReference(e.target.value)} required maxLength={160} pattern="[A-Za-z0-9][A-Za-z0-9._:/-]*" placeholder="supplier-confirmation-001"/></label>
    <label className="check"><input type="checkbox" checked={attested} onChange={e=>setAttested(e.target.checked)} required/>실제 공급사 응답을 확인했으며 위 결과를 그대로 기록합니다.</label>
    {error&&<p className="error" role="alert">{error}</p>}
    <button className="primary" disabled={busy||!attested}>접수 결과 기록</button>
  </form>;
}
