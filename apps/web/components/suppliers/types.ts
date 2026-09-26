export type Supplier = {id:string; name:string; mode:string; active:boolean};
export type Profile = {id:string; supplier_id:string; name:string; version:number};
export type Candidate = {id:string; order_id:string; supplier_id:string; amount:number; status:string};
export type BatchLine = {
  supplier_order_id:string; order_id:string; status:string; active:boolean; ack_status:string;
  rejection_reason:string|null; amount:number; payment_id:string|null; payment_status:string|null; evidence_id:string|null;
};
export type SupplierBatch = {
  id:string; supplier_id:string; profile_id:string; profile_version:number; status:string; order_count:number;
  file_hash:string; payment_path:string; generated_at:string; exported_at:string|null; sent_at:string|null;
  acknowledged_at:string|null; acknowledgement_state:string; accepted_count:number; rejected_count:number;
  review_count:number; payment_pending_count:number; shipment_pending_count:number; items?:BatchLine[];
};
export type Evidence = {id:string; method:string; reference:string; evidence_hash:string; recorded_by:string; recorded_at:string};
export type SupplierPayment = {
  id:string; supplier_id:string; amount:number; status:string; destination_fingerprint:string;
  bank_amount:number; deposit_amount:number; evidence_id:string|null; evidence_status:string; evidence?:Evidence|null;
};
export const won = (value:number) => new Intl.NumberFormat('ko-KR',{style:'currency',currency:'KRW',maximumFractionDigits:0}).format(value);
export const at = (value:string|null) => value ? new Date(value).toLocaleString('ko-KR') : '—';
export const reasons = ['OUT_OF_STOCK','PRICE_CHANGED','SKU_NOT_FOUND','ORDER_NOT_ACCEPTED','DELIVERY_UNAVAILABLE','CUTOFF_EXCEEDED','OTHER'] as const;
export const reasonLabel:Record<string,string> = {OUT_OF_STOCK:'재고 없음',PRICE_CHANGED:'가격 변경 · 지급 차단',SKU_NOT_FOUND:'SKU 없음',ORDER_NOT_ACCEPTED:'주문 미접수',DELIVERY_UNAVAILABLE:'배송 불가',CUTOFF_EXCEEDED:'마감 초과',OTHER:'기타 거절'};
