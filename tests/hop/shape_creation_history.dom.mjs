// Deliberately small DOM boundary for command-routing tests. This owns only
// elements, event bubbling, focus and geometry; no editor/WASM/history behavior.
const NativeEvent=globalThis.Event;
const NativeEventTarget=globalThis.EventTarget;
const originalTarget=Symbol('originalTarget');
const blankRect=()=>({x:0,y:0,left:0,top:0,right:0,bottom:0,width:0,height:0});

class DomEvent extends NativeEvent {
  constructor(type,options={}){super(type,{cancelable:true,...options});}
}
class DomMouseEvent extends DomEvent {
  constructor(type,options={}){super(type,options);for(const [key,value] of Object.entries({button:0,buttons:0,clientX:0,clientY:0,shiftKey:false,ctrlKey:false,metaKey:false,altKey:false}))this[key]=options[key]??value;}
}
class DomKeyboardEvent extends DomEvent {
  constructor(type,options={}){super(type,options);for(const [key,value] of Object.entries({key:'',code:'',shiftKey:false,ctrlKey:false,metaKey:false,altKey:false,isComposing:false,keyCode:0}))this[key]=options[key]??value;}
}
function styleObject(){
  const style={setProperty(name,value){this[name]=value;},removeProperty(name){delete this[name];}};
  let text='';
  Object.defineProperty(style,'cssText',{get:()=>text,set(value){text=String(value);for(const declaration of text.split(';')){
    const index=declaration.indexOf(':');if(index<0)continue;
    const name=declaration.slice(0,index).trim().replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());style[name]=declaration.slice(index+1).trim();
  }} });
  return style;
}
class DomElement extends NativeEventTarget {
  constructor(tag,owner){
    super();this.tagName=tag.toUpperCase();this.localName=tag.toLowerCase();this.ownerDocument=owner;
    this.parentElement=null;this.children=[];this.style=styleObject();this.dataset={};this.attributes=new Map();
    this.className='';this.id='';this.value='';this.checked=false;this.disabled=false;this.clientWidth=0;this.clientHeight=0;
    this.scrollLeft=0;this.scrollTop=0;this._text='';
    this.classList={contains:name=>this.className.split(/\s+/).includes(name),add:(...names)=>{this.className=[...new Set([...this.className.split(/\s+/).filter(Boolean),...names])].join(' ');},remove:(...names)=>{this.className=this.className.split(/\s+/).filter(name=>!names.includes(name)).join(' ');},toggle:(name,force)=>{const add=force??!this.classList.contains(name);add?this.classList.add(name):this.classList.remove(name);return add;}};
  }
  get parentNode(){return this.parentElement;}
  get childNodes(){return this.children;}
  get isConnected(){return Boolean(this.ownerDocument?.contains(this));}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set textContent(text){this._text=String(text);this.children=[];}
  appendChild(child){child.remove?.();child.parentElement=this;this.children.push(child);return child;}
  append(...nodes){for(const node of nodes)this.appendChild(typeof node==='string'?this.ownerDocument.createTextNode(node):node);}
  prepend(...nodes){for(const node of nodes.reverse()){node.remove?.();node.parentElement=this;this.children.unshift(node);}}
  replaceChildren(...nodes){for(const child of this.children)child.parentElement=null;this.children=[];this._text='';this.append(...nodes);}
  remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}}
  contains(node){return node===this||this.children.some(child=>child.contains?.(node));}
  setAttribute(name,value){
    value=String(value);this.attributes.set(name,value);
    if(name==='class')this.className=value;else if(name==='style')this.style.cssText=value;else if(name==='id')this.id=value;
    else if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value;
  }
  getAttribute(name){return name==='class'?this.className:name==='id'?this.id:this.attributes.get(name)??null;}
  removeAttribute(name){this.attributes.delete(name);}
  matches(selector){
    const tag=/^[\w-]+/.exec(selector)?.[0];if(tag&&tag.toLowerCase()!==this.localName)return false;
    for(const [,prefix,value] of selector.matchAll(/([.#])([\w-]+)/g))if(prefix==='#'?this.id!==value:!this.classList.contains(value))return false;
    for(const [,name,,value] of selector.matchAll(/\[([^\]=]+)(?:=(['"]?)([^\]'"\]]*)\2)?\]/g)){
      const actual=name.startsWith('data-')?this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]:this.getAttribute(name);
      if(value===undefined?actual==null:String(actual)!==value)return false;
    }
    return true;
  }
  closest(selector){for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
  querySelectorAll(selector){
    const parts=selector.split(',').map(part=>part.trim()),result=[];
    const visit=node=>{for(const child of node.children){if(parts.some(part=>child.matches(part)))result.push(child);visit(child);}};visit(this);return result;
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]??null;}
  dispatchEvent(event){
    if(!event[originalTarget]){event[originalTarget]=this;Object.defineProperty(event,'target',{value:this,configurable:true});}
    super.dispatchEvent(event);
    if(event.bubbles&&!event.cancelBubble&&this.parentElement)this.parentElement.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  click(){this.dispatchEvent(new DomMouseEvent('click',{bubbles:true}));}
  focus(){this.ownerDocument.activeElement=this;}
  blur(){this.dispatchEvent(new DomEvent('blur'));}
  select(){this.selectionStart=0;this.selectionEnd=this.value.length;}
  getBoundingClientRect(){return blankRect();}
  scrollIntoView(){}
}
class DomInput extends DomElement {}
class DomTextarea extends DomElement {}
class DomCanvas extends DomElement {}
class DomDocument extends DomElement {
  constructor(){super('#document',null);this.ownerDocument=this;this.activeElement=null;
    this.documentElement=this.createElement('html');this.body=this.createElement('body');this.appendChild(this.documentElement);this.documentElement.appendChild(this.body);
  }
  createElement(tag){const Constructor=tag==='input'?DomInput:tag==='textarea'?DomTextarea:tag==='canvas'?DomCanvas:DomElement;return new Constructor(tag,this);}
  createElementNS(_namespace,tag){return this.createElement(tag);}
  createTextNode(text){const node=this.createElement('#text');node.textContent=text;return node;}
  getElementById(id){return this.querySelector('#'+id);}
}
export function createShapeHistoryDom(){
  const document=new DomDocument(),window=new NativeEventTarget(),frameTimers=new Set(),intervals=new Set();
  const main=document.createElement('main');document.body.appendChild(main);
  const container=document.createElement('div');container.id='scroll-container';main.appendChild(container);
  const content=document.createElement('div');content.id='scroll-content';container.appendChild(content);
  const canvas=document.createElement('canvas');canvas.className='document-page-canvas';content.appendChild(canvas);
  for(const [id,command] of [['tb-textbox','insert:textbox'],['tb-shape','insert:shape'],['tb-undo','edit:undo'],['tb-redo','edit:redo'],['tb-form','view:form-mode']]){
    const button=document.createElement('button');button.id=id;button.setAttribute('data-cmd',command);main.appendChild(button);
  }
  const storage=new Map();
  Object.assign(window,{document,navigator:{userAgent:'Synthetic shape routing DOM',platform:'Linux',maxTouchPoints:0,language:'ko',languages:['ko']},
    innerWidth:800,innerHeight:1200,HTMLElement:DomElement,Element:DomElement,HTMLInputElement:DomInput,HTMLTextAreaElement:DomTextarea,HTMLCanvasElement:DomCanvas,
    Event:DomEvent,MouseEvent:DomMouseEvent,KeyboardEvent:DomKeyboardEvent,
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)},
    getComputedStyle:element=>element.style,
    requestAnimationFrame(callback){const timer=setTimeout(()=>{frameTimers.delete(timer);callback(performance.now());},16);frameTimers.add(timer);return timer;},
    cancelAnimationFrame(timer){clearTimeout(timer);frameTimers.delete(timer);},
    setInterval(callback,ms){const timer=setInterval(callback,ms);intervals.add(timer);return timer;},
    clearInterval(timer){clearInterval(timer);intervals.delete(timer);},
    close(){for(const timer of frameTimers)clearTimeout(timer);for(const timer of intervals)clearInterval(timer);frameTimers.clear();intervals.clear();},
  });
  window.window=window;document.defaultView=window;
  return {window};
}

// Independent read-only parser for the trusted native-export XML in these tests.
// Reopening still uses the actual HwpDocument parser; this never creates input.
export function parseGeneratedXml(xml){
  if(/<!DOCTYPE|<!ENTITY/.test(xml))throw new Error('Unexpected declaration in native XML');
  const decode=value=>value.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&amp;/g,'&');
  const root={children:[],localName:'#document',attrs:{},text:''},stack=[root];
  for(const token of xml.match(/<[^>]*>|[^<]+/g)??[]){
    if(token.startsWith('<?')||token.startsWith('<!--'))continue;
    if(token.startsWith('</')){const name=token.slice(2,-1).trim();if(stack.pop().name!==name)throw new Error('Native XML tags do not balance');continue;}
    if(token.startsWith('<')){
      const name=/^<([^\s/>]+)/.exec(token)[1];
      const node={name,localName:name.split(':').at(-1),children:[],attrs:{},text:''};
      for(const [,key,value] of token.matchAll(/([^\s=]+)="([^"]*)"/g))node.attrs[key]=decode(value);
      stack.at(-1).children.push(node);if(!token.endsWith('/>'))stack.push(node);
    }else stack.at(-1).text+=decode(token);
  }
  if(stack.length!==1||root.children.length!==1)throw new Error('Native XML root/tag balance differs');
  return root.children[0];
}
