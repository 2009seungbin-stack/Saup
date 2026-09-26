'use client';
import {useCallback,useEffect,useState,FormEvent} from 'react';
import {api} from '../../lib/api';
import CommandForm,{evidence,Field,Values} from './CommandForm';

type Supplier={id:string;name:string;destination_approved:boolean;destination_fingerprint:string|null;destination_proposed_by:string|null;cutoff:string;claim_days:number;active:boolean};
type Product={id:string;supplier_id:string;title:string;stock:number|null;last_inventory_at:string};
type Listing={id:string;marketplace:string;price:number;required_price:number;fee:number;margin:string;fee_rate:string;desired_state:string;remote_state:string;last_inventory_at:string};
type Setup={suppliers:Supplier[];products:Product[];listings:Listing[];profiles:{id:string;name:string;supplier_id:string}[];cash:{bank_balance:number}};
const priceFields=[['supplier_sku','공급사SKU'],['title','상품명'],['cost','원가'],['shipping','배송비'],['stock','재고'],['category','분류'],['origin','원산지'],['tax_type','과세구분'],['weight_grams','중량g'],['grade','등급'],['unit','단위']];
const orderFields=[['supplier_order_id','발주ID'],['marketplace_order_id','마켓주문ID'],['supplier_sku','공급사SKU'],['quantity','수량'],['recipient','수령인'],['phone','전화번호'],['postal_code','우편번호'],['address1','주소'],['address2','상세주소']];
const shipmentFields=[['supplier_order_id','발주ID'],['marketplace_order_id','마켓주문ID'],['courier','택배사'],['tracking','송장번호']];
const markets=[{value:'coupang',label:'쿠팡'},{value:'temu',label:'Temu'},{value:'aliexpress',label:'AliExpress'}];

function ProfileForm({suppliers,onSaved}:{suppliers:Supplier[];onSaved:()=>Promise<void>}){
  const [message,setMessage]=useState('');
  async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const d=new FormData(e.currentTarget);
    const mapping:Record<string,unknown>={sheet:d.get('sheet'),header_row:Number(d.get('header_row')),defaults:{},columns:{},order_columns:{},shipment_columns:{}};
    const columns:Record<string,string>={},defaults:Record<string,string|number>={};
    for(const [key] of priceFields){const column=String(d.get('price-'+key)??'');if(column)columns[key]=column;else {const v=String(d.get('default-'+key)??'');defaults[key]=['cost','shipping','stock','weight_grams'].includes(key)?Number(v):v;}}
    mapping.columns=columns;mapping.defaults=defaults;
    for(const [name,fields] of [['order_columns',orderFields],['shipment_columns',shipmentFields]] as const)mapping[name]=Object.fromEntries(fields.map(([key])=>[key,d.get(name+'-'+key)]));
    try{await api('/v1/profiles',{method:'POST',body:JSON.stringify({supplier_id:d.get('supplier_id'),name:d.get('name'),mapping})});setMessage('프로필 생성 완료');await onSaved();}
    catch(e){setMessage(String(e));}
  }
  return <form aria-label="Excel 프로필 생성" className="supplier-form" onSubmit={submit}><h3>3. Excel 프로필</h3><p>공급사의 실제 열 이름을 입력하세요. 가격 열 이름을 비우면 직접 입력한 기본값을 사용합니다. 이 기본 매핑은 특정 공급사의 공식 양식이 아닙니다.</p>
    <label>프로필 공급사<select name="supplier_id" required>{suppliers.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
    <label>프로필 이름<input name="name" required maxLength={100}/></label><label>시트 이름<input name="sheet" defaultValue="Sheet1" required/></label><label>헤더 행<input name="header_row" type="number" defaultValue={1} min={1} max={20} required/></label>
    <table><thead><tr><th>가격 필드</th><th>열 이름</th><th>기본값 (열 미사용 시)</th></tr></thead><tbody>{priceFields.map(([key,label])=><tr key={key}><td>{label}</td><td><input aria-label={`${label} 가격 열`} name={'price-'+key} defaultValue={label}/></td><td><input aria-label={`${label} 기본값`} name={'default-'+key}/></td></tr>)}</tbody></table>
    {([['order_columns','발주',orderFields],['shipment_columns','송장',shipmentFields]] as const).map(([name,title,fields])=><details key={name}><summary>{title} 열 매핑</summary>{fields.map(([key,label])=><label key={key}>{title} {label}<input name={name+'-'+key} defaultValue={label} required/></label>)}</details>)}
    <button>Excel 프로필 생성</button>{message&&<p role="status">{message}</p>}
  </form>;
}

