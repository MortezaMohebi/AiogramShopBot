/** Render actual loading boundaries and their shared client component on the server. */
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

const root=fileURLToPath(new URL("..",import.meta.url));
const nativeRequire=createRequire(import.meta.url);
const cache=new Map<string,Record<string,unknown>>();
/** Compile repository TSX only; React, theme and orb packages run unchanged. */
function load(relative:string):Record<string,unknown> {
  const stem=path.resolve(root,relative);
  const filename=[stem,stem+".tsx",stem+".ts"].find(existsSync);
  assert(filename,relative);
  const saved=cache.get(filename);if(saved)return saved;
  const evaluated={exports:{} as Record<string,unknown>};cache.set(filename,evaluated.exports);
  const code=ts.transpileModule(readFileSync(filename,"utf8"),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  runInNewContext(code,{module:evaluated,exports:evaluated.exports,require:(name:string)=>{
    if(name.startsWith("@/"))return load(name.slice(2));
    if(name.startsWith("."))return load(path.relative(root,path.resolve(path.dirname(filename),name)));
    return nativeRequire(name);
  }});
  return evaluated.exports;
}
for(const route of ["app/(console)/loading.tsx","app/(console)/studio/workflows/loading.tsx","app/(console)/studio/runtime/loading.tsx","app/(console)/studio/mcp/loading.tsx"]) {
  test(`${route} exposes one readable status and a decorative, unfocusable orb`,()=>{
    const Component=load(route).default as ComponentType;
    const html=renderToStaticMarkup(createElement(Component));
    assert.equal((html.match(/<canvas\b/g)||[]).length,1,"loading must include the requested orb");
    assert.match(html,/<canvas[^>]*aria-hidden="true"/);
    assert.match(html,/<canvas[^>]*tabindex="-1"/);
    assert.equal((html.match(/role="status"/g)||[]).length,1);
    assert.match(html,/در حال/);
    assert(!/role="alert"/.test(html),"loading is not an error");
  });
}
