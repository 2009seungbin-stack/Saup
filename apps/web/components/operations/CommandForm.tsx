'use client';
import {FormEvent, useState} from 'react';
import {api} from '../../lib/api';

export type Field = {name:string;label:string;type?:'number'|'password'|'checkbox';value?:string|number;min?:number;required?:boolean;options?:{value:string;label:string}[]};
export type Values = Record<string,string|number|boolean>;
export const evidence:Field[] = [
  {name:'reference',label:'외부 증빙 참조 번호'},
  {name:'evidence_hash',label:'증빙 SHA-256'},
  {name:'confirmed',label:'해당 외부 처리 / 잔액을 실제 증빙과 대조하여 확인했습니다.',type:'checkbox'},
];
export default function CommandForm({title,fields,path,body,onSaved,notice,method='POST'}:{title:string;fields:Field[];
  path:string|((v:Values)=>string);body?:(v:Values)=>unknown;onSaved:()=>Promise<void>;notice?:string;method?:string}) {
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
  async function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;const data=new FormData(form);const values:Values={};
    for(const f of fields)values[f.name]=f.type==='checkbox'?data.get(f.name)==='on':f.type==='number'?Number(data.get(f.name)):String(data.get(f.name)??'');
    setBusy(true);setMessage('');
    try{await api(typeof path==='string'?path:path(values),{method,body:JSON.stringify(body?body(values):values)});
      setMessage('기록 완료');form.reset();await onSaved();}
    catch(e){setMessage(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  return <form className="supplier-form" aria-label={title} onSubmit={submit}><h3>{title}</h3>{notice&&<p className="notice">{notice}</p>}
    <fieldset disabled={busy}>{fields.map(f=><label key={f.name}>{f.label}{f.options?
      <select name={f.name} aria-label={f.label} defaultValue={f.value??''} required><option value="">선택하세요</option>{f.options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select>:
      <input name={f.name} aria-label={f.label} type={f.type??'text'} defaultValue={f.type==='checkbox'?undefined:f.value} required={f.required!==false}
        min={f.type==='number'?(f.min??0):undefined} step={f.type==='number'?1:undefined} autoComplete={f.type==='password'?'new-password':'off'}
        pattern={f.name==='evidence_hash'?'[a-f0-9]{64}':undefined}/>}</label>)}<button className="primary">{title}</button></fieldset>
    {message&&<p role="status">{message}</p>}
  </form>;
}