export default function SetupPanel({role,onFiles,onIntake}:{role:string;onFiles:()=>void;onIntake:()=>void}){
  const [data,setData]=useState<Setup|null>(null),[error,setError]=useState('');
  const refresh=useCallback(async()=>{try{setData(await api<Setup>('/v1/setup'));}catch(e){setError(String(e));}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  if(!data)return <p>{error||'초기 설정 조회 중…'}</p>;
  const suppliers=data.suppliers.map(s=>({value:s.id,label:s.name}));
  const supplier:Field={name:'supplier_id',label:'공급사',options:suppliers};
  const withoutSupplier=(v:Values)=>{const {supplier_id,...rest}=v;return rest;};
  return <section aria-label="초기 설정"><h2>초기 설정</h2><p>관리자/운영자 → 공급사 → Excel 프로필 → 가격표 → 판매상품 → 지급처 → 확인된 자금 → 주문 가져오기</p>
    <ul>{!data.suppliers.length&&<li>공급사 생성 필요</li>}{!data.products.length&&<li>공급사 가격표 없음</li>}{!data.listings.length&&<li>마켓 listing 미생성</li>}{data.suppliers.filter(s=>!s.destination_approved).map(s=><li key={s.id}>{s.name}: 지급처 2인 승인 필요</li>)}{!data.cash.bank_balance&&<li>확인된 자금 없음</li>}</ul>
    {role==='admin'&&<><CommandForm title="1. 로컬 계정 생성" fields={[{name:'username',label:'새 아이디'},{name:'password',label:'새 비밀번호 (12자 이상)',type:'password'},{name:'role',label:'역할',options:['viewer','operator','admin'].map(x=>({value:x,label:x}))}]} path="/v1/users" onSaved={refresh}/>
    <CommandForm title="2. 공급사 생성" fields={[{name:'name',label:'공급사 이름'},{name:'cutoff',label:'마감 시간 (HH:MM)',value:'14:00'},{name:'claim_days',label:'클레임 기한 (일)',type:'number',min:1,value:3}]} body={v=>({...v,mode:'excel',active:true})} path="/v1/suppliers" onSaved={refresh}/>
    {data.suppliers.map(s=><details key={s.id}><summary>{s.name} · 운영 설정 변경</summary><CommandForm title={`${s.name} 설정 저장`} method="PUT" path={`/v1/suppliers/${s.id}`}
      fields={[{name:'name',label:'공급사 이름',value:s.name},{name:'cutoff',label:'마감 시간 (HH:MM)',value:s.cutoff},{name:'claim_days',label:'클레임 기한 (일)',type:'number',min:1,value:s.claim_days},
        {name:'active',label:'공급사 활성 상태',value:String(s.active),options:[{value:'true',label:'활성'},{value:'false',label:'중지'}]}]}
      body={v=>({...v,mode:'excel',active:v.active==='true'})} onSaved={refresh}/></details>)}
    <ProfileForm suppliers={data.suppliers} onSaved={refresh}/></>}
    {role!=='viewer'&&<><h3>4. 공급사 가격표 업로드</h3><button onClick={onFiles}>파일 화면에서 가격표 가져오기</button>
    <CommandForm title="5. 판매상품 구성" path="/v1/listings" fields={[{name:'supplier_product_id',label:'공급사 상품',options:data.products.map(p=>({value:p.id,label:p.title}))},{name:'marketplace',label:'마켓',options:markets},{name:'fee_rate',label:'확인한 수수료율 (예: 0.10)'}]} onSaved={refresh}/></>}
    {role==='admin'&&<><CommandForm title="6. 지급처 제안" path={v=>`/v1/suppliers/${v.supplier_id}/destination/propose`} fields={[supplier,{name:'destination_fingerprint',label:'검증 대상 지급처 지문 SHA-256'}]} body={withoutSupplier} onSaved={refresh}/>
    <CommandForm title="다른 관리자 지급처 승인" notice="제안한 관리자와 다른 계정으로 로그인해야 합니다. 은행 계좌 평문을 입력하지 마세요." path={v=>`/v1/suppliers/${v.supplier_id}/destination/approve`} fields={[supplier,{name:'destination_fingerprint',label:'승인할 지급처 지문 SHA-256'},{name:'verified_reference',label:'지급처 외부 검증 참조'}]} body={withoutSupplier} onSaved={refresh}/>
    <CommandForm title="7. 확인된 은행 개시 잔액" notice="빈 원장에 한 번만 기록합니다. 외부 은행 잔액과 대조한 금액입니다. 송금하지 않습니다." path="/v1/funds/opening-bank" fields={[{name:'amount',label:'확인한 개시 잔액 (원)',type:'number',min:1},...evidence]} onSaved={refresh}/>
    <CommandForm title="공급사 예치금 확인" notice="외부 입금 완료 증빙을 기록하여 은행 자금에서 해당 공급사 예치금으로 재분류합니다." path={v=>`/v1/suppliers/${v.supplier_id}/deposit`} fields={[supplier,{name:'amount',label:'확인된 예치금 (원)',type:'number',min:1},...evidence]} body={withoutSupplier} onSaved={refresh}/></>}
    <h3>판매상품 상태</h3><table><thead><tr><th>마켓</th><th>최소가 / 설정가</th><th>수수료 / 마진율</th><th>재고 확인 시각</th><th>내부 / 원격</th></tr></thead><tbody>{data.listings.map(l=><tr key={l.id}><td>{l.marketplace}</td><td>{l.required_price} / {l.price}</td><td>{l.fee} / {l.margin}</td><td>{l.last_inventory_at}</td><td>{l.desired_state} / {l.remote_state}</td></tr>)}</tbody></table>
    {role!=='viewer'&&<CommandForm title="외부 판매상품 확인 및 활성화" notice="마켓에서 실제 등록과 가격을 확인한 후 입력하세요. 재고·마진·위험·지급처·자금 검사를 통과해야 활성화됩니다." path={v=>`/v1/listings/${v.listing_id}/external-activation`} fields={[{name:'listing_id',label:'판매상품',options:data.listings.map(l=>({value:l.id,label:`${l.marketplace} ${l.id}`}))},{name:'external_id',label:'실제 마켓 상품 ID'},{name:'price',label:'확인한 판매가',type:'number',min:1},...evidence]} body={v=>{const {listing_id,...rest}=v;return rest;}} onSaved={refresh}/>}
    <h3>8. 주문 가져오기</h3><button onClick={onIntake}>표준 주문 XLSX 가져오기</button>
  </section>;
}
