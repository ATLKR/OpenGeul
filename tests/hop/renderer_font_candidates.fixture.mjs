export const state = {host:false,results:[],calls:[],singleCalls:0,entries:[],nativeCalls:[],readPaths:[]};
export function hasHostFontProvider(){return state.host;}
export function getHostFontState(){return {active:state.host,generation:1,count:0,lastError:null};}
export function changedLocalFontNames(){return [];}
export function resolveRendererLocalFontCandidates(name,style){state.calls.push({name,style});return state.results;}
export function resolveRendererLocalFont(){state.singleCalls++;return null;}
export function resetLocalFontsForTests(){state.host=false;state.results=[];state.calls=[];state.singleCalls=0;state.entries=[];state.nativeCalls=[];state.readPaths=[];}
export async function invoke(command,args){state.nativeCalls.push(command);if(command==='list_local_fonts')return state.entries;if(command==='read_local_font'&&state.entries.some(e=>e.path===args?.path)){state.readPaths.push(args.path);return [1,2,3,4];}throw new Error('Unexpected or unlisted unit native read');}
