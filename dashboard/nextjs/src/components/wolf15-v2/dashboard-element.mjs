import {normalizeSnapshot,emptySnapshot,parseRoute,freshness} from './model.mjs';
import {renderShell,renderSource} from './render.mjs';
import {styles} from './theme.mjs';

// No network or credentials in this element. Host application owns session + data.
export class Wolf15Dashboard extends HTMLElement {
  static observedAttributes=['route','can-refresh','can-logout','external-router','route-base'];
  constructor(){
    super();this.attachShadow({mode:'open'});this.model=emptySnapshot();
    this.ui={query:'',filter:'all',sort:'symbol',tablePage:1,menu:false,source:null};
    this.onHash=()=>{if(!this.hasAttribute('external-router'))this.draw();};
    this.onClick=this.handleClick.bind(this);this.onInput=this.handleInput.bind(this);this.onKey=this.handleKey.bind(this);
    // React may set a property before customElements.define finishes.
    if(Object.prototype.hasOwnProperty.call(this,'snapshot')){const v=this.snapshot;delete this.snapshot;this.snapshot=v;}
  }
  set snapshot(v){this.model=normalizeSnapshot(v);if(['session_expired','forbidden'].includes(this.model.connection)){this.ui.source=null;this.ui.query='';}if(this.isConnected)this.draw();}
  get snapshot(){return this.model;}
  connectedCallback(){
    this.shadowRoot.addEventListener('click',this.onClick);this.shadowRoot.addEventListener('input',this.onInput);this.shadowRoot.addEventListener('change',this.onInput);this.shadowRoot.addEventListener('keydown',this.onKey);window.addEventListener('hashchange',this.onHash);
    this.draw();this.clock=setInterval(()=>{if(!document.hidden)this.shadowRoot.querySelectorAll('[data-freshness]').forEach(el=>{el.textContent=freshness(this.model[el.dataset.freshness]);});},30000);
  }
  disconnectedCallback(){clearInterval(this.clock);window.removeEventListener('hashchange',this.onHash);this.shadowRoot.removeEventListener('click',this.onClick);this.shadowRoot.removeEventListener('input',this.onInput);this.shadowRoot.removeEventListener('change',this.onInput);this.shadowRoot.removeEventListener('keydown',this.onKey);}
  attributeChangedCallback(){if(this.isConnected)this.draw();}
  route(){return parseRoute(this.hasAttribute('external-router')?this.getAttribute('route'):window.location.hash);}
  draw(focusHeading=false){
    const focused=this.shadowRoot.activeElement;const search=focused?.hasAttribute('data-search');const start=search?focused.selectionStart:null;
    const route=this.route();
    const connected=this.model.connection==='connected';
    this.shadowRoot.innerHTML=`<style>${styles}</style>`+renderShell(this.model,route,this.ui,{canRefresh:connected&&this.getAttribute('can-refresh')==='true'&&!this.model.refreshing,canLogout:connected&&this.getAttribute('can-logout')==='true'})+(this.ui.source?renderSource(this.model,this.ui.source):'');
    if(this.hasAttribute('external-router')){
      const base=this.getAttribute('route-base');
      if(base&&base.startsWith('/')&&!base.startsWith('//')&&!/[?#\\]/.test(base))this.shadowRoot.querySelectorAll('a[data-route]').forEach(a=>{a.href=base.replace(/\/$/,'')+'/'+a.dataset.route;});
    }
    if(search){const input=this.shadowRoot.querySelector('[data-search]');input?.focus();input?.setSelectionRange(start,start);}
    if(focusHeading)this.shadowRoot.querySelector('h1')?.focus();
    const panel=route.params.get('panel');if(panel&&!search)this.shadowRoot.getElementById(`panel-${panel}`)?.scrollIntoView({block:'nearest'});
  }
  emit(name,detail={}){this.dispatchEvent(new CustomEvent(`wolf15:${name}`,{detail,bubbles:true,composed:true}));}
  navigate(route){this.ui.menu=false;this.ui.source=null;
    if(this.hasAttribute('external-router'))this.emit('navigate',{route});else {window.location.hash='/'+route;this.draw(true);}
  }
  handleClick(event){
    if(event.target.classList?.contains('sheet')){this.closeSheet();return;}
    const el=event.target.closest?.('a,button');if(!el)return;
    if(el.hasAttribute('data-route')){if((event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)&&(!this.hasAttribute('external-router')||this.hasAttribute('route-base')))return;event.preventDefault();this.navigate(el.dataset.route);return;}
    if(el.dataset.filter){this.ui.filter=el.dataset.filter;this.ui.tablePage=1;this.draw();this.shadowRoot.querySelector(`[data-filter="${this.ui.filter}"]`)?.focus();return;}
    if(el.dataset.pageStep){this.ui.tablePage=Math.max(1,this.ui.tablePage+Number(el.dataset.pageStep));this.draw();return;}
    if(el.dataset.source){this.ui.source=el.dataset.source;this.draw();this.shadowRoot.querySelector('[data-action="close-sheet"]')?.focus();return;}
    switch(el.dataset.action){
      case 'refresh':this.emit('refresh');break;
      case 'logout':this.snapshot={...emptySnapshot(),connection:'session_expired'};this.emit('logout');break;
      case 'menu':this.ui.menu=!this.ui.menu;this.draw();this.shadowRoot.querySelector('.sidebar.open .nav-link')?.focus();break;
      case 'close-menu':this.closeMenu();break;
      case 'close-sheet':this.closeSheet();break;
    }
  }
  closeMenu(){this.ui.menu=false;this.draw();this.shadowRoot.querySelector('[data-action="menu"]')?.focus();}
  closeSheet(){const source=this.ui.source;this.ui.source=null;this.draw();this.shadowRoot.querySelector(`[data-source="${source}"]`)?.focus();}
  handleInput(event){const el=event.target;
    if(el.hasAttribute('data-search')&&event.type==='input'){this.ui.query=el.value;this.ui.tablePage=1;this.draw();}
    if(el.hasAttribute('data-sort')&&event.type==='change'){this.ui.sort=el.value;this.draw();this.shadowRoot.querySelector('[data-sort]')?.focus();}
    if(el.hasAttribute('data-revision')&&event.type==='change'){const r=this.route();r.params.set('revision',el.value);this.navigate('5s-cr?'+r.params.toString());}
  }
  handleKey(event){
    if(event.key==='Escape'){if(this.ui.source)this.closeSheet();else if(this.ui.menu)this.closeMenu();return;}
    if(event.key!=='Tab')return;
    const box=this.ui.source?this.shadowRoot.querySelector('.sheet-content'):this.ui.menu?this.shadowRoot.querySelector('.sidebar.open'):null;
    if(!box)return;const focusable=[...box.querySelectorAll('a,button:not(:disabled),input:not(:disabled),select')];
    const first=focusable[0],last=focusable.at(-1);const current=this.shadowRoot.activeElement;
    if(event.shiftKey&&current===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&current===last){event.preventDefault();first?.focus();}
  }
}
if(!customElements.get('wolf15-dashboard'))customElements.define('wolf15-dashboard',Wolf15Dashboard);
