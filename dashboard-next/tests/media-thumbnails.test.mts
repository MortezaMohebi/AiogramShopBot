/** Render the real product-media panel without executing browser effects or mutations. */
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const root=fileURLToPath(new URL("..",import.meta.url)),nativeRequire=createRequire(import.meta.url);
const cache=new Map<string,Record<string,unknown>>();
function load(relative:string):Record<string,unknown> {
 const stem=path.resolve(root,relative),filename=[stem,stem+".tsx",stem+".ts"].find(existsSync);assert(filename,relative);
 const previous=cache.get(filename);if(previous)return previous;
 const evaluated={exports:{} as Record<string,unknown>};cache.set(filename,evaluated.exports);
 const code=ts.transpileModule(readFileSync(filename,"utf8"),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 runInNewContext(code,{module:evaluated,exports:evaluated.exports,require:(name:string)=>{
  if(name==="next/navigation")return {useRouter:()=>({refresh(){}})};
  if(name.startsWith("@/"))return load(name.slice(2));
  if(name.startsWith("."))return load(path.relative(root,path.resolve(path.dirname(filename),name)));
  return nativeRequire(name);
 }});return evaluated.exports;
}
const Panel=load("components/blocks/product-media-panel").ProductMediaPanel as ComponentType<{productId:number;initial:unknown[]}>;
const file=(id:number,mime_type:string,kind:string)=>({id,filename:`file-${id}`,kind,mime_type,size_bytes:500,caption:null,is_published:false});
test("product images reserve a skeleton and defer the authenticated URL until hydration",()=>{
 const html=renderToStaticMarkup(createElement(Panel,{productId:1,initial:[file(7,"image/png","photo")]}));
 assert.match(html,/data-media-thumbnail/);
 assert.match(html,/data-src="\/api\/admin\/preview\/product\/7"/);
 assert.match(html,/data-state="loading"/);
 // A direct preview link remains usable independently of thumbnail loading.
 assert.match(html,/href="\/api\/admin\/preview\/product\/7"/);
 assert(!/<img[^>]*src="https?:/.test(html));
});
test("non-image records keep their original file preview without an image request",()=>{
 const html=renderToStaticMarkup(createElement(Panel,{productId:1,initial:[file(8,"application/pdf","document"),file(9,"video/mp4","video")]}));
 assert(!html.includes("data-media-thumbnail"));
 for(const id of [8,9])assert(html.includes(`href="/api/admin/preview/product/${id}"`));
});
test("untrusted SVG is not rendered as an inline thumbnail",()=>{
 const html=renderToStaticMarkup(createElement(Panel,{productId:1,initial:[file(10,"image/svg+xml","photo")]}));
 assert(!html.includes("data-media-thumbnail"));
});
