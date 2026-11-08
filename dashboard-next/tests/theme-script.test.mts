/** Server needs the anti-flash script; a client-only mount must not create one. */
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import ts from "typescript";
import { patchNextThemes } from "../scripts/patch-next-themes.mjs";
const require=createRequire(import.meta.url);
const distribution=path.dirname(require.resolve("next-themes"));
function render(client:boolean,entry:string){
 const evaluated={exports:{} as {ThemeProvider:ComponentType<{children?:unknown}>}};
 const code=ts.transpileModule(readFileSync(path.join(distribution,entry),"utf8"),{compilerOptions:{allowJs:true,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 runInNewContext(code,{module:evaluated,exports:evaluated.exports,require,...(client?{window:{},localStorage:{getItem:()=>"dark"}}:{})});
 return renderToStaticMarkup(createElement(evaluated.exports.ThemeProvider,null,"Theme child"));
}
for(const entry of ["index.js","index.mjs"]){
 test(`${entry}: SSR retains the pre-hydration theme script`,()=>{assert(render(false,entry).includes("<script"));});
 test(`${entry}: fresh client mount preserves children without rendering a script tag`,()=>{const html=render(true,entry);assert(html.includes("Theme child"));assert(!html.includes("<script"));});
}
test("install patch is repeatable and rejects unknown vendor bytes before any writes",()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),"theme-patch-"));
 try{
  mkdirSync(path.join(root,"dist"));writeFileSync(path.join(root,"package.json"),JSON.stringify({name:"next-themes",version:"0.4.6"}));
  const originals=new Map<string,string>();
  for(const entry of ["index.js","index.mjs"]){
   const source=readFileSync(path.join(distribution,entry),"utf8").replace('if(typeof window!=="undefined")return null;',"");
   originals.set(entry,source);writeFileSync(path.join(root,"dist",entry),source);
  }
  writeFileSync(path.join(root,"dist/index.mjs"),"unreviewed vendor bytes");
  assert.throws(()=>patchNextThemes(root),/Unrecognized/);
  assert.equal(readFileSync(path.join(root,"dist/index.js"),"utf8"),originals.get("index.js"));
  writeFileSync(path.join(root,"dist/index.mjs"),originals.get("index.mjs")!);
  assert.equal(patchNextThemes(root),2);assert.equal(patchNextThemes(root),0);
  writeFileSync(path.join(root,"package.json"),JSON.stringify({name:"next-themes",version:"9.0.0"}));
  assert.throws(()=>patchNextThemes(root),/requires reviewed/);
 }finally{rmSync(root,{recursive:true,force:true});}
});
