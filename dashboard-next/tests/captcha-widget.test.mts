/** Exercise the real widget lifecycle with offline provider SDK boundaries. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const compiled=ts.transpileModule(readFileSync(new URL("../components/blocks/captcha-challenge.tsx",import.meta.url),"utf8"),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText;
type Widget = {size?:string; callback:(token:string)=>void; "expired-callback":()=>void; "error-callback":()=>void};
type Element = {type:unknown;props:Record<string,unknown>};

/** Mount effects and refs while substituting only browser DOM and provider I/O. */
function widget(provider:"turnstile"|"recaptcha_v2") {
  const states:unknown[]=[],refs:{current:unknown}[]=[];
  let stateIndex=0,refIndex=0,previous:unknown[]|undefined;
  const effects:(()=>unknown)[]=[];
  const handle:{current?:{getToken:()=>Promise<string|null>}}={};
  const renders:Widget[]=[];
  const Script=Symbol("NextScript");
  const dom=()=>({replaceChildren(){}});
  const sdk={render:(_target:unknown,options:Widget)=>{renders.push(options);return provider==="turnstile"?"synthetic-widget":1;},ready:(callback:()=>void)=>callback(),reset(){},remove(){}};
  const evaluatedModule={exports:{} as {CaptchaChallenge:(props:unknown,ref:unknown)=>Element}};
  runInNewContext(compiled,{
    module:evaluatedModule,exports:evaluatedModule.exports,document:{createElement:dom},window:{turnstile:sdk,grecaptcha:sdk},
    require:(name:string)=>{
      if(name==="next/script")return {__esModule:true,default:Script};
      if(name==="react/jsx-runtime")return {jsx:(type:unknown,props:Record<string,unknown>)=>({type,props}),jsxs:(type:unknown,props:Record<string,unknown>)=>({type,props})};
      assert.equal(name,"react");return {
        forwardRef:(component:unknown)=>component,
        useState:(initial:unknown)=>{const index=stateIndex++;if(!(index in states))states[index]=initial;return [states[index],(next:unknown)=>{states[index]=next;}];},
        useRef:(initial:unknown)=>{const index=refIndex++;return refs[index]??(refs[index]={current:initial});},
        useEffect:(effect:()=>unknown,deps:unknown[])=>{if(!previous||deps.some((value,index)=>!Object.is(value,previous?.[index]))){effects.push(effect);previous=deps;}},
        useImperativeHandle:(_ref:unknown,factory:()=>unknown)=>{Object.assign(handle,{current:factory()});},
      };
    },
  });
  let ready:(()=>void)|undefined;
  function render() {
    stateIndex=0;refIndex=0;
    const tree=evaluatedModule.exports.CaptchaChallenge({config:{provider,siteKey:"synthetic-site-key"}},handle);
    function visit(node:unknown) {
      if(Array.isArray(node)){node.forEach(visit);return;}
      if(!node||typeof node!=="object"||!("props" in node))return;
      const element=node as Element;
      if(element.type===Script)ready=element.props.onReady as ()=>void;
      const ref=element.props.ref as {current:unknown}|undefined;
      if(ref&&!ref.current)ref.current=dom();
      visit(element.props.children);
    }
    visit(tree);effects.splice(0).forEach((effect)=>effect());
  }
  render();assert(ready);ready();render();
  return {renders,render,getToken:()=>handle.current!.getToken()};
}

for(const provider of ["turnstile","recaptcha_v2"] as const) {
  test(`${provider} requests compact layout and preserves the provider token`,async()=>{
    const current=widget(provider);assert.equal(current.renders.length,1);
    assert.equal(current.renders[0].size,"compact");
    current.renders[0].callback("synthetic-provider-proof");current.render();
    assert.equal(await current.getToken(),"synthetic-provider-proof");
  });
  test(`${provider} never accepts an expired or failed widget token`,async()=>{
    const current=widget(provider);
    current.renders[0].callback("synthetic-provider-proof");current.render();
    current.renders[0]["expired-callback"]();current.render();
    await assert.rejects(current.getToken(),/captcha_required/);
    current.renders[0]["error-callback"]();current.render();
    await assert.rejects(current.getToken(),/captcha_unavailable/);
  });
}
